import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import vm from 'node:vm';

const sources=await Promise.all(['../../ui/page-context.js','../../web/copilot-capabilities.js','../../web/copilot-ui.js'].map(file=>readFile(new URL(file,import.meta.url),'utf8')));
const A='store_source_'+'a'.repeat(32),B='store_source_'+'b'.repeat(32);
const scope=id=>({module:'orders',demo:false,store_scope:id});
const page=(id,sha='a'.repeat(64))=>({page:'store-ops',demo:false,source:'local',filters:{scope:id,query:'合成筛选'},source_refs:{store_scope:sha}});
const clone=value=>structuredClone(value);
const canonical=value=>JSON.stringify(value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,value[key]])):value);
const draftKey=context=>'commerce-copilot-draft-v1:new:'+canonical(context);
const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const flush=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate);};
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}

function fixture(initial=scope(A),initialPage=page(A)){
  const handlers=new Map(),storage=new Map(),calls=[],threads=new Map();
  let current=clone(initial),currentPage=clone(initialPage),serial=0,chooseModule,picker;
  const gates={check:null,open:null,send:null};
  const events={addEventListener(name,handler){if(!handlers.has(name))handlers.set(name,new Set());handlers.get(name).add(handler);},removeEventListener(name,handler){handlers.get(name)?.delete(handler);}};
  const document={...events,activeElement:null,querySelector:()=>null,getElementById:()=>null};
  const ui={escape,icon:()=>'',badge:escape,alert:escape,button:({label,action,attrs={}})=>`<button data-action="${escape(action)}" ${Object.entries(attrs).map(([key,value])=>`${key}="${escape(value)}"`).join(' ')}>${escape(label)}</button>`,field:(label,value)=>label+value,input:()=>'',select:()=>'',moduleDetails:id=>({description:id})};
  const window={...events,CommerceUI:ui,innerWidth:1440,innerHeight:900,dispatchEvent(){}};window.parent=window;
  const runtime=vm.createContext({window,document,crypto:{randomUUID},setTimeout,clearTimeout,setInterval:()=>0,clearInterval(){},CustomEvent:class{},localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)}});
  for(const source of sources)vm.runInContext(source,runtime);
  const realCapabilities=window.CommerceCopilotCapabilities;
  // Capture the production controller callback at the real picker boundary.
  // The picker, its prepare/check logic, and the parent all run unmodified.
  window.CommerceCopilotCapabilities=options=>{chooseModule=options.onModule;picker=realCapabilities(options);return picker;};
  async function gate(name){const value=gates[name];gates[name]=null;if(value)await value.promise;}
  const api=async(name,args={})=>{
    calls.push({name,args:clone(args)});
    if(name==='commerce_model_list')return {models:[{id:'project-default',label:'合成固定模型',selectable:true}],default_model_id:'project-default'};
    if(name==='commerce_copilot_list')return {threads:[...threads.values()].map(clone)};
    if(name==='commerce_copilot_get')return clone(threads.get(args.thread_id));
    if(name==='commerce_copilot_capabilities')return {schema:'commerce-copilot-capabilities-v1',modules:['orders','overview','products'].map(id=>({id,label:id})),items:[{id:'mcp:commerce',kind:'mcp',name:'合成共享读取',description:'只读当前范围',selectable:true,status:'available'}],total:1,next_offset:null};
    if(name==='commerce_copilot_capability_check'){
      await gate('check');
      return {capability_ids:args.capability_ids,selection_sha256:'c'.repeat(64),available:true,capabilities:[]};
    }
    if(name==='commerce_copilot_open'){
      const thread={id:'scope-thread-'+(++serial),title:'合成店铺会话',context:clone(args.context),context_sha256:'scope-hash-'+serial,turns:[],model_selection:{model_id:'project-default',available:true,sha256:'d'.repeat(64)}};
      threads.set(thread.id,thread);await gate('open');return clone(thread);
    }
    if(name==='commerce_copilot_send'){
      await gate('send');const thread=threads.get(args.thread_id);
      thread.latest_run={id:'scope-run-'+calls.length,status:'completed',parameters:{page_context:clone(args.page_context)},result:{answer:'合成范围答复',questions:[],proposals:[]}};
      thread.turns.push({id:'scope-turn-'+calls.length,question:args.message,run:clone(thread.latest_run)});return clone(thread);
    }
    throw Error('Unexpected fixture API: '+name);
  };
  let controller;
  controller=window.CommerceCopilot({api,getContext:()=>current,getPageContext:()=>currentPage,isActive:()=>true,inline:true,compact:true,repaint(){controller?.view();},toast(){},modal(){},closeModal(){}});
  const emit=(name,event)=>{for(const handler of handlers.get(name)||[])handler(event);};
  function capability(action,attrs={}){const target={dataset:{copilotCapabilityAction:action,...attrs},closest(selector){return selector==='[data-copilot-capability-action]'?this:null;}};return picker.handleClick({target,preventDefault(){},stopImmediatePropagation(){}});}
  function assertSendStore(call,id,sha){
    const thread=threads.get(call.args.thread_id);
    assert.equal(thread.context.module,'orders');assert.equal(thread.context.store_scope,id);
    assert.equal(call.args.page_context.page,'store-ops');assert.equal(call.args.page_context.filters.scope,id);
    assert.equal(call.args.page_context.source_refs.store_scope,sha);
    assert.equal(call.args.context_sha256,thread.context_sha256);
  }
  return {calls,threads,storage,controller,assertSendStore,
    async open(){controller.open(undefined,{focus:false});controller.view();await flush();},
    choose:module=>chooseModule(module),capability,
    input(value){emit('input',{target:{id:'copilot-message',value,dataset:{}}});},
    send(){emit('keydown',{key:'Enter',ctrlKey:true,target:{id:'copilot-message'},preventDefault(){}});},
    navigate(context,nextPage){current=clone(context);currentPage=clone(nextPage);controller.contextChanged();controller.view();},
    mutatePageVersion(sha){currentPage.source_refs.store_scope=sha;currentPage.filters.query='发送后的新筛选';controller.contextChanged();},
    gate(name){const value=deferred();gates[name]=value;return value;},
    sends:()=>calls.filter(call=>call.name==='commerce_copilot_send'),
    opens:()=>calls.filter(call=>call.name==='commerce_copilot_open'),
  };
}

