import type {CaseItem} from './types';
import type {ListingTarget} from './listing-observation';

export interface ListingStoreIdentity {kind?:string;label?:string|null;platform?:string;market?:string;store_ref?:string|null;connection_id?:string|null;active?:boolean;identity_verified?:boolean}
export interface ListingImage {id:string;origin:string;source_current?:boolean;asset_id?:string;url?:string;source_kind?:string;role?:string;reference_only?:boolean;case_id?:string;entry_id?:string;entry_sha256?:string;image_index?:number;media_id?:string;sha256?:string;width?:number;height?:number}
export interface ListingCatalog {
  id:string;name:string;kind:'candidate'|'inventory';synthetic:boolean;source_sha256:string;
  sku?:string|null;product_id?:string|null;product_key?:string;primary_case_id?:string;case_ids?:string[];
  platform?:string;market?:string;store_identity?:ListingStoreIdentity;
  case?:{scope?:{platform?:string;market?:string;sku?:string;inventory_type?:string}};
  inventory_scopes?:{case_id:string;inventory_type?:string}[];
  images?:ListingImage[];
  fields?:{key:string;original:unknown;locator?:string;reviewed?:boolean}[];
  price?:number|string|null;currency?:string|null;
}
export interface ListingChoice extends CaseItem {sku?:string|null;store?:ListingStoreIdentity;productKey?:string;aliasOf?:string;scopeLabel?:string}
export interface ListingStoreChoice {platform:string;store_ref:string;market:string;label:string;connection_id?:string|null}

