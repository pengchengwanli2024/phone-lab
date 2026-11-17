import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const root=new URL('../../',import.meta.url);
const flush=async()=>{for(let i=0;i<16;i++)await Promise.resolve();};
function deferred(){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
async function harness(file){
  const listeners={},toasts=[];
  const ui={escape:v=>String(v??''),button:o=>`<button>${o.label}</button>`,field:(label,content)=>label+content,select:o=>`<select id="${o.id}">${o.value}</select>`,input:()=>'',legacyAttributes:()=>({}),badge:v=>String(v),alert:v=>String(v),empty:v=>String(v),table:(_,rows)=>rows.join('')};
  const document={addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn),querySelector:()=>null,activeElement:null};
  const context={window:{CommerceUI:ui},document,setInterval:()=>0,setTimeout:()=>0,crypto:globalThis.crypto,URL,Blob,Date};
  vm.runInNewContext(await readFile(new URL(file,root),'utf8'),context,{filename:file});
  return {window:context.window,toasts,toast:value=>toasts.push(value),emit:async(type,target)=>{for(const fn of listeners[type]??[])await fn({target,stopImmediatePropagation(){},preventDefault(){}});}};
}
const stores=['A','B'].map(store_id=>({store_id,label:'Store '+store_id,market:'US',platform:'amazon',configured:true,enabled:true,scope_reviewed:true,missing_fields:[],resources:['orders','stock'],last_job:null}));
const snapshot=tag=>({available:true,fresh:true,document:{observed_at:1,records:[{entity_id:tag+'-record',quantity:null,quantity_basis:'not_available',amount:null}],notice:'probe'}});
async function platforms(fetchSnapshot){
  const h=await harness('web/platform-ui.js');let screen='',app;
  const api=async(name,args)=>{if(name==='commerce_platform_catalog')return {};if(name==='commerce_platform_list')return {stores};if(name==='commerce_platform_snapshot')return fetchSnapshot(args);throw Error(name);};
  app=h.window.CommercePlatforms({api,esc:String,toast:h.toast,repaint:()=>screen=app.view(),modal(){},closeModal(){},isActive:()=>true,onConnections(){}});await app.enter();
  return {...h,app,get screen(){return screen;}};
}
test('platform scope clears old snapshot immediately and displays a scoped read failure in place',async()=>{
  const pending=deferred(),h=await platforms(args=>args.store_id==='A'?snapshot('A'):pending.promise);
  await h.emit('change',{id:'platform-store',value:'A'});await flush();assert.match(h.screen,/A-record/);
  await h.emit('change',{id:'platform-store',value:'B'});assert.doesNotMatch(h.screen,/A-record/);assert.match(h.screen,/正在读取所选店铺与资源/);
  pending.reject(Error('platform_http_failed'));await flush();assert.doesNotMatch(h.screen,/A-record/);assert.match(h.screen,/所选店铺与资源的快照未能读取/);assert.match(h.screen,/刷新状态重试/);assert.equal(h.toasts.length,0);
});
test('late failures from an old store cannot overwrite the newer store snapshot or error state',async()=>{
  const pending=deferred(),h=await platforms(args=>args.store_id==='A'?pending.promise:snapshot('B'));
  await h.emit('change',{id:'platform-store',value:'A'});await h.emit('change',{id:'platform-store',value:'B'});await flush();assert.match(h.screen,/B-record/);
  pending.reject(Error('platform_http_failed'));await flush();assert.match(h.screen,/B-record/);assert.doesNotMatch(h.screen,/快照未能读取|正在读取所选/);assert.equal(h.toasts.length,0);
});
test('resource changes also clear the previous resource and keep failures out of its old table',async()=>{
  const pending=deferred(),h=await platforms(args=>args.resource==='orders'?snapshot('orders'):pending.promise);
  await h.emit('change',{id:'platform-store',value:'A'});await flush();assert.match(h.screen,/orders-record/);
  await h.emit('change',{id:'platform-resource',value:'stock'});assert.doesNotMatch(h.screen,/orders-record/);
  pending.reject(Error('platform_network_unknown_no_retry'));await flush();assert.match(h.screen,/读取结果未知/);assert.doesNotMatch(h.screen,/orders-record/);
});
async function operations(write){
  const h=await harness('web/ops-ui.js'),calls=[];let app;
  const api=async(name,args)=>{calls.push({name,args:structuredClone(args)});if(name==='commerce_ops_list')return {rules:{max_age_minutes:60,dispatch_warning_hours:24,overstock_days:90},alerts:[],stock_plans:[],observation_count:0,connection:{server_timer:'stopped'}};if(name==='commerce_ops_record')return write(args);throw Error(name);};
  app=h.window.CommerceOps({api,esc:String,money:String,toast:h.toast,repaint(){},getCostBase:()=>({}),isActive:()=>true});
  const file=records=>({id:'ops-import',dataset:{},files:[{size:100,text:async()=>JSON.stringify(records)}]});
  return {...h,app,calls,file};
}
test('JSON imports freeze their initial scope, reject concurrent batches and block mode-changing demo actions',async()=>{
  const pending=deferred();let writes=0;const h=await operations(()=>++writes===1?pending.promise:{status:'recorded'});
  const first=h.emit('change',h.file([{event_id:'1'},{event_id:'2'}]));await flush();
  assert.match(h.app.render(),/<select id="ops-scope" disabled>/);assert.match(h.app.render(),/id="ops-import"[^>]*disabled/);
  const selector={id:'ops-scope',dataset:{},value:'demo'};await h.emit('change',selector);assert.equal(selector.value,'manual');
  await h.emit('change',h.file([{event_id:'other'}]));
  const button={type:'button',dataset:{opsAction:'demo'},closest:()=>button};await h.emit('click',{closest:()=>button});assert.equal(writes,1);
  pending.resolve({status:'recorded'});await first;
  assert.deepEqual(h.calls.filter(c=>c.name==='commerce_ops_record').map(c=>[c.args.record.event_id,c.args.demo]),[['1',false],['2',false]]);
  assert.match(h.toasts.at(-1),/导入完成（手工资料）：已确认处理 2 条/);assert.doesNotMatch(h.app.render(),/<select id="ops-scope" disabled>/);
  await h.emit('change',{id:'ops-scope',dataset:{},value:'demo'});assert.equal(h.calls.at(-1).args.demo,true);
});
test('partial JSON imports state exact confirmed progress, refresh saved records and never resend automatically',async()=>{
  let writes=0;const h=await operations(()=>{if(++writes===2)throw Error('request_outcome_unknown');return {status:'recorded'};});
  await h.emit('change',h.file([{event_id:'1'},{event_id:'2'},{event_id:'3'}]));
  assert.equal(writes,2);assert.match(h.toasts.at(-1),/导入已停止（手工资料）/);assert.match(h.toasts.at(-1),/已确认处理 1 \/ 3 条/);assert.match(h.toasts.at(-1),/不会自动重试/);assert.equal(h.calls.at(-1).name,'commerce_ops_list');assert.equal(h.calls.at(-1).args.demo,false);
});
