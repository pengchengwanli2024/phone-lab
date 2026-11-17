import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';
const source=fs.readFileSync(new URL('../../web/product-evidence-ui.js',import.meta.url),'utf8');
const criteria={demand:'需求',competition:'竞争',differentiation:'差异化',economics:'成本',supply:'供应',compliance:'规则'};
const sourceRow={id:'ev_'+'a'.repeat(32),revision:1,sha256:'entry-a',kind:'supplier',platform:'1688',label:'原始供货源',url:'https://detail.1688.com/offer/123.html',model:'A1',variant:'银色',observed_at:'2026-11-17T01:00:00+00:00',valid_until:'',review_state:'unreviewed',verification_note:'待核对',rights_status:'reference_only',rights_evidence:'',notes:'',quote_ids:['q1'],images:[],metrics:{},archived:false,fresh:true,recent:true,history:[]};
function data(id='case-a'){return {case_id:id,name:id,case:{currency:'RUB',scope:{platform:'ozon',market:'RU'}},dossier_sha256:'sha-'+id,sources:[structuredClone(sourceRow)],proposal:{revision:0,customer_need:'',selection_reason:'',differentiation:'',risks:'',conditions:'',currency:'RUB',trial_quantity:null,trial_budget:null,max_loss:null,min_contribution_rate:null},quotes:[{quote_id:'q1',revision:1,status:'HOLD',fields:{supplier:'供应商',currency:'CNY',purchase_cost:8},missing:['交期']}],economics:{status:'HOLD',missing:['price']},cost_checkpoint:{revision:1,payload:{input:{currency:'RUB',purchase_cost:181.53}}},projects:[{id:'project-a',name:'创意',assets:[{id:'ai-a',kind:'generated_image',name:'AI主图'}]}],executions:[{id:'task-a',title:'原执行',status:'queued',origin:'task'}],reviews:[],criteria,platforms:[{id:'1688',label:'1688'},{id:'yiwugo',label:'义乌购'}],available_evidence:[{id:'source:'+sourceRow.id+'@1',label:'来源v1'}],readiness:{trial_prerequisites_met:false,gaps:['需求待补']}};}
function fixture(apiOverride,options={}){
 const calls=[],dirty=[],window={CommerceUI:{escape:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),button:({label,attrs={}})=>'<button '+Object.entries(attrs).map(([k,v])=>k+'="'+v+'"').join(' ')+'>'+label+'</button>',badge:t=>'<span>'+t+'</span>',field:(l,c)=>'<label>'+l+c+'</label>',input:p=>'<input '+Object.entries(p).map(([k,v])=>k+'="'+v+'"').join(' ')+'>',select:p=>'<select></select>',table:(_h,rows)=>'<table>'+rows.join('')+'</table>'}};
 const api=async(tool,args)=>{calls.push({tool,args:structuredClone(args)});if(apiOverride){const r=await apiOverride(tool,args);if(r!==undefined)return r;}if(tool.endsWith('_get'))return data(args.case_id);if(tool.endsWith('_source_save'))return {entry:{...args.payload,id:args.entry_id||'ev_'+'b'.repeat(32),revision:args.expected_revision+1}};if(tool.endsWith('_review_save'))return {review:{id:'review-a'}};return {};};
 const context=vm.createContext({window,document:{querySelectorAll:()=>[],getElementById:()=>null},crypto:{randomUUID},structuredClone,URL,Blob,Uint8Array,atob:globalThis.atob,btoa:globalThis.btoa,setTimeout,clearTimeout,console});
 vm.runInContext(source,context);
 const c=window.CommerceProductEvidence({api,repaint(){},onDirty:v=>dirty.push(v),onNavigate(){},...options});
 return {c,calls,dirty,document:context.document};
}
test('sources expose mainland platforms, original quote and generated media separately',async()=>{
 const f=fixture();await f.c.enter('case-a');const h=f.c.view();assert.match(h,/1688/);assert.match(h,/原始供货源/);assert.match(h,/AI/);assert.match(h,/8/);
});
test('editing supplier keeps original quote binding and saves exact case/version',async()=>{
 const f=fixture();await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});
 f.c.input({dataset:{peField:'label'},value:'修改后的供货源'});
 assert.equal(f.c.hasUnsavedChanges(),true);
 await f.c.action('source-save',{dataset:{}});
 const call=f.calls.find(r=>r.tool.endsWith('_source_save'));
 assert.equal(call.args.case_id,'case-a');assert.equal(call.args.expected_dossier_sha256,'sha-case-a');assert.equal(call.args.expected_revision,1);assert.deepEqual(call.args.payload.quote_ids,['q1']);assert.equal(call.args.payload.label,'修改后的供货源');
});
test('failed save retains editable text and original version',async()=>{
 const f=fixture((t)=>{if(t.endsWith('_source_save'))throw Error('evidence_dossier_changed');});await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});
 f.c.input({dataset:{peField:'notes'},value:'必须保留的修改'});await f.c.action('source-save',{dataset:{}});
 assert.equal(f.c.hasUnsavedChanges(),true);assert.match(f.c.view(),/必须保留的修改/);assert.match(f.c.view(),/变化|核对/);
});
test('dirty dossier cannot be silently switched to another product',async()=>{
 const f=fixture();await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});
 f.c.input({dataset:{peField:'label'},value:'未保存'});const before=f.calls.length;await f.c.enter('case-b');
 assert.equal(f.calls.length,before);assert.match(f.c.view(),/未保存/);
});
test('late product read never replaces the active product',async()=>{
 let resolve;const f=fixture((t,a)=>t.endsWith('_get')&&a.case_id==='case-a'?new Promise(r=>resolve=r):undefined);
 const a=f.c.enter('case-a');await f.c.enter('case-b');resolve(data('case-a'));await a;assert.match(f.c.view(),/case-b/);assert.doesNotMatch(f.c.view(),/sha-case-a/);
});
test('source text is escaped before rendering',async()=>{
 const f=fixture((t,a)=>{if(t.endsWith('_get')){const d=data(a.case_id);d.sources[0].label='<img src=x onerror=bad()>';return d;}});await f.c.enter('case-a');const h=f.c.view();assert.match(h,/&lt;img/);assert.doesNotMatch(h,/<img src=x/);
});
test('review defaults to hold and refuses client-side trial without prerequisites',async()=>{
 const f=fixture();await f.c.enter('case-a');await f.c.action('review-new',{dataset:{}});
 f.c.input({dataset:{peField:'review.reason'},value:'等待样品和需求资料'});await f.c.action('review-save',{dataset:{}});
 const call=f.calls.find(r=>r.tool.endsWith('_review_save'));assert.equal(call.args.payload.decision,'hold');assert.equal(Object.keys(call.args.payload.checks).length,6);
});
test('unknown outcome freezes submitted source fields until reconciliation',async()=>{
 const f=fixture((t)=>{if(t.endsWith('_source_save'))throw Error('request_outcome_unknown');});await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});
 f.c.input({dataset:{peField:'label'},value:'提交前值'});await f.c.action('source-save',{dataset:{}});
 f.c.input({dataset:{peField:'label'},value:'结果未知后改值'});assert.match(f.c.view(),/提交前值/);assert.doesNotMatch(f.c.view(),/结果未知后改值/);assert.match(f.c.view(),/核对保存结果/);
});
test('successful save releases controls and permits another edit',async()=>{
 const f=fixture();await f.c.enter('case-a');
 for(const text of ['first','second']){
  await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});f.c.input({dataset:{peField:'notes'},value:text});await f.c.action('source-save',{dataset:{}});
 }
 const saves=f.calls.filter(x=>x.tool.endsWith('_source_save'));assert.equal(saves.length,2);assert.equal(saves[1].args.payload.notes,'second');
});
test('same-case refresh during save does not strand mutation controls',async()=>{
 let release,saveCount=0;const f=fixture((t)=>{if(t.endsWith('_source_save')&&++saveCount===1)return new Promise(r=>release=r);});
 await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});f.c.input({dataset:{peField:'notes'},value:'one'});
 const saving=f.c.action('source-save',{dataset:{}});await f.c.enter('case-a',{force:true});release({entry:{id:sourceRow.id}});await saving;
 await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});f.c.input({dataset:{peField:'notes'},value:'two'});await f.c.action('source-save',{dataset:{}});
 assert.equal(f.calls.filter(x=>x.tool.endsWith('_source_save')).length,2);
});
test('conflict can explicitly rebase edited fields while preserving newer untouched fields',async()=>{
 let reads=0,saves=0;const f=fixture((t,a)=>{if(t.endsWith('_get')){const d=data(a.case_id);if(++reads>1){d.dossier_sha256='new-sha';d.sources[0].revision=2;d.sources[0].label='另一人更新的名称';}return d;}if(t.endsWith('_source_save')&&++saves===1)throw Error('evidence_dossier_changed');});
 await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});f.c.input({dataset:{peField:'notes'},value:'我的备注'});
 await f.c.action('source-save',{dataset:{}});await f.c.action('refresh',{dataset:{}});
 assert.match(f.c.view(),/核对差异/);await f.c.action('rebase',{dataset:{}});await f.c.action('source-save',{dataset:{}});
 const calls=f.calls.filter(x=>x.tool.endsWith('_source_save'));assert.equal(calls[1].args.expected_dossier_sha256,'new-sha');assert.equal(calls[1].args.expected_revision,2);assert.equal(calls[1].args.payload.label,'另一人更新的名称');assert.equal(calls[1].args.payload.notes,'我的备注');
});
test('editing URL list preserves roles of unchanged generated/document links',async()=>{
 const f=fixture((t,a)=>{if(t.endsWith('_get')){const d=data(a.case_id);d.sources[0].images=[{url:'https://example.com/ai.png',media_id:'',label:'AI示意',role:'generated'}];return d;}});
 await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});
 f.c.input({dataset:{peField:'image_links'},value:'https://example.com/ai.png\nhttps://example.com/new.png'});await f.c.action('source-save',{dataset:{}});
 const images=f.calls.find(x=>x.tool.endsWith('_source_save')).args.payload.images;assert.equal(images[0].role,'generated');assert.equal(images[1].role,'original');
});
test('image reads restart on refreshed generation and the old result cannot overwrite',async()=>{
 const pending=[];let imageCalls=0;const f=fixture((t,a)=>{if(t.endsWith('_get')){const d=data(a.case_id);d.sources[0].images=[{url:'',media_id:'image-a',label:'原图',role:'original'}];return d;}if(t.endsWith('_image')){imageCalls++;return new Promise(r=>pending.push(r));}});
 const node={dataset:{entry:sourceRow.id,index:'0'},innerHTML:'',textContent:''};f.document.querySelectorAll=()=>[node];f.document.getElementById=()=>node;
 await f.c.enter('case-a');f.c.afterRender();await f.c.enter('case-a',{force:true});f.c.afterRender();assert.equal(imageCalls,2);
 const result={status:'archived',mime:'image/png',content_base64:'b3JpZw==',next_offset:null};pending[1](result);await new Promise(r=>setTimeout(r,0));assert.match(node.innerHTML,/<img/);const current=node.innerHTML;pending[0](result);await new Promise(r=>setTimeout(r,0));assert.equal(node.innerHTML,current);f.c.dispose();
});

