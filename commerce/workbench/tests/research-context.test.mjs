import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const context=vm.createContext({URL});vm.runInContext(await readFile('../web/research-context.js','utf8'),context);
const model=context.CommerceResearchContext;
const plain=value=>JSON.parse(JSON.stringify(value));
const snapshot=(task,id)=>({task_id:task,artifact_id:id,read_only:true,is_current_artifact:false,artifact:{id,payload:{record:{fields:{title:{original:task}}}},sha256:id,intact:true}});
test('a task-specific research snapshot never falls back to the current product artifact',()=>{
  const current={artifacts:{research:{id:'current'}}},selected={...current,research_context:snapshot('old-task','old-artifact')};
  assert.equal(model.artifact(selected,'old-task').id,'old-artifact');assert.equal(selected.artifacts.research.id,'current');
  assert.throws(()=>model.artifact(current,'old-task'),/context_unavailable/);assert.throws(()=>model.artifact(selected,'other-task'),/context_unavailable/);
  assert.equal(model.artifact(current).id,'current');
});
test('refreshing research context preserves unsaved editors and the current write-source identity',()=>{
  const forms={cost:{revision:8,payload:{input:{price:123}}}},data={case:{id:'case-a'},forms,source_sha256:'current-base',gates:{approved:false},artifacts:{research:{id:'latest'}}};
  const readback={...data,forms:{cost:{revision:99}},source_sha256:'new-server-base',research_context:snapshot('old-task','old-artifact'),research_contexts:[]};
  const merged=model.merge(data,readback,'old-task');assert.equal(merged.forms,forms);assert.equal(merged.source_sha256,'current-base');assert.equal(merged.artifacts,data.artifacts);assert.equal(merged.gates,data.gates);assert.equal(merged.research_context.artifact.id,'old-artifact');
  assert.throws(()=>model.merge(data,{...readback,case:{id:'other'}},'old-task'),/context_invalid/);
});
test('legacy and task-specific Harness resources round trip without accepting ambiguous parameters',()=>{
  assert.deepEqual(plain(model.parseResource(model.resource('case-a'))),{caseId:'case-a',researchTaskId:''});
  assert.deepEqual(plain(model.parseResource(model.resource('case-a','task-a'))),{caseId:'case-a',researchTaskId:'task-a'});
  for(const address of ['https://example.com/product/case-a','dsh-resource://commerce/product/case-a?research_task_id=../other','dsh-resource://commerce/product/case-a?research_task_id=a&research_task_id=b','dsh-resource://commerce/product/case-a?unknown=a'])assert.equal(model.parseResource(address),null);
});
test('read-only task refresh updates the same list row without modifying other tasks',()=>{
  const old={task_id:'a',status:'unknown',candidate_count:0},other={task_id:'b',status:'awaiting_input'},fresh={...old,status:'partial',candidate_count:1};
  const result=model.mergeJob([old,other],fresh);assert.equal(result[0],fresh);assert.equal(result[1],other);assert.equal(old.candidate_count,0);assert.equal(result.length,2);
});
test('list and detail reads keep monotonic revisions while list owns membership and order',()=>{
  const old={task_id:'a',revision:1,status:'unknown'},fresh={...old,revision:5,status:'partial'},other={task_id:'b',revision:2},removed={task_id:'removed',revision:9};
  assert.equal(model.mergeJob([fresh],old)[0],fresh);
  const result=model.mergeJobs([fresh,removed],[other,old]);assert.equal(result.length,2);assert.equal(result[0],other);assert.equal(result[1],fresh);
  const newest={...fresh,revision:6};assert.equal(model.mergeJobs([fresh],[newest])[0],newest);
  assert.equal(model.mergeJob([{...fresh,revision:'10'}],{...old,revision:'2'})[0].revision,'10');
});
