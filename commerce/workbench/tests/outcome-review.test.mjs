import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['src/outcome-review-state.ts'],bundle:true,format:'cjs',write:false,platform:'node'});
const module={exports:{}};new Function('module','exports',bundle.outputFiles[0].text)(module,module.exports);
const {closableItems,sourceName,kindName}=module.exports;
const item=(id,kind,extra={})=>({id,kind,source:'agent',source_id:id,title:id,detail:'',...extra});

test('only checked outcomes are offered for closing; questions, proposals and unreconciled submissions are not',()=>{
  const items=[item('a','unknown'),item('b','failed'),item('c','input'),item('d','review'),item('e','unknown',{status:'submission_unknown'}),item('f','failed',{source:'followup'}),item('g','failed',{source:'research'})];
  assert.deepEqual(closableItems(items).map(row=>row.id),['a','b','g']);
});
test('labels use plain words',()=>{
  assert.equal(sourceName('agent'),'模型请求');assert.equal(sourceName('research'),'市场研究');assert.equal(sourceName('x'),'原记录');
  assert.equal(kindName(item('a','unknown')),'结果未知');assert.equal(kindName(item('a','failed')),'未完成');
});
test('the panel can only read the list and close an item; it never retries or resends',async()=>{
  const source=await readFile('src/outcome-review.tsx','utf8');
  assert.deepEqual([...new Set([...source.matchAll(/'(commerce_[a-z_]+)'/g)].map(match=>match[1]))].sort(),['commerce_attention_close','commerce_attention_list']);
  assert.doesNotMatch(source,/retry|resume|idempotency_key/);
  assert.match(source,/也没有重发/);
});