test('unchanged save with unknown receipt remains pending across navigation',async()=>{
 const f=fixture(t=>{if(t.endsWith('_source_save'))throw Error('request_outcome_unknown');});
 await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});await f.c.action('source-save',{dataset:{}});
 assert.equal(f.c.hasUnsavedChanges(),true);const count=f.calls.length;await f.c.enter('case-b');assert.equal(f.calls.length,count);assert.match(f.c.view(),/case-a/);
});
test('active mutation remains guarded after explicit editor discard, then settles',async()=>{
 let finish;const f=fixture(t=>t.endsWith('_source_save')?new Promise(r=>finish=r):undefined);
 await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});f.c.input({dataset:{peField:'notes'},value:'pending'});
 const pending=f.c.action('source-save',{dataset:{}});assert.equal(f.c.hasActiveMutation(),true);f.c.discardChanges();assert.equal(f.c.hasActiveMutation(),true);await f.c.enter('case-b');
 finish({entry:{id:sourceRow.id}});await pending;assert.equal(f.c.hasActiveMutation(),false);await f.c.enter('case-b');assert.match(f.c.view(),/case-b/);
});


test('private image previews use the existing data-image policy rather than blob image URLs',async()=>{
 const f=fixture((t,a)=>{if(t.endsWith('_get')){const d=data(a.case_id);d.sources[0].images=[{url:'',media_id:'image-a',label:'原图',role:'original'}];return d;}if(t.endsWith('_image'))return {status:'archived',mime:'image/png',content_base64:'b3JpZw==',next_offset:null};});
 const node={dataset:{entry:sourceRow.id,index:'0'},innerHTML:''};f.document.querySelectorAll=()=>[node];f.document.getElementById=()=>node;
 await f.c.enter('case-a');f.c.afterRender();await new Promise(r=>setTimeout(r,0));assert.match(f.c.view(),/src="data:image\/png;base64,/);assert.doesNotMatch(f.c.view(),/src="blob:/);f.c.dispose();
});


