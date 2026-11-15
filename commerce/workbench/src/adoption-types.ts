export interface ImportBatch {
  id: string; sha256: string; filename: string; status: string; synthetic: boolean;
  scope: { platform: string; store_ref: string; market: string }; row_count: number; valid_count: number;
  accepted_count: number; duplicate_count: number; quarantined_count: number; preview_truncated: boolean;
  preview: { row: number; record: Record<string, string | number> }[];
  quarantined: { row: number; code: string }[];
  sales_by_currency: { currency: string; order_count: number; line_count: number; unit_count: number; gross_sales: string }[];
}
export interface PlanStep { id: string; title: string; task_id?: string }
export interface Plan { goal: string; steps: PlanStep[]; graph: { edges: { from: string; to: string }[]; positions: Record<string, { x: number; y: number }> } }
export interface PlanSnapshot { versions?: { revision: number; payload: Plan; stale: boolean; sha256: string; created_at: string }[]; case_id: string; name: string; revision: number; source_sha256: string; stale: boolean; payload: Plan; tasks: { id: string; status: string; input: { title?: string } }[] }
export interface Binding { source_id: string; version: number; sha256: string; record_key: string; quote: string }
export interface MemoryItem {
  id: string; layer: 'L1' | 'L2' | 'L3'; content: string; title?: string; status: string; effective_status: string;
  revision: number; sha256: string; synthetic: boolean; bindings?: Binding[];
  fact_refs?: { id: string; revision: number; sha256: string }[];
  scope: { platform: string; store_ref: string | null; subject_ref: string };
}
export interface BusinessSource {
  id: string; version: number; sha256: string; label: string; kind: string;
  scope: MemoryItem['scope']; fresh: boolean;
}
export function requestKey(keys: Map<string, string>, operation: string, body: object) {
  const identity = operation + ':' + JSON.stringify(body);
  let key = keys.get(identity);
  if (!key) { key = crypto.randomUUID(); keys.set(identity, key); }
  return key;
}
export const memoryStatus: Record<string, string> = { proposed: '待确认', confirmed: '已人工确认', active: '有效摘要', stale: '来源或事实已失效', withdrawn: '已撤回', imported_unverified: '导入资料 · 未核实' };
