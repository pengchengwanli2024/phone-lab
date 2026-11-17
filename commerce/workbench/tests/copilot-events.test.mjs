import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {EventType} from '@ag-ui/client';
import {randomUUID} from 'node:crypto';

const source=await readFile('../web/copilot-events.js','utf8').catch(error=>{if(error.code==='ENOENT')return '';throw error;});
const composer=await readFile('../web/copilot-ui.js','utf8');
const copy=value=>JSON.parse(JSON.stringify(value));
const flush=()=>new Promise(setImmediate);
const context={module:'overview',demo:true};
const run={id:'original',status:'running'};
const thread={id:'thread',context,context_sha256:'scope',turns:[{id:'turn',question:'原问题',run}],latest_run:run};
const snapshot=(answer,cursor,status='running',extra={})=>({cursor,status,snapshot:{cursor,answer,components:[],provisional:status==='running',mode:'provider_deltas',...extra}});
function helper(){const sandbox={setTimeout,clearTimeout};vm.runInNewContext(source,sandbox);assert.equal(typeof sandbox.CommerceRunEvents?.observe,'function','shared read-only observer must be available');return sandbox.CommerceRunEvents;}
function observe(api,options={}){
  const events=[];let dispose;
  const result=new Promise((resolve,reject)=>{dispose=helper().observe({api,thread:copy(thread),runId:run.id,pollMs:1,onEvent:event=>events.push(event),onComplete:resolve,onError:(error,settled)=>{error.thread=settled;reject(error);},...options});});
  return {events,result,dispose:()=>dispose()};
}

test('shared observer emits standard events, advances cursor and reconciles authoritative answer without sending',async()=>{
  const calls=[];let n=0;const settled=copy(thread);settled.latest_run=settled.turns[0].run={...run,status:'completed',result:{answer:'最终答复'},presentation:{components:[]}};
  const s=observe(async(name,args)=>{calls.push({name,args});if(name==='commerce_copilot_events')return ++n===1?snapshot('预览',4):snapshot('',5,'completed');assert.equal(name,'commerce_copilot_get');return settled;});
  assert.equal(await s.result,settled);assert.equal(calls[1].args.after,4);assert.ok(calls.every(c=>['commerce_copilot_events','commerce_copilot_get'].includes(c.name)));
  assert.ok(s.events.every(e=>Object.values(EventType).includes(e.type)));assert.ok(s.events.some(e=>e.type==='TEXT_MESSAGE_CONTENT'&&e.delta==='预览'));
  assert.equal(s.events.filter(e=>e.type==='TEXT_MESSAGE_START').length,1);assert.equal(s.events.findLast(e=>e.type==='MESSAGES_SNAPSHOT').messages.at(-1).content,'最终答复');assert.equal(s.events.at(-1).type,'RUN_FINISHED');
});
test('stream resets replace preview and final-only mode stays explicit',async()=>{
  let n=0;const settled=copy(thread);settled.latest_run=settled.turns[0].run={...run,status:'awaiting_input',result:{answer:'补充资料'}};
  const s=observe(async name=>name==='commerce_copilot_get'?settled:[snapshot('旧预览',1),snapshot('新预览',2),snapshot('',3,'awaiting_input',{mode:'final_only'})][n++]);
  await s.result;assert.ok(s.events.some(e=>e.type==='MESSAGES_SNAPSHOT'&&e.messages.at(-1)?.content==='新预览'));assert.ok(s.events.some(e=>e.type==='STATE_SNAPSHOT'&&e.snapshot.stream_mode==='final_only'));assert.equal(s.events.at(-1).type,'RUN_FINISHED');
});
test('preview budget exhaustion remains visible in the standard state projection',async()=>{
  let n=0;const settled=copy(thread);settled.latest_run=settled.turns[0].run={...run,status:'completed',result:{answer:'最终结果'}};
  const s=observe(async name=>name==='commerce_copilot_get'?settled:++n===1?snapshot('有界预览',100,'running',{truncated:true}):snapshot('',101,'completed'));
  await s.result;assert.ok(s.events.some(e=>e.type==='STATE_SNAPSHOT'&&e.snapshot.stream_truncated===true));
});
test('UNKNOWN retracts provisional answer and returns original terminal receipt without recovery or replay',async()=>{
  let n=0;const calls=[];const settled=copy(thread);settled.latest_run=settled.turns[0].run={...run,status:'unknown',error:'request_outcome_unknown'};
  const s=observe(async name=>{calls.push(name);return name==='commerce_copilot_get'?settled:++n===1?snapshot('不能当作最终结果',1):snapshot('',2,'unknown');});
  await assert.rejects(s.result,error=>error.message==='request_outcome_unknown'&&error.thread===settled);assert.equal(s.events.findLast(e=>e.type==='MESSAGES_SNAPSHOT').messages.some(m=>m.role==='assistant'),false);assert.ok(!s.events.some(e=>e.type==='RUN_FINISHED'));assert.ok(calls.every(name=>['commerce_copilot_events','commerce_copilot_get'].includes(name)));
});
test('disposal suppresses late response and never fetches or cancels the backend run',async()=>{
  const h=helper(),calls=[],events=[];let resolve;const gate=new Promise(r=>{resolve=r;});const dispose=h.observe({api:async name=>{calls.push(name);return gate;},thread:copy(thread),runId:run.id,pollMs:1,onEvent:e=>events.push(e),onComplete:()=>assert.fail('detached completion'),onError:()=>assert.fail('detached error')});
  dispose();resolve(snapshot('',1,'completed'));await flush();assert.deepEqual(calls,['commerce_copilot_events']);assert.equal(events.length,1);
});
test('network and unknown-tool failures are surfaced once, never resubmitted by the observer',async()=>{
  for(const code of ['offline','unknown_tool']){let calls=0;const s=observe(async()=>{calls++;throw Object.assign(Error(code),{code});});await assert.rejects(s.result,new RegExp(code));await flush();assert.equal(calls,1);}
});
test('authoritative original run is selected even when a queued successor is now latest',async()=>{
  const settled=copy(thread);settled.turns[0].run={...run,status:'completed',result:{answer:'原轮完成'}};settled.latest_run={id:'successor',status:'running'};
  const s=observe(async name=>name==='commerce_copilot_events'?snapshot('',1,'completed'):settled);await s.result;assert.equal(s.events.findLast(e=>e.type==='STATE_SNAPSHOT').snapshot.backend_run_id,'original');assert.ok(s.events.some(e=>e.type==='TEXT_MESSAGE_CONTENT'&&e.delta==='原轮完成'));
});

