import { useEffect, useMemo, useRef, useState } from 'react';
import { SurfaceView, useGenerativeUIActivitySurface, useGenerativeUIRuntime } from '@copilotkit/react-core/v2/generative-ui/native';
import type { A2UIOperation } from '@copilotkit/shared';
import { api, errorText as sharedErrorText, newKey } from './api';
import { CalculationContext, CalculationResult, UnitEconomicsForm, catalogId, fromInput, toInput, type Values } from './calculation';
import { Badge, Button, Empty, ErrorNotice, FieldDiff } from './ui';
import { SurfaceProvider } from './surface-provider';
import type { Calculation, Input, Product, Surface } from './types';
import { differences, labels, validateInput, type FieldErrors } from './cost-input';
import {CampaignScenarios} from './campaign-scenarios';
import { costComponentNames } from './cost-contract';
import {ProductCostScenarios} from './product-cost-scenarios';
const draftScope = { module: 'operations', form: 'cost', case_id: '' };
type CostDraft = { revision: number; payload: { values?: Values; origin?: string } | null };
type CostProduct=Product&{artifacts?:{economics?:{payload?:Input}|null};calculation:Calculation&{stale?:boolean}};
function errorText(failure:unknown){
  const code=failure instanceof Error?failure.message:'';
  if(code==='workspace_currency_required')return '请先确认当前成本币种，再保存并测算。';
  if(code==='workspace_quote_not_ready')return '报价依据尚未就绪，请核对原商品报价后重新读取成本。';
  if(code==='workspace_handoff_held')return '测算交接尚未确认，请读取原商品版本核对。';
  return sharedErrorText(failure);
}

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
  useEffect(() => runtime?.manager.registerTarget('cost-workspace', { components: [...costComponentNames] }), [runtime]);
  const result = useGenerativeUIActivitySurface({ runtime, threadId: 'cost-' + surface.surface_id, agentId: undefined, content, target: 'cost-workspace' });
  if (result.error || result.rejected.length) return <ErrorNotice>动态表单未通过目录校验，请使用标准表单。当前输入已保留。</ErrorNotice>;
  return result.surface ? <SurfaceView surface={result.surface} /> : <Empty>正在读取动态测算表单…</Empty>;
}

