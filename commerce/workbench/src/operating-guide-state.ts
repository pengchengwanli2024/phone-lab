import type {ListingTarget} from './listing-observation';
export type OperatingGoal='launch'|'operate';
export interface OperatingStage {id:string;name:string;required_for_goal:boolean;acceptance_status:string;capability_status:string;missing:string[];blocked_by:string[];limitations:string[]}
export interface OperatingSnapshot {schema:string;target:ListingTarget;goal:OperatingGoal;snapshot_sha256:string;product_source_sha256:string;listing_preview_sha256?:string;listing_revision?:number;stages:OperatingStage[];observed_at:string;business_outcome_verified:false;external_execution_allowed:false;unresolved_release_count:number;release_history_complete:boolean}
export function pipelineMissingText(stageName:string,item:string):string {
  return /^缺少 [a-z_]+ 岗位产物$/.test(item)?`${stageName}的工作产物待补齐`:item;
}
export function pipelineListingMissing(item:string,checkLabels:Record<string,string>):{label:string;checkId?:string} {
  if(Object.hasOwn(checkLabels,item)&&checkLabels[item])return {label:checkLabels[item],checkId:item};
  return {label:/^[a-z_][a-z0-9_]*$/i.test(item)?'发布检查项待核对，请查看发布前检查。':item};
}
export function pipelineKey(target:ListingTarget,goal:OperatingGoal):string|null {
  return ['case_id','platform','store_ref','market'].every(k=>typeof target[k as keyof ListingTarget]==='string'&&!!target[k as keyof ListingTarget].trim())?JSON.stringify([target.case_id,target.platform,target.store_ref,target.market,goal]):null;
}
export function pipelineMatches(value:OperatingSnapshot,target:ListingTarget,goal:OperatingGoal,expected?:{preview?:string;revision?:number}):boolean {
  return value?.schema==='commerce-operating-pipeline-v1'&&value.goal===goal&&!!value.target
    &&['case_id','platform','store_ref','market'].every(k=>value.target[k as keyof ListingTarget]===target[k as keyof ListingTarget])
    &&/^[a-f0-9]{64}$/.test(value.snapshot_sha256)&&/^[a-f0-9]{64}$/.test(value.product_source_sha256)
    &&Array.isArray(value.stages)&&value.external_execution_allowed===false&&value.business_outcome_verified===false
    &&(!expected?.preview||value.listing_preview_sha256===expected.preview)
    &&(expected?.revision===undefined||value.listing_revision===expected.revision);
}
export function pipelineDestination(id:string):{kind:'product'|'listing';section:string;label:string}|null {
  const destinations:Record<string,{kind:'product'|'listing';section:string;label:string}>={
    research:{kind:'product',section:'research',label:'核对市场研究'},
    sourcing:{kind:'product',section:'overview',label:'核对货源与实物资料'},
    economics:{kind:'product',section:'cost',label:'核对成本与定价'},
    localization:{kind:'product',section:'content',label:'核对商品内容'},
    images:{kind:'product',section:'media',label:'核对图片与视频'},
    ugc:{kind:'product',section:'media',label:'核对视频制作'},
    policy:{kind:'listing',section:'listing-rules_ref',label:'核对发布依据'},
    listing:{kind:'listing',section:'listing-release',label:'核对申请与回执'},
  };
  return Object.hasOwn(destinations,id)?destinations[id]:null;
}
