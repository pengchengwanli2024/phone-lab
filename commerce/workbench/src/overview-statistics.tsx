import { Badge, Button, Empty, Icon, Money, Panel } from './ui';
import './overview-statistics.css';
import { OperatingCharts, type SalesSummary, type InventorySummary } from './operating-charts';

export interface Dashboard {
  sales: number | null; currency: string; orders: number | null; pending: number | null; stock_alerts: number | null;
  orders_label?: string; pending_label?: string; data_source: string; rate_note: string;
  platforms: { id: string; name: string; amount: number }[];
  sales_label?: string; sales_summary?: SalesSummary | null; inventory?: InventorySummary | null;
}
export interface OrderSnapshot {
  orders: { status: string; status_zh?: string }[]; total: number; data_source: string;
  stale?: boolean; scope_confirmed?: boolean; observed_at?: string;
}

interface StatisticsProps { dashboard?: Dashboard; orders?: OrderSnapshot; demo: boolean; loading: boolean; navigate: (tab: string) => void }

export function OverviewStatistics(props:StatisticsProps) { return <><OverviewMetrics {...props}/><div className="r-overview-statistics"><Panel title="经营概览" action={<Button onClick={()=>props.navigate('orders')}>查看订单</Button>}><StatisticsDistribution {...props}/>{!props.demo&&<OperatingCharts sales={props.dashboard?.sales_summary} inventory={props.dashboard?.inventory} loading={props.loading}/>}</Panel></div></>; }

export function OverviewMetrics({dashboard,demo,loading}:StatisticsProps) {
  const count=(value:number|null|undefined)=>loading?'…':value==null?'待读取 / 核对':value.toLocaleString('zh-CN');
  return <div className="r-metrics r-overview-metrics" aria-label="经营指标">
    <div><span>{dashboard?.sales_label || (demo?'支付销售额':'下单金额（平台口径）')}</span><strong>{loading?'…':dashboard?.sales==null?'待核对':demo?<Money value={dashboard.sales} currency={dashboard.currency}/>:<span className="r-number">{dashboard.sales.toLocaleString('zh-CN',{maximumFractionDigits:4})}{dashboard.currency&&<small> {dashboard.currency}</small>}</span>}</strong><i className="r-metric-icon"><Icon name="chart"/></i><small>{dashboard?.sales_summary?dashboard.sales_summary.records.length+' 个平台日 · ':''}{!loading&&dashboard?.sales!=null&&!dashboard.currency?'API 未返回币种':demo?'示例汇总':'按平台下单口径'}</small></div>
    <div><span>{dashboard?.orders_label||(demo?'订单数':'同步发货单')}</span><strong>{count(dashboard?.orders)}</strong><i className="r-metric-icon"><Icon name="cart"/></i><small>{demo?'示例汇总':'当前同步范围'}</small></div>
    <div><span>{dashboard?.pending_label||(demo?'待处理订单':'待处理发货单')}</span><strong>{count(dashboard?.pending)}</strong><i className="r-metric-icon"><Icon name="clock"/></i><small>{demo?'示例汇总':'当前发货单快照'}</small></div>
    <div><span>库存提醒</span><strong className={dashboard?.stock_alerts==null&&!loading?'r-metric-empty':undefined}>{count(dashboard?.stock_alerts)}</strong><i className="r-metric-icon"><Icon name="box"/></i><small>{dashboard?.inventory?.stale?'快照过期 · 待核对':dashboard?.stock_alerts==null?'等待口径与资料核对':'当前已确认范围'}</small></div>
  </div>;
}

export function StatisticsDistribution({ dashboard, orders, demo, loading, navigate }: {
  dashboard?: Dashboard; orders?: OrderSnapshot; demo: boolean; loading: boolean; navigate: (tab: string) => void;
}) {
  const counts = new Map<string, { label: string; count: number }>();
  for (const row of orders?.orders || []) {
    const current = counts.get(row.status);
    if (current) current.count++;
    else counts.set(row.status, { label: row.status_zh || row.status || '未知状态', count: 1 });
  }
  const statuses = [...counts].sort((a, b) => b[1].count - a[1].count);
  const largestCount = Math.max(1, ...statuses.map(([, row]) => row.count));
  const platforms = dashboard?.platforms || [];
  const largestAmount = Math.max(1, ...platforms.map(row => row.amount));
  const observed = orders?.observed_at ? new Date(orders.observed_at) : undefined;
  const observedText = observed && Number.isFinite(observed.getTime()) ? observed.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '';

  return       <div className="r-statistics-columns">
        <section aria-label="发货单状态统计" data-ai-context={JSON.stringify({section:"order-status",entity:{kind:"chart",id:"order-status"}})}><h3>{demo ? '订单状态' : '发货单状态'}</h3>
          {loading ? <Empty>正在读取统计…</Empty> : !orders ? <Empty>发货单统计未读到，请刷新重试。</Empty> : orders.data_source === 'not_connected' ? <Empty>尚无发货单快照。接入并读取店铺数据后展示统计。</Empty> : <>
            <p className="r-statistics-note">当前{demo ? '示例列表' : '同步快照'}共 {orders.orders.length.toLocaleString('zh-CN')} 条{demo ? '订单' : '发货单'}{demo ? '，与汇总指标的示例范围不同。' : '，仅代表已读取范围。'}</p>
            {!demo && <div className="r-statistics-flags">{orders.stale && <Badge tone="warning">快照已过期</Badge>}{orders.scope_confirmed === false && <Badge tone="warning">同步范围待确认</Badge>}</div>}
            {statuses.length ? <ul className="r-statistics-bars" aria-label={demo ? '示例订单状态分布' : '发货单状态分布'}>{statuses.map(([status, row]) => <li key={status}><span>{row.label}</span><strong>{row.count.toLocaleString('zh-CN')} 条</strong><div className="r-statistics-track" aria-hidden="true"><i style={{ width: `${row.count / largestCount * 100}%` }} /></div></li>)}</ul> : <Empty>当前快照没有发货单。</Empty>}
            {!demo && observedText && <p className="r-statistics-note">快照时间 {observedText}（北京时间）</p>}
          </>}
        </section>
        <section aria-label="平台销售统计" data-ai-context={JSON.stringify({section:"platform-sales",entity:{kind:"chart",id:"platform-sales"}})}><h3>平台销售构成</h3>
          {loading ? <Empty>正在读取统计…</Empty> : !dashboard ? <Empty>销售统计未读到，请刷新重试。</Empty> : platforms.length ? <ul className="r-statistics-bars" aria-label={demo ? '示例平台销售构成' : '平台销售构成'}>{platforms.map(row => <li key={row.id}><span>{row.name}</span><strong><Money value={row.amount} currency={dashboard.currency} /></strong><div className="r-statistics-track" aria-hidden="true"><i style={{ width: `${Math.max(0, row.amount) / largestAmount * 100}%` }} /></div></li>)}</ul> : <Empty>尚无经过核对的销售额与趋势数据。<br /><Button onClick={() => navigate('platforms')}>查看店铺数据</Button></Empty>}
        </section>
      </div>;
}
