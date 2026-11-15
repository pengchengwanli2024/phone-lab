import {useEffect,useRef,useState} from 'react';
import {api,errorText,newKey} from './api';
import {Badge,Button,ErrorNotice,Panel} from './ui';
import type {ListingTarget} from './listing-observation';
import {ListingProductReview,type ReviewProduct} from './listing-product-review';
import './owner-review.css';

type Check={status:'pending'|'confirmed'|'not_applicable'|'rejected';source_ref:string;note:string};
interface Review {target:ListingTarget;binding_sha256:string;review_sha256:string;review_id:string|null;reviewer:string;reviewed_at:string|null;checks:Record<string,Check>;requirements:Record<string,string>;automatic_checks:{id:string;label:string;ready:boolean}[];supported:boolean;current:boolean;status:string;product:ReviewProduct|null;binding:{listing_revision:number};history:{id:string;decision:string;reviewer:string;at:string}[]}
const statuses:Record<string,string>={pending:'待逐项核对',save:'核查草稿',owner_confirmed:'负责人已签收',rejected:'已退回',withdrawn:'已撤销',stale:'资料版本已变化',prerequisites_missing:'前置资料待补齐'};
const message=(e:unknown)=>{
  const code=e instanceof Error?e.message:'';
  if(['owner_review_binding_changed','owner_review_conflict'].includes(code))return '商品资料或核查记录已变化。当前输入保留，请读取并核对当前核查包。';
  if(code==='owner_review_prerequisites_missing')return '前置资料尚未齐全，不能签收。请读取当前核查包并补齐缺项。';
  if(code==='owner_review_evidence_required')return '每项已核对结论都需要填写依据或记录位置。';
  if(code==='owner_review_not_applicable_requires_reason')return '只有资质项可以声明不适用，并须填写依据与理由。';
  if(code==='owner_review_integrity')return '核查记录完整性异常，已停止签收。请检查原资料。';
  return errorText(e);
};
export function OwnerReviewPanel({target,active,dirty,busy,previewSha,onRecorded}:{target:ListingTarget;active:boolean;dirty:boolean;busy:boolean;previewSha:string;onRecorded:()=>void}){
  const [view,setView]=useState<Review|null>(null),[latest,setLatest]=useState<Review|null>(null),[checks,setChecks]=useState<Record<string,Check>>({}),[reviewer,setReviewer]=useState('');
  const [editing,setEditing]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[confirmed,setConfirmed]=useState(false),[uncertain,setUncertain]=useState(false),[productOpen,setProductOpen]=useState(false);
  const generation=useRef(0),edit=useRef(false);edit.current=editing;
  const identity=JSON.stringify(target);
  function adopt(value:Review){setView(value);setLatest(null);setChecks(structuredClone(value.checks));setReviewer(value.reviewer);setConfirmed(false);setEditing(false);setUncertain(false);}
  async function read(){
    const sequence=++generation.current;setLoading(true);setError('');
    try{const value=await api<Review>('commerce_owner_review_get',target);if(sequence!==generation.current)return;
      if(edit.current&&view){setLatest(value);setConfirmed(false);}else adopt(value);setUncertain(false);
    }catch(e){if(sequence===generation.current){setError(message(e));setUncertain(true);}}
    finally{if(sequence===generation.current)setLoading(false);}
  }
  useEffect(()=>{if(active)void read();return()=>{generation.current++;};},[identity,active,previewSha]);
  function update(key:string,part:keyof Check,value:string){setChecks(rows=>({...rows,[key]:{...rows[key],[part]:value}}));setEditing(true);setConfirmed(false);setNotice('');}
  async function record(decision:'save'|'owner_confirmed'|'rejected'|'withdrawn'){
    if(!view||loading||dirty||busy||latest||uncertain)return;const sequence=++generation.current;setLoading(true);setError('');setNotice('');
    try{const value=await api<Review>('commerce_owner_review_record',{...target,expected_binding_sha256:view.binding_sha256,expected_review_sha256:view.review_sha256,checks,reviewer,decision,confirmed,idempotency_key:newKey()});if(sequence!==generation.current)return;
      adopt(value);setNotice(decision==='save'?'核查草稿已保存。':decision==='owner_confirmed'?'已记录经营负责人签收；不属于独立认证，未提交平台。':decision==='rejected'?'已记录退回，原历史保留。':'已撤销负责人签收，原历史保留。');onRecorded();
    }catch(e){if(sequence===generation.current){setError(message(e));setConfirmed(false);setUncertain(true);}}
    finally{if(sequence===generation.current)setLoading(false);}
  }
  const ready=!!view?.automatic_checks.every(row=>row.ready),complete=!!view&&Object.entries(checks).length===Object.keys(view.requirements).length&&Object.values(checks).every(row=>['confirmed','not_applicable'].includes(row.status)&&row.source_ref.trim()&&(row.status!=='not_applicable'||row.note.trim()));
  const disabled=loading||busy||dirty||!view?.supported||!!latest||uncertain;
  return <div id="listing-owner-review" className="r-owner-review" tabIndex={-1}><Panel title="经营负责人发布前核查" action={<Button disabled={loading||busy} onClick={()=>void read()}>读取当前核查包</Button>}>
    <p className="r-footnote">由经营负责人逐项核对并签收，不属于独立认证。签收不批准店铺写入。</p><ErrorNotice>{error}</ErrorNotice>{notice&&<p role="status">{notice}</p>}
    {dirty&&<p role="status">店铺方案有未保存修改，请保存后再核查。</p>}
    {latest&&<section className="r-source-recovery"><p>已读到当前核查包。当前输入保留，采用后须重新核对逐项结论。</p><Button onClick={()=>adopt(latest)}>采用当前核查包并重新核对</Button></section>}
    {!view?<p role="status">{loading?'正在读取核查资料…':'核查资料尚未读取。'}</p>:<>
      <p><Badge tone={view.current?'blue':'gray'}>{statuses[view.status]||view.status}</Badge> · 保存修订 {view.binding.listing_revision} · {target.store_ref} / {target.market}</p>
      <ul className="r-owner-prerequisites">{view.automatic_checks.map((row,index)=><li key={row.id+index}><span>{row.label}</span><Badge tone={row.ready?'blue':'gray'}>{row.ready?'资料已具备':'待补齐'}</Badge></li>)}</ul>
      {!view.supported?<p>当前首发核查范围为 Ozon / ozon-live / RU，请返回对应店铺方案。</p>:<>
        <details onToggle={e=>setProductOpen(e.currentTarget.open)}><summary>核对保存版本的产品信息与图片</summary>{view.product&&<ListingProductReview requestId={'owner-review:'+view.binding_sha256} requestSha={view.binding_sha256} ownerTarget={target} product={view.product} active={active&&productOpen} supported revision={view.binding.listing_revision} current={!dirty&&!latest}/>}</details>
        <fieldset disabled={disabled}><label className="ui-field">经营负责人姓名或标识<input value={reviewer} maxLength={160} onChange={e=>{setReviewer(e.target.value);setEditing(true);setConfirmed(false);}}/></label>
          {Object.entries(view.requirements).map(([key,label])=><section className="r-owner-check" key={key}><h3>{label}</h3><div className="r-listing-fields"><label className="ui-field">核对结论 · {label}<select value={checks[key]?.status||'pending'} onChange={e=>update(key,'status',e.target.value)}><option value="pending">待核对</option><option value="confirmed">已逐项核对</option><option value="rejected">需修改</option>{key==='qualifications'&&<option value="not_applicable">不适用（须说明依据）</option>}</select></label><label className="ui-field">依据或记录位置 · {label}<input value={checks[key]?.source_ref||''} maxLength={1500} onChange={e=>update(key,'source_ref',e.target.value)}/></label></div><label className="ui-field">核对说明 · {label}<textarea rows={2} value={checks[key]?.note||''} maxLength={1500} onChange={e=>update(key,'note',e.target.value)}/></label></section>)}
          <label className="r-owner-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>我以经营负责人身份核对当前版本并承担签收责任；此记录不属于独立认证或平台写入授权</label>
          <div className="r-actions"><Button onClick={()=>void record('save')}>保存核查草稿</Button><Button primary disabled={!ready||!complete||!confirmed||!reviewer.trim()} onClick={()=>void record('owner_confirmed')}>签收当前版本</Button><Button disabled={!confirmed||!reviewer.trim()} onClick={()=>void record('rejected')}>退回修改</Button><Button disabled={!view.review_id||!confirmed||!reviewer.trim()} onClick={()=>void record('withdrawn')}>撤销签收</Button></div>
        </fieldset>
      </>}
      <details><summary>签收历史与版本</summary><p className="r-code">核查包 SHA256：{view.binding_sha256}</p>{view.history.length?<ol>{view.history.map(row=><li key={row.id}>{statuses[row.decision]||row.decision} · {row.reviewer||'未填写'} · {new Date(row.at).toLocaleString('zh-CN')}</li>)}</ol>:<p>尚无负责人核查记录。</p>}</details>
    </>}
  </Panel></div>;
}
