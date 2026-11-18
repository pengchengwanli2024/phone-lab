import { useState, type ReactNode } from 'react';
import type { CaseItem, OpsAlert, Product, Task } from './types';
import { Badge, Button, Empty, Icon, Status } from './ui';
import { InventoryStatistics, SalesTrend } from './operating-charts';
import { StatisticsDistribution, type Dashboard, type OrderSnapshot } from './overview-statistics';
import { coreStages, taskKind, salesPageContext, inventoryPageContext } from './overview-model';
import type { ListingTarget } from './listing-observation';
import { pipelineStep, type CasePipeline } from './overview-pipeline';
import { platformName, storeName } from './store-display';
import type { StoreScopeCatalog } from './store-scopes';

const PREVIEW=2, LIMIT=12;
/** Launch-path diagnosis for one saved store plan. Unread, absent and failed stay distinct from zero. */
function ProductPipeline({item,pipeline,navigate,onListing,onProduct,stores}:{stores?:StoreScopeCatalog;item:CaseItem;pipeline?:CasePipeline;navigate:(tab:string,id?:string)=>void;onListing?:(target:ListingTarget)=>void;onProduct?:(caseId:string,section?:string)=>void}) {
  if(!pipeline)return <div className="r-product-pipeline" role="status"><span>正在读取上架路径…</span></div>;
  if(pipeline.state==='failed')return <div className="r-product-pipeline" role="status"><span>上架路径未读到，不能判断当前缺项。</span><button className="r-dashboard-text-link" onClick={()=>navigate('listing',item.id)}>到上架准备核对<Icon name="chevronDown"/></button></div>;
  if(pipeline.state==='none')return <div className="r-product-pipeline"><span>{pipeline.incomplete?'方案目录未读全，暂不能确认是否已有店铺方案。':'尚未保存店铺上架方案。'}</span><button className="r-dashboard-text-link" onClick={()=>navigate('listing',item.id)}>{pipeline.incomplete?'到上架准备核对':'选择店铺并建立方案'}<Icon name="chevronDown"/></button></div>;
  const {summary,target,others}=pipeline,step=pipelineStep(pipeline);
  function open(){if(!step)return;if(step.kind==='product'&&onProduct)onProduct(item.id,step.section);else if(onListing)onListing(target);else navigate(step.kind==='product'?'workspace':'listing',item.id);}
  return <div className="r-product-pipeline">
    <span><strong>上架路径 {summary.prepared}/{summary.total} 项资料已准备</strong><small>{[platformName(target.platform),storeName(target,stores),target.market].join(' · ')}{others>0&&` · 另有 ${others} 个店铺方案`}</small></span>
    {summary.unresolved?<span className="r-product-pipeline-next"><Badge tone="warning">有未决申请</Badge><small>先核对原申请回执，不用新草稿覆盖。</small></span>:summary.next?<span className="r-product-pipeline-next"><Badge tone={['unknown','failed','read_failed','stale'].includes(summary.next.status)?'warning':'gray'}>{summary.next.label}</Badge><small title={summary.next.missing||undefined}>下一步：{summary.next.name}</small></span>:<span className="r-product-pipeline-next"><Badge tone="blue">待负责人审阅</Badge><small>资料诊断已齐，签收与发布另行确认。</small></span>}
    {step&&<button className="r-dashboard-text-link" onClick={open}>{step.label}<Icon name="chevronDown"/></button>}
  </div>;
}

