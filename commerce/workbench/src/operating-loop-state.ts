/** Pure projections for the operating-loop panel. Nothing here dispatches, approves or retries. */
export interface LoopTarget {case_id:string;platform:string;store_ref:string;market:string}
export interface LoopGrant {
  id:string;target:LoopTarget;goal:string;stages:string[];level:'observe'|'prepare';max_runs_per_day:number;expires_at:number|null;
  enabled:boolean;active:boolean;halted_reason:string|null;revision:number;case_label:string|null;case_available:boolean;synthetic:boolean;
}
export interface LoopProposal {id:string;operation:string;reason:string}
export interface LoopWork {
  id:string;grant_id:string;target:LoopTarget;stage_id:string;stage_name:string;owner:string;status:string;missing:string[]|null;
  run_id:string|null;executor:string|null;created:number;updated:number;result_sha256:string|null;questions:string[]|null;
  proposals:LoopProposal[]|null;error:string|null;decision:{decision:string;proposal_id:string|null;task_id:string|null}|null;
}
export interface LoopStage {id:string;name:string;owner:string;executable:boolean;depends_on:string[]}
export interface LoopView {grants:LoopGrant[];work:LoopWork[];work_truncated:boolean;stage_catalog:LoopStage[];external_execution_allowed:false}
export interface LoopOutcome {reason:string;dispatched:LoopWork|null;view:LoopView}

const statuses:Record<string,[string,string]>={
  pending:['准备派发','gray'],dispatched:['智能体处理中','blue'],waiting_input:['等资料','warning'],awaiting_decision:['等你决定','warning'],
  completed:['已完成','green'],rejected:['已驳回','gray'],failed:['失败','danger'],unknown:['结果未知','warning'],cancelled:['已取消','gray'],resolved:['已核对关闭','gray'],superseded:['资料已更新','gray'],
};
export const workStatus=(value:string)=>{const found=statuses[value];return {label:found?.[0]||'状态待核对',tone:found?.[1]||'gray'};};

const owners:Record<string,string>={observer:'观察与复盘',scout:'市场调研',economist:'经济测算',sourcer:'供应链资料',creative:'创意与交付',localizer:'语言与字段',
  gatekeeper:'规则与合规核查',grower:'增长方案',fulfiller:'库存与履约观察',voice:'客户之声',controller:'财务控制',conductor:'编排协调'};
export const ownerName=(value:string)=>owners[value]||value||'负责人待核对';

const reasons:Record<string,string>={
  dispatched:'已按当前证据派给阶段负责人。',resumed_pending:'已接续上次未发出的同一工单，没有新建请求。',
  recorded_gap_without_executor:'已记录该阶段的缺项和负责人；这一级不调用模型。',
  no_new_evidence:'证据没有变化，没有新工单。补齐资料后会自动继续。',nothing_eligible:'所选阶段都已就绪，或仍被上游阶段挡住。',
  calculated_locally:'已按你保存的成本参数重新测算，未调用模型。',local_calculation_not_completed:'成本重算没有完成，请查看该工单的原因。',
  awaiting_your_decision:'这一阶段已有建议等你决定，决定之前不会再派发。',
  work_in_flight:'已有一项在处理，等它结束再继续。',unknown_requires_check:'有一项结果未知，请先核对原请求并关闭，再继续派发。',
  daily_limit:'今天的派发次数已到上限，明天继续。',grant_disabled:'该授权未启用。',grant_expired:'该授权已过期。',
  halted_consecutive_failures:'连续三次失败，已自动停用该授权。请核对原因后重新启用。',
};
export const outcomeText=(reason:string)=>reasons[reason]||'已读取当前状态，请核对下方工单。';

const errors:Record<string,string>={
  operating_loop_revision_conflict:'该授权已被其它窗口修改，已读取最新版本，请核对后重试。',
  operating_loop_result_changed:'智能体的结果已变化，请按当前内容重新决定。',
  operating_loop_not_awaiting_decision:'该工单当前不在待决状态，已读取最新状态。',
  operating_loop_already_decided:'该工单已有决定，未重复提交。',
  operating_loop_proposal_not_found:'该建议已不在当前结果中，请刷新核对。',
  operating_loop_not_resolvable:'只有失败或结果未知的工单可以核对关闭。',
  operating_loop_grant_expired:'授权已过期，请先修改有效期。',operating_loop_grant_limit:'回路授权数量已达上限。',
  operating_loop_invalid_stages:'请至少选择一个有效阶段。',operating_loop_invalid_target:'请选择已保存上架方案的商品。',
  agent_case_evidence_changed:'商品证据在批准前已变化，本次批准未提交。请等待按新证据生成的工单。',
  agent_case_unavailable:'该商品工作项当前不可读取，可能属于其它店铺连接。',
  organization_case_not_found:'该商品工作项当前不可读取，可能属于其它店铺连接。',
};
export const loopError=(failure:unknown)=>{const key=failure instanceof Error?failure.message:'';return errors[key]||'操作未完成，已保留当前内容；请刷新后核对。';};

export const grantLabel=(grant:LoopGrant)=>grant.case_label||(grant.case_available?'未命名商品':'商品当前不可读取');
export function grantState(grant:LoopGrant):{label:string;tone:string} {
  if(grant.halted_reason)return {label:'已自动停用',tone:'danger'};
  if(grant.enabled&&!grant.active)return {label:'已过期',tone:'warning'};
  return grant.enabled?{label:'运行中',tone:'blue'}:{label:'未启用',tone:'gray'};
}
export const levelName=(value:string)=>value==='prepare'?'范围内准备':'仅观察';

export interface LoopGroups {decide:LoopWork[];attention:LoopWork[];waiting:LoopWork[];running:LoopWork[];done:LoopWork[]}
/** Items needing a person come first; a finished item is never shown as outstanding. */
export function groupWork(view:LoopView|null,synthetic:boolean):LoopGroups {
  const groups:LoopGroups={decide:[],attention:[],waiting:[],running:[],done:[]};
  if(!view)return groups;
  const visible=new Set(view.grants.filter(grant=>grant.synthetic===synthetic).map(grant=>grant.id));
  for(const work of view.work){
    if(!visible.has(work.grant_id))continue;
    const bucket=work.status==='awaiting_decision'?groups.decide:['failed','unknown'].includes(work.status)?groups.attention
      :work.status==='waiting_input'?groups.waiting:['pending','dispatched'].includes(work.status)?groups.running:groups.done;
    bucket.push(work);
  }
  return groups;
}
/** Default to stages a role can actually work on; the rest only record gaps. */
export const defaultStages=(catalog:LoopStage[])=>catalog.filter(stage=>stage.executable&&['research','sourcing','economics','localization','images'].includes(stage.id)).map(stage=>stage.id);
export function stageWarnings(catalog:LoopStage[],selected:string[]):string[] {
  const chosen=new Set(selected),names=new Map(catalog.map(stage=>[stage.id,stage.name]));
  return catalog.filter(stage=>chosen.has(stage.id)).flatMap(stage=>stage.depends_on.filter(id=>!chosen.has(id))
    .map(id=>'“'+stage.name+'”要等“'+(names.get(id)||id)+'”就绪；后者未选入，将不会被回路推进。'));
}
