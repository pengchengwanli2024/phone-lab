/** Read-only projection of the unattended-run health checks. A green result is not business acceptance. */
export interface HealthCheck {id:string;status:string;label:string;detail:string;target:string}
export interface Health {status:string;checks:HealthCheck[];checked_at:number;auto_backup:boolean;auto_backup_count:number}

const states:Record<string,[string,string]>={ok:['正常','green'],warning:['需关注','warning'],critical:['故障','danger'],unknown:['未读到','gray']};
export const healthStatus=(value:string)=>{const found=states[value];return {label:found?.[0]||'状态待核对',tone:found?.[1]||'gray'};};
const rank:Record<string,number>={critical:0,warning:1,unknown:2,ok:3};
/** Problems first; the order within one severity is the server's. */
export const sortedChecks=(checks:HealthCheck[])=>[...checks].sort((a,b)=>(rank[a.status]??2)-(rank[b.status]??2));
const pages:Record<string,string>={tasks:'去任务中心',platforms:'查看店铺数据',connections:'查看连接'};
/** Only a check that needs attention offers a destination. */
export const checkAction=(check:HealthCheck)=>check.status==='ok'?null:pages[check.target]?{tab:check.target,label:pages[check.target]}:null;
export function healthSummary(value:Health):string {
  const open=value.checks.filter(check=>check.status==='critical'||check.status==='warning').length;
  const unread=value.checks.filter(check=>check.status==='unknown').length;
  return [open?open+' 项需要处理':'各项检查正常',unread?unread+' 项未读到':'','依赖本机保持登录和不休眠'].filter(Boolean).join(' · ');
}
