/* Read-only product labels; object identity always remains the exact case id. */
(() => {
  'use strict';
  const text=value=>typeof value==='string'?value.trim():'';
  const platforms={ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu',shopify:'Shopify',woocommerce:'WooCommerce'};
  function scope(item={}) {
    const value={...(item.scope||{}),...(item.case?.scope||{})};
    for(const key of ['platform','market','sku','fulfillment','inventory_type'])if(text(item[key])||Array.isArray(item[key]))value[key]=item[key];
    return value;
  }
  const id=item=>text(item.id||item.case?.id);
  // Research candidates keep an internal CANDIDATE key in scope.sku; it is a record number, not a store SKU.
  const internalSku=value=>/^CANDIDATE[:_-]/i.test(text(value));
  const skuText=value=>!text(value)?'':internalSku(value)?'待建立 SKU · 资料编号 '+text(value):'SKU · '+text(value);
  function shortId(item,peers=[]) {
    const value=id(item),plain=value.replace(/^(?:case|candidate|product|item)[_-]/,'');
    if(!value)return '';
    for(let size=8;size<plain.length;size+=4){const suffix=plain.slice(-size);if(!peers.some(other=>id(other)!==value&&id(other).endsWith(suffix)))return suffix;}
    return plain;
  }
  function meta(item) {
    const s=scope(item),inventory=text(s.inventory_type),fulfillment=['fbs','rfbs','fbo'].includes(inventory.toLowerCase())?inventory:Array.isArray(s.fulfillment)?s.fulfillment.map(text).filter(Boolean).join(' / '):text(s.fulfillment);
    return [platforms[s.platform]||text(s.platform)||'平台待核对',text(s.market)||'市场待核对',fulfillment?fulfillment.toUpperCase():'履约未提供'].join(' · ');
  }
  function label(item,peers=[]) {
    const s=scope(item),sku=text(s.sku),name=text(item.name)||text(s.label)||sku||'未命名商品';
    const shown=internalSku(sku)?'':sku,primary=name+(shown&&shown!==name?' / '+shown:'');
    const same=peers.some(other=>id(other)!==id(item)&&(text(other.name)||text(scope(other).label)||text(scope(other).sku)||'未命名商品')===name&&text(scope(other).sku)===sku&&meta(other)===meta(item));
    const candidate=item.candidate===true||item.kind==='candidate'||s.inventory_type==='candidate'||s.origin==='research_candidate_not_inventory';
    return [primary,meta(item),candidate?'调研候选':'',!shown||same?shortId(item,peers):''].filter(Boolean).join(' · ');
  }
  function merge(items,records) {
    const exact=new Map(records.map(record=>[id(record),record]));
    return items.map(item=>{const found=exact.get(id(item));return found?{...item,scope:{...scope(found),...scope(item)}}:item;});
  }
  window.CommerceProductIdentity={scope,meta,label,merge,internalSku,skuText};
})();
