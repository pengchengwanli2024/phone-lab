import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../../web/app.js',import.meta.url),'utf8');
const navigateCode=source.split('\n').find(line=>line.startsWith('  async function navigate(tab,initial=false)'));
const marker="  document.addEventListener('click',async event=>{\n    const b=event.target.closest('button');";
const start=source.lastIndexOf(marker),end=source.indexOf("  document.addEventListener('keydown',event=>{",start);
assert.ok(navigateCode&&start>=0&&end>start,'shared navigation and inventory action listener are available');
function deferred(){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
function harness({load=async()=>{},open=async()=>{},businessController,invoke,action='live-restock'}={}){
 const trace=[],messages=[],errors=[],handlers={};
 const button={dataset:{action,stockKey:'product-001:FBS:RU:exact-row',id:'SYN-ORDER:1'},type:'button',isConnected:true,disabled:false};
 const state={tab:action==='order-support'?'orders':'products',demo:false,orders:[{id:'SYN-ORDER:1',platform:'ozon',store_id:'synthetic-store',market:'RU',source_sha256:'a'.repeat(64)}],groupVisited:{},focusTitle:false};
 const context=vm.createContext({state,labels:{products:'库存',live:'Ozon 经营'},navigationGeneration:0,pendingFormRestore:null,formRestoreGeneration:0,dialogTrigger:null,
  document:{querySelector:()=>null,addEventListener:(type,handler)=>{handlers[type]=handler;}},ui:{moduleDetails:()=>({group:'store'})},business:businessController||{cancelEditor:()=>trace.push('cancel-editor')},reactHost:true,bridgeNonce:'synthetic-nonce',
  parent:{postMessage:message=>{messages.push(message);trace.push('route:'+message.tab);}},paint:()=>trace.push('paint'),toast:error=>errors.push(error),
  live:{load:async()=>{trace.push('load');await load();trace.push('loaded');},openPlan:async key=>{trace.push('open:'+key);await open(key);}},
  api:invoke||(()=>{throw Error('no direct business invocation expected');})
 });
 vm.runInContext(navigateCode+'\n'+source.slice(start,end),context);
 return {trace,messages,errors,button,state,click:()=>handlers.click({target:{closest:()=>button},preventDefault(){},stopImmediatePropagation(){}})};
}
test('inventory restock routes through the shared parent navigation before opening the exact stock row',async()=>{
 const read=deferred(),h=harness({load:()=>read.promise});const click=h.click();await Promise.resolve();
 assert.equal(h.messages.length,1);assert.equal(h.messages[0].type,'commerce:workspace-navigate');assert.equal(h.messages[0].tab,'live');assert.equal(h.messages[0].nonce,'synthetic-nonce');assert.equal(h.state.tab,'live');assert.deepEqual(h.trace,['cancel-editor','route:live','load']);
 read.resolve();await click;assert.deepEqual(h.trace,['cancel-editor','route:live','load','loaded','open:product-001:FBS:RU:exact-row']);assert.deepEqual(h.errors,[]);
});
test('a failed route load reports the failure and never opens a stock row against unread data',async()=>{
 const h=harness({load:async()=>{throw Error('snapshot-unavailable');}});await h.click();assert.equal(h.messages[0].tab,'live');assert.deepEqual(h.trace,['cancel-editor','route:live','load']);assert.deepEqual(h.errors,['snapshot-unavailable']);assert.equal(h.button.disabled,false);
});
test('an exact-row open failure stays on the admitted route without retrying another row',async()=>{
 const h=harness({open:async()=>{throw Error('stock-row-unavailable');}});await h.click();assert.equal(h.state.tab,'live');assert.deepEqual(h.trace,['cancel-editor','route:live','load','loaded','open:product-001:FBS:RU:exact-row']);assert.deepEqual(h.errors,['stock-row-unavailable']);assert.equal(h.messages.length,1);
});

test('the actual business controller translates order handoff failures without a secondary TypeError',async()=>{
 const root=new URL('../../',import.meta.url);const modules=await Promise.all(['ui/kit.js','web/businessforms-ui.js','web/order-support-context.js','web/business-ui.js'].map(name=>readFile(new URL(name,root),'utf8')));
 let calls=0;const document={documentElement:{dataset:{}},addEventListener(){},querySelector:()=>null,querySelectorAll:()=>[],getElementById:()=>null};const window={dispatchEvent(){},matchMedia:()=>({matches:false,addEventListener(){}})};
 const c=vm.createContext({window,document,crypto:globalThis.crypto,CustomEvent:class{},setTimeout(){}});for(const code of modules)vm.runInContext(code,c);
 const controller=window.CommerceBusiness({api:()=>{calls++;throw Error('no factory call expected');},esc:window.CommerceUI.escape,toast(){},repaint(){},modal(){},closeModal(){},isActive:()=>false});assert.equal(typeof controller.errorText,'function');
 const h=harness({businessController:controller,action:'order-support',invoke:async()=>{throw Error('order_support_scope_unconfirmed');}});await h.click();assert.equal(h.errors.length,1);assert.match(h.errors[0],/店铺连接.*确认订单范围/);assert.doesNotMatch(h.errors[0],/TypeError|order_support_scope_unconfirmed/);assert.equal(h.button.disabled,false);assert.equal(calls,0);
});
