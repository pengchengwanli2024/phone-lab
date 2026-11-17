import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { webcrypto } from 'node:crypto';
import vm from 'node:vm';
import React from 'react';

// Exercise component handlers and effect cleanup without treating this hook
// harness as a substitute for the integrated browser/media verification.
let current, invoke;
const hooks = {
  ...React,
  useState(initial) {
    const owner = current, index = owner.index++;
    owner.slots[index] ??= { value: typeof initial === 'function' ? initial() : initial };
    return [owner.slots[index].value, value => { const old = owner.slots[index].value, next = typeof value === 'function' ? value(old) : value; if (!Object.is(old, next)) { owner.slots[index].value = next; owner.dirty = true; } }];
  },
  useRef(value) { const index = current.index++; return current.slots[index] ??= { current: value }; },
  useEffect(callback, dependencies) {
    const owner = current, index = owner.index++, previous = owner.slots[index];
    if (previous && dependencies && dependencies.length === previous.dependencies?.length && dependencies.every((value, i) => Object.is(value, previous.dependencies[i]))) return;
    const slot = { dependencies, cleanup: undefined }; owner.slots[index] = slot;
    owner.effects.push(() => { previous?.cleanup?.(); slot.cleanup = callback(); });
  },
};
function mount(Component, props) {
  const instance = { slots: [], effects: [], index: 0, dirty: false, tree: null, props,
    render(next = this.props) {
      this.props = next; this.index = 0; this.effects = []; this.dirty = false; current = this;
      try { this.tree = Component(this.props); } finally { current = null; }
      for (const effect of this.effects) effect();
      return this.dirty ? this.render() : this.tree;
    },
    unmount() { for (const slot of this.slots) slot.cleanup?.(); },
  };
  instance.render(); return instance;
}
function nodes(element) {
  if (!element || typeof element !== 'object') return [];
  const children = React.Children.toArray(element.props?.children);
  return [element, ...children.flatMap(nodes)];
}
function textOf(element) {
  if (typeof element === 'string' || typeof element === 'number') return String(element);
  return React.Children.toArray(element?.props?.children).map(textOf).join('');
}
const click = (view, label) => nodes(view.tree).find(element => element.props?.onClick && textOf(element) === label)?.props.onClick();
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const settle = () => new Promise(resolve => setImmediate(resolve));
const require = createRequire(import.meta.url), timers = new Map(); let timerIndex = 0;
const compiled = await build({ stdin: { contents: `export { AssistantTeam, TeamAnswerSpeech } from './src/assistant-team'; export { AssistantToolDiscovery } from './src/assistant-tool-discovery';`, resolveDir: process.cwd(), loader: 'tsx' }, bundle: true, write: false, format: 'cjs', platform: 'node', external: ['react'], loader: { '.css': 'empty' }, plugins: [{ name: 'mock-api-boundary', setup(builder) { builder.onResolve({ filter: /^\.\/api$/ }, () => ({ path: 'team-test-api', external: true })); } }] });
const module = { exports: {} };
vm.runInNewContext(compiled.outputFiles[0].text, { module, exports: module.exports, require: name => name === 'react' ? hooks : name === 'team-test-api' ? { api: (...args) => invoke(...args), errorText: () => '读取未完成', newKey: () => 'synthetic-key' } : require(name), crypto: webcrypto, TextEncoder, setTimeout: callback => { const id = ++timerIndex; timers.set(id, callback); return id; }, clearTimeout: id => timers.delete(id) });
const { AssistantTeam, TeamAnswerSpeech, AssistantToolDiscovery } = module.exports;
const member = { name: '合成成员', profile_id: 'p', thread_id: 'thread-a', run_id: 'run-a', status: 'completed', answer: '原回答', answer_sha256: 'a'.repeat(64) };
const ready = hash => ({ status: 'ready', mime_type: 'audio/wav', audio_data_url: 'data:audio/wav;base64,UklGRg==', text_sha256: hash });

test('a speech double click sends one request and a hidden-page late response is discarded', async () => {
  const pending = deferred(), calls = [];
  invoke = async (name, args) => { calls.push({ name, args }); return pending.promise; };
  const view = mount(TeamAnswerSpeech, { member, active: true });
  click(view, '生成朗读'); click(view, '生成朗读'); await settle(); view.render();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].name, 'commerce_assistant_speech');
  assert.equal(calls[0].args.thread_id, 'thread-a');
  assert.equal(calls[0].args.expected_text_sha256, member.answer_sha256);
  assert.equal(nodes(view.tree).find(element => element.props?.onClick).props.disabled, true);
  view.render({ member, active: false }); pending.resolve(ready(member.answer_sha256)); await settle();
  view.render({ member, active: true });
  assert.equal(nodes(view.tree).some(element => element.type === 'audio'), false);
  view.unmount();
});

