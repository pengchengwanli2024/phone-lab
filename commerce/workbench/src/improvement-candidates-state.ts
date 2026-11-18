/** Read-only projection of recurring failures. A candidate is a suggestion, never an applied change. */
export interface Candidate {id:string;domain:string;error:string;count:number;last_at:number|null;fix_first:string;hint:string;status:string;engineering_feature?:string|null}
export interface Retrospect {window_days:number;candidates:Candidate[];single_incidents:number;uncoded_failures:Record<string,number>;engineering?:{covered_candidates?:string[];uncovered_domains:string[]}}
/** Say plainly who has to act on the candidates; never imply the engineering team will pick them up. */
export function handlingText(value:Retrospect):string {
  if(!value.candidates.length)return '';
  const open=value.engineering?.uncovered_domains||[],covered=value.candidates.filter(item=>item.engineering_feature).length;
  const parts=[];
  if(covered)parts.push(covered+' 项已有工程配方，可由人明确发起工程工单；不会自动发起。');
  if(open.length)parts.push('其余环节的代码超出工程执行器的受限快照范围，需要由人安排修复：'+open.map(domainName).join('、')+'。');
  return parts.join('');
}

const domains:Record<string,string>={model_request:'模型请求',extension:'扩展与定时计划',market_research:'市场研究',store_read:'店铺读取',operating_loop:'经营回路'};
const fixes:Record<string,string>={connector:'先改连接器',contract:'先改契约或校验',limits:'先核对额度',recovery:'先补核对入口',inputs:'先补资料',check:'先补检查'};
export const domainName=(value:string)=>domains[value]||value;
export const fixName=(value:string)=>fixes[value]||'先补检查';

export function candidateSummary(value:Retrospect):string {
  const uncoded=Object.values(value.uncoded_failures||{}).reduce((sum,count)=>sum+count,0);
  const parts=['最近 '+value.window_days+' 天'];
  parts.push(value.candidates.length?value.candidates.length+' 类失败重复出现':'没有重复出现的失败');
  if(value.single_incidents)parts.push(value.single_incidents+' 类只出现一次，未列为候选');
  if(uncoded)parts.push(uncoded+' 次失败没有可归类的原因码');
  return parts.join(' · ');
}
