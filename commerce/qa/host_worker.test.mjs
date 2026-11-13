import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import test from 'node:test';

const workerUrl=new URL('../harness/host-worker.js',import.meta.url);
const route={provider:'synthetic-provider',model:'synthetic-model'};
const settled=()=>({reason:'idle',state:{running:false},output:{truncated:false,records:[{type:'event',event:{type:'assistant/message',data:{
  message:{role:'assistant',source:{kind:'model',...route},content:[{type:'text',text:'{"ok":true}'}]},
  stream:[{type:'chunk',time:1,chunk:{type:'finish',reason:{kind:'stop'}}}]
}}}]}});
async function parse(value){
  assert.ok(existsSync(workerUrl),'Bounded DSH native receipt parser is missing');
  return (await import(workerUrl)).settledResult(value,route,'native-session','request-one');
}
test('native completion retains actual provider, model and session receipt',async()=>{
  const result=await parse(settled());assert.deepEqual(result.data,{ok:true});
  assert.deepEqual(result.receipt,{session_id:'native-session',provider:route.provider,model:route.model,request_id:'request-one',finish_reason:'completed',tools_used:[]});
});
for(const reason of ['timeout','input-required'])test(`native ${reason} does not claim completion`,async()=>{
  const value=settled();value.reason=reason;await assert.rejects(()=>parse(value),/unconfirmed/);
});
test('wrong actual native model is rejected',async()=>{
  const value=settled();value.output.records[0].event.data.message.source.model='another-model';
  await assert.rejects(()=>parse(value),/route_changed/);
});
test('tool call and interrupted output are rejected',async()=>{
  const value=settled();value.output.records[0].event.data.message.content.push({type:'tool-call',name:'write'});
  await assert.rejects(()=>parse(value),/tools/);
  const interrupted=settled();interrupted.output.records[0].event.data.interrupted=true;
  await assert.rejects(()=>parse(interrupted),/unconfirmed/);
});
test('token-limited JSON does not masquerade as a settled native response',async()=>{
  const value=settled();value.output.records[0].event.data.stream[0].chunk.reason.kind='max-tokens';
  await assert.rejects(()=>parse(value),/unconfirmed/);
});
test('native worker creates a scoped Agent with required SDK arguments and commits the same request',async()=>{
  const state=await mkdtemp(path.join(tmpdir(),'commerce-native-contract-'));
  await writeFile(path.join(state,'auth.token'),'synthetic-token');
  const originalFetch=globalThis.fetch,calls=[];let claimed=false,disposed=false,guard;
  const request={request_id:'synthetic-request',route,payload:{synthetic:true},output_schema:{type:'object'},instructions:'Return the supplied JSON.'};
  const lease={attempt_id:'a'.repeat(32),generation:1,lease_token:'b'.repeat(64),request};
  let resolveEvent;const event=new Promise(resolve=>resolveEvent=resolve);
  const ctx={
    agentDefaultModel:{currentSelection:()=>route},tools:{schemas:()=>[]},
    agents:{create:async options=>{
      assert.equal(options.agentOptions.model,route.model);
      options.setup({tools:{restrict:spec=>assert.deepEqual(spec,{allow:[]}),guard:fn=>guard=fn},
        systemPrompt:{section:section=>assert.ok(Number.isFinite(section.order),'Installed SDK requires a finite prompt section order')}});
      return {agent:{id:options.sessionId},dispose:async()=>{disposed=true}};
    }},
    sessionController:{prompt:async (value,signal)=>{assert.equal(value.requestId,request.request_id);assert.ok(signal instanceof AbortSignal);return {accepted:true}},wait:async()=>settled()},
  };
  globalThis.fetch=async(url,options)=>{
    const call=JSON.parse(options.body);calls.push(call);
    if(call.operation==='claim'){
      if(claimed)return Response.json(null);claimed=true;
      return Response.json({...lease,worker_id:call.arguments.worker_id});
    }
    return Response.json({});
  };
  let stop;
  try{
    const {startHostWorker}=await import(workerUrl);
    stop=startHostWorker(ctx,{state,origin:'http://synthetic.invalid',onEvent:resolveEvent});
    const outcome=await Promise.race([event,new Promise((_,reject)=>setTimeout(()=>reject(Error('Worker contract timed out')),2000).unref())]);
    assert.equal(outcome.type,'completed',String(outcome.error));
    assert.deepEqual(guard(),{reason:'commerce_native_tools_disabled'});
    const done=calls.find(c=>c.operation==='finish').arguments;
    assert.deepEqual(done.result,{ok:true});assert.equal(done.receipt.request_id,request.request_id);
    assert.equal(done.receipt.session_id,'commerce-native-'+lease.attempt_id);
  }finally{
    await stop?.();globalThis.fetch=originalFetch;await rm(state,{recursive:true,force:true});
  }
  assert.ok(disposed);
});