test('product switch rechecks an evidence mutation started during its awaited reads',async()=>{
  let finishSave;
  const f=fixture(tool=>tool.endsWith('_source_save')?new Promise(resolve=>finishSave=resolve):undefined);
  await f.c.enter('case-a');

  const parentSource=fs.readFileSync(new URL('../../web/product-workspace-ui.js',import.meta.url),'utf8');
  const reload=parentSource.slice(parentSource.indexOf('  async function reload('),parentSource.indexOf('  function selectTab('));
  assert.match(reload,/async function reload/);
  let finishProductRead;
  const s={id:'case-a',data:{},tab:'evidence',items:[],edits:{},dirty:new Set(),researchTaskId:'',researchSequence:0,generation:0};
  const context=vm.createContext({
    s,evidence:f.c,
    api:async tool=>tool==='commerce_workspace_list'?{items:[{id:'case-b'}]}:new Promise(resolve=>finishProductRead=resolve),
    render(){},modelContext:()=>({}),researchContext:{task:()=>'',artifact(){}},
    tabs:{evidence:'证据'},bridged:true,embedded:true,reactHost:false,
    reportResearchSelection(){},enrichIdentity(){},message:error=>String(error),
    studio:{},catalog:{},hostRefreshDeferred:false,
    hasPendingProductEdits:()=>f.c.hasUnsavedChanges(),
  });
  vm.runInContext(reload,context);
  const switching=vm.runInContext("reload({select:'case-b',clearEditors:true})",context);
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(typeof finishProductRead,'function');

  // A's existing evidence controls remain usable while the parent awaits B.
  await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});
  const saving=f.c.action('source-save',{dataset:{}});
  assert.equal(f.c.hasActiveMutation(),true);
  finishProductRead({case:{id:'case-b'},forms:{view:{payload:{tab:'evidence'}}}});
  let result;
  try{
    result=await switching;
    assert.equal(s.id,'case-a','B must not replace the parent while a new A evidence mutation is active');
    assert.match(f.c.view(),/data-pe-case="case-a"/);
  }finally{
    finishSave({entry:{id:sourceRow.id}});
    await saving;
    f.c.dispose();
  }
});
test('origin link requests use recorded case/source/index and preserve the workspace',async()=>{
 const f=fixture(t=>t.endsWith('_origin_open')?{status:'requested'}:undefined);await f.c.enter('case-a');
 await f.c.action('origin-open',{dataset:{entry:sourceRow.id,sourceSha:sourceRow.sha256,index:'-1'}});
 const r=f.calls.find(x=>x.tool.endsWith('_origin_open'));assert.equal(r.args.case_id,'case-a');assert.equal(r.args.entry_id,sourceRow.id);assert.equal(r.args.expected_entry_sha256,sourceRow.sha256);assert.equal(r.args.index,-1);assert.equal('url'in r.args,false);assert.match(f.c.view(),/已请求/);assert.match(f.c.view(),/data-pe-case="case-a"/);
});

