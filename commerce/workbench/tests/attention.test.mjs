import test from 'node:test';
import assert from 'node:assert/strict';
import { readAttentionTarget, linkedAttentionTasks } from '../src/attention-state.ts';

test('opening an attention item revalidates its identity through a read before returning its original target', async () => {
  const action = { type: 'thread', id: 'original-thread' };
  const target = await readAttentionTarget(async (tool, args) => {
    assert.equal(tool, 'commerce_attention_get'); assert.deepEqual(args, { item_id: 'original-item' });
    return { item: { id: 'original-item', action } };
  }, 'original-item');
  assert.deepEqual(target, action);
});

test('changed items and arbitrary targets cannot open another work item', async () => {
  for (const item of [
    { id: 'new-item', action: { type: 'thread', id: 'original-thread' } },
    { id: 'original-item', action: { type: 'execute', id: 'original-thread' } },
    { id: 'original-item', action: { type: 'thread', id: 'https://example.invalid' } },
  ]) await assert.rejects(readAttentionTarget(async () => ({ item }), 'original-item'), /attention_item_changed/);
  await assert.rejects(readAttentionTarget(async () => { throw Error('attention_source_unavailable'); }, 'original-item'), /attention_source_unavailable/);
});

test('only referenced Core tasks are suppressed from duplicate overview notices', () => {
  const ids = linkedAttentionTasks([{ source: 'agent', source_id: 'run-a', task_id: 'task-a' }, { source: 'research', source_id: 'task-b', task_id: 'task-b' }, { source: 'agent', source_id: 'run-c' }]);
  assert.deepEqual([...ids].sort(), ['task-a', 'task-b']);
  assert.equal(ids.has('run-a'), false); assert.equal(ids.has('run-c'), false);
});
