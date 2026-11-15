import {useEffect,useRef,useState} from 'react';
import {api,errorText} from './api';
import {Badge,Button,Empty,ErrorNotice,Panel} from './ui';
import type {ListingTarget} from './listing-observation';
import {ListingProductReview,type ReviewProduct} from './listing-product-review';

interface RequestView {
  id:string;sha256:string;event_sha256:string;status:string;current:boolean;connection_current:boolean;created_at:string;
  decision:string;note:string;review_note:string;missing:string[];synthetic:boolean;
  frozen:{revision:number;checks:{id:string;label:string;status:string}[];payload:ReviewProduct};
  external:{task_id:string;source_ref:string}|null;
  read:{status:string;error:string|null};last_observation_fresh:boolean;
  observation:{status:string;import_confirmed:boolean;observed_at:string;evidence:{sha256:string;endpoint:string}[]}|null;
  import_record:{status:string;product_id:string;errors:{code:string;message:string}[]}|null;
  product_record:{entity_id:string;statuses:Record<string,string|boolean>}|null;
  differences:{field:string;prepared:string|number|null;observed:string|number|null;status:string}[];
  history:{id:string;action:string;at:string;decision:string;note:string}[];
}
interface ReleaseView {image_preview_supported?:boolean;export_formats?:('json'|'html')[];request:RequestView|null;requests:{id:string;revision:number;current:boolean;created_at:string}[]}
export const releaseStatusLabels:Record<string,string>={blocked:'发布检查未关闭',outdated:'原方案已变化',needs_changes:'申请待修改',withdrawn:'本地申请已撤回',awaiting_execution_authority:'等待明确执行授权',pending:'待审阅',acknowledged:'申请已阅',not_requested:'尚未读取',running:'正在读取回执',succeeded:'本次读取已完成',failed:'本次读取失败',interrupted:'读取中断，需明确重读',empty_import_result:'导入任务未返回条目',scope_mismatch:'任务与申请 SKU 不匹配',ambiguous_import_result:'任务中存在重复 SKU',import_rejected:'平台导入被拒绝',import_issues:'导入存在待核对问题',import_pending:'平台仍在处理导入',unknown_import_status:'平台导入状态尚未适配',import_details_incomplete:'导入回执字段不完整',awaiting_product_id:'导入已受理，等待有效商品 ID',product_missing:'尚未回读到准确商品',ambiguous_product_result:'商品匹配不唯一',product_observed:'已回读对应商品，发布状态仍需核对'};
const status=releaseStatusLabels;
const eventLabels:Record<string,string>={review:'本地审阅',bind:'记录外部任务引用',read_started:'开始只读核对',read_completed:'读取回执已留存',read_failed:'读取失败',read_superseded:'旧引用结果未采用'};
const failure=(e:unknown)=>({listing_save_required:'请先保存店铺方案，再建立本地申请。',workspace_source_changed:'商品来源已变化，请核对当前资料后重新保存方案。',listing_release_conflict:'申请已有新记录。请刷新后核对；你的输入已保留。',listing_release_preview_changed:'上架方案或检查已有变化，请先核对保存版本。',listing_release_request_outdated:'原方案已变化，请对当前保存版本建立新申请。',listing_release_connection_changed:'原店铺连接已变化，需重新核对申请范围。',listing_release_external_reference_in_use:'此任务和 SKU 已关联另一申请，请打开原申请核对。',listing_release_external_reference_required:'先填写并确认实际外部任务引用。',listing_release_invalid_identifier:'请输入有效的 Ozon 任务编号，不使用科学计数法。',listing_release_demo_no_network:'示例模式不会查询实际店铺。',listing_release_read_busy:'已有回执读取在进行，请等待读取结果。',listing_release_integrity_failed:'申请或证据完整性校验失败，未采用该结果。',listing_release_withdrawn:'本地申请已撤回，不能继续修改或绑定新任务。',ozon_auth_or_permission:'当前店铺接入无此回执的读取权限。',ozon_network_error:'平台连接失败，已保留上次证据。',ozon_rate_limited:'平台已限流，请稍后明确重读。'}as Record<string,string>)[e instanceof Error?e.message:'']||errorText(e);
type Form={createNote:string;reviewNote:string;decision:string;taskId:string;source:string};
const blank=():Form=>({createNote:'',reviewNote:'',decision:'acknowledged',taskId:'',source:''});

