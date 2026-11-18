/** Which unresolved items an operator may mark as checked. Mirrors the server rule; the server decides. */
export interface ReviewItem {id:string;source:string;source_id:string;kind:string;title:string;detail:string;status?:string;demo?:boolean}

export const closable=(item:ReviewItem)=>(item.kind==='unknown'||item.kind==='failed')&&item.status!=='submission_unknown'&&item.source!=='followup';
export const closableItems=(items:ReviewItem[])=>items.filter(closable);
const sources:Record<string,string>={agent:'模型请求',research:'市场研究'};
export const sourceName=(value:string)=>sources[value]||'原记录';
export const kindName=(item:ReviewItem)=>item.kind==='unknown'?'结果未知':'未完成';
