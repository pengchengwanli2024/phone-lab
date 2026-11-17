import { useEffect, useRef, useState } from 'react';
import {enrichProductChoices} from './product-label';
import {listingChoices,listingChoiceLabel,listingStores,sameListingTarget,type ListingCatalog,type ListingChoice} from './listing-choice';
import {ListingContext,ListingIdentityStrip} from './listing-context';
import { api, errorText } from './api';
import { Badge, Button, Empty, ErrorNotice, Panel } from './ui';
import type { CaseItem } from './types';
import './operations-workbench.css';
import {ListingObservation,type ListingTarget} from './listing-observation';
import {ListingSchemaPanel,type OzonPayload} from './listing-schema';
import {ListingReleasePanel} from './listing-release';
import {ListingActionsPanel} from './listing-actions';
import {OwnerReviewPanel} from './owner-review';
import {StorefrontDraft} from './storefront-draft';
import {gapFields} from './listing-gap-actions';
import {OperatingGuide} from './operating-guide';
import {ListingInheritedField} from './listing-inherited-field';
import {changedListingOverrides,listingOverrides,listingSaveArguments,rebaseListingFields,supportsInheritance,type ListingFields,type ListingFieldOverrides} from './listing-inheritance';

type Target=ListingTarget;
type Fields=ListingFields;
type Payload={fields:Fields;language:string;fulfillment:string;rules_ref:string;attributes:{name:string;value:string;source_ref:string}[];ozon?:OzonPayload};
interface Listing {submission_available?:boolean;owner_review_available?:boolean;target:Target;payload:Payload;base_fields?:Fields;base_sha256?:string;field_overrides?:ListingFieldOverrides;product_draft?:{revision:number;stale:boolean;source_sha256:string|null;has_payload:boolean};name:string;revision:number;source_sha256:string;stale:boolean;preview_sha256:string;platforms:Record<string,string>;missing:string[];saved_targets:(Target&{revision:number;stale:boolean})[];checks:{id:string;label:string;status:string}[];invalid_source_fields:string[];synthetic:boolean}
const platforms:Record<string,string>={ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu',shopify:'Shopify',woocommerce:'WooCommerce'};
const message=(e:unknown)=>{
  const code=e instanceof Error?e.message:'';
  if(code==='listing_preview_changed')return '准备包的资料或检查已有变化，请读取当前版本后再导出。';
  if(code.startsWith('listing_invalid_'))return '请核对字段、原币金额、整数数量及HTTPS图片链接。';
  if(code==='listing_save_required')return '请先保存当前店铺方案。';
  if(code==='listing_base_fields_changed'||code==='listing_base_fields_required')return '商品基础资料已更新，请核对当前版本后再保存店铺差异。';
  return errorText(e);
};
export function ListingPage({demo,active,caseId,onProduct,onCase,requestedTarget,requestedAction,onSelectAction,onPlatform,onTargetLoaded}:{demo:boolean;active:boolean;caseId:string;onCase:(id:string)=>void;onProduct:(id:string,tab?:string)=>void;requestedTarget?:Target|null;requestedAction?:{target:Target;id:string}|null;onSelectAction:(target:Target,id:string)=>void;onPlatform:()=>void;onTargetLoaded:(target:Target)=>void}) {
  const [cases,setCases]=useState<ListingChoice[]>([]),[catalogCards,setCatalogCards]=useState<ListingCatalog[]>([]),[target,setTarget]=useState<Target>({case_id:caseId,platform:'ozon',store_ref:'',market:''});
  const [catalog,setCatalog]=useState<ListingCatalog|null>(null),[catalogError,setCatalogError]=useState(''),[choiceError,setChoiceError]=useState(''),[customStore,setCustomStore]=useState(false);
  const [data,setData]=useState<Listing|null>(null),[payload,setPayload]=useState<Payload|null>(null),[dirty,setDirty]=useState(false);
  const [overrides,setOverrides]=useState<ListingFieldOverrides>({});
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[review,setReview]=useState<Listing|null>(null),[checked,setChecked]=useState(false);
  const [targetOpen,setTargetOpen]=useState(true);
  const [guideOpen,setGuideOpen]=useState(false);
  const [pending,setPending]=useState<Target|null>(null);
  const handledTarget=useRef<Target|null|undefined>(null);
  const epoch=useRef(0),dirtyRef=useRef(dirty),loaded=useRef<Target|null>(null),mode=useRef(demo);dirtyRef.current=dirty;
  useEffect(()=>{
    let alive=true;
    void Promise.all([api<{items:CaseItem[]}>('commerce_workspace_list'),api<{items:ListingCatalog[]}>('commerce_catalog_list',{kind:'all'}).catch(()=>null)])
      .then(async([raw,grouped])=>{const enriched=await enrichProductChoices(raw.items.filter(c=>c.synthetic===demo));if(!alive)return;
        const cards=grouped?.items.filter(c=>c.synthetic===demo)||[];setCatalogCards(cards);setCases(listingChoices(cards,enriched,demo,requestedTarget?.case_id||caseId));
        setChoiceError(grouped?'':'规范商品目录未读到；当前仅保留原入口工作项，请刷新或返回商品工作区。');})
      .catch(e=>{if(alive){setCases([]);setCatalogCards([]);setChoiceError(message(e));}});
    return ()=>{alive=false;};
  },[demo,active,caseId,requestedTarget?.case_id]);
  useEffect(()=>{
    if(mode.current!==demo){mode.current=demo;setGuideOpen(false);epoch.current++;loaded.current=null;setData(null);setPayload(null);setCatalog(null);setCatalogError('');setOverrides({});setReview(null);setDirty(false);setPending(null);setTarget({case_id:'',platform:'ozon',store_ref:'',market:''});setTargetOpen(true);setError('');setBusy(false);setCustomStore(false);}
  },[demo]);
  async function load(next:Target,discard=false) {
    if(dirtyRef.current&&!discard){setPending(next);return;}
    const sequence=++epoch.current;setBusy(true);setError('');setNotice('');setReview(null);setChecked(false);setData(null);setPayload(null);setCatalog(null);setCatalogError('');setPending(null);if(discard)setDirty(false);loaded.current=null;
    try {const [value,product]=await Promise.all([api<Listing>('commerce_listing_get',next),api<ListingCatalog>('commerce_catalog_get',{case_id:next.case_id}).catch(()=>null)]);if(sequence!==epoch.current)return;setData(value);setPayload(structuredClone(value.payload));setOverrides(listingOverrides(value));setCatalog(product?.id===value.target.case_id&&product.synthetic===demo?product:null);setCatalogError(product?.id===value.target.case_id?'':'商品原始资料未读到');loaded.current=value.target;onCase(value.target.case_id);onTargetLoaded(value.target);setTarget(value.target);setDirty(false);setPending(null);setTargetOpen(!value.target.store_ref||!value.target.market);}
    catch(e){if(sequence===epoch.current)setError(message(e));}
    finally{if(sequence===epoch.current)setBusy(false);}
  }
  useEffect(()=>{if(!active){epoch.current++;handledTarget.current=null;setBusy(false);}},[active]);
  useEffect(()=>{
    if(requestedTarget||!active||!caseId||!cases.some(c=>c.id===caseId)||loaded.current?.case_id===caseId)return;
    const product=cases.find(c=>c.id===caseId)!;
    void load({case_id:caseId,platform:product.platform||'ozon',store_ref:'',market:product.market||''});
  },[caseId,active,cases]);
  useEffect(()=>{if(!requestedTarget){handledTarget.current=null;return;}if(active&&requestedTarget!==handledTarget.current&&cases.some(c=>c.id===requestedTarget.case_id)){handledTarget.current=requestedTarget;void load(requestedTarget);}},[requestedTarget,active,cases]);
  useEffect(()=>{if(active&&data&&!requestedTarget&&loaded.current?.case_id===caseId)onTargetLoaded(data.target);},[active,caseId,data?.preview_sha256,requestedTarget]);
  function change(update:(p:Payload)=>Payload){if(!payload)return;const next=update(payload);setOverrides(previous=>changedListingOverrides(payload.fields,next.fields,previous));setPayload(next);setDirty(true);setNotice('');}
  function overrideField(key:keyof Fields){if(!payload)return;setOverrides(previous=>({...previous,[key]:payload.fields[key]}));setDirty(true);setNotice('');requestAnimationFrame(()=>document.getElementById('listing-field-'+key)?.focus());}
  function restoreField(key:keyof Fields){if(!payload||!data?.base_fields)return;setOverrides(previous=>{const next={...previous};delete next[key];return next;});setPayload({...payload,fields:{...payload.fields,[key]:data.base_fields[key]}});setDirty(true);setNotice('');requestAnimationFrame(()=>document.getElementById('listing-override-'+key)?.focus());}
  async function save(){
    if(!data||!payload||busy||!sameListingTarget(data.target,target))return;const sequence=++epoch.current;setBusy(true);setError('');setNotice('');
    try{const value=await api<Listing>('commerce_listing_save',listingSaveArguments(data,payload,overrides));if(sequence!==epoch.current)return;setData(value);setPayload(structuredClone(value.payload));setOverrides(listingOverrides(value));setDirty(false);setReview(null);setNotice('店铺上架方案已保存，尚未提交平台。');}
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
    if(!data||dirty||data.stale||!sameListingTarget(data.target,target))return;const sequence=++epoch.current;setBusy(true);setError('');
    try{const value=await api<{filename:string;content:string}>('commerce_listing_export',{...data.target,expected_preview_sha256:data.preview_sha256});if(sequence!==epoch.current)return;
      const url=URL.createObjectURL(new Blob([value.content],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download=value.filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);setNotice('已导出私有准备包；其中保留未关闭检查，不是平台发布回执。');}
    catch(e){if(sequence===epoch.current)setError(message(e));}
    finally{if(sequence===epoch.current)setBusy(false);}
  }
  function resolveCheck(id:string){
    if(data&&payload){const field=gapFields(id,payload,data.target,data.invalid_source_fields)[0];if(field){const key=field.id.replace('listing-field-','')as keyof Fields;if(field.id.startsWith('listing-field-')&&supportsInheritance(data)&&!Object.hasOwn(overrides,key)){onProduct(data.target.case_id,'content');return;}if(id==='identity')setTargetOpen(true);requestAnimationFrame(()=>{const el=document.getElementById(field.id);el?.scrollIntoView({block:'center'});el?.focus();});return;}}
    if(id==='platform_schema'&&data?.target.platform!=='ozon'){onPlatform();return;}
    if(!data)return;if(id==='media'){onProduct(data.target.case_id,'media');return;}if(id==='professional_gate'){if(data.owner_review_available){const el=document.getElementById('listing-owner-review');el?.scrollIntoView({block:'start'});el?.focus();}else onProduct(data.target.case_id,'review');return;}if(id==='platform_adapter'){if(data.target.platform==='ozon'){const el=document.getElementById('listing-release');el?.scrollIntoView({block:'start'});el?.focus();}else onPlatform();return;}if(id==='source'||id==='source_fields'){void inspect();return;}
    const fields:Record<string,string>={identity:'listing-store-ref',content:'listing-field-sku',offer:'listing-field-price',locale:'listing-language',rules:'listing-rules_ref',attributes:'listing-add-attribute',platform_schema:'listing-platform-schema'};if(id==='identity')setTargetOpen(true);requestAnimationFrame(()=>{const field=document.getElementById(fields[id]);field?.scrollIntoView({block:'center'});field?.focus();});
  }
  const targetReady=!!(data?.target.store_ref&&data?.target.market);
  const targetPending=!!data&&!sameListingTarget(data.target,target),requiresSave=dirty||targetPending;
  const stores=listingStores(catalogCards,demo).filter(s=>s.platform===target.platform);
  const useCustomStore=customStore||!stores.length||!!target.store_ref&&!stores.some(s=>s.store_ref===target.store_ref);
  const contextPanel=data&&payload?<ListingContext catalog={catalog} error={catalogError} name={data.name} target={data.target} selected={target} sourceSha={data.source_sha256} productDraft={data.product_draft} base={data.base_fields} fields={payload.fields} overrides={overrides} revision={data.revision} stale={data.stale} dirty={dirty} active={active} busy={busy} onCanonical={next=>void load(next)} onReadSelected={()=>void load(target)} onRestoreSelected={()=>{setTarget(data.target);setCustomStore(false);}} onProduct={onProduct}/>:null;
  const field=(key:keyof Fields,label:string)=>payload&&data&&<ListingInheritedField key={key} field={key} label={label} value={payload.fields[key]} overridden={Object.hasOwn(overrides,key)} inheritanceAvailable={supportsInheritance(data)} onChange={value=>change(p=>({...p,fields:{...p.fields,[key]:value}}))} onOverride={()=>overrideField(key)} onRestore={()=>restoreField(key)}/>;
  return <div className="r-page r-listing-page" data-ai-page="listing" data-ai-context={JSON.stringify({demo:data?.synthetic??demo,filters:data?{platform:data.target.platform,store_ref:data.target.store_ref,market:data.target.market}:{},...(data?{entity:{kind:"case",id:data.target.case_id,name:data.name}}:{}),source_refs:data?.preview_sha256?{listing:data.preview_sha256}:{},input:data&&payload?{sku:payload.fields.sku,title:payload.fields.title,description:payload.fields.description,category_id:payload.fields.category_id,price:payload.fields.price,currency:payload.fields.currency,quantity:payload.fields.quantity}:{}})}><div className="r-page-heading"><h1>上架准备</h1>{data&&<div className="r-actions">{!demo&&data.target.platform==='ozon'&&data.target.store_ref==='ozon-live'&&data.target.market==='RU'&&<Button onClick={()=>{const node=document.getElementById('listing-image-actions');node?.scrollIntoView({block:'start'});node?.focus({preventScroll:true});}}>图片变更</Button>}<Button onClick={()=>onProduct(data.target.case_id)}>返回原商品</Button></div>}</div>
    {data&&payload&&<><ListingIdentityStrip catalog={catalog} name={data.name} target={data.target} sourceSha={data.source_sha256}/>{contextPanel}</>}
    <details className="r-listing-target-selector" open={targetOpen} onToggle={e=>setTargetOpen(e.currentTarget.open)}><summary>选择商品与目标店铺</summary><form className="r-listing-target" onSubmit={e=>{e.preventDefault();void load(target);}}>
      {data&&data.saved_targets.length>0&&<label className="ui-field">已保存的店铺方案<select disabled={busy} value="" onChange={e=>{const t=data.saved_targets[Number(e.target.value)];if(!t)return;const next={case_id:t.case_id,platform:t.platform,store_ref:t.store_ref,market:t.market};setTarget(next);void load(next);}}><option value="">选择已保存方案</option>{data.saved_targets.map((t,i)=><option key={i} value={i}>{platforms[t.platform]} · {t.store_ref||'店铺待填'} · {t.market||'市场待填'} · 修订 {t.revision}{t.stale?' · 资料已变化':''}</option>)}</select></label>}
      <label className="ui-field">商品<select disabled={busy} value={target.case_id} onChange={e=>{const product=cases.find(c=>c.id===e.target.value);setCustomStore(false);setTarget({...target,case_id:e.target.value,platform:product?.platform||target.platform,store_ref:product?.store?.active?product.store.store_ref||'':'',market:product?.market||''});}}><option value="">选择商品</option>{cases.map(c=><option key={c.id} value={c.id}>{listingChoiceLabel(c)}</option>)}</select></label>
      <label className="ui-field">目标平台<select disabled={busy} value={target.platform} onChange={e=>{setCustomStore(false);setTarget({...target,platform:e.target.value,store_ref:'',market:''});}}>{Object.entries(platforms).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
      {stores.length>0&&<label className="ui-field">已连接店铺<select id={useCustomStore?'listing-store-choice':'listing-store-ref'} disabled={busy} value={useCustomStore?'__custom__':target.store_ref} onChange={e=>{if(e.target.value==='__custom__'){setCustomStore(true);return;}setCustomStore(false);const selected=stores.find(s=>s.store_ref===e.target.value);setTarget({...target,store_ref:selected?.store_ref||'',market:selected?.market||target.market});}}><option value="">选择目标店铺</option>{stores.map(s=><option key={s.connection_id||s.store_ref} value={s.store_ref}>{s.label} · {s.market}</option>)}<option value="__custom__">自定义店铺标识</option></select></label>}
      {useCustomStore&&<label className="ui-field">目标店铺标识<input id="listing-store-ref" disabled={busy} value={target.store_ref} maxLength={100} onChange={e=>setTarget({...target,store_ref:e.target.value})} placeholder="填写准确店铺标识，勿填密钥"/></label>}
      <label className="ui-field">国家/市场代码<input id="listing-market" disabled={busy} value={target.market} maxLength={2} onChange={e=>setTarget({...target,market:e.target.value.toUpperCase()})} placeholder="例如 RU"/></label>
      <Button type="submit" disabled={!cases.some(c=>c.id===target.case_id)||busy}>读取店铺方案</Button>
    </form><p className="r-listing-target-status">商品选项按规范商品身份显示，保留旧履约入口。选择后点击「读取店铺方案」才切换下方内容；不会保存或提交。</p>{choiceError&&<ErrorNotice>{choiceError}</ErrorNotice>}</details>
    <ErrorNotice>{error}</ErrorNotice><p role="status">{busy?'正在核对当前方案…':notice}</p>
    {pending&&<section className="r-source-recovery" aria-label="未保存上架方案"><p>当前方案有未保存修改，是否切换到所选店铺方案？</p><div className="r-actions"><Button onClick={()=>{setPending(null);if(loaded.current){setTarget(loaded.current);onTargetLoaded(loaded.current);}}}>保留当前编辑</Button><Button onClick={()=>void load(pending,true)}>放弃修改并读取</Button></div></section>}
    {review&&<section className="r-source-recovery" aria-label="核对上架保存版本"><h2>核对当前保存版本</h2><p>保存修订 {review.revision} · {review.stale?'原绑定资料已变化':'当前商品资料已读回'}。本地输入保持。</p><dl>{(['title','price','currency','quantity'] as const).map(k=><div key={k}><dt>{{title:'标题',price:'售价',currency:'币种',quantity:'数量'}[k]}</dt><dd>{String(payload?.fields[k]??'未填')} → {String(review.payload.fields[k]??'未填')}</dd></div>)}</dl>
      <label><input type="checkbox" checked={checked} onChange={e=>setChecked(e.target.checked)}/>已核对当前商品资料与保存版本</label><div className="r-actions"><Button disabled={!checked} onClick={()=>{setData(review);setPayload(structuredClone(review.payload));setOverrides(listingOverrides(review));setDirty(false);setReview(null);setError('');}}>采用保存版本</Button><Button disabled={!checked} onClick={()=>{setData(review);if(payload)setPayload(rebaseListingFields(payload,review,overrides));setDirty(true);setReview(null);setError('');setNotice('本地店铺差异已保留，请核对后保存当前资料版本。');}}>保留本地修改后重新保存</Button></div></section>}
    {!data||!payload?<Empty>{cases.length?'选择商品和目标范围，读取上架准备方案。':'当前模式尚无商品工作项。'}</Empty>:<>
      {data.invalid_source_fields.length>0&&<ErrorNotice>原内容中的{data.invalid_source_fields.map(k=>({sku:'SKU',title:'标题',description:'描述',category_id:'类目',price:'售价',currency:'币种',quantity:'数量',image_refs:'图片链接'}[k]||k)).join('、')}格式需要核对，已暂留空，请补充有效资料。</ErrorNotice>}
      <details open={guideOpen} onToggle={e=>setGuideOpen(e.currentTarget.open)}><summary>查看同商品经营缺项</summary><OperatingGuide target={data.target} version={data.preview_sha256} dirty={requiresSave} active={active&&guideOpen&&!busy&&!targetPending} checkLabels={Object.fromEntries(data.checks.map(c=>[c.id,c.label]))} onGap={resolveCheck} onProduct={onProduct} onPolicy={()=>resolveCheck(data.checks.find(c=>['rules','professional_gate','platform_schema'].includes(c.id)&&c.status!=='prepared')?.id||'rules')}/></details>
      <div className="r-listing-grid"><Panel title="商品资料与店铺差异" action={<Button disabled={targetPending} onClick={()=>onProduct(data.target.case_id,'content')}>编辑商品资料</Button>}><fieldset disabled={busy||targetPending}><div className="r-listing-fields">{field('sku','SKU')}{field('title','商品标题')}{field('category_id','目标类目 ID')}{field('price','售价（原币）')}{field('currency','币种')}{field('quantity','计划上架数量')}</div>{field('description','商品描述')}
        {field('image_refs','图片 HTTPS 链接（每行一条）')}
        <div className="r-listing-fields">{(['language','fulfillment','rules_ref'] as const).map(k=><label className="ui-field" key={k}>{{language:'目标语言',fulfillment:'履约方案/仓库依据',rules_ref:'平台/站点/类目规则依据'}[k]}<input id={'listing-'+k} value={payload[k]} maxLength={1000} onChange={e=>change(p=>({...p,[k]:e.target.value}))}/></label>)}</div>
        <h3>平台属性</h3>{payload.attributes.map((row,i)=><div className="r-listing-attribute" key={i}>{(['name','value','source_ref'] as const).map(k=><label className="ui-field" key={k}>{{name:'属性名',value:'属性值',source_ref:'资料依据'}[k]}<input id={`listing-attribute-${i}-${k}`} value={row[k]} maxLength={1000} onChange={e=>change(p=>({...p,attributes:p.attributes.map((r,j)=>j===i?{...r,[k]:e.target.value}:r)}))}/></label>)}<Button aria-label={`移除属性 ${i+1}`} onClick={()=>change(p=>({...p,attributes:p.attributes.filter((_,j)=>j!==i)}))}>移除</Button></div>)}
        <div className="r-form-actions"><Button id="listing-add-attribute" disabled={payload.attributes.length>=100||targetPending} onClick={()=>change(p=>({...p,attributes:[...p.attributes,{name:'',value:'',source_ref:''}]}))}>添加属性</Button><Button primary disabled={targetPending} onClick={()=>void save()}>保存店铺方案</Button></div></fieldset></Panel>
      {targetReady?<Panel title="发布前检查">{requiresSave?<p role="status">{targetPending?'所选商品或店铺尚未读取，请先读取或恢复当前选择。':'当前输入尚未保存，保存后更新检查结果。'}</p>:<ul className="r-listing-checks">{data.checks.map(c=><li key={c.id}><span>{c.label}</span>{c.status!=='prepared'&&<Button className="r-check-action" aria-label={'处理检查：'+c.label} onClick={()=>resolveCheck(c.id)}>处理</Button>}<Badge tone={c.status==='prepared'?'blue':'gray'}>{{prepared:'资料已填',missing:'待补充',blocked:'待接入核验',stale:'已变化'}[c.status]||c.status}</Badge></li>)}</ul>}
        <p className="r-footnote">准备材料不等于平台发布；提交与回读单独核对。</p>
        <div className="r-actions"><Button disabled={busy||targetPending} onClick={()=>void inspect()}>核对保存版本</Button><Button disabled={busy||requiresSave||data.stale||!data.revision} onClick={()=>void exportPackage()}>导出准备包</Button><Button onClick={()=>onProduct(data.target.case_id,'media')}>图片与视频</Button><Button onClick={()=>onProduct(data.target.case_id,'review')}>交付审阅</Button><Button onClick={()=>{const el=document.getElementById('listing-release');el?.scrollIntoView({block:'start'});el?.focus();}}>申请与回执</Button></div>
      </Panel>:<Panel title="下一步"><p>先选择目标店铺与市场，再核对发布资料。</p><Button onClick={()=>{setTargetOpen(true);requestAnimationFrame(()=>document.getElementById('listing-store-ref')?.focus());}}>选择目标店铺</Button></Panel>}{targetReady&&<>{data.target.platform==='ozon'&&<ListingSchemaPanel publicationSupported={!!data.submission_available} target={data.target} payload={payload} active={active} previewSha={data.preview_sha256} dirty={requiresSave} busy={busy} onChange={(category,ozon)=>change(p=>({...p,fields:{...p.fields,category_id:category},ozon}))} onSave={()=>void save()}/>}{data.owner_review_available&&<OwnerReviewPanel key={JSON.stringify(data.target)} target={data.target} active={active} dirty={requiresSave} busy={busy} previewSha={data.preview_sha256} onRecorded={()=>{const sequence=epoch.current;void api<Listing>('commerce_listing_get',data.target).then(value=>{if(sequence===epoch.current&&!dirtyRef.current){setData(value);setPayload(structuredClone(value.payload));setOverrides(listingOverrides(value));}}).catch(e=>{if(sequence===epoch.current)setError(message(e));});}}/>}{['shopify','woocommerce'].includes(data.target.platform)&&<StorefrontDraft target={data.target} previewSha={data.preview_sha256} dirty={requiresSave} saved={data.revision>0} active={active} onPlatform={onPlatform}/>}<ListingReleasePanel saved={data.revision>0} target={data.target} previewSha={data.preview_sha256} dirty={requiresSave} active={active} busy={busy}/>{!demo&&data.target.platform==='ozon'&&data.target.store_ref==='ozon-live'&&data.target.market==='RU'&&<ListingActionsPanel target={data.target} active={active} dirty={requiresSave} requestedActionId={requestedAction&&Object.keys(data.target).every(key=>data.target[key as keyof Target]===requestedAction.target[key as keyof Target])?requestedAction.id:''} onSelectAction={id=>onSelectAction(data.target,id)}/>}<ListingObservation target={data.target} previewSha={data.preview_sha256} dirty={requiresSave} active={active} onTarget={next=>void load(next)} onPlatform={onPlatform}/></>}</div></>}
  </div>;
}
