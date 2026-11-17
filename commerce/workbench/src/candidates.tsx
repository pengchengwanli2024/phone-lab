import { useEffect, useRef, useState } from 'react';
import { api, errorText, newKey } from './api';
import {CatalogBrowser,type CatalogItem} from './catalog-browser';
import type { ResearchJob } from './research-types';
import { activeResearch, researchPhase, researchStatus } from './research-types';
import { ResearchDetails } from './research-details';
import { Badge, Button, Dialog, Empty, ErrorNotice } from './ui';

interface Props { active: boolean; requestedTask: string; closeTask: () => void; openTask: (id: string) => void; openThread: (id: string) => void; navigate: (tab: string, caseId?: string, researchTaskId?: string) => void; }
export function Candidates({ active, requestedTask, closeTask, openTask, openThread, navigate }: Props) {
  const [jobs, setJobs] = useState<ResearchJob[]>([]),[markets,setMarkets]=useState<string[]>([]),[catalogRefresh,setCatalogRefresh]=useState(0);
  const catalogSignature=useRef('');
  const [query, setQuery] = useState(''), [market, setMarket] = useState('all'), [scope, setScope] = useState('real');
  const [loading, setLoading] = useState(true), [jobError, setJobError] = useState('');
  const [job, setJob] = useState<ResearchJob | null>(null), [detailLoading, setDetailLoading] = useState(false), [detailError, setDetailError] = useState(''), [busy, setBusy] = useState(false);
  const generation = useRef(0), detailGeneration = useRef(0), selected = useRef(requestedTask), resumed = useRef<{ fingerprint: string; key: string } | null>(null);
  selected.current = requestedTask;
  function refreshCatalog(research:ResearchJob[]){
    const ids=new Set(catalogSignature.current.split(',').filter(Boolean));
    for(const task of research)for(const candidate of task.candidates)ids.add(candidate.case_id);
    const signature=[...ids].sort().join(',');
    if(signature!==catalogSignature.current){catalogSignature.current=signature;setCatalogRefresh(previous=>previous+1);}
  }
  async function load(quiet = false) {
    const version = ++generation.current; if (!quiet) setLoading(true); setJobError('');
    try {
      const research=await api<{jobs:ResearchJob[]}>('commerce_market_research_list');
      if(version!==generation.current)return;
      setJobs(previous=>window.CommerceResearchContext.mergeJobs(previous,research.jobs));
      refreshCatalog(research.jobs);
    }catch(failure){if(version===generation.current)setJobError(errorText(failure));}
    finally{if(version===generation.current)setLoading(false);}
  }
  async function readTask(id: string, quiet = false) {
    const version = ++detailGeneration.current;
    if (!quiet) setDetailLoading(true);
    try {
      const data = await api<ResearchJob>('commerce_market_research_get', { task_id: id });
      if (version === detailGeneration.current && selected.current === id) { setJob(data); setJobs(previous => window.CommerceResearchContext.mergeJob(previous, data)); refreshCatalog([data]); setDetailError(''); }
    } catch (failure) { if (version === detailGeneration.current && selected.current === id) setDetailError(errorText(failure)); }
    finally { if (version === detailGeneration.current) setDetailLoading(false); }
  }
  useEffect(() => { if (active) void load(); return () => { generation.current++; }; }, [active]);
  const hasActiveJobs = jobs.some(activeResearch);
  useEffect(() => {
    if (!active || !hasActiveJobs) return;
    const timer = setInterval(() => { void load(true); }, 2500);
    return () => clearInterval(timer);
  }, [active, hasActiveJobs]);
  useEffect(() => {
    detailGeneration.current++; setJob(null); setDetailError(''); setBusy(false);
    if (active && requestedTask) void readTask(requestedTask);
    return () => { detailGeneration.current++; };
  }, [active, requestedTask]);
  const taskActive = activeResearch(job);
  useEffect(() => {
    if (!active || !requestedTask || !taskActive || busy) return;
    const timer = setInterval(() => { void readTask(requestedTask, true); }, 2000);
    return () => clearInterval(timer);
  }, [active, requestedTask, taskActive, busy]);
  async function action(kind: 'cancel' | 'resume') {
    if (!job || busy) return;
    const id = job.task_id, revision = job.revision; setBusy(true); setDetailError('');
    try {
      if (kind === 'resume') {
        const fingerprint = id + ':' + revision;
        if (resumed.current?.fingerprint !== fingerprint) resumed.current = { fingerprint, key: newKey() };
        await api('commerce_market_research_resume', { task_id: id, expected_revision: revision, idempotency_key: resumed.current.key }); resumed.current = null;
      } else await api('commerce_market_research_cancel', { task_id: id });
      if (selected.current === id) await readTask(id);
      await load();
    } catch (failure) { if (selected.current === id) setDetailError(errorText(failure)); }
    finally { if (selected.current === id) setBusy(false); }
  }
  function catalogItems(items:CatalogItem[]){
    const next=[...new Set(items.filter(item=>item.synthetic===(scope==='example')).map(item=>item.market).filter((value):value is string=>!!value))];
    setMarkets(previous=>previous.join('|')===next.join('|')?previous:next);
  }
  return <div className="r-page r-candidates" data-ai-page="pilots" data-ai-context={JSON.stringify({demo:scope==="example",filters:{query,market}})}>
    <div className="r-page-heading"><h1>商品候选{scope === 'example' && <small className="r-inline-source">示例资料</small>}</h1><div className="r-actions"><Button onClick={() => navigate('old:pilots')}>已有试点</Button><Button icon="refresh" onClick={() => {setCatalogRefresh(previous=>previous+1);void load();}} disabled={loading}>刷新</Button></div></div>
    <div className="r-list-filters"><label className="ui-field">市场<select value={market} onChange={event => setMarket(event.target.value)}><option value="all">全部市场</option>{[...new Set([...markets,...(market==='all'?[]:[market])])].map(value=><option key={value} value={value}>{value}</option>)}</select></label><label className="ui-field">资料范围<select value={scope} onChange={event=>{setScope(event.target.value);setMarket('all');}}><option value="real">真实候选</option><option value="example">示例候选</option></select></label></div>
    <CatalogBrowser active={active} synthetic={scope==='example'} market={market} refreshKey={catalogRefresh} onQuery={setQuery} onItems={catalogItems} onSelect={id=>navigate('workspace',id)}/>
    <section className="r-research-jobs" aria-label="公开市场研究任务"><h2>研究任务</h2><ErrorNotice>{jobError}</ErrorNotice>{loading ? <Empty>正在读取研究任务…</Empty> : jobs.length ? <div className="r-candidate-list">{jobs.map(item => <button className="r-research-job" key={item.task_id} onClick={() => openTask(item.task_id)}><div><strong>{item.query}</strong><small>{item.market === 'RU' ? '俄罗斯' : item.market} · {(item.supplemental_source_count || 0) > 0 ? '采集来源' : '来源'} {item.source_count}{(item.supplemental_source_count || 0) > 0 && <> · 补充资料 {item.supplemental_source_count}</>} · 候选 {item.candidate_count}</small></div><Badge tone={item.status === 'failed' ? 'danger' : item.status === 'partial' ? 'warning' : 'gray'}>{activeResearch(item) ? researchPhase[item.phase] || '研究中' : researchStatus[item.status] || '待核对'}</Badge></button>)}</div> : !jobError && <Empty>尚无研究任务。</Empty>}</section>
    {active && requestedTask && <Dialog title="市场研究" close={closeTask}><ErrorNotice>{detailError}</ErrorNotice>{detailLoading && !job ? <Empty>正在读取原研究任务…</Empty> : job && <ResearchDetails job={job} busy={busy} refresh={() => void readTask(job.task_id)} cancel={() => void action('cancel')} resume={() => void action('resume')} openCandidate={(id, taskId) => { closeTask(); navigate('workspace', id, taskId); }} openThread={id => { closeTask(); openThread(id); }} />}</Dialog>}
  </div>;
}
