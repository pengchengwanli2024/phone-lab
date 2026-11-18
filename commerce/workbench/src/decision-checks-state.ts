/** Pure helpers for the read-only decision checks page: table text in, tool input out. */
export type Kind='scorecard'|'demand'|'competitor'|'shipment'|'experiment';
export const kinds:Kind[]=['scorecard','demand','competitor','shipment','experiment'];
export const tools:Record<Kind,string>={scorecard:'commerce_selection_scorecard',demand:'commerce_demand_trend_assess',
  competitor:'commerce_competitor_changes',shipment:'commerce_shipment_reconcile',experiment:'commerce_experiment_evaluate'};
export const titles:Record<Kind,string>={scorecard:'选品记分卡',demand:'需求趋势',competitor:'竞品变化',shipment:'货件差异',experiment:'实验评估'};

type Columns={text:readonly string[];number:readonly string[];flag?:readonly string[]};
/** Columns per table; numeric columns become JSON numbers, empty cells are left out. */
export const columns:Record<'scorecard'|'demand'|'competitor'|'events'|'claims',Columns>={
  scorecard:{text:['sku','title','source','source_kind','review_dependency','promo_intensity','differentiation'],number:['net_margin_pct','estimated_acos_pct']},
  demand:{text:['id','source_id','source_type','independent_group','country_code','metric','unit','series_version','period','source_kind'],number:['value'],flag:['source_revoked']},
  competitor:{text:['id','platform','country_code','external_id','observed_at','source_id','series_version','currency'],number:['price','rating','review_count','rank'],flag:['source_revoked']},
  events:{text:['event_type','event_date','source'],number:['quantity']},
  claims:{text:['claim_ref','state'],number:['claimed_quantity']},
};

export class InputProblem extends Error {}

/** RFC 4180-style parsing of comma or tab separated text with quoted cells. */
export function parseTable(text:string):string[][] {
  const rows:string[][]=[];let row:string[]=[],cell='',quoted=false;
  const source=text.replace(/^\uFEFF/,''),separator=source.split('\n',1)[0].includes('\t')?'\t':',';
  for(let i=0;i<source.length;i++){
    const ch=source[i];
    if(quoted){if(ch==='"'&&source[i+1]==='"'){cell+='"';i++;}else if(ch==='"')quoted=false;else cell+=ch;continue;}
    if(ch==='"'&&cell==='')quoted=true;
    else if(ch===separator){row.push(cell);cell='';}
    else if(ch==='\n'||ch==='\r'){if(ch==='\r'&&source[i+1]==='\n')i++;row.push(cell);cell='';if(row.some(v=>v.trim()))rows.push(row);row=[];}
    else cell+=ch;
  }
  if(quoted)throw new InputProblem('表格中有未闭合的引号');
  row.push(cell);if(row.some(v=>v.trim()))rows.push(row);
  return rows;
}

export function records(text:string,spec:Columns,label:string):Record<string,string|number|boolean>[] {
  const rows=parseTable(text);
  if(!rows.length)return [];
  const header=rows[0].map(v=>v.trim()),known=[...spec.text,...spec.number,...(spec.flag||[])];
  const unknown=header.filter(h=>!known.includes(h));
  if(unknown.length)throw new InputProblem(label+'表头有未识别的列：'+unknown.join('、'));
  if(new Set(header).size!==header.length)throw new InputProblem(label+'表头有重复的列');
  return rows.slice(1).map((cells,line)=>{
    const at=label+'第'+(line+2)+'行';
    if(cells.length>header.length)throw new InputProblem(at+'的列数多于表头');
    const out:Record<string,string|number|boolean>={};
    header.forEach((name,index)=>{
      const raw=(cells[index]??'').trim();if(!raw)return;
      if(spec.number.includes(name)){const value=Number(raw);if(!Number.isFinite(value))throw new InputProblem(at+'的 '+name+' 不是数字');out[name]=value;}
      else if(spec.flag?.includes(name)){if(!['true','false','是','否'].includes(raw))throw new InputProblem(at+'的 '+name+' 只能填 true 或 false');out[name]=raw==='true'||raw==='是';}
      else out[name]=raw;
    });
    return out;
  });
}

