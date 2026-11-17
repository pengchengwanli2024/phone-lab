import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, errorText, newKey } from './api';
import { Badge, Button, Empty, ErrorNotice, Panel } from './ui';
import './operating-control.css';

export interface OperatingControlSnapshot {
  scope: { platform: string; market: string; fulfillment: string; inventory_location: string; sku_status: string; logistics_status: string };
  budget: { configured: boolean; currency: 'CNY'; cap: string | null; occupied: string | null; spent: string | null; available: string | null; status: string; period: 'cumulative_pilot'; enforcement: string };
  mobile: { recommended: 'feishu'; connection_status: string; owner_bound: boolean; commands_ready: boolean; decisions_ready: boolean; setup_steps: string[] };
  autonomy: { status: string; external_business_enabled: boolean; blockers: string[] };
  tasks: { id: string; title: string; intent: string; status: string; created_at?: string }[];
  decisions: { id: string; title: string; status: string; expires_at?: string; detail?: string; can_decide_here: false }[];
  configuration_revision: number;
  store?: { label: string; configured: boolean; orders: StoreSnapshot; stock: StoreSnapshot; sales: StoreSnapshot; orders_scope_confirmed: boolean; automatic_read_enabled: boolean; business_writes_enabled: false } | null;
}
interface StoreSnapshot { available: boolean; fresh: boolean; count: number | null; observed_at: string | null; sha256: string | null }
interface TaskReceipt { task_id: string; title: string; status: string; dispatch_status: 'pending' | 'original_task_state'; external_execution_allowed: false }
type TaskKind = 'research' | 'feature' | 'operations';
type ScopeKey = 'live' | 'synthetic';
interface TaskDraft { kind: TaskKind; title: string; details: string; unknown: boolean; message: string; error: string; receipt: TaskReceipt | null }
const initialDraft = (): TaskDraft => ({ kind: 'research', title: '', details: '', unknown: false, message: '', error: '', receipt: null });
const taskInput = (synthetic: boolean, draft: TaskDraft) => ({ synthetic, kind: draft.kind, title: draft.title.trim(), details: draft.details.trim() });
const kindLabels: Record<TaskKind, string> = { research: '市场与商品研究', feature: '新增或改进功能', operations: '运营处理建议' };
const statuses: Record<string, string> = {
  queued: '待执行', pending: '待处理', scheduled: '已预约', running: '执行中', completed: '已完成', failed: '失败', partial: '部分完成',
  awaiting_input: '待补资料', awaiting_review: '待审阅', unknown: '结果未确认', interrupted: '已中断', cancelled: '已取消', rejected: '已退回',
  expired: '已过期', approved: '已记录决定', needs_setup: '待接入', not_connected: '尚未接通', authorization_required: '待授权',
  configured: '已登记', disabled: '未启用', pending_owner: '待绑定负责人', connected: '已建立连接', ready: '已就绪',
};
const label = (value: string) => statuses[value] || '状态待核对';
const scopeLabel = (value: string, kind: 'sku' | 'logistics') => value === 'api_synced_mapping_pending' ? '平台SKU已保存，本地映射待核对' : ['ready', 'verified', 'configured', 'confirmed', 'connected_verified'].includes(value) ? kind === 'sku' ? 'SKU已登记，执行前复核' : '仓配已登记，执行前复核' : kind === 'sku' ? 'SKU待补充' : '仓库与运输待接入';
const inventoryLabel = (value: string) => value === 'company_local' ? '公司本地库存' : !value || ['pending', 'unknown', 'not_provided'].includes(value) ? '库存地点待确认' : value;
const fulfillmentLabel = (value: string) => !value || ['pending', 'unknown', 'not_provided'].includes(value) ? '履约待确认' : value;

/** Format the ledger's decimal string without losing cents through Number. */
export function operatingMoney(value: unknown): string {
  if (typeof value !== 'string' || !/^-?\d+(?:\.\d{1,2})?$/.test(value)) return '待核对';
  const [whole, fraction = ''] = value.split('.');
  return '¥ ' + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + '.' + fraction.padEnd(2, '0');
}
function validReceipt(value: TaskReceipt): boolean {
  return !!value && typeof value.task_id === 'string' && !!value.task_id && typeof value.title === 'string'
    && typeof value.status === 'string' && !!value.status && value.external_execution_allowed === false
    && (value.status === 'queued' ? value.dispatch_status === 'pending' : value.dispatch_status === 'original_task_state');
}

