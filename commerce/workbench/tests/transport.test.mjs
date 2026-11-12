import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createInvoke } from '../src/transport.mjs';

function target(embedded = false) {
  const listeners = new Set(), sent = [];
  const t = { crypto: { randomUUID: () => 'test-request' }, addEventListener: (_name, fn) => listeners.add(fn), removeEventListener: (_name, fn) => listeners.delete(fn) };
  t.parent = embedded ? { postMessage: message => sent.push(message) } : t;
  return { t, sent, message: event => { for (const fn of listeners) fn(event); } };
}
test('browser sends the same tool and arguments to the authenticated local API', async () => {
  const { t } = target(); let request;
  const invoke = createInvoke({ target: t, fetcher: async (url, options) => { request = { url, ...options }; return { ok: true, json: async () => ({ status: 'HOLD' }) }; } });
  assert.equal((await invoke('commerce_unit_economics', { input: { currency: 'USD' } })).status, 'HOLD');
  assert.equal(request.url, '/v1/invoke'); assert.equal(JSON.parse(request.body).arguments.input.currency, 'USD'); invoke.dispose();
});
test('failed mutations are never resent by the transport', async () => {
  const { t } = target(); let calls = 0;
  const invoke = createInvoke({ target: t, fetcher: async () => { calls++; throw Error('network unavailable'); } });
  await assert.rejects(invoke('commerce_copilot_send', { message: 'test' }), /network unavailable/);
  assert.equal(calls, 1); invoke.dispose();
});
test('opaque iframe rejects responses from a different source or nonce', async () => {
  const fixture = target(true); const invoke = createInvoke({ target: fixture.t, fetcher: () => assert.fail('must use bridge'), nonce: 'known-nonce', timeoutMs: 200 });
  let settled = false; const result = invoke('commerce_task_list').then(value => { settled = true; return value; });
  fixture.message({ source: {}, data: { type: 'commerce:result', id: 'test-request', nonce: 'known-nonce', result: 'wrong source' } });
  fixture.message({ source: fixture.t.parent, data: { type: 'commerce:result', id: 'test-request', nonce: 'wrong', result: 'wrong nonce' } });
  await Promise.resolve(); assert.equal(settled, false);
  fixture.message({ source: fixture.t.parent, data: { type: 'commerce:result', id: 'test-request', nonce: 'known-nonce', result: { tasks: [] } } });
  assert.deepEqual(await result, { tasks: [] }); assert.equal(fixture.sent.length, 1); invoke.dispose();
});
test('an unacknowledged iframe write stays unknown and is not retried', async () => {
  const { t, sent } = target(true); const invoke = createInvoke({ target: t, fetcher: () => assert.fail(), timeoutMs: 5 });
  await assert.rejects(invoke('commerce_copilot_send'), /request_outcome_unknown/);
  assert.equal(sent.length, 1); invoke.dispose();
});
