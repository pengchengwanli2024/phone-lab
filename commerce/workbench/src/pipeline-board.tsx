import {useEffect,useRef,useState} from 'react';
import {api} from './api';
import type {ListingTarget} from './listing-observation';
import {readCasePipeline,targetDirectory,type CasePipeline,type TargetDirectory} from './overview-pipeline';
import {arrangeBoard,pipelineRequests,type BoardCard,type BoardProduct} from './pipeline-board-state';
import {skuText,platformName} from './store-display';
import {Badge,Button,Empty,ErrorNotice,Icon} from './ui';
import './pipeline-board.css';

/** Bounded so one visit never fans out into an unbounded number of stage reads. */
export const PIPELINE_READ_LIMIT=24;
const DIRECTORY_PAGES=4;
type DirectoryPage={items?:{target?:ListingTarget}[];next_offset?:number|null};

async function readDirectory(demo:boolean):Promise<TargetDirectory> {
  const items:NonNullable<DirectoryPage['items']>=[];let offset:number|null=0,next:number|null|undefined=null;
  for(let page=0;page<DIRECTORY_PAGES&&offset!==null;page++){
    const value:DirectoryPage=await api<DirectoryPage>('commerce_listing_directory',{demo,offset,limit:25});
    items.push(...(value.items||[]));next=value.next_offset;offset=typeof next==='number'?next:null;
  }
  return targetDirectory({items,next_offset:offset===null?null:offset});
}

