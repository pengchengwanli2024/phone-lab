import type {ListingTarget} from './listing-observation';
import {pipelineDestination,pipelineMatches,pipelineStatusLabels,type OperatingSnapshot} from './operating-guide-state';

/** The saved-plan directory is the only source of a case's store target; names never stand in for it. */
export interface TargetDirectory {targets:Map<string,ListingTarget[]>;complete:boolean}
export interface PipelineSummary {total:number;prepared:number;next:{id:string;name:string;status:string;label:string;missing:string}|null;unresolved:boolean}
export type CasePipeline=
  |{state:'none';incomplete:boolean}
  |{state:'failed'}
  |{state:'ready';target:ListingTarget;others:number;summary:PipelineSummary};

export function targetDirectory(value:{items?:{target?:ListingTarget}[];next_offset?:number|null}|null|undefined):TargetDirectory {
  const targets=new Map<string,ListingTarget[]>();
  for(const row of value?.items||[]){
    const target=row?.target;
    if(!target||!['case_id','platform','store_ref','market'].every(key=>typeof target[key as keyof ListingTarget]==='string'&&!!target[key as keyof ListingTarget]))continue;
    targets.set(target.case_id,[...(targets.get(target.case_id)||[]),target]);
  }
  return {targets,complete:value?.next_offset===null};
}

/** Diagnostic progress only: a prepared stage is not a signed, submitted or published one. */
export function pipelineSummary(value:OperatingSnapshot):PipelineSummary {
  const required=value.stages.filter(stage=>stage.required_for_goal);
  const open=required.find(stage=>stage.acceptance_status!=='prepared');
  return {
    total:required.length,
    prepared:required.filter(stage=>stage.acceptance_status==='prepared').length,
    next:open?{id:open.id,name:open.name,status:open.acceptance_status,label:pipelineStatusLabels[open.acceptance_status]||'待核对',missing:open.missing[0]||''}:null,
    unresolved:value.unresolved_release_count>0||!value.release_history_complete,
  };
}

export async function readCasePipeline(api:<T>(tool:string,args?:object)=>Promise<T>,caseId:string,directory:TargetDirectory|null):Promise<CasePipeline> {
  if(!directory)return {state:'failed'};
  const found=directory.targets.get(caseId)||[];
  if(!found.length)return {state:'none',incomplete:!directory.complete};
  const target=found[0];
  try{
    const value=await api<OperatingSnapshot>('commerce_operating_pipeline_get',{...target,goal:'launch'});
    if(!pipelineMatches(value,target,'launch'))return {state:'failed'};
    return {state:'ready',target,others:found.length-1,summary:pipelineSummary(value)};
  }catch{return {state:'failed'};}
}

export function pipelineStep(pipeline:CasePipeline):{kind:'product'|'listing';section:string;label:string}|null {
  if(pipeline.state!=='ready')return null;
  const next=pipeline.summary.next;
  if(pipeline.summary.unresolved||!next)return {kind:'listing',section:'listing-release',label:pipeline.summary.unresolved?'核对原申请回执':'核对上架方案'};
  return pipelineDestination(next.id);
}
