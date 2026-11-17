import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const compiled = await build({ stdin: { contents: `export * from './src/assistant-team-automation'; export { AssistantTeam, TeamDiscussionResults, teamContributionKey, teamCanStartDiscussion, teamErrorText } from './src/assistant-team';`, resolveDir: process.cwd(), loader: 'tsx' }, bundle: true, write: false, format: 'cjs', platform: 'node', external: ['react'], loader: { '.css': 'empty' }, plugins: [{ name: 'automation-api-boundary', setup(builder) { builder.onResolve({ filter: /^\.\/api$/ }, () => ({ path: 'automation-api', external: true })); } }] });
let invoke, current, sequence = 0;
function load(react) { const module = { exports: {} }; vm.runInNewContext(compiled.outputFiles[0].text, { module, exports: module.exports, require: name => name === 'react' ? react : name === 'automation-api' ? { api: (...args) => invoke(...args), errorText: () => '读取未完成', newKey: () => 'synthetic-' + ++sequence } : require(name), TextEncoder, Error, setTimeout: () => 1, clearTimeout() {}, window: { CommerceUI: { icon: () => '' } } }); return module.exports; }
const helpers = load(React), plain = value => JSON.parse(JSON.stringify(value));
const hooks = { ...React,
  useState(initial) { const owner = current, index = owner.index++; owner.slots[index] ??= { value: typeof initial === 'function' ? initial() : initial }; return [owner.slots[index].value, value => { const old = owner.slots[index].value, next = typeof value === 'function' ? value(old) : value; if (!Object.is(old, next)) { owner.slots[index].value = next; owner.dirty = true; } }]; },
  useRef(value) { return current.slots[current.index++] ??= { current: value }; },
  useEffect(callback, dependencies) { const owner = current, index = owner.index++, previous = owner.slots[index]; if (previous && dependencies && dependencies.length === previous.dependencies?.length && dependencies.every((value, i) => Object.is(value, previous.dependencies[i]))) return; const slot = { dependencies }; owner.slots[index] = slot; owner.effects.push(() => { previous?.cleanup?.(); slot.cleanup = callback(); }); },
};
const interactive = load(hooks);
function mount(Component, props) { const view = { slots: [], effects: [], props, render(next = this.props) { this.props = next; this.index = 0; this.effects = []; this.dirty = false; current = this; try { this.tree = Component(next); } finally { current = null; } for (const effect of this.effects) effect(); return this.dirty ? this.render() : this.tree; }, unmount() { for (const slot of this.slots) slot.cleanup?.(); } }; view.render(); return view; }
function nodes(element) { return !element || typeof element !== 'object' ? [] : [element, ...React.Children.toArray([element.props?.children, element.props?.action]).flatMap(nodes)]; }
function textOf(element) { return typeof element === 'string' || typeof element === 'number' ? String(element) : React.Children.toArray(element?.props?.children).map(textOf).join(''); }
const click = (view, label) => { const button = nodes(view.tree).find(node => node.props?.onClick && textOf(node) === label); assert.ok(button, label); button.props.onClick(); };
const settle = () => new Promise(resolve => setImmediate(resolve));
const channel = { id: 'channel-a', name: '频道 A', revision: 8, routing: { mode: 'collaborate', rules: [], max_rounds: 2 } };
const trigger = { id: 'trigger-a', name: '原触发器', revision: 3, enabled: false, kind: 'manual', channel_id: channel.id, channel_revision: 4, question: '保留的原问题', dispatch_mode: 'auto', max_rounds: 1, schedule: {}, history: [], next_at: null };

const pkg = { schema: 'phone-lab-team-v2', name: '完整预设', instructions: '完整团队指令 <script>bad()</script>', chief_key: 'chief', profiles: [{ key: 'chief', name: '负责人', role_id: 'conductor', instructions: '全部角色指令', expertise: ['物流'], skill_keys: ['s'], connector_keys: ['c'] }], channels: [{ key: 'ops', name: '运营', members: ['chief'], instructions: '完整频道指令', lead_key: 'chief', playbook_key: 'p', routing: { mode: 'collaborate', max_rounds: 2, rules: [{ keywords: ['物流'], member_keys: ['chief'] }] } }], playbooks: [{ key: 'p', name: '运营剧本', instructions: '完整工作剧本', triggers: ['参考条件'] }], starter_notes: [{ profile_key: 'chief', name: '开始', content: '完整起始笔记' }], skills: [{ key: 's', name: '脚本说明', description: '纯文本技能', instructions: '<img src=x onerror=bad()>完整技能指令' }], connector_requirements: [{ key: 'c', label: '平台接入', reason: '需要账号但尚未授权', optional: false, status: 'unconfigured' }], triggers: [{ key: 't', name: '暂停的定时', kind: 'manual', channel_key: 'ops', question: '原问题', dispatch_mode: 'auto', max_rounds: 1, schedule: {}, enabled: false }, { key: 'd', name: '外部例程', kind: 'deferred', channel_key: null, reason: '不支持的远端条件', source_spec: '仅作参考' }] };

