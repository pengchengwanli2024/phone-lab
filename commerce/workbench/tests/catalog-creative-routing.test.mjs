import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { transform } from 'esbuild';

const productSource = readFileSync(new URL('../../web/product-workspace-ui.js', import.meta.url), 'utf8');
const catalogSource = readFileSync(new URL('../../web/catalog-ui.js', import.meta.url), 'utf8');
const legacySource = readFileSync(new URL('../src/legacy.tsx', import.meta.url), 'utf8');
const kitSource = readFileSync(new URL('../../ui/kit.js', import.meta.url), 'utf8');
const clone = value => JSON.parse(JSON.stringify(value));
const turn = () => new Promise(resolve => setImmediate(resolve));
const project = suffix => ({
  id: 'project-' + suffix,
  brief: { product_binding: { case_id: 'case-' + suffix, source_sha256: suffix.repeat(64) } },
});

function cut(source, start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from);
  assert.ok(from >= 0 && to > from, 'the actual callback seam must be present');
  return source.slice(from, to);
}

function catalogFixture(readProject = async id => project(id.at(-1))) {
  const messages = [], calls = [], listeners = {};
  let options;
  const state = {
    s: { generation: 0, catalogOpen: true, tab: 'overview' },
    bridged: true,
    nonce: 'synthetic-routing-nonce',
    crypto: globalThis.crypto,
    CustomEvent: globalThis.CustomEvent,
    setTimeout, clearTimeout,
    parent: { postMessage: value => messages.push(clone(value)) },
    api: async (tool, args) => {
      calls.push({ tool, args: clone(args) });
      // This is the public creative_get contract, including its parameter name.
      assert.equal(tool, 'commerce_creative_get');
      assert.equal(typeof args.project_id, 'string');
      assert.equal(args.id, undefined);
      return readProject(args.project_id);
    },
    render() {}, reload: async () => {}, hasPendingProductEdits: () => false,
    document: {
      addEventListener: (type, fn) => (listeners[type] ||= []).push(fn),
      querySelector: () => null,
      documentElement: { dataset: {}, getAttribute: () => 'light', setAttribute() {} },
    },
    window: { dispatchEvent() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) },
  };
  const context = vm.createContext(state);
  vm.runInContext(kitSource, context);
  state.window.CommerceCatalog = value => { options = value; return {}; };
  state.window.CommerceProductCreativeLinks = () => ({});
  vm.runInContext(cut(productSource, '  function openCreativeMaster(', '  let copilot,'), context);
  const onCreative = options.onCreative;
  vm.runInContext(catalogSource, context);
  state.window.CommerceCatalog({ api: state.api, repaint() {}, onCreative });
  return {
    state, messages, calls, onCreative,
    async clickProject(id) {
      const button = { disabled: false, dataset: { catalogAction: 'project', project: id }, closest: () => ({}) };
      for (const listener of listeners.click || []) {
        await listener({ target: { closest: () => button }, preventDefault() {} });
      }
    },
  };
}

const receiveCode = (await transform(
  "let active = true, catalogCreativeRequest = '';\n" +
  cut(legacySource, '    const receive = async (event: MessageEvent) => {', "      if(product&&m.type==='commerce:workspace-edit-state'") +
  '    }; this.receive = receive;', { loader: 'ts' },
)).code;

function parentFixture(readProject = async id => project(id.at(-1))) {
  const calls = [], opened = [], errors = [];
  const frameWindow = { postMessage: value => errors.push(clone(value)) };
  const state = {
    product: true, caseId: 'case-a',
    frame: { current: { contentWindow: frameWindow } },
    nonce: { current: 'synthetic-routing-nonce' }, activeView: { current: true },
    creativeCallback: { current: value => opened.push(clone(value)) },
    creativeRequest: { current: null }, creativeOpened: { current() {} },
    api: async (tool, args) => {
      calls.push({ tool, args: clone(args) });
      assert.equal(tool, 'commerce_creative_get');
      assert.equal(typeof args.project_id, 'string');
      assert.equal(args.id, undefined);
      return readProject(args.project_id);
    },
  };
  vm.createContext(state);
  vm.runInContext(receiveCode, state);
  return {
    state, calls, opened, errors,
    send: (message, overrides = {}) => state.receive({ source: frameWindow, data: message, ...overrides }),
    pending(id) { return this.send({ type: 'commerce:workspace-catalog-creative-pending', nonce: state.nonce.current, id }); },
    open(suffix, id) {
      return this.send({ type: 'commerce:workspace-catalog-creative', nonce: state.nonce.current,
        case_id: 'case-' + suffix, source_sha256: suffix.repeat(64), project_id: 'project-' + suffix, catalog_request_id: id });
    },
  };
}

function connect(local, parent) {
  const deliveries = [];
  const post = local.state.parent.postMessage;
  local.state.parent.postMessage = message => { post(message); deliveries.push(parent.send(message)); };
  return () => Promise.all(deliveries);
}

test('the real catalog id-only action uses project_id and reaches the exact master route', async () => {
  const local = catalogFixture(), parent = parentFixture();
  const settle = connect(local, parent);
  await local.clickProject('project-b');
  await settle();
  assert.deepEqual(local.calls, [{ tool: 'commerce_creative_get', args: { project_id: 'project-b' } }]);
  assert.equal(local.messages[0].type, 'commerce:workspace-catalog-creative-pending');
  assert.equal(local.messages[1].catalog_request_id, local.messages[0].id);
  assert.deepEqual(parent.opened, [{ case_id: 'case-b', source_sha256: 'b'.repeat(64), project_id: 'project-b' }]);
});

