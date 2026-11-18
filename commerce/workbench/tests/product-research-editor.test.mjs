import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const context=vm.createContext({window:{},JSON});
vm.runInContext(await readFile('../web/product-research-editor.js','utf8'),context);
const model=context.window.CommerceProductResearchEditor.model;
const plain=value=>JSON.parse(JSON.stringify(value));
const sha=letter=>letter.repeat(64);
const spec={record:{version:'research-v1',platform:'ozon',market:'',fields:{title:{original:'',zh:'',reviewed:false}}},fields:[{key:'title',label:'Title',required:true,translatable:true},{key:'description',label:'Description',required:true,translatable:true}]};
function snapshot(){return {name:'Synthetic product',case:{id:'case-a',scope:{platform:'ozon',market:'RU',sku:'SYN',row_key:'row-a'}},source_sha256:sha('a'),artifacts:{research:{id:'original-artifact',sha256:sha('b'),intact:true,payload:{record:{version:'research-v1',platform:'ozon',market:'RU',language:'en',source_url:'https://example.invalid/original',captured_at:'2026-11-17T01:00:00Z',raw_excerpt:'Original 10 ml',fields:{title:{original:'Original 10 ml',zh:'原文 10 ml',reviewed:true,kind:'source_statement',source_url:'',locator:'line 1',translation:{original_sha256:sha('c'),model_output:'Machine output',model_output_sha256:sha('d')}},description:{original:'Description',zh:'描述',reviewed:true,kind:'source_statement',source_url:'',locator:'line 2'}}}}}}};}
const draft=()=>model.createDraft(snapshot(),'',spec,'key-original');

test('explicit research snapshots are read only even when they happen to be current',()=>{
 const current=snapshot();current.research_context={selected_explicitly:true,is_current_artifact:true};
 assert.throws(()=>model.createDraft(current,'task-a',spec,'key'),/snapshot_read_only/);
 assert.throws(()=>model.createDraft(current,'',spec,'key'),/snapshot_read_only/);
 current.research_context.selected_explicitly=false;
 assert.equal(model.createDraft(current,'',spec,'key').artifactId,'original-artifact');
 current.artifacts.research.intact=false;
 assert.throws(()=>model.createDraft(current,'',spec,'key'),/artifact_changed/);
});

test('editing text or evidence revokes only that field review and does not silently resign translation provenance',()=>{
 const d=draft(),original=plain(d.record.fields.title.translation);
 model.editField(d,'title','original','Changed 12 ml','key-changed');
 assert.equal(d.record.fields.title.reviewed,false);
 assert.equal(d.record.fields.description.reviewed,true);
 assert.deepEqual(plain(d.record.fields.title.translation),original);
 assert.equal(d.base.fields.title.original,'Original 10 ml');
 assert.equal(d.key,'key-changed');assert.equal(d.dirty,true);
 model.editField(d,'title','zh','更改 12 ml','key-zh');
 assert.equal(d.record.fields.title.reviewed,false);
 model.editField(d,'title','reviewed',true,'key-reviewed');
 assert.equal(d.record.fields.title.reviewed,true);
 model.manualRevision(d,'title','key-manual');
 assert.equal(d.record.fields.title.translation,undefined);
 assert.deepEqual(plain(d.base.fields.title.translation),original);
 assert.equal(d.record.fields.title.reviewed,false);
});

test('a changed common source revokes review while evidence notes do not certify anything',()=>{
 const d=draft();model.editCommon(d,'source_url','https://example.invalid/new-source','key-source');
 assert.ok(Object.values(d.record.fields).every(field=>!field.reviewed));
 model.editCommon(d,'evidence_note','Caller supplied, unverified','key-note');
 assert.ok(Object.values(d.record.fields).every(field=>!field.reviewed));
 model.editField(d,'title','zh','','key-empty');
 assert.throws(()=>model.editField(d,'title','reviewed',true,'key-invalid-review'),/review_requires_text/);
});

test('save DTO freezes the editor-open source and head and never invents an unguarded fallback',()=>{
 const d=draft();model.editField(d,'title','zh','人工校对','key-edited');
 const args=model.saveArguments(d);
 assert.deepEqual(Object.keys(args),['case_id','record','expected_source_sha256','expected_artifact_id','idempotency_key']);
 assert.equal(args.expected_source_sha256,sha('a'));assert.equal(args.expected_artifact_id,'original-artifact');
 d.request=plain(args);d.unknown=true;
 assert.throws(()=>model.editField(d,'title','zh','Should not replace pending request','new-key'),/save_pending/);
 assert.equal(d.request.idempotency_key,'key-edited');
 assert.equal(d.request.record.fields.title.zh,'人工校对');
});

