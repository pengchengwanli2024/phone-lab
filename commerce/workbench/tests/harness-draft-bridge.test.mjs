import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const source = await readFile('../harness/client.js', 'utf8');
function setup(locks) {
  const values = new Map(), handlers = new Set(), replies = [], refs = [], registrations = new Map(); let fetches = 0, definition;
  const React = { useEffect: effect => effect(), useState: value => [value, () => {}], useRef: value => { const ref = { current: value }; refs.push(ref); return ref; }, useCallback: fn => fn, createElement: (type, props, ...children) => ({ type, props, children }) };
  const window = { __ModuleLoader__: { load: value => { definition = value; } }, addEventListener: (_name, fn) => handlers.add(fn), removeEventListener: (_name, fn) => handlers.delete(fn), dispatchEvent() {} };
  const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  vm.runInNewContext(source, { window, navigator: { locks }, crypto: { randomUUID: () => 'frame-nonce' }, localStorage: storage, AbortController, MutationObserver: class { observe() {} disconnect() {} }, document: { documentElement: {}, body: {} }, getComputedStyle: () => ({ colorScheme: 'light' }), fetch: async () => { fetches++; return { ok: true, text: async () => '<html></html>' }; }, CustomEvent: class {} });
  const ctx = { slots: { inject: (_name, callback) => callback(), register: (config, component) => { if (config.name === 'main') registrations.set(config.key, component); } }, effect: callback => callback(), sidebarRightTabs: { register() {} }, layout: { selectPanel() {} } };
  definition.factory(() => React).apply(ctx);
  const main = registrations.get('commerce')();
  const page = main.children[0].children[0]; refs.length = 0; page.type(page.props);
  const frame = { postMessage: message => replies.push(message) }; refs[0].current = { contentWindow: frame };
  const message = async (data, source = frame) => { for (const handler of handlers) await handler({ source, data }); };
  const request = (overrides = {}) => ({ type: 'commerce:copilot-draft', nonce: 'frame-nonce', id: 'request', op: 'read', key: 'commerce-copilot-draft-v1:new:{"module":"overview","demo":false}', ...overrides });
  return { values, replies, message, request, frameRef: refs[0], get fetches() { return fetches; } };
}
test('Harness draft storage rejects another frame or nonce without touching storage', async () => {
  const s = setup(); await s.message(s.request(), {}); await s.message(s.request({ nonce: 'wrong' }));
  assert.equal(s.replies.length, 0); assert.equal(s.values.size, 0);
});
test('Harness stores only its draft namespace and never routes draft text through backend invoke', async () => {
  const s = setup(), before = s.fetches;
  await s.message(s.request({ op: 'write', value: '本机未发送草稿', expected: '' }));
  assert.equal(s.replies.at(-1).value, '本机未发送草稿');
  await s.message(s.request()); assert.equal(s.replies.at(-1).value, '本机未发送草稿');
  await s.message(s.request({ key: 'auth.token' })); assert.equal(s.replies.at(-1).error, 'invalid_draft_key');
  assert.equal(s.fetches, before); assert.equal(s.values.size, 1);
});
test('Harness draft CAS, size and operation checks protect saved input', async () => {
  const s = setup(); await s.message(s.request({ op: 'write', value: '保留原文', expected: '' }));
  for (const [args, code] of [[{ op: 'write', value: '覆盖', expected: '' }, 'draft_storage_conflict'], [{ op: 'write', value: 'x'.repeat(2001), expected: '保留原文' }, 'invalid_draft_value'], [{ op: 'delete' }, 'invalid_draft_operation']]) {
    await s.message(s.request(args)); assert.equal(s.replies.at(-1).error, code);
  }
  assert.deepEqual([...s.values.values()], ['保留原文']);
});

test('a write waiting for the origin lock cannot modify storage after its frame is replaced', async () => {
  let release, locked;const locks={request:(key,callback)=>{locked=key;return new Promise((resolve,reject)=>{release=()=>{try{resolve(callback())}catch(error){reject(error)}}})}};
  const s=setup(locks),pending=s.message(s.request({op:'write',value:'旧窗口待保存',expected:''}));
  await Promise.resolve();
  assert.equal(locked,'commerce-copilot-draft-v1:new:{"module":"overview","demo":false}');
  s.frameRef.current={contentWindow:{}};release();await pending;
  assert.equal(s.values.size,0);assert.equal(s.replies.length,0);
});
