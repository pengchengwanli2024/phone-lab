import {groupWork,type LoopView} from './operating-loop-state';

/** What the operator must know before anything else: faults first, then decisions. Read-only projection. */
export interface RuntimeRead {worker?:string;capability_runtime?:Record<string,unknown>|null}
export type Read<T>={state:'loading'}|{state:'failed'}|{state:'ready';value:T};
export interface DispatchRead {items:Record<string,string>;unassigned:number}
/** Split queued work into work some executor will pick up and work nobody will. Unknown dispatch keeps the old count. */
export function splitInProgress<T extends {id:string;status:string}>(tasks:T[],dispatch:Read<DispatchRead>):{running:T[];parked:T[]} {
  if(dispatch.state!=='ready')return {running:tasks,parked:[]};
  const parked=tasks.filter(task=>task.status==='queued'&&dispatch.value.items[task.id]==='unassigned');
  return {running:tasks.filter(task=>!parked.includes(task)),parked};
}
export interface CommandItem {id:string;tone:'danger'|'warning'|'blue';title:string;detail:string;target:'operating-control'|'tasks'|'connections'}

const faults:Record<string,string>={
  media_error:'媒体制作的后台任务正在失败',extension_error:'扩展与定时计划的后台任务正在失败',team_error:'团队触发器的后台任务正在失败',
  engineering_error:'工程任务的后台调度正在失败',operating_loop_error:'经营回路的后台检查正在失败',
};

export interface HealthRead {checks:{id:string;status:string;label:string;detail:string}[]}
/** Backup and disk are the only health checks not already shown elsewhere on this page. */
const healthOnly=['backup','disk'];

export function commandItems(runtime:Read<RuntimeRead>,loop:Read<LoopView>,synthetic:boolean,health:Read<HealthRead>={state:'loading'}):CommandItem[] {
  const items:CommandItem[]=[];
  // A failed read is reported as such; it must never look like "nothing is wrong".
  if(runtime.state==='failed')items.push({id:'runtime-unread',tone:'warning',title:'运行状态未读到',detail:'无法确认后台是否正常，请刷新。',target:'connections'});
  if(runtime.state==='ready'){
    if(runtime.value.worker!=='running')items.push({id:'worker',tone:'danger',title:'后台工作器没有在运行',detail:'排队的任务和定时计划不会被处理。',target:'connections'});
    for(const [key,value]of Object.entries(runtime.value.capability_runtime||{})){
      if(!key.endsWith('_error')||!value)continue;
      items.push({id:key,tone:'danger',title:faults[key]||'一项后台任务正在失败',detail:'相关功能可能停滞，原记录保留。',target:'connections'});
    }
  }
  if(loop.state==='failed')items.push({id:'loop-unread',tone:'warning',title:'经营回路状态未读到',detail:'无法确认是否有待你决定的事项，请刷新。',target:'operating-control'});
  if(loop.state==='ready'){
    const groups=groupWork(loop.value,synthetic);
    const halted=loop.value.grants.filter(grant=>grant.synthetic===synthetic&&grant.halted_reason).length;
    if(halted)items.push({id:'loop-halted',tone:'danger',title:halted+' 件商品的回路已自动停用',detail:'连续失败后停止派发，核对原因后可重新启用。',target:'operating-control'});
    if(groups.attention.length)items.push({id:'loop-attention',tone:'warning',title:groups.attention.length+' 项回路工单需要核对',detail:'失败或结果未知；核对关闭前不会继续派发。',target:'operating-control'});
    if(groups.decide.length)items.push({id:'loop-decide',tone:'blue',title:groups.decide.length+' 项建议等你决定',detail:'负责岗位已给出建议，批准后才会登记交接任务。',target:'operating-control'});
  }
  if(health.state==='ready')for(const check of health.value.checks){
    if(!healthOnly.includes(check.id)||!['warning','critical'].includes(check.status))continue;
    items.push({id:'health-'+check.id,tone:check.status==='critical'?'danger':'warning',title:check.label,detail:check.detail,target:'connections'});
  }
  return items;
}
