import type {ListingTarget} from './listing-observation';
import {pipelineMissingText} from './operating-guide-state';
import {pipelineStep,type CasePipeline,type TargetDirectory} from './overview-pipeline';

/** One saleable product from the shared catalog; fulfillment-scope work items are already merged under it. */
export interface BoardProduct {
  id:string;name:string;kind:'candidate'|'inventory';synthetic:boolean;sku?:string|null;
  case_ids:string[];primary_case_id:string;platform?:string;market?:string;
  store_identity?:{label?:string|null}|null;
}
export interface BoardColumn {id:string;label:string;hint:string}
/** Columns follow the launch stages the pipeline already reports; nothing here decides a stage. */
export const boardColumns:BoardColumn[]=[
  {id:'candidate',label:'选品候选',hint:'调研候选，尚未建立上架方案'},
  {id:'unplanned',label:'未建上架方案',hint:'已有商品，还没有保存目标店铺的上架方案'},
  {id:'research',label:'市场研究',hint:'等研究资料'},
  {id:'sourcing',label:'货源与实物',hint:'等报价与实物事实'},
  {id:'economics',label:'成本与定价',hint:'等同币种测算'},
  {id:'localization',label:'卖点与本地化',hint:'等商品内容'},
  {id:'images',label:'图片',hint:'等图片资料'},
  {id:'policy',label:'规则与资质',hint:'等平台规则依据'},
  {id:'listing',label:'上架与回读',hint:'等上架申请与回执'},
  {id:'prepared',label:'资料已备齐',hint:'诊断资料齐全，仍需人工审阅，不代表已发布'},
  {id:'unread',label:'阶段未读到',hint:'阶段资料未读到或超出本次读取上限'},
];
const stageColumns=new Set(boardColumns.map(column=>column.id));
export interface BoardCard {
  product:BoardProduct;column:string;caseId:string;target?:ListingTarget;others:number;
  stage:string;blocker:string;scopes:number;step:ReturnType<typeof pipelineStep>;note:string;
}
/** Targets saved for any of the product's work items. The first saved one is read; the rest are counted, never guessed. */
export function productTargets(product:BoardProduct,directory:TargetDirectory|null):ListingTarget[] {
  return directory?product.case_ids.flatMap(id=>directory.targets.get(id)||[]):[];
}
export function placeProduct(product:BoardProduct,directory:TargetDirectory|null,pipelines:Record<string,CasePipeline|undefined>):BoardCard {
  const targets=productTargets(product,directory),target=targets[0],scopes=product.case_ids.length;
  const base={product,caseId:target?.case_id||product.primary_case_id,target,others:Math.max(0,targets.length-1),scopes,step:null,blocker:'',stage:'',note:''};
  if(!directory)return {...base,column:'unread',note:'上架方案目录未读到'};
  if(!target)return {...base,column:product.kind==='candidate'?'candidate':'unplanned',note:directory.complete?'':'上架方案目录未读全，可能另有方案'};
  const pipeline=pipelines[target.case_id];
  if(!pipeline)return {...base,column:'unread',note:'超出本次读取上限，打开商品查看'};
  if(pipeline.state!=='ready')return {...base,column:'unread',note:'阶段资料未读到，请刷新'};
  const next=pipeline.summary.next,step=pipelineStep(pipeline);
  if(!next)return {...base,column:'prepared',step,stage:'资料已备齐',note:pipeline.summary.unresolved?'有未核对的申请回执':''};
  return {...base,column:stageColumns.has(next.id)?next.id:'unread',step,stage:next.label,
    blocker:next.missing?pipelineMissingText(next.name,next.missing):'',note:pipeline.summary.unresolved?'有未核对的申请回执':''};
}
export function arrangeBoard(products:BoardProduct[],directory:TargetDirectory|null,pipelines:Record<string,CasePipeline|undefined>,synthetic:boolean,query=''):{columns:{column:BoardColumn;cards:BoardCard[]}[];total:number;merged:number} {
  const q=query.trim().toLowerCase();
  const scoped=products.filter(product=>product.synthetic===synthetic&&(!q||[product.name,product.sku||''].some(text=>text.toLowerCase().includes(q))));
  const cards=scoped.map(product=>placeProduct(product,directory,pipelines));
  return {
    columns:boardColumns.map(column=>({column,cards:cards.filter(card=>card.column===column.id)})).filter(entry=>entry.cards.length),
    total:scoped.length,merged:scoped.reduce((sum,product)=>sum+Math.max(0,product.case_ids.length-1),0),
  };
}
/** Which work items need a stage read: the first saved target of each product, bounded. */
export function pipelineRequests(products:BoardProduct[],directory:TargetDirectory|null,synthetic:boolean,limit:number):string[] {
  const ids:string[]=[];
  for(const product of products){if(product.synthetic!==synthetic)continue;const target=productTargets(product,directory)[0];if(target&&!ids.includes(target.case_id))ids.push(target.case_id);}
  return ids.slice(0,limit);
}