export function DashboardPanel({title,icon,action,children,className=''}:{title:string;icon:string;action?:ReactNode;children:ReactNode;className?:string}) {
  return <section className={`card r-panel r-dashboard-panel ${className}`}><header><h2><Icon name={icon}/>{title}</h2>{action}</header>{children}</section>;
}
export function DashboardChart({dashboard,orders,demo,loading,navigate}:{dashboard?:Dashboard;orders?:OrderSnapshot;demo:boolean;loading:boolean;navigate:(tab:string)=>void}) {
  const [view,setView]=useState('amount');
  return <div className="r-dashboard-chart" data-ai-context={JSON.stringify(view!=='distribution'?salesPageContext(dashboard?.sales_summary,view==='units'?'units':'amount',demo):{section:'order-status',replace_filters:true,source:demo?'local':!orders||orders.data_source==='not_connected'?'unavailable':orders?.stale?'stale':'live',entity:{kind:'chart',id:'order-status'},filters:{platform:'all',store_id:'all',market:'all'},source_refs:{}})}>
    <DashboardPanel title="经营概览" icon="chart" action={<div className="r-chart-switch" role="group" aria-label="经营统计视图"><button aria-pressed={view==='amount'} onClick={()=>setView('amount')}>下单金额</button><button aria-pressed={view==='units'} onClick={()=>setView('units')}>下单件数</button><button aria-pressed={view==='distribution'} onClick={()=>setView('distribution')}>更多统计</button></div>}>
      <div hidden={view==='distribution'}>{demo?<div className="r-demo-chart-empty"><Icon name="chart"/><h3>当前示例未提供逐日趋势</h3><p>汇总指标与平台构成可供查看。</p><Button onClick={()=>setView('distribution')}>查看示例构成</Button></div>:<SalesTrend sales={dashboard?.sales_summary} loading={loading} metric={view==='units'?'units':'amount'} embedded/>}</div>
      <div hidden={view!=='distribution'}><StatisticsDistribution dashboard={dashboard} orders={orders} demo={demo} loading={loading} navigate={navigate}/></div>
    </DashboardPanel>
  </div>;
}
export function InventoryAndAlerts({dashboard,alerts,loading,demo,navigate}:{dashboard?:Dashboard;alerts?:OpsAlert[];loading:boolean;demo:boolean;navigate:(tab:string)=>void}) {
  const rows=(alerts||[]).filter(alert=>alert.status!=='resolved');
  return <div className="r-dashboard-stock" data-ai-context={JSON.stringify(inventoryPageContext(dashboard?.inventory,demo))}>
    <DashboardPanel title="库存统计" icon="box" action={<Button onClick={()=>navigate('alerts')}>{alerts?`${rows.length} 项经营提醒`:'提醒待读取'}</Button>}>
      {demo?<Empty>当前示例未提供履约方式库存快照。<Button onClick={()=>navigate('products')}>查看示例库存</Button></Empty>:<InventoryStatistics inventory={dashboard?.inventory} loading={loading} embedded/>}
      <div className="r-dashboard-card-footer"><span>按履约方式汇总，执行口径仍需核对。</span><button className="r-dashboard-text-link" onClick={()=>navigate('products')}>查看商品库存<Icon name="chevronDown"/></button></div>
    </DashboardPanel>
  </div>;
}

