import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['src/overview-command-state.ts'],bundle:true,format:'cjs',write:false,platform:'node'});
const module={exports:{}};new Function('module','exports',bundle.outputFiles[0].text)(module,module.exports);
const {commandItems,splitInProgress}=module.exports;
const ready=value=>({state:'ready',value});
const healthy=ready({worker:'running',capability_runtime:{stopped:false,media_error:null,extension_error:null,operating_loop_error:null,last_tick:1}});
const grant=(id,extra={})=>({id,synthetic:false,halted_reason:null,...extra});
const work=(id,status,grant_id='g')=>({id,status,grant_id});
const loop=(grants,items)=>ready({grants,work:items});
const ids=items=>items.map(item=>item.id);

test('a healthy backend with nothing pending shows nothing at all',()=>{
  assert.deepEqual(commandItems(healthy,loop([grant('g')],[work('a','completed'),work('b','waiting_input'),work('c','dispatched')]),false),[]);
  assert.deepEqual(commandItems({state:'loading'},{state:'loading'},false),[]);
});
test('a failed read is reported and never looks like all clear',()=>{
  assert.deepEqual(ids(commandItems({state:'failed'},{state:'failed'},false)),['runtime-unread','loop-unread']);
});
test('faults come first, then items to check, then decisions',()=>{
  const runtime=ready({worker:'stopped_or_stale',capability_runtime:{media_error:'media_background_tick_failed',extension_error:null,new_error:'x',stopped:true}});
  const items=commandItems(runtime,loop([grant('g'),grant('h',{halted_reason:'consecutive_failures'})],[work('a','awaiting_decision'),work('b','unknown'),work('c','failed'),work('d','awaiting_decision')]),false);
  assert.deepEqual(ids(items),['worker','media_error','new_error','loop-halted','loop-attention','loop-decide']);
  assert.match(items[1].title,/媒体/);assert.match(items[2].title,/一项后台任务/);
  assert.match(items[4].title,/^2 项/);assert.match(items[5].title,/^2 项/);
  assert.equal(items[5].target,'operating-control');assert.equal(items[0].target,'connections');
});
test('synthetic and live loop work never mix',()=>{
  const view=loop([grant('g'),grant('demo',{synthetic:true,halted_reason:'consecutive_failures'})],[work('a','awaiting_decision','demo')]);
  assert.deepEqual(commandItems(healthy,view,false),[]);
  assert.deepEqual(ids(commandItems(healthy,view,true)),['loop-halted','loop-decide']);
});
test('queued work nobody will pick up is separated from running work',()=>{
  const tasks=[{id:'a',status:'queued'},{id:'b',status:'queued'},{id:'c',status:'running'},{id:'d',status:'queued'}];
  const split=splitInProgress(tasks,ready({items:{a:'unassigned',b:'local_executor',d:'market_research'},unassigned:1}));
  assert.deepEqual(split.parked.map(t=>t.id),['a']);assert.deepEqual(split.running.map(t=>t.id),['b','c','d']);
  // Without a dispatch read nothing is reclassified.
  for(const state of [{state:'loading'},{state:'failed'}])assert.deepEqual(splitInProgress(tasks,state).parked,[]);
});
test('only backup and disk health lines are added, and only when they need attention',()=>{
  const health=ready({checks:[{id:'worker',status:'critical',label:'后台工作器',detail:'x'},{id:'backup',status:'warning',label:'数据库备份',detail:'还没有备份'},{id:'disk',status:'ok',label:'磁盘空间',detail:'剩余约 100 GB'},{id:'unassigned',status:'warning',label:'排队任务',detail:'y'}]});
  const items=commandItems(healthy,loop([],[]),false,health);
  assert.deepEqual(ids(items),['health-backup']);assert.equal(items[0].tone,'warning');assert.match(items[0].detail,/还没有备份/);
  assert.deepEqual(commandItems(healthy,loop([],[]),false,{state:'failed'}),[]);
  assert.equal(commandItems(healthy,loop([],[]),false,ready({checks:[{id:'disk',status:'critical',label:'磁盘空间',detail:'剩余约 0 GB'}]}))[0].tone,'danger');
});
