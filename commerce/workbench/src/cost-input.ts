import type { Input } from './types';
import { costFields, costFieldByKey } from './cost-contract';
export const fields = costFields.filter(field => field.kind !== 'currency').map(field => [field.key, field.label, field.kind] as const);
export const labels: Record<string, string> = Object.fromEntries(costFields.map(field => [field.key, field.label]));
export type Values = Record<string, string>;
export type FieldErrors = Record<string, string>;
export function fromInput(input: Input): Values {
  return Object.fromEntries(Object.entries(input).map(([key, value]) => [key, value == null ? '' : String(costFieldByKey[key as keyof typeof costFieldByKey]?.kind === 'rate' ? Number((Number(value) * 100).toPrecision(12)) : value)]));
}
export function validateInput(values: Values): FieldErrors {
  const errors: FieldErrors = {};
  if (values.currency?.trim() && !/^[A-Z]{3}$/.test(values.currency.trim().toUpperCase())) errors.currency = '请输入三位币种代码，例如 CNY。';
  for (const [key, label, type] of fields) {
    const raw = values[key]?.trim();
    if (!raw) continue; // Missing values remain unknown; the calculator returns HOLD.
    const field = costFieldByKey[key];
    const value = Number(raw), min = 'minimum' in field ? field.minimum : 0, max = 'maximum' in field ? field.maximum * (type === 'rate' ? 100 : 1) : 0;
    if (!Number.isFinite(value) || value < min || value > max) errors[key] = `${label}须为 ${min}–${max}${type === 'rate' ? '%' : ''} 的数值。`;
  }
  return errors;
}
export function toInput(values: Values): Input {
  const errors = validateInput(values);
  if (Object.keys(errors).length) throw Error('invalid_' + Object.keys(errors)[0]);
  const keys = costFields.map(field => field.key);
  return Object.fromEntries(keys.filter(key => values[key]?.trim()).map(key => [key, key === 'currency' ? values[key].trim().toUpperCase() : Number(values[key]) / (costFieldByKey[key].kind === 'rate' ? 100 : 1)]));
}
export function differences(local: Values, saved: Values) {
  return costFields.map(field => field.key).filter(key => (local[key] || '') !== (saved[key] || ''));
}
