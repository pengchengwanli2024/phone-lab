import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../src/app.tsx',import.meta.url),'utf8');
const code=source.slice(source.indexOf('  function navigate('),source.indexOf('  function chooseStoreScope(')).replace('next: string, id?: string, taskId?: string','next, id, taskId');
function fixture(){
 const updates={},url={value:'http://example.test/?tab=workspace&case_id=product-a'},noop=()=>{};
 const setters=Object.fromEntries(['CreativeIntent','AssistantContext','FramePage','FrameScope','ListingAction','RequestedThreadId','ResearchTaskId','ProductTab','ProductCaseId','ProductResearchTask','CostCaseId','CostSurfaceId','ListingTarget','ListingCaseId','WorkflowCase','Tab','MobileView','CaseId','LegacyTab','LegacyStarted'].map(name=>['set'+name,value=>{updates[name]=value}]));
 const context=vm.createContext({...setters,productSelection:{current:'product-a'},productResearchTask:'',workflowCase:'product-a',costSurfaceId:'',tab:'workspace',legacy:false,holdCostTransition:()=>true,writeCreativeIntent(){},holdProductTransition:()=>true,cancelOrderSupport:noop,setError:noop,threadRequest:{current:0},setVisited:noop,labels:Object.fromEntries(['workspace','operations','listing','workflow','agent','skills','assistant-team','overview'].map(x=>[x,x])),migrated:['workspace','listing','workflow','overview'],window:{},location:{get href(){return url.value}},history:{pushState:(_s,_t,value)=>{url.value=String(value)}},acceptedURL:{current:url.value},requestAnimationFrame:noop,URL,Set});context.window.parent=context.window;
 vm.runInContext(code+';this.go=navigate;',context);return {context,updates,url};
}
test('generic module navigation clears a previous product ID instead of opening it as a run',()=>{
 for(const target of ['agent','skills','assistant-team','overview']){const f=fixture();f.context.go(target);assert.equal(f.updates.CaseId,'');assert.equal(new URL(f.url.value).searchParams.has('case_id'),false);assert.equal(f.context.productSelection.current,'product-a');}
});
test('explicit detail IDs and product destinations retain their own identities',()=>{
 const f=fixture();f.context.go('agent','run-1');assert.equal(f.updates.CaseId,'run-1');assert.equal(new URL(f.url.value).searchParams.get('case_id'),'run-1');
 for(const target of ['workspace','workflow','listing']){const g=fixture();g.context.go(target);assert.equal(g.updates.CaseId,'product-a');assert.equal(new URL(g.url.value).searchParams.get('case_id'),'product-a');}
});
