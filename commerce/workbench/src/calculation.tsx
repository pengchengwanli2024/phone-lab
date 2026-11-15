import { createContext, useContext, useId, type ReactNode } from 'react';
import { createGenerativeUI } from '@copilotkit/react-core/v2/generative-ui/native';
import type { Calculation, Input } from './types';
import { Badge, Button, Empty, Money, Panel } from './ui';
import { fields, labels, type Values, type FieldErrors } from './cost-input';
import { catalogId, costFieldByKey, costFieldByNode, costNodes, registerCostComponents, type CostFieldKey } from './cost-contract';
import { CostNodeIdentity, costSlotNodes } from './cost-binding';
export { catalogId } from './cost-contract';
const breakdownLabels: Record<string, string> = { ...labels, commission: '平台佣金', payment: '支付费用', return: '退货预留', ad: '广告费用' };
export { fields, fromInput, toInput, type Values } from './cost-input';
interface FormState { values: Values; onChange: (values: Values) => void; calculate: () => void; save: () => void; busy: boolean; dirty: boolean; bound: boolean; errors: FieldErrors; }
export const CalculationContext = createContext<FormState | null>(null);
function Field({ field, label, setValue }: { field: CostFieldKey; label: string; setValue?: (value: string | number | null) => void }) {
  const state = useContext(CalculationContext), id = useId();
  if (!state) return null;
  const definition = costFieldByKey[field], currency = definition.kind === 'currency', rate = definition.kind === 'rate', error = state.errors[field];
  return <label className="ui-field" htmlFor={id}>{label}{rate ? '（%）' : ''}<input id={id} name={field} type={currency ? 'text' : 'number'} inputMode={currency ? 'text' : 'decimal'} value={state.values[field] ?? ''} placeholder={currency ? '例如 CNY' : '待填写'} maxLength={currency ? 3 : undefined} min={'minimum' in definition ? definition.minimum : undefined} max={'maximum' in definition ? definition.maximum * (rate ? 100 : 1) : undefined} step="any" disabled={state.busy} aria-invalid={!!error} aria-describedby={error ? id + '-error' : undefined} onChange={e => {
    const value = currency ? e.target.value.toUpperCase() : e.target.value;
    state.onChange({ ...state.values, [field]: value });
    setValue?.(value === '' ? null : currency ? value : Number(value) / (rate ? 100 : 1));
  }} />{error && <span id={id + '-error'} className="r-field-error">{error}</span>}</label>;
}
export function CostFields() {
  return <><fieldset className="r-cost-group"><legend>同币种金额</legend><div className="r-cost-fields"><Field field="currency" label={labels.currency} />{fields.filter(([, , type]) => type === 'money').map(([key, label]) => <Field key={key} field={key} label={label} />)}</div></fieldset><fieldset className="r-cost-group"><legend>按售价计提的费率</legend><div className="r-cost-fields">{fields.filter(([, , type]) => type === 'rate').map(([key, label]) => <Field key={key} field={key} label={label} />)}</div></fieldset></>;
}
export function UnitEconomicsForm({ input: _input }: { input?: Input }) {
  const state = useContext(CalculationContext);
  if (!state) return <Empty>请在成本工作区打开此表单。</Empty>;
  return <Panel title="单件成本" action={<Badge>{state.dirty ? '输入已修改' : '当前版本'}</Badge>}><form noValidate onSubmit={e => { e.preventDefault(); state.calculate(); }}><CostFields /><CostAction label="计算单件贡献" /></form></Panel>;
}
export function CalculationResult({ result }: { result: Calculation | null }) {
  return <div aria-live="polite" aria-atomic="true"><ResultContent result={result} /></div>;
}
function ResultContent({ result }: { result: Calculation | null }) {
  if (!result) return <Panel title="测算结果"><Empty>填写经核对的成本后计算。空白保留为未知。</Empty></Panel>;
  if (result.status === 'HOLD') return <Panel title="待补资料"><p>本次还缺少：</p><div className="r-tags">{result.missing.map(key => <Badge key={key} tone="warning">{labels[key] || key}</Badge>)}</div></Panel>;
  return <Panel title="单件贡献草稿" action={<Badge tone="blue">{result.currency}</Badge>}><div className="r-result-hero"><Money value={result.contribution} currency={result.currency} /><span className="muted">贡献率 {((result.contribution_rate || 0) * 100).toFixed(2)}%</span></div><dl className="r-breakdown"><div><dt>售价</dt><dd><Money value={result.price} currency={result.currency} /></dd></div>{Object.entries(result.cost_breakdown || {}).map(([key, value]) => <div key={key}><dt>{breakdownLabels[key] || key}</dt><dd><Money value={value} currency={result.currency} /></dd></div>)}<div className="r-total"><dt>总成本</dt><dd><Money value={result.total_cost} currency={result.currency} /></dd></div></dl><p className="r-footnote">依据本次填写的同币种金额；未换汇。结果为贡献估算，仍需核对费用依据。</p></Panel>;
}
function CostColumn({ children }: { children?: ReactNode }) {
  const identity = useContext(CostNodeIdentity), state = useContext(CalculationContext), nodes = costSlotNodes(children);
  if (nodes.some(node => !node.id)) return <Empty>动态目录的组件身份不可用，请使用标准表单。</Empty>;
  const rendered = nodes.map(node => node.child);
  if (identity === costNodes.root) return <div className="r-calculation-grid">{rendered}</div>;
  if (identity === costNodes.fields) return <Panel title="单件成本"><fieldset className="r-cost-group"><legend>同币种金额</legend><div className="r-cost-fields">{nodes.filter(node => node.field && node.field.kind !== 'rate').map(node => node.child)}</div></fieldset><fieldset className="r-cost-group"><legend>按售价计提的费率</legend><div className="r-cost-fields">{nodes.filter(node => node.field?.kind === 'rate').map(node => node.child)}</div></fieldset>{nodes.filter(node => !node.field).map(node => node.child)}</Panel>;
  if (identity === costNodes.output) return <Panel title="测算结果"><div className="r-bound-result" aria-live="polite" aria-atomic="true">{state?.dirty ? <Empty>输入已改变，重新计算后显示当前结果。</Empty> : rendered}</div></Panel>;
  return <div>{rendered}</div>;
}
function BoundField({ label, setValue }: { label: string; value?: string | number | null; unit?: string; minimum?: number; maximum?: number; setValue?: (value: string | number | null) => void }) {
  const identity = useContext(CostNodeIdentity), field = costFieldByNode[identity];
  if (!field) return <Empty>该字段不在成本目录中，请使用标准表单。</Empty>;
  return <Field field={field.key} label={label} setValue={setValue} />;
}
function CostAction({ label }: { label: string; action?: unknown }) {
  const state = useContext(CalculationContext);
  return <div className="r-form-actions"><Button primary disabled={state?.busy} onClick={() => state?.calculate()}>{state?.bound ? '保存并测算' : label}</Button><Button disabled={state?.busy || !state?.dirty} onClick={() => state?.save()}>{state?.bound ? '仅保存参数' : '保存输入'}</Button></div>;
}
function CostText({ text, variant }: { text: string; variant?: string }) { return variant === 'caption' ? <details className="r-footnote"><summary>查看测算依据</summary><p>{text}</p></details> : <p className="r-bound-text">{text}</p>; }
export const commerceUI = createGenerativeUI({ id: catalogId, components: registerCostComponents({ Column: CostColumn, Text: CostText, NumberField: BoundField, CurrencyField: BoundField, Button: CostAction }) });
