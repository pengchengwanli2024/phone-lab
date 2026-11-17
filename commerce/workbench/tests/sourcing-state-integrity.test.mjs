import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';

const source=fs.readFileSync(new URL('../../web/sourcing-ui.js',import.meta.url),'utf8');
const receipt={id:'SYN-receipt',case_id:'SYN-case',platform:'yiwugo',request_url:'https://en.yiwugo.com/product/detail/1.html',status:'preview_ready',reason:'SYN ready',draft:{label:'SYN product'},product:{title:'SYN product',images:[],offers:[]}};
function fixture(override=()=>undefined){
  const calls=[],dirty=[];let repaints=0;
  const window={CommerceUI:{escape:v=>String(v??''),button:({label})=>`<button>${label}</button>`,field:(label,content)=>label+content,input:args=>`<input value="${args.value}">`,select:args=>`<select value="${args.value}"></select>`,table:(_header,rows)=>rows.join('')}};
  vm.runInNewContext(source,{window,crypto:{randomUUID}});
  const c=window.CommerceSourcing({repaint(){repaints++;},onDirty:value=>dirty.push(value),api:async(tool,args)=>{
    calls.push({tool,args:structuredClone(args)});const custom=await override(tool,args,calls);if(custom!==undefined)return custom;
    if(tool.endsWith('_channels'))return {items:[{id:'yiwugo',label:'义乌购',search_supported:true,public_preview_supported:true},{id:'jd',label:'京东',search_supported:true,public_preview_supported:true}]};
    if(tool.endsWith('_preview'))return structuredClone(receipt);
    return {items:[]};
  }});
  return {c,calls,dirty,input:(key,value)=>c.input({dataset:{peSourcing:key},value}),get repaints(){return repaints;}};
}
function pendingFile(f,name='SYN-export.json'){
  let resolve,reject;
  const pending=f.c.input({dataset:{peSourcing:'file'},files:[{name,size:100,text:()=>new Promise((yes,no)=>{resolve=yes;reject=no;})}]});
  return {pending,resolve,reject};
}

test('known preview survives history failure without becoming an unknown operation or changing its retry key',async()=>{
  let history=0;
  const f=fixture(tool=>{if(tool.endsWith('_history')&&++history===2)throw Error('SYN history failure');});
  await f.c.enter('SYN-case');await f.input('url',receipt.request_url);
  await f.c.action('preview-public');
  assert.match(f.c.view(),/SYN product/);
  assert.match(f.c.view(),/回执列表读取失败/);
  assert.doesNotMatch(f.c.view(),/尚未确认处理结果/);
  await f.c.action('preview-public');
  const previews=f.calls.filter(call=>call.tool.endsWith('_preview'));
  assert.equal(previews.length,2);
  assert.equal(previews[0].args.idempotency_key,previews[1].args.idempotency_key);
});

test('an unknown preview retains its request key through history refresh',async()=>{
  let previews=0;
  const f=fixture(tool=>{if(tool.endsWith('_preview')&&++previews===1)throw Error('SYN response lost');if(tool.endsWith('_history'))return {items:[structuredClone(receipt)]};});
  await f.c.enter('SYN-case');await f.input('url',receipt.request_url);
  await f.c.action('preview-public');assert.match(f.c.view(),/尚未确认处理结果/);
  await f.c.action('refresh');await f.c.action('preview-public');
  const requests=f.calls.filter(call=>call.tool.endsWith('_preview'));
  assert.equal(requests[0].args.idempotency_key,requests[1].args.idempotency_key);
});

test('clearing either input entry point invalidates a pending file read',async()=>{
  for(const clear of [c=>c.action('discard'),c=>c.discard()]){
    const f=fixture();await f.c.enter('SYN-case');
    const file=pendingFile(f);await clear(f.c);
    const painted=f.repaints;
    file.resolve('{"title":"SYN abandoned import"}');await file.pending;
    assert.equal(f.c.hasUnsavedChanges(),false);
    assert.doesNotMatch(f.c.view(),/SYN abandoned import/);
    assert.equal(f.repaints,painted);
  }
});

test('the last selected file wins regardless of completion order',async()=>{
  const f=fixture();await f.c.enter('SYN-case');
  const first=pendingFile(f,'SYN-A.json'),second=pendingFile(f,'SYN-B.html');
  second.resolve('SYN chosen B');await second.pending;
  first.resolve('SYN stale A');await first.pending;
  assert.match(f.c.view(),/SYN chosen B/);assert.doesNotMatch(f.c.view(),/SYN stale A/);
  assert.match(f.c.view(),/<select value="html"/);
});

test('manual content edits invalidate pending file completion',async()=>{
  const f=fixture();await f.c.enter('SYN-case');const file=pendingFile(f);
  await f.input('content','SYN manual edit');file.resolve('SYN stale file');await file.pending;
  assert.match(f.c.view(),/SYN manual edit/);assert.doesNotMatch(f.c.view(),/SYN stale file/);
});

test('a stale file rejection does not replace a newer selection with an error',async()=>{
  const f=fixture();await f.c.enter('SYN-case');
  const first=pendingFile(f),second=pendingFile(f);
  second.resolve('SYN selected');await second.pending;
  const painted=f.repaints;first.reject(Error('SYN stale failure'));await first.pending;
  assert.match(f.c.view(),/SYN selected/);assert.doesNotMatch(f.c.view(),/未能读取资料文件/);
  assert.equal(f.repaints,painted);
});

test('case change and disposal invalidate pending file success and failure',async()=>{
  for(const close of [c=>c.enter('SYN-other-case'),c=>c.dispose()]){
    for(const outcome of ['success','failure']){
      const f=fixture();await f.c.enter('SYN-case');const file=pendingFile(f);
      await close(f.c);const painted=f.repaints;
      if(outcome==='success')file.resolve('SYN wrong case');else file.reject(Error('SYN stale failure'));
      await file.pending;
      assert.doesNotMatch(f.c.view(),/SYN wrong case|未能读取资料文件/);
      assert.equal(f.repaints,painted);
    }
  }
});
