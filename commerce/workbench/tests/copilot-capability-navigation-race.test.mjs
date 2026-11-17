import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import vm from 'node:vm';

const source = await readFile(new URL('../../web/copilot-ui.js', import.meta.url), 'utf8');
const flush = () => new Promise(setImmediate);
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[char]);

test('navigation during capability preparation never migrates another page draft', async () => {
  let finishPrepare, prepareStarted = false;
  const preparing = new Promise(resolve => { finishPrepare = resolve; });
  const handlers = new Map(), stored = new Map(), calls = [];
  const events = {
    addEventListener(name, handler) {
      if (!handlers.has(name)) handlers.set(name, new Set());
      handlers.get(name).add(handler);
    },
    removeEventListener(name, handler) { handlers.get(name)?.delete(handler); },
  };
  const document = { ...events, activeElement: null, querySelector: () => null, getElementById: () => null };
  const ui = {
    escape, icon: () => '', badge: escape, alert: escape,
    button: value => `<button>${escape(value.label)}</button>`,
    field: (label, control) => label + control, input: () => '<input>', select: () => '',
  };
  const window = { ...events, CommerceUI: ui, innerWidth: 1440, dispatchEvent() {} };
  window.parent = window;
  // Keep this test at the parent/helper interface. The independently owned
  // helper implementation and its in-flight design are deliberately not loaded.
  window.CommerceCopilotCapabilities = () => ({
    view: () => '', afterPaint() {}, restore() {}, contextChanged() {}, dispose() {},
    handleClick: async () => false, handleInput: () => false, keydown: () => false,
    async prepare() { prepareStarted = true; await preparing; return {}; },
  });
  vm.runInNewContext(source, {
    window, document, crypto: { randomUUID },
    localStorage: { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value) },
    setInterval() {}, clearInterval() {}, CustomEvent: class {},
  });
  const contextA = { module: 'overview', demo: true }, contextB = { module: 'orders', demo: true };
  let current = contextA;
  const draftAKey = 'commerce-copilot-draft-v1:new:' + JSON.stringify({ demo: true, module: 'overview' });
  const draftBKey = 'commerce-copilot-draft-v1:new:' + JSON.stringify({ demo: true, module: 'orders' });
  stored.set(draftBKey, 'UNSENT PAGE B QUESTION');
  const threadA = {
    id: 'capability-navigation-thread-A', context: contextA, context_sha256: 'synthetic-context-A', turns: [],
    model_selection: { model_id: 'project-default', sha256: 'synthetic-model' },
  };
  const controller = window.CommerceCopilot({
    compact: true, inline: true, getContext: () => current,
    getPageContext: () => ({ page: current.module, demo: true }),
    repaint() {}, scopeLabel: () => 'Synthetic scope',
    api: async (name, args) => {
      calls.push([name, args]);
      if (name === 'commerce_model_list') return {
        models: [{ id: 'project-default', label: 'Default', selectable: true }], default_model_id: 'project-default',
      };
      if (name === 'commerce_copilot_list') return { threads: [] };
      if (name === 'commerce_copilot_open' || name === 'commerce_copilot_send') return threadA;
      throw Error('Unexpected fixture tool: ' + name);
    },
  });
  const emit = (name, event) => { for (const handler of handlers.get(name) || []) handler(event); };
  try {
    controller.open(undefined, { focus: false });
    controller.view();
    await flush();
    emit('input', { target: { id: 'copilot-message', value: 'SEND PAGE A QUESTION', dataset: {} } });
    await flush();
    const target = {
      dataset: { copilotAction: 'send' },
      closest(selector) { return selector === '[data-copilot-action]' ? this : null; },
    };
    emit('click', { target, preventDefault() {} });
    await flush();
    assert.equal(prepareStarted, true);
    assert.equal(calls.filter(([name]) => name === 'commerce_copilot_open').length, 0);
    current = contextB;
    controller.contextChanged();
    controller.view();
    await flush();
    finishPrepare();
    await flush();
    await flush();

    assert.equal(stored.get(draftBKey), 'UNSENT PAGE B QUESTION', 'Preparing page A must not consume or clear page B draft');
    assert.notEqual(stored.get('commerce-copilot-draft-v1:' + threadA.id), 'UNSENT PAGE B QUESTION', 'Page B input must not be migrated into page A thread');
    const sends = calls.filter(([name]) => name === 'commerce_copilot_send');
    assert.ok(sends.length <= 1, 'Scope reconciliation must not duplicate the explicit request');
    if (sends.length === 0) {
      assert.equal(stored.get(draftAKey), 'SEND PAGE A QUESTION', 'Stopping after navigation must preserve the original page A draft');
    } else {
      const args = sends[0][1];
      assert.equal(args.message, 'SEND PAGE A QUESTION');
      assert.equal(args.thread_id, threadA.id);
      assert.equal(args.page_context.page, 'overview');
      const opened = calls.find(([name]) => name === 'commerce_copilot_open');
      assert.equal(opened?.[1].context.module, 'overview');
    }
  } finally {
    finishPrepare();
    controller.dispose();
  }
});
