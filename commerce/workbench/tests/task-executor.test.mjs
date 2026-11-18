import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['src/task-executor-state.ts'],bundle:true,format:'cjs',write:false,platform:'node'});
const module={exports:{}};new Function('module','exports',bundle.outputFiles[0].text)(module,module.exports);
const {executorView,hostName}=module.exports;
const ready=choice=>({state:'ready',choice});

test('the recorded host plan and routing reason are shown in plain words',()=>{
  const view=executorView({run_id:'r1',execution_hosts:[{host_id:'dsh',provider:'deepseek',model:'m-1'}],host_attempts:[]},ready({host_id:'dsh',model:'m-1',routing_reason:'priority_live_capability'}));
  assert.equal(view.recorded,true);assert.equal(view.name,'Harness');assert.equal(view.model,'m-1');assert.equal(view.reasonKnown,true);
  assert.match(view.reason,/优先顺序/);
  assert.match(executorView({execution_hosts:[{host_id:'codex'}]},ready({routing_reason:'explicit_host_plan'})).reason,/明确指定/);
  assert.equal(executorView({execution_hosts:[{host_id:'dsh'},{host_id:'hermes'}]},{state:'none'}).name,'Harness → Hermes');
  assert.equal(hostName('codex'),'Codex');assert.equal(hostName('other-host'),'other-host');
});
test('an unknown reason code stays visible and a missing reason is never invented',()=>{
  assert.equal(executorView({},ready({host_id:'dsh',routing_reason:'new_rule_x'})).reason,'原记录：new_rule_x');
  const chosen=executorView({},ready({label:'项目默认模型',model:'m-2'}));
  assert.equal(chosen.name,'工作台内置执行');assert.equal(chosen.reasonKnown,false);assert.match(chosen.reason,/未保存选择依据/);
  const empty=executorView(null,{state:'none'});
  assert.equal(empty.recorded,false);assert.equal(empty.name,'未记录执行端');assert.equal(empty.reason,'未记录选择依据。');
  assert.equal(executorView({},ready({})).name,'未记录执行端');
});
test('loading and failed reads are distinct from an absent reason',()=>{
  const source={execution_hosts:[{host_id:'hermes'}]};
  assert.match(executorView(source,{state:'loading'}).reason,/正在读取/);
  const failed=executorView(source,{state:'failed'});
  assert.match(failed.reason,/未读到/);assert.equal(failed.reasonKnown,false);assert.equal(failed.name,'Hermes');
});
test('unconfirmed attempts are flagged and malformed rows do not throw',()=>{
  const view=executorView({host_attempts:[{attempt_id:'a1',host_id:'dsh',phase:'plan',generation:1,status:'completed'},{attempt_id:'a2',host_id:'hermes',phase:'report',generation:2,status:'unknown'},null,{status:'odd_state'}]},{state:'none'});
  assert.equal(view.attempts.length,3);assert.equal(view.attempts[0].unresolved,false);assert.equal(view.attempts[1].unresolved,true);
  assert.match(view.attempts[1].status,/不重发/);assert.equal(view.attempts[2].host,'执行端未记录');assert.equal(view.attempts[2].status,'odd_state');
  assert.deepEqual(executorView({host_attempts:'bad',execution_hosts:'bad'},{state:'none'}).attempts,[]);
});
