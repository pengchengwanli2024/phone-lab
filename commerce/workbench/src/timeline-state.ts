export type TimelineKind = 'task' | 'run' | 'followup';
export interface TimelineEvent { id:string; event:string; source:string; source_id:string; at:number|null; status:string; detail:Record<string,unknown>;demo:boolean|null }
export interface ChainAllowance {
  chain_id:string; depth:number; limits:{model_steps:number;read_steps:number;model_seconds:number;max_depth:number};
  usage:{model_steps:number;read_steps:number;model_seconds:number}; unconfirmed_steps:number;
  recorded_since:number|null;historical_usage_unrecorded:boolean;
}
export interface TimelinePage {kind:TimelineKind;id:string;demo:boolean|null;scope_current:boolean;events:TimelineEvent[];budgets:ChainAllowance[];has_more:boolean;next_cursor:string|null;complete:boolean;missing_times:number;historical_transitions_complete:boolean;mixed_modes?:boolean}
export async function readTimeline(invoke:(name:string,args:object)=>Promise<unknown>,kind:TimelineKind,id:string,cursor?:string):Promise<TimelinePage>{
  const value=await invoke('commerce_task_timeline_get',{kind,id,limit:30,...(cursor?{cursor}:{})}) as TimelinePage;
  if(value?.kind!==kind||value.id!==id||!Array.isArray(value.events)||!Array.isArray(value.budgets))throw Error('timeline_source_changed');
  return value;
}
export function eventTime(value:number|null):string {
  if(value===null||!Number.isFinite(value))return '时间未记录';
  const date=new Date(value*1000);return Number.isFinite(date.getTime())?date.toLocaleString('zh-CN'):'时间未记录';
}
