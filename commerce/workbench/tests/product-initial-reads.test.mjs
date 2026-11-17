import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../../web/product-workspace-ui.js',import.meta.url),'utf8');
const start=source.indexOf('  const initialLoad=');
const boot=source.slice(start,source.indexOf('  if(!embedded)api(',start));
const reload=source.slice(source.indexOf('  async function reload('),source.indexOf('  function selectTab('));
const flush=()=>new Promise(setImmediate);
function fixture(selected=false){
  let reads=0;const requests=[],ready=[],parent={postMessage:m=>ready.push(m)};
  const s={id:selected?'exact-case':'',data:null,tab:'overview',researchTaskId:'',researchSequence:0,generation:0,busy:false};
  const context=vm.createContext({s,bridged:true,embedded:true,reactHost:true,hostRefreshDeferred:false,parent,nonce:'synthetic',tabs:{overview:true},
    modelContext:()=>({}),render(){},reportResearchSelection(){},message:e=>e.message,
    researchContext:{task:()=>'',artifact(){}},
    api:(tool,args)=>new Promise((resolve,reject)=>requests.push({tool,args,resolve,reject})),
    catalog:{enter:()=>{reads++;return Promise.resolve()}}});
  vm.runInContext(reload+'\n'+boot+'\nthis.retry=reload;',context);
  return {requests,get reads(){return reads},ready,context,s};
}
const list={items:[{id:'case-a'},{id:'case-b'}]};
test('the product selector finishes its first read before browsing the whole catalog',async()=>{
  const f=fixture();assert.equal(f.reads,0,'No competing full catalog request during the picker read');
  f.requests[0].resolve(list);await flush();assert.equal(f.reads,1);assert.equal(f.ready.length,1);
});
test('a direct selected product never preloads an invisible full catalog',async()=>{
  const f=fixture(true);f.requests[0].resolve(list);await flush();
  assert.equal(f.requests[1].tool,'commerce_workspace_get');assert.equal(f.reads,0);
  f.requests[1].resolve({case:{id:'exact-case'},forms:{view:{payload:null}}});await flush();
  assert.equal(f.reads,0);assert.equal(f.ready.length,1);
});
test('a failed essential read does not start additional catalog work or retry it',async()=>{
  const f=fixture();f.requests[0].reject(Error('commerce_service_unavailable'));await flush();
  assert.equal(f.reads,0);assert.equal(f.requests.length,1);assert.equal(f.ready.length,1);
});
test('an explicit reread after disconnection restores the product browser as well as its picker',async()=>{
  const f=fixture();f.requests[0].reject(Error('commerce_service_unavailable'));await flush();
  const retry=f.context.retry();f.requests[1].resolve(list);assert.equal(await retry,'refreshed');await flush();
  assert.equal(f.reads,1);assert.equal(f.s.items.length,2);assert.equal(f.s.error,'');
});
