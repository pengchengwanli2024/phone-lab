/* AG-UI events over the original durable run. Detaching only stops observation. */
;(function(target){
  const active=new Set(['queued','running','cancel_requested']);
  const messages=thread=>(thread.turns||[]).flatMap(turn=>[
    {id:'q-'+turn.id,role:'user',content:turn.question},
    ...(turn.run.result?.answer?[{id:'a-'+turn.run.id,role:'assistant',content:turn.run.result.answer}]:[])
  ]);
  target.CommerceRunEvents={observe({api,thread,runId,pollMs=500,eventThreadId=thread?.id,eventRunId=runId,onEvent=()=>{},onComplete=()=>{},onError=()=>{}}){
    let detached=false,timer=null,wake=null;
    const emit=event=>{if(!detached)onEvent(event)};
    const delay=()=>new Promise(resolve=>{wake=resolve;timer=setTimeout(()=>{timer=null;wake=null;resolve()},Math.max(1,pollMs))});
    let finalThread;
    const execute=async()=>{
      if(!thread?.id||!runId)throw Error('missing_run_receipt');
      const id='a-'+runId,base=messages(thread).filter(message=>message.id!==id);
      let cursor=0,partial='',started=false;
      const deadline=Date.now()+10*60*1000;
      emit({type:'RUN_STARTED',threadId:eventThreadId,runId:eventRunId});
      while(!detached){
        if(Date.now()>deadline)throw Error('request_outcome_unknown');
        const value=await api('commerce_copilot_events',{thread_id:thread.id,run_id:runId,after:cursor});
        if(detached)return;
        const snapshot=value.snapshot;
        if(!snapshot||!Number.isSafeInteger(value.cursor)||value.cursor<0||typeof snapshot.answer!=='string'||!Array.isArray(snapshot.components))throw Error('invalid_run_events');
        cursor=value.cursor;
        emit({type:'STATE_SNAPSHOT',snapshot:{backend_thread_id:thread.id,backend_run_id:runId,status:value.status,cursor,provisional:snapshot.provisional,stream_mode:snapshot.mode,stream_answer:snapshot.answer,stream_truncated:snapshot.truncated===true,generative_components:snapshot.components}});
        if(!active.has(value.status))break;
        const text=snapshot.answer;
        if(text!==partial){
          if(!started&&text){emit({type:'TEXT_MESSAGE_START',messageId:id,role:'assistant'});started=true}
          if(text.startsWith(partial))emit({type:'TEXT_MESSAGE_CONTENT',messageId:id,delta:text.slice(partial.length)});
          else emit({type:'MESSAGES_SNAPSHOT',messages:[...base,...(text?[{id,role:'assistant',content:text}]:[])]});
          partial=text;
        }
        await delay();
      }
      if(detached)return;
      finalThread=await api('commerce_copilot_get',{thread_id:thread.id});
      if(detached)return;
      const run=finalThread.latest_run?.id===runId?finalThread.latest_run:finalThread.turns?.find(turn=>turn.run.id===runId)?.run;
      if(!run)throw Error('run_changed');
      emit({type:'STATE_SNAPSHOT',snapshot:{backend_thread_id:thread.id,backend_run_id:runId,status:run.status,provisional:false,generative_surface:run.presentation}});
      if(!run.result?.answer&&!['completed','review','needs_input','awaiting_input','awaiting_review'].includes(run.status)){
        emit({type:'MESSAGES_SNAPSHOT',messages:base});
        throw Error(run.error||'agent_run_'+run.status);
      }
      const answer=run.result?.answer||'本轮需要补充资料，请查看原任务。';
      if(!started)emit({type:'TEXT_MESSAGE_START',messageId:id,role:'assistant'});
      if(answer.startsWith(partial))emit({type:'TEXT_MESSAGE_CONTENT',messageId:id,delta:answer.slice(partial.length)});
      else emit({type:'MESSAGES_SNAPSHOT',messages:[...base,{id,role:'assistant',content:answer}]});
      emit({type:'TEXT_MESSAGE_END',messageId:id});
      emit({type:'RUN_FINISHED',threadId:eventThreadId,runId:eventRunId});
      if(!detached)onComplete(finalThread);
    };
    void execute().catch(error=>{if(!detached){emit({type:'RUN_ERROR',message:error.message||'run_observation_failed'});onError(error,finalThread)}});
    return ()=>{detached=true;if(timer!==null)clearTimeout(timer);timer=null;wake?.();wake=null};
  }};
})(typeof window==='undefined'?globalThis:window);
