import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../../web/app.js', import.meta.url), 'utf8');
const refresh = source.slice(source.indexOf('  async function refreshThemePreference(){'), source.indexOf('  async function changeTheme(control){'));
const listener = source.split('\n').find(line => line.includes("event.data.type!=='commerce:legacy-navigate'"));
assert.ok(refresh && listener);
function harness(reactHost = true) {
  const handlers = {}, calls = [], state = { theme: 'light', themeBusy: false, themeRevision: 0 }, parent = {};
  let resolvePreference;
  const context = vm.createContext({
    state, parent, reactHost, bridgeNonce: 'synthetic-theme', labels: {}, analysis: {}, paint() {}, navigate() {},
    window: { addEventListener: (type, handler) => { handlers[type] = handler; } },
    ui: { applyTheme: theme => { context.appliedTheme = theme; } },
    document: { querySelector: () => null },
    api: tool => { calls.push(tool); return new Promise(resolve => { resolvePreference = resolve; }); },
  });
  vm.runInContext(`${refresh}\n${listener}\nglobalThis.refresh = refreshThemePreference;`, context);
  return { context, state, calls, resolve: value => resolvePreference(value), hostTheme: (theme, nonce = 'synthetic-theme') => handlers.message({ source: parent, data: { type: 'commerce:legacy-navigate', nonce, theme } }) };
}
test('React embedded modules use the host theme without a competing preference read', async () => {
  const h = harness();
  h.hostTheme('dark');
  const pending = h.context.refresh();
  if (h.calls.length) h.resolve({ theme: 'light' });
  await pending;
  assert.deepEqual(h.calls, []);
  assert.equal(h.context.appliedTheme, 'dark');
  assert.equal(h.state.theme, 'dark');
});
test('a delayed preference result cannot replace a newer authenticated host theme', async () => {
  const h = harness(false);
  const pending = h.context.refresh();
  h.hostTheme('dark');
  h.resolve({ theme: 'light' });
  await pending;
  assert.equal(h.context.appliedTheme, 'dark');
  assert.equal(h.state.theme, 'dark');
});
test('standalone preference refresh remains available and a foreign host message is ignored', async () => {
  const h = harness(false);
  h.hostTheme('dark', 'foreign');
  assert.equal(h.context.appliedTheme, undefined);
  const pending = h.context.refresh();
  h.resolve({ theme: 'system' });
  await pending;
  assert.deepEqual(h.calls, ['commerce_ui_get_preferences']);
  assert.equal(h.context.appliedTheme, 'system');
});
