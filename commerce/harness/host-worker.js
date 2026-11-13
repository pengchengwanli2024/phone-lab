import {mkdir,readFile} from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';

export function settledResult(value,route,sessionId,requestId){
  if(value?.reason!=='idle'||value.state?.running||value.output?.truncated)throw Error('native_outcome_unconfirmed');
  const messages=(value.output?.records||[]).filter(r=>r.type==='event'&&r.event?.type==='assistant/message');
  if(!messages.length)throw Error('native_outcome_unconfirmed');
  for(const record of messages){
    if(record.event.data?.message?.content?.some(block=>block.type==='tool-call'))throw Error('native_tools_unexpected');
  }
  const data=messages[0].event.data,message=data.message;
  if(data.interrupted||message?.source?.kind!=='model')throw Error('native_outcome_unconfirmed');
  if(message.source.provider!==route.provider||message.source.model!==route.model)throw Error('native_route_changed');
  const finishes=(data.stream||[]).filter(record=>record.type==='chunk'&&record.chunk?.type==='finish');
  if(finishes.at(-1)?.chunk.reason?.kind!=='stop')throw Error('native_outcome_unconfirmed');
  const text=message.content.filter(block=>block.type==='text').map(block=>block.text).join('');
  return {data:JSON.parse(text),receipt:{session_id:sessionId,provider:message.source.provider,
    model:message.source.model,request_id:requestId,finish_reason:'completed',tools_used:[]}};
}

/** Existing Harness process, scoped Agent only; never changes deployment defaults. */
export function startHostWorker(ctx,{state,origin,onEvent=()=>{}}){
  const workerId='dsh-'+randomUUID();let stopped=false,timer,activeHandle,activeAbort;
  async function broker(operation,argumentsValue){
    const token=(await readFile(path.join(state,'auth.token'),'utf8')).trim();
    const response=await fetch(origin+'/v1/host-worker',{method:'POST',
      headers:{'content-type':'application/json','authorization':'Bearer '+token},
      body:JSON.stringify({operation,arguments:argumentsValue}),signal:AbortSignal.timeout(15000)});
    if(!response.ok){
      const failure=await response.json().catch(()=>({}));
      const code=/^(?:host|agent)_[a-z_]+$/.test(failure.error)?failure.error:'commerce_host_broker_unavailable';
      throw Error(code);
    }
    return response.json();
  }
  async function register(){
    const selected=ctx.agentDefaultModel.currentSelection();
    await broker('register',{host_id:'dsh',provider:selected.provider,model:selected.model});
  }
  async function execute(lease){
    const request=lease.request,route=request.route;
    if(!/^[a-f0-9]{32}$/.test(lease.attempt_id))throw Error('invalid_native_attempt');
    const identity={attempt_id:lease.attempt_id,generation:lease.generation,
      worker_id:workerId,lease_token:lease.lease_token};
    const sessionId='commerce-native-'+lease.attempt_id;
    const cwd=path.join(state,'host-work',lease.attempt_id);await mkdir(cwd,{recursive:true,mode:0o700});
    let heartbeat,submitted=false;const abort=new AbortController();activeAbort=abort;
    try{
      activeHandle=await ctx.agents.create({sessionId,meta:{cwd},
        agentOptions:{provider:route.provider,model:route.model,maxTokens:3500},signal:abort.signal,
        setup:(agentCtx)=>{
          agentCtx.tools.restrict({allow:[]});
          agentCtx.tools.guard(()=>({reason:'commerce_native_tools_disabled'}));
          agentCtx.systemPrompt.section({name:'commerce-native-boundaries',order:10000,text:request.instructions});
        }});
      const agent=activeHandle.agent;
      if(ctx.tools.schemas(agent).length!==0)throw Error('native_tool_menu_not_empty');
      heartbeat=setInterval(()=>{
        void broker('heartbeat',identity).then(register).catch(()=>abort.abort(Error('native_lease_lost')));
      },10000);
      submitted=true;
      const accepted=await ctx.sessionController.prompt({sessionId:agent.id,requestId:request.request_id,
        content:[{type:'text',text:JSON.stringify({request_id:request.request_id,input:request.payload,
          output_schema:request.output_schema})}],mode:'queue'},abort.signal);
      if(accepted?.accepted!==true)throw Error('native_admission_unconfirmed');
      await broker('admit',{...identity,session_id:agent.id});
      const value=await ctx.sessionController.wait({sessionId:agent.id,timeoutMs:100000,maxMessages:20},abort.signal);
      if(ctx.tools.schemas(agent).length!==0)throw Error('native_tool_menu_changed');
      const result=settledResult(value,route,agent.id,request.request_id);
      await broker('finish',{...identity,outcome:'completed',result:result.data,receipt:result.receipt});
      onEvent({type:'completed',attempt_id:lease.attempt_id});
    }catch(error){
      onEvent({type:'unconfirmed',attempt_id:lease.attempt_id,submitted,error});
      await broker('finish',{...identity,outcome:submitted?'unknown':'failed'}).catch(()=>{});
    }finally{
      clearInterval(heartbeat);abort.abort();
      await activeHandle?.dispose();activeHandle=undefined;activeAbort=undefined;
    }
  }
  async function poll(){
    if(stopped)return;
    try{await register();const lease=await broker('claim',{host_id:'dsh',worker_id:workerId});
      if(lease&&!stopped)await execute(lease);
    }catch(error){onEvent({type:'unavailable',error});}
    finally{if(!stopped)timer=setTimeout(poll,2000);}
  }
  void poll();
  return async()=>{stopped=true;clearTimeout(timer);activeAbort?.abort(Error('native_worker_stopped'));
    await activeHandle?.dispose();};
}