test('a complete new project response announces its request without another product lookup', async () => {
  const local = catalogFixture();
  await local.onCreative(project('b'));
  assert.equal(local.calls.length, 0);
  assert.equal(local.messages.length, 2);
  assert.equal(local.messages[1].catalog_request_id, local.messages[0].id);
  assert.equal(local.messages[1].project_id, 'project-b');
});

test('a later catalog click cancels the previous product read even within the same product generation', async () => {
  const releases = {};
  const local = catalogFixture(id => new Promise(resolve => { releases[id] = resolve; }));
  const parent = parentFixture(), settle = connect(local, parent);
  const first = local.clickProject('project-b'), latest = local.clickProject('project-c');
  assert.equal(local.messages.filter(message => message.type.endsWith('-pending')).length, 2);
  releases['project-c'](project('c'));
  await latest;
  releases['project-b'](project('b'));
  await first;
  await settle();
  assert.deepEqual(local.messages.filter(message => message.type === 'commerce:workspace-catalog-creative').map(message => message.project_id), ['project-c']);
  assert.deepEqual(parent.opened.map(value => value.project_id), ['project-c']);
});

test('a pending newer click cancels older parent validation before the newer product read completes', async () => {
  let releaseParentB, releaseLocalC;
  const local = catalogFixture(id => id === 'project-c' ? new Promise(resolve => { releaseLocalC = resolve; }) : project('b'));
  const parent = parentFixture(id => id === 'project-b' ? new Promise(resolve => { releaseParentB = resolve; }) : project('c'));
  const settle = connect(local, parent);
  await local.clickProject('project-b');
  assert.equal(typeof releaseParentB, 'function');
  const latest = local.clickProject('project-c');
  releaseParentB(project('b'));
  await turn();
  assert.deepEqual(parent.opened, []);
  releaseLocalC(project('c'));
  await latest;
  await settle();
  assert.deepEqual(parent.opened.map(value => value.project_id), ['project-c']);
});

test('obsolete parent failures do not report an error for the newer catalog request', async () => {
  let rejectOld;
  const parent = parentFixture(() => new Promise((_resolve, reject) => { rejectOld = reject; }));
  await parent.pending('request-b');
  const old = parent.open('b', 'request-b');
  await parent.pending('request-c');
  rejectOld(Error('synthetic unavailable'));
  await old;
  assert.deepEqual(parent.opened, []);
  assert.deepEqual(parent.errors, []);
});

test('a replaced product generation or failed lookup retains the page instead of opening a project', async () => {
  let release;
  const local = catalogFixture(() => new Promise(resolve => { release = resolve; }));
  const pending = local.clickProject('project-b');
  local.state.s.generation++;
  release(project('b'));
  await pending;
  assert.equal(local.messages.filter(message => message.type === 'commerce:workspace-catalog-creative').length, 0);
  const failed = catalogFixture(async () => { throw Error('synthetic unavailable'); });
  await failed.clickProject('project-b');
  assert.match(failed.state.s.error, /未能确认/);
  assert.equal(failed.messages.filter(message => message.type === 'commerce:workspace-catalog-creative').length, 0);
});

test('wrong project IDs and incomplete bindings are rejected before the final navigation message', async () => {
  for (const response of [project('a'), { id: 'project-b' }, { id: 'project-b', brief: { product_binding: { case_id: 'case-b' } } }]) {
    const local = catalogFixture(async () => response);
    await local.clickProject('project-b');
    assert.equal(local.messages.filter(message => message.type === 'commerce:workspace-catalog-creative').length, 0);
    assert.match(local.state.s.error, /尚未读回/);
  }
});

test('parent pending messages require the matching source, nonce and active product frame', async () => {
  const parent = parentFixture();
  const pending = { type: 'commerce:workspace-catalog-creative-pending', nonce: parent.state.nonce.current, id: 'request-b' };
  await parent.send(pending, { source: {} });
  await parent.open('b', 'request-b');
  await parent.send({ ...pending, nonce: 'wrong-nonce' });
  await parent.open('b', 'request-b');
  parent.state.activeView.current = false;
  await parent.send(pending);
  parent.state.activeView.current = true;
  await parent.open('b', 'request-b');
  assert.deepEqual(parent.calls, []);
  assert.deepEqual(parent.opened, []);
});

test('parent confirms the catalog project binding and keeps the summary path on its current product', async () => {
  const parent = parentFixture(async () => project('a'));
  await parent.pending('request-b');
  await parent.open('b', 'request-b');
  assert.deepEqual(parent.opened, []);
  assert.equal(parent.errors[0].type, 'commerce:workspace-creative-error');
  await parent.send({ type: 'commerce:workspace-creative', nonce: parent.state.nonce.current, case_id: 'case-b', source_sha256: 'b'.repeat(64) });
  assert.deepEqual(parent.opened, []);
  await parent.send({ type: 'commerce:workspace-creative', nonce: parent.state.nonce.current, case_id: 'case-a', source_sha256: 'a'.repeat(64) });
  assert.deepEqual(parent.opened, [{ case_id: 'case-a', source_sha256: 'a'.repeat(64) }]);
});