test('saving success requires both the exact receipt and the exact current readback',()=>{
 const args=model.saveArguments(draft());
 const receipt={schema:'workspace-research-save-v1',case_id:'case-a',artifact_id:'saved-artifact',artifact_sha256:sha('e'),source_sha256:sha('f'),previous_source_sha256:sha('a'),previous_artifact_id:'original-artifact',external_execution_allowed:false,publication_ready:false};
 assert.equal(model.validateReceipt(receipt,args),receipt);
 assert.throws(()=>model.validateReceipt({...receipt,previous_source_sha256:sha('b')},args),/receipt_invalid/);
 const current=snapshot();current.source_sha256=sha('f');current.artifacts.research={id:'saved-artifact',sha256:sha('e'),intact:true,payload:{record:{}}};
 assert.equal(model.matchesReadback(current,receipt),true);
 assert.equal(model.matchesReadback({...current,source_sha256:sha('a')},receipt),false);
 current.artifacts.research.id='a-later-peer-revision';assert.equal(model.matchesReadback(current,receipt),false);
});

test('an explicit rebase can retain local input but never silently updates the old draft base',()=>{
 const d=draft();model.editField(d,'title','zh','Local unsaved translation','local-key');
 const latest=snapshot();latest.source_sha256=sha('f');latest.artifacts.research.id='peer-artifact';latest.artifacts.research.payload.record.fields.title.zh='Peer translation';
 const retained=model.rebase(d,latest,true,'rebase-key');
 assert.equal(retained.record.fields.title.zh,'Local unsaved translation');
 assert.equal(retained.base.fields.title.zh,'Peer translation');
 assert.equal(retained.source,sha('f'));assert.equal(retained.artifactId,'peer-artifact');
 assert.equal(d.source,sha('a'));assert.equal(d.artifactId,'original-artifact');
 const adopted=model.rebase(d,latest,false,'adopt-key');assert.equal(adopted.record.fields.title.zh,'Peer translation');assert.equal(adopted.dirty,false);
});

