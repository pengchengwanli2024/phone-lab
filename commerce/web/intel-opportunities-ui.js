/* Original extension receipts, read only. Opening this panel never runs a model. */
window.CommerceIntelOpportunities=({api,repaint,isActive=()=>true,onSource})=>{
 const ui=window.CommerceUI,e=ui.escape,id=crypto.randomUUID();
 const s={busy:false,error:'',runs:[],plans:[],generation:0,hidden:true,disposed:false,workflowCount:0};
 const active=()=>!s.disposed&&!s.hidden&&isActive();
 const paint=()=>{if(active())repaint()};
 const object=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
 const normalized=v=>Array.isArray(v)?v.map(normalized):object(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,normalized(v[k])])):v;
 const same=(a,b)=>JSON.stringify(normalized(a))===JSON.stringify(normalized(b));
 const text=(v,max)=>typeof v==='string'&&!!v.trim()&&Array.from(v).length<=max;
 const epoch=v=>typeof v==='number'&&Number.isFinite(v)?v:typeof v==='string'&&/(?:Z|[+-]\d\d:\d\d)$/.test(v)&&Number.isFinite(Date.parse(v))?Date.parse(v)/1000:null;
 const unknown=v=>object(v)&&v.status==='unknown'&&v.terms===null;
 const witness=(run,tool,output)=>Array.isArray(run.steps)&&run.steps.some(x=>x?.status==='succeeded'&&x.late_after_budget!==true&&x.source?.kind==='builtin'&&x.source.tool===tool&&x.source.verification==='observed_local_result'&&same(x.output,output));
 function eligible(row){const steps=row?.definition?.spec?.steps;return row?.kind==='workflow'&&Array.isArray(steps)&&steps.some(x=>x?.uses?.builtin==='commerce_intel_opportunity_packet')&&steps.some(x=>x?.uses?.builtin==='commerce_intel_opportunity_validate')}
 function packetObserved(run){
  const p=run.output?.packet;if(run.test||run.status!=='succeeded'||!object(p)||p.schema!=='commerce-intel-opportunity-packet-v1'||p.scope!=='news_derived_opportunity_hypotheses'||p.not_platform_hot_terms!==true||p.external_execution_allowed!==false||!unknown(p.platform_hot_terms)||!/^[a-f0-9]{64}$/.test(p.packet_sha256)||![8,20].includes(p.limit)||!Array.isArray(p.items)||p.items.length>p.limit||!object(p.coverage))return null;
  const generated=epoch(p.generated_at),expires=epoch(p.expires_at),c=p.coverage;
  if(generated===null||expires===null||!(expires>generated&&expires-generated<=3600)||c.selected!==p.items.length||c.max_items!==p.limit||c.window_hours!==24||c.status!==(p.items.length?'bounded_public_news_sample':'needs_fresh_sources')||c.selection!=='source_balanced_latest_publications'||c.archive_search!==true||typeof c.truncated!=='boolean')return null;
  if(p.items.some(x=>!object(x)||!/^[a-f0-9]{24}$/.test(x.id)||!/^[a-f0-9]{64}$/.test(x.record_sha256)||!text(x.title,180)||!text(x.source,100)||epoch(x.published)===null||epoch(x.collected_at)===null)||new Set(p.items.map(x=>x.id)).size!==p.items.length||!witness(run,'commerce_intel_opportunity_packet',p))return null;
  return p;
 }
 function observed(run){
  const r=run.output?.result,p=run.output?.packet;
  if(!packetObserved(run)||!object(r)||r.schema!=='commerce-intel-opportunity-result-v1'||r.scope!=='news_derived_opportunity_hypotheses'||r.not_platform_hot_terms!==true||r.verification!=='news_derived_hypotheses_needs_evidence'||r.packet_sha256!==p.packet_sha256||r.external_execution_allowed!==false||r.business_actions_executed!==false||!unknown(r.platform_hot_terms)||!text(r.summary,1200)||!Array.isArray(r.opportunities)||r.opportunities.length>3||!Array.isArray(r.evidence)||!same(r.evidence,p.items)||!same(r.coverage,p.coverage)||!witness(run,'commerce_intel_opportunity_validate',r))return null;
  const known=new Set(r.evidence.map(x=>x.id));
  if(r.opportunities.some(x=>!object(x)||!text(x.hypothesis,500)||x.confidence!=='low'||x.status!=='needs_evidence'||!Array.isArray(x.evidence_ids)||!x.evidence_ids.length||x.evidence_ids.length>4||new Set(x.evidence_ids).size!==x.evidence_ids.length||x.evidence_ids.some(ref=>!known.has(ref))||!Array.isArray(x.next_checks)||!x.next_checks.length||x.next_checks.length>4||x.next_checks.some(v=>!text(v,200))))return null;
  return r;
 }
 async function enter(){
  if(s.disposed)return;
  s.hidden=false;const generation=++s.generation;s.busy=true;s.error='';s.runs=[];s.plans=[];s.workflowCount=0;paint();
  try{
   const entries=await api('commerce_extension_list',{});if(!active()||generation!==s.generation)return;
   const workflows=(entries.items||[]).filter(eligible).slice(0,4),ids=new Set(workflows.map(x=>x.id));s.workflowCount=workflows.length;
   const plans=await api('commerce_extension_schedule_list',{});if(!active()||generation!==s.generation)return;
   s.plans=(plans.schedules||[]).filter(x=>x&&ids.has(x.extension_id));
   const runs=[];
   for(const workflow of workflows){const result=await api('commerce_extension_run_list',{extension_id:workflow.id});if(!active()||generation!==s.generation)return;runs.push(...(result.runs||[]).filter(x=>x&&x.extension_id===workflow.id&&!x.test).map(x=>({...x,workflow_name:workflow.name})));}
   s.runs=runs.sort((a,b)=>b.created_at-a.created_at).slice(0,10);
  }catch{if(active()&&generation===s.generation)s.error='机会观察回执暂不可读，请刷新后核对。'}
  finally{if(generation===s.generation){s.busy=false;paint()}}
 }
 const status={succeeded:'已完成',failed:'失败 · 待处理',unknown:'结果未知 · 待核对',queued:'已排队',running:'运行中',cancelled:'已取消',blocked:'等待处理'};
 const date=v=>{const t=epoch(v);return t!==null&&Number.isFinite(new Date(t*1000).getTime())?new Date(t*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'时间未记录'};
 function freshness(packet){const now=Date.now()/1000,current=epoch(packet.generated_at)<=now&&now<=epoch(packet.expires_at)&&packet.items.every(x=>0<=now-epoch(x.published)&&now-epoch(x.published)<=86400&&0<=now-epoch(x.collected_at)&&now-epoch(x.collected_at)<=21600);return `<p class="muted">${current?'当次观察':'历史观察 · 输入已过期或来源已陈旧'} · 输入形成于 ${e(date(packet.generated_at))}。未重验当前来源；来源按钮打开当前留存记录，原版本 ${packet.items.length?'见各来源哈希':'暂无'}。不代表当前市场事实或执行授权。</p>`}
 function resultView(run){
  const r=observed(run),p=packetObserved(run),skipped=run.output?.result;
  if(!r){
   const empty=p&&p.items.length===0&&skipped?.status==='skipped'&&skipped.reason==='condition_false'&&run.usage?.model_calls===0&&Array.isArray(run.steps)&&run.steps.some(x=>x?.status==='succeeded'&&x.source?.kind==='condition'&&same(x.output,skipped));
   if(empty)return `${freshness(p)}<p>本次无新鲜输入，条件分支跳过；未调用模型，未形成机会结论。请先核对原资讯采集回执。</p>`;
   return `<p class="muted">${run.status==='unknown'?'执行结果未知；不能当作完成，请先核对原运行，不自动重试。':run.status==='failed'?'本地模型或工作流校验未完成，本次没有可采用的机会结论。':run.status==='succeeded'?'原回执的校验步骤或来源绑定不完整，未展示为已校验机会。':'本次尚未完成，暂无机会结论。'}</p>`;
  }
  return `${freshness(p)}<p>${e(r.summary)}</p>${r.opportunities.map(x=>`<article class="ui-card"><h4>${e(x.hypothesis)}</h4>${ui.badge('低置信 · 待补证','gray')}<p>下一步核查：${x.next_checks.map(e).join('；')}</p><ul>${x.evidence_ids.map(ref=>{const source=r.evidence.find(x=>x.id===ref);return `<li>${ui.button({label:source.title||ref,variant:'quiet',attrs:{'data-opportunity-source':source.id}})} <span class="muted">${e(source.source)} · ${e(date(source.published))} · 版本 ${e(source.record_sha256.slice(0,12))}</span></li>`}).join('')}</ul></article>`).join('')}${!r.opportunities.length?(p.items.length?'<p>本次有来源输入，但未形成足够明确的机会假设。</p>':'<p>本次没有可用来源输入，未形成机会假设。</p>'):''}`;
 }
 function view(){return `<section data-intel-opportunities="${id}"><div class="form-actions">${ui.button({label:'刷新运行记录',attrs:{'data-opportunity-refresh':id,disabled:s.busy}})}</div><p class="muted">公开资讯形成的机会假设须补充需求、竞品和成本证据。平台热搜词尚未接入，暂无真实排名或搜索量。这里只读取原记录，不启动模型或计划。</p>${s.plans.map(x=>`<p>${e(x.name)} · ${x.enabled?'自动计划已启用':'自动计划已停用'} · ${x.interval_seconds?Math.round(x.interval_seconds/3600)+' 小时间隔':'按保存的触发条件'}；以实际运行回执为准。</p>`).join('')}${s.busy?'<p role="status">正在读取原运行记录…</p>':''}${s.error?ui.alert(s.error,'danger'):''}${!s.busy&&!s.error&&!s.runs.length?ui.empty(s.workflowCount?'机会流程已配置，尚无运行记录。':'尚未发现已配置的机会观察流程。'):''}${s.runs.map(run=>`<details class="ui-card" ${run===s.runs[0]?'open':''}><summary>${e(date(run.created_at))} · ${e(status[run.status]||'状态待核对')}</summary><p class="muted">${e(run.workflow_name)} · ${e(run.id)} · 本次模型调用 ${e(run.usage?.model_calls??'未知')} 次</p>${resultView(run)}</details>`).join('')}</section>`}
 const click=event=>{if(!active())return;const node=event.target?.closest?.('[data-opportunity-refresh],[data-opportunity-source]');if(!node?.closest(`[data-intel-opportunities="${id}"]`))return;if(node.dataset.opportunityRefresh){enter();return}const sourceId=node.dataset.opportunitySource;if(s.runs.some(run=>observed(run)?.evidence.some(x=>x.id===sourceId)))onSource?.(sourceId);};
 document.addEventListener('click',click);
 function hide(){s.hidden=true;s.generation++;s.busy=false;}
 function dispose(){if(s.disposed)return;s.disposed=true;hide();document.removeEventListener('click',click);}
 return {enter,view,hide,dispose};
};
