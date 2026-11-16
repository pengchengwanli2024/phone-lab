import {useEffect,useRef,useState} from 'react';
import {api} from './api';
import {Button} from './ui';
import type {ListingTarget} from './listing-observation';
import './listing-product-review.css';

export interface ReviewProduct {fields:{sku:string;title:string;description:string;category_id:string;price:string|number;currency:string;quantity:number|null;image_refs:string[]};language:string;fulfillment:string;attributes:{name:string;value:string;source_ref:string}[];ozon?:import('./listing-schema').OzonPayload}
interface ImageView {status:'loading'|'ready'|'failed';url?:string;error?:string}
export function ListingProductReview({requestId,requestSha,product,active,supported,revision,current,ownerTarget}:{ownerTarget?:ListingTarget;requestId:string;requestSha:string;product:ReviewProduct;active:boolean;supported:boolean;revision:number;current:boolean}){
  const [images,setImages]=useState<Record<number,ImageView>>({}),[selected,setSelected]=useState(0);
  const cache=useRef<Record<number,ImageView>>({}),epoch=useRef(0),identity=useRef('');
  const urls=product.fields.image_refs;
  function put(index:number,value:ImageView){cache.current={...cache.current,[index]:value};setImages(cache.current);}
  async function read(index:number,generation=epoch.current){
    if(!active||!supported)return;put(index,{status:'loading'});
    try{const value=await api<{mime:string;content_base64:string}>(ownerTarget?'commerce_owner_review_image':'commerce_listing_release_image',ownerTarget?{...ownerTarget,expected_binding_sha256:requestSha,index}:{request_id:requestId,expected_request_sha256:requestSha,index});if(generation!==epoch.current)return;put(index,{status:'ready',url:`data:${value.mime};base64,${value.content_base64}`});}
    catch{if(generation===epoch.current)put(index,{status:'failed',error:'此图片未读到，请重试。'});}
  }
  useEffect(()=>{
    const key=requestId+':'+requestSha,generation=++epoch.current;
    if(identity.current!==key){identity.current=key;cache.current={};setImages({});setSelected(0);}
    if(active&&supported)void(async()=>{for(let index=0;index<urls.length;index++){if(generation!==epoch.current)return;if(!cache.current[index]||cache.current[index].status==='loading')await read(index,generation);}})();
    return()=>{epoch.current++;};
  },[requestId,requestSha,active,supported]);
  const image=images[selected],fields=product.fields;
  return <section className="r-listing-product-review" aria-label={ownerTarget?"核查产品信息与图片":"申请产品信息与图片"}><h3>产品信息与图片</h3><p className="r-footnote">{ownerTarget?'保存修订':'申请修订'} {revision} · {current?'对应当前方案':'方案已变化，请核对固定版本内容'}</p><div className="r-review-product-columns"><div>
    <div className="r-review-product-image">{image?.status==='ready'?<img src={image.url} alt={'申请产品图片 '+(selected+1)} onError={()=>put(selected,{status:'failed',error:'图片无法显示，请重新读取。'})}/>:<div role="status">{!urls.length?'此申请尚无产品图片':image?.status==='loading'?'正在读取产品图片…':image?.error||'产品图片尚未读回'}{supported&&urls.length>0&&image?.status==='failed'&&<Button onClick={()=>void read(selected)}>重试读取图片</Button>}</div>}</div>
    {urls.length>0&&<><p className="r-footnote">{selected===0?'拟上架主图':'产品图片 '+(selected+1)} · 共 {urls.length} 张 · {ownerTarget?'保存方案固定版本':'申请固定版本'}</p><div className="r-review-product-thumbnails" aria-label="产品图片顺序">{urls.map((_,index)=><button key={index} type="button" aria-label={'查看产品图片 '+(index+1)} aria-pressed={selected===index} onClick={()=>setSelected(index)}>{images[index]?.status==='ready'?<img src={images[index].url} alt=""/>:<span>{index+1}{images[index]?.status==='failed'?' · 未读取':''}</span>}</button>)}</div></>}
  </div><div><h4>{fields.title||'商品标题待补充'}</h4><dl>{[['SKU',fields.sku],['售价',fields.price===''?'待补充':String(fields.price)+' '+fields.currency],['目标类目',fields.category_id],['计划上架数量',fields.quantity??'待补充'],['目标语言',product.language],['履约依据',product.fulfillment]].map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value===''?'待补充':value}</dd></div>)}</dl></div></div>
    {product.ozon?.publication&&<details><summary>包装规格与税率资料</summary><dl>{[['包装深/宽/高',[product.ozon.publication.depth,product.ozon.publication.width,product.ozon.publication.height].map(v=>v??'待补充').join(' × ')+' '+product.ozon.publication.dimension_unit],['含包装重量',String(product.ozon.publication.weight??'待补充')+' '+product.ozon.publication.weight_unit],['适用税率',product.ozon.publication.vat||'待补充'],['包装依据',product.ozon.publication.source_ref],['税率依据',product.ozon.publication.vat_source_ref],['描述属性 ID',product.ozon.publication.description_attribute_id||'待选择']].map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v||'待补充'}</dd></div>)}</dl></details>}
    <details open><summary>产品描述与参数</summary><p className="r-review-product-description">{fields.description||'产品描述待补充'}</p>{product.attributes.length>0&&<dl>{product.attributes.map((a,index)=><div key={index}><dt>{a.name}</dt><dd>{a.value||'待补充'}{a.source_ref&&<small> · {a.source_ref}</small>}</dd></div>)}</dl>}{product.ozon?.attributes.length?<dl>{product.ozon.attributes.map((a,index)=><div key={index}><dt>平台属性 {a.id}</dt><dd>{a.values.map(v=>v.value||('词典值 '+v.dictionary_value_id)).join('、')}</dd></div>)}</dl>:null}</details>
  </section>;
}