const integer=(raw:string,label:string,optional=false)=>{const value=raw.trim();if(!value){if(optional)return undefined;throw new InputProblem('请填写'+label);}
  const n=Number(value);if(!Number.isInteger(n)||n<0)throw new InputProblem(label+'须为非负整数');return n;};
const amount=(raw:string,label:string)=>{const value=raw.trim();if(!value)return undefined;const n=Number(value);if(!Number.isFinite(n)||n<0)throw new InputProblem(label+'须为非负数');return n;};
const required=(raw:string,label:string)=>{const value=raw.trim();if(!value)throw new InputProblem('请填写'+label);return value;};

export type Form=Record<string,string>;
export function buildInput(kind:Kind,form:Form):object {
  if(kind==='scorecard')return {candidates:records(form.table||'',columns.scorecard,'候选')};
  if(kind==='competitor')return {snapshots:records(form.table||'',columns.competitor,'快照')};
  if(kind==='demand')return {country_code:required(form.country_code||'','国家代码'),query:required(form.query||'','查询词'),
    as_of_month:required(form.as_of_month||'','截至月份'),months:integer(form.months||'12','窗口月数'),records:records(form.table||'',columns.demand,'序列')};
  if(kind==='shipment'){
    const input:Record<string,unknown>={as_of:required(form.as_of||'','核对日期'),
      shipment:{shipment_ref:required(form.shipment_ref||'','货件编号'),sku:required(form.sku||'','SKU'),expected_quantity:integer(form.expected_quantity||'','应收数量'),shipped_date:required(form.shipped_date||'','发货日期')},
      events:records(form.events||'',columns.events,'收货事件'),claims:records(form.claims||'',columns.claims,'已有索赔')};
    for(const [key,label] of [['in_transit_window_days','在途观察天数'],['claim_window_days','索赔窗口天数'],['proposed_claim_quantity','拟索赔数量']] as const){
      const value=integer(form[key]||'',label,true);if(value!==undefined)input[key]=value;}
    return input;
  }
  const variables=(form.changed_variables||'').split(/[\n,，、]/).map(v=>v.trim()).filter(Boolean);
  if(!variables.length)throw new InputProblem('请填写本次改动的变量');
  const input:Record<string,unknown>={primary_metric:required(form.primary_metric||'','主要指标'),changed_variables:variables,higher_is_better:form.higher_is_better!=='false',
    baseline:{trials:integer(form.baseline_trials||'','基线样本数'),successes:integer(form.baseline_successes||'','基线达成数')},
    variant:{trials:integer(form.variant_trials||'','变体样本数'),successes:integer(form.variant_successes||'','变体达成数')}};
  const minimum=integer(form.min_sample_per_arm||'','每组最少样本',true);if(minimum!==undefined)input.min_sample_per_arm=minimum;
  const interference=(form.external_interference||'').split('\n').map(v=>v.trim()).filter(Boolean);if(interference.length)input.external_interference=interference;
  const cap=amount(form.budget_cap||'','预算上限'),spent=amount(form.budget_spent||'','已花费');
  if((cap===undefined)!==(spent===undefined))throw new InputProblem('预算上限与已花费需同时填写或同时留空');
  if(cap!==undefined){input.budget_cap=cap;input.budget_spent=spent;}
  return input;
}

const fieldNames:Record<string,string>={candidates:'候选行',records:'序列行',snapshots:'快照行',events:'收货事件',claims:'已有索赔',sku:'SKU',title:'名称',source:'来源',source_kind:'来源类型',
  net_margin_pct:'净毛利',estimated_acos_pct:'预估ACOS',review_dependency:'复购依赖',promo_intensity:'促销强度',differentiation:'差异',period:'月份',as_of_month:'截至月份',months:'窗口月数',
  country_code:'国家代码',query:'查询词',observed_at:'观测时间',as_of:'核对日期',shipped_date:'发货日期',event_date:'事件日期',event_type:'事件类型',expected_quantity:'应收数量',quantity:'数量',
  claimed_quantity:'索赔数量',claim_state:'索赔状态',changed_variables:'改动变量',min_sample_per_arm:'每组最少样本（不少于30）',budget:'预算',higher_is_better:'指标方向',
  baseline:'基线',variant:'变体',primary_metric:'主要指标',value:'数值',currency:'币种',in_transit_window_days:'在途观察天数',claim_window_days:'索赔窗口天数',proposed_claim_quantity:'拟索赔数量',
  external_interference:'外部干扰',budget_cap:'预算上限',budget_spent:'已花费'};
