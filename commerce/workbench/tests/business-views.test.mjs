import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const kit = await readFile('../ui/kit.js', 'utf8');
async function business(file, factory, options) {
  const handlers = new Map(), calls = [];
  const document = { documentElement: { dataset: {} }, addEventListener(name, fn) { handlers.set(name, fn); }, querySelector: options.query || (() => null) };
  const window = { matchMedia: () => ({ matches: false, addEventListener() {} }), dispatchEvent() {} };
  const context = vm.createContext({ window, document, CustomEvent: class {}, setInterval() {}, setTimeout() {} });
  vm.runInContext(kit, context);
  vm.runInContext(await readFile('../web/' + file, 'utf8'), context);
  options.setup?.(window);
  const controller = window[factory]({ repaint() {}, isActive: () => true, toast() {}, getStatus: () => ({}), knowledgeView: () => '<section>existing-knowledge</section>', ...options,
    api: async (name, args) => { calls.push([name, args]); return options.api(name, args); } });
  return { controller, calls, handlers, window };
}
const fixtures = {
  commerce_platform_catalog: { providers: [{ name: 'Synthetic provider', resources: ['orders'], notice: 'read only' }] },
  commerce_live_status: { configured: true, orders_scope_confirmed: false, feishu_test_verified: true, feishu_received_confirmed: false, notifications_enabled: false },
};
test('connection hub reads real states separately and exposes each existing setup once', async () => {
  const s = await business('connections-ui.js', 'CommerceConnections', { api: name => { assert.ok(name in fixtures); return fixtures[name]; } });
  await s.controller.load(); const view = s.controller.view();
  assert.match(view, /凭据字段已保存/); assert.match(view, /订单范围待核对/);
  assert.match(view, /接口测试已接收/); assert.match(view, /群内收件未确认/);
  assert.equal((view.match(/data-connection-action="ozon-setup"/g) || []).length, 1);
  assert.equal((view.match(/data-connection-action="platform-setup"/g) || []).length, 1);
  assert.match(view, /existing-knowledge/); assert.equal(s.calls.length, 2);
});
test('failed connection refresh removes old successful state and never opens a setup or retries', async () => {
  let fail = false;
  const s = await business('connections-ui.js', 'CommerceConnections', { api: name => { if (fail) throw Error('test service unavailable'); return fixtures[name]; } });
  await s.controller.load(); fail = true; await s.controller.load(); const view = s.controller.view();
  assert.match(view, /状态未读到/); assert.match(view, /test service unavailable/);
  assert.doesNotMatch(view, /凭据字段已保存/); assert.doesNotMatch(view, /接口测试已接收/);
  assert.equal(s.calls.length, 4); assert.ok(s.calls.every(([name]) => name.endsWith('_catalog') || name.endsWith('_status')));
});
test('each explicit setup action calls its existing private wizard without passing credentials', async () => {
  const notices = [];
  const s = await business('connections-ui.js', 'CommerceConnections', { toast: text => notices.push(text), api: name => {
    if (name === 'commerce_live_open_setup') return { opened: false, message: 'request sent' };
    assert.equal(name, 'commerce_platform_open_setup'); return { status: 'opened_local_private_setup' };
  } });
  for (const action of ['ozon-setup', 'platform-setup']) {
    const target = { dataset: { connectionAction: action }, disabled: false, isConnected: true };
    await s.handlers.get('click')({ target: { closest: () => target } });
    assert.equal(target.disabled, false);
  }
  assert.deepEqual(s.calls.map(([name]) => name), ['commerce_live_open_setup', 'commerce_platform_open_setup']);
  assert.ok(s.calls.every(([, args]) => args === undefined));
  assert.match(notices[0], /结果尚未确认/); assert.match(notices[1], /已请求打开/);
});
test('store business and alert views retain original receipts while configuration has one entry', async () => {
  let connections = 0;
  const s = await business('live-ui.js', 'CommerceLive', {
    setup: window => { window.CommerceLivePlans = () => ({ load() {}, render: () => 'original-restock-plans', action: async () => false, isEditing: () => false }); },
    onConnections: () => connections++,
    api: (name, args) => {
      if (name === 'commerce_live_status') return { ...fixtures.commerce_live_status, orders: { available: true, fresh: true, count: 3 }, stock: { available: false }, fulfillment_modes: ['OGL'], stock_basis: 'unconfirmed', last_job: { status: 'succeeded', finished: 'synthetic-time' }, store_label: 'Synthetic store' };
      if (name === 'commerce_live_alerts') return { alerts: [{ id: 'original-live-alert', title: 'Synthetic alert', status: 'active', detail: 'original evidence', source_ref: 'snapshot-original', source_sha256: 'test-only', store_id: 'synthetic-store' }] };
      assert.equal(name, 'commerce_live_ack'); assert.equal(args.alert_id, 'original-live-alert'); return {};
    },
  });
  await s.controller.load();
  assert.match(s.controller.render(), /original-restock-plans/); assert.match(s.controller.render(), /synthetic-time/);
  assert.doesNotMatch(s.controller.render(), /Synthetic alert|data-live-action="ack"|打开.*向导/);
  const alerts = s.controller.alertsView();
  assert.match(alerts, /original-live-alert/); assert.match(alerts, /snapshot-original/); assert.match(alerts, /标为已阅/);
  for (const action of ['ack', 'setup']) {
    const target = { dataset: { liveAction: action, id: 'original-live-alert' }, disabled: false };
    await s.handlers.get('click')({ target: { closest: () => target }, stopImmediatePropagation() {} });
  }
  assert.equal(connections, 1); assert.equal(s.calls.filter(([name]) => name === 'commerce_live_ack').length, 1);
  assert.ok(!s.calls.some(([name]) => name.includes('open_setup') || name.includes('_sync')));
});

