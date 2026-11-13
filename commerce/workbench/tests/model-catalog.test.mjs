import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const compiled = await build({ entryPoints: ['src/model-catalog.ts'], bundle: true, write: false, format: 'esm', platform: 'node' });
const { modelReadiness } = await import('data:text/javascript;base64,' + Buffer.from(compiled.outputFiles[0].text).toString('base64'));
const profile = { id: 'synthetic-model', label: '合成模型', engine: 'custom', revision: '2', enabled: true, selectable: true, test_status: 'passed', tested_revision: '2' };

test('a test for an older configuration cannot mark the current model enabled', () => {
  const state = modelReadiness({ ...profile, tested_revision: '1', selectable: false });
  assert.equal(state.label, '需重新测试'); assert.notEqual(state.tone, 'success');
});
test('an unknown test outcome remains distinct from a failed test', () => {
  assert.equal(modelReadiness({ ...profile, test_status: 'unknown', selectable: false }).label, '测试结果待核对');
  assert.equal(modelReadiness({ ...profile, test_status: 'failed', selectable: false }).label, '测试未通过');
});
test('a successful connectivity test alone does not mean the profile was enabled', () => {
  assert.equal(modelReadiness({ ...profile, enabled: false, selectable: false }).label, '测试通过 · 未启用');
  assert.equal(modelReadiness(profile).label, '已启用');
});
test('the existing default route is checked at request time rather than claiming a live connection', () => {
  assert.equal(modelReadiness({ ...profile, engine: 'builtin' }).label, '按请求检查');
  assert.equal(modelReadiness({ ...profile, engine: 'builtin', selectable: false, test_status: 'invalid_configuration' }).label, '配置待修复');
});