/** The catalog owns grouping. A legacy deep link is retained explicitly, never merged by SKU. */
export function listingChoices(cards:ListingCatalog[],legacy:CaseItem[],demo:boolean,selected:string):ListingChoice[]{
  const visible=cards.filter(c=>c.synthetic===demo),result:ListingChoice[]=visible.map(c=>({
    id:c.primary_case_id||c.id,name:c.name,platform:c.platform||c.case?.scope?.platform,market:c.market||c.case?.scope?.market,
    synthetic:c.synthetic,candidate:c.kind==='candidate',sku:c.sku,store:c.store_identity,productKey:c.product_key,
  }));
  if(selected&&!result.some(c=>c.id===selected)){
    const raw=legacy.find(c=>c.id===selected&&c.synthetic===demo),card=visible.find(c=>c.case_ids?.includes(selected));
    if(raw)result.unshift({...raw,sku:card?.sku,store:card?.store_identity,productKey:card?.product_key,
      aliasOf:card?.primary_case_id||card?.id,scopeLabel:card?.inventory_scopes?.find(s=>s.case_id===selected)?.inventory_type||'原工作项'});
  }
  return result;
}
export function listingChoiceLabel(choice:ListingChoice):string{
  const store=choice.store?.label||(choice.candidate?'未绑定店铺':'店铺待核对');
  if(choice.candidate){const internal=!!choice.sku&&/^CANDIDATE[:_-]/i.test(choice.sku);
    return ['候选',choice.name,!choice.sku||internal?'待建立SKU':'拟用SKU '+choice.sku,store,...(internal?['资料编号 '+choice.sku]:[])].join(' · ');
  }
  return [choice.sku?'SKU '+choice.sku:'SKU待补充',choice.name,store,choice.aliasOf?'原履约范围 '+choice.scopeLabel:'店铺商品'].join(' · ');
}
export function listingStores(cards:ListingCatalog[],demo:boolean):ListingStoreChoice[]{
  const result=new Map<string,ListingStoreChoice>(),ambiguous=new Set<string>();
  for(const card of cards){const s=card.store_identity;if(card.synthetic!==demo||s?.kind!=='store'||s.active!==true||!s.store_ref||!s.platform||!s.market)continue;
    const key=JSON.stringify([s.platform,s.store_ref,s.market]);if(ambiguous.has(key))continue;
    if(result.has(key)&&result.get(key)?.connection_id!==s.connection_id){result.delete(key);ambiguous.add(key);continue;}
    result.set(key,{platform:s.platform,store_ref:s.store_ref,market:s.market,label:s.label||'已连接店铺',connection_id:s.connection_id});
  }
  return [...result.values()];
}
export function sameListingTarget(a:ListingTarget,b:ListingTarget):boolean{return ['case_id','platform','store_ref','market'].every(k=>a[k as keyof ListingTarget]===b[k as keyof ListingTarget]);}
export function originalListingImage(catalog:ListingCatalog){
  const images=catalog.images||[];
  const reference=(kind:string)=>catalog.kind==='candidate'?images.find(i=>i.origin==='product_evidence'&&i.source_kind===kind&&i.role==='original'&&i.reference_only===true&&i.case_id===catalog.id&&!!i.entry_id&&!!i.media_id&&/^[a-f0-9]{64}$/.test(i.entry_sha256||'')&&/^[a-f0-9]{64}$/.test(i.sha256||'')&&Number.isInteger(i.image_index)&&(i.image_index??-1)>=0):undefined;
  const selected=reference('competitor')||reference('supplier')||images.find(i=>i.origin==='product_image'&&i.source_current!==false)||images.find(i=>i.origin==='source_link_unverified');
  return selected?{image:selected,index:images.indexOf(selected)}:null;
}
export function listingImagePresentation(catalog:ListingCatalog|null,image?:ListingImage){
  const candidate=catalog?.kind==='candidate',width=image?.width,height=image?.height;
  const thumbnail=typeof width==='number'&&typeof height==='number'&&Number.isFinite(width)&&Number.isFinite(height)&&width>0&&height>0&&Math.max(width,height)<=75;
  const label=candidate?(image?.source_kind==='competitor'?'竞品参考图':image?.source_kind==='supplier'?'货源参考图':'公开来源参考图'):'原始图库预览';
  return {label,thumbnail,alt:label+(candidate?'，非自有实物':'，颜色变体待核'),hint:candidate?
    label+'仅为外部样例，非自有实物，不可直接作上架主图；品牌、配件、数量和功能不自动成为我方商品事实。'+(thumbnail?'这是 '+image?.width+' × '+image?.height+' 像素缩略图，仅供识别资料，不可作生图依据。':'须另核同款、变体、清晰度与用途。'):
    '左侧为原始图库预览，非已选上架主图；颜色、配件及包装仍需核对。原资料和优化稿可追溯，不代表实物信息已验证。'};
}
export async function checkedListingImage(value:{mime:string;content_base64:string;sha256:string}):Promise<string>{
  if(!/^image\/(png|jpeg|webp)$/.test(value.mime)||!/^[a-f0-9]{64}$/.test(value.sha256)||value.content_base64.length>7*1024*1024)throw Error('listing_original_image_invalid');
  const bytes=Uint8Array.from(atob(value.content_base64),c=>c.charCodeAt(0));
  if(bytes.byteLength>5*1024*1024)throw Error('listing_original_image_too_large');
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
  if(hash!==value.sha256)throw Error('listing_original_image_hash_mismatch');
  return `data:${value.mime};base64,${value.content_base64}`;
}
export function sourceField(catalog:ListingCatalog|null,key:string):unknown{
  if(!catalog)return null;
  if(key==='sku')return catalog.sku??catalog.case?.scope?.sku??null;
  if(key==='price')return catalog.price??null;if(key==='currency')return catalog.currency??null;
  const field=catalog.fields?.find(f=>f.key===key);if(field)return field.original;
  if(key==='description'){
    const attributes=catalog.fields?.find(f=>f.key==='attributes')?.original;
    try{const rows=typeof attributes==='string'?JSON.parse(attributes):attributes;
      const match=Array.isArray(rows)?rows.filter(r=>(r?.id==='4191'||r?.id===4191)&&[undefined,0,'0'].includes(r.complex_id)):[];
      if(match.length===1&&Array.isArray(match[0].values)&&match[0].values.length===1)return match[0].values[0].value;
    }catch{/* Keep unavailable source explicit. */}
  }
  return null;
}
