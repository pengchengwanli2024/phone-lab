import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['src/operating-loop-state.ts'],bundle:true,format:'cjs',write:false,platform:'node'});
const module={exports:{}};new Function('module','exports',bundle.outputFiles[0].text)(module,module.exports);
const {groupWork,workStatus,outcomeText,loopError,grantState,grantLabel,defaultStages,stageWarnings,ownerName,levelName}=module.exports;
const grant=(id,extra={})=>({id,target:{case_id:'c',platform:'ozon',store_ref:'s',market:'RU'},goal:'launch',stages:['research'],level:'prepare',max_runs_per_day:3,expires_at:null,enabled:true,active:true,halted_reason:null,revision:2,case_label:'合成商品',case_available:true,synthetic:false,...extra});
const work=(id,status,grant_id='g1')=>({id,grant_id,status,stage_id:'research',stage_name:'市场研究与选品',owner:'scout'});
const catalog=[{id:'research',name:'研究',owner:'scout',executable:true,depends_on:[]},{id:'sourcing',name:'货源',owner:'sourcer',executable:true,depends_on:['research']},
  {id:'economics',name:'成本',owner:'economist',executable:true,depends_on:['sourcing']},{id:'listing',name:'上架',owner:'conductor',executable:false,depends_on:['economics']},
  {id:'growth',name:'增长',owner:'grower',executable:true,depends_on:['listing']}];

test('work is grouped by who must act, and finished work is never outstanding',()=>{
  const view={grants:[grant('g1')],work:[work('a','awaiting_decision'),work('b','unknown'),work('c','failed'),work('d','waiting_input'),work('e','dispatched'),work('f','pending'),work('g','completed'),work('h','rejected'),work('i','resolved'),work('j','superseded')]};
  const groups=groupWork(view,false);
  assert.deepEqual(groups.decide.map(w=>w.id),['a']);assert.deepEqual(groups.attention.map(w=>w.id),['b','c']);
  assert.deepEqual(groups.waiting.map(w=>w.id),['d']);assert.deepEqual(groups.running.map(w=>w.id),['e','f']);
  assert.deepEqual(groups.done.map(w=>w.id),['g','h','i','j']);
  assert.deepEqual(workStatus('superseded'),{label:'资料已更新',tone:'gray'});
  assert.match(outcomeText('awaiting_your_decision'),/等你决定/);
});
test('synthetic and live scopes never mix, and a failed read yields no groups',()=>{
  const view={grants:[grant('g1'),grant('g2',{synthetic:true})],work:[work('live','awaiting_decision','g1'),work('demo','awaiting_decision','g2'),work('orphan','awaiting_decision','gone')]};
  assert.deepEqual(groupWork(view,false).decide.map(w=>w.id),['live']);assert.deepEqual(groupWork(view,true).decide.map(w=>w.id),['demo']);
  assert.deepEqual(groupWork(null,false),{decide:[],attention:[],waiting:[],running:[],done:[]});
});
test('statuses, outcomes and errors use plain words and never invent a success',()=>{
  assert.deepEqual(workStatus('awaiting_decision'),{label:'等你决定',tone:'warning'});
  assert.deepEqual(workStatus('unknown'),{label:'结果未知',tone:'warning'});
  assert.deepEqual(workStatus('brand_new_state'),{label:'状态待核对',tone:'gray'});
  assert.match(outcomeText('no_new_evidence'),/没有新工单/);assert.match(outcomeText('unknown_requires_check'),/先核对/);
  assert.match(outcomeText('some_new_reason'),/请核对/);
  assert.match(loopError(Error('operating_loop_revision_conflict')),/最新版本/);
  assert.match(loopError(Error('agent_case_evidence_changed')),/未提交/);
  assert.match(loopError(Error('anything_else')),/操作未完成/);assert.match(loopError('not an error'),/操作未完成/);
});
test('grant state distinguishes running, disabled, expired and auto-halted',()=>{
  assert.equal(grantState(grant('g')).label,'运行中');assert.equal(grantState(grant('g',{enabled:false,active:false})).label,'未启用');
  assert.equal(grantState(grant('g',{active:false})).label,'已过期');
  assert.equal(grantState(grant('g',{enabled:false,active:false,halted_reason:'consecutive_failures'})).label,'已自动停用');
  assert.equal(grantLabel(grant('g',{case_label:null,case_available:false})),'商品当前不可读取');
  assert.equal(grantLabel(grant('g',{case_label:null})),'未命名商品');
  assert.equal(ownerName('scout'),'市场调研');assert.equal(ownerName('new-role'),'new-role');assert.equal(levelName('observe'),'仅观察');
});
test('default stages are workable ones, and a missing upstream stage is called out',()=>{
  assert.deepEqual(defaultStages(catalog),['research','sourcing','economics']);
  assert.deepEqual(stageWarnings(catalog,['research','sourcing']),[]);
  const warnings=stageWarnings(catalog,['economics']);
  assert.equal(warnings.length,1);assert.match(warnings[0],/成本.*货源/);
});
