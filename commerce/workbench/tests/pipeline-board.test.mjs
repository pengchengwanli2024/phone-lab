import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['src/pipeline-board-state.ts'],bundle:true,format:'cjs',write:false,platform:'node'});
const module={exports:{}};new Function('module','exports',bundle.outputFiles[0].text)(module,module.exports);
const {arrangeBoard,placeProduct,pipelineRequests}=module.exports;
const product=(id,extra={})=>({id,name:id,kind:'inventory',synthetic:false,sku:id,case_ids:[id+'-a'],primary_case_id:id+'-a',platform:'ozon',market:'RU',...extra});
const target=case_id=>({case_id,platform:'ozon',store_ref:'ozon-live',market:'RU'});
const directory=(entries,complete=true)=>({targets:new Map(entries.map(id=>[id,[target(id)]])),complete});
const ready=(next,unresolved=false)=>({state:'ready',target:target('x'),others:0,summary:{total:7,prepared:next?2:7,next,unresolved}});

test('one card per product; fulfillment scopes of the same product are merged, not repeated',()=>{
  const items=[product('syn0004',{case_ids:['c1','c2','c3'],primary_case_id:'c1'}),product('syn0005')];
  const board=arrangeBoard(items,directory([]),{},false);
  assert.equal(board.total,2);assert.equal(board.merged,2);
  assert.equal(board.columns.flatMap(c=>c.cards).length,2);
  assert.equal(board.columns[0].column.id,'unplanned');
});
test('the card sits in the stage that holds it and shows that one blocker',()=>{
  const p=product('syn0005',{case_ids:['old','planned']});
  const card=placeProduct(p,directory(['planned']),{planned:ready({id:'sourcing',name:'多货源比较与实物事实',status:'needs_evidence',label:'待补依据',missing:'缺少 supply 岗位产物'})});
  assert.equal(card.column,'sourcing');assert.equal(card.caseId,'planned');
  assert.equal(card.blocker,'多货源比较与实物事实的工作产物待补齐');
  assert.deepEqual(card.step,{kind:'product',section:'overview',label:'核对货源与实物资料'});
});
test('candidates, unread stages and over-limit reads are never shown as progress',()=>{
  assert.equal(placeProduct(product('c',{kind:'candidate'}),directory([]),{}).column,'candidate');
  assert.equal(placeProduct(product('a'),null,{}).column,'unread');
  assert.equal(placeProduct(product('a'),directory(['a-a']),{'a-a':{state:'failed'}}).column,'unread');
  assert.match(placeProduct(product('a'),directory(['a-a']),{}).note,/上限/);
  assert.match(placeProduct(product('a'),directory([],false),{}).note,/未读全/);
});
test('all stages prepared is a review state, not a release',()=>{
  const card=placeProduct(product('a'),directory(['a-a']),{'a-a':ready(null,true)});
  assert.equal(card.column,'prepared');assert.match(card.note,/回执/);assert.equal(card.step.kind,'listing');
});
test('synthetic and live products never mix, search narrows, stage reads are bounded',()=>{
  const items=[product('live'),product('demo',{synthetic:true}),product('other')];
  assert.equal(arrangeBoard(items,directory([]),{},true).total,1);
  assert.equal(arrangeBoard(items,directory([]),{},false,'oth').total,1);
  const dir=directory(['live-a','demo-a','other-a']);
  assert.deepEqual(pipelineRequests(items,dir,false,1),['live-a']);
  assert.deepEqual(pipelineRequests(items,dir,false,9),['live-a','other-a']);
});
