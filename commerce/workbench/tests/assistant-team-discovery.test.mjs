import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { createHash, webcrypto } from 'node:crypto';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const compiled = await build({ entryPoints: ['src/assistant-tool-discovery.tsx'], bundle: true, write: false, format: 'cjs', platform: 'node', external: ['react'], loader: { '.css': 'empty' } });
const module = { exports: {} }, require = createRequire(import.meta.url);
const scope = vm.createContext({ module, exports: module.exports, require, TextEncoder, crypto: webcrypto, window: { CommerceUI: { icon: () => '' } } });
vm.runInContext(compiled.outputFiles[0].text, scope);
const { AssistantToolDiscovery, ToolDiscoveryCatalog, registeredMcpExtensions, exactDefinitionJson, extensionDefinitionHash } = module.exports;
const entry = { id: 'ext_' + 'a'.repeat(20), kind: 'plugin', name: '已登记MCP', version: 2, definition: { kind: 'plugin', spec: { transport: 'mcp_http' } } };

test('discovery selection contains only existing MCP-HTTP plugin registrations', () => {
  const rows = [entry, { ...entry, id: 'http', definition: { kind: 'plugin', spec: { transport: 'http' } } }, { ...entry, id: 'builtin', definition: { kind: 'plugin', spec: { transport: 'builtin' } } }, { ...entry, id: 'skill', kind: 'skill' }, { ...entry, id: 'broken', definition: null }];
  assert.deepEqual(Array.from(registeredMcpExtensions(rows), row => row.id), [entry.id]);
});

test('fallback JSON exactly matches Python Unicode key sorting and UTF-8 encoding', async () => {
  const definition = { name: '登记\nMCP', '𠮷': 'astral sorts after BMP', '': 'BMP', spec: { transport: 'mcp_http', required: ['中', '文'], empty: null, enabled: false }, kind: 'plugin' };
  const python = execFileSync('python3', ['-c', 'import json,sys;print(json.dumps(json.load(sys.stdin),ensure_ascii=False,sort_keys=True,separators=(",",":")),end="")'], { input: JSON.stringify(definition), encoding: 'utf8' });
  assert.equal(exactDefinitionJson(definition), python);
  assert.equal(await extensionDefinitionHash({ ...entry, definition }), createHash('sha256').update(python).digest('hex'));
});

test('server definition hash takes precedence over redacted or numerically ambiguous public definitions', async () => {
  const definition = { kind: 'plugin', max_seconds: 20, note: '[redacted]', spec: { transport: 'mcp_http' } }, expected = 'a'.repeat(64);
  assert.equal(await extensionDefinitionHash({ ...entry, definition, definition_sha256: expected }), expected);
  assert.throws(() => exactDefinitionJson({ limit: 20 }), /unsafe_number/);
  assert.throws(() => exactDefinitionJson({ note: '[redacted]' }), /redacted_definition/);
  assert.throws(() => exactDefinitionJson({ note: '\ud800' }), /hash_unavailable/);
});

test('complex schema and remote metadata remain inert and do not become usable or enabled tools', () => {
  const unsafe = '<img src=x onerror=attack()>', result = { extension_id: entry.id, version: 2, definition_sha256: 'a'.repeat(64), catalog_sha256: 'b'.repeat(64), tools: [{ name: unsafe, description: unsafe, inputSchema: { type: 'object', properties: { q: { anyOf: [{ type: 'string' }, { type: 'integer' }] } } }, extension_schema_supported: false, annotations: { destructiveHint: false, title: unsafe } }] };
  const html = renderToStaticMarkup(React.createElement(ToolDiscoveryCatalog, { result }));
  assert.match(html, /复杂 Schema · 当前扩展不支持/);
  assert.match(html, /发现不等于测试或启用/);
  assert.match(html, /annotations 不授予操作权限/);
  assert.match(html, /&lt;img/);
  assert.match(html, /anyOf/);
  assert.match(html, /目录 SHA256/);
  assert.doesNotMatch(html, /<img|<button|>启用|>测试|>调用/);
});

test('unread registry differs from a successful empty registry and accepts no URL input', () => {
  const html = renderToStaticMarkup(React.createElement(AssistantToolDiscovery));
  assert.match(html, /登记表尚未读到/);
  assert.doesNotMatch(html, /尚无可读取目录|type="url"|endpoint|tools\/call/);
});