export function ProductProgress({stores,cases,details,pipelines={},all=false,showAll,collapse,loading,navigate,onListing,onProduct}:{stores?:StoreScopeCatalog;cases?:CaseItem[];details:Record<string,Product|null>;pipelines?:Record<string,CasePipeline>;all?:boolean;showAll?:()=>void;collapse?:()=>void;loading:boolean;navigate:(tab:string,id?:string)=>void;onListing?:(target:ListingTarget)=>void;onProduct?:(caseId:string,section?:string)=>void}) {
  const count=cases?.length||0,shown=all?LIMIT:PREVIEW;
  return <div className="r-dashboard-products"><DashboardPanel title="继续商品工作" icon="box" action={<button className="r-dashboard-text-link" onClick={()=>navigate('workspace')}>全部商品<Icon name="chevronDown"/></button>}>
    {loading?<Empty>正在读取商品工作…</Empty>:!cases?<Empty>商品工作项未读到，请刷新核对。</Empty>:cases.length?cases.slice(0,shown).map(item=><div className="r-product-entry" key={item.id}><button className="r-product-progress" onClick={()=>navigate('workspace',item.id)}>
      <span className="r-product-progress-name"><i><Icon name="box"/></i><span><strong>{item.name}</strong><small>{[item.platform==='ozon'?'Ozon':item.platform,item.market,item.candidate?'调研候选':'商品工作项'].filter(Boolean).join(' · ')}<span className="r-case-reference"> · #{item.id.slice(0,8)}</span></small><em>{!details[item.id]?(Object.hasOwn(details,item.id)?'阶段资料未读到':'正在读取阶段…'):'核心资料核对'}</em></span><Icon name="chevronDown"/></span>
      <ol className="r-stage-track" aria-label={item.name+'的核心资料核对'}>{coreStages(details[item.id]||undefined).map((stage,index,stages)=><li key={stage.id} className={`${stage.status==='PASS'?'is-passed':''} ${index>0&&stage.status==='PASS'&&stages[index-1].status==='PASS'?'is-linked':''}`} title={stage.detail+' · '+stage.label}><span className="r-stage-dot">{stage.status==='PASS'?<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 8 3 3 5-6"/></svg>:<span/>}</span><strong>{stage.name}</strong><small>{stage.label}</small></li>)}</ol>
    </button><ProductPipeline stores={stores} item={item} pipeline={pipelines[item.id]} navigate={navigate} onListing={onListing} onProduct={onProduct}/></div>):<Empty>暂无当前模式的商品工作项。<br/><Button onClick={()=>navigate('pilots')}>查看已有候选</Button></Empty>}
    {count>PREVIEW&&showAll&&<div className="r-dashboard-priority-footer">{all?<><button className="r-dashboard-text-link" onClick={collapse}>收起列表<Icon name="chevronDown"/></button>{count>LIMIT&&<button className="r-dashboard-text-link" onClick={()=>navigate('workspace')}>其余 {count-LIMIT} 项在商品工作区<Icon name="chevronDown"/></button>}</>:<button className="r-dashboard-text-link" onClick={showAll}>查看全部 {count} 项商品<Icon name="chevronDown"/></button>}</div>}
    <div className="r-dashboard-card-footer"><span>阶段与上架路径均为资料诊断，不代表已签收或已发布。</span><div><button className="r-dashboard-text-link" onClick={()=>navigate('operations')}>通用成本测算</button><button className="r-dashboard-text-link" onClick={()=>navigate('research')}>调研资料</button></div></div>
  </DashboardPanel></div>;
}
export interface OperatingHint {id:string;title:string;detail:string;icon:string;action:()=>void}
export function OperatingHints({items}:{items:OperatingHint[]}) {
  return <DashboardPanel title="经营提示" icon="spark" className="r-dashboard-hints" action={<Badge tone="blue">快照核对</Badge>}>
    {items.length?items.map(item=><button key={item.id} className="r-operating-hint" onClick={item.action}><span className="r-hint-icon"><Icon name={item.icon}/></span><span><strong>{item.title}</strong><small>{item.detail}</small></span><Icon name="chevronDown"/></button>):<Empty>正在核对当前经营资料…</Empty>}
  </DashboardPanel>;
}
export function RecentTasks({tasks,navigate}:{tasks?:Task[];navigate:(tab:string,id?:string)=>void}) {
  return <DashboardPanel title="最近任务" icon="clock" className="r-dashboard-recent" action={<button className="r-dashboard-text-link" onClick={()=>navigate('tasks')}>查看全部<Icon name="chevronDown"/></button>}>
    {!tasks?<Empty>任务记录未读到。</Empty>:tasks.length?<ol className="r-task-timeline">{tasks.slice(0,5).map(task=><li key={task.id}><button className="r-recent-task" title="查看这条任务的回执" onClick={()=>navigate('tasks',task.id)}><strong>{task.input.title||'共享任务'}</strong><span><small>{taskKind(task)}</small><Status value={task.status}/><Icon name="chevronDown"/></span></button></li>)}</ol>:<Empty>暂无共享任务记录。</Empty>}
  </DashboardPanel>;
}
