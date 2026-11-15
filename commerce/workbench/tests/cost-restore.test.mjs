import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { transform } from 'esbuild';
import vm from 'node:vm';

// Exercise the actual request/submission methods without mounting the UI engine.
const source = await readFile(new URL('../src/cost-page.tsx', import.meta.url), 'utf8');
const load = source.slice(source.indexOf('  async function load(inspect'), source.indexOf('  async function enableDynamic()'));
const submit = source.slice(source.indexOf("  async function submit(action:"), source.indexOf('  const result = surface?.result'));
const target = source.split('\n').find(line => line.includes('const targetPending ='));
const compiled = (await transform(`${target}\n${load}\n${submit}\nthis.run = async () => { await load(true); await submit('update'); await submit('calculate'); };`, { loader: 'ts' })).code;

for (const oldSurface of [null, { surface_id: 'cost_' + 'a'.repeat(32), revision: 1 }]) {
  test(`failed target restoration preserves input and prevents unrelated writes (${oldSurface ? 'existing task' : 'initial target'})`, async () => {
    const calls = [], messages = [];
    let fallbackReads = 0;
    const state = {
      surface: oldSurface, requestedSurface: 'cost_' + 'b'.repeat(32), caseId: '',
      values: { price: '101' }, dirty: true, loaded: !!oldSurface,
      blocked: false, unknown: false, review: null, standardReview: null,
      operation: { current: false }, version: { current: 0 },
      api: async (name) => { calls.push(name); if (name === 'commerce_a2ui_status') return { enabled: true }; throw Error('synthetic_target_unavailable'); },
      errorText: error => error.message,
      standardLoad: async () => { fallbackReads++; throw Error('must not fall back to another draft'); },
      setBusy() {}, setError() {}, setLoadErrorCode() {}, setProduct() {},
      setMessage(value) { messages.push(value); },
      setBlocked(value) { state.blocked = value; },
      validateInput() { throw Error('submission must be blocked before validation'); },
    };
    vm.runInNewContext(compiled, state);
    await state.run();
    assert.equal(state.values.price, '101');
    assert.equal(state.blocked, true);
    assert.equal(fallbackReads, 0);
    assert.deepEqual(calls, ['commerce_a2ui_status', 'commerce_a2ui_get']);
    assert.ok(messages.some(value => value.includes('所选测算任务尚未恢复')));
  });
}
