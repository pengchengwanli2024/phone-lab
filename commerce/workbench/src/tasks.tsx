import { useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import type { Task } from './types';
import type { ResearchJob } from './research-types';
import { researchPhase } from './research-types';
import { Button, Dialog, Empty, ErrorNotice, Panel, Status } from './ui';
import {ExecutionDirectory} from './execution-directory';
import { TaskTimeline } from './task-timeline';
import { AssistantTasks } from './assistant-tasks';
import { MoreActions } from './action-menu';
import { readTaskCostSurface } from './task-cost-resume';
interface PublicResearchResult { analysis?: string; source_questions?: string[]; source_links?: {title: string; url: string}[] }
function PublicResearch({output}:{output:PublicResearchResult}){
  const inline=(text:string)=>text.split(/(\*\*[^*]+\*\*)/g).map((part,i)=>part.startsWith("**")?<strong key={i}>{part.slice(2,-2)}</strong>:part);
  return <div className="copilot-formatted">{output.analysis?.split("\n").filter(Boolean).map((line,i)=><p key={i}>{inline(line)}</p>)}{output.source_questions?.length ? <h4>原分析待补充</h4> : null}{output.source_questions?.map((q,i)=><p key={i}>{q}</p>)}<h4>原始来源</h4><ul>{output.source_links?.map(row=><li key={row.url}>{/^https?:\/\//i.test(row.url)?<a href={row.url} target="_blank" rel="noopener noreferrer">{row.title}</a>:row.title}</li>)}</ul></div>;
}
interface Receipt { task: Task; research_job?: ResearchJob; execution: null | { operation: string; attempt: number | null; finished_at?: string; error?: string; result: PublicResearchResult & { report_id?: string; content?: string; contribution?: number; currency?: string; id?: string; status?: string; actual_bytes_verified?: boolean; provider_status?: string; review_status?: string } | null } }
export function Tasks({ navigate, onResearch, onCost, onConversation, active = true }: { navigate: (tab: string, caseId?: string) => void; onResearch: (taskId: string) => void; onCost: (surfaceId: string, caseId?: string) => void; onConversation?: (threadId: string) => void; active?: boolean }) {
  const [tasks, setTasks] = useState<Task[]>([]), [filter, setFilter] = useState('all'), [query, setQuery] = useState(''), [error, setError] = useState(''), [loading, setLoading] = useState(true), [receipt, setReceipt] = useState<Receipt | null>(null), [busy, setBusy] = useState(false);
  const [view,setView]=useState<'ledger'|'assistant'|'executions'>('ledger');
  const generation = useRef(0), detailGeneration = useRef(0);
  async function load() { const id = ++generation.current; setLoading(true); try { const result = await api<{ tasks: Task[] }>('commerce_task_list'); if (id === generation.current) { setTasks(result.tasks); setError(''); } } catch (e) { if (id === generation.current) setError(errorText(e)); } finally { if (id === generation.current) setLoading(false); } }
  useEffect(() => { if (active) void load(); else setReceipt(null); return () => { generation.current++; detailGeneration.current++; }; }, [active]);
  async function details(task: Task) { const id = ++detailGeneration.current; setError(''); try { const result = await api<Receipt>('commerce_task_result', { task_id: task.id }); if (id === detailGeneration.current) setReceipt(result); } catch (e) { if (id === detailGeneration.current) setError(errorText(e)); } }
  async function cancel(task: Task) { if (busy) return; setBusy(true); try { await api('commerce_task_cancel', { task_id: task.id }); setReceipt(null); await load(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); } }
  async function retryReport(task: Task) { if (busy || task.input.mode !== 'public_research') return; setBusy(true); try { await api('commerce_task_retry', { task_id: task.id }); await details(task); await load(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); } }
  const visible = tasks.filter(task => (filter === 'all' || (filter === 'attention' ? ['blocked', 'failed', 'interrupted', 'unknown', 'needs_input', 'awaiting_input', 'awaiting_review', 'review', 'partial'].includes(task.status) : filter === 'active' ? ['queued', 'running', 'cancelling'].includes(task.status) : task.status === filter)) && [task.id, task.input.title, task.kind].some(value => value?.toLowerCase().includes(query.toLowerCase())));
  const research = receipt?.research_job?.schema === 'commerce-market-research-v1' && receipt.research_job.task_id === receipt.task.id ? receipt.research_job : null;
  const plugin = receipt?.execution?.operation === 'media_plugin' ? receipt.execution.result : null;
  async function resume() {
    if (!receipt || busy) return;
    const selected = receipt.task, id = ++detailGeneration.current;
    setBusy(true); setError('');
    try {
      if(selected.input.mode==='public_research'){
        setReceipt(null);
        if(typeof selected.input.source_thread_id==='string'&&selected.input.source_thread_id&&onConversation)onConversation(selected.input.source_thread_id);
        else navigate('intelligence');
        return;
      }
      const cost = await readTaskCostSurface(api, selected);
      if (id !== detailGeneration.current) return;
      setReceipt(null);
      if (cost) onCost(cost.surface_id, cost.binding?.case_id);
      else if (research) onResearch(research.task_id);
      else if (plugin && typeof selected.input.media_plugin_execution_id === 'string') navigate('old:creative', selected.input.media_plugin_execution_id);
      else navigate(selected.input.organization_case ? 'workspace' : 'old:tasks', selected.input.organization_case);
    } catch (e) { if (id === detailGeneration.current) setError(errorText(e)); }
    finally { setBusy(false); }
  }

  return <div className="r-page" data-ai-page="tasks" data-ai-context={JSON.stringify({filters:{query,status:filter},...(receipt?{section:"details",entity:{kind:"task",id:receipt.task.id,name:receipt.task.input.title}}:{})})}><div className="r-page-heading"><div><h1>任务</h1></div><Button onClick={() => void load()} disabled={loading}>刷新</Button></div><ErrorNotice>{error}</ErrorNotice><div className="r-tabs r-task-sources" aria-label="任务来源">{([['ledger','待处理与任务'],['assistant','助手任务'],['executions','执行记录']] as const).map(([id,label])=><Button key={id} aria-pressed={view===id} onClick={()=>setView(id)}>{label}</Button>)}</div>{view==='executions'&&<ExecutionDirectory active={active} navigate={navigate}/>}<div hidden={view!=='ledger'}><Panel title="任务账本" action={<Button onClick={() => navigate('old:tasks')}>设备与执行器</Button>}><div className="r-list-filters"><label className="ui-field">查找任务<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="任务标题或完整 ID" /></label><label className="ui-field">状态<select value={filter} onChange={e => setFilter(e.target.value)}>{[['all', '全部任务'], ['attention', '需要介入'], ['active', '排队与执行中'], ['completed', '任务已完成'], ['cancelled', '已取消']].map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>{loading ? <Empty>正在读取原任务…</Empty> : visible.length ? <div className="r-table-wrap r-task-ledger"><table className="data-table"><thead><tr><th scope="col">任务</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead><tbody>{visible.map(task => <tr key={task.id}><td><strong className="r-task-title" title={task.input.title || task.kind}>{task.input.title || task.kind}</strong><small className="r-task-id" title={task.id}>#{task.id.slice(0,8)}</small></td><td><Status value={task.status} /></td><td className="r-table-actions"><Button onClick={() => void details(task)}>查看回执</Button><MoreActions label="更多任务操作" actions={[...(typeof task.input.media_plugin_execution_id==='string'?[{id:'plugin',label:'继续插件任务',onSelect:()=>navigate('old:creative',String(task.input.media_plugin_execution_id))}]:[]),...(task.input.organization_case?[{id:'product',label:'查看原商品',onSelect:()=>navigate('workspace',task.input.organization_case)}]:[])]}/></td></tr>)}</tbody></table></div> : <Empty>当前范围没有匹配任务。</Empty>}</Panel></div><div hidden={view!=='assistant'}><AssistantTasks active={active&&view==='assistant'} onConversation={onConversation}/></div>{receipt && <Dialog title="任务与执行回执" close={() => { detailGeneration.current++; setReceipt(null); }}><ErrorNotice>{error}</ErrorNotice><h3>{receipt.task.input.title || receipt.task.kind}</h3><Status value={receipt.task.status} /><p className="r-task-id">{receipt.task.id}</p>{research ? <div><p>{researchPhase[research.phase] || '状态待核对'} · 来源 {research.source_count} · 已保存候选 {research.candidate_count}</p><ErrorNotice>{research.error?.message}</ErrorNotice>{research.questions.map((question, index) => <p key={index}>{question}</p>)}</div> : plugin ? <div><p>插件执行与实际素材回执</p><p>{plugin.actual_bytes_verified ? '实际文件已校验，可回原制作版本审阅。' : '实际文件尚未完成校验，请继续原插件任务。'}</p><p>服务回执：{plugin.provider_status || '尚无远端回执'} · {plugin.status || '状态待核对'}</p></div> : receipt.execution ? <div><p>执行尝试：{receipt.execution.attempt} · {receipt.execution.finished_at ? '已有结束回执' : '尚无结束回执'}</p>{receipt.execution.error && <ErrorNotice>本次执行失败。错误标识：{/^[a-z][a-z0-9_]{0,100}$/.test(receipt.execution.error)?receipt.execution.error:'原因需在原执行器核对'}</ErrorNotice>}{['failed','interrupted'].includes(receipt.task.status)&&!receipt.execution.error&&<p role="status">这条历史记录未保存失败原因，请在原工作中核对；刷新不会重新执行。</p>}{receipt.task.input.mode === "public_research" && receipt.execution.result?.analysis ? <PublicResearch output={receipt.execution.result}/> : receipt.execution.result?.content && <pre className="r-readable">{receipt.execution.result.content}</pre>}</div> : <Empty>{['failed','interrupted'].includes(receipt.task.status)?'历史记录未保存执行回执或失败原因，请查看原工作。':'尚无执行回执。'}</Empty>}<TaskTimeline key={receipt.task.id} kind="task" id={receipt.task.id}/><div className="r-form-actions">{receipt.task.status === 'queued' && <Button disabled={busy} onClick={() => void cancel(receipt.task)}>取消排队任务</Button>}{receipt.task.input.mode === 'public_research' && ['failed','interrupted'].includes(receipt.task.status) && <Button disabled={busy} onClick={() => void retryReport(receipt.task)}>重试本地简报</Button>}<Button disabled={busy} onClick={() => void details(receipt.task)}>刷新回执</Button><Button disabled={busy} onClick={() => void resume()}>继续原工作</Button></div></Dialog>}</div>;
}
