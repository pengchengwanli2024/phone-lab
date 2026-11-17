import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const kit = await readFile(new URL('../../ui/kit.js', import.meta.url), 'utf8');
const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const a = { platform: 'ozon', store_ref: 'shop-a', subject_ref: 'product-a' };
const b = { platform: 'ozon', store_ref: 'shop-b', subject_ref: 'product-a' };
const source = (id, kind, scope) => ({ id, kind, scope, label: id, origin_ref: 'private-export:' + id, record_count: 3, version: 1, fresh: true, observed_at: '2026-11-17T00:00:00Z', synthetic: false });
async function harness(file, factory, api, extra = {}) {
  const listeners = {}, calls = [], notices = [], sent = [], assigned = [];
  const document = { documentElement: { dataset: {} }, addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }, querySelector: () => null, querySelectorAll: () => [], getElementById: () => null };
  const window = { matchMedia: () => ({ matches: false, addEventListener() {} }), dispatchEvent() {}, __COMMERCE_LEGACY__: extra.embedded ? {} : null };
  const context = vm.createContext({ window, document, CustomEvent: class {}, setTimeout() {}, clearTimeout() {}, crypto: { randomUUID: () => 'test-only-key' }, parent: { postMessage: value => sent.push(value) }, location: { assign: value => assigned.push(value) } });
  vm.runInContext(kit, context);
  if (factory === 'CommerceBusiness') { vm.runInContext(await readFile(new URL('../../web/businessforms-ui.js', import.meta.url), 'utf8'), context); }
  vm.runInContext(await readFile(new URL('../../web/' + file, import.meta.url), 'utf8'), context);
  const controller = window[factory]({ api: async (name, args) => { calls.push([name, args]); return api(name, args); }, esc, repaint() {}, toast: text => notices.push(text), isActive: () => true, getStatus: () => ({}), knowledgeView: () => '<section>old-directory</section>', modal() {}, closeModal() {} });
  const emit = async (type, target) => { target.matches ||= () => false; for (const fn of listeners[type] || []) await fn({ target, stopImmediatePropagation() {} }); };
  return { controller, calls, notices, sent, assigned, emit };
}
const sourceIds = html => [...html.matchAll(/data-business-source="([^"]+)"/g)].map(match => match[1]);
async function business() {
  return harness('business-ui.js', 'CommerceBusiness', name => {
    assert.equal(name, 'commerce_business_list');
    return { sources: [source('review-a', 'reviews', a), source('review-b', 'reviews', b), source('fact-a', 'facts', a), source('conversation-a', 'conversation', a)], drafts: [] };
  });
}
test('reviews require an explicit scope and show only review sources from that scope', async () => {
  const h = await business(); await h.controller.enter('reviews');
  assert.deepEqual(sourceIds(h.controller.view('reviews')), []);
  await h.emit('change', { id: 'business-source-scope', value: JSON.stringify(['ozon', 'shop-a', 'product-a']) });
  assert.deepEqual(sourceIds(h.controller.view('reviews')), ['review-a']);
  await h.emit('change', { id: 'business-source-kind', value: 'facts' });
  assert.deepEqual(sourceIds(h.controller.view('reviews')), ['fact-a']);
  await h.emit('input', { id: 'business-source-query', value: 'no-such-source' });
  assert.deepEqual(sourceIds(h.controller.view('reviews')), []);
});
test('a forged selection from another scope is rejected without a business write', async () => {
  const h = await business(); await h.controller.enter('reviews');
  await h.emit('change', { id: 'business-source-scope', value: JSON.stringify(['ozon', 'shop-a', 'product-a']) });
  await h.emit('change', { id: 'business-source-review-b', checked: true, dataset: { businessSource: 'review-b' }, matches: () => true });
  assert.match(h.notices.join(' '), /平台.*店铺/);
  assert.ok(h.calls.every(([name]) => name === 'commerce_business_list'));
  assert.doesNotMatch(h.controller.view('reviews'), /data-business-source="review-a" checked/);
});
test('support defaults to conversations and changing scope clears explicit selections', async () => {
  const h = await business(); await h.controller.enter('support');
  await h.emit('change', { id: 'business-source-scope', value: JSON.stringify(['ozon', 'shop-a', 'product-a']) });
  assert.deepEqual(sourceIds(h.controller.view('support')), ['conversation-a']);
  await h.emit('change', { checked: true, dataset: { businessSource: 'conversation-a' }, matches: () => true });
  await h.emit('change', { id: 'business-source-scope', value: JSON.stringify(['ozon', 'shop-b', 'product-a']) });
  assert.match(h.controller.view('support'), /已选 0/);
});
test('connection directory lists each platform and moves the knowledge directory to memory', async () => {
  const h = await harness('connections-ui.js', 'CommerceConnections', name => {
    if (name === 'commerce_platform_catalog') return { providers: [{ id: 'shopify', name: 'Shopify', resources: ['products'], notice: 'read only' }, { id: 'woocommerce', name: 'WooCommerce', resources: ['products'], notice: 'read only' }] };
    if (name === 'commerce_platform_list') return { stores: [{ platform: 'shopify', label: 'Shop A', configured: true, enabled: false, scope_reviewed: false }] };
    assert.equal(name, 'commerce_live_status'); return { configured: true, orders_scope_confirmed: false };
  }, { embedded: true });
  await h.controller.load(); const html = h.controller.view();
  assert.match(html, /Shopify/); assert.match(html, /WooCommerce/); assert.match(html, /Shop A/);
  assert.doesNotMatch(html, /old-directory/);
  await h.emit('click', { closest: () => ({ dataset: { connectionAction: 'knowledge' } }) });
  assert.equal(h.sent[0].type, 'commerce:workspace-navigate'); assert.equal(h.sent[0].tab, 'memory');
  assert.equal(h.calls.length, 3);
});

