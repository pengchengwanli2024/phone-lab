import './listing-actions.css';
import {useEffect,useRef,useState} from 'react';
import {api,newKey,errorText} from './api';
import {Badge,Button,Panel,Empty,ErrorNotice} from './ui';
import type {ListingTarget} from './listing-observation';

type Check={status:'pending'|'confirmed'|'rejected';source_ref:string;note:string};
interface Action {id:string;sha256:string;event_sha256:string;product_id:string;sku:string;before_images:string[];after_images:string[];current:boolean;approval_fresh:boolean;
  state:{status:string;checks:Record<string,Check>;reviewer:string;review_mode:string;dispatch_started:boolean;error?:string;receipt_sha256?:string;observation?:{sha256:string;exact_images:boolean;observed_at:string;images:string[];errors_present:boolean}}}
interface View {inventory_current:boolean;case_id:string;source_sha256:string;requirements:Record<string,string>;gallery:{sha256:string;images:string[];fresh:boolean;special_images:boolean;errors_present:boolean;observed_at:string}|null;items:Action[];refresh:{status:string}|null}
type ReviewDraft={checks:Record<string,Check>;reviewer:string;mode:string;confirmed:boolean;dirty:boolean;event:string};
const urlMemory=new Map<string,{value:string;dirty:boolean}>(),reviewMemory=new Map<string,ReviewDraft>(),resultMemory=new Map<string,string>();
export const listingActionLabels:Record<string,string>={draft:'待核对图片',approved:'本次人工图片核对已记录',rejected:'本次图片已退回',checking:'执行前核对平台图库',submitting:'提交已开始，等待返回',awaiting_readback:'接口已返回，等待实际图库回读',unknown:'结果未确认，请先回读',verifying:'正在只读回读图库',observed:'已回读到目标图片顺序',conflict:'原图库或依据已变化',cancelled:'本地图片动作已撤销',owner_confirmed:'已记录人工逐图核对完成'};
const failure=(e:unknown)=>({listing_action_not_found:'未找到指定图片动作，请从日常运营重新选择准确记录。',listing_action_scope_changed:'指定图片动作与当前商品或店铺不匹配，未采用其它动作。',listing_action_fresh_inventory_required:'请先在店铺连接同步新鲜库存并核对商品范围。',listing_action_inventory_scope_changed:'当前库存未精确匹配此商品与履约范围，未执行图库修改。',listing_action_read_gallery_first:'请先读取新鲜的平台图库。',listing_action_no_change:'新旧图库相同，未创建经营动作。',listing_action_gallery_changed:'平台图库已有变化，请重新读取并准备新版本。',listing_action_nonstandard_gallery:'此首期动作只支持无色卡图、无360图且没有图片错误的标准图库。',listing_action_conflict:'已有新记录，你的审核输入已保留。请读取并核对当前版本。',listing_action_review_incomplete:'批准本次图片前，请选择本人核对、填写核对人并补齐四项依据。',listing_action_other_outcome_unresolved:'同一商品还有结果未确认的图片提交，请先回读原动作。',listing_action_approval_required:'缺少当前有效的本次图片批准，或原动作已尝试提交。',listing_action_cannot_cancel_remote:'提交已开始，不能把本地撤销当作平台取消。',listing_action_real_existing_product_required:'此处只支持已连接的真实Ozon现有商品。',listing_action_invalid_images:'请填写1–20条不重复的公开HTTPS图片直链。',listing_action_connection_changed:'店铺凭据已变化，请核对当前连接和原动作。',listing_action_busy:'已有图库读取或图片提交在进行，请等待当前结果。',workspace_source_changed:'商品来源已变化，请核对当前资料后重新准备。'}as Record<string,string>)[e instanceof Error?e.message:'']||errorText(e);

