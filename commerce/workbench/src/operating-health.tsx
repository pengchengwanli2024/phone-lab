import {useEffect,useRef,useState} from 'react';
import {api,errorText} from './api';
import {Badge,Button,Empty,ErrorNotice,Panel} from './ui';
import {checkAction,healthStatus,healthSummary,sortedChecks,type Health} from './operating-health-state';

/** Can the platform keep running unattended? Local facts only; the one write here toggles the daily database backup. */
export function OperatingHealthPanel({active=true,navigate}:{active?:boolean;navigate?:(tab:string)=>void}) {
  const [data,setData]=useState<Health|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[busy,setBusy]=useState(false);
  const version=useRef(0),alive=useRef(true);
  async function load() {
    const read=++version.current;setLoading(true);
    try{const value=await api<Health>('commerce_operating_health_get');if(alive.current&&read===version.current){setData(value);setError('');}}
    // A failed read must not look like a healthy platform.
    catch(failure){if(alive.current&&read===version.current){setData(null);setError(errorText(failure));}}
    finally{if(alive.current&&read===version.current)setLoading(false);}
  }
  useEffect(()=>{alive.current=true;if(active)void load();return ()=>{alive.current=false;version.current++;};},[active]);
  async function backup(next:boolean) {
    if(busy)return;setBusy(true);setError('');
    try{const value=await api<Health>('commerce_operating_health_configure',{auto_backup:next});if(alive.current)setData(value);}
    catch(failure){if(alive.current)setError(errorText(failure));}
    finally{if(alive.current)setBusy(false);}
  }
  if(!active)return null;
  const overall=data?healthStatus(data.status):null;
  return <Panel title="运行健康" action={<div className="r-actions">{overall?<Badge tone={overall.tone}>{overall.label}</Badge>:null}<Button onClick={()=>void load()} disabled={loading}>刷新</Button></div>}>
    <ErrorNotice>{error}</ErrorNotice>
    {!data?<Empty>{loading?'正在读取运行健康…':'运行健康未读到，请刷新。'}</Empty>:<>
      <p className="r-footnote">{healthSummary(data)}。这里只检查本机能否持续运行，不代表经营结果。</p>
      <ul className="r-oc-records">{sortedChecks(data.checks).map(check=>{const state=healthStatus(check.status),action=checkAction(check);return <li key={check.id}>
        <div className="r-oc-record-heading"><strong>{check.label}</strong><Badge tone={state.tone}>{state.label}</Badge></div>
        <p>{check.detail}</p>{action&&navigate?<Button onClick={()=>navigate(action.tab)}>{action.label}</Button>:null}
      </li>;})}</ul>
      <div className="r-oc-boundary"><span>{data.auto_backup?'每日自动备份已开启':'每日自动备份未开启'}：只备份数据库，保留最近 7 份自动备份，不含凭据、素材和知识，也不会删除手动备份。</span>
        <Button disabled={busy} onClick={()=>void backup(!data.auto_backup)}>{busy?'正在保存…':data.auto_backup?'关闭每日自动备份':'开启每日自动备份'}</Button></div>
    </>}
  </Panel>;
}
