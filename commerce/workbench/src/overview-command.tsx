import {useEffect,useRef,useState} from 'react';
import {api} from './api';
import {Icon} from './ui';
import type {LoopView} from './operating-loop-state';
import {commandItems,type HealthRead,type Read,type RuntimeRead} from './overview-command-state';

/** Faults and decisions are shown above the work queue; nothing renders when there is nothing to say. */
export function OverviewCommand({demo,active,navigate}:{demo:boolean;active:boolean;navigate:(tab:string)=>void}) {
  const [runtime,setRuntime]=useState<Read<RuntimeRead>>({state:'loading'}),[loop,setLoop]=useState<Read<LoopView>>({state:'loading'});
  const [health,setHealth]=useState<Read<HealthRead>>({state:'loading'});
  const version=useRef(0);
  useEffect(()=>{
    if(!active)return;
    const read=++version.current;setRuntime({state:'loading'});setLoop({state:'loading'});
    void api<RuntimeRead>('commerce_runtime_status').then(value=>{if(read===version.current)setRuntime({state:'ready',value});},()=>{if(read===version.current)setRuntime({state:'failed'});});
    void api<LoopView>('commerce_operating_loop_get').then(value=>{if(read===version.current)setLoop({state:'ready',value});},()=>{if(read===version.current)setLoop({state:'failed'});});
    // Optional detail: an older backend without this read simply shows no backup/disk line.
    setHealth({state:'loading'});void api<HealthRead>('commerce_operating_health_get').then(value=>{if(read===version.current)setHealth({state:'ready',value});},()=>{if(read===version.current)setHealth({state:'failed'});});
    return ()=>{version.current++;};
  },[demo,active]);
  const items=commandItems(runtime,loop,demo,health);
  if(!items.length)return null;
  return <ul className="r-overview-command" aria-label="需要先看的事项">{items.map(item=><li key={item.id} className={'is-'+item.tone}>
    <Icon name="info"/><span><strong>{item.title}</strong>{item.detail}</span>
    <button type="button" onClick={()=>navigate(item.target)}>{item.target==='operating-control'?'去处理':'查看状态'}<Icon name="chevronDown"/></button>
  </li>)}</ul>;
}