test('same-module manual selection and following the page preserve opaque and unassigned store scopes',async t=>{
  for(const id of [A,'unassigned']){
    const f=fixture(scope(id),page(id));t.after(()=>f.controller.dispose());await f.open();
    await f.choose('orders');f.input('固定当前店铺的问题');f.send();await flush();
    f.assertSendStore(f.sends()[0],id,'a'.repeat(64));
    await f.choose(null);f.input('跟随当前页面的问题');f.send();await flush();
    f.assertSendStore(f.sends()[1],id,'a'.repeat(64));
    assert.ok(f.opens().every(call=>call.args.context.store_scope===id));
    assert.doesNotMatch(f.controller.view(),/全部店铺/);
  }
});

test('incompatible manual modules are rejected before API activity and cannot remove the selected store',async t=>{
  const f=fixture();t.after(()=>f.controller.dispose());await f.open();await f.choose('orders');
  const before=f.calls.length;
  for(const module of ['overview','products','live','connections'])await assert.rejects(f.choose(module),/当前问题已限定店铺/);
  assert.equal(f.calls.length,before);
  f.input('拒绝切换后仍问当前店铺');f.send();await flush();
  f.assertSendStore(f.sends()[0],A,'a'.repeat(64));
});

test('a previously fixed unrelated module cannot override a later selected-store base context or page',async t=>{
  const f=fixture({module:'overview',demo:false},{page:'overview',demo:false});t.after(()=>f.controller.dispose());await f.open();
  await f.choose('products');f.navigate(scope(A),page(A));await flush();
  f.input('选中店铺后的新问题');f.send();await flush();
  assert.equal(f.opens().at(-1).args.context.module,'orders');
  f.assertSendStore(f.sends()[0],A,'a'.repeat(64));
});

