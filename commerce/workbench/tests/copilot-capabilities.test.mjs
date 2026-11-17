import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const script=await readFile(new URL('../../web/copilot-capabilities.js',import.meta.url),'utf8'),kit=await readFile(new URL('../../ui/kit.js',import.meta.url),'utf8');
function fixture({checkResponse,catalogResponse,parentComposing=()=>false}={}){
  let scope={module:'overview',demo:true},mode=null,checks=0,fail=false,paints=0;const calls=[];
  const events=new Map();const window={innerWidth:1440,innerHeight:1000,matchMedia:()=>({matches:false,addEventListener(){}}),dispatchEvent(){}},document={getElementById:()=>null,documentElement:{dataset:{}},addEventListener:(type,fn)=>events.set(type,fn),removeEventListener:type=>events.delete(type)};
  vm.runInNewContext(kit,{window,document,CustomEvent:class{}});
  vm.runInNewContext(script,{window,document,setTimeout,clearTimeout});
  const items=[{id:'mcp:commerce',kind:'mcp',name:'共享电商 MCP',description:'范围内读取',status:'available',selectable:true},{id:'skill:sealeap-test',kind:'skill',name:'<img src=x onerror=attack()>',description:'方法',status:'source_registered',selectable:true},{id:'plugin:lovart',kind:'plugin',name:'Lovart',description:'未连接',status:'needs_setup',selectable:false}];
  const helper=window.CommerceCopilotCapabilities({ui:window.CommerceUI,getContext:()=>scope,repaint:()=>{paints++;},isComposing:parentComposing,onModule:value=>{mode=value;scope={module:value||'overview',demo:true}},api:async(tool,args)=>{
    calls.push([tool,args]);if(fail)throw Error('offline');
    if(tool==='commerce_copilot_capabilities'&&catalogResponse)return catalogResponse(args);
    if(tool==='commerce_copilot_capabilities')return {schema:'commerce-copilot-capabilities-v1',modules:[{id:'intelligence',label:'全球情报',description:'已登记模块'}],items,total:3,next_offset:null};
    if(tool==='commerce_copilot_capability_check'){checks++;if(checkResponse)return checkResponse(args);return {available:true,capability_ids:args.capability_ids,selection_sha256:'a'.repeat(64),capabilities:items.filter(item=>args.capability_ids.includes(item.id))}}
    throw Error('unexpected '+tool);
  }});
  const click=(action,data={})=>helper.handleClick({target:{closest:()=>({dataset:{copilotCapabilityAction:action,...data}})},preventDefault(){},stopImmediatePropagation(){}});
  return {helper,click,calls,emit:(type,event)=>events.get(type)?.(event),get paints(){return paints},get mode(){return mode},get checks(){return checks},set fail(value){fail=value}};
}
test('picker uses shared primitives and escapes registry content inside rich rows',async()=>{
  const f=fixture();await f.click('toggle');await f.click('tab',{tab:'skills'});const html=f.helper.view();
  assert.match(html,/role="dialog"/);assert.match(html,/<strong[^>]*>&lt;img/);assert.doesNotMatch(html,/<img src/);assert.doesNotMatch(html,/&lt;span&gt;/);
  f.helper.dispose();
});
test('manual module choice has a reversible automatic-follow choice',async()=>{
  const f=fixture();await f.click('toggle');await f.click('module',{module:'intelligence'});assert.equal(f.mode,'intelligence');
  assert.match(f.helper.view({manualModule:'intelligence'}),/功能与工具/);
  await f.click('module',{module:''});assert.equal(f.mode,null);f.helper.dispose();
});
test('a selected capability carries the exact check receipt into a future send',async()=>{
  const f=fixture();await f.click('toggle');await f.click('select',{capabilityId:'mcp:commerce'});
  const value=await f.helper.prepare();assert.deepEqual(JSON.parse(JSON.stringify(value)),{capability_ids:['mcp:commerce'],expected_capability_sha256:'a'.repeat(64)});
  assert.equal(f.checks,1);await f.click('remove',{capabilityId:'mcp:commerce'});assert.deepEqual(JSON.parse(JSON.stringify(await f.helper.prepare())),{});f.helper.dispose();
});
test('unconfigured plugins cannot be selected and failed checks cannot prepare a send',async()=>{
  const f=fixture();await f.click('toggle');await f.click('select',{capabilityId:'plugin:lovart'});assert.equal(f.checks,0);
  f.fail=true;await f.click('select',{capabilityId:'mcp:commerce'});await assert.rejects(f.helper.prepare(),/核对/);assert.match(f.helper.view(),/条件未确认/);f.helper.dispose();
});
test('reopening a persisted original choice retains its original version receipt',async()=>{
  const f=fixture();f.helper.restore({available:true,capability_ids:['mcp:commerce'],selection_sha256:'b'.repeat(64),capabilities:[]});
  assert.equal((await f.helper.prepare()).expected_capability_sha256,'b'.repeat(64));assert.equal(f.checks,0);f.helper.dispose();
});


