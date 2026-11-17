import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const root = new URL('../../', import.meta.url);
const body = { schema:'commerce-order-support-context-v1', scope:{demo:true,platform:'ozon',store_id:'synthetic-store',market:'RU'},
  order:{id:'SYN-1:1',order_id:'SYN-1',line_id:'1',source_sha256:'a'.repeat(64),record_sha256:'b'.repeat(64),import_batch_id:'import-synthetic',batch_sha256:'d'.repeat(64)},
  source:{data_source:'operator_csv_import_unverified',observed_at:null},context_sha256:'c'.repeat(64) };
const prepared = () => ({context:structuredClone(body),sources:[],external_execution_allowed:false});
const scope = {platform:'ozon',store_ref:'synthetic-store',subject_ref:'SYN-1'};
const conversation = {id:'conv',version:1,sha256:'1'.repeat(64),fresh:true,document:{kind:'conversation',synthetic:true,scope,label:'Synthetic conversation',records:[{id:'message',role:'buyer',text:'Synthetic question'}]}};
const facts = {id:'facts',version:3,sha256:'2'.repeat(64),fresh:true,document:{kind:'facts',synthetic:true,scope,label:'Synthetic facts',records:[{key:'order_ref',value:'SYN-1'},{key:'market',value:'RU'},{key:'policy_ref',value:'synthetic-policy'}]}};
const summary = s => ({...s,...s.document,record_count:s.document.records.length,origin_ref:'private-export:synthetic.json',observed_at:'2026-11-17T00:00:00Z'});
async function harness(extra={}) {
  const listeners={},calls=[],elements={},notices=[],modals=[];let dialog=false,saved=null;
  const window={dispatchEvent(){},matchMedia:()=>({matches:false,addEventListener(){}})};
  const document={documentElement:{dataset:{}},addEventListener:(type,fn)=>(listeners[type]||=[]).push(fn),querySelector:()=>dialog?{}:null,querySelectorAll:()=>[],getElementById:id=>elements[id]||null};
  const context=vm.createContext({window,document,CustomEvent:class{},setTimeout(){},crypto:{randomUUID:()=> 'synthetic-key'}});
  for(const path of ['ui/kit.js','web/businessforms-ui.js','web/order-support-context.js','web/business-ui.js']) vm.runInContext(await readFile(new URL(path,root),'utf8'),context);
  const api=async(name,args)=>{calls.push([name,structuredClone(args)]);if(extra.api)return extra.api(name,args);if(name==='commerce_business_list')return {sources:[conversation,facts].map(summary).concat(summary({...conversation,id:'other',document:{...conversation.document,scope:{...scope,store_ref:'other-store'}}})),drafts:[]};if(name==='commerce_business_source_get')return structuredClone(args.source_id==='conv'?conversation:facts);if(name==='commerce_business_template')return {required_fields:{conversation_ref:'text',reply:'reply',policy_ref:'text'}};if(name==='commerce_order_support_draft'){saved={id:'saved-synthetic-draft',draft:{kind:'support',content:args.content,scope,synthetic:true,sources:args.source_refs,draft_sha256:'e'.repeat(64)},preflight:{status:'current',missing_fields:[],invalid_fields:[],uncited_fields:[],store_scope_known:true,ready_for_local_review:true},status:'ready_for_review',receipts:[],order_context:{context:args.context,status:'current',reason:null}};return structuredClone(saved);}if(name==='commerce_business_get'&&saved)return structuredClone(saved);throw Error('Unexpected tool '+name);};
  const app=window.CommerceBusiness({api,esc:window.CommerceUI.escape,repaint(){},isActive:()=>true,toast:t=>notices.push(t),modal:(_title,html)=>{dialog=true;modals.push(html);},closeModal:()=>{dialog=false;}});
  const emit=async(type,target)=>{target.matches||=()=>false;for(const listener of listeners[type]||[])await listener({target});};
  const action=name=>emit('click',{closest:()=>({dataset:{businessAction:name}})});
  const choose=id=>emit('change',{checked:true,dataset:{businessSource:id},matches:()=>true});
  return {window,app,calls,elements,notices,modals,emit,action,choose,setDialog:value=>dialog=value,getDialog:()=>dialog};
}

test('prepared order pins exact scope and mode, filters other stores, and creates no buyer conversation',async()=>{
  const h=await harness();await h.app.enterOrderSupport(prepared());
  const html=h.app.view('support');
  assert.match(html,/订单客服接续/);assert.match(html,/SYN-1/);assert.match(html,/import-synthetic/);
  assert.match(html,/<select[^>]*id="business-mode"[^>]*disabled/);
  assert.match(html,/<select[^>]*id="business-source-scope"[^>]*disabled/);
  assert.doesNotMatch(html,/data-business-source="other"/);
  assert.deepEqual(h.calls.map(([name])=>name),['commerce_business_list']);
  await h.emit('change',{id:'business-mode',value:'real'});
  assert.match(h.notices.at(-1),/范围不一致/);assert.equal(h.calls.length,1);
  await h.emit('change',{id:'business-source-scope',value:'forged'});
  assert.match(h.app.view('support'),/订单范围已固定/);
});

