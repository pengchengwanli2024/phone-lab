/** 使用原生 ESM 隔离加载桌面插件，验证权限边界与草稿接续。 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

const context = vm.createContext({ console, Map, Promise, JSON, Error });
const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8');
const modules = {
  '@hermes/plugin-sdk': ['Button','host','PALETTE_AREA','ROUTES_AREA','SIDEBAR_NAV_AREA'],
  react: ['useEffect','useRef','useState'],
  'react/jsx-runtime': ['jsx','jsxs']
};
const loaded = new vm.SourceTextModule(source, { context });
await loaded.link(specifier => new vm.SyntheticModule(modules[specifier], function () {
  for (const name of modules[specifier]) this.setExport(name, name === 'host' ? {} : () => {});
}, { context }));
await loaded.evaluate();
const { createBridge, prepareHtml, validDraft } = loaded.namespace;

/** 建立完全隔离的消息与存储替身。 */
function fixture() {
  const replies=[],calls=[],data=new Map();
  const frame={postMessage:value=>replies.push(value)};
  const bridge=createBridge({getFrame:()=>frame,nonce:'nonce-test',rest:async(path,options)=>{calls.push({path,options});return {shared:true}},storage:{get:async key=>data.get(key),set:async(key,value)=>data.set(key,value)}});
  const message=(extra={},source=frame)=>({source,data:{type:'commerce:call',nonce:'nonce-test',id:'1',tool:'commerce_status',arguments:{},...extra}});
  return {bridge,replies,calls,data,frame,message};
}

test('只接受当前 iframe 与匹配 nonce',async()=>{
  const f=fixture(); await f.bridge.receive(f.message({},{})); await f.bridge.receive(f.message({nonce:'other'}));
  assert.equal(f.calls.length,0); assert.equal(f.replies.length,0);
});
test('拒绝非业务工具与数组参数',async()=>{
  const f=fixture(); for(const tool of ['terminal','commerce_../x','commerce_status\n'])await f.bridge.receive(f.message({tool}));
  await f.bridge.receive(f.message({arguments:[]})); assert.equal(f.calls.length,0);
});
test('有效请求只发送一次，回执绑定原 iframe',async()=>{
  const f=fixture(); await f.bridge.receive(f.message()); assert.equal(f.calls.length,1);
  assert.equal(f.calls[0].path,'/invoke'); assert.equal(f.replies[0].result.shared,true); assert.equal(f.replies[0].nonce,'nonce-test');
});
test('断开后不执行或回复',async()=>{
  const f=fixture(); f.bridge.dispose(); await f.bridge.receive(f.message()); assert.equal(f.calls.length,0);
});
test('草稿写入及回读保留原值',async()=>{
  const f=fixture(),key='commerce-copilot-draft-v1:thread-1';
  await f.bridge.receive(f.message({type:'commerce:copilot-draft',op:'write',key,value:'未发送的输入',expected:''}));
  await f.bridge.receive(f.message({type:'commerce:copilot-draft',op:'read',key}));
  assert.equal(f.replies[1].value,'未发送的输入'); assert.equal(f.calls.length,0);
});
test('旧版本草稿不覆盖新内容',async()=>{
  const f=fixture(),key='commerce-copilot-draft-v1:thread-1';
  await f.bridge.receive(f.message({type:'commerce:copilot-draft',op:'write',key,value:'new',expected:''}));
  await f.bridge.receive(f.message({type:'commerce:copilot-draft',op:'write',key,value:'old',expected:''}));
  assert.equal(f.replies[1].error,'draft_storage_conflict'); assert.equal(f.data.get('draft:'+key),'new');
});
test('同一草稿并发写入串行处理',async()=>{
  const f=fixture(),key='commerce-copilot-draft-v1:thread-1';
  await Promise.all([f.bridge.receive(f.message({type:'commerce:copilot-draft',op:'write',key,value:'a',expected:''})),f.bridge.receive(f.message({type:'commerce:copilot-draft',op:'write',key,value:'b',expected:''}))]);
  assert.equal(f.replies.filter(x=>x.error==='draft_storage_conflict').length,1);
});
test('新对话草稿范围校验',()=>{
  assert.equal(validDraft({op:'read',key:'commerce-copilot-draft-v1:new:{"module":"overview","demo":false}'}),true);
  assert.equal(validDraft({op:'read',key:'commerce-copilot-draft-v1:new:{"module":"../x","demo":false}'}),false);
  assert.equal(validDraft({op:'write',key:'commerce-copilot-draft-v1:x',value:'x'.repeat(2001),expected:''}),false);
});
test('HTML 使用随机桥接并禁止外连、顶层导航和同源权限',()=>{
  const html=prepareHtml('<html><head></head><body>__COMMERCE_BRIDGE_NONCE__</body></html>','unique');
  assert.ok(html.includes("connect-src 'none'")); assert.ok(html.includes('unique')); assert.ok(!html.includes('__COMMERCE_BRIDGE_NONCE__'));
  assert.ok(!source.includes('allow-same-origin')); assert.ok(!source.includes('allow-top-navigation'));
});
test('已确认的冲突与权限拒绝保留原错误码',async()=>{
  for (const code of ['workspace_source_changed','form_draft_conflict','permission_denied']) {
    const replies=[],frame={postMessage:value=>replies.push(value)}; let calls=0;
    const bridge=createBridge({getFrame:()=>frame,nonce:'n',storage:{},rest:async()=>{calls++;return {__commerceBridgeError:code}}});
    await bridge.receive({source:frame,data:{type:'commerce:call',nonce:'n',id:'1',tool:'commerce_status',arguments:{}}});
    assert.equal(calls,1); assert.equal(replies[0].error,code); assert.equal(replies[0].result,undefined);
  }
});
test('传输异常不重试、不回显底层异常',async()=>{
  const replies=[],frame={postMessage:value=>replies.push(value)}; let calls=0;
  const bridge=createBridge({getFrame:()=>frame,nonce:'n',storage:{},rest:async()=>{calls++;throw Error('private-secret')}});
  await bridge.receive({source:frame,data:{type:'commerce:call',nonce:'n',id:'1',tool:'commerce_status',arguments:{}}});
  assert.equal(calls,1); assert.equal(replies[0].error,'request_outcome_unknown');
});
