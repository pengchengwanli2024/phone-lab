import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {existsSync,readFileSync} from 'node:fs';

function harness(){
  const handlers=new Map(),revoked=[],links=[],timers=[];
  const window={addEventListener:(type,fn)=>handlers.set(type,fn),removeEventListener:(type)=>handlers.delete(type),crypto:{randomUUID:()=>`request-${Math.random()}`}};
  window.parent=window;
  const document={body:{appendChild(link){links.push(link);}},createElement(){const events=new Map();return {click(){this.clicked=true;},remove(){this.removed=true;},addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:name=>events.delete(name),dispatch:name=>events.get(name)?.()};}};
  const source=new URL('../ui/shipping-files.js',import.meta.url),context={window,document,Blob,TextDecoder,TextEncoder,URL:{createObjectURL:()=> 'blob:top-frame-file',revokeObjectURL:url=>revoked.push(url)},setTimeout:(fn,ms)=>{const id=setTimeout(fn,ms);id.unref?.();timers.push(id);return id;},clearTimeout};
  vm.createContext(context);if(existsSync(source))vm.runInContext(readFileSync(source,'utf8'),context);
  assert.ok(window.CommerceShippingFiles,'shared shipping file service is installed');
  return {files:window.CommerceShippingFiles,window,handlers,revoked,links,cleanup:()=>timers.forEach(clearTimeout)};
}
const file={filename:'shipping_synthetic-space.csv',mime_type:'text/csv;charset=utf-8',content:'SKU,quantity\r\n示例,2\r\n'};