export function ListingActionsPanel({target,active,dirty,requestedActionId='',onSelectAction}:{target:ListingTarget;active:boolean;dirty:boolean;requestedActionId?:string;onSelectAction:(id:string)=>void}){
  const [data,setData]=useState<View|null>(null),[selected,setSelected]=useState(''),[urls,setUrls]=useState(''),[urlDirty,setUrlDirty]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false),[executeConfirmed,setExecuteConfirmed]=useState(false),[epoch,setEpoch]=useState(0);
  const urlDrafts=useRef(urlMemory),currentCase=useRef(target.case_id),selection=useRef(selected);currentCase.current=target.case_id;selection.current=selected;
  const resultNotes=useRef(resultMemory),previews=useRef(new Map<string,string[]>());const [resultConfirmed,setResultConfirmed]=useState(false);
  const drafts=useRef(reviewMemory),generation=useRef(0),pending=useRef<{fingerprint:string;key:string}|null>(null),editingUrls=useRef(urlDirty);editingUrls.current=urlDirty;
  const action=data?.items.find(a=>a.id===selected)||data?.items[0],draft=action?drafts.current.get(action.id):undefined;
  function adopt(value:View){setData(value);if(!editingUrls.current)setUrls(value.gallery?.images.join('\n')||'');for(const item of value.items){const local=drafts.current.get(item.id);if(!local||!local.dirty)drafts.current.set(item.id,{checks:structuredClone(item.state.checks),reviewer:item.state.reviewer,mode:item.state.review_mode,confirmed:false,dirty:false,event:item.event_sha256});}}
  async function load(actionId=selection.current){if(currentCase.current!==target.case_id)return;const version=++generation.current;try{const value=await api<View>('commerce_listing_action_get',{case_id:target.case_id,...(actionId?{action_id:actionId}:{})});if(version===generation.current){adopt(value);setError('');}}catch(e){if(version===generation.current){setError(failure(e));setExecuteConfirmed(false);setResultConfirmed(false);setData(previous=>previous?{...previous,inventory_current:false,gallery:previous.gallery?{...previous.gallery,fresh:false}:null,items:previous.items.map(item=>({...item,current:false}))}:null);}}}
  useEffect(()=>{generation.current++;setData(null);setSelected(requestedActionId);selection.current=requestedActionId;const saved=urlDrafts.current.get(target.case_id);setUrls(saved?.value||'');setUrlDirty(!!saved?.dirty);editingUrls.current=!!saved?.dirty;setBusy(false);setExecuteConfirmed(false);pending.current=null;if(active)void load(requestedActionId);return()=>{generation.current++;};},[target.case_id,target.store_ref,target.platform,requestedActionId]);
  useEffect(()=>{if(active&&!dirty)void load();},[active]);
  const running=data?.refresh?.status==='running';
  useEffect(()=>{if(!active||!running)return;const timer=setInterval(()=>void load(),1500);return()=>clearInterval(timer);},[active,running,target.case_id]);
  useEffect(()=>{setExecuteConfirmed(false);setResultConfirmed(false);},[action?.id,action?.event_sha256]);
  function edit(change:(d:ReviewDraft)=>void){if(!draft)return;change(draft);draft.dirty=true;setEpoch(v=>v+1);}
  function key(kind:string,payload:object){const fingerprint=JSON.stringify([kind,payload]);if(pending.current?.fingerprint!==fingerprint)pending.current={fingerprint,key:newKey()};return pending.current.key;}
  async function run(kind:'refresh'|'prepare'|'save'|'approved'|'rejected'|'submit'|'readback'|'cancel'|'finish'){
    if(busy||!data)return;const scope=target.case_id;setBusy(true);setError('');
    try{
      if(kind==='refresh')await api('commerce_listing_action_refresh',{case_id:target.case_id});
      else if(kind==='prepare'){
        const payload={case_id:target.case_id,expected_source_sha256:data.source_sha256,expected_gallery_sha256:data.gallery?.sha256||'',image_urls:urls.split('\n').map(v=>v.trim()).filter(Boolean)};
        const made=await api<{id:string}>('commerce_listing_action_prepare',{...payload,idempotency_key:key(kind,payload)});if(currentCase.current!==scope)return;setSelected(made.id);selection.current=made.id;onSelectAction(made.id);setUrlDirty(false);editingUrls.current=false;urlDrafts.current.set(scope,{value:urls,dirty:false});
      }else if(action){
        const base={action_id:action.id,expected_event_sha256:['save','approved','rejected'].includes(kind)?draft?.event||'':action.event_sha256};
        if(['save','approved','rejected'].includes(kind)&&draft){
          const payload={...base,checks:draft.checks,decision:kind,reviewer:draft.reviewer,review_mode:draft.mode,confirmed:draft.confirmed};
          await api('commerce_listing_action_review',{...payload,idempotency_key:key(kind,payload)});draft.dirty=false;
        }else{
          const payload={...base,...(kind==='submit'?{expected_action_sha256:action.sha256,confirmed:executeConfirmed}:kind==='finish'?{expected_observation_sha256:action.state.observation?.sha256||'',note:resultNotes.current.get(action.id)||'',confirmed:resultConfirmed}:{})};
          await api('commerce_listing_action_'+kind,{...payload,idempotency_key:key(kind,payload)});
        }
      }
      if(currentCase.current!==scope)return;pending.current=null;await load();setExecuteConfirmed(false);
    }catch(e){if(currentCase.current===scope)setError(failure(e));}finally{if(currentCase.current===scope)setBusy(false);}
  }
  async function loadImages(){if(!action?.state.observation||busy)return;const scope=target.case_id,observed=action.state.observation;setBusy(true);setError('');try{const items:string[]=[];for(let index=0;index<observed.images.length;index++){const image=await api<{mime:string;content_base64:string}>('commerce_listing_action_image',{action_id:action.id,expected_observation_sha256:observed.sha256,index});items.push(`data:${image.mime};base64,${image.content_base64}`);if(currentCase.current!==scope)return;}previews.current.set(observed.sha256,items);setEpoch(v=>v+1);}catch(e){if(currentCase.current===scope)setError(failure(e));}finally{if(currentCase.current===scope)setBusy(false);}}
  return <section id="listing-image-actions" tabIndex={-1} data-form-epoch={epoch}><Panel title="现有商品图片变更" action={<Button disabled={busy||dirty} onClick={()=>void load()}>读取当前记录</Button>}>
    <ErrorNotice>{error}</ErrorNotice>
    <p className="r-footnote">只更新此商品的标准图库；新数组会替换原数组，首张作为主图。本次人工图片核对不构成独立合规认证，原 S6 门禁与整卡上架状态分别保留。</p>
    {data&&!data.inventory_current&&<p>店铺库存观测已过期或商品范围已变化。请先在店铺连接显式同步，再返回核对；当前图片输入会保留。</p>}{dirty?<Empty>先保存当前上架编辑，再准备准确的图片变更。</Empty>:!data?<Empty>{error?'图片动作资料未读回，请核对当前连接后重试。':'正在读取图片变更记录…'}</Empty>:<>
      <div className="r-actions"><Button disabled={busy||running} onClick={()=>void run('refresh')}>读取平台当前图库</Button>{running&&<span role="status">正在读取或执行，请等待真实状态…</span>}</div>
      <details open={!action}><summary>准备图片前后差异</summary>
        {!data.gallery?<p>尚无图库快照。请先同步当前店铺资料并读取平台图库。</p>:<><p>原图库 {data.gallery.images.length} 张 · {data.gallery.fresh?'观测仍有效':'观测已过期'} · {new Date(data.gallery.observed_at).toLocaleString()}</p><ol>{data.gallery.images.map(u=><li key={u} className="r-code">{u}</li>)}</ol></>}
        <label className="ui-field">新图库HTTPS直链，每行一张<textarea aria-label="新图库HTTPS直链，每行一张" rows={5} maxLength={42000} value={urls} onChange={e=>{setUrls(e.target.value);setUrlDirty(true);urlDrafts.current.set(target.case_id,{value:e.target.value,dirty:true});}}/></label>
        <Button disabled={busy||running||!data.gallery?.fresh||!data.inventory_current} onClick={()=>void run('prepare')}>固定图片变更版本</Button>
      </details>
      {data.items.length>1&&<label className="ui-field">图片动作版本<select value={action?.id||''} onChange={e=>{setSelected(e.target.value);selection.current=e.target.value;onSelectAction(e.target.value);}}>{data.items.map((a,i)=><option key={a.id} value={a.id}>{i+1} · {listingActionLabels[a.state.status]||a.state.status}</option>)}</select></label>}
      {action&&draft&&<>
        <p role="status"><Badge>{listingActionLabels[action.state.status]||action.state.status}</Badge> · SKU {action.sku} · 商品 ID {action.product_id}</p>
        {!action.current&&<p>原来源或连接已变化，不能提交此旧动作。</p>}
        <details><summary>准确图库差异：{action.before_images.length} → {action.after_images.length} 张</summary><div className="r-table-wrap"><table className="data-table"><thead><tr><th>顺序</th><th>原图库</th><th>本次图库</th></tr></thead><tbody>{Array.from({length:Math.max(action.before_images.length,action.after_images.length)},(_,i)=><tr key={i}><th>{i+1}{i===0?' · 主图':''}</th><td className="r-code">{action.before_images[i]||'无'}</td><td className="r-code">{action.after_images[i]||'移除'}</td></tr>)}</tbody></table></div></details>
        {draft.dirty&&draft.event!==action.event_sha256&&<p>审核记录已有变化。你的输入已保留；重新采用前请核对当前版本。<Button onClick={()=>{draft.dirty=false;adopt(data);setEpoch(v=>v+1);}}>采用当前审核记录</Button></p>}
        <details open={action.state.status==='draft'||action.state.status==='rejected'||!!draft.dirty}><summary>本次图片人工核对</summary><fieldset disabled={busy||running||action.state.dispatch_started||action.state.status==='cancelled'}><legend>核对依据</legend>
          <label className="ui-field">核对方式<select aria-label="核对方式" value={draft.mode} onChange={e=>edit(d=>{d.mode=e.target.value;})}><option value="">请选择</option><option value="owner_manual">本人基于资料逐项核对本次图片</option></select></label>
          <label className="ui-field">核对人声明<input aria-label="核对人声明" maxLength={160} value={draft.reviewer} onChange={e=>edit(d=>{d.reviewer=e.target.value;})}/></label>
          <p className="r-footnote">核对人名称为操作者声明，系统未验证独立审核身份。需要独立审核人的商品应继续保持未批准。</p>
          {Object.entries(data.requirements).map(([name,label])=><div key={name} className="r-form-grid"><label className="ui-field">{label}<select aria-label={label+'结论'} value={draft.checks[name].status} onChange={e=>edit(d=>{d.checks[name].status=e.target.value as Check['status'];})}><option value="pending">待核对</option><option value="confirmed">已核对并提供依据</option><option value="rejected">不通过</option></select></label><label className="ui-field">{label}依据<input aria-label={label+'依据'} maxLength={1000} value={draft.checks[name].source_ref} onChange={e=>edit(d=>{d.checks[name].source_ref=e.target.value;})}/></label><label className="ui-field">{label}说明<textarea aria-label={label+'说明'} rows={2} maxLength={1000} value={draft.checks[name].note} onChange={e=>edit(d=>{d.checks[name].note=e.target.value;})}/></label></div>)}
          <label><input type="checkbox" checked={draft.confirmed} onChange={e=>edit(d=>{d.confirmed=e.target.checked;})}/>确认本次人工核对声明；批准仅限上述图片数组</label>
          <div className="r-actions"><Button onClick={()=>void run('save')}>保存核对草稿</Button><Button disabled={!draft.confirmed} onClick={()=>void run('rejected')}>退回本次图片</Button><Button disabled={!action.current||!draft.confirmed||draft.mode!=='owner_manual'||!draft.reviewer.trim()||Object.values(draft.checks).some(c=>c.status!=='confirmed'||!c.source_ref.trim())} onClick={()=>void run('approved')}>批准本次图片版本</Button></div>
        </fieldset></details>
        {action.state.status==='approved'&&<div><p>执行前会重新读取平台图库；若已被其他操作者修改，本次提交停止。批准有效期30分钟。</p><label><input type="checkbox" checked={executeConfirmed} onChange={e=>setExecuteConfirmed(e.target.checked)}/>我明确授权将此商品图库替换为上述完整数组</label><div className="r-actions"><Button disabled={busy||running||!executeConfirmed||draft.dirty||!action.current||!action.approval_fresh||!data.inventory_current} onClick={()=>void run('submit')}>执行一次图片更新</Button></div></div>}
        <div className="r-actions"><Button disabled={busy||running||!action.state.dispatch_started||['observed','owner_confirmed'].includes(action.state.status)} onClick={()=>void run('readback')}>只读核对平台图片结果</Button><Button disabled={busy||action.state.dispatch_started||action.state.status==='cancelled'} onClick={()=>void run('cancel')}>撤销本地图片动作</Button></div>
        {action.state.error&&<p>最近操作：{failure(new Error(action.state.error))}</p>}
        {action.state.observation&&<section aria-label="平台图库结果核对"><p>图库回读：{new Date(action.state.observation.observed_at).toLocaleString()} · {action.state.observation.exact_images?'图片地址及顺序精确一致':'地址尚未精确匹配，可能经过平台转存，需逐图核对'}</p>
          <Button disabled={busy||running} onClick={()=>void loadImages()}>查看平台回读图片</Button>
          <div className="r-listing-action-previews">{previews.current.get(action.state.observation.sha256)?.map((url,i)=><figure key={url.slice(-50)+i}><img src={url} alt={'平台回读图片 '+(i+1)}/><figcaption>{i+1}{i===0?' · 平台主图':''}</figcaption></figure>)}</div>
          {action.state.status==='unknown'&&<><label className="ui-field">逐图核对说明<textarea aria-label="逐图核对说明" rows={2} value={resultNotes.current.get(action.id)||''} onChange={e=>{resultNotes.current.set(action.id,e.target.value);setEpoch(v=>v+1);}} maxLength={1000}/></label><label><input type="checkbox" checked={resultConfirmed} onChange={e=>setResultConfirmed(e.target.checked)}/>我已逐张核对平台当前图片与顺序，确认与本次图片方案一致</label><div className="r-actions"><Button disabled={busy||running||!resultConfirmed||!resultNotes.current.get(action.id)?.trim()||previews.current.get(action.state.observation.sha256)?.length!==action.state.observation.images.length} onClick={()=>void run('finish')}>记录人工逐图完成</Button></div><p className="r-footnote">只记录你的视觉核对声明；原始回读与地址未精确匹配的事实仍保留，不冒充平台自动证明。</p></>}
        </section>}
        <p className="r-footnote">接口返回不等于图片更新完成。结果未知时先回读，不重复提交；已提交动作不能通过本地撤销取消平台处理。</p>
      </>}
    </>}
  </Panel></section>;
}