function controller({saveError=null,laterPeer=false,capability=true,original:suppliedOriginal,holdImport=false,stopSave=false,holdFirstCheck=false,holdFirstSave=false,holdReadback=false}={}){
 const requests=[],events={},dirty=[],saved=[],views=[];
 const original=suppliedOriginal||snapshot();let serial=0,saveCount=0,checkCount=0,releaseImport,releaseFirstCheck,rejectFirstSave,releaseReadback,currentData=original;
 const receipt={schema:'workspace-research-save-v1',case_id:'case-a',artifact_id:'saved-artifact',artifact_sha256:sha('e'),source_sha256:sha('f'),previous_source_sha256:sha('a'),previous_artifact_id:'original-artifact',external_execution_allowed:false,publication_ready:false};
 const readback=snapshot();readback.source_sha256=sha('f');readback.artifacts.research.id=laterPeer?'peer-after-save':'saved-artifact';readback.artifacts.research.sha256=sha('e');readback.artifacts.research.payload.record.fields.title.original='Latest current title';
 const document={activeElement:null,querySelector:selector=>selector==='.dialog .pre-editor'?{}:null,getElementById:()=>null,addEventListener:(name,callback)=>(events[name]||=[]).push(callback)};
 const fixture=vm.createContext({window:{},document,crypto:{randomUUID:()=>`key-${++serial}`},JSON});
 return readFile('../web/product-research-editor.js','utf8').then(source=>{
  vm.runInContext(source,fixture);
  const ui={escape:value=>String(value??''),button:({label})=>`<button>${label}</button>`,field:(label,input)=>`<label>${label}${input}</label>`,input:()=>'<input>',select:()=>'<select>',alert:text=>`<aside>${text}</aside>`};
  const editor=fixture.window.CommerceProductResearchEditor({ui,getCurrent:()=>({data:currentData,taskId:''}),showDialog:(_title,body,actions)=>views.push(body+actions),closeDialog(){},onDirty:value=>dirty.push(value),onSaved:value=>saved.push(value),api:async(tool,args)=>{
   requests.push({tool,args:plain(args)});
   if(tool==='commerce_workspace_research_capabilities'){if(!capability)throw Error('unknown_tool');return {schema:'workspace-research-save-v1',save_tool:'commerce_workspace_research_save',atomic_source_and_head:true,idempotent_receipt:true,external_execution_allowed:false};}
   if(tool==='commerce_collection_template')return spec;
   if(tool==='commerce_collection_check'){checkCount++;if(holdFirstCheck&&checkCount===1)return new Promise(resolve=>releaseFirstCheck=()=>resolve({status:'HOLD',issues:[]}));if(holdImport&&checkCount===2)return new Promise(resolve=>releaseImport=resolve);return {status:'HOLD',issues:[{field:'description',message:'Description required'}]};}
   if(tool==='commerce_workspace_research_save'){saveCount++;if(stopSave)throw Error('invalid_synthetic_stop');if(holdFirstSave&&saveCount===1)return new Promise((_resolve,reject)=>rejectFirstSave=()=>reject(Error('commerce_service_unavailable')));if(saveError&&saveCount===1)throw Error(saveError);return receipt;}
   if(tool==='commerce_workspace_get'){if(holdReadback)return new Promise(resolve=>releaseReadback=()=>resolve(readback));return readback;}
   throw Error('unexpected tool');
  }});
  const event=(id,extra={})=>({target:{id,dataset:{},closest:()=>({}),...extra},stopImmediatePropagation(){}});
  return {editor,requests,dirty,saved,views,original,events,event,setCurrent:value=>currentData=value,releaseImport:()=>releaseImport({status:'HOLD',issues:[]}),releaseFirstCheck:()=>releaseFirstCheck(),rejectFirstSave:()=>rejectFirstSave(),releaseReadback:()=>releaseReadback(),input(part,value){const target={closest:()=>({}),dataset:{preField:part},type:'text',value};events.input[0]({target,stopImmediatePropagation(){}});}};
 });
}

test('the controller saves only through confirmed CAS capability and adopts only verified readback',async()=>{
 const f=await controller();await f.editor.open(f.original);f.input('zh','Local revised translation');
 await f.editor.action('save');
 const write=f.requests.find(row=>row.tool==='commerce_workspace_research_save');
 assert.equal(write.args.expected_artifact_id,'original-artifact');assert.equal(write.args.record.fields.title.zh,'Local revised translation');
 assert.equal(write.args.record.fields.title.reviewed,false);
 assert.equal(f.saved.length,1);assert.equal(f.editor.isOpen(),false);assert.equal(f.dirty.at(-1),false);
 assert.ok(!f.requests.some(row=>row.tool==='commerce_organization_record'));
});

test('unknown outcome retains frozen arguments; an explicit retry reuses the same key and payload',async()=>{
 const f=await controller({saveError:'commerce_service_unavailable'});await f.editor.open(f.original);f.input('zh','Frozen local translation');
 await f.editor.action('save');assert.equal(f.editor.hasPendingChanges(),true);assert.equal(f.saved.length,0);
 f.input('zh','This must not replace the original request');
 await f.editor.action('retry');
 const writes=f.requests.filter(row=>row.tool==='commerce_workspace_research_save');
 assert.equal(writes.length,2);assert.deepEqual(writes[0].args,writes[1].args);
 assert.equal(writes[1].args.record.fields.title.zh,'Frozen local translation');assert.equal(f.saved.length,1);
});

test('a later peer revision never gets adopted as the save result and dirty close needs explicit discard',async()=>{
 const f=await controller({laterPeer:true});await f.editor.open(f.original);f.input('zh','Unsaved local text');
 let left=0;assert.equal(f.editor.requestLeave(()=>left++),false);assert.equal(left,0);assert.match(f.views.at(-1),/当前输入尚未保存/);
 await f.editor.action('keep-editing');await f.editor.action('save');
 assert.equal(f.saved.length,0);assert.equal(f.editor.isOpen(),true);assert.match(f.views.at(-1),/当前商品已有后续更新/);
 f.editor.requestLeave(()=>left++);await f.editor.action('discard');assert.equal(left,1);assert.equal(f.editor.isOpen(),false);
});