// Actual submission and formatter contracts for the integrated evidence surface.
test('empty source submit identifies each required field without sending a write',async()=>{
 const f=fixture();let focused='';f.document.getElementById=id=>({focus(){focused=id;}});
 await f.c.enter('case-a');await f.c.action('source-new');await f.c.action('source-save');
 assert.equal(f.calls.filter(x=>x.tool.endsWith('_source_save')).length,0);assert.equal(focused,'pe-label');
 f.c.input({dataset:{peField:'label'},value:'new source'});await f.c.action('source-save');
 assert.equal(f.calls.filter(x=>x.tool.endsWith('_source_save')).length,0);assert.equal(focused,'pe-url');
 f.c.input({dataset:{peField:'url'},value:'https://detail.1688.com/offer/123.html'});await f.c.action('source-save');
 assert.equal(f.calls.filter(x=>x.tool.endsWith('_source_save')).length,1);
});
test('empty review reason focuses its field and preserves the six judgments',async()=>{
 const f=fixture();let focused='';f.document.getElementById=id=>({focus(){focused=id;}});
 await f.c.enter('case-a');await f.c.action('review-new');await f.c.action('review-save');
 assert.equal(f.calls.filter(x=>x.tool.endsWith('_review_save')).length,0);assert.equal(focused,'pe-review-reason');
 f.c.input({dataset:{peField:'review.reason'},value:'hold for evidence'});await f.c.action('review-save');
 assert.equal(Object.keys(f.calls.find(x=>x.tool.endsWith('_review_save')).args.payload.checks).length,6);
});
test('associated project headings use the catalog identity formatter with all sibling records',async()=>{
 let seen;const f=fixture(undefined,{formatProjectLabel:(p,all)=>{seen={p,all};return 'identified project';}});
 await f.c.enter('case-a');assert.match(f.c.view(),/identified project/);assert.equal(seen.p.id,'project-a');assert.equal(seen.all.length,1);
});
test('opening another editor removes stale success and validation notices',async()=>{
 const f=fixture();await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});
 await f.c.action('source-save');assert.match(f.c.view(),/已保存当前商品的新版本/);
 await f.c.action('review-new');assert.doesNotMatch(f.c.view(),/已保存当前商品的新版本/);
});

test('date validation feedback uses the domain date error and retains the source input',async()=>{
 const f=fixture(t=>{if(t.endsWith('_source_save'))throw Error('evidence_invalid_date');});
 await f.c.enter('case-a');await f.c.action('source-edit',{dataset:{entry:sourceRow.id}});
 f.c.input({dataset:{peField:'observed_at'},value:'2026-11-17 12:00'});await f.c.action('source-save');
 assert.match(f.c.view(),/含时区的有效日期/);assert.match(f.c.view(),/2026-11-17 12:00/);assert.equal(f.c.hasUnsavedChanges(),true);
});
