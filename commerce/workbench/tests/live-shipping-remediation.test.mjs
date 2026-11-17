import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
const root=resolve(import.meta.dirname,'../..'),sourceRoot=process.env.UI_REMEDIATION_SOURCE_ROOT||root;
const kit=await readFile(resolve(root,'ui/kit.js'),'utf8');
const [liveSource,planSource,shippingSource]=await Promise.all(['web/live-ui.js','web/live-plan-ui.js','web/shipping-ui.js'].map(path=>readFile(resolve(sourceRoot,path),'utf8')));
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve()};
function surface(){
 const listeners={},nodes={},body={};
 const document={body,activeElement:body,documentElement:{dataset:{},getAttribute(){return 'light'},setAttribute(){}},querySelector:selector=>nodes[selector]||null,querySelectorAll:()=>[],addEventListener(name,fn){(listeners[name]||=[]).push(fn)}};
 const window={dispatchEvent(){},addEventListener(){},matchMedia:()=>({matches:false,addEventListener(){}})};
 const timers=new Map();let timerId=1;
 const context=vm.createContext({window,document,crypto:globalThis.crypto,Intl,Date,URL,Blob,structuredClone,queueMicrotask,CustomEvent:class{constructor(type,args){this.type=type;this.detail=args?.detail}},setInterval(){},setTimeout(fn){const id=timerId++;timers.set(id,fn);return id},clearTimeout:id=>timers.delete(id)});
 vm.runInContext(kit,context);
 const input=(dataset,value)=>{for(const fn of listeners.input||[])fn({target:{dataset,value,type:'text',closest:()=>true}})};
 const click=async(dataset)=>{const target={dataset,disabled:false,closest:()=>target};for(const fn of listeners.click||[])await fn({target:{closest:selector=>selector==='[data-shipping-open]'?null:target},stopImmediatePropagation(){},preventDefault(){}});await flush()};
 return {window,document,nodes,context,listeners,timers,input,click};
}
const stock=()=>({key:'stock-a',offer_id:'合成SKU',product_id:7,type:'FBO',present:8,reserved:3,available:5,scope:'履约方式汇总，非单仓',observed_at:'2026-11-17T01:02:03Z',fresh:true,source_sha256:'stock-sha'});
const readiness=()=>({complete:2,total:3,notice:'桌面经营核验；通知后置',checks:[{label:'库存口径',status:'needs_action',detail:'待核对',action:'setup'}],deliveries:[]});
function liveApi(name){
 if(name==='commerce_live_readiness')return readiness();
 if(name==='commerce_live_restock_list')return {candidates:[stock()],plans:[]};
 if(name==='commerce_live_alerts')return {alerts:[]};
 if(name==='commerce_live_status')return {configured:false,store_label:'合成店铺',fulfillment_modes:['FBO'],lookback_days:30,orders_scope_confirmed:false,stock_basis:'unconfirmed',orders:{count:3,available:true,fresh:true},stock:{count:30,available:true,fresh:false},last_job:{status:'partial',finished:'2026-11-17T01:02:03Z',result:{orders:{status:'success',count:3},stock:{status:'success',count:30},sales:{status:'success',count:39}}}};
 throw Error(name);
}
async function live(){const f=surface();vm.runInContext(planSource,f.context);vm.runInContext(liveSource,f.context);const view=f.window.CommerceLive({api:async name=>liveApi(name),repaint(){},isActive:()=>true,toast(){}});await view.load();return {...f,view};}
test('real alerts contain one refresh action in their content header without an empty source card',async()=>{
 const f=await live(),html=f.view.alertsView();assert.equal((html.match(/data-live-action="refresh"/g)||[]).length,1);
 assert.doesNotMatch(html,/Ozon 来源状态/);assert.match(html,/<div class="live-alert-heading"><h2>真实订单与库存提醒<\/h2>/);
});
test('snapshot sync distinguishes stock from sales with readable local time and preserves raw receipts in details',async()=>{
 const f=await live(),html=f.view.render(),main=html.split('<section class="live-planning-workspace">')[0].replace(/<details[\s\S]*?<\/details>/g,'');
 assert.match(main,/库存产品 · 履约方式汇总，非单仓/);assert.match(main,/销售分析 · 最近 30 天，与发货单不同口径/);
 assert.match(main,/<td>30<\/td>/);assert.match(main,/<td>39<\/td>/);assert.match(main,/部分同步完成/);assert.match(main,/09:02:03/);
 assert.doesNotMatch(main,/2026-11-17T01:02:03Z|>success</);assert.match(html,/原始同步回执与快照标识/);assert.match(html,/2026-11-17T01:02:03Z/);assert.match(main,/已过期/);
});
async function plans({stale=false}={}){
 const f=surface(),calls=[];let fail=true;vm.runInContext(planSource,f.context);
 const api=async(name,args)=>{calls.push({name,args});if(name==='commerce_live_restock_save'){if(fail){fail=false;throw Error('synthetic_timeout')}return {}};if(name==='commerce_live_restock_list')return {candidates:[{...stock(),...(stale?{fresh:false,available:null}:{})}],plans:[]};return liveApi(name)};
 const view=f.window.CommerceLivePlans({api,repaint(){},toast(){}});await view.load();view.select('stock-a');return {...f,view,calls};
}
test('platform restock uses the shared three-source navigation and keeps snapshot evidence out of primary text',async()=>{
 const f=await plans({stale:true}),html=f.view.render(),main=html.replace(/<details[\s\S]*?<\/details>/g,'');
 assert.match(html,/aria-label="补货资料来源"/);assert.match(html,/data-restock-source="manual"/);assert.match(html,/data-analysis-mode="stock"/);assert.match(html,/data-tab="live" aria-current="page"/);
 assert.match(main,/可售库存 <strong>未知<\/strong>/);assert.match(main,/已过期，需重新同步/);assert.doesNotMatch(main,/stock-sha|present：|2026-11-17T01:02:03Z/);assert.match(html,/stock-sha/);
 assert.equal((html.match(/data-live-plan-field=/g)||[]).length,9);
});
test('restock form grouping preserves explicit zero inbound, source hash and retry identity',async()=>{
 const f=await plans();for(const [key,value]of Object.entries({sold_units:'10',window_days:'5',lead_time_days:'7',safety_days:'3',pack_size:'4',inbound_units:'0',source_ref:'synthetic:row',demand_observed_at:'2026-11-17T09:00:00+08:00'}))f.input({livePlanField:key},value);
 const submit=()=>{for(const fn of f.listeners.submit||[])fn({target:{id:'live-restock-form'},preventDefault(){}})};
 submit();await flush();submit();await flush();const writes=f.calls.filter(x=>x.name==='commerce_live_restock_save');assert.equal(writes.length,2);assert.equal(writes[0].args.idempotency_key,writes[1].args.idempotency_key);assert.equal(writes[1].args.source_sha256,'stock-sha');assert.equal(writes[1].args.input.inbound_units,0);assert.ok(!('inbound_due_at'in writes[1].args.input));assert.equal(writes[1].args.input.demand_observed_at,'2026-11-17T09:00:00+08:00');
});
test('restock IME confirmation never saves while ordinary Enter still submits once',async()=>{
 const f=await plans();f.input({livePlanField:'source_ref'},'合成来源');
 for(const native of [{isComposing:true,keyCode:13},{isComposing:false,keyCode:229}]){
  for(const handler of f.listeners.keydown||[])handler({key:'Enter',...native,target:{form:{id:'live-restock-form'}},preventDefault(){}});
  await flush();assert.equal(f.calls.filter(call=>call.name==='commerce_live_restock_save').length,0);
 }
 for(const handler of f.listeners.keydown||[])handler({key:'Enter',isComposing:false,keyCode:13,target:{form:{id:'live-restock-form'}},preventDefault(){}});
 await flush();assert.equal(f.calls.filter(call=>call.name==='commerce_live_restock_save').length,1);
});
const model=id=>({id,model_id:id,name:id,kind:'container',inner_cm:[500,200,200],outer_cm:[510,210,210],tare_kg:1,max_weight_kg:100,packaging_cost:'',door_cm:[190,190]});
function result(input){return {id:'saved',created_at:'2026-11-17T01:02:03Z',sha256:'plan-sha',input_sha256:'input-sha',input,input_units:20,synthetic:true,mode:'warehouse',variants:{space:{groups:[],complete:true,box_count:0,total_outer_volume_cm3:0,gross_weight_kg:0,shipping_cost:null,packaging_cost:null,total_cost:null,currency:'CNY'},cost:null},comparisons:[],notice:'合成方案'};}
async function shipping(){
 const f=surface(),calls=[];vm.runInContext(shippingSource,f.context);let app,html='';
 const node=(selector)=>({focus(){f.document.activeElement=this},scrollIntoView(){this.scrolled=true}});
 function repaint(){html=app.view();for(const id of ['shipping-input','shipping-input-title','shipping-comparison-title','shipping-plan-detail'])f.nodes['#'+id]=node('#'+id);f.nodes['#shipping-input'].open=/<details id="shipping-input"[^>]*\sopen(?:\s|>)/.test(html);f.nodes['#shipping-result']={set innerHTML(value){html=app.view()}};for(const a of ['calculate','stage-detail']){const tag=(html.match(/<button\b[^>]*>/g)||[]).find(x=>x.includes(`data-shipping-action="${a}"`));f.nodes[`[data-shipping-action="${a}"]`]={dataset:{shippingAction:a},disabled:/\sdisabled(?:\s|>)/.test(tag||'')};}}
 const api=async(name,args)=>{calls.push({name,args});if(name==='commerce_shipping_state')return {rate_books:[],plans:[],model_catalog:{models:['20gp','40gp','40hq'].map(x=>model('container-'+x))}};if(name==='commerce_shipping_plan_create')return result(args.input);if(name==='commerce_shipping_compare')return {models:['20gp','40gp','40hq'].map(x=>({model_id:'container-'+x,status:'ready',plan:result(args.input),summary:{box_count:0,placed_units:20,unplaced_units:0,complete:true}}))};throw Error(name)};
 app=f.window.CommerceShipping({api,ui:f.window.CommerceUI,esc:f.window.CommerceUI.escape,repaint,isActive:()=>true});await app.open();
 return {...f,app,calls,get html(){return html},runTimers:async()=>{const timers=[...f.timers.values()];f.timers.clear();for(const fn of timers)await fn();await flush()}};
}
test('shipping groups input, comparison and detail with CSV and advanced tools disclosed on demand',async()=>{
 const f=await shipping(),html=f.html;assert.match(html,/aria-label="装箱流程"/);assert.match(html,/<details id="shipping-input"[^>]*\sopen/);assert.match(html,/<details class="shipping-import-tools"><summary>商品 CSV 与模板/);assert.match(html,/<details class="shipping-advanced"><summary>/);
 for(const action of ['pick-file','template','calculate','add-item','add-model'])assert.match(html,new RegExp(`data-shipping-action="${action}"`));
});
test('shipping calculation folds inputs, retains values and allows focus navigation without another calculation',async()=>{
 const f=await shipping();await f.click({shippingAction:'example'});f.document.activeElement=f.nodes['[data-shipping-action="calculate"]'];await f.click({shippingAction:'calculate'});
 assert.equal(f.nodes['#shipping-input'].open,false);assert.match(f.html,/id="shipping-plan-detail"/);assert.equal(f.nodes['[data-shipping-action="stage-detail"]'].disabled,false);
 const before=f.calls.length;await f.click({shippingAction:'stage-input'});assert.equal(f.nodes['#shipping-input'].open,true);assert.equal(f.document.activeElement,f.nodes['#shipping-input-title']);assert.match(f.app.view(),/value="DEMO-A"/);
 await f.click({shippingAction:'stage-detail'});assert.equal(f.nodes['#shipping-input'].open,false);assert.equal(f.document.activeElement,f.nodes['#shipping-plan-detail']);assert.equal(f.calls.length,before);
});
test('read-only model comparison enables detail navigation after a partial result update',async()=>{
 const f=await shipping();await f.click({shippingAction:'example'});await f.click({shippingAction:'enable-comparison'});await f.runTimers();
 assert.equal(f.nodes['[data-shipping-action="stage-detail"]'].disabled,false);assert.equal(f.calls.filter(x=>x.name==='commerce_shipping_plan_create').length,0);
});
