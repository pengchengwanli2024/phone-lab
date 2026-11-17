import { useEffect,useRef,useState } from 'react';
import { api,errorText } from './api';
import { Badge,Button,Empty,ErrorNotice,Status } from './ui';
import { eventTime,readTimeline,type TimelineKind,type TimelinePage } from './timeline-state';

const labels:Record<string,string>={task_current:'原任务当前状态',human_request:'明确提交模型请求',run_recovery_created:'接续原任务的模型请求',run_current:'模型请求当前状态',proposal_submitted:'人工确认并关联本地任务',local_execution_requested:'明确请求本地执行',local_execution_started:'本地执行开始',local_execution_finished:'本地执行结束回执',research_current:'原研究当前进展',host_attempt_current:'宿主执行尝试',model_step:'模型步骤额度记录',model_step_legacy:'历史模型步骤（时间未记录）',read_evidence:'已读取的依据回执',read_step:'读取步骤额度记录',followup_created:'预约只读复查',followup_current:'复查当前状态',followup_checked:'已保存复查回执'};
const states:Record<string,string>={reserved:'预留中／待核对',consumed:'已预留一次读取',ready:'有结果待核对',unchanged:'未发现变化',changed:'原事项已变化',scope_changed:'原范围已变化',outcome_unknown:'结果未知',needs_attention:'需要核对',unavailable:'来源未读到',scheduled:'等待复查',checked:'已有回执',acknowledged:'已查看',cancelled:'已取消'};

export function TaskTimeline({kind,id}:{kind:TimelineKind;id:string}){
  const [data,setData]=useState<TimelinePage|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const version=useRef(0),details=useRef<HTMLDetailsElement>(null),busyRef=useRef(false);
  useEffect(()=>()=>{version.current++;},[kind,id]);
  async function load(more=false){
    if(busyRef.current)return;busyRef.current=true;setBusy(true);setError('');const request=++version.current;
    try{
      const result=await readTimeline(api,kind,id,more?data?.next_cursor||undefined:undefined);
      if(request!==version.current)return;
      setData(previous=>more&&previous?{...result,events:[...new Map([...previous.events,...result.events].map(event=>[event.id,event])).values()]}:result);
      if(!result.complete)setError('部分历史资料未读到，时间线不完整。');
    }catch(failure){if(request===version.current)setError(errorText(failure));}
    finally{if(request===version.current){busyRef.current=false;setBusy(false);}}
  }
  return <details ref={details} onToggle={()=>{if(details.current?.open&&!data&&!busyRef.current)void load();}}>
    <summary>任务时间线</summary><ErrorNotice>{error}</ErrorNotice>
    <div className="r-form-actions"><Button disabled={busy} onClick={()=>void load()}>刷新时间线</Button>{data?.demo&&<Badge>示例数据</Badge>}</div>
    {data&&!data.scope_current&&<p role="status">当前工作范围已变化，以下保留原范围历史。</p>}
    {data?.budgets.map(budget=><section key={budget.chain_id}><strong>任务链额度</strong><p>模型步骤 {budget.usage.model_steps} / {budget.limits.model_steps} · 读取 {budget.usage.read_steps} / {budget.limits.read_steps}</p><p>模型预留／执行耗时 {Math.ceil(budget.usage.model_seconds)} / {budget.limits.model_seconds} 秒 · 层级 {budget.depth} / {budget.limits.max_depth}</p>{budget.unconfirmed_steps>0&&<p>有 {budget.unconfirmed_steps} 个未确认步骤保留额度占用。</p>}{budget.historical_usage_unrecorded&&<p className="r-footnote">启用前的累计调用量未完整记录。</p>}</section>)}
    {data&&!data.historical_transitions_complete&&<p role="status" className="r-footnote">这条历史记录未保存完整过程；以下仅显示已有回执。</p>}{!!data?.budgets.length&&<details><summary>额度口径</summary><p className="r-footnote">额度按原记录汇总，不代表费用或业务完成；等待人工期间不计执行耗时。</p></details>}
    {busy&&!data?<Empty>正在读取原任务历史…</Empty>:data?.events.length?<ol className="r-notices">{data.events.map(event=><li className="r-notice" key={event.id}><div><strong>{labels[event.event]||'原记录'}</strong><p>{eventTime(event.at)}</p>{typeof event.detail.request_summary==='string'&&<p>{event.detail.request_summary}</p>}{data.mixed_modes&&<Badge>{event.demo===true?'示例数据':event.demo===false?'本机记录':'范围未知'}</Badge>}</div>{event.status&&(states[event.status]?<Badge>{states[event.status]}</Badge>:<Status value={event.status}/>)}</li>)}</ol>:data?<Empty>当前没有已记录的历史步骤。</Empty>:null}
    {data?.has_more&&<Button disabled={busy} onClick={()=>void load(true)}>加载更早的历史</Button>}
  </details>;
}
