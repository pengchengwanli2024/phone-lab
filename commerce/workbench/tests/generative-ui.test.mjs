import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function runtime(){const window={dispatchEvent(){},matchMedia:()=>({addEventListener(){}})};const context=vm.createContext({window,console,CustomEvent:class{},document:{documentElement:{dataset:{}}}});vm.runInContext(fs.readFileSync(new URL('../../ui/kit.js',import.meta.url),'utf8'),context);vm.runInContext(fs.readFileSync(new URL('../../web/generative-ui.js',import.meta.url),'utf8'),context);return window;}
test('renderer implements every catalog entry and no additional component',()=>{
  const catalog=JSON.parse(fs.readFileSync(new URL('../../generative/catalog.json',import.meta.url),'utf8'));
  assert.deepEqual([...runtime().CommerceGenerativeUI.components].sort(),Object.keys(catalog.components).sort());
});
test('business cards escape values, keep stable identities and distinguish missing prices',()=>{
  const w=runtime(),surface={schema:'commerce-generative-surface-v1',catalog_version:1,components:[{id:'quote-one',component:'QuoteComparison',label:'供应报价',binding:{reference:'R1'},data:{items:[{quote_id:'q1',supplier:'<img onerror=alert(1)>',currency:'CNY',unit_price:null,goods_subtotal:'0',status:'HOLD'}]}}]};
  const html=w.CommerceGenerativeUI.render(surface,{ui:w.CommerceUI}).html;
  assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img onerror/);assert.match(html,/待补充/);assert.match(html,/data-field-id="supply_quote:q1:unit_price"/);
});
test('unrecognized catalog falls back and previews never expose image or review actions',()=>{
  const w=runtime();assert.equal(w.CommerceGenerativeUI.render({schema:'unknown',components:[]},{ui:w.CommerceUI}),null);
  const result=w.CommerceGenerativeUI.render({schema:'commerce-generative-surface-v1',catalog_version:1,provisional:true,components:[{id:'listing',component:'ListingReview',label:'上架',binding:{},data:{product:{image_count:1,title:'test'},image_binding:{count:1,target:{},expected_binding_sha256:'a'.repeat(64)}}}]},{ui:w.CommerceUI});
  assert.doesNotMatch(result.html,/data-generative-image=/);
});
test('cost summary presents business amounts and rates without internal runtime fields',()=>{
  const w=runtime(),html=w.CommerceGenerativeUI.render({schema:'commerce-generative-surface-v1',catalog_version:1,components:[{id:'cost',component:'CostSummary',label:'测算',data:{calculation:{status:'CALCULATED',contribution:38,contribution_rate:.38,total_cost:62,price:100,currency:'CNY',data_source:'caller_input',marketplace_writes:false,model:'explicit_unit_contribution'}}}]},{ui:w.CommerceUI}).html;
  assert.match(html,/38%/);assert.doesNotMatch(html,/caller_input|marketplace_writes|explicit_unit_contribution/);
});
test('skill conditions retain external prerequisites and distinguish runtime from authorization',()=>{
  const w=runtime(),html=w.CommerceGenerativeUI.render({schema:'commerce-generative-surface-v1',catalog_version:1,components:[{id:'skill',component:'SkillReadiness',label:'技能条件',data:{state:'needs_inputs',source_intact:true,missing_fields:['facts_with_source'],external_prerequisites:['需要店铺授权与目标站点权限'],model_draft:{runtime_status:'not_checked'},offline_check:{can_request:false},external_execution:{authorized:false}}}]},{ui:w.CommerceUI}).html;
  assert.match(html,/需要店铺授权与目标站点权限/);assert.match(html,/带来源的产品事实/);assert.match(html,/未核对/);assert.match(html,/未授权/);
});
test('delivery status and missing checks use business labels and preserve the source state',()=>{
  const w=runtime(),data={delivery_review:{status:'stale',professional_gate:'BLOCKED',pending_checks:['facts','translation','media_rights','platform_rules']}};
  const html=w.CommerceGenerativeUI.render({schema:'commerce-generative-surface-v1',catalog_version:1,components:[{id:'delivery',component:'DeliveryReview',label:'交付',data}]},{ui:w.CommerceUI}).html;
  assert.match(html,/来源已变化/);assert.match(html,/产品事实/);assert.match(html,/素材使用权/);assert.doesNotMatch(html,/>stale<|>media_rights</);assert.equal(data.delivery_review.status,'stale');
});
test('quote card exposes MOQ-rounded order quantity and partial coverage',()=>{
  const w=runtime(),items=Array.from({length:21},(_,i)=>({quote_id:'q'+i,currency:'CNY',moq:20,order_units:20,extra_units:10,unit_price:'30',goods_subtotal:'600',status:'READY_FOR_SELECTION'}));
  const html=w.CommerceGenerativeUI.render({schema:'commerce-generative-surface-v1',catalog_version:1,components:[{id:'quotes',component:'QuoteComparison',label:'报价',data:{quantity:10,items}}]},{ui:w.CommerceUI}).html;
  assert.match(html,/下单件数/);assert.match(html,/20（多10件）/);assert.match(html,/报价已限量/);
});
test('a loaded listing image survives repaint and is isolated by saved-version binding',async()=>{
  const w=runtime(),target={case_id:'case-a',platform:'ozon',store_ref:'store-a',market:'RU'},binding='a'.repeat(64);
  const feedback={textContent:'',replaceChildren(){}},button={disabled:false,dataset:{generativeImage:JSON.stringify({...target,expected_binding_sha256:binding,index:0})},parentElement:{querySelector:()=>feedback},ownerDocument:{createElement:()=>({style:{}})}};
  await w.CommerceGenerativeUI.image({target:{closest:()=>button}},async()=>({mime:'image/png',content_base64:'AQ=='}));
  const surface={schema:'commerce-generative-surface-v1',catalog_version:1,components:[{id:'listing',component:'ListingReview',label:'上架',data:{product:{},image_binding:{target,expected_binding_sha256:binding,count:1}}}]};
  assert.match(w.CommerceGenerativeUI.render(surface,{ui:w.CommerceUI}).html,/src="data:image\/png;base64,AQ=="/);
  surface.components[0].data.image_binding.expected_binding_sha256='b'.repeat(64);
  assert.doesNotMatch(w.CommerceGenerativeUI.render(surface,{ui:w.CommerceUI}).html,/src="data:image/);
});
