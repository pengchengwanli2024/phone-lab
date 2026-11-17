import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { randomUUID } from 'node:crypto';

const source = await readFile('../web/copilot-ui.js', 'utf8');
const reading = await readFile('../web/copilot-interactions.js', 'utf8');
const capabilitySource = await readFile('../web/copilot-capabilities.js', 'utf8');
const flush = () => new Promise(setImmediate);
const esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
async function fixture({ status = 'completed', materials = [], send, capabilities = false, legacyEvents = false } = {}) {
  const handlers = new Map(), calls = [], modals = [], toasts = [], storage = new Map();
  const events = { addEventListener(name, fn) { if (!handlers.has(name)) handlers.set(name, []); handlers.get(name).push(fn); }, removeEventListener() {} };
  const document = { ...events, querySelector: () => null, getElementById: () => null, activeElement: null };
  const ui = { escape: esc, icon: () => '', badge: esc, alert: esc,
    button: v => `<button ${Object.entries(v.attrs || {}).map(([k, value]) => `${k}="${esc(value)}"`).join(' ')}>${esc(v.label)}</button>`,
    field: (label, value) => label + value, input: v => `<input id="${v.id}">`, select: () => '' };
  const context = { module: 'intelligence', demo: true };
  const run = { id: 'run', status, parameters: { page_context: { page: 'intelligence', demo: true, filters: { country: 'RU' }, source_refs: { news: 'a'.repeat(64) } } }, created: Date.now() / 1000, result: { answer: '# Answer\n\nA **readable** response', questions: [] }, trace: [] };
  const thread = { id: 'thread', updated: Date.now()/1000, context, context_sha256: 'scope', model_selection: { model_id: 'fixed', sha256: 'model', revision: '1' },
    interaction_capabilities: { followups: true, materials: true }, materials,
    followups: { revision: 1, items: [], can_steer: true, paused: false }, latest_run: run, turns: [{ id: 'turn', question: 'Previous', run }] };
  const window = { ...events, CommerceUI: ui, innerWidth: 1440, dispatchEvent() {}, navigator: { clipboard: { writeText: async value => { window.copied = value; } } } };
  let polling;
  vm.runInNewContext(reading + '\n' + (capabilities?capabilitySource:'') + '\n' + source, { window, document, crypto: { randomUUID }, setTimeout, clearTimeout, setInterval(fn) {polling=fn;}, clearInterval() {}, CustomEvent: class {},
    localStorage: { getItem: k => storage.get(k) || null, setItem: (k, v) => storage.set(k, v) } });
  const controller = window.CommerceCopilot({ ui, inline: true, compact: true, isActive: () => true, getContext: () => context,
    getPageContext: () => ({ page: 'intelligence', demo: true, filters: { country: 'RU' }, source_refs: { news: 'a'.repeat(64) } }),
    repaint() {}, scopeLabel: () => 'Intelligence example', toast: message => toasts.push(message), modal: (...args) => modals.push(args), closeModal() {},
    api: async (name, args) => {
      calls.push([name, args]);
      if(name==='commerce_copilot_events'&&legacyEvents)throw Object.assign(Error('unknown_tool'),{code:'unknown_tool'});
      if (name === 'commerce_model_list') return { models: [{ id: 'fixed', label: 'Fixed model', selectable: true }, { id: 'other', label: 'Other model', selectable: true }], default_model_id: 'fixed' };
      if(name === 'commerce_copilot_capabilities')return {schema:'commerce-copilot-capabilities-v1',modules:[{id:'orders',label:'订单',description:'订单范围'}],items:[{id:'mcp:commerce',kind:'mcp',name:'共享业务工具',description:'沿当前范围',status:'available',selectable:true}],next_offset:null};
      if(name === 'commerce_copilot_capability_check')return {capability_ids:args.capability_ids,selection_sha256:'capability-version',available:true,capabilities:[{id:'mcp:commerce',name:'共享业务工具'}]};
      if (name === 'commerce_copilot_list') return { threads: [thread], interaction_capabilities: { followups: true, materials: true } };
      if (['commerce_copilot_get', 'commerce_copilot_open', 'commerce_copilot_model'].includes(name)) return thread;
      if (name === 'commerce_copilot_send') return send ? send(thread) : thread;
      if (name === 'commerce_copilot_followup_add') return { revision: 2, items: [{ id: 'queued', mode: args.mode, message: args.message, status: args.mode === 'steer' ? 'waiting' : 'queued' }], can_steer: true };
      if (name === 'commerce_copilot_material_get') return { ...materials[0], text: '<literal reference>' };
      throw Error(name);
    } });
  const emit = (name, value) => { for (const fn of handlers.get(name) || []) fn(value); };
  const input = text => emit('input', { target: { id: 'copilot-message', value: text, dataset: {} } });
  const click = (action, extra = {}) => emit('click', { preventDefault() {}, target: { closest: selector => selector === '[data-copilot-action]' ? { dataset: { copilotAction: action, ...extra }, closest: () => null } : null } });
  const capClick = (action,extra={}) => {const target={dataset:{copilotCapabilityAction:action,...extra},closest:selector=>selector==='[data-copilot-capability-action]'?target:null};emit('click',{preventDefault(){},target});};
  const key = extra => emit('keydown', { target: { id: 'copilot-message' }, key: 'Enter', preventDefault() {}, ...extra });
  controller.open(undefined, { focus: false }); await flush(); await controller.openThread('thread'); await flush();
  return { controller, calls, modals, toasts, storage, emit, input, click, capClick, key, window, poll:()=>polling() };
}

