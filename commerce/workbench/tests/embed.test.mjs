import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { inlineLegacy, inlineDocuments, packDocument } from '../embed.mjs';
import { gunzipSync } from 'node:zlib';
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
test('inert documents follow the application, round trip script text and do not accumulate across builds',()=>{
  const html='<body><script>/* INLINE_APP */</script></body>',document='<p>中文</p><script>nested()</script>';
  const packed=packDocument(document),result=inlineDocuments(html,{legacy:packed});
  assert.ok(result.indexOf('/* INLINE_APP */')<result.indexOf('id="commerce-embedded-legacy"'));
  const payload=result.match(/type="application\/octet-stream">([^<]+)<\/script>/)[1];
  assert.equal(gunzipSync(Buffer.from(payload,'base64')).toString(),document);
  assert.equal(inlineDocuments(result,{legacy:packed}),result);
  assert.equal((result.match(/COMMERCE_EMBEDDED_DOCUMENTS_START/g)||[]).length,1);
  assert.throws(()=>inlineDocuments(html,{legacy:'</script><script>alert(1)</script>'}),/embedded_payload_invalid/);
});
