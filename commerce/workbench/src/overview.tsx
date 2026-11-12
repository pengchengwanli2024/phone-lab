import { useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import type { CaseItem, LiveStatus, OpsAlert, Task } from './types';
import { Badge, Button, Empty, ErrorNotice, Icon, Panel, Status } from './ui';

interface Dashboard { orders: number | null; pending: number | null; stock_alerts: number | null; orders_label?: string; pending_label?: string; data_source: string }
interface OverviewData { dashboard?: Dashboard; tasks?: Task[]; cases?: CaseItem[]; alerts?: OpsAlert[]; live?: LiveStatus; errors: string[] }
type Notice = { id: string; category: string; title: string; detail: string; target: string; caseId?: string; status?: string };
export function Overview({ demo, navigate }: { demo: boolean; navigate: (tab: string, caseId?: string) => void }) {
  const [data, setData] = useState<OverviewData>({ errors: [] }), [loading, setLoading] = useState(true), [filter, setFilter] = useState('all'), [time, setTime] = useState('');
  const version = useRef(0);
  async function load() {
    const revision = ++version.current; setLoading(true);
    const results = await Promise.allSettled([
      api<Dashboard>('commerce_dashboard', { demo }), api<{ tasks: Task[] }>('commerce_task_list'),
      api<{ items: CaseItem[] }>('commerce_workspace_list'), api<{ alerts: OpsAlert[] }>('commerce_live_alerts'),
      api<{ alerts: OpsAlert[] }>('commerce_ops_list', { demo }), api<LiveStatus>('commerce_live_status'),
    ]);
    if (revision !== version.current) return;
    const [dashboard, tasks, cases, liveAlerts, opsAlerts, live] = results;
    const names = ['经营数据', '共享任务', '商品工作项', '店铺提醒', '导入提醒', '连接状态'];
    setData({ dashboard: dashboard.status === 'fulfilled' ? dashboard.value : undefined, tasks: tasks.status === 'fulfilled' ? tasks.value.tasks : undefined, cases: cases.status === 'fulfilled' ? cases.value.items.filter(c => c.synthetic === demo) : undefined, live: live.status === 'fulfilled' ? live.value : undefined,
      alerts: liveAlerts.status === 'fulfilled' && opsAlerts.status === 'fulfilled' ? [...(demo ? [] : liveAlerts.value.alerts), ...opsAlerts.value.alerts] : undefined,
      errors: results.flatMap((r, i) => r.status === 'rejected' ? [names[i]] : []),
    });
    setTime(new Date().toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit' })); setLoading(false);
  }
  useEffect(() => { void load(); return () => { version.current++; }; }, [demo]);
  const notices: Notice[] = [];
  for (const task of data.tasks || []) {
    if (['failed', 'interrupted', 'unknown', 'needs_input', 'awaiting_input', 'review', 'awaiting_review', 'queued', 'running'].includes(task.status)) notices.push({ id: task.id, category: ['failed', 'interrupted'].includes(task.status) ? 'failed' : task.status === 'unknown' ? 'unknown' : ['needs_input', 'awaiting_input'].includes(task.status) ? 'input' : ['review', 'awaiting_review'].includes(task.status) ? 'review' : 'active', title: task.input.title || '共享任务', detail: '', target: 'tasks', caseId: task.input.organization_case, status: task.status });
  }
  for (const alert of data.alerts || []) if (alert.status !== 'resolved') notices.push({ id: alert.id, category: alert.status === 'suspended' || alert.kind === 'data_stale' ? 'stale' : 'input', title: alert.title, detail: [alert.sku, alert.detail].filter(Boolean).join(' · '), target: 'alerts' });
  const order = ['failed', 'unknown', 'stale', 'review', 'input', 'active']; notices.sort((a, b) => order.indexOf(a.category) - order.indexOf(b.category));
  const visible = filter === 'all' ? notices : notices.filter(n => n.category === filter);
  const labels: Record<string, string> = { input: '待补充', review: '待审阅', failed: '失败 / 中断', unknown: '结果未知', stale: '来源失效', active: '进行中' };
  const unread = !data.tasks || !data.alerts;
  return <div className="r-page"><div className="r-page-heading"><div><h1>运营台{demo && <small className="r-inline-source">示例数据</small>}</h1><p>{time ? `读取于 ${time}` : '从当前工作继续，处理需要你介入的事项。'}</p></div><Button onClick={() => void load()} disabled={loading} icon="refresh">刷新</Button></div>{data.errors.length > 0 && <ErrorNotice>部分资料未读到：{data.errors.join('、')}。当前列表不完整，请刷新核对。</ErrorNotice>}
    {!demo && data.live && (!data.live.configured || !data.live.orders?.fresh || !data.live.stock?.fresh) && <section className="r-setup-strip"><Icon name="store" /><div><strong>{!data.live.configured ? '尚未连接店铺' : '店铺资料待更新'}</strong><p>{!data.live.configured ? '接入后读取店铺资料。' : '快照缺失或已过期。'}</p></div><Button primary onClick={() => navigate('platforms')}>查看店铺数据</Button></section>}
    <div className="r-metrics">{[[data.dashboard?.orders_label || '同步发货单', data.dashboard?.orders], [data.dashboard?.pending_label || '待处理发货单', data.dashboard?.pending], ['库存提醒', data.dashboard?.stock_alerts]].map(([label, value]) => <div key={String(label)}><span>{label}</span><strong>{loading ? '…' : value == null ? '待读取 / 核对' : value.toLocaleString()}</strong></div>)}</div>
    <div className="r-overview-grid"><Panel title="需要处理" action={<Badge tone="blue">{unread ? '资料不完整' : notices.length}</Badge>}><div className="r-tabs" role="group" aria-label="按待办状态筛选">{[['all', '全部'], ...Object.entries(labels)].map(([key, label]) => <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}</div>{loading ? <Empty>正在读取共享记录…</Empty> : visible.length ? <div className="r-notices">{visible.slice(0, 30).map(n => <button key={n.id} className="r-notice" onClick={() => navigate(n.target, n.caseId)}><div><span className="r-notice-title">{n.title}</span>{n.detail&&<p>{n.detail}</p>}</div>{n.status ? <Status value={n.status} /> : <Badge tone={n.category === 'stale' ? 'warning' : 'gray'}>{labels[n.category]}</Badge>}<Icon name="chevronDown" /></button>)}</div> : <Empty>{unread ? '尚未完整读取待办，不能判断是否有待处理事项。' : !data.live?.configured && !demo ? '当前没有已连接店铺的经营依据。可先接入店铺，或从商品研究开始。' : '当前已读范围内没有此类待办。'}</Empty>}</Panel>
    <Panel title="继续商品工作" action={<Button onClick={() => navigate('workspace')}>查看全部</Button>}>{data.cases?.length ? data.cases.slice(0, 6).map(item => <button key={item.id} className="r-object-row" onClick={() => navigate('workspace', item.id)}><span className="r-object-icon"><Icon name="box" /></span><div><strong>{item.name}</strong><p>{[item.platform, item.market, item.candidate ? '候选' : '', (data.cases||[]).filter(c=>c.name===item.name).length>1?'#'+item.id.slice(0,8):''].filter(Boolean).join(' · ')}</p></div><Icon name="chevronDown" /></button>) : <Empty>暂无当前模式的商品工作项。<br /><Button onClick={() => navigate('pilots')}>查看已有候选</Button></Empty>}<div className="r-quick-actions"><Button onClick={() => navigate('operations')} icon="doc">成本测算</Button><Button onClick={() => navigate('research')} icon="search">调研资料</Button><Button onClick={() => navigate('tasks')} icon="clock">共享任务</Button></div></Panel></div></div>;
}
