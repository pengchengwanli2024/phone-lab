import { useEffect, useRef, useState } from 'react';
import { api, errorText, newKey } from './api';
import { Badge, Button, Dialog, Empty, ErrorNotice } from './ui';
import { TaskTimeline } from './task-timeline';
import { dueAt, localTimeInput, originalFollowupAction, type Followup, type FollowupAction, type FollowupChoice } from './followup-state';

const kinds = { attention: '事项版本', task_result: '任务结果', public_source: '公开来源快照' };
const states = { scheduled: '等待复查', checked: '已有检查回执', cancelled: '已取消复查', acknowledged: '已查看回执' };
const conditions: Record<string,string> = { ready:'发现新结果', unchanged:'尚未发现变化', changed:'原事项已有变化', scope_changed:'原工作范围已变化', outcome_unknown:'原任务结果仍未知', needs_attention:'原记录或回执需要核对', unavailable:'本机来源未读到' };
const key = (choice: FollowupChoice) => choice.target.kind + ':' + choice.target.ref;
const time = (value: string) => new Date(value).toLocaleString('zh-CN');

export function Followups({ demo, followupId, close, changed, openOriginal }: {
  demo: boolean; followupId: string; close: () => void; changed: () => void; openOriginal: (action: FollowupAction) => void;
}) {
  const [choices,setChoices] = useState<FollowupChoice[]>([]), [items,setItems] = useState<Followup[]>([]);
  const [selection,setSelection] = useState(''), [due,setDue] = useState(localTimeInput);
  const [record,setRecord] = useState<Followup|null>(null), [editing,setEditing] = useState<Followup|null>(null);
  const [cursor,setCursor] = useState<string|null>(null), [loading,setLoading] = useState(true), [busy,setBusy] = useState(false), [error,setError] = useState('');
  const generation = useRef(0), detailGeneration = useRef(0), request = useRef<{ fingerprint:string; key:string }|null>(null);
  async function load(selected = record?.id) {
    const version = ++generation.current; detailGeneration.current++; setLoading(true); setError('');
    const replies = await Promise.allSettled([
      api<{targets:FollowupChoice[];complete:boolean;truncated?:boolean}>('commerce_followup_targets',{demo}),
      api<{items:Followup[];next_cursor:string|null}>('commerce_followup_list',{demo,limit:30}),
      selected ? api<Followup>('commerce_followup_get',{followup_id:selected}) : Promise.resolve(null),
    ]);
    if (version !== generation.current) return;
    const [targets,history,detail] = replies;
    setChoices(targets.status==='fulfilled'?targets.value.targets:[]);
    setItems(history.status==='fulfilled'?history.value.items:[]); setCursor(history.status==='fulfilled'?history.value.next_cursor:null);
    setRecord(detail.status==='fulfilled'&&detail.value?.demo===demo?detail.value:null);
    if (replies.some(value=>value.status==='rejected')) setError('部分复查资料未读到，请刷新核对。');
    else if (targets.status==='fulfilled'&&targets.value.truncated) setError('当前模式仅列出最近100个未结束任务，可预约列表不完整。');
    else if (targets.status==='fulfilled'&&!targets.value.complete) setError('部分原事项未能读取，当前可预约列表不完整。');
    setLoading(false);
  }
  useEffect(()=>{setRecord(null);setEditing(null);setSelection('');void load(followupId||undefined);return()=>{generation.current++;detailGeneration.current++;};},[demo,followupId]);
  async function select(id:string) {
    const version = generation.current, detail = ++detailGeneration.current; setError('');
    try { const value=await api<Followup>('commerce_followup_get',{followup_id:id}); if(version===generation.current&&detail===detailGeneration.current){if(value.demo!==demo)throw Error('followup_source_changed');setRecord(value);} }
    catch(failure){if(version===generation.current&&detail===detailGeneration.current)setError(errorText(failure));}
  }
  async function returnOriginal(value:Followup) {
    if(busy)return;const version=generation.current;detailGeneration.current++;setBusy(true);setError('');
    try {
      const current=await api<Followup>('commerce_followup_get',{followup_id:value.id});
      if(version!==generation.current)return;
      if(current.demo!==demo)throw Error('followup_source_changed');
      setRecord(current);const action=originalFollowupAction(current.current_action);
      if(!current.scope_current||!action){setError('原工作入口已有变化，请核对当前资料。');return;}
      close();openOriginal(action);
    } catch(failure){if(version===generation.current)setError(errorText(failure));}
    finally{setBusy(false);}
  }
  async function more() {
    if(!cursor||busy)return;const version=generation.current;setBusy(true);
    try { const page=await api<{items:Followup[];next_cursor:string|null}>('commerce_followup_list',{demo,limit:30,cursor});if(version===generation.current){setItems(previous=>[...new Map([...previous,...page.items].map(value=>[value.id,value])).values()]);setCursor(page.next_cursor);} }
    catch(failure){if(version===generation.current)setError(errorText(failure));}finally{if(version===generation.current)setBusy(false);}
  }
  async function save() {
    if(busy)return;setBusy(true);setError('');const version=generation.current;
    try {
      const due_at=dueAt(due);let value:Followup;
      if(editing)value=await api('commerce_followup_reschedule',{followup_id:editing.id,expected_revision:editing.revision,due_at});
      else {
        const choice=choices.find(value=>key(value)===selection);if(!choice)throw Error('invalid_followup_target');
        const args={target:choice.target,due_at},fingerprint=JSON.stringify(args);
        if(request.current?.fingerprint!==fingerprint)request.current={fingerprint,key:newKey()};
        value=await api('commerce_followup_create',{...args,idempotency_key:request.current.key});
      }
      if(version!==generation.current)return;
      request.current=null;setEditing(null);await load(value.id);changed();
    } catch(failure){if(version===generation.current)setError(errorText(failure));}
    finally{setBusy(false);}
  }
  async function mutate(value:Followup, action:'cancel'|'ack') {
    if(busy)return;const version=generation.current;setBusy(true);setError('');
    try { const current=await api<Followup>('commerce_followup_'+action,{followup_id:value.id,expected_revision:value.revision,...(action==='ack'&&value.receipt_group?{group_sha256:value.receipt_group.sha256}:{})});if(version===generation.current){if(editing?.id===value.id)setEditing(null);await load(current.id);changed();} }
    catch(failure){if(version===generation.current)setError(errorText(failure));}finally{setBusy(false);}
  }
  const original=originalFollowupAction(record?.current_action);
  return <Dialog title="复查计划" close={close}><ErrorNotice>{error}</ErrorNotice>
    <p className="r-footnote">每次预约只检查本机已保存的记录一次，不执行原任务。时间按本机时区显示。</p>
    <form onSubmit={event=>{event.preventDefault();void save();}}>
      {editing?<p>改期：{editing.label}</p>:<label className="ui-field">复查内容<select value={selection} disabled={busy||loading} onChange={event=>setSelection(event.target.value)}><option value="">请选择本次复查内容</option>{choices.map(choice=><option key={key(choice)} value={key(choice)}>{kinds[choice.target.kind]} · {choice.label}</option>)}</select></label>}
      <label className="ui-field">复查时间<input type="datetime-local" required value={due} disabled={busy} onChange={event=>setDue(event.target.value)}/></label>
      <div className="r-form-actions"><Button type="submit" primary disabled={busy||loading||(!editing&&!selection)}>{busy?'正在保存…':editing?'保存新时间':'预约一次复查'}</Button>{editing&&<Button disabled={busy} onClick={()=>{setEditing(null);setDue(localTimeInput());}}>取消改期</Button>}<Button disabled={busy||loading} onClick={()=>void load()}>刷新计划</Button></div>
    </form>
    {record&&<section className="card"><h3>{record.label}</h3><Badge>{states[record.state]}</Badge><p>预约时间：{time(record.due_at)}</p>{record.receipt&&<><p>{conditions[record.receipt.condition]||'检查结果待核对'} · {time(record.receipt.checked_at)}</p><p className="r-footnote">检查回执不代表原业务已完成或来源事实已核实。</p></>}{!record.scope_current&&<p role="status">原工作范围已变化，请核对当前资料。</p>}<div className="r-form-actions">{original&&<Button disabled={busy} onClick={()=>void returnOriginal(record)}>{original.type==='tasks'?'查看共享任务':'返回原工作'}</Button>}{record.state==='scheduled'&&<><Button disabled={busy} onClick={()=>{setEditing(record);setDue(localTimeInput(new Date(record.due_at)));}}>改期</Button><Button disabled={busy} onClick={()=>void mutate(record,'cancel')}>取消本次复查</Button></>}{record.state==='checked'&&<Button disabled={busy} onClick={()=>void mutate(record,'ack')}>{record.receipt_group&&record.receipt_group.count>1?'标记'+record.receipt_group.count+'条已查看':'标记已查看'}</Button>}</div>{record.receipt_group&&record.receipt_group.count>1&&<p className="r-footnote">同一对象已合并 {record.receipt_group.count} 次复查，原始回执均保留。最新结果：{conditions[record.receipt_group.latest.condition]||'待核对'} · {time(record.receipt_group.latest.checked_at)}</p>}<TaskTimeline key={record.id} kind="followup" id={record.id}/></section>}
    <h3>已保存的预约与回执</h3>{loading?<Empty>正在读取复查计划…</Empty>:items.length?<div className="r-notices">{items.map(value=><button className="r-notice" key={value.id} disabled={busy} onClick={()=>void select(value.id)}><div><span className="r-notice-title">{value.label}</span><p>{time(value.due_at)}</p></div><Badge>{states[value.state]}</Badge></button>)}</div>:<Empty>{error?'当前复查记录未完整读到。':'当前范围没有已保存的复查计划。'}</Empty>}{cursor&&<Button disabled={busy} onClick={()=>void more()}>加载更多复查</Button>}
  </Dialog>;
}