test('a running reply accepts a separately acknowledged queue or current-run supplement', async () => {
  const s = await fixture({ status: 'running' });
  s.input('下一轮单独处理'); s.key({ ctrlKey: true }); await flush();
  const queued = s.calls.find(([name]) => name === 'commerce_copilot_followup_add');
  assert.equal(queued?.[1].mode, 'queue'); assert.equal(queued[1].after_run_id, 'run');
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 0);
  assert.match(s.controller.view(), /下一轮单独处理/);
  s.input('当前回答请简洁'); s.click('steer'); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_followup_add').at(-1)[1].mode, 'steer');
  s.controller.dispose();
});

test('send-key preference keeps IME safe and retains the explicit shortcut', async () => {
  const s = await fixture(); s.input('保留输入法确认');
  s.emit('change', { target: { id: 'copilot-send-key', value: 'enter' } });
  s.key({ isComposing: true }); s.key({ shiftKey: true }); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 0);
  s.key({ isComposing: false }); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 1);
  assert.equal(s.storage.get('commerce-copilot-send-key-v1'), 'enter'); s.controller.dispose();
});

test('context details expose the bound filters and source versions without a model request', async () => {
  const s = await fixture(); s.click('context-details'); await flush();
  assert.match(s.modals.at(-1)?.[1] || '', /RU/);
  assert.match(s.modals.at(-1)?.[1] || '', /aaaaaaaa/);
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 0); s.controller.dispose();
});

test('history leaves the current composer available and long input shows its real limit', async () => {
  const s = await fixture(); s.input('x'.repeat(1900)); s.click('history'); await flush();
  const view = s.controller.view(); assert.match(view, /copilot-message/); assert.match(view, /1900\s*\/\s*2000/);
  s.controller.dispose();
});

test('only explicitly selected immutable material IDs travel on Send', async () => {
  const id = 'b'.repeat(32), s = await fixture({ materials: [{ id, kind: 'attachment', filename: '<notes>.txt', sha256: 'sha', extraction_status: 'completed', model_usable: true }] });
  s.click('material-select', { material: id }); s.input('请总结资料'); s.key({ metaKey: true }); await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls.find(([name]) => name === 'commerce_copilot_send')[1].material_ids)), [id]);
  s.click('material-preview', { material: id }); await flush();
  assert.match(s.modals.at(-1)?.[1] || '', /&lt;literal reference>/); s.controller.dispose();
});

test('answer reading supports safe formatting and copy preserves the original text', async () => {
  const s = await fixture(); assert.match(s.controller.view(), /<h1>Answer<\/h1>/);
  s.click('copy-answer', { run: 'run' }); await flush();
  assert.equal(s.window.copied, '# Answer\n\nA **readable** response'); s.controller.dispose();
});

test('the shared capability picker freezes the same explicit selection on send and queue', async () => {
  for(const status of ['completed','running']){
    const s=await fixture({status,capabilities:true});s.capClick('toggle');await flush();s.capClick('tab',{tab:'tools'});s.capClick('select',{capabilityId:'mcp:commerce'});await flush();await flush();
    s.input('按所选工具核对范围');s.key({ctrlKey:true});await flush();await flush();
    const sent=s.calls.find(([name])=>name===(status==='running'?'commerce_copilot_followup_add':'commerce_copilot_send'));
    assert.deepEqual(JSON.parse(JSON.stringify(sent?.[1].capability_ids)),['mcp:commerce']);
    assert.equal(sent[1].expected_capability_sha256,'capability-version');s.controller.dispose();
  }
});

test('fixing a conversation module leaves the original run alone and can return to automatic scope', async () => {
  const s=await fixture({status:'running',capabilities:true});s.capClick('module',{module:'orders'});await flush();await flush();
  assert.match(s.controller.view(),/固定模块/);
  assert.equal(s.calls.filter(([name])=>name==='commerce_copilot_cancel').length,0);
  s.capClick('module',{module:''});await flush();await flush();
  assert.doesNotMatch(s.controller.view(),/固定模块/);s.controller.dispose();
});
test('a backend without incremental events falls back to the original request read without resending', async()=>{
  const s=await fixture({status:'running',legacyEvents:true});const before=s.calls.filter(([name])=>name==='commerce_copilot_get').length;
  await s.poll();
  assert.equal(s.calls.filter(([name])=>name==='commerce_copilot_get').length,before+1);
  assert.equal(s.calls.filter(([name])=>name==='commerce_copilot_send').length,0);
  assert.doesNotMatch(s.controller.view(),/当前共享后台尚未启用运营助手|状态读取未完成/);s.controller.dispose();
});
