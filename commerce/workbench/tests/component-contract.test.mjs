import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

// Actual installed SurfaceView + manager; labels/order must never determine input names.
const output = path.resolve('../../.local/coordination/first-batch-20261114/component-contract-renderer.cjs');
await mkdir(path.dirname(output), { recursive: true });
const bundle = await build({ stdin: { contents: `
export { commerceUI, CalculationContext } from './src/calculation';
export { SurfaceView, GenerativeUIRuntimeContext } from '@copilotkit/react-core/v2/generative-ui/native';
export { GenerativeUISurfaceManager, createGenerativeUIDispatcher } from '@copilotkit/core/generative-ui';
export { createElement } from 'react';
export { renderToStaticMarkup } from 'react-dom/server';
`, resolveDir: process.cwd(), loader: 'tsx' }, bundle: true, write: false, format: 'cjs', platform: 'node', external: ['react', 'react-dom/server'], nodePaths: [path.resolve('node_modules')] });
// Keep React single-instance and resolve it relative to the workbench, not the private output directory.
const require = createRequire(path.resolve('package.json'));
const module = { exports: {} };
// SurfaceView deliberately has an empty server snapshot. Use its live store snapshot
// for this synchronous render, keeping the actual manager, resolver and components.
const rendererRequire = name => name === 'react' ? { ...require('react'), useSyncExternalStore: (_subscribe, getSnapshot) => getSnapshot() } : require(name);
new Function('require', 'module', 'exports', bundle.outputFiles[0].text)(rendererRequire, module, module.exports);
await writeFile(output, bundle.outputFiles[0].text);
const { commerceUI, CalculationContext, SurfaceView, GenerativeUIRuntimeContext, GenerativeUISurfaceManager, createGenerativeUIDispatcher, createElement: h, renderToStaticMarkup } = module.exports;
const payload = JSON.parse(execFileSync('python3', ['-c', "import json,sys;sys.path.insert(0,'../');from a2ui.cost import messages;print(json.dumps(messages('cost_'+'a'*32,{},None)))"], { encoding: 'utf8' }));
function render(operations, values = {}) {
  const manager = new GenerativeUISurfaceManager(commerceUI);
  manager.registerTarget('test', { components: ['Column', 'Text', 'NumberField', 'CurrencyField', 'Button'] });
  const content = { surfaceId: 'cost_' + 'a'.repeat(32), catalogId: commerceUI.id, operations, target: 'test', status: 'ready', rejected: [] };
  manager.ingest('test', undefined, content);
  const surface = manager.getSurface('test', content.surfaceId);
  const runtime = { manager, dispatcher: createGenerativeUIDispatcher({ getDeclared: () => new Map() }), ui: commerceUI, transport: 'tool', config: { ui: commerceUI }, forwardEvent: async () => {}, reportError: () => {} };
  assert.ok(surface, 'manager should accept the existing wire payload');
  const state = { values, onChange() {}, calculate() {}, save() {}, busy: false, dirty: false, bound: false, errors: {} };
  return renderToStaticMarkup(h(GenerativeUIRuntimeContext.Provider, { value: runtime }, h(CalculationContext.Provider, { value: state }, h(SurfaceView, { surface }))));
}
test('renamed field labels preserve stable input names and percentage display', () => {
  const changed = structuredClone(payload);
  for (const node of changed[0].createSurface.components) if (node.id.startsWith('field_')) node.label = 'New label <safe>';
  const html = render(changed, { price: '123', commission_rate: '7.3' });
  assert.match(html, /name="price"[^>]*value="123"/);
  assert.match(html, /name="commission_rate"[^>]*value="7.3"/);
  assert.ok(html.includes('New label &lt;safe&gt;'));
});
test('reordered and fewer children keep field identities and panel roles', () => {
  const changed = structuredClone(payload), nodes = changed[0].createSurface.components;
  nodes.find(n => n.id === 'root').children.reverse();
  nodes.find(n => n.id === 'fields').children = ['field_ad_rate', 'field_price', 'field_currency', 'calculate'];
  changed[0].createSurface.components = nodes.filter(n => !n.id.startsWith('field_') || ['field_ad_rate', 'field_price', 'field_currency'].includes(n.id));
  const html = render(changed, { price: '88', ad_rate: '12' });
  assert.match(html, /name="price"[^>]*value="88"/);
  assert.match(html, /max="100"[^>]*name="ad_rate"[^>]*value="12"/);
  assert.ok(html.includes('单件成本'));
  assert.ok(html.includes('测算结果'));
  assert.ok(html.indexOf('name="price"') < html.indexOf('name="ad_rate"'), 'amount/rate groups use contract semantics');
});