test('keyword and routing validation reject oversized input and retain saved routing on member removal', () => {
  assert.deepEqual(plain(helpers.teamKeywords(' 采购，物流、采购\n评论, ')), ['采购', '物流', '评论']);
  assert.match(helpers.teamKeywordValidation(Array.from({ length: 17 }, (_, i) => String(i))), /16/);
  assert.match(helpers.teamKeywordValidation(['长'.repeat(41)]), /40/);
  const original = { mode: 'auto', lead_id: 'removed', max_rounds: 2, rules: [{ keywords: ['物流'], member_ids: ['kept', 'removed'] }] };
  assert.deepEqual(plain(helpers.teamRoutingForMembers(original, ['kept'])), { mode: 'auto', max_rounds: 2, rules: [{ keywords: ['物流'], member_ids: ['kept'] }] });
  assert.equal(original.lead_id, 'removed'); assert.deepEqual(original.rules[0].member_ids, ['kept', 'removed']);
  assert.match(helpers.teamRoutingValidation({ ...original, rules: [{ keywords: [], member_ids: [] }] }), /至少/);
});

test('trigger schedules require explicit offset, integer intervals and valid weekly timezone', () => {
  const draft = { ...trigger, kind: 'once', schedule: { at: '2027-01-01T09:00:00' } };
  assert.match(helpers.teamTriggerValidation(draft), /时区偏移/);
  assert.equal(helpers.teamTriggerValidation({ ...draft, schedule: { at: '2027-01-01T09:00:00+08:00' } }), '');
  for (const interval_seconds of [59, 604801, 60.5]) assert.match(helpers.teamTriggerValidation({ ...draft, kind: 'interval', schedule: { start_at: '2027-01-01T01:00:00Z', interval_seconds } }), /60 至 604800/);
  assert.equal(helpers.teamTriggerValidation({ ...draft, kind: 'weekly', schedule: { weekday: 0, time: '09:00', timezone: 'Asia/Shanghai' } }), '');
  assert.match(helpers.teamTriggerValidation({ ...draft, kind: 'weekly', schedule: { weekday: 6, time: '25:00', timezone: 'Asia/Shanghai' } }), /有效/);
  assert.match(helpers.teamTriggerValidation({ ...draft, kind: 'weekly', schedule: { weekday: 6, time: '09:00', timezone: 'No/SuchZone' } }), /IANA/);
  assert.match(helpers.teamTriggerValidation({ ...draft, kind: 'after_discussion', schedule: {} }), /原讨论/);
});

test('save payload strips document state and stale schedule keys while retaining pinned channel revision', () => {
  const payload = plain(helpers.teamTriggerRequest({ ...trigger, kind: 'weekly', schedule: { weekday: 0, time: '09:00', timezone: 'Asia/Shanghai', at: 'ignored' }, question: ' 原问题 ' }));
  assert.equal(payload.channel_revision, 4); assert.equal(payload.question, '原问题');
  assert.deepEqual(payload.schedule, { weekday: 0, time: '09:00', timezone: 'Asia/Shanghai' });
  for (const field of ['enabled', 'revision', 'history', 'next_at']) assert.equal(field in payload, false);
  assert.deepEqual(plain(helpers.teamTriggerRequest({ ...trigger, kind: 'webhook', schedule: { at: 'old' } }).schedule), {});
});

test('full preset retains all reference text as escaped content without execution buttons', () => {
  const html = renderToStaticMarkup(React.createElement(helpers.TeamPackageContents, { value: pkg }));
  for (const text of ['完整团队指令', '全部角色指令', '完整频道指令', '完整工作剧本', '完整起始笔记', '完整技能指令', '默认工作剧本：运营剧本（p）', '未配置', '已暂停', '延后 · 不可执行', '不支持的远端条件', '仅作参考']) assert.ok(html.includes(text), text);
  assert.match(html, /&lt;script&gt;/); assert.match(html, /&lt;img/); assert.doesNotMatch(html, /<script|<img|<button/);
  const old = renderToStaticMarkup(React.createElement(helpers.TeamPackageContents, { value: { schema: 'phone-lab-team-v1', name: '旧包', profiles: [], channels: [] } })); assert.match(old, /未提供工作剧本/);
});