test('answer changes discard old audio; hiding and unmounting pause a user-controlled player', async () => {
  const pending = deferred(); invoke = async () => pending.promise;
  const view = mount(TeamAnswerSpeech, { member, active: true });
  click(view, '生成朗读'); await settle();
  const changed = { ...member, answer: '新原文', answer_sha256: 'b'.repeat(64) };
  view.render({ member: changed, active: true }); pending.resolve(ready(member.answer_sha256)); await settle(); view.render();
  assert.equal(nodes(view.tree).some(element => element.type === 'audio'), false);
  invoke = async () => ready(changed.answer_sha256); click(view, '生成朗读'); await settle(); view.render();
  const audio = nodes(view.tree).find(element => element.type === 'audio');
  assert.ok(audio); assert.equal(audio.props.autoPlay, undefined); assert.equal(audio.props.controls, true);
  let pauses = 0; const player = { pause() { pauses++; }, currentTime: 8 }; audio.props.ref.current = player;
  view.render({ member: changed, active: false }); assert.equal(pauses, 1); assert.equal(player.currentTime, 0);
  view.unmount(); assert.ok(pauses >= 2);
});

test('discovery ignores an old selected definition and only contacts the explicitly selected registration', async () => {
  const first = deferred(), discovery = deferred(), calls = [];
  const a = { id: 'ext_' + 'a'.repeat(20), kind: 'plugin', name: 'A', version: 1, definition_sha256: 'a'.repeat(64), definition: { kind: 'plugin', spec: { transport: 'mcp_http' } } };
  const b = { ...a, id: 'ext_' + 'b'.repeat(20), name: 'B', definition_sha256: 'b'.repeat(64) };
  invoke = async (name, args) => { calls.push({ name, args }); if (name === 'commerce_extension_list') return { items: [a, b] }; if (name === 'commerce_extension_get') return args.extension_id === a.id ? first.promise : b; if (name === 'commerce_extension_tools_discover') return discovery.promise; throw Error('unexpected tool'); };
  const view = mount(AssistantToolDiscovery, { active: true }); await settle(); view.render();
  const select = () => nodes(view.tree).find(element => element.type === 'select');
  select().props.onChange({ target: { value: a.id } }); view.render();
  select().props.onChange({ target: { value: b.id } }); await settle(); view.render();
  first.resolve(a); await settle(); view.render();
  assert.equal(select().props.value, b.id);
  assert.match(textOf(view.tree), new RegExp(b.definition_sha256));
  assert.equal(calls.some(call => call.name === 'commerce_extension_tools_discover'), false, 'selection and definition reads never connect to MCP');
  click(view, '发现此扩展的工具目录'); await settle(); view.render();
  const request = calls.find(call => call.name === 'commerce_extension_tools_discover');
  assert.equal(request.args.extension_id, b.id); assert.equal(request.args.expected_definition_sha256, b.definition_sha256);
  view.render({ active: false }); discovery.resolve({ extension_id: b.id, version: b.version, definition_sha256: b.definition_sha256, catalog_sha256: 'c'.repeat(64), tools: [] }); await settle(); view.render({ active: true });
  assert.equal(nodes(view.tree).some(element => element.props?.result), false, 'a hidden-page receipt does not replace the current view');
  assert.ok(calls.every(call => ['commerce_extension_list', 'commerce_extension_get', 'commerce_extension_tools_discover'].includes(call.name)));
  view.unmount();
});