export function OperatingControl({ synthetic, active = true, onNavigate }: { synthetic: boolean; active?: boolean; onNavigate?: (tab: 'tasks', taskId?: string) => void }) {
  const scope: ScopeKey = synthetic ? 'synthetic' : 'live';
  const [saved, setSaved] = useState<{ scope: ScopeKey; data: OperatingControlSnapshot } | null>(null);
  const [loading, setLoading] = useState<ScopeKey | null>(null), [readError, setReadError] = useState<{ scope: ScopeKey; message: string } | null>(null);
  const [drafts, setDrafts] = useState<Record<ScopeKey, TaskDraft>>({ live: initialDraft(), synthetic: initialDraft() });
  const [submitting, setSubmitting] = useState<Record<ScopeKey, boolean>>({ live: false, synthetic: false });
  const lifecycle = useRef(0), readVersion = useRef(0), inFlight = useRef(new Set<ScopeKey>()), alive = useRef(true);
  const pending = useRef(new Map<ScopeKey, { signature: string; key: string }>());
  const context = useRef({ scope, active }); context.current = { scope, active };
  const input = useRef<HTMLInputElement>(null);
  const data = saved?.scope === scope ? saved.data : null, draft = drafts[scope];
  const busy = submitting[scope] && inFlight.current.has(scope);
  const current = (generation: number, requestedScope: ScopeKey) => alive.current && generation === lifecycle.current && context.current.active && context.current.scope === requestedScope;
  function updateDraft(requestedScope: ScopeKey, change: Partial<TaskDraft>) { setDrafts(previous => ({ ...previous, [requestedScope]: { ...previous[requestedScope], ...change } })); }

  async function load() {
    if (!alive.current || !context.current.active || context.current.scope !== scope) return;
    const requestedScope = scope, generation = lifecycle.current, read = ++readVersion.current;
    setLoading(requestedScope); setReadError(null);
    try {
      const value = await api<OperatingControlSnapshot>('commerce_operating_control_get', { synthetic });
      if (!current(generation, requestedScope) || read !== readVersion.current) return;
      setSaved({ scope: requestedScope, data: value });
    } catch (failure) {
      if (current(generation, requestedScope) && read === readVersion.current) setReadError({ scope: requestedScope, message: errorText(failure) });
    } finally {
      if (current(generation, requestedScope) && read === readVersion.current) setLoading(null);
    }
  }
  useEffect(() => {
    alive.current = true;
    if (active) void load();
    return () => { alive.current = false; lifecycle.current++; readVersion.current++; };
  }, [synthetic, active]);

  function edit(key: 'title' | 'details' | 'kind', value: string) {
    if (!alive.current || !context.current.active || context.current.scope !== scope || inFlight.current.has(scope)) return;
    const next = { ...draft, [key]: value };
    const changed = JSON.stringify(taskInput(synthetic, next)) !== JSON.stringify(taskInput(synthetic, draft));
    if (changed) pending.current.delete(scope);
    updateDraft(scope, changed ? { [key]: value, error: '', message: '', unknown: false, receipt: null } : { [key]: value });
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!alive.current || !active || !context.current.active || context.current.scope !== scope || inFlight.current.has(scope) || !data) return;
    if (!draft.title.trim()) { updateDraft(scope, { error: '请填写任务标题。' }); input.current?.focus(); return; }
    if (draft.title.length > 160 || draft.details.length > 4000) { updateDraft(scope, { error: '任务标题最多160字，详细要求最多4000字。' }); return; }
    const requestedScope = scope, generation = lifecycle.current;
    const args = taskInput(synthetic, draft);
    const signature = JSON.stringify(args);
    let request = pending.current.get(scope);
    if (!request || request.signature !== signature) { request = { signature, key: newKey() }; pending.current.set(scope, request); }
    inFlight.current.add(scope); setSubmitting(previous => ({ ...previous, [scope]: true }));
    // If the page changes scope before the reply, the original key and draft
    // remain available for explicit reconciliation in their original scope.
    updateDraft(scope, { error: '', message: '', unknown: true, receipt: null });
    try {
      const value = await api<TaskReceipt>('commerce_operating_control_task_submit', { ...args, idempotency_key: request.key });
      if (!current(generation, requestedScope)) return;
      if (!validReceipt(value)) throw Error('request_outcome_unknown');
      if (value.dispatch_status === 'pending') {
        pending.current.delete(requestedScope);
        updateDraft(requestedScope, { title: '', details: '', unknown: false, receipt: value, error: '', message: '任务已登记，待派发；尚未执行。' });
      } else {
        updateDraft(requestedScope, { unknown: false, receipt: value, error: '', message: '已查回原任务：' + label(value.status) + '。该请求仍关联原记录。' });
      }
      // This refresh owns its own failure state. A failed list read must never
      // turn a known successful registration back into an unknown submission.
      void load();
    } catch (failure) {
      if (!current(generation, requestedScope)) return;
      const definite = failure instanceof Error && ['idempotency_conflict', 'invalid_arguments', 'operating_control_invalid_task', 'operating_control_task_invalid'].includes(failure.message);
      updateDraft(requestedScope, { unknown: !definite, error: definite ? errorText(failure) : '创建结果尚未确认。输入和原请求键已保留；可刷新任务记录，或以原请求核对登记。' });
    } finally {
      inFlight.current.delete(requestedScope);
      if (alive.current) setSubmitting(previous => ({ ...previous, [requestedScope]: false }));
    }
  }

  if (!active) return null;
  return <div className="r-page r-operating-control">
    <header className="r-page-heading"><div><h1>自动经营控制台</h1><p>集中查看共享预算、登记任务与待决策事项。</p></div><div className="r-actions"><Badge tone={synthetic ? 'warning' : 'blue'}>{synthetic ? '合成演示范围' : '本机经营范围'}</Badge><Button onClick={() => void load()} disabled={loading === scope}>刷新状态</Button></div></header>
    <ErrorNotice>{readError?.scope === scope ? readError.message : ''}</ErrorNotice>
    {!data ? <Empty>{loading === scope ? '正在读取经营配置与原任务…' : '当前范围尚未读到经营配置，请刷新状态。'}</Empty> : <>
      <div className="r-oc-scope" aria-label="当前经营范围"><strong>{data.scope.platform === 'ozon' ? 'Ozon' : data.scope.platform} · {data.scope.market || '市场待确认'} · {fulfillmentLabel(data.scope.fulfillment)}</strong><span>{inventoryLabel(data.scope.inventory_location)}</span><Badge>{scopeLabel(data.scope.sku_status, 'sku')}</Badge><Badge>{scopeLabel(data.scope.logistics_status, 'logistics')}</Badge></div>
      {data.store ? <Panel title="当前 Ozon 店铺" action={<Badge tone={data.store.configured ? 'blue' : 'warning'}>{data.store.configured ? '已保存私有连接' : '待接入'}</Badge>}>
        <p><strong>{data.store.label}</strong></p>
        <dl className="r-oc-state">{([['订单', data.store.orders], ['商品库存', data.store.stock], ['日销售统计', data.store.sales]] as const).map(([title, snapshot]) => <div key={title}><dt>{title}</dt><dd>{snapshot.available ? `${snapshot.count ?? '待核对'} 条 · ${snapshot.fresh ? '快照有效' : '快照已过期，需刷新'}` : '尚未取得完整快照'}</dd></div>)}</dl>
        <p className="r-footnote">{data.store.automatic_read_enabled ? '已开启定时只读同步。' : '定时只读同步尚未启用。'}平台库存不等于公司实物盘点；订单快照也不代表已装箱、发货或收到结算。</p>
      </Panel> : null}
      <Panel title="共享经营预算" action={<Badge tone={data.budget.configured ? 'blue' : 'warning'}>{data.budget.configured ? '累计试运行总额' : '尚未配置'}</Badge>}>
        <dl className="r-oc-budget">{([['预算上限', data.budget.cap], ['预留占用', data.budget.occupied], ['已记支出', data.budget.spent], ['台账可用', data.budget.available]] as const).map(([title, amount]) => <div key={title}><dt>{title}</dt><dd>{operatingMoney(amount)}</dd></div>)}</dl>
        <p className="r-footnote">人民币累计额度由各任务共享，不按角色重复分配，也不自动每日重置。仅统计已登记任务，不代表店铺余额或尚未同步的支出。</p>
        <div className="r-oc-boundary"><span>{data.budget.enforcement === 'ledger_only' ? '当前已提供预算台账与占用校验，外部执行接入范围仍待逐项核对。' : '预算约束的实际执行范围须与对应业务回执一并核对。'}</span><Button disabled title="预算调整须由已绑定的负责人在受信设置中确认">调整预算</Button></div>
        <p className="r-footnote">预算调整需由负责人确认；本页暂未开放修改，不会因填写金额而授权付款或投放。</p>
      </Panel>
      <Panel title="自动运行与待接条件" action={<Badge tone={data.autonomy.external_business_enabled ? 'blue' : 'warning'}>{data.autonomy.external_business_enabled ? '按已授权范围执行' : '外部经营执行尚未启用'}</Badge>}>
        {data.autonomy.blockers.length ? <ul className="r-oc-checks">{data.autonomy.blockers.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="r-footnote">当前返回范围未列出阻塞；实际执行仍受权限、预算与来源版本校验。</p>}
        <p className="r-footnote">默认先完成商品图文和试销，取得可信的同商品销量后再评估视频制作。</p>
      </Panel>
      <div className="r-oc-columns">
        <Panel title="登记新任务">
          <form onSubmit={event => void submit(event)} className="r-oc-task-form" aria-label="登记经营或工程任务">
            <label className="ui-field" htmlFor="oc-task-kind">任务类型<select id="oc-task-kind" name="kind" aria-label="任务类型" value={draft.kind} disabled={busy} onChange={event => edit('kind', event.target.value)}>{Object.entries(kindLabels).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
            <label className="ui-field" htmlFor="oc-task-title">任务标题<input ref={input} id="oc-task-title" name="title" maxLength={160} value={draft.title} disabled={busy} aria-invalid={!!draft.error && !draft.title.trim()} onChange={event => edit('title', event.target.value)} placeholder="例如：调研俄罗斯市场的厨房收纳需求" /></label>
            <label className="ui-field" htmlFor="oc-task-details">详细要求<textarea id="oc-task-details" name="details" rows={5} maxLength={4000} value={draft.details} disabled={busy} onChange={event => edit('details', event.target.value)} placeholder="目标、范围、参考资料与完成条件；请勿填写密码或密钥。" /></label>
            <ErrorNotice>{busy ? '' : draft.error}</ErrorNotice>
            {!busy && draft.unknown && !draft.error ? <p className="r-footnote" role="status">先前创建结果尚未确认，原输入和请求键已保留。</p> : null}
            <div className="r-oc-submit"><Button type="submit" primary disabled={busy}>{busy ? '正在登记…' : draft.unknown ? '以原请求核对登记' : draft.receipt?.dispatch_status === 'original_task_state' ? '核对原任务' : '登记任务'}</Button><span className="r-footnote">登记后进入原任务队列；发布、付款与广告仍需对应权限。</span></div>
            {draft.message ? <p className="r-oc-result" role="status">{draft.message}</p> : null}
            {draft.receipt ? <div className="r-oc-receipt"><strong>{draft.receipt.title}</strong><span className="r-task-id">{draft.receipt.task_id}</span>{onNavigate ? <Button onClick={() => onNavigate('tasks', draft.receipt!.task_id)}>查看原任务</Button> : null}</div> : null}
          </form>
        </Panel>
        <Panel title="手机指挥与确认" action={<Badge tone={data.mobile.connection_status === 'connected' ? 'blue' : 'warning'}>{label(data.mobile.connection_status)}</Badge>}>
          <p>首选飞书应用机器人，接通后在手机发送任务、查询进度，并处理绑定原对象的决策卡片。</p>
          <dl className="r-oc-state"><div><dt>负责人身份</dt><dd>{data.mobile.owner_bound ? '已绑定' : '待绑定'}</dd></div><div><dt>任务指令</dt><dd>{data.mobile.commands_ready ? '解析已就绪，送达以通道状态为准' : '待接通并验收'}</dd></div><div><dt>决策回传</dt><dd>{data.mobile.decisions_ready ? '按准确申请核对' : '待接通并验收'}</dd></div></dl>
          {data.mobile.setup_steps.length ? <ol className="r-oc-checks">{data.mobile.setup_steps.map((step, index) => <li key={index}>{step}</li>)}</ol> : null}
          <details><summary>接通后的指令示例</summary><p className="r-footnote">/新任务 调研俄罗斯厨房收纳需求<br />/功能建议 补充物流停滞提醒<br />/状态<br />/预算查询</p><p className="r-footnote">指令只形成相应任务和回执，不会把聊天文字直接当作执行权限。暂停请求也需查回实际处理结果。</p></details>
        </Panel>
      </div>
      <div className="r-oc-columns">
        <Panel title="任务记录">{data.tasks.length ? <ul className="r-oc-records">{data.tasks.map(task => <li key={task.id}><div className="r-oc-record-heading"><strong>{task.title}</strong><Badge tone={task.status === 'unknown' ? 'warning' : 'gray'}>{label(task.status)}</Badge></div><span className="r-task-id">{task.id}</span><p className="r-footnote">{kindLabels[task.intent as TaskKind] || '原任务'}{task.created_at ? ' · ' + task.created_at : ''}</p>{onNavigate ? <Button onClick={() => onNavigate('tasks', task.id)}>查看原任务</Button> : null}</li>)}</ul> : <Empty>当前范围尚无返回的任务记录。可以先登记一项明确任务。</Empty>}</Panel>
        <Panel title="待决策事项">{data.decisions.length ? <ul className="r-oc-records">{data.decisions.map(decision => <li key={decision.id}><div className="r-oc-record-heading"><strong>{decision.title}</strong><Badge>{label(decision.status)}</Badge></div>{decision.detail ? <p>{decision.detail}</p> : null}{decision.expires_at ? <p className="r-footnote">有效期：{decision.expires_at}</p> : null}<p className="r-footnote">本页仅展示。通过已核验身份的原审批入口确认；通知送达不代表已批准或执行。</p></li>)}</ul> : <Empty>当前没有返回的待决策事项。手机身份和回传仍需单独验收。</Empty>}</Panel>
      </div>
    </>}
  </div>;
}
