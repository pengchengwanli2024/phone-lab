export type AttentionTarget = { type: 'thread' | 'research' | 'agent' | 'followup'; id: string };
export interface AttentionItem {
  id: string; source: 'agent' | 'research' | 'followup'; source_id: string;
  kind: 'unknown' | 'failed' | 'review' | 'input'; title: string; detail: string;
  status: string; action: AttentionTarget; task_id?: string; run_id?: string; thread_id?: string;
}
export interface AttentionPage {
  items: AttentionItem[]; has_more: boolean; next_cursor: string | null;
  complete: boolean; source_errors: string[]; read_at: string;
}
type Invoke = (tool: string, args: object) => Promise<unknown>;
export async function readAttentionTarget(invoke: Invoke, id: string): Promise<AttentionTarget> {
  const value = await invoke('commerce_attention_get', { item_id: id }) as { item?: AttentionItem };
  const item = value?.item, action = item?.action;
  if (item?.id !== id || !action || !['thread', 'research', 'agent', 'followup'].includes(action.type) ||
      typeof action.id !== 'string' || !/^[a-zA-Z0-9_-]{1,160}$/.test(action.id)) throw Error('attention_item_changed');
  return action;
}
export function linkedAttentionTasks(items: Pick<AttentionItem, 'source' | 'source_id' | 'task_id'>[]): Set<string> {
  return new Set(items.flatMap(item => item.task_id ? [item.task_id] : []));
}
