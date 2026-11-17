import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const root=new URL('../../',import.meta.url);
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function deferred(){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
const A='a'.repeat(32),B='b'.repeat(32);
const account=(id,active,extra={})=>({account_id:id,label:active?'Synthetic active store':'Synthetic saved store',active,configured:true,connection_id:'synthetic-'+id,stored_snapshot_count:null,fulfillment_modes:['OGL'],status:active?'active_single_connector':'stored_inactive',automatic_sync_enabled:false,...extra});
const accounts=rows=>({accounts:rows,mode:'single_active_connector',parallel_store_sync:false});
const store={store_id:'synthetic-amazon',label:'Synthetic Amazon store',platform:'amazon',market:'US',configured:true,enabled:true,scope_reviewed:true,missing_fields:[],resources:['orders','stock'],last_job:null,revision:'synthetic-revision'};
async function harness(overrides={}){
  const listeners={},calls=[],toasts=[];let app,active=true,ozonVisits=0,connectionVisits=0,screen='',dialog=null;
  const document={documentElement:{dataset:{}},addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn),querySelector:selector=>selector==='.dialog'?dialog:selector==='#platform-window'?{value:'7'}:null};
  const context={window:{matchMedia:()=>({matches:false,addEventListener(){}}),dispatchEvent(){}},document,CustomEvent:class{},setInterval:()=>0,setTimeout:()=>0,crypto:globalThis.crypto,URL,Blob,Date};
  vm.runInNewContext(await readFile(new URL('ui/kit.js',root),'utf8'),context,{filename:'ui/kit.js'});
  vm.runInNewContext(await readFile(new URL('web/platform-ui.js',root),'utf8'),context,{filename:'web/platform-ui.js'});
  const api=async(name,args)=>{
    calls.push({name,args:structuredClone(args)});
    if(overrides[name])return overrides[name](args);
    if(name==='commerce_platform_catalog')return {};
    if(name==='commerce_platform_list')return {stores:[store]};
    if(name==='commerce_platform_snapshot')return {available:false};
    if(name==='commerce_ozon_accounts_list')return accounts([]);
    if(name==='commerce_ozon_account_status')return {account:account(args.account_id,args.account_id===A),mode:'single_active_connector'};
    if(name==='commerce_live_open_setup')return {opened:true};
    if(name==='commerce_platform_open_setup')return {status:'opened_local_private_setup'};
    throw Error('Unexpected tool: '+name);
  };
  app=context.window.CommercePlatforms({api,esc:context.window.CommerceUI.escape,toast:v=>toasts.push(v),repaint:()=>screen=app.view(),isActive:()=>active,onConnections:()=>connectionVisits++,onOzon:()=>ozonVisits++,modal:(title,body,actions)=>dialog={title,body,actions},closeModal:()=>dialog=null});
  const emit=async(name,target)=>{for(const fn of listeners[name]??[])await fn({target,preventDefault(){},stopImmediatePropagation(){}});};
  const click=(action,data={})=>{const b={dataset:{platformAction:action,...data},disabled:false,isConnected:false,focus(){}};return emit('click',{closest:selector=>selector==='[data-platform-action]'?b:null});};
  return {app,calls,toasts,click,change:(id,value)=>emit('change',{id,value}),setActive:value=>active=value,get screen(){return screen||app.view();},get dialog(){return dialog;},get ozonVisits(){return ozonVisits;},get connectionVisits(){return connectionVisits;}};
}

test('seven visible provider choices open the exact private wizard and never claim binding succeeded',async()=>{
  const h=await harness();await h.app.enter();
  const options=[...h.screen.matchAll(/<option value="([^"]+)"[^>]*>/g)].map(m=>m[1]);
  for(const provider of ['ozon','tiktok','amazon','mercado','temu','shopify','woocommerce']){
    assert.ok(options.includes(provider));
    await h.change('platform-add-provider',provider);await h.click('bind');
    assert.deepEqual(h.calls.at(-1),provider==='ozon'?{name:'commerce_live_open_setup',args:{}}:{name:'commerce_platform_open_setup',args:{platform:provider}});
    assert.match(h.screen,/已请求打开私有接入向导/);assert.doesNotMatch(h.screen,/>(绑定成功|授权成功)</);
  }
  assert.match(h.screen,/密钥、令牌和密码仅在私有向导填写/);
  assert.doesNotMatch(h.screen,/<input[^>]*type="password"/);
  await h.click('setup');assert.equal(h.connectionVisits,1);
});

