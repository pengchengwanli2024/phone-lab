import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { randomUUID } from 'node:crypto';

const source = await readFile('../web/copilot-ui.js', 'utf8');
const flush = () => new Promise(setImmediate);
function setup({ compact = true, selection, catalog, defaultId, uncreated = false, override, query, queryAll, element, createElement, onModels } = {}) {
  const events = new Map(), calls = [];
  const listeners = { addEventListener(name, fn) { if (!events.has(name)) events.set(name, []); events.get(name).push(fn); }, removeEventListener() {} };
  const escape = v => String(v ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  const ui = { escape, icon: () => '', badge: escape, alert: escape, field: (a, b) => a + b, select: () => '', button: ({ label, description = '', attrs }) => '<button ' + Object.entries(attrs).filter(([, v]) => v !== false && v != null).map(([k, v]) => k + '="' + escape(v) + '"').join(' ') + '>' + escape(label) + (description ? '<small>' + escape(description) + '</small>' : '') + '</button>' };
  const document = { ...listeners, querySelector: query || (() => null), querySelectorAll: queryAll || (() => []), getElementById: element || (() => null), activeElement: null, ...(createElement ? { createElement } : {}) };
  const window = { ...listeners, CommerceUI: ui, innerWidth: 1440, dispatchEvent() {} };
  const context = uncreated ? { module: 'overview', demo: true } : { module: 'organization', demo: true, entity: { kind: 'case', id: 'model-qa' } };
  const state = { catalog: catalog ?? [{ id: 'project-default', label: '项目默认', model: 'default-model', selectable: true }], thread: { id: 'thread', context, context_sha256: 'scope', turns: [], model_selection: selection ?? { model_id: 'project-default', available: true, sha256: 'a'.repeat(64) } } };
  state.defaultId = defaultId;
  const draftValues = new Map();
  vm.runInNewContext(source, { window, document, crypto: { randomUUID }, setInterval() {}, clearInterval() {}, CustomEvent: class {}, localStorage: { getItem: key => key.startsWith('commerce-copilot-draft-v1:') ? draftValues.get(key) ?? null : null, setItem: (key, value) => draftValues.set(key, value) } });
  const controller = window.CommerceCopilot({ api: async (name, args) => {
    calls.push([name, args]);
    if (override) { const value = await override(name, args); if (value !== undefined) return value; }
    if (name === 'commerce_model_list') return { models: state.catalog, ...(state.defaultId === undefined ? {} : { default_model_id: state.defaultId }) };
    if (name === 'commerce_copilot_list') return { threads: uncreated ? [] : [state.thread] };
    if (name === 'commerce_copilot_open' || name === 'commerce_copilot_get' || name === 'commerce_copilot_send') return structuredClone(state.thread);
    throw Error('unexpected API: ' + name);
  }, getContext: () => context, inline: true, compact, scopeLabel: () => '合成模型验收', onModels, repaint() {}, toast() {} });
  const emit = (name, event) => { for (const fn of events.get(name) || []) fn(event); };
  const click = (action, data = {}) => { const target = { dataset: { copilotAction: action, ...data }, closest: selector => selector === '[data-copilot-action]' ? target : null }; emit('click', { target, preventDefault() {} }); };
  const input = value => emit('input', { target: { id: 'copilot-message', value } });
  const enter = () => emit('keydown', { target: { id: 'copilot-message' }, key: 'Enter', ctrlKey: true, preventDefault() {} });
  const sendButton = () => controller.view().match(/<button[^>]*data-copilot-action="send"[^>]*>/)?.[0];
  controller.open(undefined, { focus: false });
  return { ...state, state, controller, calls, click, input, enter, emit, sendButton };
}

const option = (s, id) => s.controller.view().match(new RegExp('<button[^>]*data-model="' + id + '"[^>]*>'))?.[0];
const autoCatalog = () => [{ id: 'project-default', label: '固定 Codex', model: 'fixed-model', selectable: true }, { id: 'project-auto', label: '智能选择', engine: 'builtin', provider: 'host_auto', model: '按任务选择', selectable: true }];
test('an uncreated conversation displays the catalog default before sending and pins the opened model', async () => {
  const s = setup({ uncreated: true, catalog: autoCatalog(), defaultId: 'project-auto', selection: { model_id: 'project-auto', available: true, sha256: 'c'.repeat(64) } });
  await flush(); assert.match(option(s, 'project-auto'), /aria-selected="true"/);
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_open').length, 0);
  s.input('先用当前显示的智能选择回复'); s.enter(); await flush();
  const sends = s.calls.filter(([name]) => name === 'commerce_copilot_send');
  assert.equal(sends.length, 1); assert.equal(sends[0][1].expected_model_sha256, 'c'.repeat(64)); s.controller.dispose();
});
test('a catalog default never replaces an explicitly selected fixed conversation model', async () => {
  const s = setup({ catalog: autoCatalog(), defaultId: 'project-auto' }); await flush();
  assert.match(option(s, 'project-default'), /aria-selected="true"/);
  s.input('沿用原固定模型'); s.enter(); await flush();
  assert.equal(s.calls.find(([name]) => name === 'commerce_copilot_send')[1].expected_model_sha256, 'a'.repeat(64)); s.controller.dispose();
});
test('an unavailable automatic default blocks a new send without falling back to the fixed route', async () => {
  const catalog = autoCatalog(); catalog[1].selectable = false;
  const s = setup({ uncreated: true, catalog, defaultId: 'project-auto' }); await flush(); s.input('保留等待执行端的输入');
  assert.match(option(s, 'project-auto'), /aria-selected="true"[^>]*disabled/); assert.match(s.sendButton(), /disabled/);
  s.enter(); s.click('send'); await flush();
  assert.equal(s.calls.filter(([name]) => /commerce_copilot_(open|send|model)$/.test(name)).length, 0);
  assert.ok(s.controller.view().includes('保留等待执行端的输入')); s.controller.dispose();
});
test('a new conversation cannot send while its default catalog is still loading', async () => {
  let complete;
  const s = setup({ uncreated: true, override: name => name === 'commerce_model_list' ? new Promise(resolve => { complete = resolve; }) : undefined });
  s.input('尚未读到默认模型'); s.enter(); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_open').length, 0); assert.match(s.sendButton(), /disabled/);
  complete({ models: autoCatalog(), default_model_id: 'project-auto' }); await flush();
  assert.ok(s.controller.view().includes('尚未读到默认模型')); assert.match(option(s, 'project-auto'), /aria-selected="true"/); s.controller.dispose();
});
test('a changed default between catalog and opening preserves the draft without sending under a different model', async () => {
  const s = setup({ uncreated: true, catalog: autoCatalog(), defaultId: 'project-auto' }); await flush(); s.input('先核对改变后的默认模型');
  s.enter(); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_open').length, 1);
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 0);
  assert.ok(s.controller.view().includes('先核对改变后的默认模型')); assert.ok(s.controller.view().includes('模型配置已变化')); s.controller.dispose();
});
test('a transient initial catalog failure cannot pretend the fixed model is the default', async () => {
  const s = setup({ uncreated: true, override: name => { if (name === 'commerce_model_list') throw Error('temporarily_unavailable'); } });
  await flush(); s.input('目录恢复后再发送'); s.enter(); await flush();
  assert.match(s.sendButton(), /disabled/); assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_open').length, 0);
  assert.ok(s.controller.view().includes('目录恢复后再发送')); s.controller.dispose();
});
test('refreshing a new-conversation default keeps its unsent input and never creates a thread', async () => {
  const s = setup({ uncreated: true, catalog: autoCatalog(), defaultId: 'project-auto' }); await flush(); s.input('默认变化时保留草稿');
  s.state.defaultId = 'project-default'; s.click('models-refresh'); await flush();
  assert.match(option(s, 'project-default'), /aria-selected="true"/); assert.ok(s.controller.view().includes('默认变化时保留草稿'));
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_open').length, 0); s.controller.dispose();
});