test('selection summary stays in the trigger while removable chips live inside the popup',async()=>{
  const f=fixture();await f.click('toggle');await f.click('select',{capabilityId:'mcp:commerce'});await f.click('close');
  const closed=f.helper.view();assert.match(closed,/已选 1/);assert.doesNotMatch(closed,/copilot-capability-chip/);
  await f.click('toggle');assert.match(f.helper.view(),/copilot-capability-chip/);f.helper.dispose();
});
test('changing category clears the previous category query and loads its own results',async()=>{
  const f=fixture();await f.click('toggle');f.helper.handleInput({target:{id:'copilot-capability-query',value:'inventory'}});
  await new Promise(resolve=>setTimeout(resolve,220));await f.click('tab',{tab:'skills'});
  assert.equal(f.calls.filter(([tool])=>tool==='commerce_copilot_capabilities').at(-1)[1].query,'');f.helper.dispose();
});
test('unavailable entries have inspectable details without selecting or invoking them',async()=>{
  const f=fixture();await f.click('toggle');await f.click('tab',{tab:'tools'});await f.click('details',{capabilityId:'plugin:lovart'});
  assert.match(f.helper.view(),/在宿主中连接后可用/);assert.match(f.helper.view(),/Lovart/);assert.equal(f.checks,0);
  assert.deepEqual(JSON.parse(JSON.stringify(await f.helper.prepare())),{});f.helper.dispose();
});
test('clear selection invalidates its old receipt and prepares an empty next send',async()=>{
  const f=fixture();await f.click('toggle');await f.click('select',{capabilityId:'mcp:commerce'});await f.click('clear');
  assert.deepEqual(JSON.parse(JSON.stringify(await f.helper.prepare())),{});assert.match(f.helper.view(),/已选 0/);f.helper.dispose();
});
test('outside dismissal leaves the clicked composer control mounted for its original action',async()=>{
  const f=fixture();await f.click('toggle');const before=f.paints;
  await f.helper.handleClick({target:{closest:()=>null}});assert.equal(f.paints,before);assert.doesNotMatch(f.helper.view(),/role="dialog"/);f.helper.dispose();
});


test('pending read-only checks keep the focused choice usable and wait before preparing a send',async()=>{
  let finish;const f=fixture({checkResponse:args=>new Promise(resolve=>{finish=()=>resolve({available:true,capability_ids:args.capability_ids,selection_sha256:'c'.repeat(64),capabilities:[]})})});
  await f.click('toggle');await f.click('tab',{tab:'tools'});const pending=f.click('select',{capabilityId:'mcp:commerce'});
  const row=f.helper.view().match(/<button[^>]*data-capability-id="mcp:commerce"[^>]*data-capability-choice[^>]*>/)?.[0];
  assert.ok(row);assert.doesNotMatch(row,/disabled/);const prepared=f.helper.prepare();finish();await pending;
  assert.equal((await prepared).expected_capability_sha256,'c'.repeat(64));assert.equal((await f.helper.prepare()).expected_capability_sha256,'c'.repeat(64));f.helper.dispose();
});
test('module search does not put the automatic-follow shortcut before matching choices',async()=>{
  const f=fixture();await f.click('toggle');f.helper.handleInput({target:{id:'copilot-capability-query',value:'全球'}});
  assert.doesNotMatch(f.helper.view(),/<strong>跟随当前页面<\/strong>/);f.helper.dispose();
});


test('rapid selection changes keep only the latest condition receipt when responses arrive out of order',async()=>{
  const replies=[];const f=fixture({checkResponse:args=>new Promise(resolve=>replies.push({args,resolve}))});await f.click('toggle');
  const first=f.click('select',{capabilityId:'mcp:commerce'}),second=f.click('select',{capabilityId:'skill:sealeap-test'});
  replies[1].resolve({available:true,capability_ids:replies[1].args.capability_ids,selection_sha256:'latest',capabilities:[]});await second;
  replies[0].resolve({available:true,capability_ids:replies[0].args.capability_ids,selection_sha256:'older',capabilities:[]});await first;
  const value=await f.helper.prepare();assert.equal(value.expected_capability_sha256,'latest');assert.deepEqual(JSON.parse(JSON.stringify(value.capability_ids)),['mcp:commerce','skill:sealeap-test']);f.helper.dispose();
});


test('an async catalog response waits for Chinese composition before repainting the picker',async()=>{
  let finish;const f=fixture({catalogResponse:()=>new Promise(resolve=>{finish=resolve})});const opened=f.click('toggle');
  f.emit('compositionstart',{target:{id:'copilot-capability-query'}});const before=f.paints;
  finish({schema:'commerce-copilot-capabilities-v1',modules:[],items:[],next_offset:null});await opened;
  assert.equal(f.paints,before);f.emit('compositionend',{target:{id:'copilot-capability-query',value:'库存'}});assert.ok(f.paints>before);f.helper.dispose();
});


test('the parent composition guard also defers a late catalog repaint before local input events',async()=>{
  let finish,composing=false;const f=fixture({parentComposing:()=>composing,catalogResponse:()=>new Promise(resolve=>{finish=resolve})});const opened=f.click('toggle');composing=true;const before=f.paints;
  finish({schema:'commerce-copilot-capabilities-v1',modules:[],items:[],next_offset:null});await opened;assert.equal(f.paints,before);
  composing=false;f.helper.handleInput({target:{id:'copilot-capability-query',value:'库存'}});assert.match(f.helper.view(),/value="库存"/);f.helper.dispose();
});


test('Escape during Chinese composition belongs to the input method and leaves the picker open',async()=>{
  const f=fixture();await f.click('toggle');let prevented=false;
  const handled=f.helper.keydown({key:'Escape',isComposing:true,target:{id:'copilot-capability-query'},preventDefault(){prevented=true}});
  assert.equal(handled,false);assert.equal(prevented,false);assert.match(f.helper.view(),/role="dialog"/);f.helper.dispose();
});
test('dismissing preedit clears its local guard so a later opening can paint normally',async()=>{
  const f=fixture();await f.click('toggle');f.emit('compositionstart',{target:{id:'copilot-capability-query'}});await f.click('close');const before=f.paints;
  await f.click('toggle');assert.ok(f.paints>before);f.helper.dispose();
});
