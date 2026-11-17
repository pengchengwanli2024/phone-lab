import { Badge, Button, Empty, Icon } from './ui';
import { useEffect, useId, useRef, useState } from 'react';
import { api, errorText } from './api';
import { salesSeries, salesPageContext, inventoryPageContext } from './overview-model';

export interface SalesSummary {
  date_from: string; date_to: string; ordered_units: number; records: { day: string; amount: string; ordered_units: number }[];
  stale: boolean; observed_at: string; source_sha256: string; definition_url: string;
}
export interface InventorySummary {
  source_sha256?: string;
  sku_count: number; stale: boolean; observed_at: string; scope: string; orderable_basis: string;
  groups: { type: string; rows: number; present: number; reserved: number; orderable_api: number | null; inconsistent_rows: number }[];
}
const number = (value: number) => value.toLocaleString('zh-CN', { maximumFractionDigits: 4 });
const sourceTime = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });

export function SalesTrend({sales,loading,metric:chosenMetric,embedded=false}:{sales?:SalesSummary|null;loading:boolean;metric?:'amount'|'units';embedded?:boolean}) {
  const [localMetric,setMetric]=useState<'amount'|'units'>('amount'),titleId=useId(),metric=chosenMetric||localMetric;
  const rows=salesSeries(sales,metric),rawMax=Math.max(1,...rows.map(row=>row.value)),max=metric==='units'?Math.ceil(rawMax/4)*4:rawMax;
  const x=(index:number)=>20+960*index/Math.max(1,rows.length-1),y=(value:number)=>200-180*value/max;
  const points=rows.map((row,index)=>`${x(index)},${y(row.value)}`).join(' ');
  const ticks=[...new Set(Array.from({length:Math.min(5,rows.length)},(_,i)=>Math.round(i*(rows.length-1)/Math.max(1,Math.min(5,rows.length)-1))))];
  const context=salesPageContext(sales,metric);
  return <section className="r-sales-trend" tabIndex={0} aria-label="销售趋势" data-ai-context={JSON.stringify(context)}>
    {!embedded&&<div className="r-trend-top"><h3 id={titleId}>销售趋势 · {metric==='amount'?'下单金额':'下单件数'}</h3><div className="r-chart-switch" role="group" aria-label="销售趋势指标"><button aria-pressed={metric==='amount'} onClick={()=>setMetric('amount')}>下单金额</button><button aria-pressed={metric==='units'} onClick={()=>setMetric('units')}>下单件数</button></div></div>}
    {loading?<Empty>正在读取趋势…</Empty>:!sales||!sales.records.length?<Empty>尚无完整的销售分析快照，请同步店铺数据。</Empty>:<>
      <div className="r-trend-summary"><div><strong className={metric==='amount'?'r-trend-label':undefined}>{metric==='amount'?'下单金额':number(sales.ordered_units)}</strong><span>{metric==='amount'?'平台原值 · 币种未返回':'下单件数 · 件'}</span></div>{sales.stale?<Badge tone="warning">销售快照已过期</Badge>:<Badge tone="blue">真实快照</Badge>}</div>
      <p className="r-trend-range">{sales.date_from} — {sales.date_to} · {rows.length} 个平台日</p>
      <div className="r-sales-plot"><div className="r-chart-y" aria-hidden="true">{[1,.75,.5,.25,0].map(ratio=><span key={ratio}>{(max*ratio).toLocaleString('zh-CN',{maximumFractionDigits:metric==='units'?0:1})}</span>)}</div><div className="r-chart-drawing">
        <svg className="r-sales-chart" viewBox="0 0 1000 220" preserveAspectRatio="none" role="img" aria-label={`${metric==='amount'?'下单金额':'下单件数'}趋势，${sales.date_from}至${sales.date_to}，${rows.length}个真实日数据点，${metric==='amount'?'币种未返回':'单位件'}`}>
          {[20,65,110,155,200].map(value=><line key={value} x1="0" x2="1000" y1={value} y2={value} />)}
          {metric==='amount'?<><polygon className="r-chart-area" points={`20,200 ${points} ${x(rows.length-1)},200`} /><polyline points={points}/>{rows.map((row,index)=><circle key={row.day} cx={x(index)} cy={y(row.value)} r={rows.length>14?3:4} aria-label={`${row.day}：${number(row.value)}，币种未返回`}><title>{row.day} · {number(row.value)} · 币种未返回</title></circle>)}</>:rows.map((row,index)=><rect className="r-chart-bar" key={row.day} x={x(index)-Math.min(20,480/Math.max(1,rows.length))} y={y(row.value)} width={Math.min(40,960/Math.max(1,rows.length))} height={200-y(row.value)} rx="3"><title>{row.day} · {row.value} 件</title></rect>)}
        </svg><div className="r-chart-x" aria-hidden="true">{ticks.map(index=><span key={index}>{rows[index].day.slice(5)}</span>)}</div>
      </div></div>
      <div className="r-trend-foot"><span><i/> {metric==='amount'?'下单金额':'下单件数'}</span><details className="r-chart-source"><summary><Icon name="info"/> 数据口径</summary><p>读取于 {sourceTime(sales.observed_at)}（北京时间）。下单金额沿用平台 revenue 定义，与实收、结算金额口径不同。按平台日统计，币种未返回，不做汇率折算。</p></details></div>
      <details className="r-sales-details"><summary>按日明细（{rows.length} 天）</summary><div className="r-table-wrap" role="region" aria-label="按日下单金额" tabIndex={0}><table><thead><tr><th>平台日</th><th>下单金额（币种未返回）</th><th>下单件数</th></tr></thead><tbody>{sales.records.map(row=><tr key={row.day}><td>{row.day}</td><td>{number(Number(row.amount))}</td><td>{number(row.ordered_units)}</td></tr>)}</tbody></table></div></details>
    </>}
  </section>;
}

