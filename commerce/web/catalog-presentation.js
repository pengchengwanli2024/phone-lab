/* Readable projections only: original platform documents remain unchanged. */
window.CommerceCatalogPresentation=(()=>{
  const e=value=>window.CommerceUI.escape(String(value??''));
  function plain(value){
    const entities={nbsp:' ',amp:'&',lt:'<',gt:'>',quot:'"',apos:"'"};
    return String(value??'').replace(/&(#x[0-9a-f]+|#\d+|nbsp|amp|lt|gt|quot|apos);/gi,(_,key)=>{
      if(key[0]!=='#')return entities[key.toLowerCase()]||_;
      const n=key[1]?.toLowerCase()==='x'?parseInt(key.slice(2),16):Number(key.slice(1));
      return Number.isInteger(n)&&n>0&&n<=0x10ffff&&!(n>=0xd800&&n<=0xdfff)?String.fromCodePoint(n):_;
    }).replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi,'').replace(/<(?:br\s*\/?|\/?p|\/?div|\/?li|\/?h[1-6])\b[^>]*>/gi,'\n').replace(/<[^>]*>/g,'').replace(/\r/g,'').replace(/[ \t]+/g,' ').replace(/\n\s*\n\s*\n/g,'\n\n').trim();
  }
  function readable(value,key){
    let data;try{data=typeof value==='string'?JSON.parse(value):value;}catch{return null;}
    if(key==='attributes'&&Array.isArray(data))return data.slice(0,100).map(row=>{
      if(!row||typeof row!=='object'||!Array.isArray(row.values))return null;
      const label=plain(row.name||row.label||('平台属性 '+String(row.id??'未知')));
      const values=row.values.slice(0,100).map(v=>typeof v?.value==='string'?plain(v.value):'').filter(Boolean);
      return values.length?{label,value:values.join('、')}:null;
    }).filter(Boolean);
    if(data&&typeof data==='object'&&!Array.isArray(data)){
      const labels={depth:'长 / 深',length:'长度',width:'宽度',height:'高度',dimension_unit:'尺寸单位',weight:'重量',weight_unit:'重量单位',status_name:'商品状态',status_description:'状态说明',moderate_status:'平台审核状态',validation_status:'平台校验状态'};
      return Object.entries(data).slice(0,40).map(([name,v])=>({label:labels[name]||name,value:plain(v&&typeof v==='object'?JSON.stringify(v):v)}));
    }
    return null;
  }
  function textBlock(value){const text=plain(value);if(!text)return '<span class="muted">未提供</span>';return text.length<=600?`<p class="catalog-readable-text">${e(text)}</p>`:`<p class="catalog-readable-text">${e(text.slice(0,600))}…</p><details><summary>展开完整内容</summary><p class="catalog-readable-text">${e(text)}</p></details>`;}
  function field(field){
    const rows=readable(field.original,field.key);
    const body=rows?.length?`<dl class="catalog-readable-pairs">${rows.slice(0,5).map(r=>`<div><dt>${e(r.label)}</dt><dd>${textBlock(r.value)}</dd></div>`).join('')}</dl>${rows.length>5?`<details><summary>其余 ${rows.length-5} 项属性</summary><dl class="catalog-readable-pairs">${rows.slice(5).map(r=>`<div><dt>${e(r.label)}</dt><dd>${textBlock(r.value)}</dd></div>`).join('')}</dl></details>`:''}`:textBlock(field.original);
    return `${body}<details class="catalog-original"><summary>查看原始字段</summary><pre>${e(typeof field.original==='string'?field.original:JSON.stringify(field.original,null,2))}</pre></details>`;
  }
  const storeLabel=item=>item?.store_identity?.label||(item?.store_identity?.kind==='research_candidate'||item?.kind==='candidate'?'调研候选 · 尚未绑定店铺':'店铺身份待核对');
  function scopes(item){return [...new Set((item?.inventory_scopes||[]).map(r=>r.inventory_type).filter(Boolean))].map(v=>({fbs:'FBS',rfbs:'realFBS',fbo:'FBO'})[v]||v).join(' / ');}
  return {plain,readable,field,textBlock,storeLabel,scopes};
})();