test('source summaries are bounded, searchable beyond the first page, and never analyze facts', async () => {
  const rows = Array.from({ length: 12 }, (_, index) => source('review-' + index, 'reviews', a));
  rows.push(source('fact-a', 'facts', a));
  const h = await harness('business-ui.js', 'CommerceBusiness', name => {
    assert.equal(name, 'commerce_business_list'); return { sources: rows, drafts: [] };
  });
  await h.controller.enter('reviews');
  await h.emit('change', { id: 'business-source-scope', value: JSON.stringify(['ozon', 'shop-a', 'product-a']) });
  assert.equal(sourceIds(h.controller.view('reviews')).length, 8);
  await h.emit('input', { id: 'business-source-query', value: 'review-11' });
  assert.deepEqual(sourceIds(h.controller.view('reviews')), ['review-11']);
  await h.emit('input', { id: 'business-source-query', value: '' });
  await h.emit('click', { closest: () => ({ dataset: { businessAction: 'source-more' } }) });
  assert.equal(sourceIds(h.controller.view('reviews')).length, 12);
  await h.emit('change', { id: 'business-source-kind', value: 'facts' });
  await h.emit('change', { checked: true, dataset: { businessSource: 'fact-a' }, matches: () => true });
  await h.emit('click', { closest: () => ({ dataset: { businessAction: 'analyze' } }) });
  assert.match(h.notices.join(' '), /只能选评论/);
  assert.ok(h.calls.every(([name]) => name === 'commerce_business_list'));
});

async function setupTheme(scriptName) {
  const windowEvents = {}, documentEvents = {}, pending = [], calls = [];
  const root = { innerHTML: '', addEventListener() {} };
  const document = { documentElement: { dataset: {} }, hidden: false, getElementById: () => root, querySelector: () => root, addEventListener(type, fn) { documentEvents[type] = fn; } };
  const window = { matchMedia: () => ({ matches: false, addEventListener() {} }), dispatchEvent() {}, addEventListener(type, fn) { windowEvents[type] = fn; } };
  const context = vm.createContext({ window, document, CustomEvent: class {}, AbortController, setTimeout() {}, clearTimeout() {}, crypto: { randomUUID: () => 'synthetic-id' }, fetch: async (path, init) => {
    const tool = init.body ? JSON.parse(init.body).tool : undefined; calls.push(tool || path);
    if (tool === 'commerce_ui_get_preferences') return new Promise(resolve => pending.push(theme => resolve({ ok: true, json: async () => ({ theme }) })));
    if (path === '/v1/connections/status') return { ok: false, json: async () => ({ error: 'synthetic-unavailable' }) };
    return { ok: true, json: async () => tool === 'commerce_model_list' ? { models: [] } : path === '/v1/models/accounts' ? { accounts: [] } : tool === 'commerce_platform_catalog' ? { providers: [] } : { stores: [] } };
  } });
  vm.runInContext(kit, context);
  let script = await readFile(new URL('../../web/' + scriptName, import.meta.url), 'utf8');
  vm.runInContext(script, context); await new Promise(setImmediate);
  return { window, windowEvents, documentEvents, pending, calls, root };
}
for (const file of ['model-setup.js', 'platform-setup.js', 'setup.js']) {
  test(file + ' reads preferences on focus and ignores an older theme response', async () => {
    const h = await setupTheme(file);
    if (!h.pending.length) h.windowEvents.focus();
    h.windowEvents.focus();
    h.pending[1]('dark'); await new Promise(setImmediate);
    h.pending[0]('light'); await new Promise(setImmediate);
    assert.equal(h.window.CommerceUI.getTheme().preference, 'dark');
    assert.ok(h.calls.every(name => name !== 'commerce_ui_set_preferences'));
    h.documentEvents.visibilitychange();
    h.pending[2]('system'); await new Promise(setImmediate);
    assert.equal(h.window.CommerceUI.getTheme().preference, 'system');
  });
}