test('same-order conversation and facts preserve source versions and typed order context at save',async()=>{
  const h=await harness();await h.app.enterOrderSupport(prepared());await h.choose('conv');await h.choose('facts');
  await h.action('compose');assert.equal(h.modals.length,1);assert.match(h.modals[0],/business-value-conversation_ref[^>]*readonly/);
  h.elements['business-content-advanced']={checked:false};
  h.elements['business-value-conversation_ref']={value:'SYN-1'};
  h.elements['business-value-reply']={value:'Synthetic reply that remains local'};
  h.elements['business-value-policy_ref']={value:'synthetic-policy'};
  h.elements['business-citation-policy_ref']={value:'2'};
  await h.action('draft-save');
  const call=h.calls.find(([name])=>name==='commerce_order_support_draft');assert.ok(call);
  assert.deepEqual(call[1].context,body);assert.deepEqual(call[1].source_refs.map(s=>[s.id,s.version]),[['conv',1],['facts',3]]);
  assert.equal(call[1].content.fields.reply,'Synthetic reply that remains local');assert.equal(h.getDialog(),false);assert.match(h.notices.at(-1),/草稿已保存/);assert.match(h.app.view('support'),/Synthetic reply that remains local/);
  assert.ok(!h.calls.some(([name])=>/send|reply|import/.test(name)));
});

test('source hash rejection retains the exact reply, citation, and editor without closing',async()=>{
  const h=await harness({api:(name,args)=>{
    if(name==='commerce_business_list')return {sources:[conversation,facts].map(summary),drafts:[]};
    if(name==='commerce_business_source_get')return structuredClone(args.source_id==='conv'?conversation:facts);
    if(name==='commerce_business_template')return {required_fields:{conversation_ref:'text',reply:'reply',policy_ref:'text'}};
    if(name==='commerce_order_support_draft')throw Error('order_support_source_changed');
    throw Error(name);
  }});
  await h.app.enterOrderSupport(prepared());await h.choose('conv');await h.choose('facts');await h.action('compose');
  const typed={fields:{conversation_ref:'SYN-1',reply:'Keep this exact synthetic text',policy_ref:'synthetic-policy'},citations:{policy_ref:{source_id:'facts',key:'policy_ref'}}};
  h.elements['business-content-advanced']={checked:true};h.elements['business-content-json']={value:JSON.stringify(typed)};h.elements['business-modal-error']={textContent:''};
  await h.action('draft-save');assert.match(h.elements['business-modal-error'].textContent,/版本已变化/);
  assert.equal(h.elements['business-content-json'].value,JSON.stringify(typed));assert.equal(h.modals.length,1);
  await assert.rejects(h.app.enterOrderSupport(prepared()),/order_support_editor_open/);
});

test('reentering the same prepared snapshot keeps the current explicit source selection',async()=>{
  const h=await harness();await h.app.enterOrderSupport(prepared());await h.choose('conv');
  await h.app.enterOrderSupport(prepared());
  assert.match(h.app.view('support'),/已选 1 条/);
  assert.deepEqual(h.calls.map(([name])=>name),['commerce_business_list','commerce_business_list']);
});

test('missing sources retain the fixed order, and no source is automatically created',async()=>{
  const h=await harness({api:()=>({sources:[],drafts:[]})});await h.app.enterOrderSupport(prepared());
  const html=h.app.view('support');assert.match(html,/此订单暂无匹配资料/);assert.match(html,/ozon · synthetic-store · SYN-1/);assert.doesNotMatch(html,/undefined/);
  assert.deepEqual(h.calls.map(([name])=>name),['commerce_business_list']);
});

test('helper rejects wrong market, stale sources and edited conversation identities',async()=>{
  const h=await harness(),helper=h.window.CommerceOrderSupportContext();
  assert.throws(()=>helper.receive({...prepared(),external_execution_allowed:true}),/invalid_context/);
  const stale=structuredClone(facts);stale.fresh=false;
  assert.throws(()=>helper.selected([conversation,stale],body),/source_stale/);
  const other=structuredClone(facts);other.document.records[1].value='US';
  assert.throws(()=>helper.selected([conversation,other],body),/market_mismatch/);
  assert.throws(()=>helper.request(body,[conversation,facts],{fields:{conversation_ref:'OTHER'},citations:{}}),/order_mismatch/);
});

test('read-only assistant getters keep synthetic mode and exact order hashes without mapping CSV stores to old filters',async()=>{
  const h=await harness();await h.app.enterOrderSupport(prepared());const before=h.calls.length;
  const context=h.app.context(),page=h.app.pageContext();
  assert.equal(context.module,'support');assert.equal(context.demo,true);assert.deepEqual({...context.entity},{kind:'order',id:'SYN-1:1'});
  assert.equal(Object.hasOwn(context,'store_id'),false);assert.equal(Object.hasOwn(context,'store_scope'),false);
  assert.equal(page.demo,true);assert.equal(page.source,'local');assert.equal(page.filters.store_ref,'synthetic-store');assert.equal(Object.hasOwn(page.filters,'store_id'),false);
  assert.equal(page.source_refs.record,body.order.record_sha256);assert.equal(page.source_refs.order,body.order.source_sha256);assert.equal(page.source_refs.order_context,body.context_sha256);assert.equal(page.source_refs.import_batch,body.order.batch_sha256);
  page.filters.store_ref='modified-only-by-caller';context.entity.id='modified-only-by-caller';
  assert.equal(h.app.context().entity.id,'SYN-1:1');assert.equal(h.app.pageContext().filters.store_ref,'synthetic-store');assert.equal(h.calls.length,before);
});

test('unbound real input has no inherited synthetic order identity or source references',async()=>{
  const h=await harness();await h.app.enter('support');const before=h.calls.length;
  assert.equal(h.app.context().demo,false);assert.equal(h.app.context().entity,undefined);assert.equal(h.app.pageContext().demo,false);
  assert.deepEqual({...h.app.pageContext().source_refs},{});assert.deepEqual({...h.app.pageContext().filters},{});assert.equal(h.calls.length,before);
});