test('playbook selection stays within the owning imported channel preset', () => {
  const a = { id: 'a', name: 'A', channel_map: { ops: 'channel-a' }, package: pkg };
  const b = { id: 'b', name: 'B', channel_map: { ops: 'channel-b' }, package: { ...pkg, playbooks: [{ key: 'p', name: '别的剧本', instructions: '', triggers: [] }] } };
  assert.deepEqual(plain(helpers.teamPresetPlaybooks([b, a], 'channel-a')), [{ key: 'p', name: 'A · 运营剧本' }]);
});

test('event dispatch remains distinct from discussion completion and links to the original discussion', () => {
  assert.equal(helpers.teamTriggerStatus('dispatched'), '已派发 · 待查看讨论'); assert.match(helpers.teamTriggerStatus('unknown'), /未确认/);
  assert.equal(helpers.teamTriggerTime(null), '未安排'); assert.equal(helpers.teamTriggerTime(0), '1970-01-01 00:00:00 UTC');
  const html = renderToStaticMarkup(React.createElement(helpers.TeamTriggerHistory, { events: [{ id: 'e', status: 'dispatched', discussion_id: 'original' }], onDiscussion() {} })); assert.match(html, /读取原讨论/); assert.doesNotMatch(html, /已完成/);
});

test('collaboration renders repeated original runs, selection reason, contributions and synthesis', () => {
  const a = { profile_id: 'same', thread_id: 'thread-1', run_id: 'run-1', name: '负责人', status: 'completed', answer: '第一轮原回答' }, b = { ...a, thread_id: 'thread-2', run_id: 'run-2', answer: '第二轮原回答' };
  assert.notEqual(helpers.teamContributionKey(a, 0), helpers.teamContributionKey(b, 1));
  const html = renderToStaticMarkup(React.createElement(helpers.TeamDiscussionResults, { onConversation() {}, discussion: { id: 'd', channel_id: 'c', question: '原问题', status: 'completed', mode: 'collaborate', members: [a, b], routing_decision: { selected_member_names: ['负责人'], selected_member_ids: ['same'], reason: 'keyword_rules', matched_keywords: ['物流'], lead_id: 'same' }, plan: [{ index: 0, round: 1, name: '负责人', kind: 'contribution', status: 'completed' }, { index: 1, round: 2, name: '负责人', kind: 'synthesis', status: 'completed' }], final_answer: '最终汇总回答', budget: { max_member_requests: 3, used_member_requests: 2 } } }));
  for (const text of ['第一轮原回答', '第二轮原回答', '命中频道关键词规则', '物流', '第 1 轮贡献', '最终汇总', '最终回答', '最终汇总回答', '成员请求 2 / 3']) assert.ok(html.includes(text), text);
});

test('editing preserves pinned revision until explicitly rebound and save never enables or dispatches', async () => {
  const calls = []; let saved = trigger;
  invoke = async (name, args) => { calls.push({ name, args }); if (name.endsWith('_list')) return { triggers: [saved] }; if (name.endsWith('_get')) return saved; if (name.endsWith('_save')) return saved = { ...trigger, ...args.trigger, revision: 4, enabled: false }; throw Error('unexpected ' + name); };
  const view = mount(interactive.AssistantTeamAutomation, { channels: [channel], active: true, onDiscussion() {} }); await settle(); view.render(); click(view, '查看触发器'); await settle(); view.render(); click(view, '编辑并保存为暂停'); view.render(); assert.match(textOf(view.tree), /当前绑定修订 4/);
  nodes(view.tree).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await settle(); view.render();
  const save = calls.find(call => call.name.endsWith('_save')); assert.equal(save.args.expected_revision, 3); assert.equal(save.args.trigger.channel_revision, 4); assert.equal(save.args.trigger.enabled, undefined);
  assert.equal(calls.some(call => /_enable|_run|_event$/.test(call.name)), false);
  click(view, '编辑并保存为暂停'); view.render(); click(view, '明确绑定频道当前修订'); view.render(); assert.match(textOf(view.tree), /当前绑定修订 8/); view.unmount();
});