test('an older backend remains editable locally but cannot fall back to the unguarded writer',async()=>{
 const f=await controller({capability:false});await f.editor.open(f.original);f.input('zh','Retained draft');await f.editor.action('save');
 assert.equal(f.editor.hasPendingChanges(),true);assert.equal(f.saved.length,0);
 assert.ok(!f.requests.some(row=>row.tool==='commerce_workspace_research_save'||row.tool==='commerce_organization_record'));
 assert.match(f.views.at(-1),/暂不能保存/);
});

test('research cards distinguish visible-field proofreading from whole-research gates and explicit snapshots',async()=>{
 const source=await readFile('../web/product-workspace-ui.js','utf8');
 const code=source.slice(source.indexOf('  function researchView('),source.indexOf('  function supplyView('));
 const data=snapshot();data.stages=[{id:'S1',status:'HOLD'},{id:'S5',status:'HOLD'}];data.research_context={selected_explicitly:false};
 const ctx=vm.createContext({s:{data,researchTaskId:'',researchLoading:false,researchContextError:''},window:{},researchContext:{artifact:()=>data.artifacts.research},researchControls:()=>'',esc:value=>String(value||''),stamp:value=>value,ui:{badge:value=>`[${value}]`},section:(title,body,actions='')=>title+body+actions,btn:(label,action)=>`<button data-action="${action}">${label}</button>`,supplyView:()=>'',alert:value=>value,gaps:()=>''});
 vm.runInContext(code+';this.researchView=researchView;',ctx);
 const overview=ctx.researchView(true);assert.match(overview,/2项内容已校对/);assert.match(overview,/整体研究仍有未关闭项/);assert.doesNotMatch(overview,/整体资料检查通过/);
 assert.match(ctx.researchView(false),/research-source/);
 data.research_context.selected_explicitly=true;assert.doesNotMatch(ctx.researchView(false),/research-source/);
});

test('valid sparse HOLD records open and edit without changing the original saved baseline',async()=>{
 const original=snapshot(),minimal={version:'research-v1',platform:'ozon',market:'RU'};
 original.artifacts.research.payload.record=minimal;
 const f=await controller({original});await assert.doesNotReject(f.editor.open(original));
 assert.match(f.views.at(-1),/原文或明确的缺失说明/);
 f.input('original','A newly supplied title');
 assert.equal(f.editor.hasPendingChanges(),true);
 await f.editor.action('save');
 assert.equal(f.requests.find(row=>row.tool==='commerce_workspace_research_save').args.record.fields.title.original,'A newly supplied title');
 assert.equal(Object.hasOwn(minimal,'fields'),false);
 const d=model.createDraft(original,'',spec,'minimal-key');
 assert.deepEqual(plain(d.record.fields),{});assert.equal(Object.hasOwn(d.base,'fields'),false);
 for(const fields of [null,[],0,'broken']){
  const damaged=snapshot();damaged.artifacts.research.payload.record.fields=fields;
  assert.throws(()=>model.createDraft(damaged,'',spec,'invalid-key'),/invalid_research/);
 }
 for(const record of [null,[],0,'broken']){const damaged=snapshot();damaged.artifacts.research.payload.record=record;assert.throws(()=>model.createDraft(damaged,'',spec,'invalid-record'),/invalid_research/);}
});

test('a delayed JSON check cannot overwrite a newly adopted draft or inherit its new CAS base',async()=>{
 const f=await controller({holdImport:true,stopSave:true});await f.editor.open(f.original);
 const imported={case_id:'case-a',kind:'research',payload:{sku:'SYN',row_key:'row-a',record:plain(f.original.artifacts.research.payload.record)}};
 imported.payload.record.fields.title.original='Imported stale title';
 f.events.change[0](f.event('pre-import',{files:[{size:100,text:async()=>JSON.stringify(imported)}]}));
 await new Promise(setImmediate);
 await f.editor.action('latest');f.events.input[0](f.event('pre-rebase-confirm',{checked:true}));await f.editor.action('adopt-latest');
 assert.match(f.views.at(-1),/Latest current title/);
 f.releaseImport();await new Promise(setImmediate);await new Promise(setImmediate);
 assert.match(f.views.at(-1),/Latest current title/);assert.doesNotMatch(f.views.at(-1),/Imported stale title/);
 await f.editor.action('save');const write=f.requests.find(row=>row.tool==='commerce_workspace_research_save');
 assert.equal(write.args.expected_source_sha256,sha('f'));assert.equal(write.args.record.fields.title.original,'Latest current title');
});

