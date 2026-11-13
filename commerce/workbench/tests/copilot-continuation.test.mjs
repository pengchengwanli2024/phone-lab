import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import vm from 'node:vm';

const source = await readFile('../web/copilot-ui.js', 'utf8');
const flush = () => new Promise(setImmediate);
const clone = value => JSON.parse(JSON.stringify(value ?? {}));

async function setup() {
  const events = new Map(), calls = [], dialogs = [];
  const listeners = { addEventListener(name, fn) { if (!events.has(name)) events.set(name, []); events.get(name).push(fn); }, removeEventListener() {} };
  const escape = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  const ui = { escape, icon: () => '', badge: escape, alert: escape, field: (a, b) => a + b, select: () => '', button: ({ label, attrs }) => '<button ' + Object.entries(attrs).filter(([, v]) => v !== false && v != null).map(([k, v]) => k + '="' + escape(v) + '"').join(' ') + '>' + escape(label) + '</button>' };
  const document = { ...listeners, querySelector: () => null, getElementById: () => null, activeElement: null };
  const window = { ...listeners, CommerceUI: ui, innerWidth: 1440, dispatchEvent() {} };
  const original = { module: 'organization', demo: true, entity: { kind: 'case', id: 'synthetic-original' } };
  let page = clone(original);
  const run = { id: 'run-a', status: 'awaiting_input', result_sha256: 'result-hash', result: { answer: '请补充预算。', questions: ['预算是多少？'], proposals: [{ id: 'P1', operation: 'report', reason: '合成审阅建议', input: {} }] } };
  const thread = { id: 'thread-a', title: '合成待补充会话', context: original, context_sha256: 'original-scope', latest_run: run, turns: [{ id: 'turn-a', question: '先核对资料', run }], model_selection: { model_id: 'project-default', available: true, sha256: 'a'.repeat(64) } };
  vm.runInNewContext(source, { window, document, crypto: { randomUUID }, setInterval() {}, clearInterval() {}, CustomEvent: class {}, localStorage: { getItem: () => 'thread-a', setItem() {} } });
  const controller = window.CommerceCopilot({ api: async (name, args) => {
    calls.push({ name, args: clone(args) });
    if (name === 'commerce_model_list') return { models: [{ id: 'project-default', label: '项目默认', selectable: true }] };
    if (name === 'commerce_copilot_list') return { threads: [clone(thread)] };
    if (name === 'commerce_copilot_get' || name === 'commerce_copilot_send') return clone(thread);
    throw Error('unexpected API: ' + name);
  }, inline: true, compact: true, getContext: () => page, scopeLabel: () => '合成会话范围', repaint() {}, toast() {}, modal: (...args) => dialogs.push(args), closeModal() {} });
  const emit = (name, event) => { for (const fn of events.get(name) || []) fn(event); };
  const input = value => emit('input', { target: { id: 'copilot-message', value } });
  const enter = (extra = {}) => emit('keydown', { key: 'Enter', ctrlKey: true, target: { id: 'copilot-message' }, preventDefault() {}, ...extra });
  const click = (action, data = {}) => { const target = { dataset: { copilotAction: action, ...data }, closest: selector => selector === '[data-copilot-action]' ? target : null }; emit('click', { target, preventDefault() {} }); };
  const button = action => controller.view().match(new RegExp('<button[^>]*data-copilot-action="' + action + '"[^>]*>'))?.[0];
  controller.open(undefined, { focus: false }); await flush();
  assert.ok(calls.some(c => c.name === 'commerce_copilot_get'), 'fixture must load the original conversation before navigation');
  return { controller, calls, dialogs, thread, input, enter, click, emit, button, page(value) { page = clone(value); controller.contextChanged(); } };
}

const elsewhere = { module: 'organization', demo: true, entity: { kind: 'case', id: 'synthetic-other' } };

test('explicitly reopening a saved clarification allows a direct reply to its original thread and scope', async () => {
  const s = await setup(); s.page(elsewhere); await s.controller.openThread('thread-a');
  s.input('预算500元，继续原来的工作。');
  assert.doesNotMatch(s.button('send'), /disabled/);
  s.enter(); await flush();
  const sends = s.calls.filter(c => c.name === 'commerce_copilot_send');
  assert.equal(sends.length, 1);
  assert.equal(sends[0].args.thread_id, 'thread-a');
  assert.equal(sends[0].args.context_sha256, 'original-scope');
  assert.equal(sends[0].args.message, '预算500元，继续原来的工作。');
  assert.equal(sends[0].args.expected_model_sha256, 'a'.repeat(64));
  assert.equal(s.calls.filter(c => ['commerce_copilot_open', 'commerce_copilot_context'].includes(c.name)).length, 0);
  s.controller.dispose();
});

test('navigation without an explicit saved-conversation selection still blocks cross-scope send', async () => {
  const s = await setup(); s.input('尚未发送的原会话补充'); s.page(elsewhere);
  assert.match(s.button('send'), /disabled/); s.enter(); s.click('send'); await flush();
  assert.equal(s.calls.filter(c => c.name === 'commerce_copilot_send').length, 0);
  assert.ok(s.controller.view().includes('尚未发送的原会话补充')); s.controller.dispose();
});

test('explicit original-thread reply does not authorize proposals against a different page scope', async () => {
  const s = await setup(); s.page(elsewhere); await s.controller.openThread('thread-a'); s.input('可回复原会话');
  assert.doesNotMatch(s.button('send'), /disabled/);
  assert.match(s.button('review'), /disabled/);
  s.click('review', { run: 'run-a', proposal: 'P1' }); await flush();
  assert.equal(s.dialogs.length, 0);
  s.click('apply'); await flush();
  assert.equal(s.calls.filter(c => c.name === 'commerce_copilot_apply').length, 0); s.controller.dispose();
});

test('a later page navigation or changed thread context invalidates the original-thread reply selection', async () => {
  const s = await setup(); s.page(elsewhere); await s.controller.openThread('thread-a'); s.input('保留未发补充');
  assert.doesNotMatch(s.button('send'), /disabled/);
  s.page({ ...elsewhere, market: 'RU' }); assert.match(s.button('send'), /disabled/);
  await s.controller.openThread('thread-a'); assert.doesNotMatch(s.button('send'), /disabled/);
  s.thread.context_sha256 = 'changed-scope'; s.click('models-refresh'); await flush();
  assert.match(s.button('send'), /disabled/); assert.ok(s.controller.view().includes('保留未发补充'));
  s.enter(); await flush(); assert.equal(s.calls.filter(c => c.name === 'commerce_copilot_send').length, 0); s.controller.dispose();
});

test('IME confirmation keeps the original-thread draft and only an explicit send submits it', async () => {
  const s = await setup(); s.page(elsewhere); await s.controller.openThread('thread-a'); s.input('中文补充预算');
  s.emit('compositionstart', { target: { id: 'copilot-message' } }); s.enter(); s.enter({ isComposing: true });
  s.emit('compositionend', { target: { id: 'copilot-message' } }); s.enter({ keyCode: 229 });
  await flush(); assert.equal(s.calls.filter(c => c.name === 'commerce_copilot_send').length, 0);
  assert.ok(s.controller.view().includes('中文补充预算'));
  s.enter(); await flush(); assert.equal(s.calls.filter(c => c.name === 'commerce_copilot_send').length, 1); s.controller.dispose();
});
