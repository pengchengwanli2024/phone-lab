import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';
const sources=await Promise.all(['../ui/page-context.js','../web/copilot-ui.js'].map(file=>readFile(file,'utf8')));
const flush=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate)};
function setup(){
  const handlers=new Map(),calls=[],threads=new Map(),storage=new Map();let serial=0,scope={module:'overview',demo:false},page={page:'overview',demo:false},openGate=null;
  const events={addEventListener(name,fn){if(!handlers.has(name))handlers.set(name,[]);handlers.get(name).push(fn)},removeEventListener(name,fn){handlers.set(name,(handlers.get(name)||[]).filter(v=>v!==fn))}};
  const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const ui={escape:esc,icon:()=>'',badge:esc,alert:esc,button:({label,action,attrs={}})=>`<button data-copilot-action="${action||''}" ${Object.entries(attrs).map(([k,v])=>`${k}="${esc(v)}"`).join(' ')}>${esc(label)}</button>`,field:(name,value)=>name+value,input:()=>'',select:()=>''};
  const document={...events,querySelector:()=>null,getElementById:()=>null,activeElement:null},window={...events,CommerceUI:ui,innerWidth:1440,dispatchEvent(){}};window.parent=window;
  const clone=value=>structuredClone(value);
  for(const source of sources)vm.runInNewContext(source,{window,document,crypto:{randomUUID},setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},CustomEvent:class{},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)}});
  const api=async(name,args={})=>{calls.push({name,args:clone(args)});
    if(name==='commerce_model_list')return {models:[{id:'project-default',selectable:true}],default_model_id:'project-default'};
    if(name==='commerce_copilot_list')return {threads:[...threads.values()].map(clone)};
    if(name==='commerce_copilot_get')return clone(threads.get(args.thread_id));
    if(name==='commerce_copilot_open'){if(openGate)await openGate;const thread={id:'thread-'+(++serial),context:clone(args.context),context_sha256:'hash-'+serial,turns:[],model_selection:{model_id:'project-default',available:true,sha256:'a'.repeat(64)}};threads.set(thread.id,thread);return clone(thread);}
    if(name==='commerce_copilot_send'){const thread=threads.get(args.thread_id);thread.latest_run={id:'run-'+calls.length,status:'completed',parameters:{page_context:clone(args.page_context)},result:{answer:'synthetic',questions:[],proposals:[]}};thread.turns.push({id:'turn-'+calls.length,question:args.message,run:clone(thread.latest_run)});return clone(thread);}
    throw Error('Unexpected '+name);
  };
  const controller=window.CommerceCopilot({api,getContext:()=>scope,getPageContext:()=>page,isActive:()=>true,inline:true,compact:true,repaint(){},scopeLabel:c=>c.module,toast(){},modal(){},closeModal(){}});
  const emit=(name,event)=>{for(const fn of handlers.get(name)||[])fn(event)};
  const input=value=>emit('input',{target:{id:'copilot-message',value}});
  const send=()=>emit('keydown',{key:'Enter',ctrlKey:true,target:{id:'copilot-message'},preventDefault(){}});
  return {controller,calls,threads,input,send,open(){controller.open(undefined,{focus:false})},navigate(next,nextPage){scope=clone(next);page=clone(nextPage);controller.contextChanged()},page(next){page=clone(next);controller.contextChanged()},gate(promise){openGate=promise}};
}

test('a new question automatically follows the module and preserves the original draft',async()=>{
  const s=setup();s.open();await flush();s.input('运营台问题');s.send();await flush();s.input('运营台未发送补充');
  s.navigate({module:'products',demo:false},{page:'products',demo:false,entity:{kind:'product',id:'SKU-A'}});await flush();
  assert.doesNotMatch(s.controller.view(),/运营台未发送补充/);assert.match(s.controller.view(),/库存/);
  s.input('这个库存为什么不对？');s.send();await flush();
  const sends=s.calls.filter(c=>c.name==='commerce_copilot_send');assert.equal(sends.length,2);assert.notEqual(sends[0].args.thread_id,sends[1].args.thread_id);assert.equal(sends[1].args.page_context.page,'products');assert.equal(sends[1].args.page_context.entity.id,'SKU-A');
  await s.controller.openThread(sends[0].args.thread_id);assert.match(s.controller.view(),/运营台未发送补充/);s.controller.dispose();
});
test('pages sharing one permission scope still tell the model the exact active page',async()=>{
  const s=setup();s.navigate({module:'connections',demo:false},{page:'models',demo:false});s.open();await flush();s.input('这个怎么配置？');s.send();await flush();
  s.page({page:'memory',demo:false});s.input('这里怎么找？');s.send();await flush();
  assert.deepEqual(s.calls.filter(c=>c.name==='commerce_copilot_send').map(c=>c.args.page_context.page),['models','memory']);assert.match(s.controller.view(),/资料与知识/);s.controller.dispose();
});
test('location is captured when Send is pressed, before asynchronous conversation creation',async()=>{
  const s=setup();s.open();await flush();let release;s.gate(new Promise(resolve=>release=resolve));
  s.page({page:'overview',demo:false,section:'sales-trend',source_refs:{sales:'b'.repeat(64)}});s.input('这两天为什么下降？');s.send();await flush();
  s.page({page:'overview',demo:false,section:'inventory-statistics'});release();await flush();
  const send=s.calls.find(c=>c.name==='commerce_copilot_send');assert.equal(send.args.page_context.section,'sales-trend');assert.equal(send.args.page_context.source_refs.sales,'b'.repeat(64));s.controller.dispose();
});
test('explicit original-thread continuation retains its page instead of silently taking the visible page',async()=>{
  const s=setup();s.open();await flush();s.page({page:'overview',demo:false,section:'sales-trend'});s.input('原问题');s.send();await flush();const original=s.calls.find(c=>c.name==='commerce_copilot_send').args.thread_id;
  s.navigate({module:'products',demo:false},{page:'products',demo:false});await s.controller.openThread(original);s.input('继续原问题');s.send();await flush();
  const send=s.calls.filter(c=>c.name==='commerce_copilot_send').at(-1);assert.equal(send.args.thread_id,original);assert.equal(send.args.page_context.page,'overview');assert.equal(send.args.page_context.intent,'original_thread');s.controller.dispose();
});
test('choosing another chart ends explicit original-question targeting',async()=>{
  const s=setup();s.open();await flush();s.page({page:'overview',demo:false,section:'sales-trend'});s.input('原问题');s.send();await flush();
  await s.controller.openThread(s.calls.find(c=>c.name==='commerce_copilot_send').args.thread_id);
  s.page({page:'overview',demo:false,section:'inventory-statistics'});s.input('现在这个呢？');s.send();await flush();
  const send=s.calls.filter(c=>c.name==='commerce_copilot_send').at(-1);assert.equal(send.args.page_context.section,'inventory-statistics');assert.equal(send.args.page_context.intent,'current_page');s.controller.dispose();
});
test('page metadata drops credentials and explains an unavailable source',()=>{
  const scope={};const window={};vm.runInNewContext(sources[0],{window});
  const result=window.CommercePageContext.clean({page:'overview',source:'unavailable',input:{price:4,api_key:'private'},filters:{query:'Bearer private'}});
  assert.equal(result.input.price,4);assert.equal(result.input.api_key,undefined);assert.equal(result.filters,undefined);assert.match(window.CommercePageContext.label(result),/暂无真实数据/);
});
