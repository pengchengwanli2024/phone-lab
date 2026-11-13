import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { randomUUID } from 'node:crypto';

const source = await readFile('../web/copilot-ui.js', 'utf8');
const flush = () => new Promise(setImmediate);
function setup({ compact = true, selection, catalog, override, query, onModels } = {}) {
  const events = new Map(), calls = [];
  const listeners = { addEventListener(name, fn) { if (!events.has(name)) events.set(name, []); events.get(name).push(fn); }, removeEventListener() {} };
  const escape = v => String(v ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  const ui = { escape, icon: () => '', badge: escape, alert: escape, field: (a, b) => a + b, select: () => '', button: ({ label, attrs }) => '<button ' + Object.entries(attrs).filter(([, v]) => v !== false && v != null).map(([k, v]) => k + '="' + escape(v) + '"').join(' ') + '>' + escape(label) + '</button>' };
  const document = { ...listeners, querySelector: query || (() => null), getElementById: () => null, activeElement: null };
  const window = { ...listeners, CommerceUI: ui, innerWidth: 1440, dispatchEvent() {} };
  const context = { module: 'organization', demo: true, entity: { kind: 'case', id: 'model-qa' } };
  const state = { catalog: catalog ?? [{ id: 'project-default', label: '项目默认', model: 'default-model', selectable: true }], thread: { id: 'thread', context, context_sha256: 'scope', turns: [], model_selection: selection ?? { model_id: 'project-default', available: true, sha256: 'a'.repeat(64) } } };
  vm.runInNewContext(source, { window, document, crypto: { randomUUID }, setInterval() {}, clearInterval() {}, CustomEvent: class {}, localStorage: { getItem: () => null, setItem() {} } });
  const controller = window.CommerceCopilot({ api: async (name, args) => {
    calls.push([name, args]);
    if (override) { const value = await override(name, args); if (value !== undefined) return value; }
    if (name === 'commerce_model_list') return { models: state.catalog };
    if (name === 'commerce_copilot_list') return { threads: [state.thread] };
    if (name === 'commerce_copilot_get' || name === 'commerce_copilot_send') return structuredClone(state.thread);
    throw Error('unexpected API: ' + name);
  }, getContext: () => context, inline: true, compact, scopeLabel: () => '合成模型验收', onModels, repaint() {}, toast() {} });
  const emit = (name, event) => { for (const fn of events.get(name) || []) fn(event); };
  const click = action => { const target = { dataset: { copilotAction: action }, closest: selector => selector === '[data-copilot-action]' ? target : null }; emit('click', { target, preventDefault() {} }); };
  const input = value => emit('input', { target: { id: 'copilot-message', value } });
  const enter = () => emit('keydown', { target: { id: 'copilot-message' }, key: 'Enter', ctrlKey: true, preventDefault() {} });
  const sendButton = () => controller.view().match(/<button[^>]*data-copilot-action="send"[^>]*>/)?.[0];
  controller.open(undefined, { focus: false });
  return { ...state, state, controller, calls, click, input, enter, emit, sendButton };
}

test('explicit model refresh reads the catalog and selection while retaining an unsent draft', async () => {
  const s = setup(); await flush(); s.input('刷新后保留这条草稿');
  s.state.catalog.push({ id: 'local', label: '本地模型', selectable: true });
  s.state.thread.model_selection = { model_id: 'local', available: true, sha256: 'b'.repeat(64) };
  const before = s.calls.length; s.click('models-refresh'); await flush();
  assert.ok(s.calls.slice(before).some(([name]) => name === 'commerce_model_list'));
  assert.ok(s.calls.slice(before).some(([name]) => name === 'commerce_copilot_get'));
  assert.ok(s.controller.view().includes('value="local" selected'));
  assert.ok(s.controller.view().includes('刷新后保留这条草稿'));
  assert.ok(s.calls.every(([name]) => /_(list|get)$/.test(name)));
  s.enter(); await flush();
  assert.equal(s.calls.find(([name]) => name === 'commerce_copilot_send')[1].expected_model_sha256, 'b'.repeat(64));
  s.controller.dispose();
});

for (const compact of [true, false]) test(`unavailable selection blocks button and shortcut without default fallback (${compact ? 'compact' : 'legacy'})`, async () => {
  const s = setup({ compact, selection: { model_id: 'local', label: '本地模型', available: false }, catalog: [{ id: 'project-default', label: '项目默认', selectable: true }, { id: 'local', label: '本地模型', selectable: false, enabled: false }] });
  await flush(); s.input('不要退回默认模型');
  assert.match(s.sendButton(), /disabled/);
  assert.ok(s.controller.view().includes('当前模型不可用'));
  s.click('send'); s.enter(); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 0);
  assert.ok(s.controller.view().includes('不要退回默认模型'));
  s.controller.dispose();
});

