import type { Input } from './types';

export const fields = [
  ['price', '单件售价', 'money'], ['purchase_cost', '采购成本', 'money'], ['domestic_shipping', '国内运费', 'money'],
  ['packaging', '包装成本', 'money'], ['fulfillment_cost', '履约费用', 'money'], ['electronic_fee', '其他固定费用', 'money'],
  ['commission_rate', '平台佣金率', 'rate'], ['payment_rate', '支付费率', 'rate'], ['return_rate', '退货预留比例', 'rate'], ['ad_rate', '广告费用比例', 'rate'],
] as const;
export const labels: Record<string, string> = { currency: '币种', ...Object.fromEntries(fields.map(([key, label]) => [key, label])) };
export type Values = Record<string, string>;
export type FieldErrors = Record<string, string>;
export function fromInput(input: Input): Values {
  return Object.fromEntries(Object.entries(input).map(([key, value]) => [key, value == null ? '' : String(key.endsWith('_rate') ? Number((Number(value) * 100).toPrecision(12)) : value)]));
}
export function validateInput(values: Values): FieldErrors {
  const errors: FieldErrors = {};
  if (values.currency?.trim() && !/^[A-Z]{3}$/.test(values.currency.trim().toUpperCase())) errors.currency = '请输入三位币种代码，例如 CNY。';
  for (const [key, label, type] of fields) {
    const raw = values[key]?.trim();
    if (!raw) continue; // Missing values remain unknown; the calculator returns HOLD.
    const value = Number(raw), min = key === 'price' ? .01 : 0, max = type === 'rate' ? 100 : 1e12;
    if (!Number.isFinite(value) || value < min || value > max) errors[key] = `${label}须为 ${min}–${max}${type === 'rate' ? '%' : ''} 的数值。`;
  }
  return errors;
}
export function toInput(values: Values): Input {
  const errors = validateInput(values);
  if (Object.keys(errors).length) throw Error('invalid_' + Object.keys(errors)[0]);
  const keys = ['currency', ...fields.map(([key]) => key)];
  return Object.fromEntries(keys.filter(key => values[key]?.trim()).map(key => [key, key === 'currency' ? values[key].trim().toUpperCase() : Number(values[key]) / (key.endsWith('_rate') ? 100 : 1)]));
}
export function differences(local: Values, saved: Values) {
  return ['currency', ...fields.map(([key]) => key)].filter(key => (local[key] || '') !== (saved[key] || ''));
}
