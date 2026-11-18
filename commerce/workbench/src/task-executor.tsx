import {useEffect,useState} from 'react';
import {api} from './api';
import {executorView,type ChoiceRead,type ExecutorSource,type ModelChoice} from './task-executor-state';

/** Shows the executor recorded on the original receipt. Display only: it never selects, retries or takes over. */
export function TaskExecutor({source,choice}:{source?:ExecutorSource|null;choice?:ModelChoice|null}) {
  const runId=source?.run_id&&/^[a-zA-Z0-9_-]{1,160}$/.test(source.run_id)?source.run_id:'';
  const [read,setRead]=useState<{run:string;value:ChoiceRead}>({run:'',value:{state:'none'}});
  useEffect(()=>{
    if(choice||!runId)return;
    let current=true;setRead({run:runId,value:{state:'loading'}});
    api<{model_choice?:ModelChoice}>('commerce_agent_get',{run_id:runId})
      .then(value=>{if(current)setRead({run:runId,value:value.model_choice&&typeof value.model_choice==='object'?{state:'ready',choice:value.model_choice}:{state:'none'}});})
      .catch(()=>{if(current)setRead({run:runId,value:{state:'failed'}});});
    return()=>{current=false;};
  },[runId,choice]);
  const view=executorView(source,choice?{state:'ready',choice}:read.run===runId?read.value:{state:'none'});
  return <section className="r-task-executor" aria-label="执行端与选择依据">
    <dl><div><dt>执行端</dt><dd>{view.name}{view.model&&<small> · {view.model}</small>}</dd></div><div><dt>选择依据</dt><dd>{view.reason}</dd></div></dl>
    {view.attempts.length>0&&<ul>{view.attempts.map(item=><li key={item.key}>{[item.host,item.phase,item.generation!=null?'第 '+item.generation+' 次':''].filter(Boolean).join(' · ')}：{item.status}</li>)}</ul>}
    {view.attempts.some(item=>item.unresolved)&&<p role="status">有执行尝试结果未确认。先核对原请求回执，不重新提交。</p>}
  </section>;
}