test('JSON sparse records use the same legal-default normalization without repairing malformed fields',async()=>{
 const f=await controller();await f.editor.open(f.original);
 const imported={case_id:'case-a',kind:'research',payload:{sku:'SYN',row_key:'row-a',record:{version:'research-v1',platform:'ozon',market:'RU'}}};
 f.events.change[0](f.event('pre-import',{files:[{size:100,text:async()=>JSON.stringify(imported)}]}));await new Promise(setImmediate);await new Promise(setImmediate);
 assert.equal(f.editor.hasPendingChanges(),true);assert.match(f.views.at(-1),/原文或明确的缺失说明/);
 await f.editor.action('save');assert.deepEqual(f.requests.find(row=>row.tool==='commerce_workspace_research_save').args.record.fields,{});
 const g=await controller();await g.editor.open(g.original);imported.payload.record.fields=null;
 g.events.change[0](g.event('pre-import',{files:[{size:100,text:async()=>JSON.stringify(imported)}]}));await new Promise(setImmediate);await new Promise(setImmediate);
 assert.match(g.views.at(-1),/输入格式未通过校验/);assert.match(g.views.at(-1),/Original 10 ml/);
});

test('closing and reopening the editor or changing the current case invalidates old import replies',async()=>{
 for(const reopen of [true,false]){
  const f=await controller({holdImport:true});await f.editor.open(f.original);
  const imported={case_id:'case-a',kind:'research',payload:{sku:'SYN',row_key:'row-a',record:plain(f.original.artifacts.research.payload.record)}};imported.payload.record.fields.title.original='Old dialog import';
  f.events.change[0](f.event('pre-import',{files:[{size:100,text:async()=>JSON.stringify(imported)}]}));await new Promise(setImmediate);
  if(reopen){await f.editor.action('close');await f.editor.open(f.original);}else{const other=snapshot();other.case.id='another-current-case';f.setCurrent(other);}
  f.releaseImport();await new Promise(setImmediate);await new Promise(setImmediate);
  assert.doesNotMatch(f.views.at(-1),/Old dialog import/);assert.ok(!f.requests.some(row=>row.tool==='commerce_workspace_research_save'));
 }
});

test('active mutation spans dispatch, unknown result and same-key retry until the exact readback is confirmed',async()=>{
 const f=await controller({holdFirstSave:true,holdReadback:true});await f.editor.open(f.original);
 assert.equal(f.editor.hasActiveMutation(),false);f.input('zh','Mutation-bound text');assert.equal(f.editor.hasActiveMutation(),false);
 const saving=f.editor.action('save');await new Promise(setImmediate);
 assert.equal(f.editor.hasActiveMutation(),true);assert.equal(f.requests.filter(row=>row.tool==='commerce_workspace_research_save').length,1);
 f.rejectFirstSave();await saving;assert.equal(f.editor.hasActiveMutation(),true);assert.equal(f.saved.length,0);
 const retry=f.editor.action('retry');await new Promise(setImmediate);
 assert.equal(f.editor.hasActiveMutation(),true);assert.equal(f.saved.length,0);
 const writes=f.requests.filter(row=>row.tool==='commerce_workspace_research_save');assert.deepEqual(writes[0].args,writes[1].args);
 f.releaseReadback();await retry;assert.equal(f.saved.length,1);assert.equal(f.editor.hasActiveMutation(),false);assert.equal(f.editor.isOpen(),false);
});

test('initial loading and validation busy states never claim an active mutation',async()=>{
 const f=await controller({holdFirstCheck:true});
 assert.equal(f.editor.hasActiveMutation(),false);
 const opening=f.editor.open(f.original);assert.equal(f.editor.hasActiveMutation(),false);await new Promise(setImmediate);
 assert.equal(f.editor.hasPendingChanges(),true);assert.equal(f.editor.hasActiveMutation(),false);
 f.releaseFirstCheck();await opening;assert.equal(f.editor.hasActiveMutation(),false);
 const checking=f.editor.action('check');assert.equal(f.editor.hasActiveMutation(),false);await checking;
 assert.equal(f.editor.hasActiveMutation(),false);
});
