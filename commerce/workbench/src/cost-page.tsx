import { useEffect, useMemo, useRef, useState } from 'react';
import { SurfaceView, useGenerativeUIActivitySurface, useGenerativeUIRuntime } from '@copilotkit/react-core/v2/generative-ui/native';
import type { A2UIOperation } from '@copilotkit/shared';
import { api, errorText, newKey } from './api';
import { CalculationContext, CalculationResult, UnitEconomicsForm, catalogId, fromInput, toInput, type Values } from './calculation';
import { Badge, Button, Empty, ErrorNotice } from './ui';
import { SurfaceProvider } from './surface-provider';
import type { Calculation, Product, Surface } from './types';
import { differences, labels, validateInput, type FieldErrors } from './cost-input';
const draftScope = { module: 'operations', form: 'cost', case_id: '' };
type CostDraft = { revision: number; payload: { values?: Values; origin?: string } | null };

function DynamicCost({ surface }: { surface: Surface }) {
  const runtime = useGenerativeUIRuntime();
  const history = useRef<A2UIOperation[]>([]), lastRevision = useRef(-1);
  const content = useMemo(() => {
    if (lastRevision.current !== surface.revision) {
      history.current = history.current.length ? [...history.current, ...surface.updates] : surface.messages;
      lastRevision.current = surface.revision;
    }
    return { surfaceId: surface.surface_id, target: 'cost-workspace', catalogId, operations: history.current, status: 'ready' as const, rejected: [] };
  }, [surface]);
  useEffect(() => runtime?.manager.registerTarget('cost-workspace', { components: ['Column', 'Text', 'NumberField', 'CurrencyField', 'Button'] }), [runtime]);
  const result = useGenerativeUIActivitySurface({ runtime, threadId: 'cost-' + surface.surface_id, agentId: undefined, content, target: 'cost-workspace' });
  if (result.error || result.rejected.length) return <ErrorNotice>动态表单未通过目录校验，请使用标准表单。当前输入已保留。</ErrorNotice>;
  return result.surface ? <SurfaceView surface={result.surface} /> : <Empty>正在读取动态测算表单…</Empty>;
}

