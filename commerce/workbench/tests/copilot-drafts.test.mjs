import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { randomUUID } from 'node:crypto';

const source = await readFile(process.env.COPILOT_SOURCE || '../web/copilot-ui.js', 'utf8');
const flush = () => new Promise(setImmediate);
function mount(storage, scope = { module: 'overview', demo: false }, sendError = false, openGate) {
  const handlers = new Map(), calls = [];
  const events = { addEventListener(name, fn) { if (!handlers.has(name)) handlers.set(name, new Set()); handlers.get(name).add(fn); }, removeEventListener(name, fn) { handlers.get(name)?.delete(fn); } };
  const escape = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  const ui = { escape, icon: () => '', badge: escape, alert: escape, button: ({ label }) => `<button>${escape(label)}</button>` };
  const document = { ...events, querySelector: () => null, getElementById: () => null, activeElement: null };
  const window = { ...events, CommerceUI: ui, dispatchEvent() {}, innerWidth: 1440 }; window.parent = window;
  vm.runInNewContext(source, { window, document, crypto: { randomUUID }, localStorage: storage, setTimeout, clearTimeout, setInterval() {}, clearInterval() {}, CustomEvent: class {} });
  const thread = { id: 'draft-test-thread', context: scope, context_sha256: 'scope', turns: [], model_selection: { model_id: 'project-default', available: true } };
  const controller = window.CommerceCopilot({ compact: true, inline: true, repaint() {}, getContext: () => scope, scopeLabel: () => '测试范围', api: async (name, args) => {
    calls.push([name, args]);
    if (name === 'commerce_model_list') return { models: [{ id: 'project-default', label: '项目默认', selectable: true }] };
    if (name === 'commerce_copilot_list') return { threads: [] };
    if (name === 'commerce_copilot_get') return args.thread_id === thread.id ? thread : { ...thread, id: args.thread_id, context: { ...scope, entity: { kind: 'case', id: 'other-product' } } };
    if (name === 'commerce_copilot_open') { if(openGate) await openGate; return thread; }
    if (name === 'commerce_copilot_send') { if (sendError) throw Error('offline'); return thread; }
    throw Error(name);
  } });
  const emit = (name, event) => { for (const fn of handlers.get(name) || []) fn(event); };
  const input = value => emit('input', { target: { id: 'copilot-message', value } });
  const send = () => emit('keydown', { target: { id: 'copilot-message' }, key: 'Enter', ctrlKey: true, preventDefault() {} });
  const create = () => { const target={dataset:{copilotAction:'new'},closest:selector=>selector==='[data-copilot-action]'?target:null};emit('click',{target,preventDefault(){}}); };
  controller.open(undefined, { focus: false }); controller.view();
  return { controller, calls, input, send, create, window, emit };
}
function store() { const values = new Map(); return { values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }; }

