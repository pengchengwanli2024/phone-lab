/** Read-only projection of existing memory and skill-task records. Nothing here is inferred. */
export interface MemoryRecord {
  id: string; layer: string; content: string; title?: string; status: string; effective_status: string;
  revision: number; synthetic: boolean; created_at?: number; invalid_reason?: string | null;
  supersedes?: { id: string; revision: number };
}
export interface SkillCase {
  id: string; skill_id: string; mode_id?: string | null; source_sha256?: string; adapter?: string | null;
  status: string; created_at?: string; synthetic: boolean;
}
export interface LibrarySource { id: string; commit: string; skills: number }
export interface HistoryRow {
  key: string; kind: 'memory' | 'skill'; at: number | null; label: string; title: string;
  status: string; tone: 'gray' | 'warning'; meta: string[];
}

const memoryStatus: Record<string, string> = {
  proposed: '待确认', confirmed: '已人工确认', active: '有效摘要', stale: '来源或事实已失效', withdrawn: '已撤回',
};
const caseStatus: Record<string, string> = {
  prepared: '已准备，未执行', needs_inputs: '缺少输入', guidance_ready: '仅流程说明', running: '执行中',
  interrupted: '已中断，结果未知', completed: '已完成本机计算', failed: '执行失败',
};
const warning = new Set(['stale', 'withdrawn', 'interrupted', 'failed', 'needs_inputs']);
/** Unknown codes stay visible instead of being mapped to a neighbouring state. */
const named = (table: Record<string, string>, code: string) => table[code] || `原记录：${code}`;
const short = (value: string, size: number) => value.length > size ? value.slice(0, size) + '…' : value;

export function memoryRows(items: MemoryRecord[]): HistoryRow[] {
  return items.map(item => {
    const state = item.effective_status || item.status;
    const meta = [`修订 ${item.revision}`];
    if (item.supersedes) meta.push(`纠正旧事实 ${short(item.supersedes.id, 15)}（修订 ${item.supersedes.revision}）`);
    if (item.invalid_reason) meta.push(`失效原因：${item.invalid_reason}`);
    return {
      key: 'memory:' + item.id, kind: 'memory' as const,
      at: typeof item.created_at === 'number' && Number.isFinite(item.created_at) ? item.created_at * 1000 : null,
      label: item.layer === 'L3' ? '摘要' : '事实', title: short(item.title || item.content, 120),
      status: named(memoryStatus, state), tone: warning.has(state) ? 'warning' as const : 'gray' as const, meta,
    };
  });
}

/** The case list is not scoped by the backend; keep only the page's own data range. */
export function skillRows(cases: SkillCase[], demo: boolean): HistoryRow[] {
  return cases.filter(item => item.synthetic === demo).map(item => {
    const parsed = item.created_at ? Date.parse(item.created_at) : NaN;
    const meta = [item.adapter ? '离线计算器' : '无本机计算器'];
    if (item.mode_id) meta.push(`模式 ${item.mode_id}`);
    if (item.source_sha256) meta.push(`技能版本 ${item.source_sha256.slice(0, 8)}`);
    return {
      key: 'skill:' + item.id, kind: 'skill' as const, at: Number.isFinite(parsed) ? parsed : null,
      label: '技能任务', title: item.skill_id, status: named(caseStatus, item.status),
      tone: warning.has(item.status) ? 'warning' as const : 'gray' as const, meta,
    };
  });
}

/** Newest first; records without a readable time sink to the end rather than getting a guessed one. */
export function historyRows(items: MemoryRecord[], cases: SkillCase[], demo: boolean): HistoryRow[] {
  return [...memoryRows(items), ...skillRows(cases, demo)]
    .sort((a, b) => a.at === null ? (b.at === null ? 0 : 1) : b.at === null ? -1 : b.at - a.at);
}

export function timeText(at: number | null): string {
  if (at === null) return '时间未记录';
  const d = new Date(at), two = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
}
