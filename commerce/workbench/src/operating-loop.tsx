import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api } from './api';
import { Badge, Button, Empty, ErrorNotice, Panel } from './ui';
import { defaultStages, grantLabel, grantState, groupWork, levelName, loopError, outcomeText, ownerName, stageWarnings, workStatus,
  type LoopGrant, type LoopOutcome, type LoopTarget, type LoopView, type LoopWork } from './operating-loop-state';
import './operating-loop.css';

interface Choice {target:LoopTarget;name:string;sku?:string}
interface Draft {choice:string;level:'observe'|'prepare';stages:string[];limit:number}

/**
 * Operating loop: grants are explicit, start disabled, and never include a store write,
 * payment or message. A decision here reuses the original review path on the server.
 */
export function OperatingLoopPanel({ synthetic, active = true, onNavigate }: { synthetic: boolean; active?: boolean; onNavigate?: (tab: 'tasks', taskId?: string) => void }) {
  const [view, setView] = useState<LoopView | null>(null), [choices, setChoices] = useState<Choice[] | null>(null);
  const [loading, setLoading] = useState(false), [busy, setBusy] = useState(''), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [editing, setEditing] = useState(false), [draft, setDraft] = useState<Draft>({ choice: '', level: 'observe', stages: [], limit: 3 });
  const version = useRef(0), alive = useRef(true), scope = useRef(synthetic); scope.current = synthetic;

  async function load() {
    const read = ++version.current, requested = synthetic; setLoading(true);
    try {
      const value = await api<LoopView>('commerce_operating_loop_get');
      if (alive.current && read === version.current && scope.current === requested) { setView(value); setError(''); }
    } catch (failure) {
      // A failed read must not look like "no grants" or "nothing to decide".
      if (alive.current && read === version.current) { setView(null); setError(loopError(failure)); }
    } finally { if (alive.current && read === version.current) setLoading(false); }
  }
  useEffect(() => { alive.current = true; setView(null); setChoices(null); setEditing(false); setNotice(''); if (active) void load(); return () => { alive.current = false; version.current++; }; }, [synthetic, active]);

  async function run(key: string, action: () => Promise<string>) {
    if (busy) return;
    setBusy(key); setError(''); setNotice('');
    try { const message = await action(); if (alive.current) setNotice(message); }
    catch (failure) { if (alive.current) setError(loopError(failure)); }
    finally { if (alive.current) { setBusy(''); void load(); } }
  }
  const toggle = (grant: LoopGrant) => run('grant:' + grant.id, async () => {
    await api('commerce_operating_loop_grant_enable', { grant_id: grant.id, expected_revision: grant.revision, enabled: !grant.enabled });
    return grant.enabled ? '已停用。已发出的请求不会被撤回，可在下方继续核对。' : '已启用。回路每分钟最多检查一次，证据不变不会重复派发。';
  });
  const advance = (grant: LoopGrant) => run('advance:' + grant.id, async () => outcomeText((await api<LoopOutcome>('commerce_operating_loop_advance', { grant_id: grant.id })).reason));
  const decide = (work: LoopWork, decision: 'approve' | 'reject', proposalId?: string) => run('work:' + work.id, async () => {
    await api('commerce_operating_loop_decide', { work_id: work.id, decision, expected_result_sha256: work.result_sha256, ...(proposalId ? { proposal_id: proposalId } : {}) });
    return decision === 'approve' ? '已批准，原岗位交接任务已登记。这不代表资料已补齐或任何店铺操作已执行。' : '已驳回，未创建任务。';
  });
  const resolve = (work: LoopWork) => run('work:' + work.id, async () => {
    await api('commerce_operating_loop_resolve', { work_id: work.id, note: '' });
    return '已核对关闭，未重发原请求。';
  });

  async function openForm() {
    setEditing(true); setError('');
    setDraft(value => ({ ...value, stages: value.stages.length ? value.stages : defaultStages(view?.stage_catalog || []) }));
    if (choices) return;
    try {
      const value = await api<{ items: Choice[] }>('commerce_listing_directory', { demo: synthetic, offset: 0, limit: 25 });
      if (alive.current) setChoices((value.items || []).filter(item => item?.target?.case_id && item.target.store_ref && item.target.market));
    } catch (failure) { if (alive.current) { setChoices([]); setError(loopError(failure)); } }
  }
  function save(event: FormEvent) {
    event.preventDefault();
    const choice = choices?.[Number(draft.choice)];
    if (!choice) { setError('请选择一件已保存上架方案的商品。'); return; }
    if (!draft.stages.length) { setError('请至少选择一个阶段。'); return; }
    const existing = view?.grants.find(grant => grant.goal === 'launch' && (['case_id', 'platform', 'store_ref', 'market'] as const).every(key => grant.target[key] === choice.target[key]));
    void run('save', async () => {
      await api('commerce_operating_loop_grant_save', { target: choice.target, goal: 'launch', stages: draft.stages, level: draft.level, max_runs_per_day: draft.limit, expected_revision: existing?.revision || 0 });
      if (alive.current) setEditing(false);
      return '授权已保存，仍为未启用。核对范围后再点“启用”。';
    });
  }

  if (!active) return null;
  const grants = (view?.grants || []).filter(grant => grant.synthetic === synthetic), groups = groupWork(view, synthetic);
  const catalog = view?.stage_catalog || [], warnings = stageWarnings(catalog, draft.stages);
  const item = (work: LoopWork, extra?: React.ReactNode) => { const status = workStatus(work.status), grant = view?.grants.find(row => row.id === work.grant_id); return <li key={work.id}>
    <div className="r-oc-record-heading"><strong>{grant ? grantLabel(grant) : '商品待核对'} · {work.stage_name}</strong><Badge tone={status.tone}>{status.label}</Badge></div>
    <span className="r-footnote">负责：{ownerName(work.owner)}{work.executor === 'local_calculator' ? ' · 确定性计算，未调用模型' : work.executor ? '' : ' · 未调用模型'}</span>
    {extra}
  </li>; };
  const missing = (work: LoopWork) => work.missing?.length ? <ul>{work.missing.slice(0, 4).map((text, index) => <li key={index}>{text}</li>)}</ul> : null;

  return <Panel title="经营回路" action={<div className="r-actions"><Badge tone="gray">不含店铺写入、付款或消息</Badge><Button onClick={() => void load()} disabled={loading}>刷新</Button></div>}>
    <ErrorNotice>{error}</ErrorNotice>
    {notice ? <p className="r-oc-result r-loop-status" role="status">{notice}</p> : null}
    {!view ? <Empty>{loading ? '正在读取经营回路…' : '经营回路状态未读到，请刷新。'}</Empty> : <>
      {grants.length ? <ul className="r-loop-grants">{grants.map(grant => { const state = grantState(grant); return <li key={grant.id}>
        <div><strong>{grantLabel(grant)}</strong> <Badge tone={state.tone}>{state.label}</Badge><br />
          <span className="r-footnote">{levelName(grant.level)} · {grant.stages.length} 个阶段 · 每日最多 {grant.max_runs_per_day} 次{grant.halted_reason ? ' · 连续失败后自动停用' : ''}</span></div>
        <div className="r-actions">{grant.enabled ? <Button disabled={!!busy} onClick={() => advance(grant)}>立即检查一次</Button> : null}
          <Button primary={!grant.enabled} disabled={!!busy} onClick={() => toggle(grant)}>{grant.enabled ? '停用' : '启用'}</Button></div>
      </li>; })}</ul> : <Empty>还没有开启回路的商品。新建授权后，系统会按该商品的缺项把下一步派给负责岗位。</Empty>}

      {groups.decide.length ? <section className="r-loop-group" aria-label="等你决定"><h3>等你决定（{groups.decide.length}）</h3><ul className="r-loop-work">{groups.decide.map(work => item(work, <>
        {missing(work)}
        {(work.proposals || []).map(proposal => <div className="r-loop-proposal" key={proposal.id}><span>{proposal.reason}</span>
          <div className="r-actions"><Button primary disabled={!!busy} onClick={() => decide(work, 'approve', proposal.id)}>批准交接</Button></div></div>)}
        <Button disabled={!!busy} onClick={() => decide(work, 'reject')}>全部驳回</Button>
      </>))}</ul></section> : null}

      {groups.attention.length ? <section className="r-loop-group" aria-label="需要核对"><h3>需要核对（{groups.attention.length}）</h3><ul className="r-loop-work">{groups.attention.map(work => item(work, <>
        <p className="r-footnote">{work.status === 'unknown' ? '原请求的结果没有确认。系统不会重发；核对后关闭，回路才会继续。' : '本次未完成。核对原因后关闭；证据变化时会生成新工单。'}</p>
        <Button disabled={!!busy} onClick={() => resolve(work)}>已核对，关闭</Button>
      </>))}</ul></section> : null}

      {groups.waiting.length ? <section className="r-loop-group" aria-label="等资料"><h3>等资料（{groups.waiting.length}）</h3><ul className="r-loop-work">{groups.waiting.map(work => item(work, <>{missing(work)}{(work.questions || []).map((text, index) => <p key={index}>{text}</p>)}</>))}</ul></section> : null}
      {groups.running.length ? <section className="r-loop-group" aria-label="处理中"><h3>处理中（{groups.running.length}）</h3><ul className="r-loop-work">{groups.running.map(work => item(work))}</ul></section> : null}
      {groups.done.length ? <details><summary>已结束（{groups.done.length}）</summary><ul className="r-loop-work">{groups.done.map(work => item(work, work.decision?.task_id && onNavigate ? <Button onClick={() => onNavigate('tasks', work.decision!.task_id!)}>查看交接任务</Button> : null))}</ul></details> : null}
      {view.work_truncated ? <p className="r-footnote">仅显示最近 100 项工单。</p> : null}

      {editing ? <form className="r-loop-form" onSubmit={save} aria-label="新建或修改回路授权">
        <label className="ui-field" htmlFor="loop-choice">商品与目标店铺<select id="loop-choice" aria-label="商品与目标店铺" value={draft.choice} disabled={!!busy || !choices} onChange={event => setDraft({ ...draft, choice: event.target.value })}>
          <option value="">{choices ? choices.length ? '请选择' : '没有已保存上架方案的商品' : '正在读取…'}</option>
          {(choices || []).map((choice, index) => <option key={index} value={index}>{choice.name || '未命名商品'} · {choice.target.platform} · {choice.target.market}</option>)}</select></label>
        <label className="ui-field" htmlFor="loop-level">自治级别<select id="loop-level" aria-label="自治级别" value={draft.level} disabled={!!busy} onChange={event => setDraft({ ...draft, level: event.target.value as Draft['level'] })}>
          <option value="observe">仅观察：记录缺项和负责人，不调用模型</option><option value="prepare">范围内准备：由负责岗位做一次只读分析，建议等你决定</option></select></label>
        <fieldset><legend>纳入回路的阶段</legend><div className="r-loop-stages">{catalog.map(stage => <label key={stage.id}><input type="checkbox" checked={draft.stages.includes(stage.id)} disabled={!!busy}
          onChange={event => setDraft({ ...draft, stages: event.target.checked ? [...draft.stages, stage.id] : draft.stages.filter(id => id !== stage.id) })} />
          <span>{stage.name}<small>{ownerName(stage.owner)}{stage.executable ? '' : ' · 只记录缺项'}</small></span></label>)}</div></fieldset>
        {warnings.map((text, index) => <p className="r-footnote" key={index}>{text}</p>)}
        {draft.level === 'prepare' ? <label className="ui-field" htmlFor="loop-limit">每日最多派发次数<input id="loop-limit" aria-label="每日最多派发次数" type="number" min={1} max={12} value={draft.limit} disabled={!!busy}
          onChange={event => setDraft({ ...draft, limit: Math.min(12, Math.max(1, Number(event.target.value) || 1)) })} /></label> : null}
        <div className="r-oc-submit"><Button type="submit" primary disabled={!!busy}>{busy === 'save' ? '正在保存…' : '保存授权'}</Button><Button type="button" disabled={!!busy} onClick={() => setEditing(false)}>取消</Button>
          <span className="r-footnote">保存后默认未启用；修改已有授权会先停用它。</span></div>
      </form> : <div className="r-oc-boundary"><span>回路只把已知的下一步派给负责岗位，建议由你决定；发布、采购、付款、广告和客户消息不在其中。</span><Button onClick={() => void openForm()} disabled={!!busy}>新建授权</Button></div>}
    </>}
  </Panel>;
}
