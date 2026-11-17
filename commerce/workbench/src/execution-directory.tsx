import {useEffect,useRef,useState} from 'react';
import {api,errorText} from './api';
import {Button,Empty,ErrorNotice,Panel,Status} from './ui';

type Origin='agent'|'skills'|'assistant-team';
interface RecordItem {key:string;id:string;title:string|null;status:string|null;at?:string|number|null;origin:Origin;version?:number|null}
interface HistoryPage {items:RecordItem[];next_cursor:string|null}
interface Filters {query:string;origin:string;status:string}
const names:Record<Origin,string>={agent:'模型分析',skills:'自建能力','assistant-team':'团队讨论'};
const states=['queued','running','cancel_requested','cancelling','awaiting_input','awaiting_review','pending_review','partial','completed','succeeded','success','failed','unknown','interrupted','cancelled','blocked'];
export function executionTime(value?:string|number|null) {
  if(value==null||value==='')return '时间未记录';
  const date=new Date(typeof value==='number'&&value<1e12?value*1000:value);
  return Number.isFinite(date.getTime())?date.toLocaleString('zh-CN'):'时间未记录';
}
export function executionHistoryError(error:unknown) {
  const key=error instanceof Error?error.message:'';
  if(key==='execution_history_invalid_cursor')return '分页依据已失效或与筛选不一致，请从首页重新读取。';
  if(key==='execution_history_invalid_query')return '筛选格式不正确，请核对关键词与原状态代码。';
  if(key==='execution_history_source_unavailable')return '执行历史暂未完整读到，请稍后重试；当前记录与筛选已保留。';
  return errorText(error);
}
export function restoreExecutionFocus(trigger:HTMLElement,fallback:HTMLElement|null) {
  const doc=trigger.ownerDocument,current=doc.activeElement;
  if(current!==trigger&&current!==doc.body&&current!==doc.documentElement)return;
  const target=[trigger,fallback].find(element=>element?.isConnected&&!element.matches(':disabled')&&element.getClientRects().length&&doc.defaultView?.getComputedStyle(element).visibility!=='hidden');
  target?.focus({preventScroll:true});
}
export function ExecutionDirectory({active,navigate}:{active:boolean;navigate:(page:string,id?:string)=>void}) {
  const [data,setData]=useState<HistoryPage|null>(null),[query,setQuery]=useState(''),[origin,setOrigin]=useState('all'),[status,setStatus]=useState('all'),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [applied,setApplied]=useState<Filters>({query:'',origin:'all',status:'all'}),[cursors,setCursors]=useState<(string|undefined)[]>([undefined]);
  const epoch=useRef(0);
  const paginationStatus=useRef<HTMLSpanElement>(null),returnFocus=useRef<{generation:number;trigger:HTMLElement}|null>(null);
  async function load(filters:Filters=applied,trail:(string|undefined)[]=cursors,trigger?:HTMLElement|null){
    const current=++epoch.current;setBusy(true);setError('');
    returnFocus.current=trigger?{generation:current,trigger}:null;
    try{
      const value=await api<HistoryPage>('commerce_execution_history',{...filters,limit:30,...(trail.at(-1)?{cursor:trail.at(-1)}:{})});
      if(current!==epoch.current)return;
      setData(value);setApplied(filters);setCursors(trail);
    }catch(reason){if(current===epoch.current)setError(executionHistoryError(reason));}
    finally{if(current===epoch.current)setBusy(false);}
  }
  useEffect(()=>{if(active)void load();return()=>{epoch.current++;};},[active]);
  useEffect(()=>{
    const pending=returnFocus.current;
    if(busy||!active||!pending||pending.generation!==epoch.current)return;
    returnFocus.current=null;
    restoreExecutionFocus(pending.trigger,paginationStatus.current);
  },[busy,active,data,error,cursors]);
  const dirty=query!==applied.query||origin!==applied.origin||status!==applied.status;
  return <Panel title="执行记录" action={<Button id="execution-history-refresh" disabled={busy} onClick={event=>void load(applied,cursors,event?.currentTarget)}>刷新记录</Button>}>
    <ErrorNotice>{error}</ErrorNotice><form onSubmit={event=>{event.preventDefault();const trigger=(event.nativeEvent as SubmitEvent|undefined)?.submitter||event.currentTarget?.ownerDocument.activeElement;void load({query,origin,status},[undefined],trigger as HTMLElement|null);}}><div className="r-list-filters"><label className="ui-field">查找执行<input type="search" maxLength={200} value={query} onChange={e=>setQuery(e.target.value)} placeholder="问题、标题或完整记录 ID"/></label><label className="ui-field">来源<select value={origin} onChange={e=>setOrigin(e.target.value)}><option value="all">全部来源</option>{Object.entries(names).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label><label className="ui-field">原状态<input list="execution-original-statuses" maxLength={64} value={status==='all'?'':status} onChange={e=>setStatus(e.target.value||'all')} placeholder="全部状态，或输入原状态代码"/><datalist id="execution-original-statuses">{states.map(code=><option key={code} value={code}>{window.CommerceUI.status(code).label} · {code}</option>)}</datalist></label><Button id="execution-history-apply" type="submit" disabled={busy}>应用筛选</Button></div></form>
    {dirty&&<p className="r-footnote" role="status">新筛选尚未应用，当前保留上次读取结果。</p>}
    <div aria-busy={busy}>{data?.items.length?<div className="r-table-wrap r-task-ledger"><table className="data-table"><thead><tr><th scope="col">事项</th><th scope="col">来源与时间</th><th scope="col">原状态</th><th scope="col">操作</th></tr></thead><tbody>{data.items.map(row=><tr key={row.key}><td><strong className="r-task-title" title={row.title||undefined}>{row.title||'标题未记录'}</strong><small className="r-task-id" title={row.key}>{row.id.slice(-12)}</small></td><td className="r-execution-origin">{names[row.origin]}{row.version!=null&&` · v${row.version}`}<small className="r-task-id r-execution-time">{executionTime(row.at)}</small></td><td>{row.status?<><Status value={row.status}/><small className="r-task-id">{row.status}</small></>:'状态未记录'}</td><td><Button onClick={()=>navigate(row.origin,row.id)}>查看原记录</Button></td></tr>)}</tbody></table></div>:<Empty>{busy?'正在读取原记录…':error?'执行历史尚未读到，请重试。':'当前筛选没有执行记录。'}</Empty>}</div>
    {(data||error)&&<div className="r-form-actions"><Button id="execution-history-first" disabled={busy||cursors.length===1} onClick={event=>void load(applied,[undefined],event?.currentTarget)}>回到首页</Button><Button id="execution-history-previous" disabled={busy||cursors.length===1} onClick={event=>void load(applied,cursors.slice(0,-1),event?.currentTarget)}>上一页记录</Button><span id="execution-history-page" ref={paginationStatus} role="status" tabIndex={-1}>第 {cursors.length} 页{busy?' · 正在读取…':''}</span><Button id="execution-history-next" disabled={busy||!data?.next_cursor} onClick={event=>data?.next_cursor&&void load(applied,[...cursors,data.next_cursor],event?.currentTarget)}>下一页记录</Button></div>}
  </Panel>;
}
