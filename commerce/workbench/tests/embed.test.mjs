import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { inlineLegacy } from '../embed.mjs';
test('actual product template keeps bootstrap and inner bridge independent from Harness replacement', async () => {
  const template = await readFile('../web/product-workspace.html', 'utf8');
  const script = "const sample = '$& $`'; const nonce='__COMMERCE_BRIDGE_NONCE__';";
  const inner = inlineLegacy(template, '.test{}', script);
  const outer = JSON.stringify(inner).replaceAll('__COMMERCE_BRIDGE_NONCE__', 'outer-only');
  const restored = JSON.parse(outer).replaceAll('__COMMERCE_NESTED_NONCE__', 'inner-only').replace('__COMMERCE_NESTED_BOOTSTRAP__', () => '{"case_id":"synthetic-case"}');
  assert.ok(restored.includes("const sample = '$& $`'"));
  assert.ok(restored.includes("nonce='inner-only'"));
  assert.ok(restored.includes('{"case_id":"synthetic-case"}'));
  assert.ok(!restored.includes('outer-only'));
});
