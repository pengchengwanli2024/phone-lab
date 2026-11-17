import {useEffect,useRef,useState} from 'react';
import {api} from './api';
import {Badge,Button} from './ui';
import type {ListingTarget} from './listing-observation';
import type {ListingFields,ListingFieldOverrides} from './listing-inheritance';
import {checkedListingImage,listingImagePresentation,originalListingImage,sameListingTarget,sourceField,type ListingCatalog} from './listing-choice';
import '../../web/catalog-presentation.js';
import './listing-context.css';

declare global {interface Window {CommerceCatalogPresentation:{plain:(value:unknown)=>string}}}
const valueText=(value:unknown)=>value===null||value===undefined||value===''?'未提供':Array.isArray(value)?value.length+' 张图片链接':window.CommerceCatalogPresentation.plain(value);
function CompareValue({value}:{value:unknown}){const text=valueText(value);return text.length>240?<><span>{text.slice(0,240)}…</span><details><summary>展开完整字段</summary><p>{text}</p></details></>:<>{text}</>;}
const fieldLabels={sku:'SKU',title:'标题',description:'描述',category_id:'类目',price:'售价',currency:'币种',quantity:'计划数量'};
export function ListingIdentityStrip({catalog,name,target,sourceSha}:{catalog:ListingCatalog|null;name:string;target:ListingTarget;sourceSha:string}){
  const current=catalog?.source_sha256===sourceSha?catalog:null,identity=current?.store_identity;
  const known=identity?.kind==='store'&&identity.platform===target.platform&&identity.store_ref===target.store_ref&&identity.market===target.market;
  return <div className="r-listing-current-sticky" role="region" aria-label="当前编辑商品身份"><strong>{current?.name||name}</strong><span>SKU {current?.sku||'身份未读到'}</span><span>原店铺：{identity?.label||(current?.kind==='candidate'?'调研候选 · 未绑定店铺':'身份未读到')}</span><span>目标：{target.platform==='ozon'?'Ozon':target.platform} · {known?identity?.label:target.store_ref||'店铺未选择'} · {target.market||'市场未选择'}</span></div>;
}