const channelFixture = { profile: 'commerce-bot', profile_available: true, shared_core_configured: false, probe_status: 'observed', setup_command: 'hermes -p commerce-bot gateway setup', channels: [{ id: 'feishu', name: '飞书', modes: [{ id: 'app', label: '企业应用', adapter_supported: true }], binding: { mode: 'app', selected: false, label: '', revision: '0' }, adapter_available: true, credentials_present: false, gateway_enabled: false, runtime_status: 'not_running', readiness: 'authorization_required', delivery_verified: false, missing_fields: ['FEISHU_APP_ID'] }] };
test('channel diagnostics do not turn available adapters into authorization or delivery claims', async () => {
  const s = await business('channels-ui.js', 'CommerceChannels', { api: name => { assert.equal(name, 'commerce_channel_status'); return channelFixture; } });
  await s.controller.load(); const view = s.controller.view();
  assert.match(view, /待授权/); assert.match(view, /送达待核对/); assert.match(view, /共享业务核心待配置/);
  assert.doesNotMatch(view, /送达已核对/); assert.equal(s.calls.length, 1);
});
test('an unavailable channel probe reports unknown instead of absent credentials or processes', async () => {
  const s = await business('channels-ui.js', 'CommerceChannels', { api: () => ({ ...channelFixture, probe_status: 'unavailable', profile_available: false }) });
  await s.controller.load(); const view = s.controller.view();
  assert.match(view, /本机诊断未确认/); assert.match(view, /凭据字段：未知/); assert.match(view, /运行状态：未知/);
  assert.doesNotMatch(view, /运行状态：未运行|客户端：未启用|尚未找到项目客户端/);
});
test('channel configuration preserves the expected revision and editor values on conflict', async () => {
  const fields = { '#channel-editor': { dataset: { channelEditor: '1' } }, '#channel-mode': { value: 'app' }, '#channel-label': { value: 'Synthetic example' }, '#channel-selected': { checked: true }, '#channel-edit-error': { textContent: '' } };
  const s = await business('channels-ui.js', 'CommerceChannels', { query: key => fields[key], modal() {}, closeModal() { throw Error('must retain editor'); }, api: name => { if (name === 'commerce_channel_status') return channelFixture; assert.equal(name, 'commerce_channel_configure'); throw Error('channel_configuration_conflict'); } });
  await s.controller.load();
  for (const action of ['edit', 'save']) { const target = { dataset: { channelAction: action, channel: 'feishu' }, disabled: false, isConnected: true }; await s.handlers.get('click')({ target: { closest: () => target } }); }
  assert.equal(s.calls.at(-1)[1].expected_revision, '0');
  assert.equal(s.calls.at(-1)[1].label, 'Synthetic example');
  assert.deepEqual(Object.keys(s.calls.at(-1)[1]).sort(), ['channel', 'expected_revision', 'label', 'mode', 'selected']);
  assert.match(fields['#channel-edit-error'].textContent, /配置已有新版本/); assert.equal(fields['#channel-label'].value, 'Synthetic example');
});
test('credential-like channel remarks are rejected before an MCP write', async () => {
  const fields = { '#channel-editor': { dataset: { channelEditor: '1' } }, '#channel-mode': { value: 'app' }, '#channel-label': { value: 'https://example.invalid/not-a-credential' }, '#channel-selected': { checked: true }, '#channel-edit-error': { textContent: '' } };
  const s = await business('channels-ui.js', 'CommerceChannels', { query: key => fields[key], modal() {}, api: name => { assert.equal(name, 'commerce_channel_status'); return channelFixture; } });
  await s.controller.load();
  for (const action of ['edit', 'save']) { const target = { dataset: { channelAction: action, channel: 'feishu' }, disabled: false }; await s.handlers.get('click')({ target: { closest: () => target } }); }
  assert.equal(s.calls.length, 1); assert.match(fields['#channel-edit-error'].textContent, /不能填写凭据/);
});
test('late channel save cannot close a different editor opened while it was pending', async () => {
  let finish, closed = 0;
  const fields = { '#channel-mode': { value: 'app' }, '#channel-label': { value: 'First editor' }, '#channel-selected': { checked: true }, '#channel-edit-error': { textContent: '' } };
  const s = await business('channels-ui.js', 'CommerceChannels', { query: key => fields[key], modal(title, body) { fields['#channel-editor'] = { dataset: { channelEditor: body.match(/data-channel-editor="(\d+)"/)[1] } }; }, closeModal() { closed++; }, api: name => name === 'commerce_channel_status' ? channelFixture : new Promise(resolve => { finish = resolve; }) });
  await s.controller.load();
  const click = action => { const target = { dataset: { channelAction: action, channel: 'feishu' }, disabled: false, isConnected: true }; return s.handlers.get('click')({ target: { closest: () => target } }); };
  await click('edit'); const saving = click('save'); await new Promise(setImmediate);
  await click('edit'); fields['#channel-label'].value = 'Second editor'; finish(channelFixture); await saving;
  assert.equal(closed, 0); assert.equal(fields['#channel-label'].value, 'Second editor');
});