test('CSV reader preserves a selected UTF8 BOM file and measures bytes',async()=>{
  const h=harness(),data=new Blob(['\ufeffid,name\r\na,中文\r\n']);data.name='报价.CSV';
  const result=await h.files.readCsv(data,{kind:'rates'});
  assert.equal(result.filename,'报价.CSV');assert.equal(result.bytes,22);assert.match(result.content,/中文/);h.cleanup();
});
test('CSV reader rejects corrupt encoding instead of replacing tariff text',async()=>{
  const h=harness(),data=new Blob([new Uint8Array([0x69,0x64,0x2c,0xc3,0x28])]);data.name='bad.csv';
  await assert.rejects(h.files.readCsv(data,{kind:'rates'}),/UTF-8/);h.cleanup();
});
test('CSV reader rejects unsupported files and exact intake byte overflow',async()=>{
  const h=harness(),wrong=new Blob(['id']);wrong.name='rates.xlsx';await assert.rejects(h.files.readCsv(wrong,{kind:'rates'}),/CSV/);
  const big=new Blob(['x'.repeat(200001)]);big.name='items.csv';await assert.rejects(h.files.readCsv(big,{kind:'items'}),/200/);h.cleanup();
});
test('top frame picker opens immediately and returns only the selected validated CSV',async()=>{
  const h=harness();assert.equal(typeof h.files.pickCsv,'function');
  const pending=h.files.pickCsv({kind:'rates'}),picker=h.links[0];assert.equal(picker.type,'file');assert.equal(picker.clicked,true);
  const selected=new Blob(['id,name\r\na,示例\r\n']);selected.name='local.csv';picker.files=[selected];picker.dispatch('change');
  const result=await pending;assert.equal(result.status,'selected');assert.equal(result.filename,'local.csv');assert.match(result.content,/示例/);assert.equal(picker.removed,true);h.cleanup();
});
test('top frame picker cancellation returns no file and removes the input',async()=>{
  const h=harness();assert.equal(typeof h.files.pickCsv,'function');const pending=h.files.pickCsv({kind:'items'}),picker=h.links[0];picker.dispatch('cancel');
  assert.equal((await pending).status,'cancelled');assert.equal(picker.removed,true);h.cleanup();
});
test('top frame picker refuses a corrupt CSV rather than sending replaced text',async()=>{
  const h=harness();assert.equal(typeof h.files.pickCsv,'function');const pending=h.files.pickCsv({kind:'rates'}),picker=h.links[0],bad=new Blob([new Uint8Array([0xff])]);bad.name='bad.csv';picker.files=[bad];picker.dispatch('change');
  await assert.rejects(pending,/UTF-8/);assert.equal(picker.removed,true);h.cleanup();
});
test('native download keeps host blob alive until the real saved receipt',async()=>{
  const h=harness();let finish,source;
  const pending=h.files.saveFile(file,async value=>{source=value;return new Promise(resolve=>finish=resolve);});
  await Promise.resolve();assert.deepEqual(h.revoked,[]);assert.equal(source.name,file.filename);assert.equal(source.url,'blob:top-frame-file');
  finish({status:'saved',path:'/synthetic/downloads/packing.csv'});const receipt=await pending;
  assert.equal(receipt.status,'saved');assert.equal(receipt.filename,file.filename);assert.deepEqual(h.revoked,['blob:top-frame-file']);h.cleanup();
});
test('browser download attaches a named link and reports only requested',async()=>{
  const h=harness(),receipt=await h.files.saveFile(file);
  assert.equal(receipt.status,'requested');assert.equal(h.links.length,1);assert.equal(h.links[0].download,file.filename);assert.equal(h.links[0].clicked,true);assert.equal(h.links[0].removed,true);assert.deepEqual(h.revoked,[]);h.cleanup();
});
test('cancel and native failure are not turned into saved receipts',async()=>{
  const h=harness();assert.equal((await h.files.saveFile(file,async()=>({status:'cancelled'}))).status,'cancelled');
  await assert.rejects(h.files.saveFile(file,async()=>{throw Error('disk_unavailable');}),/disk_unavailable/);
  await assert.rejects(h.files.saveFile(file,async()=>({status:'saved'})),/receipt/);assert.equal(h.revoked.length,3);h.cleanup();
});
test('file boundary rejects paths, executable extensions, MIME mismatch and nontext payload',async()=>{
  const h=harness();for(const bad of [{...file,filename:'../secret.csv'},{...file,filename:'tool.command'},{...file,mime_type:'application/javascript'},{...file,content:42}])await assert.rejects(h.files.saveFile(bad),/file/);
  assert.equal(h.links.length,0);h.cleanup();
});
test('bridge ignores foreign frames and nonces and binds replies to request ids',async()=>{
  const h=harness(),posted=[],parent={postMessage:message=>posted.push(message)};h.window.parent=parent;
  const client=h.files.createClient({target:h.window,nonce:'same-frame',timeoutMs:1000});const pending=client.request('download',{file});
  assert.equal(posted.length,1);const request=posted[0],receive=h.handlers.get('message');
  receive({source:{},data:{type:'commerce:shipping-file-result',nonce:'same-frame',id:request.id,result:{status:'saved'}}});
  receive({source:parent,data:{type:'commerce:shipping-file-result',nonce:'wrong',id:request.id,result:{status:'saved'}}});
  receive({source:parent,data:{type:'commerce:shipping-file-result',nonce:'same-frame',id:'other',result:{status:'saved'}}});
  receive({source:parent,data:{type:'commerce:shipping-file-result',nonce:'same-frame',id:request.id,result:{status:'requested',filename:file.filename}}});
  assert.equal((await pending).status,'requested');client.dispose();assert.equal(h.handlers.size,0);h.cleanup();
});
test('receiver validates frame and file payload before native side effect',async()=>{
  const h=harness(),source={postMessage:message=>replies.push(message)},replies=[];let saves=0;
  const options={source,nonce:'private',perform:async()=>{saves++;return {status:'requested'};}};
  const event={source,data:{type:'commerce:shipping-file',nonce:'private',id:'req-1',op:'download',args:{file}}};
  assert.equal(await h.files.handleRequest({...event,source:{}},options),false);assert.equal(saves,0);
  await h.files.handleRequest({...event,data:{...event.data,args:{file:{...file,filename:'../unsafe.csv'}}}},options);assert.equal(saves,0);assert.match(replies[0].error,/file/);
  await h.files.handleRequest(event,options);assert.equal(saves,1);assert.equal(replies[1].result.status,'requested');h.cleanup();
});
test('bridge timeout distinguishes file selection from an uncertain download',async()=>{
  const h=harness();h.window.parent={postMessage(){}};
  const client=h.files.createClient({target:h.window,nonce:'timeout',timeoutMs:2});
  const selection=assert.rejects(client.request('pick-csv',{kind:'rates'}),/shipping_file_selection_unknown/);
  const download=assert.rejects(client.request('download',{file}),/request_outcome_unknown/);
  await new Promise(resolve=>setTimeout(resolve,10));await Promise.all([selection,download]);client.dispose();h.cleanup();
});
