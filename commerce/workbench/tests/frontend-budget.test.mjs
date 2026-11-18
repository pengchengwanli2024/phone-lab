import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {gzipSync} from 'node:zlib';
import path from 'node:path';

// Guards the first-screen payload measured in .local/coordination/frontend-pipeline-20261118/PERFORMANCE.md.
// These are the built artifacts, so the generated-sync gate keeps the numbers honest.
const web=path.resolve(import.meta.dirname,'../../web'), ui=path.resolve(import.meta.dirname,'../../ui');
const [html,bundle,css,primitives,status,kit,shipping]=await Promise.all([
  readFile(path.join(web,'workbench.html'),'utf8'),readFile(path.join(web,'workbench.bundle.js'),'utf8'),
  readFile(path.join(web,'workbench.bundle.css'),'utf8'),readFile(path.join(ui,'primitives.css'),'utf8'),
  readFile(path.join(ui,'status.js'),'utf8'),readFile(path.join(ui,'kit.js'),'utf8'),readFile(path.join(ui,'shipping-files.js'),'utf8'),
]);
const kib=value=>Math.round(value/1024);
const NEWLINE=String.fromCharCode(10);
// split/join, not replace(): the payloads contain $ sequences that replace() would expand.
const fill=(source,marker,value)=>source.split(marker).join(value);
const served=fill(fill(fill(html,'/* INLINE_STYLE */',primitives+NEWLINE+css),'/* INLINE_KIT */',status+NEWLINE+kit+NEWLINE+shipping),'/* INLINE_APP */',bundle);

test('the executable workbench stays within its payload budget',()=>{
  // 1490 KiB when the budget was set; ~5% headroom so a normal feature does not trip it.
  assert.ok(bundle.length/1024<=1560,kib(bundle.length)+' KiB executable bundle exceeds 1560 KiB');
  assert.ok(!/maplibre|katex/i.test(bundle),'the business artifact carries no map or math renderer');
  assert.equal(bundle.match(/zod.fv4.fv4.[a-z]*locales/g),null,'only the English zod locale is bundled');
});

test('the inline documents are the payload we measured, not more',()=>{
  const documents=[...served.matchAll(/<script id="commerce-embedded-([a-z-]+)" type="application\/octet-stream">([^<]*)<\/script>/g)];
  assert.deepEqual(documents.map(match=>match[1]).sort(),['intel-map','legacy','product']);
  const total=documents.reduce((sum,match)=>sum+match[2].length,0)/1024;
  assert.ok(total<=2900,Math.round(total)+' KiB of inline documents exceeds 2900 KiB');
});

test('the build still packs every document the server hands out on demand',()=>{
  // react_page strips these blocks for browsers and serves them from /workspace/document/<id>;
  // a payload that stops being built would leave that endpoint with nothing to send.
  for(const id of ['legacy','product','intel-map']){
    const block=[...html.matchAll(/<script id="commerce-embedded-([a-z-]+)" type="application\/octet-stream">([^<]*)<\/script>/g)].find(match=>match[1]===id);
    assert.ok(block,'block '+id+' is missing');
    assert.ok(/^[A-Za-z0-9+/]+={0,2}$/.test(block[2]),'block '+id+' is not base64 for the endpoint');
    assert.ok(block[2].length>1024,'block '+id+' is too small to be a document');
  }
});

test('the whole page still transfers within its measured budget',()=>{
  // 2564 KiB gzipped when the budget was set. Growth here is what makes the first screen slow.
  const wire=gzipSync(Buffer.from(served,'utf8'),{level:9}).length;
  assert.ok(wire/1024<=2650,kib(wire)+' KiB gzipped page exceeds 2650 KiB');
});
