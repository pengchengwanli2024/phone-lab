import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { randomUUID } from 'node:crypto';

const source = await readFile('../web/copilot-ui.js', 'utf8');
const context = { module: 'organization', demo: true, entity: { kind: 'case', id: 'example-case' } };
const question = '你希望研究哪个市场？';
function setup(send = async thread => thread, field = question) {
  const handlers = new Map(), calls = [];
  const events = { addEventListener(name, fn) { if (!handlers.has(name)) handlers.set(name, []); handlers.get(name).push(fn); }, removeEventListener() {} };
  const document = { ...events, querySelector: () => null, getElementById: () => null, activeElement: null };
  const esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  const ui = { escape: esc, icon: () => '', badge: esc, alert: esc, button: value => `<button>${esc(value.label)}</button>`, field: (label, value) => label + value, input: value => `<input data-copilot-answer="${esc(value['data-copilot-answer'])}">`, select: () => '' };
  const window = { ...events, CommerceUI: ui, innerWidth: 1440, dispatchEvent() {} };
  const run = { id: 'run', status: 'awaiting_input', result: { answer: '请补充市场信息', questions: [question] } };
  const thread = { id: 'thread', title: '市场研究', context, context_sha256: 'example-hash', latest_run: run, turns: [{ id: 'turn', question: '帮我选品', run }], surfaces: [{ surfaceUpdate: { surfaceId: 'reply', components: [{ id: 'root', component: { TextField: { label: { literalString: field } } } }] } }, { beginRendering: { surfaceId: 'reply', root: 'root' } }] };
  vm.runInNewContext(source, { window, document, crypto: { randomUUID }, setInterval() {}, clearInterval() {}, CustomEvent: class {}, localStorage: { getItem: () => 'thread', setItem() {} } });
  const controller = window.CommerceCopilot({ api: async (name, args) => { calls.push([name, args]); if (name === 'commerce_copilot_list') return { threads: [thread] }; if (name === 'commerce_copilot_get') return thread; if (name === 'commerce_copilot_send') return send(thread); throw Error(name); }, getContext: () => context, isActive: () => true, inline: true, compact: true, repaint() {}, scopeLabel: () => 'Example scope', toast() {} });
  const emit = (name, event) => { for (const fn of handlers.get(name) || []) fn(event); };
  const input = value => emit('input', { target: { id: 'copilot-message', value } });
  const enter = extra => emit('keydown', { target: { id: 'copilot-message' }, key: 'Enter', ctrlKey: true, preventDefault() {}, ...extra });
  controller.open(undefined, { focus: false });
  return { controller, calls, input, enter, emit };
}
const flush = () => new Promise(setImmediate);

test('known follow-up questions use the single composer; unrelated generated fields keep their editor', async () => {
  const s = setup(); await flush();
  assert.ok(s.controller.view().includes(question));
  assert.ok(!s.controller.view().includes('data-copilot-answer='));
  assert.ok(!s.controller.view().includes('将补充内容填入输入框'));
  assert.ok(s.controller.view().includes('补充回答'));
  const other = setup(undefined, '其它受控字段'); await flush();
  assert.ok(other.controller.view().includes('data-copilot-answer='));
  s.controller.dispose(); other.controller.dispose();
});

test('IME confirmation and plain Enter do not submit, while explicit shortcut submits once', async () => {
  const s = setup(); await flush(); s.input('俄罗斯市场');
  s.enter({ isComposing: true }); s.enter({ ctrlKey: false });
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 0);
  s.enter({ isComposing: false }); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 1);
  assert.equal(s.calls.at(-1)[1].message, '俄罗斯市场');
  s.controller.dispose();
});

test('text entered during submission and failed submission remain available without automatic retry', async () => {
  let finish;
  const s = setup(thread => new Promise(resolve => { finish = () => resolve(thread); })); await flush();
  s.input('第一条'); s.enter(); await flush(); s.input('下一条，先不发送'); finish(); await flush();
  assert.ok(s.controller.view().includes('下一条，先不发送'));
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 1);
  const failed = setup(async () => { throw Error('test_unavailable'); }); await flush(); failed.input('失败后保留'); failed.enter(); await flush();
  assert.ok(failed.controller.view().includes('失败后保留'));
  assert.equal(failed.calls.filter(([name]) => name === 'commerce_copilot_send').length, 1);
  s.controller.dispose(); failed.controller.dispose();
});