test('a removed profile remains visibly selected and cannot silently become the first catalog option', async () => {
  const s = setup({ selection: { model_id: 'removed', label: '已移除的模型', available: false } }); await flush();
  assert.match(s.controller.view(), /value="removed" selected disabled/);
  s.input('保留输入'); s.enter(); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 0);
  s.controller.dispose();
});

test('catalog failure preserves older backend conversation compatibility', async () => {
  const s = setup({ override: async name => { if (name === 'commerce_model_list') throw Error('unknown_tool'); } });
  delete s.state.thread.model_selection; await flush(); s.input('原有配置仍可发送');
  assert.doesNotMatch(s.sendButton(), /disabled/); s.enter(); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 1);
  assert.ok(s.controller.view().includes('模型选项暂不可用'));
  s.controller.dispose();
});

test('refresh recovers a disabled selection without discarding input', async () => {
  const s = setup({ selection: { model_id: 'local', available: false }, catalog: [{ id: 'local', label: '本地模型', selectable: false }] }); await flush(); s.input('启用后再明确发送');
  assert.match(s.sendButton(), /disabled/);
  s.state.catalog = [{ id: 'local', label: '本地模型', selectable: true }]; s.state.thread.model_selection.available = true;
  s.click('models-refresh'); await flush(); assert.doesNotMatch(s.sendButton(), /disabled/);
  assert.ok(s.controller.view().includes('启用后再明确发送')); assert.ok(!s.controller.view().includes('当前模型不可用'));
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 0); s.controller.dispose();
});

test('history shows each run model and frozen profile version, with escaped text', async () => {
  const s = setup();
  s.state.thread.turns = [{ id: 'old', question: '旧问题', run: { id: 'old-run', status: 'completed', model_choice: { label: '<旧模型>', model: 'old-weight', profile_revision: '7' }, result: { answer: '旧回答' } } }, { id: 'new', question: '新问题', run: { id: 'new-run', status: 'completed', result: { answer: '新回答', model: 'actual-legacy-model' } } }];
  await flush(); const html = s.controller.view();
  assert.ok(html.includes('&lt;旧模型&gt;')); assert.ok(html.includes('old-weight')); assert.ok(html.includes('配置版本 7')); assert.ok(html.includes('actual-legacy-model'));
  assert.ok(!html.includes('<旧模型>')); assert.equal(html.split('copilot-run-model').length - 1, 2); s.controller.dispose();
});

test('closing during a catalog refresh discards its late response', async () => {
  let finish, delay = false;
  const s = setup({ override: name => { if (name !== 'commerce_model_list') return; if (delay === 'unavailable') throw Error('temporarily_unavailable'); if (delay) return new Promise(resolve => { finish = resolve; }); } });
  await flush(); delay = true; s.click('models-refresh'); await flush(); s.controller.close();
  finish({ models: [{ id: 'project-default', label: 'stale-result', selectable: false }] }); await flush();
  delay = 'unavailable'; s.controller.open(); await flush(); assert.ok(!s.controller.view().includes('stale-result'));
  s.controller.dispose();
});

