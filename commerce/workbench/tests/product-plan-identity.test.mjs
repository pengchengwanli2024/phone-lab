import test from 'node:test';
import assert from 'node:assert/strict';
import {planEditorFixture} from './helpers/product-plan-editor.mjs';

test('same-title steps and their task identities survive a goal-only edit',async()=>{
 const f=planEditorFixture();f.open();f.input('pw-goal','Updated goal');await f.action('save-plan');
 assert.equal(f.saved.goal,'Updated goal');assert.deepEqual(f.saved.steps.map(s=>[s.id,s.task_id]),[['step_a','task_a'],['step_b','task_b']]);
 assert.equal(f.requests[0].tool,'commerce_workspace_save');assert.equal(f.requests[0].args.case_id,'exact-case');
});
test('rename and explicit reorder preserve each original task identity',async()=>{
 const f=planEditorFixture();f.open();f.input('step_b','Renamed second step');await f.action('plan-step-up','step_b');await f.action('save-plan');
 assert.deepEqual(f.saved.steps.map(s=>[s.id,s.task_id,s.title]),[['step_b','task_b','Renamed second step'],['step_a','task_a','Same title']]);
});
test('removing one duplicate and adding another creates a new identity without reusing a task',async()=>{
 const f=planEditorFixture();f.open();await f.action('plan-step-remove','step_a');await f.action('plan-step-add');const id=f.draft.steps[1].id;f.input(id,'Same title');await f.action('save-plan');
 assert.deepEqual(f.saved.steps[0],{id:'step_b',title:'Same title',task_id:'task_b'});assert.match(id,/^step_[a-f0-9]{32}$/);assert.equal(f.saved.steps[1].task_id,undefined);
});
test('blank step validation preserves the open editor and does not save',async()=>{
 const f=planEditorFixture();f.open();await f.action('plan-step-add');await f.action('save-plan');assert.equal(f.requests.length,0);assert.match(f.draft.error,/名称/);assert.equal(f.draft.steps.length,3);
});
test('failed save retains the plan checkpoint edits and task IDs for recovery',async()=>{
 const f=planEditorFixture(undefined,{failSave:true});f.open();f.input('step_b','Unsent retry');await f.action('save-plan');assert.equal(f.s.errorCode,'request_outcome_unknown');assert.equal(f.s.dirty.has('plan'),true);assert.equal(f.s.edits.plan.steps[1].id,'step_b');assert.equal(f.s.edits.plan.steps[1].title,'Unsent retry');
});
