import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';

const source=await readFile('../web/copilot-ui.js','utf8'),flush=()=>new Promise(setImmediate);
const question='您希望调研俄罗斯市场的哪个产品品类，主要研究目标是什么？';
const clone=value=>structuredClone(value);
function setup(status='running'){
  const handlers=new Map(),calls=[],timers=new Set(),storage=new Map();let read,paints=0;
  const events={addEventListener(name,fn){if(!handlers.has(name))handlers.set(name,[]);handlers.get(name).push(fn)},removeEventListener(){}};
  const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const ui={escape:esc,icon:()=>'',badge:esc,alert:esc,button:({label,attrs={}})=>`<button ${Object.entries(attrs).map(([k,v])=>`${k}="${esc(v)}"`).join(' ')}>${esc(label)}</button>`,field:(label,value)=>label+value,input:()=>'',select:()=>''};
  const document={...events,querySelector:()=>null,getElementById:()=>null,activeElement:null},window={...events,CommerceUI:ui,innerWidth:1440,dispatchEvent(){}};window.parent=window;
  const context={module:'overview',demo:false};
  function thread(id,stage){const job={schema:'commerce-market-research-v1',task_id:id+'-task',run_id:id+'-run',thread_id:id,revision:1,status:stage,phase:'planning',market:'RU',source_count:0,candidate_count:0,questions:stage==='awaiting_input'?[question]:[],candidates:[],sources:[]};const run={id:job.run_id,status:'completed',research_job:job,result:{answer:'研究已受理',questions:[]}};return {id,title:id,context,context_sha256:id,latest_run:run,turns:[{id:id+'-turn',question:'先确认品类和目标，再采集真实公开资料',run}],research_job:job,model_selection:{model_id:'project-default',available:true,sha256:id}}}
  const threads={'thread-a':thread('thread-a',status),'thread-b':thread('thread-b','awaiting_input')};threads['thread-b'].research_job.questions=['另一个会话的问题'];
  vm.runInNewContext(source,{window,document,crypto:{randomUUID},setTimeout,clearTimeout,setInterval:fn=>{timers.add(fn);return fn},clearInterval:fn=>timers.delete(fn),CustomEvent:class{},localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)}});
  const controller=window.CommerceCopilot({api:async(name,args)=>{calls.push([name,args]);if(name==='commerce_model_list')return {models:[{id:'project-default',selectable:true}],default_model_id:'project-default'};if(name==='commerce_copilot_list')return {threads:Object.values(threads).map(clone)};if(name==='commerce_copilot_get')return read?read(args.thread_id):clone(threads[args.thread_id]);throw Error('unexpected API '+name)},getContext:()=>context,isActive:()=>true,inline:true,compact:true,repaint(){paints++},scopeLabel:()=> '研究范围',onResearch(){},toast(){}});
  const emit=(name,event)=>{for(const fn of handlers.get(name)||[])fn(event)};
  return {controller,calls,timers,threads,setRead:fn=>read=fn,poll:()=>[...timers][0](),paints:()=>paints,input:value=>emit('input',{target:{id:'copilot-message',value}}),click(action){const target={dataset:{copilotAction:action},closest:selector=>selector==='[data-copilot-action]'?target:null};emit('click',{target,preventDefault(){}})},complete(id='thread-a'){const value=threads[id];value.research_job.status='awaiting_input';value.research_job.revision=5;value.research_job.questions=[question];value.latest_run.result={answer:'需要补充研究方向。',questions:[question]};return clone(value)}};
}
async function ready(s){s.controller.open(undefined,{focus:false});await flush();await s.controller.openThread('thread-a')}

test('current research clarification appears once, including a matching run fallback',async()=>{
  const s=setup('awaiting_input');s.threads['thread-a'].research_job.questions=[];s.threads['thread-a'].latest_run.result.questions=[question];await ready(s);
  const html=s.controller.view();assert.equal(html.split(question).length-1,1);assert.equal(html.split('data-copilot-action="reply"').length-1,1);s.controller.dispose();
});
test('finished or unrelated research never revives an earlier run clarification',async()=>{
  for(const status of ['partial','completed','unknown','awaiting_input']){const s=setup(status);s.threads['thread-a'].research_job.questions=[];s.threads['thread-a'].latest_run.result.questions=[question];if(status==='awaiting_input')s.threads['thread-a'].research_job.run_id='another-run';await ready(s);assert.ok(!s.controller.view().includes(question),status);s.controller.dispose()}
});
test('slow polling reads the current thread once without refreshing model or list catalogs',async()=>{
  const s=setup();await ready(s);s.input('等待状态时保留的草稿');const pending=[],before=s.calls.length;s.setRead(()=>new Promise(resolve=>pending.push(resolve)));
  for(let tick=0;tick<5;tick++){s.poll();await flush()}assert.equal(pending.length,1);
  pending[0](s.complete());await flush();assert.ok(s.controller.view().includes(question));assert.ok(s.controller.view().includes('等待状态时保留的草稿'));
  assert.deepEqual(s.calls.slice(before).map(([name])=>name),['commerce_copilot_get']);assert.equal(s.calls.at(-1)[1].thread_id,'thread-a');s.controller.dispose();
});
test('a failed poll releases its slot and the next read recovers without resending',async()=>{
  const s=setup();await ready(s);s.setRead(async()=>{throw Error('temporary-read-failure')});s.poll();await flush();assert.ok(s.controller.view().includes('temporary-read-failure'));
  const fresh=s.complete();s.setRead(async()=>fresh);s.poll();await flush();assert.ok(s.controller.view().includes(question));assert.ok(!s.controller.view().includes('temporary-read-failure'));assert.ok(!s.calls.some(([name])=>/send|start|resume/.test(name)));s.controller.dispose();
});
test('switching threads discards a late polling response or failure',async()=>{
  for(const fail of [false,true]){const s=setup();await ready(s);let resolve,reject;s.setRead(id=>id==='thread-a'?new Promise((yes,no)=>{resolve=yes;reject=no}):clone(s.threads[id]));s.poll();await flush();await s.controller.openThread('thread-b');if(fail)reject(Error('stale-poll-failure'));else resolve(s.complete());await flush();const html=s.controller.view();assert.ok(html.includes('另一个会话的问题'));assert.ok(!html.includes(question));assert.ok(!html.includes('stale-poll-failure'));s.controller.dispose()}
});
test('a disposed controller cannot paint a late read or launch more polls',async()=>{
  const s=setup();await ready(s);let resolve;s.setRead(()=>new Promise(yes=>resolve=yes));const poll=[...s.timers][0];poll();await flush();s.controller.dispose();const count=s.paints(),calls=s.calls.length;resolve(s.complete());await flush();poll();await flush();assert.equal(s.paints(),count);assert.equal(s.calls.length,calls);assert.equal(s.timers.size,0);
});
test('an explicit refresh wins over an older pending poll',async()=>{
  const s=setup();await ready(s);const stale=clone(s.threads['thread-a']);let resolve;s.setRead(()=>new Promise(yes=>resolve=yes));s.poll();await flush();s.complete();s.setRead(undefined);s.click('refresh');await flush();assert.ok(s.controller.view().includes(question));resolve(stale);await flush();assert.ok(s.controller.view().includes(question));s.controller.dispose();
});