/** Read-only product pipeline: one card per product, in the stage that currently holds it. */
export function PipelineBoard({demo,active,onProduct,onListing,navigate}:{demo:boolean;active:boolean;onProduct:(caseId:string,section?:string)=>void;onListing:(target:ListingTarget)=>void;navigate:(tab:string)=>void}) {
  const [products,setProducts]=useState<BoardProduct[]|null>(null),[directory,setDirectory]=useState<TargetDirectory|null>(null);
  const [pipelines,setPipelines]=useState<Record<string,CasePipeline>>({}),[errors,setErrors]=useState<string[]>([]);
  const [loading,setLoading]=useState(true),[stagesLoading,setStagesLoading]=useState(false),[query,setQuery]=useState(''),[view,setView]=useState<'board'|'list'>('board');
  const version=useRef(0);
  async function load(){
    const revision=++version.current;setLoading(true);setPipelines({});
    const [catalog,plans]=await Promise.allSettled([api<{items:BoardProduct[]}>('commerce_catalog_list',{kind:'all'}),readDirectory(demo)]);
    if(revision!==version.current)return;
    const list=catalog.status==='fulfilled'?catalog.value.items||[]:null,dir=plans.status==='fulfilled'?plans.value:null;
    setProducts(list);setDirectory(dir);setErrors([...(list?[]:['商品目录']),...(dir?[]:['上架方案目录'])]);setLoading(false);
    if(!list||!dir)return;
    const ids=pipelineRequests(list,dir,demo,PIPELINE_READ_LIMIT);if(!ids.length)return;
    setStagesLoading(true);
    const read=await Promise.all(ids.map(id=>readCasePipeline(api,id,dir)));
    if(revision!==version.current)return;
    setPipelines(Object.fromEntries(ids.map((id,index)=>[id,read[index]])));setStagesLoading(false);
  }
  useEffect(()=>{if(active)void load();return()=>{version.current++;};},[demo,active]);
  const board=products?arrangeBoard(products,directory,stagesLoading?{}:pipelines,demo,query):null;
  function open(card:BoardCard){onProduct(card.caseId);}
  function next(card:BoardCard){const step=card.step;if(!step)return open(card);if(step.kind==='listing'&&card.target)onListing(card.target);else onProduct(card.caseId,step.section);}
  const cardView=(card:BoardCard)=><li key={card.product.id} className="r-pipeline-card">
    <button type="button" className="r-pipeline-open" onClick={()=>open(card)}>
      <strong>{card.product.name}</strong>
      <small>{[platformName(card.product.platform),card.product.market,card.product.store_identity?.label,skuText(card.product.sku)].filter(Boolean).join(' · ')}</small>
    </button>
    {card.stage&&<p className="r-pipeline-stage"><Badge tone={card.column==='prepared'?'success':'blue'}>{card.stage}</Badge></p>}
    {card.blocker&&<p className="r-pipeline-blocker"><span>挡住它的</span>{card.blocker}</p>}
    {card.note&&<p className="r-pipeline-note">{card.note}</p>}
    <div className="r-pipeline-meta">
      {card.scopes>1&&<details><summary>{card.scopes} 个履约范围条目已合并</summary><ul>{card.product.case_ids.map(id=><li key={id}><button type="button" className="r-dashboard-text-link" onClick={()=>onProduct(id)}>工作项 #{id.slice(0,8)}</button></li>)}</ul></details>}
      {card.others>0&&<span>另有 {card.others} 个店铺目标</span>}
      {card.step&&<Button onClick={()=>next(card)}>{card.step.label}</Button>}
    </div>
  </li>;
  return <div className="r-page r-pipeline-board" data-ai-page="pipeline" data-ai-context={JSON.stringify({filters:{query,view}})}>
    <div className="r-page-heading"><div><h1>商品管线{demo&&<small className="r-inline-source">示例数据</small>}</h1><p className="muted">每件商品一张卡，停在挡住它的那一个阶段。阶段为资料诊断，不代表已签收或已发布；本页只读取，不创建任务或调用模型。</p></div>
      <div className="r-actions"><Button icon="refresh" disabled={loading} onClick={()=>void load()}>刷新</Button></div></div>
    {errors.length>0&&<ErrorNotice>部分资料未读到：{errors.join('、')}。当前看板不完整，请刷新核对。</ErrorNotice>}
    <div className="r-pipeline-toolbar">
      <label className="ui-field">查找商品<input type="search" value={query} placeholder="名称或 SKU" onChange={event=>setQuery(event.target.value)}/></label>
      <div className="r-tabs" role="group" aria-label="显示方式">{([['board','看板'],['list','列表']] as const).map(([key,label])=><button key={key} type="button" aria-pressed={view===key} onClick={()=>setView(key)}>{label}</button>)}</div>
    </div>
    {loading?<Empty>正在读取商品与上架方案…</Empty>:!board?<Empty>商品目录未读到，请刷新。</Empty>:!board.total?<Empty>{query?'没有匹配的商品。':'当前模式下还没有商品。'}<br/><Button onClick={()=>navigate('pilots')}>查看商品候选</Button></Empty>:<>
      <p className="r-pipeline-summary" role="status">{board.total} 件商品{board.merged>0?` · 已合并 ${board.merged} 个同商品履约范围条目`:''}{stagesLoading?' · 正在读取阶段…':''}</p>
      {view==='board'?<div className="r-pipeline-columns">{board.columns.map(({column,cards})=><section key={column.id} className="r-pipeline-column" aria-labelledby={'pipeline-'+column.id}>
        <header><h2 id={'pipeline-'+column.id}>{column.label}</h2><Badge>{cards.length}</Badge></header><p className="muted">{column.hint}</p>
        <ul>{cards.map(cardView)}</ul></section>)}</div>
      :<table className="ui-table r-pipeline-table"><thead><tr><th>商品</th><th>阶段</th><th>挡住它的</th><th>下一步</th></tr></thead><tbody>{board.columns.flatMap(({column,cards})=>cards.map(card=><tr key={card.product.id}>
        <td><button type="button" className="r-dashboard-text-link" onClick={()=>open(card)}>{card.product.name}</button><small>{[platformName(card.product.platform),card.product.market,skuText(card.product.sku),card.scopes>1?card.scopes+' 个条目已合并':''].filter(Boolean).join(' · ')}</small></td>
        <td>{column.label}</td><td>{card.blocker||card.note||'—'}</td><td>{card.step?<Button onClick={()=>next(card)}>{card.step.label}</Button>:'—'}</td></tr>))}</tbody></table>}
    </>}
  </div>;
}
