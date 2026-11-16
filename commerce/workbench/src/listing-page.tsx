import { useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import { Badge, Button, Empty, ErrorNotice, Panel } from './ui';
import type { CaseItem } from './types';
import './operations-workbench.css';
import {ListingObservation,type ListingTarget} from './listing-observation';
import {ListingSchemaPanel,type OzonPayload} from './listing-schema';
import {ListingReleasePanel} from './listing-release';
import {ListingActionsPanel} from './listing-actions';
import {OwnerReviewPanel} from './owner-review';

type Target=ListingTarget;
type Fields={sku:string;title:string;description:string;category_id:string;price:string|number;currency:string;quantity:number|null;image_refs:string[]};
type Payload={fields:Fields;language:string;fulfillment:string;rules_ref:string;attributes:{name:string;value:string;source_ref:string}[];ozon?:OzonPayload};
interface Listing {submission_available?:boolean;owner_review_available?:boolean;target:Target;payload:Payload;name:string;revision:number;source_sha256:string;stale:boolean;preview_sha256:string;platforms:Record<string,string>;missing:string[];saved_targets:(Target&{revision:number;stale:boolean})[];checks:{id:string;label:string;status:string}[];invalid_source_fields:string[];synthetic:boolean}
const platforms:Record<string,string>={ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu',shopify:'Shopify',woocommerce:'WooCommerce'};
const message=(e:unknown)=>{
  const code=e instanceof Error?e.message:'';
  if(code==='listing_preview_changed')return '准备包的资料或检查已有变化，请读取当前版本后再导出。';
  if(code.startsWith('listing_invalid_'))return '请核对字段、原币金额、整数数量及HTTPS图片链接。';
  if(code==='listing_save_required')return '请先保存当前店铺方案。';
  return errorText(e);
};
export function ListingPage({demo,active,caseId,onProduct,onCase,requestedTarget,requestedAction,onSelectAction,onPlatform,onTargetLoaded}:{demo:boolean;active:boolean;caseId:string;onCase:(id:string)=>void;onProduct:(id:string,tab?:string)=>void;requestedTarget?:Target|null;requestedAction?:{target:Target;id:string}|null;onSelectAction:(target:Target,id:string)=>void;onPlatform:()=>void;onTargetLoaded:(target:Target)=>void}) {
  const [cases,setCases]=useState<CaseItem[]>([]),[target,setTarget]=useState<Target>({case_id:caseId,platform:'ozon',store_ref:'',market:''});
  const [data,setData]=useState<Listing|null>(null),[payload,setPayload]=useState<Payload|null>(null),[dirty,setDirty]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[review,setReview]=useState<Listing|null>(null),[checked,setChecked]=useState(false);
  const [targetOpen,setTargetOpen]=useState(true);
  const [pending,setPending]=useState<Target|null>(null);
  const handledTarget=useRef<Target|null|undefined>(null);
  const epoch=useRef(0),dirtyRef=useRef(dirty),loaded=useRef<Target|null>(null),mode=useRef(demo);dirtyRef.current=dirty;
  useEffect(()=>{
    let alive=true;
    void api<{items:CaseItem[]}>('commerce_workspace_list').then(result=>{if(alive)setCases(result.items.filter(c=>c.synthetic===demo));}).catch(e=>{if(alive)setError(message(e));});
    return ()=>{alive=false;};
  },[demo,active]);
  useEffect(()=>{
    if(mode.current!==demo){mode.current=demo;epoch.current++;loaded.current=null;setData(null);setPayload(null);setReview(null);setDirty(false);setPending(null);setTarget({case_id:'',platform:'ozon',store_ref:'',market:''});setTargetOpen(true);setError('');setBusy(false);}
  },[demo]);
  async function load(next:Target,discard=false) {
    if(dirtyRef.current&&!discard){setPending(next);return;}
    const sequence=++epoch.current;setBusy(true);setError('');setNotice('');setReview(null);setChecked(false);
    try {const value=await api<Listing>('commerce_listing_get',next);if(sequence!==epoch.current)return;setData(value);setPayload(structuredClone(value.payload));loaded.current=value.target;onCase(value.target.case_id);onTargetLoaded(value.target);setTarget(value.target);setDirty(false);setPending(null);setTargetOpen(!value.target.store_ref||!value.target.market);}
    catch(e){if(sequence===epoch.current)setError(message(e));}
    finally{if(sequence===epoch.current)setBusy(false);}
  }
  useEffect(()=>{
    if(requestedTarget||!active||!caseId||!cases.some(c=>c.id===caseId)||loaded.current?.case_id===caseId)return;
    const product=cases.find(c=>c.id===caseId)!;
    void load({case_id:caseId,platform:product.platform||'ozon',store_ref:'',market:product.market||''});
  },[caseId,active,cases]);
  useEffect(()=>{if(!requestedTarget){handledTarget.current=null;return;}if(active&&requestedTarget!==handledTarget.current&&cases.some(c=>c.id===requestedTarget.case_id)){handledTarget.current=requestedTarget;void load(requestedTarget);}},[requestedTarget,active,cases]);
  useEffect(()=>{if(active&&data&&!requestedTarget&&loaded.current?.case_id===caseId)onTargetLoaded(data.target);},[active,caseId,data?.preview_sha256,requestedTarget]);
  function change(update:(p:Payload)=>Payload){setPayload(p=>p?update(p):p);setDirty(true);setNotice('');}
  async function save(){
    if(!data||!payload||busy)return;const sequence=++epoch.current;setBusy(true);setError('');setNotice('');
    try{const value=await api<Listing>('commerce_listing_save',{...data.target,payload,expected_revision:data.revision,expected_source_sha256:data.source_sha256});if(sequence!==epoch.current)return;setData(value);setPayload(structuredClone(value.payload));setDirty(false);setReview(null);setNotice('店铺上架方案已保存，尚未提交平台。');}
    catch(e){if(sequence===epoch.current)setError(message(e));}
    finally{if(sequence===epoch.current)setBusy(false);}
  }
  async function inspect(){
    if(!data)return;const sequence=++epoch.current;setBusy(true);setError('');setChecked(false);
    try{const latest=await api<Listing>('commerce_listing_get',data.target);if(sequence===epoch.current)setReview(latest);}
    catch(e){if(sequence===epoch.current)setError(message(e));}
    finally{if(sequence===epoch.current)setBusy(false);}
  }
  async function exportPackage(){
    if(!data||dirty||data.stale)return;const sequence=++epoch.current;setBusy(true);setError('');
    try{const value=await api<{filename:string;content:string}>('commerce_listing_export',{...data.target,expected_preview_sha256:data.preview_sha256});if(sequence!==epoch.current)return;
      const url=URL.createObjectURL(new Blob([value.content],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download=value.filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);setNotice('已导出私有准备包；其中保留未关闭检查，不是平台发布回执。');}
    catch(e){if(sequence===epoch.current)setError(message(e));}
    finally{if(sequence===epoch.current)setBusy(false);}
  }
  function resolveCheck(id:string){
    if(id==='platform_schema'&&data?.target.platform!=='ozon'){onPlatform();return;}
    if(!data)return;if(id==='media'){onProduct(data.target.case_id,'media');return;}if(id==='professional_gate'){if(data.owner_review_available){const el=document.getElementById('listing-owner-review');el?.scrollIntoView({block:'start'});el?.focus();}else onProduct(data.target.case_id,'review');return;}if(id==='platform_adapter'){if(data.target.platform==='ozon'){const el=document.getElementById('listing-release');el?.scrollIntoView({block:'start'});el?.focus();}else onPlatform();return;}if(id==='source'||id==='source_fields'){void inspect();return;}
    const fields:Record<string,string>={identity:'listing-store-ref',content:'listing-field-sku',offer:'listing-field-price',locale:'listing-language',rules:'listing-rules_ref',attributes:'listing-add-attribute',platform_schema:'listing-platform-schema'};if(id==='identity')setTargetOpen(true);requestAnimationFrame(()=>{const field=document.getElementById(fields[id]);field?.scrollIntoView({block:'center'});field?.focus();});
  }
  const field=(key:Exclude<keyof Fields,'image_refs'>,label:string)=>payload&&<label className="ui-field" key={key}>{label}{key==='description'?<textarea id={'listing-field-'+key} rows={5} value={payload.fields[key]} onChange={e=>change(p=>({...p,fields:{...p.fields,[key]:e.target.value}}))}/>:<input id={'listing-field-'+key} value={payload.fields[key]??''} type={key==='quantity'?'number':'text'} min={key==='quantity'?0:undefined} step={key==='quantity'?1:undefined} maxLength={500} onChange={e=>change(p=>({...p,fields:{...p.fields,[key]:key==='quantity'?(e.target.value===''?null:Number(e.target.value)):e.target.value}}))}/>}</label>;
  return <div className="r-page r-listing-page"><div className="r-page-heading"><h1>上架准备</h1>{data&&<div className="r-actions">{!demo&&data.target.platform==='ozon'&&data.target.store_ref==='ozon-live'&&data.target.market==='RU'&&<Button onClick={()=>{const node=document.getElementById('listing-image-actions');node?.scrollIntoView({block:'start'});node?.focus({preventScroll:true});}}>图片变更</Button>}<Button onClick={()=>onProduct(data.target.case_id)}>返回原商品</Button></div>}</div>
    <details className="r-listing-target-selector" open={targetOpen} onToggle={e=>setTargetOpen(e.currentTarget.open)}><summary>选择商品与目标店铺</summary><form className="r-listing-target" onSubmit={e=>{e.preventDefault();void load(target);}}>
      {data&&data.saved_targets.length>0&&<label className="ui-field">已保存的店铺方案<select disabled={busy} value="" onChange={e=>{const t=data.saved_targets[Number(e.target.value)];if(!t)return;const next={case_id:t.case_id,platform:t.platform,store_ref:t.store_ref,market:t.market};setTarget(next);void load(next);}}><option value="">选择已保存方案</option>{data.saved_targets.map((t,i)=><option key={i} value={i}>{platforms[t.platform]} · {t.store_ref||'店铺待填'} · {t.market||'市场待填'} · 修订 {t.revision}{t.stale?' · 资料已变化':''}</option>)}</select></label>}
      <label className="ui-field">商品<select disabled={busy} value={target.case_id} onChange={e=>setTarget({...target,case_id:e.target.value})}><option value="">选择商品</option>{cases.map(c=><option key={c.id} value={c.id}>{c.name} · {c.market} · {c.id.slice(0,8)}</option>)}</select></label>
      <label className="ui-field">目标平台<select disabled={busy} value={target.platform} onChange={e=>setTarget({...target,platform:e.target.value})}>{Object.entries(platforms).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
      <label className="ui-field">目标店铺标识<input id="listing-store-ref" disabled={busy} value={target.store_ref} maxLength={100} onChange={e=>setTarget({...target,store_ref:e.target.value})} placeholder="填写店铺标识，勿填密钥"/></label>
      <label className="ui-field">国家/市场代码<input disabled={busy} value={target.market} maxLength={2} onChange={e=>setTarget({...target,market:e.target.value.toUpperCase()})} placeholder="例如 RU"/></label>
      <Button type="submit" disabled={!cases.some(c=>c.id===target.case_id)||busy}>读取店铺方案</Button>
    </form></details>
    <ErrorNotice>{error}</ErrorNotice><p role="status">{busy?'正在核对当前方案…':notice}</p>
    {pending&&<section className="r-source-recovery" aria-label="未保存上架方案"><p>当前方案有未保存修改，是否切换到所选店铺方案？</p><div className="r-actions"><Button onClick={()=>{setPending(null);if(loaded.current){setTarget(loaded.current);onTargetLoaded(loaded.current);}}}>保留当前编辑</Button><Button onClick={()=>void load(pending,true)}>放弃修改并读取</Button></div></section>}
    {review&&<section className="r-source-recovery" aria-label="核对上架保存版本"><h2>核对当前保存版本</h2><p>保存修订 {review.revision} · {review.stale?'原绑定资料已变化':'当前商品资料已读回'}。本地输入保持。</p><dl>{(['title','price','currency','quantity'] as const).map(k=><div key={k}><dt>{{title:'标题',price:'售价',currency:'币种',quantity:'数量'}[k]}</dt><dd>{String(payload?.fields[k]??'未填')} → {String(review.payload.fields[k]??'未填')}</dd></div>)}</dl>
      <label><input type="checkbox" checked={checked} onChange={e=>setChecked(e.target.checked)}/>已核对当前商品资料与保存版本</label><div className="r-actions"><Button disabled={!checked} onClick={()=>{setData(review);setPayload(structuredClone(review.payload));setDirty(false);setReview(null);setError('');}}>采用保存版本</Button><Button disabled={!checked} onClick={()=>{setData(review);setDirty(true);setReview(null);setError('');setNotice('本地修改已保留，请核对后保存当前资料版本。');}}>保留本地修改后重新保存</Button></div></section>}
    {!data||!payload?<Empty>{cases.length?'选择商品和目标范围，读取上架准备方案。':'当前模式尚无商品工作项。'}</Empty>:<>
      {data.invalid_source_fields.length>0&&<ErrorNotice>原内容中的{data.invalid_source_fields.map(k=>({sku:'SKU',title:'标题',description:'描述',category_id:'类目',price:'售价',currency:'币种',quantity:'数量',image_refs:'图片链接'}[k]||k)).join('、')}格式需要核对，已暂留空，请补充有效资料。</ErrorNotice>}
      <p className="r-footnote">当前编辑：{data.name} · {platforms[data.target.platform]} · {data.target.store_ref||'店铺待填'} · {data.target.market||'市场待填'} {data.synthetic&&<Badge>合成验证资料</Badge>}</p>
      <div className="r-listing-grid"><Panel title="店铺商品资料"><fieldset disabled={busy}><div className="r-listing-fields">{field('sku','SKU')}{field('title','商品标题')}{field('category_id','目标类目 ID')}{field('price','售价（原币）')}{field('currency','币种')}{field('quantity','计划上架数量')}</div>{field('description','商品描述')}
        <label className="ui-field">图片 HTTPS 链接（每行一条）<textarea rows={3} value={payload.fields.image_refs.join('\n')} onChange={e=>change(p=>({...p,fields:{...p.fields,image_refs:e.target.value.split('\n').filter(x=>x.trim())}}))}/></label>
        <div className="r-listing-fields">{(['language','fulfillment','rules_ref'] as const).map(k=><label className="ui-field" key={k}>{{language:'目标语言',fulfillment:'履约方案/仓库依据',rules_ref:'平台/站点/类目规则依据'}[k]}<input id={'listing-'+k} value={payload[k]} maxLength={1000} onChange={e=>change(p=>({...p,[k]:e.target.value}))}/></label>)}</div>
        <h3>平台属性</h3>{payload.attributes.map((row,i)=><div className="r-listing-attribute" key={i}>{(['name','value','source_ref'] as const).map(k=><label className="ui-field" key={k}>{{name:'属性名',value:'属性值',source_ref:'资料依据'}[k]}<input value={row[k]} maxLength={1000} onChange={e=>change(p=>({...p,attributes:p.attributes.map((r,j)=>j===i?{...r,[k]:e.target.value}:r)}))}/></label>)}<Button aria-label={`移除属性 ${i+1}`} onClick={()=>change(p=>({...p,attributes:p.attributes.filter((_,j)=>j!==i)}))}>移除</Button></div>)}
        <div className="r-form-actions"><Button id="listing-add-attribute" disabled={payload.attributes.length>=100} onClick={()=>change(p=>({...p,attributes:[...p.attributes,{name:'',value:'',source_ref:''}]}))}>添加属性</Button><Button primary onClick={()=>void save()}>保存店铺方案</Button></div></fieldset></Panel>
      <Panel title="发布前检查">{dirty?<p role="status">当前输入尚未保存，保存后更新检查结果。</p>:<ul className="r-listing-checks">{data.checks.map(c=><li key={c.id}><span>{c.label}</span>{c.status!=='prepared'&&<Button className="r-check-action" aria-label={'处理检查：'+c.label} onClick={()=>resolveCheck(c.id)}>处理</Button>}<Badge tone={c.status==='prepared'?'blue':'gray'}>{{prepared:'资料已填',missing:'待补充',blocked:'待接入核验',stale:'已变化'}[c.status]||c.status}</Badge></li>)}</ul>}
        <p className="r-footnote">资料已填表示准备材料存在。规则核验、平台授权、提交和发布后回读仍需各自完成。</p>
        <div className="r-actions"><Button disabled={busy} onClick={()=>void inspect()}>核对保存版本</Button><Button disabled={busy||dirty||data.stale||!data.revision} onClick={()=>void exportPackage()}>导出准备包</Button><Button onClick={()=>onProduct(data.target.case_id,'media')}>图片与视频</Button><Button onClick={()=>onProduct(data.target.case_id,'review')}>交付审阅</Button><Button onClick={()=>{const el=document.getElementById('listing-release');el?.scrollIntoView({block:'start'});el?.focus();}}>申请与回执</Button></div>
      </Panel>{data.target.platform==='ozon'&&<ListingSchemaPanel publicationSupported={!!data.submission_available} target={data.target} payload={payload} active={active} previewSha={data.preview_sha256} dirty={dirty} busy={busy} onChange={(category,ozon)=>change(p=>({...p,fields:{...p.fields,category_id:category},ozon}))} onSave={()=>void save()}/>}{data.owner_review_available&&<OwnerReviewPanel key={JSON.stringify(data.target)} target={data.target} active={active} dirty={dirty} busy={busy} previewSha={data.preview_sha256} onRecorded={()=>{const sequence=epoch.current;void api<Listing>('commerce_listing_get',data.target).then(value=>{if(sequence===epoch.current)setData(value);}).catch(e=>{if(sequence===epoch.current)setError(message(e));});}}/>}<ListingReleasePanel saved={data.revision>0} target={data.target} previewSha={data.preview_sha256} dirty={dirty} active={active} busy={busy}/>{!demo&&data.target.platform==='ozon'&&data.target.store_ref==='ozon-live'&&data.target.market==='RU'&&<ListingActionsPanel target={data.target} active={active} dirty={dirty} requestedActionId={requestedAction&&Object.keys(data.target).every(key=>data.target[key as keyof Target]===requestedAction.target[key as keyof Target])?requestedAction.id:''} onSelectAction={id=>onSelectAction(data.target,id)}/>}<ListingObservation target={data.target} previewSha={data.preview_sha256} dirty={dirty} active={active} onTarget={next=>void load(next)} onPlatform={onPlatform}/></div></>}
  </div>;
}
