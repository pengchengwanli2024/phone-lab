import test from 'node:test';
import assert from 'node:assert/strict';
import { conversationDestination } from '../src/navigation.ts';
test('returning to a case conversation opens its original business page',()=>{
  const context={module:'organization',entity:{kind:'case',id:'case'}};
  assert.equal(conversationDestination(context),'workspace');
  assert.equal(conversationDestination(context,{page:'listing'}),'listing');
  assert.equal(conversationDestination(context,{page:'workflow'}),'workflow');
  assert.equal(conversationDestination(context,{page:'organization'}),'organization');
  assert.equal(conversationDestination(context,{page:'orders'}),'workspace');
});
test('a generic module never inherits an unrelated case page',()=>{
  assert.equal(conversationDestination({module:'intelligence'},{page:'workspace'}),'intelligence');
  assert.equal(conversationDestination({module:'orders'},{page:'store-ops'}),'store-ops');
  assert.equal(conversationDestination({module:'organization'},{page:'listing'}),'organization');
});
