import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {webcrypto,randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';
const source=await readFile('../web/copilot-upload.js','utf8').catch(e=>{if(e.code==='ENOENT')return '';throw e;});
const thread={id:'original-thread',context_sha256:'scope'},caps={max_file_bytes:65536,max_chunked_file_bytes:2097152,chunked_upload_available:true},bytes=new Uint8Array(150000).fill(97);
function uploader(api,options={}){const sandbox={crypto:{subtle:webcrypto.subtle,randomUUID},btoa:text=>Buffer.from(text,'binary').toString('base64')};vm.runInNewContext(source,sandbox);assert.equal(typeof sandbox.CommerceMaterialUpload?.create,'function','selected-file upload must support a bounded shared chunk protocol');return sandbox.CommerceMaterialUpload.create({api,...options});}
const selected={filename:'local.txt',mime_type:'text/plain',bytes};
test('large file is preflighted, hashed and transmitted in bounded original-scope chunks without model calls',async()=>{
  const calls=[],progress=[],item={id:'material',sha256:'sha'};const u=uploader(async(name,args)=>{calls.push({name,args});if(name.endsWith('preflight'))return {allowed:true};if(name.endsWith('upload_begin'))return {id:'upload',status:'uploading',chunk_bytes:49152,next_index:0};if(name.endsWith('upload_chunk'))return {received_bytes:Math.min((args.index+1)*49152,bytes.length)};if(name.endsWith('upload_finish'))return item;throw Error(name);},{onProgress:value=>progress.push(value)});
  assert.equal(await u.upload({thread,selected,caps}),item);assert.equal(calls.filter(c=>c.name.endsWith('upload_chunk')).length,4);assert.ok(calls.filter(c=>c.name.endsWith('upload_chunk')).every(c=>c.args.thread_id===thread.id&&c.args.content_base64.length<=65536));assert.match(calls.find(c=>c.name.endsWith('upload_begin')).args.content_sha256,/^[a-f0-9]{64}$/);assert.equal(progress.at(-1).status,'completed');assert.ok(calls.every(c=>c.name.startsWith('commerce_copilot_material_')));
});
test('explicit retry reuses one idempotency key and resumes at confirmed byte cursor',async()=>{
  const keys=[],indexes=[];let failed=false;const u=uploader(async(name,args)=>{if(name.endsWith('preflight'))return {allowed:true};if(name.endsWith('upload_begin')){keys.push(args.idempotency_key);return {id:'same',status:'uploading',chunk_bytes:49152,next_index:failed?1:0};}if(name.endsWith('upload_chunk')){indexes.push(args.index);if(args.index===1&&!failed){failed=true;throw Error('offline');}return {};}if(name.endsWith('upload_finish'))return {id:'same-material'};throw Error(name);});
  await assert.rejects(u.upload({thread,selected,caps}),/offline/);assert.equal((await u.upload({thread,selected,caps})).id,'same-material');assert.equal(keys[0],keys[1]);assert.deepEqual(indexes,[0,1,1,2,3]);
});
test('cancel and page detach never finish or send a partly uploaded selection',async()=>{
  const calls=[];let u;u=uploader(async(name,args)=>{calls.push(name);if(name.endsWith('preflight'))return {allowed:true};if(name.endsWith('upload_begin'))return {id:'same',status:'uploading',chunk_bytes:49152,next_index:0};if(name.endsWith('upload_chunk')){await u.cancel();return {};}if(name.endsWith('upload_cancel'))return {status:'cancelled'};throw Error(name);});
  await assert.rejects(u.upload({thread,selected,caps}),/upload_cancelled/);assert.ok(!calls.some(c=>c.endsWith('upload_finish')));assert.equal(calls.filter(c=>c.endsWith('upload_cancel')).length,1);
  let current=true;const detached=uploader(async name=>{if(name.endsWith('preflight'))return {allowed:true};if(name.endsWith('upload_begin')){current=false;return {id:'same',status:'uploading',chunk_bytes:49152,next_index:0};}assert.fail('No data write after detach');},{shouldContinue:()=>current});await assert.rejects(detached.upload({thread,selected,caps}),/scope_changed/);
});
test('old services keep the original single request and reject larger files before a write',async()=>{
  const calls=[];const u=uploader(async name=>{calls.push(name);return {id:'old-material'};});assert.equal((await u.upload({thread,selected:{...selected,bytes:bytes.slice(0,4)},caps:{max_file_bytes:65536}})).id,'old-material');assert.deepEqual(calls,['commerce_copilot_material_upload']);await assert.rejects(u.upload({thread,selected,caps:{max_file_bytes:65536}}),/size/);assert.equal(calls.length,1);
});
test('expired intake can be explicitly restarted and uncertain cancellation remains retryable',async()=>{
  let n=0;const keys=[];const u=uploader(async(name,args)=>{if(name.endsWith('preflight'))return {allowed:true};if(name.endsWith('upload_begin')){keys.push(args.idempotency_key);if(n++===0)throw Error('copilot_upload_expired');return {id:'new',status:'completed',chunk_bytes:49152,next_index:4};}if(name.endsWith('upload_finish'))return {id:'resolved'};throw Error(name);});await assert.rejects(u.upload({thread,selected,caps}),/expired/);assert.equal((await u.upload({thread,selected,caps})).id,'resolved');assert.notEqual(keys[0],keys[1]);
  let cancels=0,stopped=false;const progress=[];let v;v=uploader(async name=>{if(name.endsWith('preflight'))return {allowed:true};if(name.endsWith('upload_begin'))return {id:'original',status:'uploading',chunk_bytes:49152,next_index:0};if(name.endsWith('upload_chunk')){try{await v.cancel()}catch{}return {};}if(name.endsWith('upload_cancel')){if(!cancels++)throw Error('offline');stopped=true;return {status:'cancelled'};}throw Error(name);},{onProgress:p=>progress.push(p)});await assert.rejects(v.upload({thread,selected,caps}));assert.equal(progress.at(-1).cancellable,true);await v.cancel();assert.equal(stopped,true);
});
test('a late chunk refusal after confirmed cancellation remains a cancelled result',async()=>{
  let u;u=uploader(async name=>{if(name.endsWith('preflight'))return {allowed:true};if(name.endsWith('upload_begin'))return {id:'same',status:'uploading',chunk_bytes:49152,next_index:0};if(name.endsWith('upload_chunk')){await u.cancel();throw Error('copilot_upload_not_active');}if(name.endsWith('upload_cancel'))return {status:'cancelled'};throw Error(name);});await assert.rejects(u.upload({thread,selected,caps}),/copilot_upload_cancelled/);
});
