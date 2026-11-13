import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source=await readFile('../web/product-workspace-ui.js','utf8');
const identity=await readFile('../web/research-context.js','utf8');
const copilot=await readFile('../web/copilot-ui.js','utf8');
const code=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end));
const flush=()=>new Promise(setImmediate);
const snapshot=task=>({case:{id:'case-a'},forms:{cost:{revision:7}},source_sha256:'base',artifacts:{research:{id:'latest'}},gates:{approved:false},research_context:{task_id:task,artifact_id:task,read_only:true,artifact:{id:task}}});
function fixture({holdList=false}={}){
  const requests=[],reports=[],initial=snapshot('old-task');
  const s={id:'case-a',data:initial,tab:'cost',researchTaskId:'old-task',researchSequence:0,researchLoading:false,researchContextError:'',generation:0,busy:false,edits:{cost:{price:123}},dirty:new Set(['cost'])};
  const context=vm.createContext({URL,s,embedded:true,bridged:true,tabs:{},render(){},modelContext:()=>({}),message:error=>error.message,
    reportResearchSelection:()=>reports.push({task:s.researchTaskId,actual:s.data.research_context?.task_id}),
    api:(name,args)=>name==='commerce_workspace_list'&&!holdList?Promise.resolve({items:[]}):new Promise((resolve,reject)=>requests.push({name,args,resolve,reject}))});
  vm.runInContext(identity+`;const researchContext=CommerceResearchContext;`+code('  async function loadResearchContext(','  function researchView(')+code('  async function reload(','  function selectTab(')+`;this.actions={reload,loadResearchContext};`,context);
  return {s,initial,requests,reports,...context.actions};
}
test('a product still loading uses a valid local draft scope before any API response',async()=>{
  const window={addEventListener(){},removeEventListener(){}};window.parent=window;
  const context=vm.createContext({window,s:{data:null},localStorage:{getItem:()=>null}});
  vm.runInContext(copilot.slice(0,copilot.indexOf('window.CommerceCopilot=')).concat(code('  function modelContext()','  function renderChat()')),context);
  const scope=context.modelContext();assert.equal(await window.CommerceCopilotDraftStorage().request('read','commerce-copilot-draft-v1:new:'+JSON.stringify(scope)),'');
});
test('late full refresh cannot replace a newer research context or report refreshed',async()=>{
  const f=fixture(),old=f.reload();await flush();
  const latest=f.loadResearchContext('new-task');await flush();
  f.requests[1].resolve(snapshot('new-task'));await latest;
  f.requests[0].resolve(snapshot('old-task'));assert.equal(await old,'superseded');
  assert.equal(f.s.data.research_context.task_id,'new-task');assert.equal(f.s.data.forms,f.initial.forms);assert.equal(f.s.edits.cost.price,123);assert.equal(f.s.busy,false);
  assert.deepEqual(f.reports,[{task:'new-task',actual:'new-task'}]);
});
test('late failed refresh cannot replace a newer context with an error',async()=>{
  const f=fixture(),old=f.reload();await flush();const latest=f.loadResearchContext('new-task');await flush();
  f.requests[1].resolve(snapshot('new-task'));await latest;f.requests[0].reject(Error('old failure'));
  assert.equal(await old,'superseded');assert.equal(f.s.error,undefined);assert.equal(f.s.busy,false);
});
test('a refresh superseded during list loading never requests the old snapshot',async()=>{
  const f=fixture({holdList:true}),old=f.reload();const latest=f.loadResearchContext('new-task');
  f.requests[1].resolve(snapshot('new-task'));await latest;f.requests[0].resolve({items:[]});
  assert.equal(await old,'superseded');assert.equal(f.requests.length,2);assert.equal(f.s.data.research_context.task_id,'new-task');assert.equal(f.s.busy,false);
});
test('a failed explicit context is retained while the stale full refresh is ignored',async()=>{
  const f=fixture(),old=f.reload();await flush();const latest=f.loadResearchContext('new-task');await flush();
  f.requests[1].reject(Error('workspace_research_context_mismatch'));await latest;f.requests[0].resolve(snapshot('old-task'));await old;
  assert.equal(f.s.researchTaskId,'new-task');assert.equal(f.s.researchContextError,'workspace_research_context_mismatch');assert.equal(f.reports.length,0);assert.equal(f.s.busy,false);
});
test('two read-only context requests resolve only the latest selection',async()=>{
  const f=fixture(),first=f.loadResearchContext('first-task'),last=f.loadResearchContext('last-task');
  f.requests[1].resolve(snapshot('last-task'));await last;f.requests[0].resolve(snapshot('first-task'));await first;
  assert.equal(f.s.data.research_context.task_id,'last-task');assert.equal(f.s.researchLoading,false);assert.equal(f.s.data.source_sha256,'base');assert.deepEqual(f.reports,[{task:'last-task',actual:'last-task'}]);
});
