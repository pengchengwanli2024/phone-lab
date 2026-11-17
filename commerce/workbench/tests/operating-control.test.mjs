import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import React from 'react';

// Execute the real component closures with scope-isolated hooks. Browser layout
// and native/mobile approval acceptance are separate integration checks.
let current, invoke, keySequence = 0;
const hooks = { ...React,
  useState(initial) { const owner = current, index = owner.index++; owner.slots[index] ??= { value: typeof initial === 'function' ? initial() : initial }; return [owner.slots[index].value, value => { owner.writes++; const next = typeof value === 'function' ? value(owner.slots[index].value) : value; if (!Object.is(next, owner.slots[index].value)) { owner.slots[index].value = next; owner.dirty = true; } }]; },
  useRef(value) { return current.slots[current.index++] ??= { current: value }; },
  useEffect(callback, dependencies) { const owner = current, index = owner.index++, old = owner.slots[index]; if (old && dependencies?.length === old.dependencies?.length && dependencies.every((value, i) => Object.is(value, old.dependencies[i]))) return; const slot = { dependencies }; owner.slots[index] = slot; owner.effects.push(() => { old?.cleanup?.(); slot.cleanup = callback(); }); },
};
const require = createRequire(import.meta.url);
const compiled = await build({ entryPoints: ['src/operating-control.tsx'], bundle: true, write: false, format: 'cjs', platform: 'node', external: ['react'], loader: { '.css': 'empty' }, plugins: [{ name: 'operating-control-api', setup(builder) { builder.onResolve({ filter: /^\.\/api$/ }, () => ({ path: 'operating-control-test-api', external: true })); } }] });
const module = { exports: {} };
vm.runInNewContext(compiled.outputFiles[0].text, { module, exports: module.exports, require: name => name === 'react' ? hooks : name === 'operating-control-test-api' ? { api: (...args) => invoke(...args), newKey: () => 'test-key-' + ++keySequence, errorText: () => '读取未完成，请核对连接。' } : require(name), window: { CommerceUI: { icon: () => '' } }, Error, TypeError });
const { OperatingControl, operatingMoney } = module.exports;
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const settle = () => new Promise(resolve => setImmediate(resolve));
const snapshot = (label = '真实任务', cap = '1234.50') => ({ scope: { platform: 'ozon', market: 'RU', fulfillment: 'OGL', inventory_location: '公司本地', sku_status: 'pending', logistics_status: 'pending' }, budget: { configured: true, currency: 'CNY', cap, occupied: '10.00', spent: '20.00', available: '1204.50', status: 'configured', period: 'cumulative_pilot', enforcement: 'ledger_only' }, mobile: { recommended: 'feishu', connection_status: 'not_connected', owner_bound: false, commands_ready: false, decisions_ready: false, setup_steps: ['配置应用后绑定负责人'] }, autonomy: { status: 'needs_setup', external_business_enabled: false, blockers: ['SKU与仓配尚待接入'] }, tasks: [{ id: 'task-' + label, title: label, intent: 'research', status: 'queued' }], decisions: [{ id: 'decision-a', title: '一项待核决策', status: 'pending', can_decide_here: false }], configuration_revision: 1 });
const receipt = title => ({ task_id: 'task-created', title, status: 'queued', dispatch_status: 'pending', external_execution_allowed: false });
function mount(props = { synthetic: false }) {
  const view = { props, slots: [], effects: [], index: 0, writes: 0, dirty: false, tree: null,
    render(next = this.props) { this.props = next; this.index = 0; this.effects = []; this.dirty = false; current = this; try { this.tree = OperatingControl(this.props); } finally { current = null; } for (const effect of this.effects) effect(); return this.dirty ? this.render() : this.tree; },
    unmount() { for (const slot of this.slots) slot.cleanup?.(); },
  }; view.render(); return view;
}
function nodes(element) { if (!element || typeof element !== 'object') return []; return [element, ...React.Children.toArray(element.props?.children).flatMap(nodes)]; }
function textOf(element) { if (typeof element === 'string' || typeof element === 'number') return String(element); return React.Children.toArray(element?.props?.children).map(textOf).join(''); }
const find = (view, predicate) => nodes(view.tree).find(predicate);
function edit(view, name, value) { const node = find(view, element => element.props?.name === name); assert.ok(node, name); node.props.onChange({ target: { value } }); view.render(); }
function submit(view) { const form = find(view, element => element.type === 'form'); assert.ok(form); return form.props.onSubmit({ preventDefault() {} }); }
function click(view, label) { const node = find(view, element => element.props?.onClick && textOf(element) === label); assert.ok(node, label); return node.props.onClick(); }

test('unknown and malformed amounts stay unknown; exact decimal strings keep cents and sign', () => {
  for (const value of [null, undefined, '', 'NaN', 'Infinity', '1.234', 0, false]) assert.equal(operatingMoney(value), '待核对');
  assert.equal(operatingMoney('0'), '¥ 0.00');
  assert.equal(operatingMoney('123456789012345.01'), '¥ 123,456,789,012,345.01');
  assert.equal(operatingMoney('-12.30'), '¥ -12.30');
});

