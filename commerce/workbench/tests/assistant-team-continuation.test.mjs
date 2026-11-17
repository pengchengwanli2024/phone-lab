import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { randomUUID } from 'node:crypto';

const source = await readFile('../web/copilot-ui.js', 'utf8');
const app = await readFile('src/app.tsx', 'utf8');
const flush = async () => { for (let i = 0; i < 5; i++) await new Promise(setImmediate); };
function fixture() {
  const calls = [], storage = new Map(), handlers = new Map();
  let context = { module: 'overview', demo: true }, page = { page: 'assistant-team', demo: false };
  const run = { id: 'original-run', status: 'awaiting_input', result: { answer: '合成原回答，等待补充。', questions: ['请明确目的地。'], proposals: [], evidence_refs: [] } };
  const thread = { id: 'original-thread', title: '合成物流原对话', context: structuredClone(context), context_sha256: 'original-context-hash', turns: [{ id: 'original-turn', question: '合成原问题：物流范围', run }], latest_run: run, model_selection: { model_id: 'fixed-local', label: '本机固定模型', available: true, sha256: 'a'.repeat(64) } };
  const listeners = { addEventListener(name, fn) { const rows = handlers.get(name) || new Set(); rows.add(fn); handlers.set(name, rows); }, removeEventListener(name, fn) { handlers.get(name)?.delete(fn); } };
  const escape = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  const ui = { escape, icon: () => '', badge: escape, alert: escape, button: value => '<button>' + escape(value.label) + '</button>', field: (_label, value) => value, input: () => '', select: () => '' };
  const document = { ...listeners, querySelector: () => null, getElementById: () => null, activeElement: null };
  const window = { ...listeners, CommerceUI: ui, innerWidth: 1440, dispatchEvent() {} }; window.parent = window;
  vm.runInNewContext(source, { window, document, crypto: { randomUUID }, setTimeout, clearTimeout, setInterval: () => 1, clearInterval() {}, CustomEvent: class {}, localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) } });
  const controller = window.CommerceCopilot({
    api: async (name, args) => { calls.push({ name, args });
      if (name === 'commerce_model_list') return { models: [{ id: 'project-auto', label: '智能选择', selectable: true }, { id: 'fixed-local', label: '本机固定模型', selectable: true }], default_model_id: 'project-auto' };
      if (name === 'commerce_copilot_list') return { threads: [structuredClone(thread)] };
      if (name === 'commerce_copilot_get') { assert.equal(args.thread_id, thread.id); return structuredClone(thread); }
      throw Error('Unexpected API ' + name);
    }, inline: true, compact: true, getContext: () => context, getPageContext: () => ({ ...page, demo: !!context.demo }), isActive: () => true, repaint() {}, scopeLabel: value => value.module, toast() {}, modal() {}, closeModal() {},
  });
  return { controller, calls, thread, metadata(next) { page = { ...page, ...next }; controller.contextChanged(); }, navigate() { context = { module: 'orders', demo: false }; page = { page: 'orders', demo: false }; controller.contextChanged(); } };
}
function assertOriginal(s) {
  const html = s.controller.view();
  assert.ok(html.includes(s.thread.turns[0].question)); assert.ok(html.includes(s.thread.latest_run.result.answer));
  assert.match(html, /id="copilot-model-trigger"[^>]*aria-label="选择对话模型：本机固定模型/);
  assert.ok(s.calls.every(call => ['commerce_model_list', 'commerce_copilot_list', 'commerce_copilot_get'].includes(call.name)), 'continuation never creates a thread, sends a model request or changes model/context');
}

test('a team-only original scope pin preserves original turns and model through page metadata refreshes', async () => {
  const s = fixture(); s.controller.open(undefined, { focus: false }); await flush(); await s.controller.openThread(s.thread.id); assertOriginal(s);
  for (const metadata of [{ section: 'details' }, { source: 'local', errors: ['合成页面反馈'] }, { section: 'list', errors: [] }]) { s.metadata(metadata); await flush(); assertOriginal(s); }
  s.controller.dispose();
});

test('ordinary module navigation still clears the team-only pin and follows the new page', async () => {
  const s = fixture(); s.controller.open(undefined, { focus: false }); await flush(); await s.controller.openThread(s.thread.id); assertOriginal(s);
  s.navigate(); await flush();
  assert.ok(!s.controller.view().includes(s.thread.latest_run.result.answer));
  assert.ok(s.calls.every(call => ['commerce_model_list', 'commerce_copilot_list', 'commerce_copilot_get'].includes(call.name)));
  s.controller.dispose();
});

test('the parent keeps the visited team mounted but supplies its actual visibility', () => {
  const team = app.match(/<AssistantTeam\b[^>]*(?:=>[^>]*)?\/>/)?.[0] || '';
  assert.match(team, /active=\{tab\s*===\s*['"]assistant-team['"]\}/);
});

test('only the team conversation callback opts into the original scope without navigating', () => {
  assert.ok(/<AssistantTeam\b[^\n]*onConversation=\{id\s*=>\s*void openResearchThread\(id,\s*false,\s*true\)\}/.test(app), 'team callback must keep its page and opt into the original scope');
  assert.ok(/openResearchThread\(id:\s*string,\s*returnToModule\s*=\s*false,\s*keepOriginalScope\s*=\s*false\)/.test(app), 'other callers must retain the default unpinned behavior');
  assert.ok(/setAssistantContext\(keepOriginalScope\s*\?\s*thread\.context\s*:\s*null\)/.test(app), 'the opt-in scope must come from the fetched original thread');
});
