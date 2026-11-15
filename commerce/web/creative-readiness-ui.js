/* Preparation diagnostics share the server's current contract, not generation permission. */
window.CommerceCreativeReadinessView=(data,kind,busy=false)=>{
 const ui=window.CommerceUI,e=ui.escape,button=(label,action,attrs={})=>ui.button({label,attrs:{id:action==='refresh'?'media-readiness-refresh':undefined,'data-media-action':action,disabled:busy,...attrs}});
 if(!data)return `<section class="media-readiness" aria-label="制作准备检查">${ui.alert('制作准备状态尚未读取，请重新检查当前资料。','warning')}${button('检查准备情况','refresh')}</section>`;
 const checks=data.checks||[],byKey=Object.fromEntries(checks.map(c=>[c.key,c])),canCreate=data.formats[kind]?.can_create_request;
 const needs=checks.filter(c=>c.status!=='ready'&&(c.stage==='planning'||c.key==='product_image'||c.key==='reference_media'&&(byKey.design_direction?.status!=='ready'||c.status!=='missing')));
 const labels={product_name:'补充商品名称',product_facts:'补充卖点及资料依据',product_image:'导入或核对产品原图',reference_media:'导入或核对参考素材',design_direction:'核对并保存设计方向',product_source:'核对当前商品来源'};
 const status={missing:'尚未提供',stale:'依据已有变化',unavailable:'登记文件不可读取或已变化',unchecked:'部分文件尚未检查'};
 return `<section class="media-readiness" aria-label="制作准备检查"><div class="media-readiness-heading"><strong>制作准备检查</strong>${button('重新检查','refresh')}</div><p>${canCreate?'当前商品依据与设计方向可以建立制作清单。':'先核对商品依据、参考素材与设计方向。产品原图可在建立清单后导入。'}${!data.plugin_inputs_ready&&canCreate?'插件制作还需有效产品原图。':''}</p>${needs.length?`<ul>${needs.map(c=>`<li><div><strong>${e(c.label)}</strong> · ${e(status[c.status]||'待核对')}${c.unchecked_count?`<small>本次检查 ${c.checked_count} 项，另有 ${c.unchecked_count} 项未检查。</small>`:''}</div>${button(labels[c.key]||'补齐资料','preparation',{'data-preparation-key':c.key,id:'media-preparation-'+c.key})}</li>`).join('')}</ul>`:''}</section>`;
};