test('the page and source reference are frozen when Send is pressed before conversation creation finishes',async t=>{
  const f=fixture();t.after(()=>f.controller.dispose());await f.open();await f.choose('orders');
  const opening=f.gate('open');f.input('原页面版本的问题');f.send();await flush();
  assert.equal(f.opens().length,1);assert.equal(f.sends().length,0);
  f.mutatePageVersion('b'.repeat(64));opening.resolve();await flush();
  f.assertSendStore(f.sends()[0],A,'a'.repeat(64));
  assert.equal(f.sends()[0].args.page_context.filters.query,'合成筛选');
});

test('navigation between stores during real capability preparation sends neither a mixed nor a global request',async t=>{
  const f=fixture();t.after(()=>f.controller.dispose());f.storage.set(draftKey(scope(B)),'店铺 B 未发送草稿');await f.open();
  await f.capability('toggle');const checking=f.gate('check');
  const pending=f.capability('select',{capabilityId:'mcp:commerce'});await flush();
  f.input('店铺 A 原问题');f.send();await flush();
  assert.equal(f.opens().length,0);
  f.navigate(scope(B),page(B,'b'.repeat(64)));checking.resolve();await pending;await flush();
  assert.equal(f.opens().length,0);assert.equal(f.sends().length,0);
  assert.match(f.controller.view(),/店铺 B 未发送草稿/);
  assert.match(f.controller.view(),/发送前页面范围已变化/);
  f.navigate(scope(A),page(A));await flush();assert.match(f.controller.view(),/店铺 A 原问题/);
});

test('a late conversation-open response keeps the original request bound and leaves the new-store draft separate',async t=>{
  const f=fixture();t.after(()=>f.controller.dispose());f.storage.set(draftKey(scope(B)),'店铺 B 未发送草稿');await f.open();
  const opening=f.gate('open');f.input('店铺 A 已点击发送的问题');f.send();await flush();
  assert.equal(f.opens().length,1);f.navigate(scope(B),page(B,'b'.repeat(64)));await flush();
  opening.resolve();await flush();
  assert.equal(f.sends().length,1);f.assertSendStore(f.sends()[0],A,'a'.repeat(64));
  assert.match(f.controller.view(),/店铺 B 未发送草稿/);assert.doesNotMatch(f.controller.view(),/店铺 A 已点击发送的问题/);
  f.send();await flush();assert.equal(f.sends().length,2);f.assertSendStore(f.sends()[1],B,'b'.repeat(64));
  assert.equal(f.sends()[1].args.message,'店铺 B 未发送草稿');assert.notEqual(f.sends()[0].args.thread_id,f.sends()[1].args.thread_id);
});

test('an old-store send acknowledgement cannot replace the new-store page or its next submission',async t=>{
  const f=fixture();t.after(()=>f.controller.dispose());f.storage.set(draftKey(scope(B)),'店铺 B 保留输入');await f.open();
  const sending=f.gate('send');f.input('店铺 A 发送中的问题');f.send();await flush();
  assert.equal(f.sends().length,1);f.navigate(scope(B),page(B,'b'.repeat(64)));sending.resolve();await flush();
  assert.match(f.controller.view(),/店铺 B 保留输入/);assert.doesNotMatch(f.controller.view(),/店铺 A 发送中的问题/);
  f.send();await flush();f.assertSendStore(f.sends()[0],A,'a'.repeat(64));f.assertSendStore(f.sends()[1],B,'b'.repeat(64));
  assert.equal(f.sends()[1].args.message,'店铺 B 保留输入');
});
