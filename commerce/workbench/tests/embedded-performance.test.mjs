import test from 'node:test';
import assert from 'node:assert/strict';
import * as embedding from '../embed.mjs';
import {embeddedDocument} from '../src/embedded-document.ts';

test('each embedded block proves completion before a later asset starts arriving',()=>{
  const result=embedding.inlineDocuments('<body><script>/* INLINE_APP */</script></body>',{
    product:embedding.packDocument('<p>product</p>'),legacy:embedding.packDocument('<p>legacy</p>'),
  });
  const productClose=result.indexOf('</script>',result.indexOf('id="commerce-embedded-product"'));
  const complete=result.indexOf('id="commerce-embedded-product-complete"');
  assert.ok(complete>productClose,'the marker must follow the complete data script');
  assert.ok(complete<result.indexOf('id="commerce-embedded-legacy"'),'the marker must precede later data');
});

test('a complete product block decodes while the trailing map and HTML remain incomplete',async()=>{
  const original=globalThis.document;
  const packed=embedding.packDocument('<p>商品已到齐</p>');
  // The claim is about ordering, not speed: decoding must finish while the document is still
  // loading and without ever subscribing to DOMContentLoaded. An 80 ms wall-clock race used to
  // stand in for that and failed on a busy machine, where decompression alone can take longer.
  let waitedForLoad=false;
  globalThis.document={readyState:'loading',getElementById:id=>id==='commerce-embedded-perf-product'?{textContent:packed}:id==='commerce-embedded-perf-product-complete'?{}:null,addEventListener(){waitedForLoad=true;}};
  try{
    let timer;
    const value=await Promise.race([embeddedDocument('inline:perf-product'),new Promise(resolve=>{timer=setTimeout(()=>resolve('never-resolved'),10000);})]);
    clearTimeout(timer);
    assert.equal(value,'<p>商品已到齐</p>');
    assert.equal(globalThis.document.readyState,'loading','the document never finished loading during this test');
    assert.equal(waitedForLoad,false,'a complete block must not wait for DOMContentLoaded');
  }finally{globalThis.document=original;}
});

test('a completion marker arriving after subscription releases only that document',async()=>{
  const originalDocument=globalThis.document,originalObserver=globalThis.MutationObserver;
  const packed=embedding.packDocument('<p>普通业务已到齐</p>');let complete=false,changed,disconnected=false;
  globalThis.document={readyState:'loading',documentElement:{},getElementById:id=>id==='commerce-embedded-perf-legacy'?{textContent:complete?packed:packed.slice(0,12)}:id==='commerce-embedded-perf-legacy-complete'&&complete?{}:null,addEventListener(){},removeEventListener(){}};
  globalThis.MutationObserver=class{constructor(callback){changed=callback;}observe(){}disconnect(){disconnected=true;}};
  try{
    const pending=embeddedDocument('inline:perf-legacy');await Promise.resolve();
    assert.equal(typeof changed,'function','streaming must observe completion without waiting for DOMContentLoaded');
    complete=true;changed();assert.equal(await pending,'<p>普通业务已到齐</p>');assert.equal(disconnected,true);
  }finally{globalThis.document=originalDocument;globalThis.MutationObserver=originalObserver;}
});

test('map extraction removes exactly the generated map while preserving other business source',()=>{
  assert.equal(typeof embedding.separateLegacyMap,'function');
  const map='window.CommerceGeoMap=()=>({active:()=>false});\n';
  const input='before();\n/* COMMERCE_INTEL_START */\n'+map+'\nsocial();\n/* COMMERCE_INTEL_END */\nafter();';
  const result=embedding.separateLegacyMap(input,map,'window.CommerceGeoMap=lazyMap;');
  assert.equal(result,'before();\n/* COMMERCE_INTEL_START */\nwindow.CommerceGeoMap=lazyMap;\nsocial();\n/* COMMERCE_INTEL_END */\nafter();');
  assert.throws(()=>embedding.separateLegacyMap(input.replace(map,map+map),map,'proxy'),/embedded_map_boundary/);
  assert.throws(()=>embedding.separateLegacyMap(input.replace('COMMERCE_INTEL_START','OTHER_START'),map,'proxy'),/embedded_map_boundary/);
});
