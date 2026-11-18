import type {StoreScopeCatalog} from './store-scopes';

const platforms:Record<string,string>={ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu',shopify:'Shopify',woocommerce:'WooCommerce'};
export const platformName=(value?:string|null)=>platforms[value||'']||value||'平台待核对';

/** Research candidates carry an internal CANDIDATE key in the sku field; it is a record number, not a store SKU. */
export const internalSku=(value?:string|null)=>/^CANDIDATE[:_-]/i.test((value||'').trim());
export function skuText(value?:string|null):string {
  const sku=(value||'').trim();
  return !sku?'':internalSku(sku)?'待建立 SKU · 资料编号 '+sku:'SKU '+sku;
}

type StoreTarget={platform?:string;store_ref?:string|null;market?:string};
/**
 * Display only. The readable name comes from the store view the reference already belongs to;
 * the exact reference stays visible, and an unread or ambiguous catalog falls back to it alone.
 */
export function storeName(target:StoreTarget,catalog?:StoreScopeCatalog|null):string {
  const reference=(target.store_ref||'').trim();
  if(!reference)return '店铺待核对';
  if(!catalog)return reference;
  const same=(item:{platform:string;market:string})=>item.platform===target.platform&&item.market===target.market;
  const named=(label?:string)=>label&&label!==reference?`${label}（${reference}）`:reference;
  const saved=catalog.sources.filter(item=>item.kind==='listing'&&same(item)&&item.label===reference);
  if(saved.length===1){
    const store=catalog.stores.find(item=>item.id===catalog.mapping[saved[0].id]);
    if(store&&store.label!==reference)return named(store.label);
  }
  // 'ozon-live' is the fixed reference of the single connected Ozon store.
  const live=catalog.sources.filter(item=>item.kind==='live'&&same(item));
  if(reference==='ozon-live'&&target.platform==='ozon'&&live.length===1)return named(live[0].label);
  return reference;
}
/** Alerts already carry the store view they were projected into. */
export function scopeName(storeId:string|undefined,scope:string|null|undefined,catalog?:StoreScopeCatalog|null):string {
  const label=scope?catalog?.stores.find(item=>item.id===scope)?.label:'';
  return !storeId?label||'':label&&label!==storeId?`${label}（${storeId}）`:storeId;
}
