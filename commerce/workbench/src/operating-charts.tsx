import { Badge, Button, Empty } from './ui';
import { useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';

export interface SalesSummary {
  date_from: string; date_to: string; ordered_units: number; records: { day: string; amount: string; ordered_units: number }[];
  stale: boolean; observed_at: string; source_sha256: string; definition_url: string;
}
export interface InventorySummary {
  sku_count: number; stale: boolean; observed_at: string; scope: string; orderable_basis: string;
  groups: { type: string; rows: number; present: number; reserved: number; orderable_api: number | null; inconsistent_rows: number }[];
}
const number = (value: number) => value.toLocaleString('zh-CN', { maximumFractionDigits: 4 });
const sourceTime = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });

export function OperatingCharts({ sales, inventory, loading }: { sales?: SalesSummary | null; inventory?: InventorySummary | null; loading: boolean }) {
  const rows = sales?.records || [], max = Math.max(1, ...rows.map(row => Number(row.amount)));
  const points = rows.map((row, i) => `${96 + i * 496 / Math.max(1, rows.length - 1)},${176 - Number(row.amount) / max * 140}`);
  const dates = rows.filter((_, i) => i === 0 || i === rows.length - 1 || i === Math.floor(rows.length / 2));
  return <div className="r-operating-charts">
    <section aria-label="销售趋势"><h3>销售趋势 · 下单金额</h3>
      {loading ? <Empty>正在读取趋势…</Empty> : !sales ? <Empty>尚无完整的销售分析快照，请同步店铺数据。</Empty> : <>
        <p className="r-statistics-note">{sales.date_from} — {sales.date_to} · 按平台日 · 下单 {number(sales.ordered_units)} 件 · 币种未返回</p>
        {sales.stale && <Badge tone="warning">销售快照已过期</Badge>}
        <svg className="r-sales-chart" viewBox="0 0 624 212" role="img" aria-label={`下单金额趋势，${sales.date_from}至${sales.date_to}，${rows.length}个真实日数据点，币种未返回`}>
          {[0, 1, 2].map(i => <g key={i}><line x1="96" x2="592" y1={176-i*70} y2={176-i*70} /><text x="88" y={180-i*70} textAnchor="end">{(max*i/2).toLocaleString('zh-CN',{maximumFractionDigits:1})}</text></g>)}
          {points.length > 0 && <polyline points={points.join(' ')} />}
          {dates.map(row => <text key={row.day} x={96+rows.indexOf(row)*496/Math.max(1,rows.length-1)} y="202" textAnchor="middle">{row.day.slice(5)}</text>)}
        </svg>
        <details className="r-sales-details"><summary>按日明细（{rows.length} 天）</summary><div className="r-table-wrap" role="region" aria-label="按日下单金额" tabIndex={0}><table><thead><tr><th>平台日</th><th>下单金额（币种未返回）</th><th>下单件数</th></tr></thead><tbody>{rows.map(row => <tr key={row.day}><td>{row.day}</td><td>{number(Number(row.amount))}</td><td>{number(row.ordered_units)}</td></tr>)}</tbody></table></div></details>
        <p className="r-statistics-note">读取于 {sourceTime(sales.observed_at)}（北京时间）。下单金额沿用平台 revenue 定义，与实收、结算金额口径不同。</p>
      </>}
    </section>
    <section aria-label="真实库存统计"><h3>库存统计</h3>
      {loading ? <Empty>正在读取库存…</Empty> : !inventory ? <Empty>尚无库存快照，请同步店铺数据。</Empty> : <>
        <p className="r-statistics-note">{number(inventory.sku_count)} 个商品 · {inventory.scope}</p>
        {inventory.stale && <Badge tone="warning">库存快照已过期</Badge>}
        <div className="r-table-wrap" role="region" aria-label="按履约方式的库存统计" tabIndex={0}><table><thead><tr><th>履约方式</th><th>库存条目</th><th>现有数</th><th>预留数</th><th>可下单数（API）</th></tr></thead><tbody>{inventory.groups.map(row => <tr key={row.type}><td>{row.type.toUpperCase()}</td><td>{number(row.rows)}</td><td>{number(row.present)}</td><td>{number(row.reserved)}</td><td>{row.orderable_api == null ? `待核对（${row.inconsistent_rows} 条异常）` : number(row.orderable_api)}</td></tr>)}</tbody></table></div>
        <p className="r-statistics-note">可下单数 = {inventory.orderable_basis}。补货与提醒执行口径仍按原确认状态。读取于 {sourceTime(inventory.observed_at)}（北京时间）。</p>
      </>}
    </section>
  </div>;
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
