import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const window = { matchMedia: () => ({ matches: false, addEventListener() {} }), dispatchEvent() {} };
vm.runInNewContext(await readFile('../ui/kit.js', 'utf8'), { window, document: { documentElement: { dataset: {} } }, CustomEvent: class {} });
const ui = window.CommerceUI;

test('evidence displays provenance and verification separately, escaping all source text', () => {
  const html = ui.evidence({ title: '<img src=x onerror=alert(1)>', quote: '原文 <script>bad()</script>', sourceId: 'source-1', version: 'v2', recordKey: 'row-3', sha256: 'a'.repeat(64), verification: 'imported_unverified' });
  assert.ok(html.includes('导入资料 · 未独立核实'));
  assert.ok(html.includes('source-1') && html.includes('v2') && html.includes('row-3') && html.includes('a'.repeat(64)));
  assert.ok(html.includes('&lt;script&gt;bad()&lt;/script&gt;'));
  assert.ok(!html.includes('<img') && !html.includes('<script'));
  assert.ok(ui.evidence({ verification: 'made-up' }).includes('核实状态未知'));
  assert.ok(ui.evidence({ verification: 'confirmed' }).includes('人工确认 · 未独立核实'));
});

test('field difference distinguishes missing values, zero, false, and text while retaining field IDs', () => {
  const html = ui.fieldDiff({ rows: [{ key: 'price', label: '售价', before: 0, after: null }, { key: 'flag', label: '开关', before: false, after: '<x>' }] });
  assert.ok(html.includes('data-field-id="price"'));
  assert.ok(html.includes('>0</td>') && html.includes('未知'));
  assert.ok(html.includes('>false</td>') && html.includes('&lt;x&gt;'));
  assert.ok(ui.fieldDiff({ rows: [] }).includes('参数一致'));
});

test('receipt never turns queued, incomplete, or unknown outcomes into completion', () => {
  const queued = ui.receipt({ task_id: 'task-1', status: 'queued', outcome: 'pending' });
  assert.ok(queued.includes('排队中') && queued.includes('尚未完成'));
  const unknown = ui.receipt({ task_id: 'task-2', status: 'completed', outcome: 'unknown' });
  assert.ok(unknown.includes('结果待核对') && !unknown.includes('本地处理完成'));
  const completed = ui.receipt({ task_id: 'task-3', status: 'completed', outcome: 'succeeded', result_sha256: 'hash', external_operations_executed: false });
  assert.ok(completed.includes('本地处理完成') && completed.includes('hash') && completed.includes('未执行外部操作'));
  assert.ok(ui.receipt({ task_id: '<svg>', outcome: 'failed' }).includes('&lt;svg&gt;'));
});