export function CostPage({ caseId = '', onReturn }: { caseId?: string; onReturn?: () => void }) {
  const [surface, setSurface] = useState<Surface | null>(null), [values, setValues] = useState<Values>({}), [dirty, setDirty] = useState(false);
  const [dynamic, setDynamic] = useState(true), [error, setError] = useState(''), [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [loaded, setLoaded] = useState(false);
  const [standardResult, setStandardResult] = useState<Calculation | null>(null), [draftRevision, setDraftRevision] = useState(0), [restoreEpoch, setRestoreEpoch] = useState(0);
  const [product, setProduct] = useState<Product | null>(null);
  const [sourceReviewed, setSourceReviewed] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({}), [review, setReview] = useState<Surface | null>(null);
  const [standardReview, setStandardReview] = useState<CostDraft | null>(null);
  const [blocked, setBlocked] = useState(false), [unknown, setUnknown] = useState(false);
  const [loadErrorCode, setLoadErrorCode] = useState('');
  const page = useRef<HTMLDivElement>(null);
  const operation = useRef(false), version = useRef(0), pending = useRef<{ key: string; fingerprint: string; event?: object } | null>(null);
  async function standardLoad() {
    const saved = await api<CostDraft>('commerce_form_draft_get', { scope: draftScope });
    return saved;
  }
  function adoptStandard(saved: CostDraft, keepLocal = false) {
    setDraftRevision(saved.revision); setStandardReview(null); setBlocked(false); setUnknown(false); setStandardResult(null);
    if (!keepLocal) { setValues(saved.payload?.values || {}); setDirty(false); }
    else setDirty(differences(values, saved.payload?.values || {}).length > 0);
  }
  function adopt(current: Surface, keepLocal = false) {
    setSurface(current); setReview(null); setBlocked(false); setUnknown(false); pending.current = null; setSourceReviewed(false); setFieldErrors({});
    if (!keepLocal) { setValues(fromInput(current.input)); setDirty(false); setRestoreEpoch(v => v + 1); }
    else setDirty(differences(values, fromInput(current.input)).length > 0);
    setMessage(keepLocal ? '已核对保存版本，保留本地输入；下次提交会校验本版本。' : '已采用当前保存版本。');
  }
  function focusError(errors: FieldErrors) {
    requestAnimationFrame(() => page.current?.querySelector<HTMLInputElement>(`input[name="${Object.keys(errors)[0]}"]`)?.focus());
  }
  async function load(inspect = false) {
    if (operation.current) return;
    const generation = ++version.current; setError(''); setLoadErrorCode('');
    setBusy(true);
    try {
      const item = caseId ? await api<Product>('commerce_workspace_get', { case_id: caseId }) : null;
      if (generation !== version.current) return;
      setProduct(item);
      const id = new URL(location.href).searchParams.get('surface');
      if (!item && !surface && !id) {
        const saved = await standardLoad();
        if (generation !== version.current) return;
        if (inspect && (dirty || blocked || unknown)) { setStandardReview(saved); setMessage('已读取当前草稿，请核对后选择采用或保留本地输入。'); }
        else adoptStandard(saved);
        setDynamic(false); setLoaded(true); return;
      }
      const status = await api<{ enabled: boolean }>('commerce_a2ui_status');
      if (!status.enabled) throw Error('a2ui_disabled');
      const current = item ? await api<Surface>('commerce_a2ui_create', { case_id: caseId, expected_source_sha256: item.source_sha256, idempotency_key: 'react-cost-case:' + caseId + ':' + item.source_sha256 }) : await api<Surface>('commerce_a2ui_get', { surface_id: surface?.surface_id || id! });
      if ((caseId && current.binding?.case_id !== caseId) || (!caseId && current.binding)) throw Error('workspace_source_changed');
      if (generation !== version.current) return;
      if (inspect && (dirty || blocked || unknown)) { setReview(current); setMessage('已读取当前保存版本。请核对保存版本与本地输入，再选择如何继续。'); }
      else { adopt(current); if (!inspect) setMessage(''); }
      setLoaded(true);
    } catch (e) {
      if (generation !== version.current) return;
      setError(errorText(e));
      setLoadErrorCode(e instanceof Error ? e.message : 'request_failed');
      if (!surface && !caseId) {
        setDynamic(false);
        try { const saved = await standardLoad(); if (generation !== version.current) return; setDraftRevision(saved.revision); if (!dirty) { setValues(saved.payload?.values || {}); setDirty(false); } setLoaded(true); }
        catch (failure) { if (generation === version.current) setError(errorText(failure)); }
      }
    } finally { if (generation === version.current) setBusy(false); }
  }
  async function enableDynamic() {
    if (surface) { setDynamic(v => !v); return; }
    if (busy || blocked || operation.current || caseId) return;
    operation.current = true; setBusy(true); setError('');
    const generation = version.current;
    try {
      const current = await api<Surface>('commerce_a2ui_create', { idempotency_key: 'react-cost-local-owner-v1' });
      if (generation !== version.current) return;
      if (current.binding) throw Error('workspace_source_changed');
      adopt(current, true); setDynamic(true); setMessage('动态测算任务已打开；输入需保存或计算后持久化。');
    } catch (failure) { if (generation === version.current) setError(errorText(failure)); }
    finally { operation.current = false; if (generation === version.current) setBusy(false); }
  }
  useEffect(() => { void load(); return () => { version.current++; }; }, []);
  function edit(next: Values) { setValues(next); setDirty(true); setMessage(''); setError(''); setFieldErrors(previous => Object.fromEntries(Object.entries(previous).filter(([key]) => next[key] === values[key]))); }
  async function submit(action: 'update' | 'calculate') {
    if (!loaded || operation.current || blocked || unknown || review || standardReview) return;
    if (surface?.binding?.stale && !sourceReviewed) { setError('请先核对当前商品依据，再明确保存或重新测算。'); return; }
    const errors = validateInput(values); setFieldErrors(errors);
    if (Object.keys(errors).length) { setError('请修正标记字段。'); focusError(errors); return; }
    operation.current = true; setBusy(true); setError(''); setMessage('');
    const generation = version.current;
    try {
      const input = toInput(values);
      if (!surface) {
        if (action === 'update') {
          const saved = await api<{ revision: number }>('commerce_form_draft_save', { scope: draftScope, payload: { values, origin: 'manual' }, expected_revision: draftRevision });
          if (generation === version.current) { setDraftRevision(saved.revision); setDirty(false); setStandardResult(null); setMessage('输入已保存。'); }
        } else {
          const result = await api<Calculation>('commerce_unit_economics', { input });
          if (generation === version.current) { setStandardResult(result); setDirty(false); setMessage('已按当前输入计算；输入需显式保存后才能恢复。'); }
        }
        return;
      }
      const base = { revision: String(surface.revision), input, ...(surface.binding ? { case_id: surface.binding.case_id, expected_source_sha256: surface.binding.source_sha256 } : {}) };
      const fingerprint = JSON.stringify({ ...base, surface_id: surface.surface_id, action });
      if (!pending.current || pending.current.fingerprint !== fingerprint) pending.current = { key: newKey(), fingerprint, event: { version: '1.0', action: { name: 'commerce.cost.calculate', surfaceId: surface.surface_id, sourceComponentId: 'calculate', timestamp: new Date().toISOString(), context: {} } } };
      const value = await api<Surface>(action === 'calculate' ? 'commerce_a2ui_action' : 'commerce_a2ui_update', { ...base, ...(action === 'calculate' ? { event: pending.current.event } : { surface_id: surface.surface_id }), idempotency_key: pending.current.key });
      if (generation !== version.current) return;
      setSurface(value); setValues(fromInput(value.input)); setDirty(false); pending.current = null;
      if (value.result?.status === 'HOLD') { const missing = Object.fromEntries(value.result.missing.map(key => [key, '待填写；未知值不可按 0 测算。'])); setFieldErrors(missing); focusError(missing); }
      setMessage(action === 'update' ? '输入已保存，测算结果待重新计算。' : value.result?.status === 'HOLD' ? '资料尚未齐全，请补齐标记字段。' : '已按本次输入计算并保存。');
    } catch (e) { if (generation === version.current) {
      setError(errorText(e));
      const code = e instanceof Error ? e.message : '';
      if (code === 'request_outcome_unknown' || e instanceof TypeError) { setUnknown(true); setBlocked(true); }
      if (['a2ui_revision_conflict', 'form_draft_conflict', 'workspace_source_changed', 'idempotency_conflict'].includes(code)) setBlocked(true);
    } }
    finally { operation.current = false; if (generation === version.current) setBusy(false); }
  }
  const result = surface?.result || standardResult;
  const changed = review ? differences(values, fromInput(review.input)) : standardReview ? differences(values, standardReview.payload?.values || {}) : [];
  const savedValues = review ? fromInput(review.input) : standardReview?.payload?.values || {};
  return <div className="r-page r-cost-page" ref={page}>
    <div className="r-page-heading"><div><h1>{product?.name || (caseId ? '当前商品成本' : '成本测算')}</h1><p>{caseId ? '成本测算 · 当前商品' : '未关联商品 · 同币种通用测算'}</p></div><div className="r-actions">{caseId && <Button onClick={onReturn}>返回原商品</Button>}<Button onClick={() => void enableDynamic()} disabled={busy || blocked || !!standardReview || (!surface && (!!caseId || !loaded))}>{surface ? dynamic ? '使用标准表单' : '使用动态表单' : '创建动态测算任务'}</Button><Button onClick={() => void load(true)} disabled={busy}>读取当前保存版本</Button></div></div>
    <div className="r-scope-line"><Badge tone="blue">{product?.case.scope.synthetic === true ? '合成示例 · ' : ''}{surface?.binding?.stale ? '依据待核对' : product ? '当前商品 · 同币种' : '本次填写 · 同币种'}</Badge><span>{dynamic ? '动态表单' : '标准表单'}</span>{surface && <details><summary>版本与来源</summary><p>修订 {surface.revision}{surface.binding ? ` · 来源 ${surface.binding.source_sha256.slice(0, 12)}` : ' · 手动填写'}</p></details>}</div>
    <ErrorNotice>{error || (surface?.binding?.stale ? '商品依据已变化，请核对后重新保存。' : '')}</ErrorNotice>
    {unknown && <p role="status">提交结果尚未确认。已暂停保存与测算，请先读取当前保存版本核对。</p>}
    {(review || standardReview) && <section className="r-source-recovery" aria-label="核对保存版本"><p>当前保存修订 {review?.revision ?? standardReview?.revision}；本地输入已保留。</p>{changed.length ? <div className="r-table-wrap"><table><thead><tr><th>字段</th><th>本地输入</th><th>保存版本</th></tr></thead><tbody>{changed.map(key => <tr key={key}><th>{labels[key]}{key.endsWith('_rate') ? '（%）' : ''}</th><td>{values[key] || '未知'}</td><td>{savedValues[key] || '未知'}</td></tr>)}</tbody></table></div> : <p>保存版本与本地输入一致。</p>}{review && <CalculationResult result={review.result} />}<div className="r-actions"><Button onClick={() => review ? adopt(review) : standardReview && adoptStandard(standardReview)}>采用保存版本</Button><Button onClick={() => review ? adopt(review, true) : standardReview && adoptStandard(standardReview, true)}>核对后保留本地输入</Button></div></section>}
    {surface?.binding?.stale && !review && <div className="r-source-recovery"><label><input type="checkbox" checked={sourceReviewed} onChange={e => setSourceReviewed(e.target.checked)} />已核对当前商品依据，继续使用本次填写的参数</label><Button disabled={!sourceReviewed || busy || blocked} onClick={() => void submit('update')}>确认并保存当前依据</Button></div>}
    {message && <p role="status" className="r-feedback">{message}</p>}
    {!loaded ? <Empty>{caseId && ['a2ui_disabled','a2ui_dependency_missing'].includes(loadErrorCode) ? '动态成本表单暂不可用。请返回同一商品的成本阶段使用标准表单。' : error ? caseId ? '未读到当前商品成本，请返回原商品核对连接与成本币种。' : '未读到测算记录，可重读后继续。' : '正在读取保存的输入…'}</Empty> : <CalculationContext.Provider value={{ values, onChange: edit, busy: busy || blocked || !!review || !!standardReview, dirty, bound: !!surface?.binding, errors: fieldErrors, calculate: () => void submit('calculate'), save: () => void submit('update') }}>{dynamic && surface ? <SurfaceProvider key={surface.surface_id + ':' + restoreEpoch}><DynamicCost surface={surface} /></SurfaceProvider> : <div className="r-calculation-grid"><UnitEconomicsForm /><CalculationResult result={dirty ? null : result} /></div>}</CalculationContext.Provider>}
  </div>;
}
