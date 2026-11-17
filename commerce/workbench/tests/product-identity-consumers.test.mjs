import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { randomUUID } from 'node:crypto';
const read=name=>fs.readFileSync(new URL('../../web/'+name,import.meta.url),'utf8');
const tick=()=>new Promise(setImmediate);
function runtime() {
  const events={};const ui={escape:value=>String(value??''),button:({label,attrs={}})=>`<button ${Object.entries(attrs).map(([key,value])=>`${key}="${value}"`).join(' ')}>${label}</button>`,field:(name,html)=>name+html,input:()=>'',select:({options})=>options.map(option=>`<option value="${option.value}">${option.label}</option>`).join(''),badge:String,alert:String,empty:String,table:(headers,rows)=>rows.join(''),card:({title,content})=>title+content};
  const context=vm.createContext({window:{CommerceUI:ui},document:{addEventListener:(name,fn)=>(events[name]||=[]).push(fn),querySelector:()=>null},crypto:{randomUUID},queueMicrotask,Map,Set,setTimeout,clearTimeout,setInterval(){}});
  vm.runInContext(read('product-identity.js')+read('catalog-ui.js')+read('exposure-ui.js'),context);return {events,window:context.window,context};
}
const products=['one','two'].map(id=>({id,name:'同名商品',platform:'ozon',market:'RU',images:[],kind:'inventory',source_sha256:id,supplier_count:0}));
test('catalog optional scope read does not block browsing, and labels keep both fulfillment records',async()=>{
  const r=runtime();let scopeReply;const calls=[];
  const catalog=r.window.CommerceCatalog({repaint(){},api:async(tool,args)=>{calls.push({tool,args});if(tool==='commerce_catalog_list')return {items:products};if(tool==='commerce_catalog_store_status')return {};if(tool==='commerce_agent_cases')return new Promise(resolve=>scopeReply=resolve);throw Error('Unexpected '+tool);}});
  await catalog.enter();assert.match(catalog.view(),/同名商品/);assert.equal(calls.filter(call=>call.tool==='commerce_catalog_list').length,1);
  scopeReply({cases:products.map((item,i)=>({id:item.id,scope:{sku:'SAME-SKU',inventory_type:i?'rfbs':'fbs',fulfillment:['fbs','rfbs']}}))});await tick();
  const html=catalog.view();assert.match(html,/FBS/);assert.match(html,/RFBS/);assert.equal((html.match(/<article /g)||[]).length,2);assert.match(html,/catalog-picture is-empty/);
});
test('failed optional metadata leaves the catalog readable and does not claim a fulfillment mode',async()=>{
  const r=runtime(),catalog=r.window.CommerceCatalog({repaint(){},api:async tool=>tool==='commerce_catalog_list'?{items:products}:tool==='commerce_agent_cases'?Promise.reject(Error('offline')):{}});
  await catalog.enter();await tick();const html=catalog.view();assert.match(html,/履约未提供/);assert.doesNotMatch(html,/商品资料暂不可读/);assert.equal((html.match(/<article /g)||[]).length,2);
});
test('exposure candidate names are joined by case id and selection keeps the exact case',async()=>{
  const r=runtime(),calls=[];
  const exposure=r.window.CommerceExposure({esc:String,repaint(){},isActive:()=>true,api:async(tool,args)=>{calls.push({tool,args});if(tool==='commerce_agent_cases')return {cases:products.map(item=>({id:item.id,scope:{platform:'ozon',market:'RU',inventory_type:'candidate'}}))};if(tool==='commerce_workspace_list')return {items:products};if(tool==='commerce_intel_search')return {items:[]};if(tool==='commerce_exposure_targets')return {targets:[]};if(tool==='commerce_exposure_history')return {assessments:[]};throw Error('Unexpected '+tool);}});
  await exposure.enter();await tick();const html=exposure.view();
  assert.match(html,/<option value="one">同名商品/);assert.match(html,/<option value="two">同名商品/);assert.match(html,/调研候选/);
  await r.events.change[0]({target:{id:'exposure-case',value:'two'}});
  assert.equal(calls.find(call=>call.tool==='commerce_exposure_targets').args.case_id,'two');
});