test('explicit run locks double clicks and retains idempotency after an unknown receipt', async () => {
  const enabled = { ...trigger, enabled: true }, calls = []; let resolve;
  invoke = async (name, args) => { calls.push({ name, args }); if (name.endsWith('_list')) return { triggers: [enabled] }; if (name.endsWith('_get')) return enabled; if (name.endsWith('_run')) return new Promise(done => { resolve = done; }); throw Error('unexpected'); };
  const view = mount(interactive.AssistantTeamAutomation, { channels: [channel], active: true, onDiscussion() {} }); await settle(); view.render(); click(view, '查看触发器'); await settle(); view.render();
  click(view, '执行一次（调用模型）'); click(view, '执行一次（调用模型）'); assert.equal(calls.filter(call => call.name.endsWith('_run')).length, 1);
  resolve({ id: 'event-original', status: 'unknown' }); await settle(); view.render(); click(view, '执行一次（调用模型）');
  const runs = calls.filter(call => call.name.endsWith('_run')); assert.equal(runs.length, 2); assert.equal(runs[0].args.idempotency_key, runs[1].args.idempotency_key); assert.equal(runs[0].args.expected_revision, 3); resolve({ status: 'unknown' }); await settle(); view.unmount();
});

test('auto routing accepts a partly configured channel and all/collaborate still require all members', () => {
  const roster = [{ enabled: true, model_ids: ['model'] }, { enabled: false, model_ids: [] }];
  assert.equal(helpers.teamCanStartDiscussion('auto', roster), true);
  assert.equal(helpers.teamCanStartDiscussion('all', roster), false);
  assert.equal(helpers.teamCanStartDiscussion('collaborate', roster), false);
  assert.equal(helpers.teamCanStartDiscussion('auto', [{ enabled: false, model_ids: [] }]), false);
  assert.equal(helpers.teamCanStartDiscussion('auto', []), false);
});

function field(view, title) {
  const label = nodes(view.tree).find(node => node.type === 'label' && textOf(node).startsWith(title));
  assert.ok(label, title); return nodes(label).find(node => ['input', 'select', 'textarea'].includes(node.type));
}
test('webhook editor rejects JSON scalars before sending an explicit object event', async () => {
  const item = { ...trigger, kind: 'webhook', enabled: true }, calls = [];
  invoke = async (name, args) => { calls.push({ name, args }); if (name.endsWith('_list')) return { triggers: [item] }; if (name.endsWith('_get')) return item; if (name.endsWith('_event')) return { id: 'e', status: 'skipped' }; throw Error('unexpected'); };
  const view = mount(interactive.AssistantTeamAutomation, { channels: [channel], active: true, onDiscussion() {} }); await settle(); view.render(); click(view, '查看触发器'); await settle(); view.render();
  field(view, '事件编号').props.onChange({ target: { value: 'original-event-id' } }); view.render();
  for (const payload of ['null', '[]', '"text"', '7']) {
    field(view, '事件内容').props.onChange({ target: { value: payload } }); view.render(); click(view, '提交此事件（可调用模型）'); view.render();
    assert.match(textOf(view.tree), /JSON 对象/);
  }
  assert.equal(calls.some(call => call.name.endsWith('_event')), false);
  field(view, '事件内容').props.onChange({ target: { value: '{"source":"synthetic"}' } }); view.render(); click(view, '提交此事件（可调用模型）'); await settle(); view.render();
  const event = calls.find(call => call.name.endsWith('_event')); assert.equal(event.args.event_id, 'original-event-id'); assert.equal(event.args.expected_revision, 3); assert.deepEqual(plain(event.args.payload), { source: 'synthetic' }); view.unmount();
});