export function InventoryStatistics({inventory,loading,embedded=false}:{inventory?:InventorySummary|null;loading:boolean;embedded?:boolean}) {
  return <section className="r-inventory-statistics" tabIndex={0} aria-label="真实库存统计" data-ai-context={JSON.stringify(inventoryPageContext(inventory))}>
    {!embedded&&<h3>库存统计</h3>}
    {loading?<Empty>正在读取库存…</Empty>:!inventory?<Empty>尚无库存快照，请同步店铺数据。</Empty>:<>
      <div className="r-inventory-caption"><span>{number(inventory.sku_count)} 个商品 · {inventory.scope}</span>{inventory.stale&&<Badge tone="warning">库存快照已过期</Badge>}</div>
      <div className="r-table-wrap" role="region" aria-label="按履约方式的库存统计" tabIndex={0}><table><thead><tr><th>履约方式</th><th>库存条目</th><th>现有数</th><th>预留数</th><th>可下单数（API）</th></tr></thead><tbody>{inventory.groups.map(row=><tr key={row.type}><td>{row.type.toUpperCase()}</td><td>{number(row.rows)}</td><td>{number(row.present)}</td><td>{number(row.reserved)}</td><td>{row.orderable_api==null?`待核对（${row.inconsistent_rows} 条异常）`:number(row.orderable_api)}</td></tr>)}</tbody></table></div>
      <details className="r-inventory-source"><summary>库存口径与来源</summary><p>可下单数 = {inventory.orderable_basis}。补货与提醒执行口径仍按原确认状态。读取于 {sourceTime(inventory.observed_at)}（北京时间）。</p></details>
    </>}
  </section>;
}
export function OperatingCharts({sales,inventory,loading}:{sales?:SalesSummary|null;inventory?:InventorySummary|null;loading:boolean}) {
  return <div className="r-operating-charts"><SalesTrend sales={sales} loading={loading}/><InventoryStatistics inventory={inventory} loading={loading}/></div>;
}

type Job = { id: string; status: string; result?: Record<string, { status: string; code?: string }> };
export function StatisticsSync({ active, completed }: { active: boolean; completed: () => void }) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  const revision = useRef(0), completedRef = useRef(completed); completedRef.current = completed;
  useEffect(() => { return () => { revision.current++; setBusy(false); }; }, [active]);
  async function sync() {
    if (busy) return;
    const current = ++revision.current; setBusy(true); setMessage('正在只读同步订单、库存与销售分析…');
    const valid = () => current === revision.current;
    try {
      const started = await api<Job>('commerce_live_sync');
      if (!started.id) throw Error('同步任务未确认，请稍后刷新核对。');
      for (let i = 0; i < 65 && valid(); i++) {
        const status = await api<{ last_job: Job | null }>('commerce_live_status');
        if (!valid()) return;
        const job = status.last_job;
        if (job?.id === started.id && job.status !== 'running') {
          const names: Record<string, string> = { orders: '订单', stock: '库存', sales: '销售分析' };
          const failed = Object.entries(job.result || {}).filter(([, value]) => value.status !== 'success');
          setMessage(failed.length ? `部分资料未更新：${failed.map(([key, value]) => (names[key] || key) + (value?.code === 'ozon_rate_limited' ? '（平台限流，请稍后重试）' : value?.code === 'ozon_auth_or_permission' ? '（读取权限不足）' : '（请稍后核对）')).join('、')}。原快照保留。` : job.status === 'success' ? '订单、库存与销售分析已同步。' : '同步未完成，请稍后核对。原快照保留。');
          completedRef.current(); return;
        }
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
      if (valid()) setMessage('同步尚未确认完成，请稍后刷新核对；不会重复发起。');
    } catch (error) { if (valid()) setMessage(`同步结果未确认：${errorText(error)}`); }
    finally { if (valid()) setBusy(false); }
  }
  return <div className="r-statistics-sync"><Button onClick={() => void sync()} disabled={busy || !active}>{busy ? '正在同步…' : '同步店铺数据'}</Button>{message && <span role="status">{message}</span>}</div>;
}
