import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const window={};vm.runInNewContext(await readFile('../web/copilot-evidence.js','utf8'),{window});
const label=run=>window.CommerceAssistantEvidence.reviewStatus(run);
const run={status:'awaiting_review',result:{proposals:[{id:'P1'},{id:'P2'}]},actions:[]};
const action=(id,outcome,status='completed')=>({proposal_id:id,task_id:'task-'+id,receipt:{outcome,status,result_sha256:'hash'}});
test('completed local receipts replace the old review label without rewriting original status',()=>{
 const value={...run,actions:[action('P1','succeeded'),action('P2','succeeded')]};
 assert.equal(label(value),'本地任务已完成');assert.equal(value.status,'awaiting_review');
});
test('partial approval still waits for the remaining original proposal',()=>{
 assert.equal(label({...run,actions:[action('P1','succeeded')]}),null);
 assert.equal(label({...run,actions:[action('other','succeeded'),action('P1','succeeded')]}),null);
});
test('unknown failed and queued receipts never become completed',()=>{
 for(const [outcome,status,expected]of [['unknown','completed','任务结果待核对'],['failed','failed','本地任务失败'],['pending','queued','本地任务处理中']]){
  assert.equal(label({...run,actions:[action('P1','succeeded'),action('P2',outcome,status)]}),expected);
 }
});
test('unrecognized task output falls through instead of producing an empty report',()=>{
 assert.equal(window.CommerceAssistantEvidence.archive({other:'data'},String),null);
});
test('calculation result renders exact quantities and distinguishes zero from unknown',()=>{
 window.CommerceUI={table:(_headers,rows)=>rows.join('')};
 const html=window.CommerceAssistantEvidence.archive({model:'windowed_stock_cover',status:'CALCULATED',velocity:3,days_of_cover:4,target_units:30,suggested_qty:18},String);
 assert.match(html,/建议补货/);assert.match(html,/>18 件</);assert.match(html,/未创建采购单/);
 const missing=window.CommerceAssistantEvidence.archive({model:'windowed_stock_cover',velocity:0,days_of_cover:null,suggested_qty:0},String);
 assert.match(missing,/>0 件/);assert.match(missing,/未知/);
});