export function ListingReleasePanel({target,previewSha,active,dirty,busy,saved}:{target:ListingTarget;previewSha:string;active:boolean;dirty:boolean;busy:boolean;saved:boolean}){
  const [data,setData]=useState<ReleaseView|null>(null),[selected,setSelected]=useState(''),[form,setForm]=useState<Form>(blank),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [downloading,setDownloading]=useState(false),downloadInFlight=useRef(false);
  const [loading,setLoading]=useState(false),[working,setWorking]=useState(false),[confirmCreate,setConfirmCreate]=useState(false),[confirmReview,setConfirmReview]=useState(false),[confirmBind,setConfirmBind]=useState(false);
  const epoch=useRef(0),writing=useRef(false),mounted=useRef(true),forms=useRef(new Map<string,Form>()),attempts=useRef(new Map<string,{signature:string;key:string}>());
  const identity=JSON.stringify(target),formKey=identity+':'+selected;
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;epoch.current++;};},[]);
  useEffect(()=>{epoch.current++;setSelected('');setData(null);setError('');setNotice('');},[identity]);
  useEffect(()=>{setForm(forms.current.get(formKey)||blank());setConfirmCreate(false);setConfirmReview(false);setConfirmBind(false);},[formKey]);
  useEffect(()=>{setConfirmCreate(false);setConfirmReview(false);setConfirmBind(false);},[previewSha,active,data?.request?.event_sha256]);
  function edit<K extends keyof Form>(key:K,value:Form[K]){setForm(old=>{const next={...old,[key]:value};forms.current.set(formKey,next);return next;});}
  async function load(requestId=selected){const n=++epoch.current;setLoading(true);
    try{const v=await api<ReleaseView>('commerce_listing_release_get',{...target,...(requestId?{request_id:requestId}:{})});if(n!==epoch.current||!mounted.current)return;setData(v);if(!requestId&&v.request){const next=identity+':'+v.request.id;const pending=forms.current.get(formKey);if(pending&&!forms.current.has(next))forms.current.set(next,pending);setSelected(v.request.id);}}
    catch(e){if(n===epoch.current&&mounted.current)setError(failure(e));}
    finally{if(n===epoch.current&&mounted.current)setLoading(false);}
  }
  useEffect(()=>{epoch.current++;if(active)void load();return()=>{epoch.current++;};},[identity,selected,previewSha,active]);
  const request=data?.request,reading=request?.read.status==='running';
  useEffect(()=>{if(!active||!reading)return;const timer=setTimeout(()=>void load(),600);return()=>clearTimeout(timer);},[active,reading,data]);
  async function action(kind:'create'|'review'|'bind'|'refresh'){
    if(writing.current)return;const r=data?.request;if(kind!=='create'&&!r)return;
    writing.current=true;setWorking(true);setError('');setNotice('');const n=++epoch.current;
    const args=kind==='create'?{...target,expected_preview_sha256:previewSha,note:form.createNote,confirmed:confirmCreate}:{request_id:r!.id,expected_event_sha256:r!.event_sha256,...(kind==='review'?{decision:form.decision,note:form.reviewNote,confirmed:confirmReview}:kind==='bind'?{task_id:form.taskId,source_ref:form.source,confirmed:confirmBind}:{})};
    const signature=JSON.stringify(args),key=formKey+':'+kind;let attempt=attempts.current.get(key);
    if(!attempt||attempt.signature!==signature){attempt={signature,key:crypto.randomUUID()};attempts.current.set(key,attempt);}
    try{const result=await api<{request_id:string}>('commerce_listing_release_'+kind,{...args,idempotency_key:attempt.key});if(n!==epoch.current||!mounted.current)return;
      setConfirmCreate(false);setConfirmReview(false);setConfirmBind(false);setNotice(kind==='create'?'已记录本地申请，未向平台提交。':kind==='bind'?'已记录外部引用，需读取接口核对。':kind==='review'?'已记录本地决定，原专业与发布门禁保留。':'已开始只读核对，未重发平台提交。');
      if(result.request_id!==selected)setSelected(result.request_id);await load(result.request_id);
    }catch(e){if(n===epoch.current&&mounted.current){setError(failure(e));await load();}}
    finally{writing.current=false;if(mounted.current)setWorking(false);}
  }
  async function download(format:'json'|'html'='json'){if(!request||downloadInFlight.current)return;const n=epoch.current;downloadInFlight.current=true;setDownloading(true);setError('');try{let unavailable=0;if(format==='html'&&data?.image_preview_supported){for(let index=0;index<request.frozen.payload.fields.image_refs.length;index++){if(n!==epoch.current||!mounted.current)return;try{await api('commerce_listing_release_image',{request_id:request.id,expected_request_sha256:request.sha256,index});}catch{unavailable++;}}}const v=await api<{content:string;filename:string}>('commerce_listing_release_export',{request_id:request.id,expected_event_sha256:request.event_sha256,...(format==='html'?{format}:{})});if(n!==epoch.current||!mounted.current)return;const url=URL.createObjectURL(new Blob([v.content],{type:format==='html'?'text/html;charset=utf-8':'application/json'}));const a=document.createElement('a');a.href=url;a.download=v.filename;document.body.append(a);a.click();a.remove();if(unavailable)setNotice(`已导出，${unavailable} 张图片未读到，审阅包已明确标注。`);setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){if(n===epoch.current&&mounted.current)setError(failure(e));}finally{downloadInFlight.current=false;if(mounted.current)setDownloading(false);}}
  const locked=busy||working||downloading,closed=request?.decision==='withdrawn';
  return <div className="r-listing-observation" id="listing-release" tabIndex={-1}><Panel title="发布申请与外部回执" action={<Button disabled={working||loading} onClick={()=>{setError('');void load();}}>刷新申请记录</Button>}>
    <ErrorNotice>{error}</ErrorNotice>{notice&&<p role="status">{notice}</p>}
    {request&&<ListingProductReview requestId={request.id} requestSha={request.sha256} product={request.frozen.payload} active={active} supported={!!data?.image_preview_supported} revision={request.frozen.revision} current={request.current}/>}
    <div className="r-observation-grid"><section aria-label="本地发布申请">
      <details open={!request}><summary>{request?'建立新版本申请':'建立本地发布申请'}</summary><label className="ui-field">申请说明<textarea rows={3} value={form.createNote} maxLength={2000} onChange={e=>edit('createNote',e.target.value)}/></label>
      <label><input type="checkbox" checked={confirmCreate} onChange={e=>setConfirmCreate(e.target.checked)}/>确认只建立当前保存版本的本地申请，不提交平台</label>
      {dirty&&<p>当前编辑尚未保存，保存后再建立申请。</p>}{!saved&&<p>先保存店铺方案，再建立版本固定的申请。</p>}
      <div className="r-form-actions"><Button primary disabled={locked||dirty||!saved||!form.createNote.trim()||!confirmCreate} onClick={()=>void action('create')}>建立本地发布申请</Button></div></details>
      {data?.requests.length?<label className="ui-field">已保存的发布申请<select value={selected} aria-label="已保存的发布申请" disabled={locked} onChange={e=>setSelected(e.target.value)}>{data.requests.map(r=><option key={r.id} value={r.id}>修订 {r.revision} · {r.id.slice(0,8)} · {r.current?'当前方案':'旧方案'}</option>)}</select></label>:<Empty>{loading?'正在读取原申请账本…':'此店铺方案尚无本地发布申请。'}</Empty>}
      {request&&<><p role="status"><Badge>{status[request.status]||request.status}</Badge>{request.synthetic&&' · 合成验收资料'}</p>
        <p>申请商品：{request.frozen.payload.fields.sku||'SKU 未填'} · {request.frozen.payload.fields.title||'标题未填'} · 修订 {request.frozen.revision}</p>
        <p>{request.note}</p>{request.review_note&&<p>审阅记录：{request.review_note}</p>}{!request.connection_current&&<p>原店铺连接已变化，旧引用不能自动用于新连接。</p>}
        <details><summary>固定版本与未关闭检查 · {request.missing.length} 项</summary><p className="r-code">{request.sha256}</p><ul>{request.frozen.checks.filter(c=>c.status!=='prepared').map(c=><li key={c.id}>{c.label}</li>)}</ul></details>
        <fieldset disabled={locked||closed||dirty}><legend>记录申请审阅</legend><label className="ui-field">申请处理决定<select aria-label="申请处理决定" value={form.decision} onChange={e=>edit('decision',e.target.value)}><option value="acknowledged">已阅申请，保留原门禁</option><option value="needs_changes">退回补充或修改</option><option value="withdrawn">撤回本地申请，不撤回平台任务</option></select></label>
          <label className="ui-field">申请审阅说明<textarea rows={3} maxLength={2000} value={form.reviewNote} onChange={e=>edit('reviewNote',e.target.value)}/></label><label><input type="checkbox" checked={confirmReview} onChange={e=>setConfirmReview(e.target.checked)}/>确认记录当前申请版本的本地决定</label><div className="r-form-actions"><Button disabled={!confirmReview||!form.reviewNote.trim()} onClick={()=>void action('review')}>记录申请审阅</Button></div>
        </fieldset><div className="r-actions"><Button disabled={locked||loading} onClick={()=>void download()}>导出申请与回执</Button>{data?.export_formats?.includes('html')&&<Button disabled={locked||loading} onClick={()=>void download('html')}>导出可读审阅包</Button>}</div>
      </>}
    </section><section aria-label="外部任务与商品回读">
      {!request?<Empty>建立本地申请后，可记录你另行提交的 Ozon 任务并读取回执。</Empty>:<>
        <p>本系统没有向平台提交该申请。外部任务引用须由接口按同店铺、SKU 和商品 ID 核对。</p>
        {target.platform==='ozon'&&target.store_ref==='ozon-live'&&target.market==='RU'?<>
          <details open={!request.external}><summary>{request.external?'更换或补充外部任务引用':'记录外部 Ozon 任务'}</summary><fieldset disabled={locked||closed||dirty||!request.connection_current}><legend>外部引用资料</legend><label className="ui-field">Ozon 导入任务编号<input inputMode="numeric" maxLength={19} value={form.taskId} onChange={e=>edit('taskId',e.target.value)}/></label><label className="ui-field">外部提交依据<input maxLength={1000} value={form.source} onChange={e=>edit('source',e.target.value)}/></label><label><input type="checkbox" checked={confirmBind} onChange={e=>setConfirmBind(e.target.checked)}/>确认这是我另行提交的外部任务，引用尚需核对</label><div className="r-form-actions"><Button disabled={!confirmBind||!form.taskId||!form.source.trim()} onClick={()=>void action('bind')}>记录外部任务引用</Button></div></fieldset></details>
          {request.external&&<><p>已绑定外部任务：{request.external.task_id}</p><p>{request.external.source_ref}</p><Button disabled={locked||reading||!request.connection_current} onClick={()=>void action('refresh')}>读取并核对外部回执</Button></>}
        </>:<Empty>当前平台的任务回执读取尚未接入，原申请记录与检查继续保留。</Empty>}
        <p role="status">{status[request.read.status]||'读取状态未确认'}</p>{request.read.error&&<ErrorNotice>{failure(new Error(request.read.error))}</ErrorNotice>}
        {closed&&<p>撤回仅作用于本地申请，平台任务没有被取消；已绑定的原任务仍可只读核对。</p>}
        {request.observation&&<><p role="status"><Badge>{status[request.observation.status]||'平台状态尚未确认'}</Badge></p><p className="r-footnote">{request.last_observation_fresh?'上次证据在有效期内':'上次证据已过期'} · {new Date(request.observation.observed_at).toLocaleString()}</p>
          {request.import_record&&<p>平台原始导入状态：{request.import_record.status} · 商品 ID：{request.import_record.product_id}</p>}
          {request.import_record?.errors.map((e,i)=><p key={i}>{e.code}：{e.message}</p>)}
          {request.product_record&&<details><summary>平台返回状态</summary>{Object.entries(request.product_record.statuses).map(([k,v])=><p key={k}>{k}：{String(v)}</p>)}</details>}
          {request.differences.length>0&&<div className="r-table-wrap" role="region" aria-label="申请版本与商品回读差异" tabIndex={0}><table className="data-table"><thead><tr><th>字段</th><th>申请版本</th><th>平台回读</th><th>核对</th></tr></thead><tbody>{request.differences.map(d=><tr key={d.field}><th>{{title:'标题',price:'售价',currency:'币种',quantity:'数量'}[d.field]||d.field}</th><td>{d.prepared??'未填'}</td><td>{d.observed??'未返回'}</td><td>{{same:'相同',different:'有差异',not_comparable:'口径不可比较',unknown:'未知'}[d.status]||d.status}</td></tr>)}</tbody></table></div>}
          <details><summary>回执证据版本</summary>{request.observation.evidence.map(e=><p className="r-code" key={e.sha256}>{e.endpoint} · {e.sha256}</p>)}</details>
        </>}
      </>}
    </section></div>
    {request&&<details><summary>申请记录 · 最近 {request.history.length} 条</summary><ul>{request.history.map(e=><li key={e.id}>{new Date(e.at).toLocaleString()} · {eventLabels[e.action]||e.action}{e.action==='review'&&` · ${status[e.decision]||e.decision} · ${e.note}`}</li>)}</ul></details>}
    <p className="r-footnote">本地申请与审阅不解除独立合规或平台发布门禁。导入受理、商品存在、审核通过和可售分别核对；SKU/商品 ID 对应也不证明外部提交内容与此固定版本完全一致。</p>
  </Panel></div>;
}
