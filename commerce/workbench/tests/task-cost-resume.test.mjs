import test from 'node:test';
import assert from 'node:assert/strict';
import { readTaskCostSurface } from '../src/task-cost-resume.ts';

const surfaceId = 'cost_' + 'a'.repeat(32);
const task = { id: 'original-task', input: { surface_id: surfaceId } };
test('cost continuation re-reads the original Surface and returns its actual binding', async () => {
  const current = { surface_id: surfaceId, task_id: task.id, binding: { case_id: 'original-case' } };
  assert.equal(await readTaskCostSurface(async (tool, args) => {
    assert.equal(tool, 'commerce_a2ui_get'); assert.deepEqual(args, { surface_id: surfaceId }); return current;
  }, task), current);
});
test('cost continuation rejects changed task identity and skips ordinary tasks', async () => {
  await assert.rejects(readTaskCostSurface(async () => ({ surface_id: surfaceId, task_id: 'another-task' }), task), /cost_task_changed/);
  await assert.rejects(readTaskCostSurface(async () => ({ surface_id: 'cost_' + 'b'.repeat(32), task_id: task.id }), task), /cost_task_changed/);
  assert.equal(await readTaskCostSurface(async () => { throw Error('must not request'); }, { id: 'other', input: {} }), null);
});
