import {mkdir,readFile,writeFile,rename,unlink} from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';

const NATIVE_MAX_TOKENS=8192;
async function writePrivateJSON(file,value){
  const temporary=file+'.'+randomUUID()+'.tmp';
  try{await writeFile(temporary,JSON.stringify(value),{mode:0o600,flag:'wx'});await rename(temporary,file);}
  finally{await unlink(temporary).catch(()=>{});}
}

function parseDecision(text){
  // A completed model may wrap its sole JSON value in a Markdown code fence.
  // Normalize only that exact envelope; never extract JSON from surrounding prose.
  const fenced=text.trim().match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i);
  if(fenced)text=fenced[1];
  try{return JSON.parse(text)}catch{
    // Some completed native replies contain literal newlines/tabs inside JSON
    // strings. Escape only those characters; schema validation stays server-side.
    let quoted=false,escaped=false,normalized='';
    for(const character of text){
      if(quoted&&character.charCodeAt(0)<32){normalized+=JSON.stringify(character).slice(1,-1);continue}
      normalized+=character;
      if(escaped){escaped=false;continue}
      if(quoted&&character==='\\'){escaped=true;continue}
      if(character==='"')quoted=!quoted;
    }
    return JSON.parse(normalized);
  }
}

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
  const finishReason=finishes.at(-1)?.chunk.reason?.kind;
  if(finishReason==='max-tokens')throw Error('native_output_limit');
  if(finishReason!=='stop')throw Error('native_outcome_unconfirmed');
  const text=message.content.filter(block=>block.type==='text').map(block=>block.text).join('');
  let decision;try{decision=parseDecision(text)}catch{throw Error('native_invalid_json')}
  return {data:decision,receipt:{session_id:sessionId,provider:message.source.provider,
    model:message.source.model,request_id:requestId,finish_reason:'completed',tools_used:[]}};
}

/** Existing Harness process, scoped Agent only; never changes deployment defaults. */
export function startHostWorker(ctx,{state,origin,onEvent=()=>{}}){
  const workerId='dsh-'+randomUUID();let stopped=false,timer,activeHandle,activeAbort;
  const versionReady=writePrivateJSON(path.join(state,'native-worker-version.json'),{
    schema:'commerce-native-worker-v1',version:'json-envelope-3',worker_id:workerId,
    output_tokens:NATIVE_MAX_TOKENS,started_at:Date.now()}).catch(()=>{});
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
        // Reasoning consumes the same output budget. 3500 truncated a real
        // final analysis before its JSON answer; keep a larger bounded budget.
        agentOptions:{provider:route.provider,model:route.model,maxTokens:NATIVE_MAX_TOKENS},signal:abort.signal,
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
      const known=new Set(['native_output_limit','native_invalid_json','native_outcome_unconfirmed',
        'native_route_changed','native_tools_unexpected','native_admission_unconfirmed',
        'native_tool_menu_not_empty','native_tool_menu_changed','native_lease_lost','host_invalid_result']);
      const diagnostic={schema:'commerce-native-outcome-v1',attempt_id:lease.attempt_id,
        request_id:request.request_id,phase:lease.phase||null,provider:route.provider,model:route.model,
        code:known.has(error?.message)?error.message:'native_outcome_unconfirmed',max_tokens:NATIVE_MAX_TOKENS,
        submitted,recorded_at:Date.now()};
      // This receipt explains uncertainty without storing prompts, replies or credentials.
      // A diagnostic must never replace the broker's authoritative completion/schema checks.
      await writePrivateJSON(path.join(cwd,'outcome.json'),diagnostic).catch(()=>{});
      onEvent({type:'unconfirmed',attempt_id:lease.attempt_id,submitted,error});
      await broker('finish',{...identity,outcome:submitted?'unknown':'failed'}).catch(()=>{});
    }finally{
      clearInterval(heartbeat);abort.abort();
      await activeHandle?.dispose();activeHandle=undefined;activeAbort=undefined;
    }
  }
  async function poll(){
    if(stopped)return;
    try{await versionReady;await register();const lease=await broker('claim',{host_id:'dsh',worker_id:workerId});
      if(lease&&!stopped)await execute(lease);
    }catch(error){onEvent({type:'unavailable',error});}
    finally{if(!stopped)timer=setTimeout(poll,2000);}
  }
  void poll();
  return async()=>{stopped=true;clearTimeout(timer);activeAbort?.abort(Error('native_worker_stopped'));
    await activeHandle?.dispose();};
}