test('a remounted composer restores its own unsent draft without opening or sending a conversation', async () => {
  const storage = store(), first = mount(storage); await flush(); first.input('刷新后保留的中文草稿'); await flush(); first.controller.dispose();
  const second = mount(storage); await flush();
  assert.ok(second.controller.view().includes('刷新后保留的中文草稿'));
  assert.equal(second.calls.filter(([name]) => /commerce_copilot_(open|send)/.test(name)).length, 0); second.controller.dispose();
});
test('page, example mode and product scope drafts remain separate after remount', async () => {
  const storage = store(), real = mount(storage); await flush(); real.input('真实运营台草稿'); await flush(); real.controller.dispose();
  for (const scope of [{ module: 'overview', demo: true }, { module: 'pilots', demo: false }, { module: 'organization', demo: false, entity: { kind: 'case', id: 'other' } }]) {
    const other = mount(storage, scope); await flush(); assert.ok(!other.controller.view().includes('真实运营台草稿')); other.controller.dispose();
  }
});
test('typing while New is opening keeps the latest draft, including an initially empty composer', async () => {
  for(const initial of ['', '创建前输入']){
    let finish;const gate=new Promise(resolve=>{finish=resolve});const storage=store(),s=mount(storage,undefined,false,gate);await flush();if(initial)s.input(initial);await flush();s.create();await flush();s.input('新建过程中继续输入');await flush();finish();await flush();await flush();
    assert.ok(s.controller.view().includes('新建过程中继续输入'));assert.ok([...storage.values.values()].includes('新建过程中继续输入'));assert.equal(s.calls.filter(([name])=>name==='commerce_copilot_send').length,0);s.controller.dispose();
  }
});
test('another window cannot overwrite a newer stored draft and keeps its own input visible', async () => {
  const storage = store(), a = mount(storage), b = mount(storage); await flush(); a.input('第一个窗口的新草稿'); await flush(); b.input('第二个窗口的输入'); await flush();
  assert.ok(b.controller.view().includes('第二个窗口的输入')); assert.ok(b.controller.view().includes('草稿保存遇到冲突'));
  assert.ok([...storage.values.values()].includes('第一个窗口的新草稿')); a.controller.dispose(); b.controller.dispose();
});
test('late storage reads do not replace newly typed input', async () => {
  const storage = store(); storage.getItem = key => key.startsWith('commerce-copilot-draft-v1:') ? '未读到的旧草稿' : null;
  const s = mount(storage); s.input('刚输入的新内容'); await flush();
  assert.ok(s.controller.view().includes('刚输入的新内容')); assert.equal(storage.values.size, 0); s.controller.dispose();
});
test('confirmed submission clears only its draft; failed submission remains recoverable', async () => {
  for (const failed of [false, true]) {
    const storage = store(), s = mount(storage, undefined, failed); await flush(); s.input('发送状态验收'); await flush(); s.send(); await flush(); await flush();
    assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 1);
    assert.equal([...storage.values.values()].includes('发送状态验收'), failed); s.controller.dispose();
  }
});
test('opaque draft responses require the expected parent and nonce', async () => {
  const s = mount(store()); const sent = []; s.window.parent = { postMessage: message => sent.push(message) };
  const storage = s.window.CommerceCopilotDraftStorage(s.window); let settled = false;
  const result = storage.request('read', 'commerce-copilot-draft-v1:new:{"module":"overview","demo":false}').then(value => { settled = true; return value; });
  const message = { type: 'commerce:copilot-draft-result', nonce: '__COMMERCE_BRIDGE_NONCE__', id: sent[0].id, value: '合法草稿' };
  s.emit('message', { source: {}, data: message }); s.emit('message', { source: s.window.parent, data: { ...message, nonce: 'wrong' } }); await Promise.resolve(); assert.equal(settled, false);
  s.emit('message', { source: s.window.parent, data: message }); assert.equal(await result, '合法草稿');
  await assert.rejects(storage.request('read', 'auth.token'), /invalid_draft_key/); storage.dispose(); s.controller.dispose();
});

test('a composition completing after an external thread switch persists only in its original draft', async () => {
  const storage = store(), s = mount(storage); await flush();
  await s.controller.openThread('draft-test-thread'); await flush();
  s.input('原商品草稿'); await flush();
  s.emit('compositionstart', { target: { id: 'copilot-message', value: '原商品草稿' } });
  await s.controller.openThread('other-draft-thread'); await flush();
  s.input('原商品中文完成');
  s.emit('compositionend', { target: { id: 'copilot-message', value: '原商品中文完成' } }); await flush();
  assert.equal(storage.values.get('commerce-copilot-draft-v1:draft-test-thread'), '原商品中文完成');
  assert.notEqual(storage.values.get('commerce-copilot-draft-v1:other-draft-thread'), '原商品中文完成');
  await s.controller.openThread('draft-test-thread'); assert.ok(s.controller.view().includes('原商品中文完成'));
  s.controller.dispose();
  const restored = mount(storage); await flush(); await restored.controller.openThread('other-draft-thread'); await flush();
  assert.ok(!restored.controller.view().includes('原商品中文完成'));
  await restored.controller.openThread('draft-test-thread'); restored.controller.view(); await flush(); assert.ok(restored.controller.view().includes('原商品中文完成')); restored.controller.dispose();
});

test('closing during composition does not leave the reopened composer unable to send', async () => {
  const s = mount(store()); await flush();
  s.input('关闭前输入');
  s.emit('compositionstart', { target: { id: 'copilot-message', value: '关闭前输入' } });
  s.controller.close(); s.controller.open(undefined, { focus: false }); await flush();
  s.send(); await flush(); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 1);
  s.controller.dispose();
});

test('a long editor never sends a different conversation draft after an external switch', async()=>{
  const storage=store(),s=mount(storage);await flush();await s.controller.openThread('draft-test-thread');await flush();s.input('VISIBLE A QUESTION');await flush();
  const target={dataset:{copilotAction:'expand-editor'},closest:selector=>selector==='[data-copilot-action]'?target:null};s.emit('click',{target,preventDefault(){}});
  await s.controller.openThread('other-draft-thread');await flush();s.input('UNSENT B QUESTION');await flush();
  s.emit('keydown',{target:{id:'copilot-expanded-message',dataset:{copilotDraftKey:'draft-test-thread'}},key:'Enter',ctrlKey:true,preventDefault(){}});await flush();await flush();
  assert.equal(s.calls.filter(([name])=>name==='commerce_copilot_send').length,0);
  assert.equal(storage.values.get('commerce-copilot-draft-v1:other-draft-thread'),'UNSENT B QUESTION');
  assert.equal(storage.values.get('commerce-copilot-draft-v1:draft-test-thread'),'VISIBLE A QUESTION');s.controller.dispose();
});
