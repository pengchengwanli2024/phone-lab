import test from 'node:test';
import assert from 'node:assert/strict';
import {packDocument,inlineLegacy} from '../embed.mjs';
import {embeddedDocument} from '../src/embedded-document.ts';

test('compressed offline document preserves UTF-8, script text and independent nested bridge tokens',async()=>{
 const html=inlineLegacy('<html><style>/* INLINE_STYLE */</style><script>/* INLINE_APP */</script></html>',':root{color:blue}',"const text='中文 $&';const nonce='__COMMERCE_BRIDGE_NONCE__';const boot='__COMMERCE_BOOTSTRAP__';");
 const packed=packDocument(html),decoded=await embeddedDocument(packed);
 assert.equal(decoded,html);
 assert.ok(decoded.includes("text='中文 $&'"));
 assert.ok(decoded.includes("nonce='__COMMERCE_NESTED_NONCE__'"));
 assert.ok(decoded.includes("boot='__COMMERCE_NESTED_BOOTSTRAP__'"));
 const first=embeddedDocument(packed);assert.equal(first,embeddedDocument(packed));
});
test('corrupt compressed documents reject and leave retry possible',async()=>{
 const first=embeddedDocument('invalid-gzip');await assert.rejects(first);
 const retry=embeddedDocument('invalid-gzip');assert.notEqual(retry,first);await assert.rejects(retry);
});
test('an unsupported decompression runtime fails explicitly without loading external scripts',async()=>{
 const native=globalThis.DecompressionStream;globalThis.DecompressionStream=undefined;
 try{await assert.rejects(embeddedDocument(packDocument('<p>unsupported-runtime</p>')),/embedded_document_unsupported/);}
 finally{globalThis.DecompressionStream=native;}
});
test('inert inline data decodes independently from the executable application bundle',async()=>{
 const original=globalThis.document,html='<p>尾部商品页 · $&</p>';
 globalThis.document={readyState:'complete',getElementById:id=>id==='commerce-embedded-reference-test'?{textContent:packDocument(html)}:null};
 try{assert.equal(await embeddedDocument('inline:reference-test'),html);}
 finally{if(original===undefined)delete globalThis.document;else globalThis.document=original;}
});
test('a document request waits for the parser to receive its trailing inline data',async()=>{
 const original=globalThis.document,html='<p>晚到的内联资料</p>';let received=false,parsed;
 globalThis.document={readyState:'loading',getElementById:()=>received?{textContent:packDocument(html)}:null,addEventListener:(_event,callback)=>{parsed=callback;}};
 try{
  const pending=embeddedDocument('inline:parser-test');let settled=false;pending.then(()=>{settled=true;},()=>{settled=true;});
  await Promise.resolve();assert.equal(settled,false);
  received=true;globalThis.document.readyState='interactive';parsed();assert.equal(await pending,html);
 }finally{if(original===undefined)delete globalThis.document;else globalThis.document=original;}
});
test('a visible data element is not decoded until its streamed content is complete',async()=>{
 const original=globalThis.document,packed=packDocument('<p>完整文档</p>');let received=false,parsed;
 globalThis.document={readyState:'loading',getElementById:()=>({textContent:received?packed:packed.slice(0,10)}),addEventListener:(_event,callback)=>{parsed=callback;}};
 try{
  const pending=embeddedDocument('inline:partial-parser-test');assert.equal(typeof parsed,'function');
  received=true;globalThis.document.readyState='interactive';parsed();assert.equal(await pending,'<p>完整文档</p>');
 }finally{if(original===undefined)delete globalThis.document;else globalThis.document=original;}
});
