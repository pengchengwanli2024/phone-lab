import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {transform} from 'esbuild';

// Execute the actual component and its event closures with isolated hook state.
// This covers local state/row binding; it does not claim browser rendering acceptance.
const source=(await readFile(new URL('../src/order-imports.tsx',import.meta.url),'utf8')).replace(/^import .*?;\n/gm,'').replace(/^import '\.\/adoption\.css';\n/m,'');
const compiled=(await transform(source,{loader:'tsx',format:'cjs',jsx:'transform',jsxFactory:'element'})).code;
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
const text=node=>node==null?'':Array.isArray(node)?node.map(text).join(''):typeof node==='object'?text(node.props?.children):String(node);
function nodes(node,predicate){if(node==null||typeof node!=='object')return [];if(Array.isArray(node))return node.flatMap(child=>nodes(child,predicate));return [...(predicate(node)?[node]:[]),...nodes(node.props?.children,predicate)];}
function harness(){
  const hooks=[],effects=[],calls=[],handed=[];let cursor=0,tree,props={demo:true,navigate(){},onSupport:async value=>handed.push(value)},pendingSupport=null;
  const rows=(count,prefix)=>Array.from({length:count},(_,i)=>({id:`${prefix}-${i+1}:1`,order_id:`${prefix}-${i+1}`,line_id:'1',sku:`${prefix}-SKU-${i+1}`,quantity:1,unit_price:'10',currency:'CNY',source_sha256:(i+1).toString(16).padStart(64,'0')}));
  const orders={large:rows(51,'L'),small:rows(3,'S'),empty:[]};
  const batches=Object.fromEntries(Object.entries(orders).map(([id,items])=>[id,{id,sha256:`batch-sha-${id}`,filename:`${id}.csv`,status:'confirmed',synthetic:true,scope:{platform:'ozon',store_ref:`store-${id}`,market:'RU'},row_count:items.length,valid_count:items.length,accepted_count:items.length,duplicate_count:0,quarantined_count:0,preview_truncated:items.length>50,preview:[],quarantined:[],sales_by_currency:[]} ]));
  const context={module:{exports:{}},exports:{},React:{Fragment:'fragment'},element:(type,props,...children)=>({type,props:{...props,children}}),
    Button:'button',Panel:'section',Empty:'empty',ErrorNotice:'error',
    useState:initial=>{const index=cursor++;if(!(index in hooks))hooks[index]=typeof initial==='function'?initial():initial;return [hooks[index],value=>{hooks[index]=typeof value==='function'?value(hooks[index]):value;}];},
    useRef:initial=>{const index=cursor++;if(!(index in hooks))hooks[index]={current:initial};return hooks[index];},
    useEffect:(callback,deps)=>{const index=cursor++,old=hooks[index];if(!old||deps.some((value,i)=>value!==old.deps[i])){old?.cleanup?.();hooks[index]={deps};effects.push(()=>{hooks[index].cleanup=callback();});}},
    errorText:error=>error.message,requestKey:()=> 'qa-key',
    api:async(name,args)=>{calls.push({name,args:structuredClone(args)});if(name==='commerce_order_import_list')return {items:args.synthetic?Object.values(batches):[]};if(name==='commerce_order_import_get')return batches[args.batch_id];if(name==='commerce_order_import_preview')return {...batches.large,status:'preview',preview:orders.large.slice(0,50).map((record,index)=>({row:index+2,record}))};if(name==='commerce_order_import_confirm')return batches[args.batch_id];if(name==='commerce_orders_list')return {orders:orders[args.import_batch_id]};if(name==='commerce_order_support_prepare'){if(pendingSupport)return pendingSupport.promise;return {context:{order:{id:args.order_id}},external_execution_allowed:false};}throw Error(name);},
  };
  context.exports=context.module.exports;vm.runInNewContext(compiled,context);
  function render(next={}){props={...props,...next};cursor=0;tree=context.module.exports.OrderImports(props);while(effects.length)effects.shift()();return tree;}
  const button=label=>{const item=nodes(tree,n=>n.type==='button'&&text(n).includes(label))[0];assert.ok(item,`Button ${label} exists`);return item;};
  async function click(label){const b=button(label);assert.ok(!b.props.disabled,`Button ${label} enabled`);await b.props.onClick();await flush();render();}
  return {render,click,button,calls,handed,batches,orders,get tree(){return tree;},setPendingSupport:value=>pendingSupport=value};
}