export function ListingContext({catalog:readCatalog,error,name,target,selected,base,fields,overrides,revision,stale,dirty,active,busy,sourceSha,productDraft,onCanonical,onProduct,onReadSelected,onRestoreSelected}:{
  catalog:ListingCatalog|null;error:string;name:string;target:ListingTarget;selected:ListingTarget;sourceSha:string;
  productDraft?:{revision:number;stale:boolean;source_sha256:string|null;has_payload:boolean};
  base?:ListingFields;fields:ListingFields;overrides:ListingFieldOverrides;revision:number;stale:boolean;dirty:boolean;active:boolean;busy:boolean;
  onCanonical:(target:ListingTarget)=>void;onProduct:(id:string,tab?:string)=>void;onReadSelected:()=>void;onRestoreSelected:()=>void;
}){
  const catalog=readCatalog?.source_sha256===sourceSha?readCatalog:null;
  const [image,setImage]=useState<{state:'loading'|'ready'|'failed';src?:string;key?:string}>({state:'loading'}),[retry,setRetry]=useState(0);
  const epoch=useRef(0),original=catalog?originalListingImage(catalog):null;
  const pictureInfo=listingImagePresentation(catalog,original?.image);
  const imageKey=JSON.stringify([catalog?.id,catalog?.source_sha256,original?.image.id]),currentImageKey=useRef(imageKey);currentImageKey.current=imageKey;
  useEffect(()=>{
    const sequence=++epoch.current;setImage({state:'loading',key:imageKey});
    if(!active||!catalog||!original)return;
    void api<{mime:string;content_base64:string;sha256:string}>('commerce_catalog_image',{case_id:catalog.id,expected_source_sha256:catalog.source_sha256,index:original.index,image_id:original.image.id})
      .then(async v=>{if(sequence!==epoch.current)return;const src=await checkedListingImage(v);if(sequence===epoch.current)setImage({state:'ready',src,key:imageKey});})
      .catch(()=>{if(sequence===epoch.current)setImage({state:'failed',key:imageKey});});
    return()=>{epoch.current++;};
  },[active,catalog?.id,catalog?.source_sha256,original?.image.id,retry]);
  const identity=catalog?.store_identity,alias=!!catalog?.primary_case_id&&catalog.primary_case_id!==target.case_id;
  const platform=target.platform==='ozon'?'Ozon':target.platform;
  const currentName=catalog?.name||name,sku=catalog?.sku||fields.sku||'待补充';
  const pending=!sameListingTarget(target,selected);
  const knownTarget=identity?.kind==='store'&&identity.platform===target.platform&&identity.store_ref===target.store_ref&&identity.market===target.market;
  const targetLabel=knownTarget?identity.label||target.store_ref:target.store_ref||'尚未选择';
  return <section className="r-listing-context" aria-label="当前已读取商品与目标">
    {pending&&<div className="r-source-recovery" role="status"><p>选择器中的商品或店铺尚未读取；当前显示「{currentName}」，编辑和发布操作已暂锁。</p><div className="r-actions"><Button disabled={busy} onClick={onReadSelected}>读取所选商品与店铺</Button><Button disabled={busy} onClick={onRestoreSelected}>恢复当前商品与店铺选择</Button></div></div>}
    <div className="r-listing-context-main"><div className="r-listing-picture"><div className="r-listing-context-image">{original&&image.state==='ready'&&image.key===imageKey?<img src={image.src} alt={currentName+' · '+pictureInfo.alt} onError={()=>{if(currentImageKey.current===imageKey)setImage({state:'failed',key:imageKey});}}/>:<div role="status">{!catalog?'商品原图资料未读到':!original?(catalog.kind==='candidate'?'当前工作项未登记参考图':'当前工作项未登记产品原图'):image.state==='loading'||image.key!==imageKey?(catalog.kind==='candidate'?'正在读取参考图…':'正在读取原图…'):(catalog.kind==='candidate'?'参考图未读到':'原图未读到')}{original&&image.state==='failed'&&image.key===imageKey&&<Button onClick={()=>setRetry(v=>v+1)}>{catalog?.kind==='candidate'?'重试参考图':'重试原图'}</Button>}</div>}</div>{original&&<p className="r-footnote">{pictureInfo.label}{pictureInfo.thumbnail?' · '+original.image.width+' × '+original.image.height+' px 缩略图':''}</p>}</div>
      <div className="r-listing-context-copy"><div className="r-actions"><Badge>{catalog?.synthetic?'合成验证资料':catalog?.kind==='candidate'?'调研候选 · 未入库存':catalog?.kind==='inventory'?(identity?.kind==='store'?'店铺商品 · 按来源记录':'库存工作项 · 店铺待核对'):'身份资料未读到'}</Badge><Badge>{stale?'来源已变化':dirty?'有未保存修改':revision?'本地方案修订 '+revision:'尚未保存店铺方案'}</Badge><Badge>商品信息待核对</Badge></div>
        <h2>{currentName}</h2><dl><div><dt>商品 SKU</dt><dd>{sku}</dd></div><div><dt>平台商品 ID</dt><dd>{catalog?.product_id||'未提供'}</dd></div><div><dt>原店铺</dt><dd>{identity?.label||(identity?.kind==='research_candidate'?'调研候选，尚未绑定店铺':'店铺身份未读到')}</dd></div><div><dt>本次目标</dt><dd>{platform} · {targetLabel} · {target.market||'市场未选择'}</dd></div></dl>
        <p className="r-footnote">{pictureInfo.hint}</p>
        {(error||readCatalog&&!catalog)&&<p className="alert error">{error||'原资料版本与当前方案不一致，请重新读取方案'}；不会显示上一个商品或旧版本的图片资料。</p>}
        <div className="r-actions"><Button onClick={()=>onProduct(target.case_id,'content')}>核对原商品资料</Button><Button onClick={()=>onProduct(target.case_id,'media')}>核对图片与素材</Button></div>
      </div></div>
    {alias&&<div className="r-source-recovery" aria-label="原履约范围与规范商品"><strong>你正查看同商品的原履约工作项</strong><p>当前范围：{catalog?.case?.scope?.inventory_type||'原工作项'}。该商品共有 {catalog?.case_ids?.length||1} 个履约范围；规范商品资料另存，旧方案和执行记录保持在原工作项。</p><Button disabled={busy} onClick={()=>onCanonical({case_id:catalog!.primary_case_id!,platform:identity?.platform||target.platform,store_ref:identity?.store_ref||target.store_ref,market:identity?.market||target.market})}>读取该商品的规范上架资料</Button></div>}
    <details className="r-listing-source-comparison"><summary>核对原始资料、商品工作区当前稿与本店方案</summary><p className="r-footnote">仅对照当前来源与本地稿件；不同不一定是错误，相同也不代表已核实。空白保持未提供。{productDraft?(productDraft.has_payload?'商品稿修订 '+productDraft.revision+(productDraft.stale?' 已过期，本列为当前可继承资料。':' · 已读取。'):'商品工作区尚未保存优化稿。'):'商品稿修订未提供。'}</p><div className="r-listing-compare-scroll"><table><thead><tr><th>字段</th><th>采集原值</th><th>商品工作区当前稿</th><th>本店当前编辑{dirty?' · 未保存':' · 保存修订 '+revision}</th></tr></thead><tbody>{(Object.keys(fieldLabels)as (keyof typeof fieldLabels)[]).map(key=><tr key={key}><th scope="row">{fieldLabels[key]}</th><td><CompareValue value={sourceField(catalog,key)}/></td><td><CompareValue value={base?.[key]}/></td><td><small>{Object.hasOwn(overrides,key)?'本店单独修改':'沿用商品当前稿'}</small><CompareValue value={fields[key]}/></td></tr>)}</tbody></table></div><details><summary>查看准确资料范围与来源标识</summary><dl><div><dt>工作项 ID</dt><dd><code>{target.case_id}</code></dd></div><div><dt>来源 SHA</dt><dd><code>{catalog?.source_sha256||'未读到'}</code></dd></div>{catalog?.fields?.filter(f=>['title','description','attributes'].includes(f.key)).map(f=><div key={f.key}><dt>{f.key} 来源位置</dt><dd>{f.locator||'来源未提供位置'}</dd></div>)}</dl></details></details>
  </section>;
}