const fixed:Record<string,string>={decision_duplicate_sku:'有重复的 SKU',decision_duplicate_record_id:'序列中有重复的记录 id',decision_duplicate_claim_ref:'已有索赔中有重复编号',
  decision_price_requires_currency:'填写了价格的快照必须同时填写币种',decision_invalid_snapshot:'快照 id 重复，或观测时间不是 YYYY-MM-DD / YYYY-MM-DDTHH:MM:SSZ',
  decision_invalid_input:'缺少必填列，或含有不支持的字段',decision_invalid_shipped_date:'发货日期晚于核对日期',decision_invalid_event_date:'事件日期须在发货日期与核对日期之间'};
export function problemText(code:string):string {
  if(fixed[code])return fixed[code];
  const match=/^decision_invalid_(.+?)(_trials|_successes)?$/.exec(code);
  if(!match)return '';
  const suffix=match[2]==='_trials'?'样本数':match[2]==='_successes'?'达成数':'';
  return (fieldNames[match[1]]||match[1])+suffix+'不符合要求，请核对格式与范围';
}

function demandSample(){
  const lines=['id,source_id,source_type,independent_group,country_code,metric,unit,series_version,period,value,source_kind'];
  [10,10,10,10,12,13,14,15,18,20,20,20].forEach((v,i)=>{const month='2025-'+String(i+1).padStart(2,'0');
    lines.push('a'+i+',demo-search,search,g1,RU,interest,index,v1,'+month+','+v+',THIRD_PARTY_ESTIMATE');
    lines.push('b'+i+',demo-market,marketplace,g2,RU,interest,index,v1,'+month+','+(v+2)+',THIRD_PARTY_ESTIMATE');});
  return lines.join('\n');
}
/** Synthetic examples, visibly labelled on the page; they never come from a store. */
export const samples:Record<Kind,Form>={
  scorecard:{table:'sku,title,source,source_kind,review_dependency,net_margin_pct,promo_intensity,estimated_acos_pct,differentiation\nDEMO-A,示例收纳盒,合成示例,MANUAL_QUOTE,low,32,medium,12,buyer_visible\nDEMO-B,示例挂钩,合成示例,THIRD_PARTY_ESTIMATE,medium,18,high,15,unknown\nDEMO-C,示例毛巾架,合成示例,MANUAL_QUOTE,high,,low,20,unknown\nDEMO-D,示例同款收纳盒,合成示例,MANUAL_QUOTE,low,24,high,20,none'},
  demand:{country_code:'RU',query:'示例查询',as_of_month:'2025-12',months:'12',table:demandSample()},
  competitor:{table:'id,platform,country_code,external_id,observed_at,source_id,series_version,price,currency,rating,review_count,rank\ns1,ozon,RU,DEMO-1,2025-01-01,demo-export,v1,1000,RUB,4.6,120,\ns2,ozon,RU,DEMO-1,2025-01-08,demo-export,v1,900,RUB,4.5,131,12'},
  shipment:{shipment_ref:'DEMO-SHIP',sku:'DEMO-A',expected_quantity:'100',shipped_date:'2025-01-01',as_of:'2025-03-01',proposed_claim_quantity:'5',in_transit_window_days:'',claim_window_days:'',
    events:'event_type,quantity,event_date,source\nRECEIVED,90,2025-01-12,示例入库回执\nTRANSFER,3,2025-01-20,示例调拨记录',claims:'claim_ref,claimed_quantity,state'},
  experiment:{primary_metric:'转化率',changed_variables:'主图',higher_is_better:'true',baseline_trials:'1000',baseline_successes:'100',variant_trials:'1000',variant_successes:'150',min_sample_per_arm:'',external_interference:'',budget_cap:'',budget_spent:''},
};
const header=(text:string)=>text.split('\n')[0];
export const blank:Record<Kind,Form>={
  scorecard:{table:header(samples.scorecard.table)},
  demand:{country_code:'',query:'',as_of_month:'',months:'12',table:header(samples.demand.table)},
  competitor:{table:header(samples.competitor.table)},
  shipment:{shipment_ref:'',sku:'',expected_quantity:'',shipped_date:'',as_of:'',proposed_claim_quantity:'',in_transit_window_days:'',claim_window_days:'',events:header(samples.shipment.events),claims:samples.shipment.claims},
  experiment:{primary_metric:'',changed_variables:'',higher_is_better:'true',baseline_trials:'',baseline_successes:'',variant_trials:'',variant_successes:'',min_sample_per_arm:'',external_interference:'',budget_cap:'',budget_spent:''},
};