test('channel routing edits preserve exact original scope and revision rather than clearing object bindings', async () => {
  const scope = { module: 'products', demo: false, store_id: 'synthetic-store', entity: { kind: 'product', id: 'synthetic-product' } };
  const original = { ...channel, instructions: '频道指令', context: scope, member_ids: ['p'], routing: { mode: 'auto', lead_id: 'p', rules: [], max_rounds: 1 } };
  const catalog = { profiles: [{ id: 'p', name: '成员', instructions: '', revision: 1, role_id: 'conductor', enabled: true, model_ids: ['model'] }], channels: [original], roles: [{ id: 'conductor', name: '负责人' }], models: [], limits: {}, discussions: [] }, calls = [];
  invoke = async (name, args) => { calls.push({ name, args }); if (name.endsWith('_catalog')) return catalog; if (name.endsWith('_channel_save')) return { ...original, ...args.channel }; throw Error('unexpected'); };
  const view = mount(interactive.AssistantTeam, { active: true, onConversation() {} }); await settle(); view.render(); click(view, '频道'); view.render(); click(view, '编辑频道'); view.render();
  const routing = nodes(view.tree).find(node => typeof node.props?.onChange === 'function' && Array.isArray(node.props?.members) && node.props?.value?.rules);
  assert.ok(routing); routing.props.onChange({ mode: 'collaborate', lead_id: 'p', rules: [], max_rounds: 2 }); view.render(); nodes(view.tree).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await settle(); view.render();
  const saved = calls.find(call => call.name.endsWith('_channel_save')); assert.equal(saved.args.expected_revision, 8); assert.deepEqual(plain(saved.args.channel.context), scope); assert.equal(saved.args.channel.routing.mode, 'collaborate'); assert.deepEqual(original.context, scope); view.unmount();
});

test('continuing collaboration uses the original discussion update guard and never reissues discussion_start', async () => {
  const original = { id: 'original-discussion', channel_id: channel.id, question: '原问题', status: 'awaiting_input', mode: 'collaborate', updated: 123.5, stopped_reason: 'team_collaboration_awaiting_input', members: [] }, calls = [];
  const catalog = { profiles: [], channels: [{ ...channel, context: { module: 'overview', demo: true }, member_ids: [] }], roles: [], models: [], limits: {}, discussions: [original] };
  invoke = async (name, args) => { calls.push({ name, args }); if (name.endsWith('_catalog')) return catalog; if (name.endsWith('_discussion_get')) return original; if (name.endsWith('_discussion_advance')) return { ...original, status: 'running', stopped_reason: null, updated: 124 }; throw Error('unexpected'); };
  const view = mount(interactive.AssistantTeam, { active: true, onConversation() {} }); await settle(); view.render(); click(view, '讨论记录'); view.render(); click(view, '原问题'); await settle(); view.render(); click(view, '核对原回答并继续后续步骤'); await settle(); view.render();
  const continuation = calls.find(call => call.name.endsWith('_discussion_advance')); assert.equal(continuation.args.discussion_id, original.id); assert.equal(continuation.args.expected_updated, 123.5); assert.equal(calls.some(call => call.name.endsWith('_discussion_start')), false); view.unmount();
});

test('channel scope drift tells the user to start a new discussion without suggesting continuation', () => {
  const html = renderToStaticMarkup(React.createElement(helpers.TeamDiscussionResults, { onConversation() {}, discussion: { id: 'd', channel_id: 'c', question: '原问题', status: 'blocked', mode: 'collaborate', stopped_reason: 'team_channel_scope_changed', members: [] } }));
  assert.match(html, /频道业务范围已变化/); assert.match(html, /另开讨论/); assert.match(html, /原请求不会重发/); assert.doesNotMatch(html, /继续后续步骤/);
});

test('mentions-only auto routing is editable, survives member changes and reports missing recipients clearly', () => {
  const value = { mode: 'auto', lead_id: 'p', mentions_only: true, rules: [], max_rounds: 1 }, members = [{ id: 'p', name: '成员' }]; let changed;
  const tree = helpers.TeamRoutingEditor({ value, members, onChange: next => { changed = next; } });
  const checkbox = nodes(tree).find(node => node.type === 'input' && node.props.type === 'checkbox'); assert.ok(checkbox); assert.equal(checkbox.props.checked, true);
  checkbox.props.onChange({ target: { checked: false } }); assert.equal(changed.mentions_only, false); assert.equal(changed.lead_id, 'p'); assert.equal(value.mentions_only, true);
  const lead = nodes(tree).find(node => node.type === 'select' && node.props.value === 'p'); lead.props.onChange({ target: { value: '' } }); assert.equal(changed.mentions_only, true);
  assert.equal(helpers.teamRoutingForMembers(value, ['p']).mentions_only, true);
  assert.match(helpers.teamRoutingValidation({ ...value, mentions_only: 'true' }), /须为/);
  assert.equal(helpers.teamErrorText(new Error('team_no_recipient')), '此频道仅响应点名，请使用 @成员名称 后再发送。');
  const all = helpers.TeamRoutingEditor({ value: { ...value, mode: 'all' }, members, onChange() {} }); assert.equal(nodes(all).some(node => node.type === 'input' && node.props.type === 'checkbox'), false);
});
