import {useEffect,useRef,useState} from 'react';
import {api,errorText} from './api';
import {Badge,Button,Empty,ErrorNotice,Panel} from './ui';
export interface ListingTarget {case_id:string;platform:string;store_ref:string;market:string}
interface Observation {status:string;observed_at:number|string|null;sha256:string|null;match_count:number;matches:{status:string|null}[];detail_fresh?:boolean;detail_observed_at?:string;detail_sha256?:string}
interface Comparison {comparison_sha256:string;plan_revision:number;plan_stale:boolean;observation:Observation;store_choices:{store_id:string;platform:string;market:string;label:string}[];
  differences:{field:string;prepared:string|number|null;observed:string|number|null;status:string;quantity_basis:string|null}[];
  review:{id:string;sha256:string;decision:string;note:string;current:boolean;created_at:string}|null}
export const observationLabels:Record<string,string>={demo_no_platform_read:'示例范围不读取真实店铺快照',store_unlinked:'店铺尚未关联',scope_mismatch:'店铺平台或市场不匹配',resource_not_supported:'此接入尚无商品或库存资料',snapshot_missing:'尚无当前范围的快照',snapshot_stale:'快照或授权范围已失效',sku_required:'请先补齐 SKU',sku_missing:'当前快照未找到此 SKU',sku_ambiguous:'同 SKU 对应多行，需核对范围',observed:'已精确匹配当前快照'};
const differenceLabels:Record<string,string>={different:'有差异',same:'相同',unknown:'资料不足',missing_input:'方案待填',not_comparable:'口径待核对'};
function failure(e:unknown){const code=e instanceof Error?e.message:'';return ({listing_comparison_changed:'方案或平台快照已有变化，请重新核对。',listing_review_conflict:'已有新的核对记录，请刷新后再操作。',listing_observation_required:'当前缺少可核对的同店铺、市场与 SKU 快照。',listing_review_note_required:'请填写核对说明。'})[code]||errorText(e);}
export function ListingObservation({target,previewSha,dirty,active,onTarget,onPlatform}:{target:ListingTarget;previewSha:string;dirty:boolean;active:boolean;onTarget:(target:ListingTarget)=>void;onPlatform:()=>void}){
  const [data,setData]=useState<Comparison|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [decision,setDecision]=useState('needs_changes'),[note,setNote]=useState(''),[confirmed,setConfirmed]=useState(false);
  const epoch=useRef(0),attempt=useRef<{signature:string;key:string}|null>(null),writing=useRef(false);const key=JSON.stringify(target);
  async function load(){const current=++epoch.current;setBusy(true);setError('');
    try{const value=await api<Comparison>('commerce_listing_reconcile',target);if(current===epoch.current)setData(value);}
    catch(e){if(current===epoch.current){setData(null);setError(failure(e));}}finally{if(current===epoch.current)setBusy(false);}
  }
  useEffect(()=>{setNote('');setDecision('needs_changes');setNotice('');attempt.current=null;},[key]);
  useEffect(()=>{epoch.current++;setData(null);setConfirmed(false);setError('');if(active&&!dirty)void load();return()=>{epoch.current++;};},[key,previewSha,dirty,active]);
  async function record(){if(!data||dirty||writing.current)return;writing.current=true;const current=++epoch.current;setBusy(true);setError('');
    const args={...target,expected_comparison_sha256:data.comparison_sha256,expected_review_sha256:data.review?.sha256||'',decision,note,confirmed};const signature=JSON.stringify(args);
    if(attempt.current?.signature!==signature)attempt.current={signature,key:crypto.randomUUID()};
    try{await api('commerce_listing_review',{...args,idempotency_key:attempt.current.key});if(current!==epoch.current)return;setNotice('已保存此版本的本地核对声明，平台状态与差异分别保留。');setConfirmed(false);await load();}
    catch(e){if(current===epoch.current)setError(failure(e));}finally{writing.current=false;if(current===epoch.current)setBusy(false);}
  }
  const observed=data?.observation.status==='observed';
  return <div className="r-listing-observation"><Panel title="平台快照与核对" action={<Button disabled={busy||dirty} onClick={()=>void load()}>刷新核对</Button>}>
    {dirty?<p>当前输入尚未保存，保存后核对同一版本。</p>:<>
      <ErrorNotice>{error}</ErrorNotice>{notice&&<p role="status">{notice}</p>}
      {!data?<Empty>{busy?'正在读取已留存的平台资料…':'平台核对资料尚未读回。'}</Empty>:<div className="r-observation-grid"><div>
        <p role="status"><Badge>{observationLabels[data.observation.status]||'状态未知'}</Badge></p>
        <label className="ui-field">关联已配置店铺<select value="" disabled={busy} onChange={e=>{const choice=data.store_choices.find(c=>c.store_id===e.target.value);if(choice)onTarget({...target,store_ref:choice.store_id,market:choice.market});}}><option value="">选择店铺并读取对应方案</option>{data.store_choices.map(c=><option key={c.store_id} value={c.store_id}>{c.label} · {c.market}</option>)}</select></label>
        <div className="r-actions"><Button onClick={onPlatform}>打开平台数据</Button></div>
        {observed&&<><p className="r-footnote">精确匹配 {data.observation.match_count} 行 · 平台原始状态：{data.observation.matches[0]?.status||'未提供'}</p>
          {data.observation.detail_observed_at&&<p className="r-footnote">商品详情观测：{new Date(data.observation.detail_observed_at).toLocaleString()} · {data.observation.detail_fresh?'用于核对标题、售价和币种':'已过期，不参与字段核对'}</p>}
          <div className="r-table-wrap r-observation-table" tabIndex={0} role="region" aria-label="方案与平台快照差异"><table className="data-table"><thead><tr><th>字段</th><th>当前方案</th><th>平台快照</th><th>核对</th></tr></thead><tbody>{data.differences.map(r=><tr key={r.field}><th>{{title:'标题',price:'售价',currency:'币种',quantity:'数量'}[r.field]||r.field}</th><td>{r.prepared??'未填'}</td><td>{r.observed??'未提供'}</td><td>{differenceLabels[r.status]||r.status}</td></tr>)}</tbody></table></div>
          <p className="r-footnote">数量保留来源范围与口径，未折算成全店可售库存。快照匹配不作为本系统发布成功回执。</p>
          <details><summary>快照版本</summary><p className="r-code">{data.observation.sha256}</p><p>{data.observation.observed_at?new Date(typeof data.observation.observed_at==='number'?data.observation.observed_at*1000:data.observation.observed_at).toLocaleString():'时间未提供'}</p></details></>}
        {data.review&&<section aria-label="已保存的上架核对"><p>{data.review.current?'当前版本核对':'旧版本核对已失效'} · {data.review.decision==='reviewed'?'已逐项核对':'需补充或修改'}</p><p>{data.review.note}</p></section>}
        </div><fieldset disabled={busy||!data.plan_revision}><legend>记录本地核对</legend>{!data.plan_revision&&<p>先保存店铺方案，再记录本地核对。</p>}
          <label className="ui-field">核对结论<select value={decision} onChange={e=>setDecision(e.target.value)}><option value="needs_changes">需补充或修改</option><option value="reviewed" disabled={!observed||data.plan_stale}>已逐项核对该快照</option></select></label>
          <label className="ui-field">核对说明<textarea rows={3} maxLength={2000} value={note} onChange={e=>setNote(e.target.value)}/></label>
          <label><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>确认记录当前版本的本地核对结果</label>
          <div className="r-form-actions"><Button disabled={!confirmed||!note.trim()||!data.plan_revision} onClick={()=>void record()}>保存核对记录</Button></div>
        </fieldset>
      </div>}
    </>}
  </Panel></div>;
}