const names:Record<string,string>={READY:'数据就绪',HOLD:'待补依据',REJECT:'不建议',UP:'上升',DOWN:'下降',FLAT:'持平',UNKNOWN:'无法判断',
  EMERGING:'新兴',DECLINING:'下降',SUSTAINED:'持续',SEASONAL:'季节性',INSUFFICIENT_EVIDENCE:'证据不足',CORROBORATED:'两源互证',DIVERGENT:'来源分歧',
  BALANCED:'收发一致',IN_TRANSIT:'仍在运输观察期',CONFIRMED_VARIANCE:'确认差异',OVER_RECEIVED:'多收',
  WITHIN_VARIANCE:'在确认差异内',BLOCKED_IN_TRANSIT:'仍在途，暂不能索赔',BLOCKED_NO_VARIANCE:'没有可索赔的差异',BLOCKED_WINDOW_ELAPSED:'已超过索赔窗口',BLOCKED_EXCESS:'超过确认差异',
  VARIANT_FAVORED:'变体更好',BASELINE_FAVORED:'基线更好',NO_DETECTED_DIFFERENCE:'未发现差异',INCONCLUSIVE:'无法下结论',CONFOUNDED:'多个变量同时改动',
  EXTERNAL_INTERFERENCE:'有外部干扰',BUDGET_CAP_EXCEEDED:'超出预算',IDENTICAL_EVENT_ROWS:'有完全相同的事件行',CLAIMS_EXCEED_VARIANCE:'已索赔超过差异',
  NO_BASELINE:'没有上一快照',VALUE_MISSING:'缺值',COMPARABILITY_BREAK:'来源或口径变化',CURRENCY_MISMATCH:'币种不同',SOURCE_UNAVAILABLE:'来源已撤回',AMBIGUOUS_ORDER:'两次快照时间相同',
  REGION_MISMATCH:'国家不一致',COVERAGE_BELOW_70_PERCENT:'覆盖不足70%',CONFLICTING_MONTHS:'有冲突月份',SIMULATION_EXCLUDED:'模拟数据不计入',WINDOW_EDGE_MISSING:'窗口首尾缺数据',ZERO_BASELINE:'起点为零',
  non_simulated_source:'非模拟来源',differentiation:'差异说明',net_margin_pct:'净毛利',estimated_acos_pct:'预估ACOS',review_dependency:'复购依赖',promo_intensity:'促销强度'};
export const label=(code:string|null|undefined)=>code?names[code]||code:'—';
const good=['READY','BALANCED','CORROBORATED','WITHIN_VARIANCE','VARIANT_FAVORED','BASELINE_FAVORED'];
const bad=['REJECT','DIVERGENT','CONFIRMED_VARIANCE','OVER_RECEIVED','CONFOUNDED'];
const neutral=['UNKNOWN','INSUFFICIENT_EVIDENCE','NO_DETECTED_DIFFERENCE'];
export const tone=(code:string)=>good.includes(code)?'success':bad.includes(code)||code.startsWith('BLOCKED')?'danger':neutral.includes(code)?'gray':'warning';
