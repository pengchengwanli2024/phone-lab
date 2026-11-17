import {useEffect,useRef,useState} from 'react';
import {api,errorText} from './api';
import {Badge,Button,Empty,ErrorNotice,Panel} from './ui';
import type {ListingTarget} from './listing-observation';
import {pipelineDestination,pipelineKey,pipelineMatches,pipelineMissingText,pipelineListingMissing,type OperatingGoal,type OperatingSnapshot,type OperatingStage} from './operating-guide-state';

const statusLabels:Record<string,string>={prepared:'原资料已准备',needs_evidence:'待补依据',needs_calculation:'待更新测算',needs_target_evidence:'需当前目标资料',needs_fulfillment_evidence:'待履约回执',awaiting_review:'待审阅',awaiting_approval:'待批准',stale:'依据已变化',unknown:'结果待核对',checking:'核查中',submitting:'提交中',accepted:'平台已受理',reading:'回读中',read_failed:'回读失败',failed:'执行失败',cancelled:'已取消',failed_before_dispatch:'尚未发出',interrupted_before_dispatch:'发出前中断',queued:'已排队',running:'执行中',blocked:'待解决阻塞'};
export function OperatingGuide({target,version,revision,dirty=false,active,goal='launch',checkLabels={},onGap,onProduct,onListing,onPolicy}:{target:ListingTarget;version:string;revision?:number;dirty?:boolean;active:boolean;goal?:OperatingGoal;checkLabels?:Record<string,string>;onGap?:(id:string)=>void;onProduct?:(id:string,section?:string)=>void;onListing?:(target:ListingTarget)=>void;onPolicy?:()=>void}){
  const key=pipelineKey(target,goal),binding=JSON.stringify([key,version,revision,dirty,active]);
  const [result,setResult]=useState<{binding:string;data:OperatingSnapshot}|null>(null),[error,setError]=useState<{binding:string;text:string}|null>(null),[loading,setLoading]=useState('');
  const epoch=useRef(0),current=useRef(binding);current.current=binding;
  async function load(){
    if(!active||dirty||!key)return;
    const generation=++epoch.current,expected=binding;setLoading(expected);setError(null);setResult(null);
    try{
      const value=await api<OperatingSnapshot>('commerce_operating_pipeline_get',{...target,goal});
      if(generation!==epoch.current||current.current!==expected)return;
      if(!pipelineMatches(value,target,goal))throw Error('operating_scope_mismatch');
      if(!pipelineMatches(value,target,goal,goal==='launch'?{preview:version}:{revision}))throw Error('operating_listing_changed');
      setResult({binding:expected,data:value});
    }catch(e){if(generation===epoch.current&&current.current===expected)setError({binding:expected,text:e instanceof Error&&e.message==='operating_listing_changed'?'经营依据与当前保存方案版本未能匹配，请读取当前店铺方案后再核对。':e instanceof Error&&e.message==='unknown_tool'?'当前后台尚未加载经营缺项读取，请核对运行版本。':e instanceof Error&&e.message==='operating_scope_mismatch'?'返回资料与当前商品或店铺范围不一致，请重新读取。':errorText(e)});}
    finally{if(generation===epoch.current)setLoading('');}
  }
  useEffect(()=>{setResult(null);setError(null);setLoading('');if(active&&!dirty&&key)void load();return()=>{epoch.current++;};},[binding]);
  const data=result?.binding===binding?result.data:null,busy=loading===binding,stages=data?.stages.filter(s=>s.required_for_goal)||[];
  function open(id:string){const route=pipelineDestination(id);if(!route||dirty||!data)return;if(id==='policy'&&onPolicy)onPolicy();else if(route.kind==='product')onProduct?.(target.case_id,route.section);else if(onListing)onListing(target);else{const node=document.getElementById(route.section);node?.scrollIntoView({block:'start'});node?.focus();}}
  function missingItem(stage:OperatingStage,item:string){
    if(stage.id!=='listing')return pipelineMissingText(stage.name,item);
    const {label,checkId}=pipelineListingMissing(item,checkLabels);
    return checkId&&onGap?<Button onClick={()=>{if(active&&!dirty&&data)onGap(checkId);}}>补充：{label}</Button>:label;
  }
  return <Panel title={goal==='launch'?'商品到发布：当前缺项':'日常经营：当前缺项'} action={<Button disabled={!active||dirty||!key||busy} onClick={()=>void load()}>重新核对经营缺项</Button>}>
    {dirty?<p role="status">当前方案有未保存修改，保存后核对同一版本。</p>:!key?<Empty>先确定商品、店铺与市场，再读取经营缺项。</Empty>:<>
      <ErrorNotice>{error?.binding===binding?error.text:''}</ErrorNotice>
      {!data?<Empty>{busy?'正在读取当前商品与店铺的经营依据…':'经营依据尚未读回。'}</Empty>:<>
        <p className="r-footnote">{target.platform} · {target.store_ref} · {target.market}；以下为原资料诊断，签收、执行与平台结果分别核对。</p>
        {(data.unresolved_release_count>0||!data.release_history_complete)&&<p role="status">仍有未决申请或申请历史未核全。先核对原申请回执，不能用新草稿覆盖未知结果。</p>}
        <ul className="r-operation-list">{stages.map(stage=>{const route=pipelineDestination(stage.id);return <li key={stage.id}><div><strong>{stage.name}</strong><p><Badge>{statusLabels[stage.acceptance_status]||'待核对'}</Badge>{stage.capability_status==='missing'&&' · 处理能力待接入'}</p>{stage.missing.length>0&&<div>{stage.missing.slice(0,2).map((text,i)=><p key={i}>{missingItem(stage,text)}</p>)}</div>}{(stage.missing.length>2||stage.limitations.length>0)&&<details><summary>查看完整缺项与依据限制</summary>{stage.missing.slice(2).map((text,i)=><p key={'m'+i}>{missingItem(stage,text)}</p>)}{stage.limitations.map((text,i)=><p key={'l'+i}>{text}</p>)}</details>}</div>{route&&(route.kind==='listing'||onProduct)&&<Button onClick={()=>open(stage.id)}>{route.label}</Button>}</li>})}</ul>
        {goal==='operate'&&onListing&&<Button onClick={()=>onListing(target)}>核对同商品上架方案与回执</Button>}
      </>}
    </>}
  </Panel>;
}
