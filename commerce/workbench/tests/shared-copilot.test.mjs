import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { build } from 'esbuild';

const source = await readFile('../web/copilot-ui.js', 'utf8');
const compiled = await build({ entryPoints: ['src/copilot-scope.ts', 'src/navigation.ts'], bundle: true, write: false, outdir: 'unused', format: 'esm', platform: 'node' });
const imports = await Promise.all(compiled.outputFiles.map(file => import('data:text/javascript;base64,' + Buffer.from(file.text).toString('base64'))));
const { productScope } = imports.find(module => module.productScope);
const { navigation, destinationFor, businessModule } = imports.find(module => module.navigation);

function shared() {
  const handlers = new Map(), timers = new Set(), calls = [];
  const target = () => ({ addEventListener(name, fn) { if (!handlers.has(name)) handlers.set(name, new Set()); handlers.get(name).add(fn); }, removeEventListener(name, fn) { handlers.get(name)?.delete(fn); } });
  const document = { ...target(), querySelector: () => null, getElementById: () => null, activeElement: null };
  const escape = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  const ui = { escape, icon: () => '', badge: value => escape(value), alert: value => escape(value), button: value => `<button>${escape(value.label)}</button>`, field: (label, value) => label + value, input: () => '', select: () => '' };
  const window = { ...target(), CommerceUI: ui, innerWidth: 1440, dispatchEvent() {} };
  vm.runInNewContext(source, { window, document, setInterval(fn) { timers.add(fn); return fn; }, clearInterval(fn) { timers.delete(fn); }, CustomEvent: class {}, localStorage: { getItem: () => null, setItem() {} } });
  let context = { module: 'overview', demo: false };
  const controller = window.CommerceCopilot({ api: async name => { calls.push(name); if(name==='commerce_model_list')return {models:[]}; assert.equal(name, 'commerce_copilot_list'); return { threads: [] }; }, getContext: () => context, isActive: () => true, inline: true, compact: true, repaint() {}, scopeLabel: () => 'Current scope', renderContext: () => '', toast() {}, modal() {}, closeModal() {} });
  return { controller, handlers, timers, calls, context(value) { context = value; controller.contextChanged(); }, input(value) { for (const fn of handlers.get('input') || []) fn({ target: { id: 'copilot-message', value } }); } };
}

test('unsent new-conversation drafts stay in their module and return intact without a model request', async () => {
  const s = shared(); s.controller.open(undefined, { focus: false }); await new Promise(setImmediate);
  s.input('overview-only-draft'); assert.ok(s.controller.view().includes('overview-only-draft'));
  s.context({ module: 'orders', demo: false }); assert.ok(!s.controller.view().includes('overview-only-draft'));
  s.input('orders-only-draft'); s.context({ module: 'overview', demo: false });
  assert.ok(s.controller.view().includes('overview-only-draft')); assert.ok(!s.controller.view().includes('orders-only-draft'));
  assert.ok(s.calls.every(name => ['commerce_copilot_list','commerce_model_list'].includes(name))); s.controller.dispose();
});
test('disposing a shared assistant releases polling and all document/window listeners', () => {
  const s = shared(); assert.equal(s.timers.size, 1); assert.ok([...s.handlers.values()].some(value => value.size));
  s.controller.dispose(); assert.equal(s.timers.size, 0); assert.ok([...s.handlers.values()].every(value => value.size === 0));
});
test('bound cost assistant uses the original product conversation scope, not a destination alias', () => {
  const product = { case: { id: 'case-a', scope: { platform: 'ozon', market: 'RU', synthetic: false } } };
  assert.deepEqual(productScope({ module: 'operations', demo: true, entity: { kind: 'case', id: 'case-a' } }, product), { module: 'organization', demo: false, platform: 'ozon', market: 'RU', entity: { kind: 'case', id: 'case-a' } });
});
test('another product cannot supply the assistant scope', () => {
  assert.throws(() => productScope({ module: 'operations', entity: { kind: 'case', id: 'case-a' } }, { case: { id: 'case-b', scope: {} } }), /workspace_source_changed/);
});
test('seven destinations retain every old route exactly once, including cost deep links', () => {
  const routes = navigation.flatMap(destination => destination.items);
  assert.equal(navigation.length, 7); assert.equal(routes.length, 21); assert.equal(new Set(routes).size, 21);
  assert.equal(destinationFor('support').id, 'orders'); assert.equal(destinationFor('live').id, 'orders');
  assert.equal(destinationFor('connections').id, 'skills'); assert.equal(destinationFor('old:operations').id, 'workspace');
  assert.equal(destinationFor('restock').id, 'orders');
  assert.equal(businessModule('restock'), 'operations'); assert.equal(businessModule('workspace'), 'organization');
});