test('opening a wizard freezes provider choice, blocks duplicate clicks and keeps failure distinct from binding',async()=>{
  const pending=deferred(),h=await harness({commerce_platform_open_setup:()=>pending.promise});await h.app.enter();
  await h.change('platform-add-provider','amazon');const first=h.click('bind');await flush();
  assert.match(h.screen,/<select[^>]*id="platform-add-provider"[^>]*disabled/);
  await h.change('platform-add-provider','shopify');await h.click('bind');
  assert.equal(h.calls.filter(c=>c.name==='commerce_platform_open_setup').length,1);
  pending.reject(Error('SECRET_ERROR_MUST_STAY_PRIVATE'));await first;
  assert.match(h.screen,/私有接入向导未能打开/);assert.doesNotMatch(h.screen,/SECRET_ERROR|>绑定成功</);
  assert.match(h.screen,/<option value="amazon" selected/);
  assert.doesNotMatch(h.screen,/<select[^>]*id="platform-add-provider"[^>]*disabled/);
});

test('unconfirmed browser launch is not a successful opening and hidden-page management events cannot execute',async()=>{
  const h=await harness({commerce_live_open_setup:()=>({opened:false})});await h.app.enter();await h.click('bind');
  assert.match(h.screen,/是否打开尚未确认/);assert.doesNotMatch(h.screen,/已请求打开私有接入向导/);
  const before=h.calls.length;h.setActive(false);await h.click('bind');await h.click('ozon-setup');
  assert.equal(h.calls.length,before);
});

test('Ozon tool failure leaves other provider selection and scoped snapshot reads usable',async()=>{
  const h=await harness({commerce_ozon_accounts_list:()=>{throw Error('PRIVATE_FAILURE');}});await h.app.enter();
  assert.match(h.screen,/Ozon 账号状态未能读取/);assert.match(h.screen,/Synthetic Amazon store/);
  assert.doesNotMatch(h.screen,/PRIVATE_FAILURE|当前活跃店铺|本地快照：0|已连接/);
  await h.change('platform-store',store.store_id);await flush();
  assert.deepEqual(h.calls.at(-1),{name:'commerce_platform_snapshot',args:{store_id:store.store_id,resource:'orders'}});
  assert.match(h.screen,/当前没有完整快照/);assert.equal(h.toasts.length,0);
});

test('multiple saved Ozon accounts expose only safe metadata, exact account detail and single active navigation',async()=>{
  const rows=[account(A,true,{label:'Synthetic <active>',stored_snapshot_count:3,api_key:'SECRET_LIST_VALUE'}),account(B,false)];
  const h=await harness({commerce_ozon_accounts_list:()=>accounts(rows),commerce_ozon_account_status:args=>({account:{...rows.find(a=>a.account_id===args.account_id),api_key:'SECRET_DETAIL_VALUE'},mode:'single_active_connector'})});await h.app.enter();
  assert.match(h.screen,/一次仅一个活跃读取连接/);assert.match(h.screen,/尚不支持多店并行同步/);
  assert.match(h.screen,/Synthetic &lt;active&gt;/);assert.doesNotMatch(h.screen,/<active>|SECRET_LIST_VALUE/);
  assert.match(h.screen,/本地快照：3 份/);assert.match(h.screen,/本地快照：未知/);
  assert.equal((h.screen.match(/data-platform-action="ozon"/g)||[]).length,1);
  assert.equal(h.calls.filter(c=>c.name==='commerce_ozon_account_status').length,0);
  await h.click('account',{accountId:B});assert.deepEqual(h.calls.at(-1),{name:'commerce_ozon_account_status',args:{account_id:B}});
  assert.match(h.screen,/Synthetic saved store/);assert.match(h.screen,/未核实平台身份/);assert.doesNotMatch(h.screen,/SECRET_DETAIL_VALUE|<dd>0 份/);
  await h.click('ozon',{accountId:B});assert.equal(h.ozonVisits,0);
  await h.click('ozon',{accountId:A});assert.equal(h.ozonVisits,1);
  await h.click('ozon-setup');assert.deepEqual(h.calls.at(-1),{name:'commerce_live_open_setup',args:{}});
  assert.equal(h.calls.filter(c=>/sync|activate|configure|pause/.test(c.name)).length,0);
});

