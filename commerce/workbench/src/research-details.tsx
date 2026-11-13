import type { ResearchJob } from './research-types';
import { activeResearch, researchPhase, researchStatus, sourceLink } from './research-types';
import { Badge, Button, Empty, ErrorNotice } from './ui';

interface Props { job: ResearchJob; busy: boolean; refresh: () => void; cancel: () => void; resume: () => void; openCandidate: (id: string, taskId: string) => void; openThread: (id: string) => void; }
function captured(value: string | number) {
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
  return Number.isNaN(date.valueOf()) ? '时间待核对' : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
}
export function ResearchDetails({ job, busy, refresh, cancel, resume, openCandidate, openThread }: Props) {
  return <div className="r-research-detail">
    <div className="r-research-state"><Badge tone={job.status === 'failed' ? 'danger' : job.status === 'partial' ? 'warning' : 'gray'}>{researchStatus[job.status] || '状态待核对'}</Badge><span>{researchPhase[job.phase] || job.phase}</span><span>{job.market === 'RU' ? '俄罗斯' : job.market}</span></div>
    <details className="r-research-request"><summary>研究需求</summary><p className="r-readable">{job.query}</p></details>
    <p className="r-footnote">来源 {job.source_count} · 已保存候选 {job.candidate_count} · 更新于 {captured(job.updated_at)}</p>
    <ErrorNotice>{job.error?.message}</ErrorNotice>
    {job.questions.length > 0 && <div className="r-research-questions">{job.questions.map((question, index) => <p key={index}>{question}</p>)}</div>}
    <div className="r-form-actions"><Button onClick={refresh} disabled={busy} icon="refresh">刷新状态</Button>{activeResearch(job) && <Button onClick={cancel} disabled={busy || job.status === 'cancelling'}>停止研究</Button>}{['interrupted', 'failed', 'unknown'].includes(job.status) && <Button onClick={resume} disabled={busy}>继续原任务</Button>}{job.thread_id && <Button onClick={() => openThread(job.thread_id)} disabled={busy}>在原对话继续</Button>}</div>
    {job.report && <section className="r-research-section" aria-label="市场分析"><h3>市场分析</h3><p className="r-readable">{job.report.summary}</p>{job.report.findings.length > 0 && <ul>{job.report.findings.map((finding, index) => <li key={index}>{finding}</li>)}</ul>}{job.report.limitations.length > 0 && <details open><summary>样本与资料限制</summary><ul>{job.report.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}</section>}
    <section className="r-research-section" aria-label="本次保存的候选"><h3>商品候选</h3>{job.candidates.length ? <div>{job.candidates.map(candidate => <div key={candidate.case_id} className="r-research-candidate"><div><strong>{candidate.name}</strong><small>来源 {candidate.source_ids.join('、')}</small></div><Button onClick={() => openCandidate(candidate.case_id, job.task_id)}>继续研究</Button></div>)}</div> : <Empty>{activeResearch(job) ? '尚未保存候选。' : '本次没有已保存候选，请查看来源与缺项。'}</Empty>}</section>
    <section className="r-research-section" aria-label="采集来源"><h3>来源记录</h3>{job.sources.length ? job.sources.map(source => <details className="r-research-source" key={source.id}><summary><span>{source.title || source.id}</span><Badge tone={source.status === 'collected' ? 'gray' : 'warning'}>{source.status === 'collected' ? '已采集' : '未采集成功'}</Badge></summary><p>{source.id} · {captured(source.captured_at)}</p>{sourceLink(source.url) ? <a href={sourceLink(source.url)!} target="_blank" rel="noreferrer noopener">打开原始来源</a> : <p>来源链接不可用</p>}{source.error && <><p>{source.error.includes("timeout") ? "来源访问超时，未取得可分析正文。" : "来源未能采集，请查看技术详情。"}</p><details><summary>技术详情</summary><code>{source.error}</code></details></>}{source.excerpt && <p className="r-readable">{source.excerpt}</p>}<small className="r-source-hash">SHA-256 · {source.sha256 || '无正文哈希'}</small></details>) : <Empty>尚无来源记录。</Empty>}<p className="r-footnote">已采集表示取得来源内容，事实与结论仍需核对。</p></section>
    <details className="r-research-identities"><summary>任务标识</summary><code>{job.task_id}</code></details>
  </div>;
}