test('opening and refreshing the model menu retains its state and draft without creating work', async () => {
  const s = setup(); await flush(); s.input('保留输入与展开菜单');
  s.emit('toggle', { target: { id: 'copilot-model-picker', open: true } });
  assert.match(s.controller.view(), /id="copilot-model-picker" open/);
  s.click('models-refresh'); await flush();
  assert.match(s.controller.view(), /id="copilot-model-picker" open/);
  assert.ok(s.controller.view().includes('保留输入与展开菜单'));
  assert.ok(s.calls.every(([name]) => /_(list|get)$/.test(name))); s.controller.dispose();
});
test('Escape closes the model menu and restores its trigger focus without sending', async () => {
  let open = true, focused = 0;
  const picker = { removeAttribute() { open = false; }, querySelector() { return { focus() { focused++; } }; } };
  const s = setup({ query: selector => selector === '#copilot-model-picker[open]' && open ? picker : null }); await flush(); s.input('退出菜单不发出');
  s.emit('toggle', { target: { id: 'copilot-model-picker', open: true } }); const before = s.calls.length;
  s.emit('keydown', { key: 'Escape', target: { id: 'copilot-model' }, preventDefault() {} });
  assert.equal(open, false); assert.equal(focused, 1); assert.doesNotMatch(s.controller.view(), /id="copilot-model-picker" open/);
  assert.ok(s.controller.view().includes('退出菜单不发出')); assert.equal(s.calls.length, before); s.controller.dispose();
});
test('clicking outside the model menu only dismisses it', async () => {
  let open = true; const picker = { contains: () => false, removeAttribute() { open = false; } };
  const s = setup({ query: selector => selector === '#copilot-model-picker[open]' && open ? picker : null }); await flush();
  s.emit('toggle', { target: { id: 'copilot-model-picker', open: true } }); const before = s.calls.length;
  s.emit('click', { target: { closest: () => null }, preventDefault() {} });
  assert.equal(open, false); assert.doesNotMatch(s.controller.view(), /id="copilot-model-picker" open/); assert.equal(s.calls.length, before); s.controller.dispose();
});

test('workspace model management navigates without opening a private setup or changing the draft', async () => {
  let opened = 0; const s = setup({ onModels: () => { opened++; } }); await flush();
  s.input('返回后仍有这条输入'); const before = s.calls.length; s.click('models'); await flush();
  assert.equal(opened, 1); assert.equal(s.calls.length, before); assert.ok(s.controller.view().includes('返回后仍有这条输入')); s.controller.dispose();
});

test('editing a failed question only fills the composer and keeps an existing draft', async () => {
  const s = setup(); const run = { id: 'failed-run', status: 'failed', error: 'agent_evidence_reference_required' };
  s.state.thread.turns = [{ id: 'failed-turn', question: '补充真实来源再回答', run }]; s.state.thread.latest_run = run; await flush();
  assert.ok(s.controller.view().includes('来源引用')); const before = s.calls.length;
  const clickEdit = () => s.emit('click', { target: { dataset: { copilotAction: 'edit-question', run: 'failed-run' }, closest(selector) { return selector === '[data-copilot-action]' ? this : null; } }, preventDefault() {} });
  clickEdit(); await flush(); assert.match(s.controller.view(), /<textarea[^>]*>补充真实来源再回答<\/textarea>/);
  s.input('已有未发送草稿'); clickEdit(); await flush(); assert.match(s.controller.view(), /<textarea[^>]*>已有未发送草稿<\/textarea>/);
  assert.equal(s.calls.length, before); s.controller.dispose();
});
test('unknown model results do not become a failed result or offer a resend action', async () => {
  const s = setup(); const run = { id: 'unknown-run', status: 'unknown', error: 'synthetic_timeout' };
  s.state.thread.turns = [{ id: 'unknown-turn', question: '核对原请求', run }]; s.state.thread.latest_run = run; await flush();
  assert.ok(s.controller.view().includes('结果尚未确认')); assert.ok(!s.controller.view().includes('data-copilot-action="edit-question"'));
  assert.ok(s.calls.every(([name]) => /_(list|get)$/.test(name))); s.controller.dispose();
});
