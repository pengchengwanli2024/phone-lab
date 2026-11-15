export type FollowupAction = { type: 'thread' | 'research' | 'agent' | 'tasks'; id: string };
export interface FollowupTarget { kind: 'attention' | 'task_result' | 'public_source'; ref: string; version_sha256: string }
export interface FollowupChoice { label: string; target: FollowupTarget }
export interface Followup {
  id: string; kind: FollowupTarget['kind']; ref: string; label: string; demo: boolean; revision: number;
  state: 'scheduled' | 'checked' | 'cancelled' | 'acknowledged'; due_at: string; scope_current: boolean;
  current_action: unknown; receipt: null | { checked_at: string; condition: string; observed: Record<string, unknown> };
  receipt_group?:null|{count:number;sha256:string;latest:{id:string;checked_at:string;condition:string}};
}
export function dueAt(input: string): string {
  const value = new Date(input);
  if (!input || !Number.isFinite(value.getTime())) throw Error('invalid_followup_time');
  return value.toISOString();
}
export function localTimeInput(input = new Date(Date.now() + 15 * 60_000)): string {
  const two = (value: number) => String(value).padStart(2, '0');
  return `${input.getFullYear()}-${two(input.getMonth()+1)}-${two(input.getDate())}T${two(input.getHours())}:${two(input.getMinutes())}`;
}
export function originalFollowupAction(value: unknown): FollowupAction | null {
  if (!value || typeof value !== 'object') return null;
  const action = value as FollowupAction;
  return ['thread','research','agent','tasks'].includes(action.type) && typeof action.id === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(action.id) ? action : null;
}
