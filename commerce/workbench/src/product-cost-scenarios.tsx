import {useEffect,useRef,useState} from 'react';
import {api,errorText,newKey} from './api';
import {labels} from './cost-input';
import {Badge,Button,Empty,ErrorNotice,Money,Panel} from './ui';
import type {Calculation,Input} from './types';

export interface CostScenarioSnapshot {caseId:string;sourceSha:string;costRevision:number}
interface CostScenario {id:string;label:string;source_sha256:string;cost_revision:number;sha256:string;stale:boolean;input:Input;result:Calculation}
interface CostScenarioList {case_id:string;items:CostScenario[]}
interface Props {snapshot:CostScenarioSnapshot;disabled:boolean;onEditState?:(dirty:boolean)=>void;onWriting?:(writing:boolean)=>void}

function scenarioError(failure:unknown){
  const code=failure instanceof Error?failure.message:'';
  if(code==='cost_scenario_label_required')return '请输入情景名称，最多80个字。';
  if(code==='cost_scenario_parameters_required'||code==='workspace_cost_checkpoint_required')return '请先保存并完成当前成本测算，再保存情景。';
  if(code==='workspace_quote_not_ready')return '报价依据已变化，请核对报价并重新测算后保存情景。';
  if(code==='workspace_currency_required')return '请先确认当前成本币种并重新测算，再保存情景。';
  if(code==='cost_scenario_integrity')return '情景记录完整性检查未通过，请核对原记录。';
  return errorText(failure);
}
function parameterValue(key:string,value:unknown){
  if(key.endsWith('_rate')&&typeof value==='number')return `${Number((value*100).toPrecision(12))}%`;
  return value==null?'待补充':String(value);
}

/** Saved alternatives are immutable; reading them never adopts their input. */
export function ProductCostScenarios({snapshot,disabled,onEditState,onWriting}:Props){
  const [label,setLabel]=useState(''),[rows,setRows]=useState<CostScenario[]|null>(null),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState<''|'read'|'save'>(''),[unknown,setUnknown]=useState(false);
  const epoch=useRef(0),intent=useRef<{fingerprint:string;key:string}|null>(null),live=useRef(true),current=useRef(snapshot),callbacks=useRef({onEditState,onWriting});
  current.current=snapshot;callbacks.current={onEditState,onWriting};
  useEffect(()=>{callbacks.current.onEditState?.(!!label.trim()||busy==='save'||unknown);callbacks.current.onWriting?.(busy==='save');},[label,busy,unknown]);
  useEffect(()=>{live.current=true;return()=>{live.current=false;epoch.current++;callbacks.current.onEditState?.(false);callbacks.current.onWriting?.(false);};},[]);
  const sameSnapshot=(start:CostScenarioSnapshot)=>start.caseId===current.current.caseId&&start.sourceSha===current.current.sourceSha&&start.costRevision===current.current.costRevision;
  async function read(){
    if(busy)return;const start=snapshot,request=++epoch.current;setBusy('read');setError('');
    try{const value=await api<CostScenarioList>('commerce_cost_scenarios_get',{case_id:start.caseId});if(!live.current||request!==epoch.current||start.caseId!==current.current.caseId)return;if(value.case_id!==start.caseId)throw Error('workspace_source_changed');setRows(value.items);if(unknown){setUnknown(false);setNotice('已读取保存记录。核对后可明确重试原保存请求，不会自动重发。');}}
    catch(failure){if(live.current&&request===epoch.current)setError(scenarioError(failure));}
    finally{if(live.current&&request===epoch.current)setBusy('');}
  }
  async function save(){
    if(busy||disabled||unknown)return;const name=label.trim();if(!name||name.length>80){setError('请输入情景名称，最多80个字。');return;}
    const start=snapshot,fingerprint=JSON.stringify([start.caseId,start.sourceSha,start.costRevision,name]);
    if(!intent.current||intent.current.fingerprint!==fingerprint)intent.current={fingerprint,key:newKey()};
    const request=++epoch.current;setBusy('save');setError('');setNotice('');
    try{const value=await api<CostScenarioList>('commerce_cost_scenarios_save',{case_id:start.caseId,label:name,expected_source_sha256:start.sourceSha,expected_revision:start.costRevision,idempotency_key:intent.current.key});
      if(!live.current||request!==epoch.current||!sameSnapshot(start))return;if(value.case_id!==start.caseId)throw Error('workspace_source_changed');setRows(value.items);setLabel('');intent.current=null;setUnknown(false);setNotice('成本情景已保存，当前参数与报价保持。');
    }catch(failure){if(live.current&&request===epoch.current){setError(scenarioError(failure));if(failure instanceof TypeError||failure instanceof Error&&failure.message==='request_outcome_unknown'){setUnknown(true);setNotice('保存回执尚未确认。请先读取已保存情景核对。');}}}
    finally{if(live.current&&request===epoch.current)setBusy('');}
  }
  return <details className="r-product-cost-scenarios"><summary>保存与比较成本情景</summary><Panel title="成本情景" action={<Button disabled={!!busy} onClick={()=>void read()}>读取已保存情景</Button>}>
    <ErrorNotice>{error}</ErrorNotice><div className="r-cost-fields"><label className="ui-field">情景名称<input maxLength={80} value={label} disabled={!!busy||unknown} placeholder="例如：当前报价、调整售价" onChange={e=>{setLabel(e.target.value);setError('');setNotice('');}}/></label></div>
    <div className="r-form-actions"><Button primary disabled={disabled||!!busy||unknown||!label.trim()} onClick={()=>void save()}>保存当前测算为情景</Button></div>{notice&&<p role="status">{notice}</p>}
    {rows===null?null:rows.length?<><div className="r-table-wrap"><table className="data-table"><thead><tr><th>情景与依据</th><th>售价</th><th>单件总成本</th><th>单件贡献估算</th><th>贡献率</th></tr></thead><tbody>{rows.map(row=><tr key={row.id}><td><strong>{row.label}</strong><Badge tone={row.stale||row.source_sha256!==snapshot.sourceSha?'warning':'gray'}>{row.stale||row.source_sha256!==snapshot.sourceSha?'依据已变化':'当前依据'}</Badge><details><summary>参数与版本</summary><p>成本修订 {row.cost_revision}</p><dl>{Object.entries(row.input).map(([key,value])=><div key={key}><dt>{labels[key]||key}</dt><dd>{parameterValue(key,value)}</dd></div>)}</dl><small>{row.sha256}</small></details></td><td><Money value={row.result.price} currency={row.result.currency}/></td><td><Money value={row.result.total_cost} currency={row.result.currency}/></td><td><Money value={row.result.contribution} currency={row.result.currency}/></td><td>{row.result.contribution_rate==null?'待补充':`${Number((row.result.contribution_rate*100).toFixed(2))}%`}</td></tr>)}</tbody></table></div><p className="r-footnote">仅同币种情景可直接比较。历史结果不替换当前输入，最多读取最近20项。</p></>:<Empty>尚无已保存情景。</Empty>}
  </Panel></details>;
}
