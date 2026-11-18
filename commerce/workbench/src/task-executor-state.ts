/** Read-only projection of who ran a task and why that executor was chosen. Nothing here selects, retries or takes over. */
export interface HostRoute {host_id?:string;provider?:string;model?:string}
export interface HostAttempt {attempt_id?:string;phase?:string;generation?:number;host_id?:string;status?:string}
export interface ModelChoice {label?:string;provider?:string;model?:string;host_id?:string;native_provider?:string;routing_reason?:string}
export interface ExecutorSource {run_id?:string;execution_hosts?:HostRoute[];host_attempts?:HostAttempt[]}
export type ChoiceRead={state:'none'}|{state:'loading'}|{state:'failed'}|{state:'ready';choice:ModelChoice};
export interface ExecutorView {
  recorded:boolean;name:string;model:string;reason:string;reasonKnown:boolean;
  attempts:{key:string;host:string;phase:string;generation:number|null;status:string;unresolved:boolean}[];
}

const hosts:Record<string,string>={dsh:'Harness',hermes:'Hermes',codex:'Codex'};
const reasons:Record<string,string>={
  priority_live_capability:'智能选择：按已设定的执行端优先顺序，选用提交时在线的第一个执行端',
  explicit_host_plan:'提交时明确指定了该执行端',
  explicit_deepseek_account:'提交时明确选择了该模型账号',
};
const attemptStates:Record<string,string>={pending:'等待执行端领取',claimed:'执行端已领取，结果尚未回报',completed:'已有完成回执',failed:'执行失败',unknown:'结果未知，先核对原请求，不重发'};
const text=(value:unknown,limit=80)=>typeof value==='string'?value.trim().slice(0,limit):'';
export const hostName=(value?:string)=>hosts[value||'']||text(value)||'';

export function executorView(source:ExecutorSource|null|undefined,read:ChoiceRead):ExecutorView {
  const plan=Array.isArray(source?.execution_hosts)?source.execution_hosts.filter(item=>item&&typeof item==='object'):[];
  const choice=read.state==='ready'?read.choice:null;
  const planned=plan.map(item=>hostName(item.host_id)).filter(Boolean);
  // A model chosen without a host route runs inside the shared workbench; say so only when the record shows it.
  const name=planned.length?planned.join(' → '):hostName(choice?.host_id)||(choice&&(choice.label||choice.model)?'工作台内置执行':'');
  const model=text(plan[0]?.model)||text(choice?.model);
  const code=text(choice?.routing_reason,200);
  const reason=read.state==='loading'?'正在读取选择依据…':read.state==='failed'?'选择依据未读到，可稍后重新查看回执。'
    :code?reasons[code]||'原记录：'+code
    :choice&&name?'原记录未保存选择依据；该执行端或模型由提交时的选择直接决定。':'未记录选择依据。';
  const attempts=(Array.isArray(source?.host_attempts)?source.host_attempts:[]).filter(item=>item&&typeof item==='object').map((item,index)=>({
    key:text(item.attempt_id,160)||String(index),host:hostName(item.host_id)||'执行端未记录',phase:text(item.phase),
    generation:typeof item.generation==='number'?item.generation:null,
    status:attemptStates[item.status||'']||text(item.status)||'状态待核对',unresolved:['claimed','unknown'].includes(item.status||''),
  }));
  return {recorded:!!name,name:name||'未记录执行端',model,reason,reasonKnown:!!code&&read.state==='ready',attempts};
}
