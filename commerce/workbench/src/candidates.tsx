import { useEffect, useRef, useState } from 'react';
import { api, errorText, newKey } from './api';
import type { CaseItem } from './types';
import type { ResearchJob } from './research-types';
import { activeResearch, researchPhase, researchStatus } from './research-types';
import { ResearchDetails } from './research-details';
import { Badge, Button, Dialog, Empty, ErrorNotice, Icon } from './ui';

interface Props { active: boolean; requestedTask: string; closeTask: () => void; openTask: (id: string) => void; openThread: (id: string) => void; navigate: (tab: string, caseId?: string) => void; }
export function Candidates({ active, requestedTask, closeTask, openTask, openThread, navigate }: Props) {
  const [items, setItems] = useState<CaseItem[]>([]), [jobs, setJobs] = useState<ResearchJob[]>([]);
  const [query, setQuery] = useState(''), [market, setMarket] = useState('all'), [scope, setScope] = useState('real');
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [jobError, setJobError] = useState('');
  const [job, setJob] = useState<ResearchJob | null>(null), [detailLoading, setDetailLoading] = useState(false), [detailError, setDetailError] = useState(''), [busy, setBusy] = useState(false);
  const generation = useRef(0), detailGeneration = useRef(0), selected = useRef(requestedTask), resumed = useRef<{ fingerprint: string; key: string } | null>(null);
  selected.current = requestedTask;
  async function load(quiet = false) {
    const version = ++generation.current; if (!quiet) setLoading(true); setError(''); setJobError('');
    const [cases, research] = await Promise.allSettled([api<{ items: CaseItem[] }>('commerce_workspace_list'), api<{ jobs: ResearchJob[] }>('commerce_market_research_list')]);
    if (version !== generation.current) return;
    if (cases.status === 'fulfilled') setItems(cases.value.items.filter(item => item.candidate)); else { setItems([]); setError(errorText(cases.reason)); }
    if (research.status === 'fulfilled') {
      setJobs(research.value.jobs);
      const expected = research.value.jobs.flatMap(item => item.candidates.map(candidate => candidate.case_id));
      if (cases.status === 'fulfilled' && expected.some(id => !cases.value.items.some(item => item.id === id))) {
        try {
          const fresh = await api<{ items: CaseItem[] }>('commerce_workspace_list');
          if (version === generation.current) {
            setItems(fresh.items.filter(item => item.candidate));
            if (expected.some(id => !fresh.items.some(item => item.id === id))) setError('部分已保存候选尚未读回，请刷新核对原研究任务。');
          }
        } catch (failure) { if (version === generation.current) setError(errorText(failure)); }
      }
    } else { setJobs([]); setJobError(errorText(research.reason)); }
    if (version === generation.current) setLoading(false);
  }
  async function readTask(id: string, quiet = false) {
    const version = ++detailGeneration.current;
    if (!quiet) setDetailLoading(true);
    try {
      const data = await api<ResearchJob>('commerce_market_research_get', { task_id: id });
      if (version === detailGeneration.current && selected.current === id) { setJob(data); setDetailError(''); }
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
  const scoped = items.filter(item => item.synthetic === (scope === 'example'));
  const markets = [...new Set([...scoped.map(item => item.market).filter((value): value is string => !!value), ...(market === 'all' ? [] : [market])])];
  const visible = scoped.filter(item => (market === 'all' || item.market === market) && [item.name, item.id, item.platform, item.market].some(value => value?.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
  return <div className="r-page r-candidates">
    <div className="r-page-heading"><h1>商品候选{scope === 'example' && <small className="r-inline-source">示例资料</small>}</h1><div className="r-actions"><Button onClick={() => navigate('old:pilots')}>已有试点</Button><Button icon="refresh" onClick={() => void load()} disabled={loading}>刷新</Button></div></div>
    <ErrorNotice>{error}</ErrorNotice>
    <div className="r-list-filters"><label className="ui-field">查找候选<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="商品名称或市场" /></label><label className="ui-field">市场<select value={market} onChange={event => setMarket(event.target.value)}><option value="all">全部市场</option>{markets.map(value => <option key={value} value={value}>{value}</option>)}</select></label><label className="ui-field">资料范围<select value={scope} onChange={event => setScope(event.target.value)}><option value="real">真实候选</option><option value="example">示例候选</option></select></label></div>
    {loading ? <Empty>正在读取已保存候选…</Empty> : error ? null : visible.length ? <div className="r-candidate-list" aria-label="已保存商品候选">{visible.map(item => <article className="r-candidate-row" key={item.id}><span className="r-object-icon"><Icon name="box" /></span><div className="r-candidate-title"><h2>{item.name}</h2><p>{[item.platform === 'ozon' ? 'Ozon' : item.platform, item.market || '市场待核对'].filter(Boolean).join(' · ')} <Badge>调研候选</Badge></p></div><Button onClick={() => navigate('workspace', item.id)}>继续研究</Button></article>)}</div> : <Empty>{query || market !== 'all' ? '没有匹配的候选。' : '从智能助手发起选品或市场调研，保存的候选会出现在这里。'}</Empty>}
    <section className="r-research-jobs" aria-label="公开市场研究任务"><h2>研究任务</h2><ErrorNotice>{jobError}</ErrorNotice>{loading ? <Empty>正在读取研究任务…</Empty> : jobs.length ? <div className="r-candidate-list">{jobs.map(item => <button className="r-research-job" key={item.task_id} onClick={() => openTask(item.task_id)}><div><strong>{item.query}</strong><small>{item.market === 'RU' ? '俄罗斯' : item.market} · 来源 {item.source_count} · 候选 {item.candidate_count}</small></div><Badge tone={item.status === 'failed' ? 'danger' : item.status === 'partial' ? 'warning' : 'gray'}>{activeResearch(item) ? researchPhase[item.phase] || '研究中' : researchStatus[item.status] || '待核对'}</Badge></button>)}</div> : !jobError && <Empty>尚无研究任务。</Empty>}</section>
    {active && requestedTask && <Dialog title="市场研究" close={closeTask}><ErrorNotice>{detailError}</ErrorNotice>{detailLoading && !job ? <Empty>正在读取原研究任务…</Empty> : job && <ResearchDetails job={job} busy={busy} refresh={() => void readTask(job.task_id)} cancel={() => void action('cancel')} resume={() => void action('resume')} openCandidate={id => { closeTask(); navigate('workspace', id); }} openThread={id => { closeTask(); openThread(id); }} />}</Dialog>}
  </div>;
}
