// Focus refresh must yield to an explicit click; no browser, feed or network.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../web/intel-ui.js', import.meta.url), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const documentEvents = new Map(), windowEvents = new Map(), requests = [];
  const document = { addEventListener: (type, fn) => { documentEvents.set(type, [...(documentEvents.get(type) || []), fn]); }, querySelector: () => null };
  const window = { CommerceUI: {}, CommerceSocial: () => ({}), addEventListener: (type, fn) => windowEvents.set(type, fn) };
  vm.runInNewContext(source, { window, document, location: { hash: '' }, setInterval() {}, setTimeout, clearTimeout, URL, Date, console });
  const api = (tool, args) => {
    if (tool !== 'commerce_intel_search') return Promise.resolve({ watches: [], jobs: [], alerts: [] });
    return new Promise(resolve => requests.push({ args, resolve }));
  };
  const intel = window.CommerceIntel({ api, repaint() {}, isActive: () => true });
  const clickNext = () => {
    const target = { dataset: { intelAction: 'next' } };
    for (const fn of documentEvents.get('click')) fn({ target: { closest: selector => selector.includes('data-intel-action') ? target : null } });
  };
  const finish = (index, cursor, offset = 0) => requests[index].resolve({ items: [], sources: [], total: 50, offset, next_cursor: cursor });
  return { intel, requests, clickNext, finish, focus: () => windowEvents.get('focus')() };
}
test('focus refresh cannot consume the first explicit next-page click or overwrite its result', async () => {
  const f = fixture(); await f.intel.enter(); f.finish(0, 'page-two'); await tick();
  f.focus(); assert.equal(f.requests.length, 2);
  f.clickNext();
  assert.equal(f.requests.length, 3, 'Explicit pagination was silently swallowed by the quiet focus refresh');
  assert.equal(f.requests[2].args.cursor, 'page-two');
  f.finish(2, 'page-three', 20); await tick();
  f.finish(1, 'stale-page-two'); await tick();
  f.clickNext(); assert.equal(f.requests[3].args.cursor, 'page-three', 'Late background data replaced the current page');
  f.finish(3, null, 40); await tick();
});
test('focus refresh does not supersede an already pending foreground search', async () => {
  const f = fixture(); await f.intel.enter();
  f.focus(); assert.equal(f.requests.length, 1);
  f.finish(0, null); await tick();
});
