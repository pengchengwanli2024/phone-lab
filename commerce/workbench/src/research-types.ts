export interface ResearchSource {
  id: string; url: string; title: string; captured_at: string; sha256: string;
  status: 'collected' | 'failed'; error: string | null; evidence_kind: string; excerpt: string;
}
export interface ResearchCandidate { case_id: string; name: string; source_url: string; source_ids: string[]; workspace_url: string; }
export interface ResearchJob {
  schema: 'commerce-market-research-v1'; task_id: string; run_id: string; thread_id: string;
  status: string; phase: string; revision: string | number; query: string; market: string;
  source_count: number; candidate_count: number; error: null | { code: string; message: string };
  questions: string[]; candidates: ResearchCandidate[]; sources: ResearchSource[];
  report: null | { summary: string; findings: string[]; limitations: string[]; evidence_refs: string[] };
  updated_at: string | number;
}
export const researchStatus: Record<string, string> = {
  queued: '排队中', running: '研究中', awaiting_input: '待补充', completed: '已完成', partial: '部分完成',
  failed: '未完成', unknown: '结果待核对', interrupted: '已中断', cancelling: '正在停止', cancelled: '已停止',
};
export const researchPhase: Record<string, string> = { planning: '明确研究范围', collecting: '采集公开资料', analyzing: '分析市场证据', saving: '保存商品候选', finished: '研究结束' };
export const activeResearch = (job: ResearchJob | null | undefined) => !!job && ['queued', 'running', 'cancelling'].includes(job.status);
export function sourceLink(value: string): string | null {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}
