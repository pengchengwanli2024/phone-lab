import { useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import type { CaseItem, LiveStatus, OpsAlert, Product, Task } from './types';
import { Badge, Button, Empty, ErrorNotice, Icon, Status } from './ui';
import { useAttention } from './attention';
import { linkedAttentionTasks } from './attention-state';
import { Followups } from './followups';
import type { FollowupAction } from './followup-state';
import { DashboardChart, DashboardPanel, InventoryAndAlerts, OperatingHints, ProductProgress, RecentTasks, type OperatingHint } from './overview-widgets';
import './overview-dashboard.css';
import { StatisticsSync } from './operating-charts';
import { OverviewMetrics, type Dashboard, type OrderSnapshot } from './overview-statistics';

interface OverviewData { dashboard?: Dashboard; orders?: OrderSnapshot; tasks?: Task[]; cases?: CaseItem[]; alerts?: OpsAlert[]; alertsComplete?:boolean; live?: OverviewLive; errors: string[] }
type Notice = { id: string; category: string; title: string; detail: string; target: string; caseId?: string; status?: string; attentionId?: string };
interface OverviewLive extends LiveStatus { stock_basis?: string }
export function Overview({ demo, navigate, active = true, onThread, onResearch }: { demo: boolean; navigate: (tab: string, caseId?: string) => void; active?: boolean; onThread: (id: string) => void; onResearch: (id: string) => void }) {
  const attention = useAttention(demo, active);
  const [followupId,setFollowupId] = useState<string|null>(null);
  const [opening, setOpening] = useState(''), [openError, setOpenError] = useState('');
  const [data, setData] = useState<OverviewData>({ errors: [] }), [loading, setLoading] = useState(true), [filter, setFilter] = useState('all'), [time, setTime] = useState('');
  const version = useRef(0);
  const [expanded,setExpanded]=useState(false),[caseDetails,setCaseDetails]=useState<Record<string,Product|null>>({});
  function selectFilter(value:string){setFilter(value);setExpanded(false)}
  async function load() {
    const revision = ++version.current; setLoading(true);
    const results = await Promise.allSettled([
      api<Dashboard>('commerce_dashboard', { demo }), api<{ tasks: Task[] }>('commerce_task_list'),
      api<{ items: CaseItem[] }>('commerce_workspace_list'), api<{ alerts: OpsAlert[] }>('commerce_live_alerts'),
      api<{ alerts: OpsAlert[] }>('commerce_ops_list', { demo }), api<OverviewLive>('commerce_live_status'),
      api<OrderSnapshot>('commerce_orders_list', { demo }),
    ]);
    if (revision !== version.current) return;
    const [dashboard, tasks, cases, liveAlerts, opsAlerts, live, orders] = results;
    const names = ['经营数据', '共享任务', '商品工作项', '店铺提醒', '导入提醒', '连接状态', '发货单统计'];
    setData({ dashboard: dashboard.status === 'fulfilled' ? dashboard.value : undefined, tasks: tasks.status === 'fulfilled' ? tasks.value.tasks : undefined, cases: cases.status === 'fulfilled' ? cases.value.items.filter(c => c.synthetic === demo) : undefined, live: live.status === 'fulfilled' ? live.value : undefined,
      orders: orders.status === 'fulfilled' ? orders.value : undefined,
      alerts: [...(!demo&&liveAlerts.status==='fulfilled'?liveAlerts.value.alerts:[]),...(opsAlerts.status==='fulfilled'?opsAlerts.value.alerts:[])],
      alertsComplete:(demo||liveAlerts.status==='fulfilled')&&opsAlerts.status==='fulfilled',
      errors: results.flatMap((r, i) => r.status === 'rejected' ? [names[i]] : []),
    });
    setTime(new Date().toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit' })); setLoading(false);
    setCaseDetails({});
    const previewCases=cases.status==='fulfilled'?cases.value.items.filter(item=>item.synthetic===demo).slice(0,2):[];
    const previews=await Promise.allSettled(previewCases.map(item=>api<Product>('commerce_workspace_get',{case_id:item.id})));
    if(revision===version.current)setCaseDetails(Object.fromEntries(previewCases.map((item,index)=>[item.id,previews[index].status==='fulfilled'?previews[index].value:null])));
  }
  useEffect(() => { if (active) { setOpenError(''); void load(); } return () => { version.current++; }; }, [demo, active]);
  async function openNotice(notice: Notice) {
    if (!notice.attentionId) { navigate(notice.target, notice.caseId); return; }
    if (opening) return;
    setOpening(notice.attentionId); setOpenError('');
    try {
      const action = await attention.target(notice.attentionId);
      if (action.type === 'thread') onThread(action.id);
      else if (action.type === 'research') onResearch(action.id);
      else if(action.type==='followup')setFollowupId(action.id);
      else navigate('old:agent', action.id);
    } catch (failure) { setOpenError(errorText(failure)); }
    finally { setOpening(''); }
  }
  function openOriginal(action:FollowupAction) {
    if(action.type==='thread')onThread(action.id);
    else if(action.type==='research')onResearch(action.id);
    else if(action.type==='tasks')navigate('tasks');
    else navigate('old:agent',action.id);
  }
  const notices: Notice[] = [];
  const linked = linkedAttentionTasks(attention.items);
  for (const task of data.tasks || []) {
    if (linked.has(task.id)) continue;
    if (['failed', 'interrupted', 'unknown', 'needs_input', 'awaiting_input', 'review', 'awaiting_review', 'queued', 'running'].includes(task.status)) notices.push({ id: task.id, category: ['failed', 'interrupted'].includes(task.status) ? 'failed' : task.status === 'unknown' ? 'unknown' : ['needs_input', 'awaiting_input'].includes(task.status) ? 'input' : ['review', 'awaiting_review'].includes(task.status) ? 'review' : 'active', title: task.input.title || '共享任务', detail: '', target: 'tasks', caseId: task.input.organization_case, status: task.status });
  }
  for (const item of attention.items) notices.push({ id: item.id, category: item.kind, title: item.title, detail: item.detail, target: '', attentionId: item.id });
  for (const alert of data.alerts || []) if (alert.status !== 'resolved') notices.push({ id: alert.id, category: alert.status === 'suspended' || alert.kind === 'data_stale' ? 'stale' : 'input', title: alert.title, detail: [alert.sku, alert.detail].filter(Boolean).join(' · '), target: 'alerts' });
  const order = ['failed', 'unknown', 'stale', 'review', 'input', 'active']; notices.sort((a, b) => order.indexOf(a.category) - order.indexOf(b.category));
  const visible = filter === 'all' ? notices : notices.filter(n => n.category === filter);
  const labels: Record<string, string> = { input: '待补充', review: '待审阅', failed: '失败 / 中断', unknown: '结果未知', stale: '来源失效', active: '进行中' };
  const unread = !data.tasks || !data.alertsComplete || !attention.complete;
  const needsRefresh=!demo&&!!data.live&&(!data.live.configured||!data.live.orders?.fresh||!data.live.stock?.fresh||data.dashboard?.sales_summary?.stale);
  const hints:OperatingHint[]=[];
  if(!demo&&data.live&&!data.live.configured)hints.push({id:'connect',title:'连接经营数据',detail:'接入店铺后读取订单、库存与销售分析。',icon:'store',action:()=>navigate('platforms')});
  else if(needsRefresh)hints.push({id:'fresh',title:'店铺资料待更新',detail:'当前快照缺失或已过期，请核对最新资料。',icon:'clock',action:()=>navigate('platforms')});
  if(data.dashboard?.pending)hints.push({id:'orders',title:'核对待处理发货单',detail:`当前已读快照中有 ${data.dashboard.pending} 条待处理发货单。`,icon:'cart',action:()=>navigate('orders')});
  if(!demo&&data.live?.stock_basis==='unconfirmed')hints.push({id:'stock',title:'确认库存执行口径',detail:'已保留平台原始库存；补货与提醒口径仍待确认。',icon:'box',action:()=>navigate('platforms')});
  const reviews=notices.filter(notice=>notice.category==='review').length;
  if(reviews)hints.push({id:'review',title:'查看待审阅事项',detail:`当前已读范围有 ${reviews} 项等待人工审阅。`,icon:'doc',action:()=>selectFilter('review')});
  const uncertain=notices.filter(notice=>notice.category==='unknown').length,failed=notices.filter(notice=>notice.category==='failed').length;
  if(uncertain)hints.push({id:'uncertain',title:'核对待确认的结果',detail:`${uncertain} 项执行结果尚未确认，可从原记录继续核对。`,icon:'clock',action:()=>selectFilter('unknown')});
  else if(failed)hints.push({id:'failed',title:'核对未完成的执行',detail:`${failed} 项执行未完成或已中断，可从原记录查看原因。`,icon:'clock',action:()=>selectFilter('failed')});
  if(!hints.length&&!loading)hints.push({id:'tasks',title:'继续当前商品工作',detail:'从商品工作区核对资料、成本和交付状态。',icon:'box',action:()=>navigate('workspace')});
  const platform=data.dashboard?.platforms.length===1?data.dashboard.platforms[0].name:'经营数据';
  const sales=data.dashboard?.sales_summary;
  return <div className="r-page r-dashboard" data-ai-page="overview" data-ai-context={JSON.stringify({source:demo?'local':sales?.stale?'stale':data.dashboard?.data_source==='ozon_api'?'live':data.dashboard?.data_source==='not_connected'?'unavailable':'local',filters:{platform:'all',store_id:'all',market:'all',...(sales?{date_from:sales.date_from,date_to:sales.date_to}:{})},source_refs:{...(sales?.source_sha256?{sales:sales.source_sha256}:{}),...(data.dashboard?.inventory?.source_sha256?{stock:data.dashboard.inventory.source_sha256}:{})},errors:data.errors})}>
    <div className="r-page-heading r-dashboard-heading"><div><h1>运营台{demo&&<small className="r-inline-source">示例数据</small>}</h1><div className="r-dashboard-scope"><span><Icon name="store"/>{demo?'示例汇总':platform}{platform==='Ozon'?' · 俄罗斯站':''}</span>{sales&&<span><Icon name="clock"/>{sales.date_from} — {sales.date_to}</span>}<span className="r-dashboard-read-time">{time?`读取于 ${time}`:'正在读取当前资料'}</span>{needsRefresh&&data.live?.configured&&<Badge tone="warning">快照已过期</Badge>}</div></div><div className="r-dashboard-actions">{!demo&&<StatisticsSync active={active} completed={()=>void load()}/>}<Button onClick={()=>{void load();void attention.refresh()}} disabled={loading||attention.loading}>刷新</Button></div></div>
    {data.errors.length>0&&<ErrorNotice>部分资料未读到：{data.errors.join('、')}。当前列表不完整，请刷新核对。</ErrorNotice>}<ErrorNotice>{attention.error||openError}</ErrorNotice>
    {needsRefresh&&!data.live?.configured&&<div className="r-dashboard-data-notice"><Icon name="info"/><span>{!data.live?.configured?'尚未连接店铺，经营指标等待接入。':'当前经营快照缺失或已过期，金额与库存保留原读取时间。'}</span><button onClick={()=>navigate('platforms')}>查看店铺数据<Icon name="chevronDown"/></button></div>}
    <OverviewMetrics dashboard={data.dashboard} orders={data.orders} demo={demo} loading={loading} navigate={navigate}/>
    <div className="r-overview-grid r-dashboard-grid">
      <div className="r-dashboard-priorities"><DashboardPanel title="优先事项" icon="doc" action={<div className="r-dashboard-priority-actions"><Badge tone="blue">{unread?'资料不完整':attention.hasMore?notices.length+'+':notices.length}</Badge><button className="r-dashboard-text-link" onClick={()=>setFollowupId('')}><Icon name="clock"/>复查计划</button></div>}>
        <div className="r-tabs r-dashboard-filters" role="group" aria-label="按待办状态筛选">{[['all','全部'],...Object.entries(labels)].map(([key,label])=><button key={key} aria-pressed={filter===key} onClick={()=>selectFilter(key)}>{label}</button>)}</div>
        {loading||attention.loading?<Empty>正在读取共享记录…</Empty>:visible.length?<div className="r-notices">{(expanded?visible:visible.slice(0,4)).map(n=><button key={n.id} className="r-notice" disabled={!!opening} onClick={()=>void openNotice(n)}><span className={`r-notice-symbol is-${n.category}`}><Icon name={n.category==='review'?'doc':n.category==='stale'?'store':n.category==='active'?'clock':'info'}/></span><div><span className="r-notice-title">{n.title}</span>{n.detail&&<p>{n.detail}</p>}{notices.some(other=>other.id!==n.id&&other.title===n.title)&&<small className="r-notice-reference">{n.target==='tasks'?'本地任务':n.attentionId?'模型与研究':'经营提醒'} · #{n.id.slice(-8)}</small>}</div>{n.status?<Status value={n.status}/>:<Badge tone={n.category==='stale'?'warning':'gray'}>{labels[n.category]}</Badge>}<Icon name="chevronDown"/></button>)}</div>:<Empty>{unread?'尚未完整读取待办，不能判断是否有待处理事项。':!data.live?.configured&&!demo?'当前没有已连接店铺的经营依据。可先接入店铺，或从商品研究开始。':'当前已读范围内没有此类待办。'}</Empty>}
        <div className="r-dashboard-priority-footer">{visible.length>4&&<button className="r-dashboard-text-link" onClick={()=>setExpanded(value=>!value)}>{expanded?'收起列表':`查看全部 ${visible.length} 项`}<Icon name="chevronDown"/></button>}{attention.hasMore&&<Button disabled={attention.moreBusy||attention.loading} onClick={()=>{setExpanded(true);void attention.more()}}>{attention.moreBusy?'正在读取…':'加载更多模型与研究事项'}</Button>}</div>
      </DashboardPanel></div>
      <DashboardChart dashboard={data.dashboard} orders={data.orders} demo={demo} loading={loading} navigate={navigate}/>
      <InventoryAndAlerts dashboard={data.dashboard} alerts={data.alerts} demo={demo} loading={loading} navigate={navigate}/>
      <ProductProgress cases={data.cases} details={caseDetails} loading={loading} navigate={navigate}/>
      <aside className="r-dashboard-rail" aria-label="经营提示与任务"><OperatingHints items={hints.slice(0,3)}/><RecentTasks tasks={data.tasks} navigate={navigate}/></aside>
    </div>
    {followupId!==null&&<Followups demo={demo} followupId={followupId} close={()=>setFollowupId(null)} changed={()=>void attention.refresh()} openOriginal={openOriginal}/>}</div>;
}