test('late account details cannot replace another account or reopen details closed by the user',async()=>{
  const pendingA=deferred(),pendingB=deferred();let bReads=0;
  const h=await harness({commerce_ozon_accounts_list:()=>accounts([account(A,true),account(B,false)]),commerce_ozon_account_status:({account_id})=>account_id===A?pendingA.promise:++bReads===1?{account:account(B,false,{label:'Latest exact B'}),mode:'single_active_connector'}:pendingB.promise});await h.app.enter();
  const first=h.click('account',{accountId:A});await flush();await h.click('account',{accountId:B});
  pendingA.resolve({account:account(A,true,{label:'Stale detail A'}),mode:'single_active_connector'});await first;
  assert.match(h.screen,/Latest exact B/);assert.doesNotMatch(h.screen,/Stale detail A/);
  const second=h.click('account',{accountId:B});await flush();await h.click('close-account');
  pendingB.resolve({account:account(B,false,{label:'Closed detail B'}),mode:'single_active_connector'});await second;
  assert.doesNotMatch(h.screen,/Closed detail B|Ozon 店铺信息/);
});

test('refresh removes stale Ozon details and ignores older list responses; mismatched account receipts stay unknown',async()=>{
  const old=deferred();let reads=0;
  const h=await harness({commerce_ozon_accounts_list:()=>++reads===1?old.promise:accounts([account(B,true,{label:'Latest list B'})]),commerce_ozon_account_status:()=>({account:account(A,true),mode:'single_active_connector'})});
  const first=h.app.enter();await flush();await h.app.enter();
  old.resolve(accounts([account(A,true,{label:'Stale list A'})]));await first;
  assert.match(h.screen,/Latest list B/);assert.doesNotMatch(h.screen,/Stale list A/);
  await h.click('account',{accountId:B});assert.match(h.screen,/所选账号信息未能核对/);assert.doesNotMatch(h.screen,/<dd>活跃/);
  await h.app.enter();assert.doesNotMatch(h.screen,/所选账号信息未能核对|Ozon 店铺信息/);
});

test('invalid multiple-active or incomplete Ozon list never becomes connected, an empty account list or zero snapshots',async()=>{
  for(const response of [accounts([account(A,true),account(B,true)]),{accounts:[]},accounts([account(A,true),account(A,false)])]){
    const h=await harness({commerce_ozon_accounts_list:()=>response});await h.app.enter();
    assert.match(h.screen,/Ozon 账号状态未能读取/);assert.doesNotMatch(h.screen,/还没有保存 Ozon 店铺|当前活跃店铺|本地快照：0|已连接/);
  }
});

test('new management actions preserve the original confirmed store/resource/revision/window read contract',async()=>{
  const h=await harness({commerce_platform_sync:args=>({store_id:args.store_id,id:'synthetic-job',status:'queued'})});await h.app.enter();
  await h.change('platform-store',store.store_id);await flush();await h.change('platform-resource','stock');await flush();
  await h.click('read');assert.match(h.dialog.body,/Synthetic Amazon store/);assert.match(h.dialog.body,/库存/);
  const frozen=Object.fromEntries([...h.dialog.actions.matchAll(/data-(store|revision|resource|days|key)="([^"]+)"/g)].map(m=>[m[1],m[2]]));
  assert.deepEqual({...frozen,key:'normalized-key'},{store:store.store_id,revision:store.revision,resource:'stock',days:'7',key:'normalized-key'});
  await h.click('confirm',frozen);
  assert.deepEqual(h.calls.find(c=>c.name==='commerce_platform_sync').args,{store_id:store.store_id,resource:'stock',expected_revision:store.revision,window_days:7,max_pages:3,idempotency_key:frozen.key});
});