test('initial screen waits for the backend and invents no amount or execution result', () => {
  const pending = deferred(); invoke = () => pending.promise;
  const view = mount(); assert.match(textOf(view.tree), /正在读取/); assert.doesNotMatch(textOf(view.tree), /10,000|已执行|已连接/); view.unmount();
});

test('a late real-mode read never replaces a newer synthetic-mode snapshot', async () => {
  const live = deferred(); invoke = (_tool, args) => args.synthetic ? snapshot('合成任务', '70') : live.promise;
  const view = mount(); view.render({ synthetic: true }); await settle(); view.render();
  assert.match(textOf(view.tree), /合成任务/); assert.match(textOf(view.tree), /¥ 70.00/);
  live.resolve(snapshot('过期真实任务', '9000')); await settle(); view.render();
  assert.doesNotMatch(textOf(view.tree), /过期真实任务|9,000/); view.unmount();
});

test('hidden and unmounted pages ignore late reads and showing again performs one fresh read', async () => {
  const old = deferred(); let reads = 0; invoke = () => ++reads === 1 ? old.promise : snapshot('恢复后');
  const view = mount(); view.render({ synthetic: false, active: false }); old.resolve(snapshot('隐藏旧结果')); await settle(); view.render(); assert.equal(view.tree, null);
  view.render({ synthetic: false, active: true }); await settle(); view.render(); assert.match(textOf(view.tree), /恢复后/); assert.equal(reads, 2); view.unmount();
  const late = deferred(); invoke = () => late.promise; const disposed = mount(); disposed.unmount(); const writes = disposed.writes; late.resolve(snapshot()); await settle(); assert.equal(disposed.writes, writes);
});

test('double submit sends one original task request and known success is only queued', async () => {
  const pending = deferred(), calls = []; invoke = (name, args) => { calls.push({ name, args }); return name.endsWith('_get') ? snapshot() : pending.promise; };
  const view = mount(); await settle(); view.render(); edit(view, 'title', '调研收纳架'); edit(view, 'details', '保留真实来源');
  const first = submit(view); submit(view); assert.equal(calls.filter(c => c.name.endsWith('_task_submit')).length, 1);
  pending.resolve(receipt('调研收纳架')); await first; await settle(); view.render();
  assert.match(textOf(view.tree), /已登记/); assert.match(textOf(view.tree), /待派发/); assert.match(textOf(view.tree), /尚未执行/);
  assert.equal(find(view, x => x.props?.name === 'title').props.value, ''); view.unmount();
});

test('unknown submit and refresh preserve the same key; changed payload gets a new key', async () => {
  const calls = []; let writes = 0; invoke = (name, args) => { calls.push({ name, args }); if (name.endsWith('_get')) return snapshot(); if (++writes < 3) throw new TypeError('network'); return receipt(args.title); };
  const view = mount(); await settle(); view.render(); edit(view, 'title', '原请求'); await submit(view); view.render();
  assert.match(textOf(view.tree), /结果尚未确认/); await click(view, '刷新状态'); view.render(); await submit(view); view.render();
  let requests = calls.filter(c => c.name.endsWith('_task_submit')); assert.equal(requests[0].args.idempotency_key, requests[1].args.idempotency_key); assert.equal(find(view, x => x.props?.name === 'title').props.value, '原请求');
  edit(view, 'details', '补充范围'); await submit(view); view.render(); requests = calls.filter(c => c.name.endsWith('_task_submit')); assert.notEqual(requests[1].args.idempotency_key, requests[2].args.idempotency_key); view.unmount();
});

test('known task acceptance survives a subsequent read failure without becoming unknown', async () => {
  let reads = 0; invoke = (name, args) => { if (name.endsWith('_get')) { if (++reads > 1) throw Error('read'); return snapshot(); } return receipt(args.title); };
  const view = mount(); await settle(); view.render(); edit(view, 'title', '已登记任务'); await submit(view); await settle(); view.render();
  assert.match(textOf(view.tree), /已登记/); assert.doesNotMatch(textOf(view.tree), /创建结果尚未确认/); assert.equal(find(view, x => x.props?.name === 'title').props.value, ''); view.unmount();
});

test('a cancelled replay remains the original task and keeps its key despite refresh failure', async () => {
  let reads = 0; const calls = [];
  invoke = (name, args) => { calls.push({ name, args }); if (name.endsWith('_get')) { if (++reads > 1) throw Error('read'); return snapshot(); } return { task_id: 'task-original-cancelled', title: args.title, status: 'cancelled', dispatch_status: 'original_task_state', external_execution_allowed: false }; };
  const view = mount(); await settle(); view.render(); edit(view, 'title', '原取消任务'); await submit(view); await settle(); view.render();
  assert.match(textOf(view.tree), /已查回原任务：已取消/); assert.doesNotMatch(textOf(view.tree), /创建结果尚未确认|任务已登记，待派发/); assert.equal(find(view, x => x.props?.name === 'title').props.value, '原取消任务');
  await submit(view); await settle(); view.render(); const writes = calls.filter(c => c.name.endsWith('_task_submit')); assert.equal(writes.length, 2); assert.equal(writes[0].args.idempotency_key, writes[1].args.idempotency_key); assert.match(textOf(view.tree), /task-original-cancelled/); view.unmount();
});

