import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../../web/product-workspace-ui.js',import.meta.url),'utf8');
const cut=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
function fixture(){
 const messages=[],s={id:'case-a',researchTaskId:'',researchSequence:0,generation:0,changes:1,busy:false,dirty:new Set(['cost']),data:{},error:'',errorCode:''};let listener,fail=false;
 const parent={postMessage:m=>messages.push(m)};
 const context=vm.createContext({s,parent,bridged:true,reactHost:true,embedded:true,message:e=>e.message,nonce:'nonce',hostRefreshDeferred:false,window:{addEventListener:(name,fn)=>{listener=fn}},modelContext:()=>({}),hasPendingProductEdits:()=>s.dirty.size>0,announce(){},render(){},reportResearchSelection(){},tabs:{},researchContext:{task:()=>null,artifact(){}},api:async name=>{if(fail)throw Error('read_failed');return name==='commerce_workspace_list'?{items:[{id:'case-a'}]}:{case:{id:'case-a'},forms:{view:{payload:{tab:'cost'}}}}},catalog:{enter(){}},clearTimeout(){}});
 vm.runInContext(cut("  window.addEventListener('message'",'  function announce(')+cut('  async function reload(','  function selectTab(')+';this.reload=reload;',context);
 return {s,messages,context,requestRefresh:()=>listener({source:parent,data:{type:'commerce:workspace-refresh',nonce:'nonce'}}),failRead:()=>fail=true};
}
test('a deferred product refresh notice clears only after a successful clean current-item read',async()=>{
 const f=fixture();f.requestRefresh();assert.equal(f.messages.at(-1).status,'deferred');assert.equal(f.context.hostRefreshDeferred,true);
 f.s.dirty.clear();assert.equal(await f.context.reload(),'refreshed');assert.equal(f.messages.at(-1).status,'refreshed');assert.equal(f.messages.at(-1).case_id,'case-a');assert.equal(f.context.hostRefreshDeferred,false);
});
test('failed reads or remaining edits preserve the deferred refresh state',async()=>{
 const f=fixture();f.requestRefresh();assert.equal(await f.context.reload(),'refreshed');assert.equal(f.messages.length,1);assert.equal(f.context.hostRefreshDeferred,true);
 f.s.dirty.clear();f.failRead();assert.equal(await f.context.reload(),'failed');assert.equal(f.messages.length,1);assert.equal(f.context.hostRefreshDeferred,true);assert.equal(f.s.error,'read_failed');
});