export function CostPage({ caseId = '', requestedSurface = '', onReturn,onEditState }: { caseId?: string; requestedSurface?: string; onReturn?: () => void;onEditState?:(caseId:string,dirty:boolean)=>void }) {
  const [surface, setSurface] = useState<Surface | null>(null), [values, setValues] = useState<Values>({}), [dirty, setDirty] = useState(false);
  const [dynamic, setDynamic] = useState(true), [error, setError] = useState(''), [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [loaded, setLoaded] = useState(false);
  const [standardResult, setStandardResult] = useState<Calculation | null>(null), [draftRevision, setDraftRevision] = useState(0), [restoreEpoch, setRestoreEpoch] = useState(0);
  const [product, setProduct] = useState<CostProduct | null>(null);
  const [sourceReviewed, setSourceReviewed] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({}), [review, setReview] = useState<Surface | null>(null);
  const [standardReview, setStandardReview] = useState<CostDraft | null>(null);
  const [workspaceReview,setWorkspaceReview]=useState<CostProduct|null>(null),[scenarioDirty,setScenarioDirty]=useState(false),[scenarioWriting,setScenarioWriting]=useState(false);
  const [blocked, setBlocked] = useState(false), [unknown, setUnknown] = useState(false);
  const [loadErrorCode, setLoadErrorCode] = useState('');
  const targetPending = !!requestedSurface && requestedSurface !== surface?.surface_id;
  const page = useRef<HTMLDivElement>(null);
  const operation = useRef(false), version = useRef(0), pending = useRef<{ key: string; fingerprint: string; event?: object } | null>(null);
  const draftValues=useRef<Values>({}),pendingEdits=useRef(false);
  const uncommitted=dirty||(!caseId&&!surface&&differences(values,draftValues.current).length>0);
  pendingEdits.current=uncommitted||scenarioDirty||unknown;
  const editCallback=useRef(onEditState);editCallback.current=onEditState;
  useEffect(()=>{editCallback.current?.(caseId,uncommitted||scenarioDirty||operation.current||unknown);},[caseId,uncommitted,scenarioDirty,busy,unknown]);
  useEffect(()=>()=>editCallback.current?.(caseId,false),[caseId]);
  useEffect(()=>{const protect=(event:BeforeUnloadEvent)=>{if(pendingEdits.current||operation.current){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',protect);return()=>window.removeEventListener('beforeunload',protect);},[]);
  async function standardLoad() {
    const saved = await api<CostDraft>('commerce_form_draft_get', { scope: draftScope });
    return saved;
  }
  function adoptStandard(saved: CostDraft, keepLocal = false) {
    draftValues.current={...saved.payload?.values};
    setDraftRevision(saved.revision); setStandardReview(null); setBlocked(false); setUnknown(false); setStandardResult(null);
    if (!keepLocal) { setValues(saved.payload?.values || {}); setDirty(false); }
    else setDirty(differences(values, saved.payload?.values || {}).length > 0);
  }
  function adopt(current: Surface, keepLocal = false) {
    setSurface(current);setStandardResult(null); setReview(null);setWorkspaceReview(null); setBlocked(false); setUnknown(false); pending.current = null; setSourceReviewed(false); setFieldErrors({});
    if (!keepLocal) { setValues(fromInput(current.input)); setDirty(false); setRestoreEpoch(v => v + 1); }
    else setDirty(differences(values, fromInput(current.input)).length > 0);
    setMessage(keepLocal ? '已核对保存版本，保留本地输入；下次提交会校验本版本。' : '已采用当前保存版本。');
  }
  function adoptWorkspace(current:CostProduct,keepLocal=false){
    const saved=fromInput(current.forms.cost.payload?.input||current.artifacts?.economics?.payload||{});
    setProduct(current);setSurface(null);setReview(null);setStandardReview(null);setWorkspaceReview(null);setBlocked(false);setUnknown(false);pending.current=null;setSourceReviewed(false);setFieldErrors({});setDynamic(false);setStandardResult(current.calculation);
    if(!keepLocal){setValues(saved);setDirty(false);}else setDirty(differences(values,saved).length>0);
    setMessage(keepLocal?'已核对保存版本，保留本地输入；下次提交会校验本版本。':'');
  }
  function focusError(errors: FieldErrors) {
    requestAnimationFrame(() => page.current?.querySelector<HTMLInputElement>(`input[name="${Object.keys(errors)[0]}"]`)?.focus());
  }
  async function load(inspect = false) {
    if (operation.current) return;
    const generation = ++version.current; setError(''); setLoadErrorCode('');
    setBusy(true);
    let item:CostProduct|null=null,surfaceAttempted=false;
    try {
      item = caseId ? await api<CostProduct>('commerce_workspace_get', { case_id: caseId }) : null;
      if (generation !== version.current) return;
      if(item&&item.case.id!==caseId)throw Error('workspace_source_changed');
      setProduct(item);
      const id = requestedSurface;
      if (id && id !== surface?.surface_id) {
        setBlocked(true);
        setMessage('正在恢复所选测算任务，原输入保留。');
      }
      if (!item && !surface && !id) {
        const saved = await standardLoad();
        if (generation !== version.current) return;
        if (inspect && (dirty || blocked || unknown)) { setStandardReview(saved); setMessage('已读取当前草稿，请核对后选择采用或保留本地输入。'); }
        else adoptStandard(saved);
        setDynamic(false); setLoaded(true); return;
      }
      const status = await api<{ enabled: boolean }>('commerce_a2ui_status');
      if (!status.enabled) throw Error('a2ui_disabled');
      surfaceAttempted=true;
      const current = item ? await api<Surface>('commerce_a2ui_create', { case_id: caseId, expected_source_sha256: item.source_sha256, idempotency_key: 'react-cost-case:' + caseId + ':' + item.source_sha256 }) : await api<Surface>('commerce_a2ui_get', { surface_id: id || surface!.surface_id });
      if ((caseId && current.binding?.case_id !== caseId) || (!caseId && current.binding)) throw Error('workspace_source_changed');
      if (generation !== version.current) return;
      if (inspect && (dirty || blocked || unknown)) { setReview(current); setMessage('已读取当前保存版本。请核对保存版本与本地输入，再选择如何继续。'); }
      else { adopt(current); if (!inspect) setMessage(''); }
      setLoaded(true);
    } catch (e) {
      if (generation !== version.current) return;
      const code=e instanceof Error?e.message:'request_failed';
      if(item?.case.id===caseId&&!requestedSurface&&(!surfaceAttempted||['a2ui_disabled','a2ui_dependency_missing'].includes(code))){
        if(inspect&&(dirty||blocked||unknown)){setWorkspaceReview(item);setMessage('已读取当前商品成本版本，本地输入已保留。');}
        else adoptWorkspace(item);
        setLoaded(true);setError('');setLoadErrorCode('');return;
      }
      setError(errorText(e));
      setLoadErrorCode(code);
      if (requestedSurface) setMessage('所选测算任务尚未恢复，当前输入已保留。请读取当前保存版本后再继续。');
      if (!surface && !caseId && !requestedSurface) {
        setDynamic(false);
        try { const saved = await standardLoad(); if (generation !== version.current) return;draftValues.current={...saved.payload?.values}; setDraftRevision(saved.revision); if (!dirty) { setValues(saved.payload?.values || {}); setDirty(false); } setLoaded(true); }
        catch (failure) { if (generation === version.current) setError(errorText(failure)); }
      }
    } finally { if (generation === version.current) setBusy(false); }
  }
  async function enableDynamic() {
    if(surface&&!busy&&!scenarioWriting&&!blocked&&!operation.current)setDynamic(v=>!v);
  }
  const resumedSurface = useRef(requestedSurface);
  useEffect(() => { void load(); return () => { version.current++; }; }, []);
  useEffect(() => {
    if (requestedSurface === resumedSurface.current || busy || operation.current) return;
    resumedSurface.current = requestedSurface;
    // Finish an in-flight save first, then compare a different task with local input.
    if (requestedSurface && requestedSurface !== surface?.surface_id) void load(true);
  }, [requestedSurface, busy]);
  function edit(next: Values) { setValues(next); setDirty(true); setMessage(''); setError(''); setFieldErrors(previous => Object.fromEntries(Object.entries(previous).filter(([key]) => next[key] === values[key]))); }
  async function submit(action: 'update' | 'calculate') {
    if (!loaded || operation.current || scenarioWriting || blocked || targetPending || unknown || review || standardReview || workspaceReview) return;
    if ((surface?.binding?.stale||!surface&&(product?.forms.cost.stale||product?.calculation.stale)) && !sourceReviewed) { setError('请先核对当前商品依据，再明确保存或重新测算。'); return; }
    const errors = validateInput(values); setFieldErrors(errors);
    if (Object.keys(errors).length) { setError('请修正标记字段。'); focusError(errors); return; }
    operation.current = true; setBusy(true); setError(''); setMessage('');
    const generation = version.current;
    try {
      const input = toInput(values);
      if (!surface) {
        if(caseId){
          if(!product||product.case.id!==caseId)throw Error('workspace_source_changed');
          if(action==='calculate'&&(!product.case.currency||product.case.currency!==input.currency))throw Error('workspace_currency_required');
          let revision=product.forms.cost.revision;const source=product.source_sha256;
          if(action==='update'||dirty||product.forms.cost.stale||!revision){
            const saved=await api<{revision:number;payload:{input:Input};source_sha256:string}>('commerce_workspace_save',{case_id:caseId,form:'cost',payload:{input},expected_revision:revision,expected_source_sha256:source});
            if(generation!==version.current)return;revision=saved.revision;setProduct({...product,forms:{...product.forms,cost:{revision,payload:saved.payload,stale:false}}});setDirty(false);setStandardResult(null);
          }
          if(action==='calculate')await api<Calculation>('commerce_workspace_calculate',{case_id:caseId,expected_revision:revision,expected_source_sha256:source});
          const current=await api<CostProduct>('commerce_workspace_get',{case_id:caseId});if(generation!==version.current)return;if(current.case.id!==caseId)throw Error('workspace_source_changed');adoptWorkspace(current);if(action==='update')setStandardResult(null);setMessage(action==='update'?'输入已保存，测算结果待重新计算。':current.calculation.status==='HOLD'?'资料尚未齐全，请补齐后继续。':'已按本次输入计算并保存。');return;
        }
        if (action === 'update') {
          const saved = await api<{ revision: number }>('commerce_form_draft_save', { scope: draftScope, payload: { values, origin: 'manual' }, expected_revision: draftRevision });
          if (generation === version.current) {draftValues.current={...values}; setDraftRevision(saved.revision); setDirty(false); setStandardResult(null); setMessage('输入已保存。'); }
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
  async function confirmCurrency(){
    const currency=values.currency?.trim().toUpperCase();if(!product||!currency||!/^[A-Z]{3}$/.test(currency)||busy||scenarioWriting||operation.current||unknown||blocked||targetPending||review||standardReview||workspaceReview)return;
    const generation=version.current;operation.current=true;setBusy(true);setError('');setMessage('');let confirmed=false;
    try{await api('commerce_workspace_currency',{case_id:caseId,currency,expected_source_sha256:surface?.binding?.source_sha256||product.source_sha256});confirmed=true;const current=await api<CostProduct>('commerce_workspace_get',{case_id:caseId});if(generation!==version.current)return;if(current.case.id!==caseId)throw Error('workspace_source_changed');setProduct(current);if(surface){const fresh=await api<Surface>('commerce_a2ui_get',{surface_id:surface.surface_id});if(generation!==version.current)return;if(fresh.binding?.case_id!==caseId)throw Error('workspace_source_changed');setSurface(fresh);}setSourceReviewed(true);setDirty(true);setMessage('成本币种已确认；核对当前参数后保存或测算。');}
    catch(failure){if(generation===version.current){setError(errorText(failure));if(confirmed){setBlocked(true);setMessage('币种已确认，但新成本版本尚未读回，请读取当前保存版本核对。');}if(failure instanceof TypeError||failure instanceof Error&&failure.message==='request_outcome_unknown'){setUnknown(true);setBlocked(true);}}}
    finally{operation.current=false;if(generation===version.current)setBusy(false);}
  }
  const result = surface?.result || (!surface?standardResult:null);
  const basisStale=surface?!!surface.binding?.stale:!!(product?.forms.cost.stale||product?.calculation.stale);
  const changed = review ? differences(values, fromInput(review.input)) : workspaceReview?differences(values,fromInput(workspaceReview.forms.cost.payload?.input||workspaceReview.artifacts?.economics?.payload||{})):standardReview ? differences(values, standardReview.payload?.values || {}) : [];
  const savedValues = review ? fromInput(review.input) : workspaceReview?fromInput(workspaceReview.forms.cost.payload?.input||workspaceReview.artifacts?.economics?.payload||{}):standardReview?.payload?.values || {};
  return <div className="r-page r-cost-page" ref={page} data-ai-page="operations" data-ai-context={JSON.stringify({section:"cost",...(caseId?{entity:{kind:"case",id:caseId,name:product?.name}}:{}),input:Object.fromEntries(Object.entries(values).map(([k,v])=>[k,k.endsWith("_rate")&&v&&Number.isFinite(Number(v))?Number(v)/100:v])),source_refs:surface?.binding?.source_sha256||product?.source_sha256?{case:surface?.binding?.source_sha256||product?.source_sha256}:{},errors:[error,basisStale?'商品依据已变化，请核对后重新保存。':'',...Object.values(fieldErrors)].filter(Boolean).slice(0,3)})}>
    <div className="r-page-heading"><div><h1>{product?.name || (caseId ? '当前商品成本' : '成本测算')}</h1><p>{caseId ? '成本测算 · 当前商品' : '未关联商品 · 同币种通用测算'}</p></div><div className="r-actions">{caseId && <Button onClick={onReturn}>返回原商品</Button>}<Button onClick={() => void load(true)} disabled={busy||scenarioWriting}>读取当前保存版本</Button></div></div>
    <div className="r-scope-line"><Badge tone="blue">{product?.case.scope.synthetic === true ? '合成示例 · ' : ''}{basisStale ? '依据待核对' : product ? '当前商品 · 同币种' : '本次填写 · 同币种'}</Badge><details><summary>显示与版本</summary><p>{dynamic&&surface?'动态表单':'标准表单'}{surface?` · 修订 ${surface.revision}${surface.binding?` · 来源 ${surface.binding.source_sha256.slice(0,12)}`:' · 手动填写'}`:product?` · 成本修订 ${product.forms.cost.revision}`:` · 保存修订 ${draftRevision}`}</p>{surface&&<Button onClick={() => void enableDynamic()} disabled={busy||scenarioWriting || blocked || !!standardReview || !!workspaceReview}>{dynamic?'使用标准表单':'使用动态表单'}</Button>}</details></div>
    <ErrorNotice>{error || (basisStale ? '商品依据已变化，请核对后重新保存。' : '')}</ErrorNotice>
    {unknown && <p role="status">提交结果尚未确认。已暂停保存与测算，请先读取当前保存版本核对。</p>}
    {(review || standardReview || workspaceReview) && <section className="r-source-recovery" aria-label="核对保存版本"><p>当前保存修订 {review?.revision ?? workspaceReview?.forms.cost.revision ?? standardReview?.revision}；本地输入已保留。</p><FieldDiff rows={changed.map(key => ({ key, label: labels[key] + (key.endsWith('_rate') ? '（%）' : ''), before: values[key], after: savedValues[key] }))} beforeLabel="本地输入" afterLabel="保存版本" />{review && <CalculationResult result={review.result} />}<div className="r-actions"><Button onClick={() => review ? adopt(review) : workspaceReview?adoptWorkspace(workspaceReview):standardReview && adoptStandard(standardReview)}>采用保存版本</Button><Button onClick={() => review ? adopt(review, true) : workspaceReview?adoptWorkspace(workspaceReview,true):standardReview && adoptStandard(standardReview, true)}>核对后保留本地输入</Button></div></section>}
    {basisStale && !review && !workspaceReview && <div className="r-source-recovery"><label><input type="checkbox" checked={sourceReviewed} onChange={e => setSourceReviewed(e.target.checked)} />已核对当前商品依据，继续使用本次填写的参数</label><Button disabled={!sourceReviewed || busy || scenarioWriting || blocked} onClick={() => void submit('update')}>确认并保存当前依据</Button></div>}
    {product&&product.case.currency!==values.currency?.trim().toUpperCase()&&<div className="r-source-recovery"><span>商品成本币种：{product.case.currency||'待确认'}；本次输入：{values.currency?.trim().toUpperCase()||'待填写'}</span><Button disabled={busy||scenarioWriting||unknown||blocked||targetPending||!!review||!!standardReview||!!workspaceReview||!values.currency?.trim()||!/^[A-Z]{3}$/.test(values.currency.trim().toUpperCase())} onClick={()=>void confirmCurrency()}>确认使用此币种</Button></div>}
    {message && <p role="status" className="r-feedback">{message}</p>}
    {!loaded ? <Empty>{error ? caseId ? '未读到当前商品成本，请读取当前保存版本或核对原商品连接。' : '未读到测算记录，可重读后继续。' : '正在读取保存的输入…'}</Empty> : <CalculationContext.Provider value={{ values, onChange: edit, busy: busy || scenarioWriting || blocked || targetPending || !!review || !!standardReview || !!workspaceReview, dirty: uncommitted || targetPending, bound: !!caseId||!!surface?.binding, errors: fieldErrors, calculate: () => void submit('calculate'), save: () => void submit('update') }}>{dynamic && surface ? <SurfaceProvider key={surface.surface_id + ':' + restoreEpoch}><DynamicCost surface={surface} /></SurfaceProvider> : <div className="r-calculation-grid"><UnitEconomicsForm /><CalculationResult result={dirty || targetPending ? null : result} /></div>}</CalculationContext.Provider>}
    {loaded&&caseId&&product&&<ProductCostScenarios key={caseId} snapshot={{caseId,sourceSha:surface?.binding?.source_sha256||product.source_sha256,costRevision:surface?.binding?.cost_revision??product.forms.cost.revision}} disabled={busy||blocked||targetPending||unknown||dirty||!!review||!!standardReview||!!workspaceReview||basisStale||result?.status!=='CALCULATED'} onEditState={setScenarioDirty} onWriting={setScenarioWriting}/>}
    {loaded&&<CampaignScenarios values={values} disabled={busy||scenarioWriting||blocked||targetPending||unknown||!!review||!!standardReview||!!workspaceReview||!!(basisStale&&!sourceReviewed)}/>}
  </div>;
}
