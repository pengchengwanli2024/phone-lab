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
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

test('expanded input entered during first-send draft migration remains unsent and recoverable', async () => {
  const opening = deferred(), migration = deferred();
  const handlers = new Map(), stored = new Map(), calls = [], modals = [];
  let migrationWriteStarted = false;
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
  vm.runInNewContext(source, {
    window, document, crypto: { randomUUID },
    localStorage: { getItem: () => null, setItem() {} },
    setInterval() {}, clearInterval() {}, CustomEvent: class {},
  });
  // Model the existing asynchronous host draft bridge, including compare-and-set.
  // Only the first migration write is delayed; later edits retain normal ordering.
  window.CommerceCopilotDraftStorage = () => ({
    async request(operation, key, value, expected) {
      if (operation === 'read') return stored.get(key) || '';
      if (key === 'commerce-copilot-draft-v1:migration-thread' && !migrationWriteStarted) {
        migrationWriteStarted = true;
        await migration.promise;
      }
      assert.equal(stored.get(key) || '', expected, 'The fixture must preserve draft compare-and-set semantics');
      stored.set(key, value);
      return value;
    },
    dispose() {},
  });
  const context = { module: 'overview', demo: true };
  const thread = {
    id: 'migration-thread', context, context_sha256: 'synthetic-context', turns: [],
    model_selection: { model_id: 'project-default', sha256: 'synthetic-model' },
  };
  const controller = window.CommerceCopilot({
    compact: true, inline: true, getContext: () => context, repaint() {}, scopeLabel: () => 'Synthetic scope',
    modal: (title, body) => modals.push({ title, body }), closeModal() {},
    api: async (name, args) => {
      calls.push([name, args]);
      if (name === 'commerce_model_list') return {
        models: [{ id: 'project-default', label: 'Default', selectable: true }], default_model_id: 'project-default',
      };
      if (name === 'commerce_copilot_list') return { threads: [] };
      if (name === 'commerce_copilot_open') { await opening.promise; return thread; }
      if (name === 'commerce_copilot_send') return thread;
      throw Error('Unexpected fixture tool: ' + name);
    },
  });
  const emit = (name, event) => { for (const handler of handlers.get(name) || []) handler(event); };
  const click = action => {
    const target = {
      dataset: { copilotAction: action },
      closest(selector) { return selector === '[data-copilot-action]' ? this : null; },
    };
    emit('click', { target, preventDefault() {} });
  };
  try {
    controller.open(undefined, { focus: false });
    controller.view();
    await flush();
    emit('input', { target: { id: 'copilot-message', value: 'FIRST QUESTION', dataset: {} } });
    await flush();
    click('send');
    await flush();
    assert.equal(calls.filter(([name]) => name === 'commerce_copilot_open').length, 1);
    click('expand-editor');
    const encodedOwner = modals.at(-1)?.body.match(/data-copilot-draft-key="([^"]+)"/)?.[1];
    assert.ok(encodedOwner, 'Expanded editor must retain the draft identity it opened with');
    const owner = encodedOwner.replaceAll('&quot;', '"').replaceAll('&#39;', "'").replaceAll('&amp;', '&');
    assert.ok(owner.startsWith('new:'), 'The expanded editor is opened before a thread is acknowledged');
    opening.resolve();
    await flush();
    assert.equal(migrationWriteStarted, true);
    emit('input', {
      target: { id: 'copilot-expanded-message', value: 'NEXT UNSENT QUESTION', dataset: { copilotDraftKey: owner } },
    });
    await flush();
    migration.resolve();
    await flush();
    await flush();
    assert.deepEqual(calls.filter(([name]) => name === 'commerce_copilot_send').map(([, args]) => args.message), ['FIRST QUESTION']);
    assert.ok(controller.view().includes('NEXT UNSENT QUESTION'), 'A late expanded edit must remain in the current composer');
    assert.ok([...stored.values()].includes('NEXT UNSENT QUESTION'), 'A late expanded edit must remain recoverable after remount');
  } finally {
    opening.resolve();
    migration.resolve();
    controller.dispose();
  }
});

test('a migrated editor completing IME after an external thread switch still belongs to its original thread', async () => {
  const opening = deferred(), handlers = new Map(), stored = new Map(), calls = [];
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
  vm.runInNewContext(source, {
    window, document, crypto: { randomUUID },
    localStorage: { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value) },
    setInterval() {}, clearInterval() {}, CustomEvent: class {},
  });
  const context = { module: 'overview', demo: true };
  const threadA = {
    id: 'migration-ime-thread-A', context, context_sha256: 'synthetic-context-A', turns: [],
    model_selection: { model_id: 'project-default', sha256: 'synthetic-model' },
  };
  const threadB = { ...threadA, id: 'migration-ime-thread-B', context_sha256: 'synthetic-context-B' };
  const controller = window.CommerceCopilot({
    compact: true, inline: true, getContext: () => context, repaint() {}, scopeLabel: () => 'Synthetic scope',
    api: async (name, args) => {
      calls.push([name, args]);
      if (name === 'commerce_model_list') return {
        models: [{ id: 'project-default', label: 'Default', selectable: true }], default_model_id: 'project-default',
      };
      if (name === 'commerce_copilot_list') return { threads: [] };
      if (name === 'commerce_copilot_open') { await opening.promise; return threadA; }
      if (name === 'commerce_copilot_send') return threadA;
      if (name === 'commerce_copilot_get') return args.thread_id === threadA.id ? threadA : threadB;
      throw Error('Unexpected fixture tool: ' + name);
    },
  });
  const emit = (name, event) => { for (const handler of handlers.get(name) || []) handler(event); };
  const click = action => {
    const target = {
      dataset: { copilotAction: action },
      closest(selector) { return selector === '[data-copilot-action]' ? this : null; },
    };
    emit('click', { target, preventDefault() {} });
  };
  try {
    controller.open(undefined, { focus: false });
    controller.view();
    await flush();
    emit('input', { target: { id: 'copilot-message', value: 'FIRST QUESTION', dataset: {} } });
    await flush();
    click('send');
    await flush();
    const editor = { id: 'copilot-message', value: 'FIRST QUESTION', dataset: {} };
    emit('compositionstart', { target: editor });
    assert.ok(editor.dataset.copilotDraftKey.startsWith('new:'));
    editor.value = 'IME INTERMEDIATE';
    emit('input', { target: editor });
    await flush();
    opening.resolve();
    await flush();
    await flush();
    assert.deepEqual(calls.filter(([name]) => name === 'commerce_copilot_send').map(([, args]) => args.message), ['FIRST QUESTION']);
    await controller.openThread(threadB.id);
    editor.value = 'IME FINAL AFTER SWITCH';
    emit('compositionend', { target: editor });
    await flush();
    assert.equal(stored.get('commerce-copilot-draft-v1:' + threadA.id), 'IME FINAL AFTER SWITCH', 'The migrated editor must keep thread A as its stable draft owner');
    assert.notEqual(stored.get('commerce-copilot-draft-v1:' + threadB.id), 'IME FINAL AFTER SWITCH', 'The late composition must not enter the newly selected thread B');
    assert.ok(!controller.view().includes('IME FINAL AFTER SWITCH'));
    await controller.openThread(threadA.id);
    await flush();
    assert.ok(controller.view().includes('IME FINAL AFTER SWITCH'), 'Returning to thread A must restore the completed composition');
    assert.equal(calls.filter(([name]) => name === 'commerce_copilot_send').length, 1);
  } finally {
    opening.resolve();
    controller.dispose();
  }
});
