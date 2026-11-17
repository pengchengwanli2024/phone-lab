import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {transform,build} from 'esbuild';
import vm from 'node:vm';
const inputBundle=await build({entryPoints:['src/cost-input.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {fromInput,toInput,validateInput,differences}=await import('data:text/javascript;base64,'+Buffer.from(inputBundle.outputFiles[0].text).toString('base64'));
const source=await readFile(new URL('../src/cost-page.tsx',import.meta.url),'utf8');
const cut=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const code=(await transform(cut('  function adoptWorkspace(','  function focusError(')+cut('  async function load(inspect','  async function enableDynamic(')+cut("  async function submit(action:",'  const result = surface?.result')+';this.actions={load,submit,confirmCurrency};',{loader:'ts'})).code;
const clone=x=>JSON.parse(JSON.stringify(x));
const input={currency:'CNY',price:100,purchase_cost:20,domestic_shipping:2,packaging:1,fulfillment_cost:10,electronic_fee:1,commission_rate:.1,payment_rate:.02,return_rate:.03,ad_rate:.05};
const product=(overrides={})=>({case:{id:'exact-case',currency:'CNY',scope:{}},name:'Synthetic cost',source_sha256:'source-a',forms:{cost:{revision:3,payload:{input},stale:false}},calculation:{status:'CALCULATED',price:100,currency:'CNY',contribution:56,total_cost:44,contribution_rate:.56,missing:[]},...overrides});
function fixture(api){
 const requests=[],state={caseId:'exact-case',product:product(),surface:null,requestedSurface:'',values:fromInput(input),dirty:false,loaded:false,busy:false,blocked:false,unknown:false,review:null,standardReview:null,workspaceReview:null,scenarioWriting:false,targetPending:false,sourceReviewed:false,operation:{current:false},version:{current:0},pending:{current:null},draftValues:{current:fromInput(input)},draftRevision:0,error:'',message:'',fieldErrors:{},standardResult:null,dynamic:true};
 const setters=Object.fromEntries(['Product','Surface','Values','Dirty','Loaded','Blocked','Unknown','Review','StandardReview','WorkspaceReview','SourceReviewed','Error','Message','FieldErrors','StandardResult','Dynamic','LoadErrorCode','DraftRevision','Busy'].map(name=>['set'+name,value=>{const key=name[0].toLowerCase()+name.slice(1);state[key]=typeof value==='function'?value(state[key]):value}]));
 Object.assign(state,setters,{draftScope:{module:'operations',form:'cost',case_id:''},Error,TypeError,fromInput,toInput,validateInput,differences,errorText:e=>e.message,focusError(){},standardLoad:()=>{throw Error('unbound fallback forbidden')},adopt:()=>{throw Error('dynamic adoption unexpected')},newKey:()=> 'new-key',api:async(name,args)=>{requests.push({name,args:clone(args||{})});return api(name,args,state)}});
 vm.runInNewContext(code,state);return {state,requests,...state.actions};
}
test('disabled dynamic rendering opens a bound standard form using saved percentage input',async()=>{
 const f=fixture(name=>name==='commerce_workspace_get'?product():{enabled:false});await f.load();assert.equal(f.state.loaded,true);assert.equal(f.state.dynamic,false);assert.equal(f.state.values.commission_rate,'10');assert.equal(f.state.product.case.id,'exact-case');assert.deepEqual(f.requests.map(x=>x.name),['commerce_workspace_get','commerce_a2ui_status']);
});
test('standard restoration offers a saved-version comparison instead of replacing dirty local input',async()=>{
 const f=fixture(name=>name==='commerce_workspace_get'?product():{enabled:false});f.state.dirty=true;f.state.values.price='117';await f.load(true);assert.equal(f.state.values.price,'117');assert.equal(f.state.workspaceReview.case.id,'exact-case');assert.equal(f.state.workspaceReview.forms.cost.revision,3);
});
test('bound standard form saves exact scope and percentage contract before calculation, then reads current receipt',async()=>{
 const f=fixture((name,args)=>name==='commerce_workspace_save'?{revision:4,payload:args.payload,source_sha256:'source-a'}:name==='commerce_workspace_calculate'?product().calculation:product({source_sha256:'source-b',forms:{cost:{revision:5,payload:{input:{...input,price:117}},stale:false}}}));f.state.loaded=true;f.state.dirty=true;f.state.values.price='117';await f.submit('calculate');
 assert.deepEqual(f.requests.map(x=>x.name),['commerce_workspace_save','commerce_workspace_calculate','commerce_workspace_get']);assert.deepEqual(f.requests[0].args,{case_id:'exact-case',form:'cost',payload:{input:{...input,price:117}},expected_revision:3,expected_source_sha256:'source-a'});assert.deepEqual(f.requests[1].args,{case_id:'exact-case',expected_revision:4,expected_source_sha256:'source-a'});assert.equal(f.state.product.forms.cost.revision,5);assert.equal(f.state.product.source_sha256,'source-b');assert.equal(f.state.dirty,false);
});
test('failed save preserves input and does not calculate or use an unbound draft',async()=>{
 const f=fixture(()=>{throw Error('form_draft_conflict')});f.state.loaded=true;f.state.dirty=true;f.state.values.price='117';await f.submit('calculate');assert.equal(f.state.dirty,true);assert.equal(f.state.values.price,'117');assert.equal(f.state.blocked,true);assert.deepEqual(f.requests.map(x=>x.name),['commerce_workspace_save']);
});
test('a confirmed save followed by failed calculation retains its new revision and does not resend that save',async()=>{
 let fail=true;const f=fixture((name,args)=>{if(name==='commerce_workspace_save')return {revision:4,payload:args.payload,source_sha256:'source-a'};if(name==='commerce_workspace_calculate'&&fail)throw Error('workspace_quote_not_ready');return name==='commerce_workspace_get'?product({forms:{cost:{revision:5,payload:{input},stale:false}}}):product().calculation;});f.state.loaded=true;f.state.dirty=true;await f.submit('calculate');assert.equal(f.state.product.forms.cost.revision,4);assert.equal(f.state.dirty,false);fail=false;await f.submit('calculate');assert.equal(f.requests.filter(x=>x.name==='commerce_workspace_save').length,1);assert.equal(f.requests.filter(x=>x.name==='commerce_workspace_calculate')[1].args.expected_revision,4);
});
test('currency mismatch cannot write a calculation and explicit confirmation preserves current parameter edits',async()=>{
 const f=fixture(name=>name==='commerce_workspace_get'?product({case:{id:'exact-case',currency:'USD',scope:{}},source_sha256:'source-usd'}):{});f.state.loaded=true;f.state.dirty=true;f.state.values.currency='USD';f.state.values.price='117';await f.submit('calculate');assert.equal(f.requests.length,0);assert.equal(f.state.error,'workspace_currency_required');await f.confirmCurrency();assert.equal(f.requests[0].name,'commerce_workspace_currency');assert.deepEqual(f.requests[0].args,{case_id:'exact-case',currency:'USD',expected_source_sha256:'source-a'});assert.equal(f.state.values.price,'117');assert.equal(f.state.product.source_sha256,'source-usd');assert.equal(f.state.dirty,true);
});
test('unknown write outcome blocks later writes until a read and review resolve it',async()=>{
 const f=fixture(()=>{throw TypeError('synthetic connection loss')});f.state.loaded=true;f.state.dirty=true;await f.submit('update');await f.submit('calculate');assert.equal(f.requests.length,1);assert.equal(f.state.unknown,true);assert.equal(f.state.blocked,true);assert.equal(f.state.dirty,true);
});

test('generic standard calculation keeps unsaved values available for an explicit draft save',async()=>{
 const f=fixture(name=>name==='commerce_unit_economics'?product().calculation:{revision:1});f.state.caseId='';f.state.product=null;f.state.loaded=true;f.state.dirty=true;f.state.values.price='117';await f.submit('calculate');assert.equal(f.state.dirty,false);assert.equal(f.state.draftValues.current.price,'100');
 const pendingLine=source.split('\n').find(line=>line.includes('const uncommitted='));vm.runInNewContext((await transform(pendingLine+';this.isUncommitted=uncommitted;',{loader:'ts'})).code,f.state);assert.equal(f.state.isUncommitted,true);assert.equal(f.requests[0].args.input.commission_rate,.1);await f.submit('update');assert.equal(f.requests[1].name,'commerce_form_draft_save');assert.equal(f.requests[1].args.payload.values.price,'117');assert.equal(f.requests[1].args.payload.values.commission_rate,'10');assert.equal(f.state.draftValues.current.price,'117');
});

test('a failed read-only dynamic capability probe still exposes the current product standard form',async()=>{
 const f=fixture(name=>{if(name==='commerce_workspace_get')return product();throw TypeError('probe unavailable')});await f.load();assert.equal(f.state.loaded,true);assert.equal(f.state.product.case.id,'exact-case');assert.equal(f.state.dynamic,false);assert.equal(f.state.error,'');assert.deepEqual(f.requests.map(x=>x.name),['commerce_workspace_get','commerce_a2ui_status']);
});
test('an uncertain dynamic creation is not replaced by another cost write path',async()=>{
 const f=fixture(name=>{if(name==='commerce_workspace_get')return product();if(name==='commerce_a2ui_status')return {enabled:true};throw TypeError('create receipt missing')});await f.load();assert.equal(f.state.loaded,false);assert.deepEqual(f.requests.map(x=>x.name),['commerce_workspace_get','commerce_a2ui_status','commerce_a2ui_create']);
});

test('saving standard product input alone does not present a read-derived estimate as a completed calculation',async()=>{
 const f=fixture((name,args)=>name==='commerce_workspace_save'?{revision:4,payload:args.payload,source_sha256:'source-a'}:product({forms:{cost:{revision:4,payload:{input},stale:false}}}));f.state.loaded=true;f.state.dirty=true;await f.submit('update');assert.equal(f.state.standardResult,null);assert.match(f.state.message,/测算结果待重新计算/);assert.deepEqual(f.requests.map(x=>x.name),['commerce_workspace_save','commerce_workspace_get']);
});

test('unresolved saved-version conflicts also block the explicit currency write',async()=>{
 const f=fixture(()=>{throw Error('write forbidden')});f.state.values.currency='USD';f.state.blocked=true;await f.confirmCurrency();assert.equal(f.requests.length,0);f.state.blocked=false;f.state.workspaceReview=product();await f.confirmCurrency();assert.equal(f.requests.length,0);
});
