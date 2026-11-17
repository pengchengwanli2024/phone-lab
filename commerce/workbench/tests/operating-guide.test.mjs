import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {existsSync} from 'node:fs';
let matches,destination,key,missingText,listingMissing;
if(existsSync('src/operating-guide-state.ts')){
  const compiled=await build({entryPoints:['src/operating-guide-state.ts'],bundle:true,write:false,format:'esm',platform:'node'});
  ({pipelineMatches:matches,pipelineDestination:destination,pipelineKey:key,pipelineMissingText:missingText,pipelineListingMissing:listingMissing}=await import('data:text/javascript;base64,'+Buffer.from(compiled.outputFiles[0].text).toString('base64')));
}
const target={case_id:'case-a',platform:'ozon',store_ref:'synthetic-store',market:'RU'};
const snapshot={schema:'commerce-operating-pipeline-v1',target,goal:'launch',snapshot_sha256:'a'.repeat(64),product_source_sha256:'b'.repeat(64),stages:[],business_outcome_verified:false,external_execution_allowed:false};
test('operating guidance rejects a different product, store, market, goal or execution authority',()=>{
  assert.equal(typeof matches,'function','read-only guidance needs a scope-bound projection');
  assert.equal(matches(snapshot,target,'launch'),true);
  for(const field of Object.keys(target))assert.equal(matches({...snapshot,target:{...target,[field]:'other'}},target,'launch'),false);
  for(const change of [{goal:'operate'},{external_execution_allowed:true},{business_outcome_verified:true},{schema:'other'},{snapshot_sha256:'old'},{stages:null}])assert.equal(matches({...snapshot,...change},target,'launch'),false);
});
test('only known original destinations are offered; suggested tools cannot become executable UI',()=>{
  assert.equal(typeof destination,'function');
  assert.deepEqual(destination('research'),{kind:'product',section:'research',label:'核对市场研究'});
  assert.deepEqual(destination('images'),{kind:'product',section:'media',label:'核对图片与视频'});
  assert.deepEqual(destination('listing'),{kind:'listing',section:'listing-release',label:'核对申请与回执'});
  assert.equal(destination('commerce_listing_submission_submit'),null);assert.equal(destination('__proto__'),null);
  for(const id of ['growth','service','procurement','logistics','settlement','brand'])assert.equal(destination(id),null,'an unavailable business adapter must not be represented as handled');
});
test('incomplete targets have no read key and each exact scope has a separate identity',()=>{
  assert.equal(typeof key,'function');assert.equal(key({...target,store_ref:''},'launch'),null);assert.equal(key({...target,market:''},'launch'),null);
  assert.notEqual(key(target,'launch'),key(target,'operate'));assert.notEqual(key(target,'launch'),key({...target,store_ref:'second'},'launch'));
});
test('guidance must bind the original saved listing preview or revision, including legacy response refusal',()=>{
  const bound={...snapshot,listing_preview_sha256:'c'.repeat(64),listing_revision:4};
  assert.equal(matches(bound,target,'launch',{preview:'d'.repeat(64)}),false);
  assert.equal(matches(bound,target,'launch',{preview:'c'.repeat(64)}),true);
  assert.equal(matches(bound,target,'launch',{revision:5}),false);assert.equal(matches(bound,target,'launch',{revision:4}),true);
  assert.equal(matches(snapshot,target,'launch',{preview:'c'.repeat(64)}),false);
  assert.deepEqual(destination('policy'),{kind:'listing',section:'listing-rules_ref',label:'核对发布依据'});
});
test('legacy role artifact IDs use their original stage name without rewriting ordinary evidence warnings',()=>{
  assert.equal(typeof missingText,'function');
  assert.equal(missingText('主图、细节、多视角与场景图','缺少 images 岗位产物'),'主图、细节、多视角与场景图的工作产物待补齐');
  const warning='缺采购成本、交期、供应商、来源或明确币种';assert.equal(missingText('多货源比较与实物事实',warning),warning);
});
test('unknown release and incomplete history reasons remain visible; only original checks provide gap actions',()=>{
  assert.equal(typeof listingMissing,'function');
  const labels={content:'SKU、标题、描述与类目资料'};
  assert.deepEqual(listingMissing('content',labels),{label:labels.content,checkId:'content'});
  for(const warning of ['同目标历史申请仍有未决结果；先核对原申请，不能用新草稿覆盖或重发','目标申请历史超过200条，本轮未完整核查；不得推断没有更早未决申请'])assert.deepEqual(listingMissing(warning,labels),{label:warning});
  for(const id of ['future_check','__proto__','constructor'])assert.deepEqual(listingMissing(id,labels),{label:'发布检查项待核对，请查看发布前检查。'});
});