test('the 51st imported order is reachable and support retains its exact batch, scope and source hash',async()=>{
  const h=harness();h.render();await flush();h.render();await h.click('large.csv');
  assert.match(text(h.tree),/1–50 \/ 51 条已保存记录/);assert.equal(nodes(h.tree,n=>n.type==='tr').length,51);
  await h.click('下一页订单');assert.match(text(h.tree),/51–51 \/ 51 条已保存记录/);assert.match(text(h.tree),/L-51/);assert.doesNotMatch(text(h.tree),/L-50/);
  await h.click('起草此订单回复');
  const request=h.calls.find(call=>call.name==='commerce_order_support_prepare');
  assert.deepEqual(request.args,{demo:true,platform:'ozon',store_id:'store-large',market:'RU',order_id:'L-51:1',expected_source_sha256:h.orders.large[50].source_sha256,import_batch_id:'large'});
  assert.equal(h.handed[0].context.order.id,'L-51:1');
  await h.click('上一页订单');assert.match(text(h.tree),/1–50 \/ 51 条已保存记录/);
});

test('new batches and data modes reset pagination and empty batches expose no invalid page',async()=>{
  const h=harness();h.render();await flush();h.render();await h.click('large.csv');await h.click('下一页订单');
  await h.click('small.csv');assert.match(text(h.tree),/1–3 \/ 3 条已保存记录/);assert.equal(h.button('上一页订单').props.disabled,true);assert.equal(h.button('下一页订单').props.disabled,true);
  await h.click('empty.csv');assert.match(text(h.tree),/0–0 \/ 0 条已保存记录/);assert.equal(h.button('下一页订单').props.disabled,true);
  await h.click('large.csv');await h.click('下一页订单');h.render({demo:false});await flush();h.render();assert.doesNotMatch(text(h.tree),/L-51|已保存记录/);assert.match(text(h.tree),/当前范围尚无导入记录/);
});

test('support handoff locks pagination and retains the existing editor recovery entry on rejection',async()=>{
  const h=harness();h.render();await flush();h.render();await h.click('large.csv');await h.click('下一页订单');
  const pending=deferred();h.setPendingSupport(pending);const request=h.button('起草此订单回复').props.onClick();await flush();h.render();
  assert.equal(h.button('上一页订单').props.disabled,true);assert.equal(h.button('下一页订单').props.disabled,true);
  pending.resolve({context:{order:{id:'L-51:1'}},external_execution_allowed:false});await request;await flush();h.render();assert.equal(h.button('上一页订单').props.disabled,false);
  h.setPendingSupport(null);h.render({onSupport:async()=>{throw Error('order_support_editor_open');}});await h.click('起草此订单回复');
  assert.ok(h.button('回到当前编辑'));assert.match(text(h.tree),/51–51 \/ 51 条已保存记录/);
});

test('a new preview and confirmation return to the first page without changing the batch confirmation guard',async()=>{
  const h=harness();h.render();await flush();h.render();await h.click('large.csv');await h.click('下一页订单');
  await h.click('填入合成示例');assert.doesNotMatch(text(h.tree),/51–51/);
  await h.click('预览导入');assert.match(text(h.tree),/确认后可翻页查看全部已保存订单/);assert.equal(h.button('确认本机导入').props.disabled,true);
  const check=nodes(h.tree,node=>node.type==='input'&&node.props.type==='checkbox')[0];check.props.onChange({target:{checked:true}});h.render();await h.click('确认本机导入');
  assert.match(text(h.tree),/1–50 \/ 51 条已保存记录/);assert.equal(h.button('上一页订单').props.disabled,true);
  const confirmation=h.calls.find(call=>call.name==='commerce_order_import_confirm');assert.deepEqual(confirmation.args,{batch_id:'large',expected_sha256:'batch-sha-large',confirmed:true,idempotency_key:'qa-key'});
});