test('configured scope codes are human-readable without implying actual fulfillment', async () => {
  const value = snapshot(); value.scope.inventory_location = 'company_local'; value.scope.fulfillment = 'pending'; value.scope.sku_status = 'confirmed'; value.scope.logistics_status = 'connected_verified'; invoke = () => value;
  const view = mount(); await settle(); view.render(); assert.match(textOf(view.tree), /公司本地库存/); assert.match(textOf(view.tree), /履约待确认/); assert.match(textOf(view.tree), /SKU已登记/); assert.match(textOf(view.tree), /仓配已登记/); assert.doesNotMatch(textOf(view.tree), /company_local|connected_verified/); view.unmount();
});

test('whitespace edits keep an unknown request key when the submitted payload is unchanged', async () => {
  const calls = []; invoke = (name, args) => { calls.push({ name, args }); if (name.endsWith('_get')) return snapshot(); throw new TypeError('network'); };
  const view = mount(); await settle(); view.render(); edit(view, 'title', '原任务'); await submit(view); await settle(); view.render();
  edit(view, 'title', ' 原任务 '); assert.match(textOf(view.tree), /结果尚未确认/); await submit(view); await settle(); view.render();
  const writes = calls.filter(c => c.name.endsWith('_task_submit')); assert.equal(writes.length, 2); assert.equal(writes[0].args.idempotency_key, writes[1].args.idempotency_key); assert.equal(writes[1].args.title, '原任务'); view.unmount();
});

test('a stale form event after scope change or unmount cannot submit against its old scope', async () => {
  const calls = []; invoke = (name, args) => { calls.push({ name, args }); return snapshot(); };
  const view = mount(); await settle(); view.render(); edit(view, 'title', '真实草稿'); const original = find(view, x => x.type === 'form').props.onSubmit;
  view.render({ synthetic: true }); await settle(); view.render(); original({ preventDefault() {} }); await settle(); assert.equal(calls.filter(c => c.name.endsWith('_task_submit')).length, 0);
  edit(view, 'title', '合成草稿'); const discarded = find(view, x => x.type === 'form').props.onSubmit; view.unmount(); discarded({ preventDefault() {} }); await settle(); assert.equal(calls.filter(c => c.name.endsWith('_task_submit')).length, 0);
});

test('scope switches keep separate drafts and late task receipts cannot claim another scope success', async () => {
  const late = deferred(), calls = []; invoke = (name, args) => { calls.push({ name, args }); return name.endsWith('_get') ? snapshot(args.synthetic ? '合成记录' : '真实记录') : late.promise; };
  const view = mount(); await settle(); view.render(); edit(view, 'title', '真实草稿'); const request = submit(view);
  view.render({ synthetic: true }); await settle(); view.render(); assert.equal(find(view, x => x.props?.name === 'title').props.value, ''); edit(view, 'title', '合成草稿');
  late.resolve(receipt('真实草稿')); await request; await settle(); view.render(); assert.equal(find(view, x => x.props?.name === 'title').props.value, '合成草稿'); assert.doesNotMatch(textOf(view.tree), /task-created/);
  view.render({ synthetic: false }); await settle(); view.render(); assert.equal(find(view, x => x.props?.name === 'title').props.value, '真实草稿'); assert.match(textOf(view.tree), /结果尚未确认/); view.unmount();
});

test('empty tasks do not write and read-only decision cards expose no approval handler', async () => {
  const calls = []; invoke = (name, args) => { calls.push({ name, args }); return snapshot(); };
  const view = mount(); await settle(); view.render(); await submit(view); view.render(); assert.equal(calls.length, 1); assert.match(textOf(view.tree), /填写任务标题/);
  assert.equal(nodes(view.tree).some(x => x.props?.onClick && /批准|驳回/.test(textOf(x))), false); view.unmount();
});

test('returning to a scope before its old submission settles clears busy without an unrelated render', async () => {
  const late = deferred(); invoke = (name, args) => name.endsWith('_get') ? snapshot(args.synthetic ? '合成' : '真实') : late.promise;
  const view = mount(); await settle(); view.render(); edit(view, 'title', '原范围请求');
  const pending = submit(view); view.render();
  view.render({ synthetic: true }); await settle(); view.render();
  view.render({ synthetic: false }); await settle(); view.render();
  assert.equal(find(view, x => x.props?.type === 'submit').props.disabled, true);
  view.dirty = false;
  late.resolve(receipt('原范围请求')); await pending; await settle();
  if (view.dirty) view.render();
  assert.equal(find(view, x => x.props?.type === 'submit').props.disabled, false);
  assert.match(textOf(view.tree), /结果尚未确认/); assert.doesNotMatch(textOf(view.tree), /task-created/);
  view.unmount();
});
