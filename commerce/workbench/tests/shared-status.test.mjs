import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const context=vm.createContext({});vm.runInContext(await readFile('../ui/status.js','utf8'),context);
const describe=context.CommerceStatus.describe;

test('an unconfirmed outcome is its own warning state, not an unrecognized code',()=>{
  const unknown=describe('unknown',{cancel:true,retry:true});
  assert.equal(unknown.label,'结果未知');assert.equal(unknown.tone,'warning');
  // Never offered as cancellable or retryable: the original request must be checked first.
  assert.equal(unknown.canCancel,false);assert.equal(unknown.canRetry,false);assert.equal(unknown.terminal,false);
  assert.equal(describe('needs_input').label,describe('awaiting_input').label);
});
test('unrecognized codes stay visibly unrecognized and imply no action',()=>{
  for(const code of ['future_status','',undefined,null,'constructor']){
    const row=describe(code,{cancel:true,retry:true});
    assert.equal(row.label,'状态未知');assert.equal(row.tone,'gray');assert.equal(row.canCancel,false);assert.equal(row.canRetry,false);
  }
});
test('success, failure and interruption keep separate tones',()=>{
  assert.deepEqual(['completed','failed','interrupted','cancelled','queued'].map(code=>describe(code).tone),['success','danger','warning','gray','blue']);
});
