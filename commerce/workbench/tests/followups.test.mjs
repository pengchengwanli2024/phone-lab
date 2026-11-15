import test from 'node:test';
import assert from 'node:assert/strict';
import { dueAt, originalFollowupAction } from '../src/followup-state.ts';
import { readAttentionTarget } from '../src/attention-state.ts';

test('a timezone-qualified user appointment is preserved as the same UTC instant', () => {
  assert.equal(dueAt('2027-01-15T20:00:00+08:00'), '2027-01-15T12:00:00.000Z');
  assert.throws(() => dueAt(''), /invalid_followup_time/);
  assert.throws(() => dueAt('not-a-date'), /invalid_followup_time/);
});
test('only original read navigation can leave a follow-up receipt', () => {
  assert.deepEqual(originalFollowupAction({ type:'research', id:'original-task' }), { type:'research', id:'original-task' });
  assert.deepEqual(originalFollowupAction({ type:'tasks', id:'original-task' }), { type:'tasks', id:'original-task' });
  for (const value of [null, { type:'execute', id:'a' }, { type:'followup', id:'a' }, { type:'thread', id:'https://example.invalid' }]) {
    assert.equal(originalFollowupAction(value), null);
  }
});
test('an explicitly included follow-up attention entry opens its receipt, never the watched execution', async () => {
  const action = await readAttentionTarget(async (name, args) => {
    assert.equal(name, 'commerce_attention_get'); assert.equal(args.item_id, 'attention-item');
    return { item:{ id:'attention-item', action:{ type:'followup', id:'followup_receipt' } } };
  }, 'attention-item');
  assert.deepEqual(action, { type:'followup', id:'followup_receipt' });
});