async function mount(){
  const handlers=new Map(),intervals=new Set(),calls=[];let page=copy(context),eventResponse;
  const gate=new Promise(resolve=>{eventResponse=resolve;});const events={addEventListener(name,fn){if(!handlers.has(name))handlers.set(name,new Set());handlers.get(name).add(fn);},removeEventListener(name,fn){handlers.get(name)?.delete(fn);}};
  const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const ui={escape,icon:()=>'',badge:escape,alert:escape,button:({label})=>`<button>${escape(label)}</button>`};
  const document={...events,querySelector:()=>null,getElementById:()=>null,activeElement:null};const window={...events,CommerceUI:ui,innerWidth:1440,dispatchEvent(){}};window.parent=window;
  const sandbox={window,document,crypto:{randomUUID},localStorage:{getItem:()=>null,setItem(){}},setTimeout,clearTimeout,setInterval(fn){intervals.add(fn);return fn;},clearInterval(fn){intervals.delete(fn);},CustomEvent:class{}};
  vm.runInNewContext(source+'\n'+composer,sandbox);
  const controller=window.CommerceCopilot({api:async(name,args)=>{calls.push({name,args});if(name==='commerce_model_list')return {models:[]};if(name==='commerce_copilot_list')return {threads:[]};if(name==='commerce_copilot_get')return copy(thread);if(name==='commerce_copilot_events')return gate;throw Error(name);},inline:true,compact:true,repaint(){},getContext:()=>page,getPageContext:()=>({...page,page:page.module,source:'local'}),scopeLabel:()=> '合成测试'});
  controller.open(undefined,{focus:false});await flush();await controller.openThread(thread.id);await flush();
  return {controller,calls,tick:()=>{for(const fn of intervals)void fn();return flush();},eventResponse,page(value){page=value;controller.contextChanged();},input(value){for(const fn of handlers.get('input')||[])fn({target:{id:'copilot-message',value}});}};
}
test('main composer has one event observer and accepts standard stream state while keeping draft',async t=>{
  const s=await mount();t.after(()=>s.controller.dispose());s.input('未发送的补充');await s.tick();await s.tick();assert.equal(s.calls.filter(c=>c.name==='commerce_copilot_events').length,1);s.eventResponse(snapshot('同源事件预览',8));await flush();
  assert.ok(s.controller.view().includes('同源事件预览'));assert.ok(s.controller.view().includes('未发送的补充'));assert.equal(s.calls.filter(c=>/send|open/.test(c.name)).length,0);s.controller.dispose();
});
test('main composer discards late event after scope navigation and releases observer on close',async t=>{
  const s=await mount();t.after(()=>s.controller.dispose());await s.tick();s.page({module:'orders',demo:true});await s.tick();s.eventResponse(snapshot('不能串入新页面',9));await flush();assert.ok(!s.controller.view().includes('不能串入新页面'));s.controller.close();s.controller.dispose();assert.equal(s.calls.filter(c=>c.name==='commerce_copilot_events').length,1);
});
