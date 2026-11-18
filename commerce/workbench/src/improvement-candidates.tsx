import {useEffect,useRef,useState} from 'react';
import {api,errorText} from './api';
import {Badge,Button,Empty,ErrorNotice,Panel} from './ui';
import {candidateSummary,domainName,fixName,handlingText,type Retrospect} from './improvement-candidates-state';

/** Recurring failures as improvement candidates. Reading creates no task, model call or change. */
export function ImprovementCandidates() {
  const [data,setData]=useState<Retrospect|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[days,setDays]=useState<7|30>(7);
  const generation=useRef(0);
  async function load(window:7|30) {
    const request=++generation.current;setLoading(true);
    try{const value=await api<Retrospect>('commerce_operating_retrospect_get',{window_days:window});if(request===generation.current){setData(value);setError('');}}
    catch(failure){if(request===generation.current){setData(null);setError(errorText(failure));}}
    finally{if(request===generation.current)setLoading(false);}
  }
  useEffect(()=>{void load(days);return ()=>{generation.current++;};},[days]);
  return <Panel title="改进候选" action={<div className="r-actions"><Button aria-pressed={days===7} disabled={loading} onClick={()=>setDays(7)}>近 7 天</Button><Button aria-pressed={days===30} disabled={loading} onClick={()=>setDays(30)}>近 30 天</Button></div>}>
    <ErrorNotice>{error}</ErrorNotice>
    {!data?<Empty>{loading?'正在统计重复出现的失败…':'改进候选未读到，请稍后再试。'}</Empty>:<>
      <p className="adoption-scope">{candidateSummary(data)}。这里只统计真实运行本机记录的失败，不含经营结果；候选不会自动应用，也不会自动创建任务。</p>
      {handlingText(data)?<p className="adoption-scope">{handlingText(data)}</p>:null}
      {data.candidates.length?<ul className="adoption-list">{data.candidates.map(item=><li className="adoption-item" key={item.id}>
        <div className="adoption-actions"><Badge>{domainName(item.domain)}</Badge><Badge tone="warning">{item.count} 次</Badge><Badge tone="blue">{fixName(item.fix_first)}</Badge>{item.engineering_feature?<Badge tone="green">已有工程配方</Badge>:null}</div>
        <p>{item.hint}</p><p className="adoption-scope">原因码 {item.error}{item.engineering_feature?' · 工程配方 '+item.engineering_feature:''}</p>
      </li>)}</ul>:null}
    </>}
  </Panel>;
}