const oldDiscussion = { id: 'discussion-old', channel_id: 'channel', question: '历史问题', status: 'running', members: [] };
const catalog = { profiles: [{ id: 'p', name: '成员', enabled: true, model_ids: ['model'] }], channels: [{ id: 'channel', name: '频道', revision: 1, context: { module: 'overview', demo: true }, member_ids: ['p'] }], roles: [], models: [], limits: {}, discussions: [oldDiscussion] };
test('a newer discussion receipt updates only its existing history summary without another request or losing the draft', async () => {
  timers.clear(); const calls = [], other = { ...oldDiscussion, id: 'discussion-other', question: '另一条历史', status: 'completed', created: 123 };
  const snapshot = { ...catalog, discussions: [{ ...oldDiscussion, created: 456 }, other] };
  let reads = 0;
  invoke = async (name, args) => { calls.push({ name, args }); if (name === 'commerce_assistant_team_catalog') return snapshot; if (name === 'commerce_assistant_team_discussion_get') return ++reads === 1 ? oldDiscussion : { ...oldDiscussion, status: 'awaiting_input' }; throw Error('unexpected call'); };
  const view = mount(AssistantTeam, { active: true, onConversation() {} }); await settle(); view.render(); click(view, '讨论记录'); view.render();
  nodes(view.tree).find(element => element.type === 'textarea').props.onChange({ target: { value: '保留的共同问题草稿' } }); view.render();
  click(view, '历史问题'); await settle(); view.render();
  const timer = [...timers.values()][0]; timers.clear(); timer(); await settle(); view.render();
  assert.equal(nodes(view.tree).find(element => element.props?.discussion).props.discussion.status, 'awaiting_input');
  const history = nodes(view.tree).filter(element => element.props?.className === 'team-history-item');
  assert.equal(history.length, 2, 'a read updates existing summaries without creating a new record');
  assert.equal(nodes(history[0]).find(element => element.props?.status).props.status, 'awaiting_input');
  assert.equal(nodes(history[1]).find(element => element.props?.status).props.status, 'completed');
  assert.equal(nodes(view.tree).find(element => element.type === 'textarea').props.value, '保留的共同问题草稿');
  assert.equal(calls.length, 3); assert.equal(calls.filter(call => call.name === 'commerce_assistant_team_catalog').length, 1);
  assert.deepEqual(calls.filter(call => call.name === 'commerce_assistant_team_discussion_get').map(call => call.args.discussion_id), [oldDiscussion.id, oldDiscussion.id]);
  assert.equal(snapshot.discussions[0].status, 'running', 'the catalog response object is not mutated');
  view.unmount();
});
test('hiding a team page pauses polling, preserves a question draft and restores only the original discussion read', async () => {
  timers.clear(); const calls = [];
  invoke = async (name, args) => { calls.push({ name, args }); return name === 'commerce_assistant_team_catalog' ? catalog : oldDiscussion; };
  const props = { active: true, onConversation() {} }, view = mount(AssistantTeam, props); await settle(); view.render();
  click(view, '讨论记录'); view.render();
  nodes(view.tree).find(element => element.type === 'textarea').props.onChange({ target: { value: '未保存的共同问题' } }); view.render();
  click(view, '历史问题'); await settle(); view.render();
  assert.equal(timers.size, 1);
  const readsBefore = calls.filter(call => call.name === 'commerce_assistant_team_discussion_get').length;
  view.render({ ...props, active: false }); assert.equal(timers.size, 0);
  view.render(props); await settle(); view.render();
  assert.equal(nodes(view.tree).find(element => element.type === 'textarea').props.value, '未保存的共同问题');
  const reads = calls.filter(call => call.name === 'commerce_assistant_team_discussion_get');
  assert.equal(reads.length, readsBefore + 1); assert.equal(reads.at(-1).args.discussion_id, oldDiscussion.id);
  assert.ok(calls.every(call => !call.name.endsWith('_start') && !call.name.endsWith('_send')));
  view.unmount(); assert.equal(timers.size, 0);
});

test('an old poll and a double submit cannot hide or replace the new discussion receipt', async () => {
  timers.clear(); const poll = deferred(), started = deferred(); let getCount = 0, starts = 0;
  invoke = async name => { if (name === 'commerce_assistant_team_catalog') return catalog; if (name === 'commerce_assistant_team_discussion_get') return ++getCount === 1 ? oldDiscussion : poll.promise; if (name === 'commerce_assistant_team_discussion_start') { starts++; return started.promise; } throw Error('unexpected call'); };
  const view = mount(AssistantTeam, { active: true, onConversation() {} }); await settle(); view.render(); click(view, '讨论记录'); view.render(); click(view, '历史问题'); await settle(); view.render();
  const timer = [...timers.values()][0]; timers.clear(); timer(); await settle();
  nodes(view.tree).find(element => element.type === 'textarea').props.onChange({ target: { value: '新的共同问题' } }); view.render();
  const submit = nodes(view.tree).find(element => element.type === 'form').props.onSubmit;
  submit({ preventDefault() {} }); submit({ preventDefault() {} }); view.render();
  assert.equal(starts, 1);
  poll.resolve(oldDiscussion); await settle(); view.render();
  started.resolve({ ...oldDiscussion, id: 'discussion-new', question: '新的共同问题', status: 'completed' }); await settle(); view.render();
  const result = nodes(view.tree).find(element => element.props?.discussion);
  assert.equal(result.props.discussion.id, 'discussion-new');
  assert.equal(nodes(view.tree).find(element => element.type === 'textarea').props.value, '');
  view.unmount();
});