test('explicit model refresh reads the catalog and selection while retaining an unsent draft', async () => {
  const s = setup(); await flush(); s.input('刷新后保留这条草稿');
  s.state.catalog.push({ id: 'local', label: '本地模型', selectable: true });
  s.state.thread.model_selection = { model_id: 'local', available: true, sha256: 'b'.repeat(64) };
  const before = s.calls.length; s.click('models-refresh'); await flush();
  assert.ok(s.calls.slice(before).some(([name]) => name === 'commerce_model_list'));
  assert.ok(s.calls.slice(before).some(([name]) => name === 'commerce_copilot_get'));
  assert.match(option(s, 'local'), /aria-selected="true"/);
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
  assert.match(option(s, 'removed'), /aria-selected="true"[^>]*disabled/);
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


test('the menu explains the real automatic strategy and separates model identity from its label', async () => {
  const s = setup({ catalog: autoCatalog() }); await flush();
  assert.ok(s.controller.view().includes('按可用执行端优先顺序选择'));
  assert.ok(s.controller.view().includes('fixed-model'));
  assert.ok(!s.controller.view().includes('按任务选择'));
  s.controller.dispose();
});
test('choosing the current model dismisses the menu without creating a conversation or updating its selection', async () => {
  const s = setup({ uncreated: true, catalog: autoCatalog(), defaultId: 'project-auto' }); await flush(); s.input('只打开菜单，不发任务');
  s.emit('toggle', { target: { id: 'copilot-model-picker', open: true } }); const before=s.calls.length;
  s.click('model-select', { model: 'project-auto' }); await flush();
  assert.equal(s.calls.length, before); assert.doesNotMatch(s.controller.view(), /id="copilot-model-picker" open/);
  assert.ok(s.controller.view().includes('只打开菜单，不发任务')); s.controller.dispose();
});
test('an unavailable model is explained and cannot be selected by an event or keyboard', async () => {
  const s = setup({ catalog: [{ id:'project-default',label:'固定模型',selectable:true },{ id:'offline',label:'本地模型',selectable:false,enabled:false }] }); await flush();
  assert.ok(s.controller.view().includes('未启用')); const before=s.calls.length;
  s.click('model-select',{model:'offline'}); await flush(); assert.equal(s.calls.length,before); s.controller.dispose();
});
test('selection is pinned to its own revision and preserves the composer', async () => {
  const s = setup({ catalog:autoCatalog(), selection:{model_id:'project-default',available:true,revision:'7'}, override:(name,args)=>{
    if(name==='commerce_copilot_model')return {...s.state.thread,model_selection:{model_id:args.model_id,available:true,revision:'8'}};
  } }); await flush(); s.input('切换模型仍保留问题'); s.click('model-select',{model:'project-auto'}); await flush();
  assert.equal(s.calls.find(([name])=>name==='commerce_copilot_model')[1].expected_revision,'7');
  assert.match(option(s,'project-auto'),/aria-selected="true"/); assert.ok(s.controller.view().includes('切换模型仍保留问题'));
  assert.equal(s.calls.filter(([name])=>name==='commerce_copilot_send').length,0); s.controller.dispose();
});
test('a rejected selection keeps the old model and menu with an actionable local error', async () => {
  const s=setup({catalog:autoCatalog(),override:name=>{if(name==='commerce_copilot_model')throw Error('model_not_ready');}}); await flush(); s.input('失败时保留');
  s.emit('toggle',{target:{id:'copilot-model-picker',open:true}}); s.click('model-select',{model:'project-auto'}); await flush();
  assert.match(option(s,'project-default'),/aria-selected="true"/); assert.match(s.controller.view(),/id="copilot-model-picker" open/);
  assert.ok(s.controller.view().includes('模型未切换')); assert.ok(s.controller.view().includes('失败时保留')); s.controller.dispose();
});
test('refresh provides pending and completion feedback, preserves input and prevents duplicate reads', async () => {
  let finish,delayed=false; const s=setup({override:name=>name==='commerce_model_list'&&delayed?new Promise(resolve=>{finish=resolve;}):undefined});
  await flush();s.input('刷新时保留');delayed=true;s.click('models-refresh');await flush();
  assert.ok(s.controller.view().includes('正在刷新')); const count=s.calls.length;s.click('models-refresh');await flush();assert.equal(s.calls.length,count);
  finish({models:autoCatalog(),default_model_id:'project-auto'});await flush();
  assert.ok(s.controller.view().includes('已刷新'));assert.ok(s.controller.view().includes('刷新时保留'));s.controller.dispose();
});
test('failed refresh keeps the cached selection and reports failure instead of success', async () => {
  let failed=false;const s=setup({override:name=>{if(name==='commerce_model_list'&&failed)throw Error('network_failed');}});await flush();failed=true;s.click('models-refresh');await flush();
  assert.match(option(s,'project-default'),/aria-selected="true"/);assert.ok(s.controller.view().includes('刷新未完成'));assert.ok(!s.controller.view().includes('已刷新'));s.controller.dispose();
});
test('model search includes labels and model names, supports clearing and never changes selection', async () => {
  const s=setup({catalog:autoCatalog()});await flush();const before=s.calls.length;
  s.emit('input',{target:{id:'copilot-model-query',value:'missing model'}});assert.ok(s.controller.view().includes('没有匹配的模型'));
  s.click('model-query-clear');await flush();assert.ok(option(s,'project-auto'));assert.match(option(s,'project-default'),/aria-selected="true"/);assert.equal(s.calls.length,before);s.controller.dispose();
});
test('search composition does not replace its input until composition finishes', async () => {
  const s=setup({catalog:autoCatalog()});await flush();s.emit('compositionstart',{target:{id:'copilot-model-query'}});
  s.emit('input',{target:{id:'copilot-model-query',value:'智能',isComposing:true}});
  s.emit('compositionend',{target:{id:'copilot-model-query',value:'智能'}});
  assert.ok(option(s,'project-auto'));assert.equal(option(s,'project-default'),undefined);assert.equal(s.calls.filter(([name])=>name==='commerce_copilot_model').length,0);s.controller.dispose();
});
test('arrow navigation from search reaches an available model without selecting it', async () => {
  let focused=0;const row={getClientRects:()=>[{}],focus(){focused++;},getAttribute:()=>null};
  const s=setup({queryAll:()=>[row]});await flush();const before=s.calls.length;
  s.emit('keydown',{target:{id:'copilot-model-query'},key:'ArrowDown',preventDefault(){}});
  assert.equal(focused,1);assert.equal(s.calls.length,before);s.controller.dispose();
});
test('an active run explains the selection lock and never switches a model', async () => {
  const s=setup({catalog:autoCatalog()});s.state.thread.latest_run={id:'active',status:'running'};await flush();s.click('model-select',{model:'project-auto'});await flush();
  assert.ok(s.controller.view().includes('处理结束后可切换模型'));assert.equal(s.calls.filter(([name])=>name==='commerce_copilot_model').length,0);s.controller.dispose();
});


test('an unconfirmed selection blocks sending until an explicit refresh reads the authoritative selection', async () => {
  let reject=true;
  const s=setup({catalog:autoCatalog(),override:name=>{if(name==='commerce_copilot_model'&&reject)throw Error('request_outcome_unknown');}});await flush();s.input('结果未知时保留');
  s.click('model-select',{model:'project-auto'});await flush();assert.ok(s.controller.view().includes('切换结果未确认'));assert.match(s.sendButton(),/disabled/);
  s.enter();await flush();assert.equal(s.calls.filter(([name])=>name==='commerce_copilot_send').length,0);
  reject=false;s.state.thread.model_selection={model_id:'project-auto',available:true,sha256:'d'.repeat(64)};
  s.click('models-refresh');await flush();assert.match(option(s,'project-auto'),/aria-selected="true"/);assert.doesNotMatch(s.sendButton(),/disabled/);
  assert.ok(s.controller.view().includes('结果未知时保留'));assert.equal(s.calls.filter(([name])=>name==='commerce_copilot_send').length,0);s.controller.dispose();
});


test('filtering models updates only the result list so native typing keeps its input and caret', async () => {
  let replacements=0;
  const list={replaceWith(){replacements++;}};
  const s=setup({element:id=>id==='copilot-model-list'?list:null,createElement:()=>({content:{querySelector:()=>({})}})});await flush();
  s.emit('input',{target:{id:'copilot-model-query',value:'d'}});
  s.emit('input',{target:{id:'copilot-model-query',value:'de'}});
  assert.equal(replacements,2);s.controller.dispose();
});


test('an asynchronous catalog repaint also preserves the model search DOM node', async () => {
  let kept=0;const input={value:'previous search'},nextInput={value:'',replaceWith(node){assert.equal(node,input);kept++;}};
  const root={replaceWith(){},setAttribute(){},querySelectorAll:()=>[]};
  const s=setup({query:selector=>selector==='#commerce-copilot'?root:null,element:id=>id==='copilot-model-query'?input:null,createElement:()=>({content:{querySelector:selector=>selector==='#copilot-model-query'?nextInput:null}})});
  await flush();assert.ok(kept>0);assert.equal(input.value,'');s.controller.dispose();
});
