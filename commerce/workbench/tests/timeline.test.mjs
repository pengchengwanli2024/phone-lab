import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';

async function helper(){
  assert.ok(existsSync(new URL('../src/timeline-state.ts',import.meta.url)),'timeline read contract is missing');
  return import('../src/timeline-state.ts');
}
test('timeline pagination reads the exact original object without a write or fallback list',async()=>{
  const{readTimeline}=await helper();const calls=[];
  const result=await readTimeline(async(name,args)=>{calls.push([name,args]);return {kind:'task',id:'original-task',events:[],budgets:[],has_more:false,next_cursor:null};},'task','original-task','snapshot:cursor');
  assert.deepEqual(calls,[['commerce_task_timeline_get',{kind:'task',id:'original-task',limit:30,cursor:'snapshot:cursor'}]]);
  assert.equal(result.id,'original-task');
});
test('another object cannot supply a late timeline response',async()=>{
  const{readTimeline}=await helper();
  await assert.rejects(()=>readTimeline(async()=>({kind:'run',id:'another-run',events:[]}), 'run','selected-run'),/timeline_source_changed/);
});
test('missing historical timestamps remain unknown instead of becoming an epoch date',async()=>{
  const{eventTime}=await helper();assert.equal(eventTime(null),'时间未记录');assert.equal(eventTime(NaN),'时间未记录');
  assert.notEqual(eventTime(1800000000),'时间未记录');
});
