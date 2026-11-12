/* One shared role-request UI, compiled into the existing three-resource route. */
window.CommerceAgent=({api,esc,toast,repaint,modal,closeModal,isActive})=>{
  const ui=window.CommerceUI;
  const state={status:null,cases:[],caseId:'',stageId:'',caseChecks:{},runs:[],selected:null,role:'conductor',topic:'runtime',question:'',parameters:'',parent:null,busy:false,error:'',request:null,loadId:0};
  const active=['queued','running','cancel_requested'];
  const labels={queued:'排队中',running:'正在分析',awaiting_input:'等待补充信息',awaiting_review:'建议待审阅',completed:'分析已返回',failed:'分析失败',unknown:'模型结果未知',cancelled:'已取消',cancel_requested:'正在请求停止',interrupted:'运行中断'};
  const button=(label,action,attrs={})=>ui.button({label,attrs:{'data-agent-action':action,...attrs}});
  function parameters(){if(!state.parameters.trim())return {};const value=JSON.parse(state.parameters);if(!value||typeof value!=='object'||Array.isArray(value))throw Error('补充数据必须为 JSON 对象');return value}
  function caseFields(){return `<div class="agent-form-row">${ui.field('明确选择工作项',ui.select({id:'agent-case',name:'case_id',value:state.caseId,options:[{value:'',label:'请选择，不自动选取商品'},...state.cases.map(c=>({value:c.id,label:[c.scope.sku,c.scope.market,c.scope.inventory_type,c.currency||'币种待核对'].join(' · ')}))]}))}${ui.field('岗位阶段',ui.select({id:'agent-stage',name:'stage_id',value:state.stageId,options:[{value:'',label:'查看该工作项各阶段'},...(state.status?.case_stages||[]).map(s=>({value:s.id,label:s.id+' · '+s.name}))]}))}</div><p class="muted">只分析该商品的市场、履约范围与岗位缺项。${state.cases.length?'确认时将按所读取的版本复核。':'暂无已有工作项，请先在“岗位与闭环”导入并核对。'}</p>`}
  function caseCheckView(run,id){const value=state.caseChecks[run+':'+id];if(!value)return '';return `<div class="agent-case-check" data-case-check-status="${esc(value.gate_status)}"><p>复验结果：${esc(value.gate_status)}${value.evidence_changed?' · 依据已有变化':''}</p><p class="muted">复验于 ${esc(new Date(value.checked_at*1000).toLocaleString())} · 任务状态：${esc(value.task?.status||'尚未派单')}；门禁检查与任务状态分别读取，不代表经营操作已完成。</p>${(value.current?.stage.gaps||[]).map(g=>`<p>${esc(g.reason)}<br><small class="muted">责任：${esc(g.owner)} · 复验：${esc(g.verify)}</small></p>`).join('')}</div>`}
  function feedback(){return state.error?ui.alert(state.error,'danger'):''}
  function renderResult(){
    const run=state.selected;
    if(!run)return ui.empty('选择一条记录查看回答、工具依据和待确认建议。');
    const result=run.result;
    return `<section class="card agent-answer" aria-live="polite"><div class="agent-heading"><h2>${esc(run.role.name)}</h2>${ui.badge(labels[run.status]||run.status,run.status==='failed'?'danger':'blue')}</div><p class="agent-text"><strong>本轮问题</strong><br>${esc(run.question)}</p>${active.includes(run.status)?`<p role="status" data-ui-help>后台正在处理，可关闭页面，稍后从任意客户端读取结果。</p>${button('请求停止','cancel',{'data-run':run.id})}`:''}${result?.answer?`<p class="agent-text">${esc(result.answer)}</p><p class="muted">${esc(result.provider)} / ${esc(result.model)} · 模型分析待核对，未执行店铺操作。</p>${result.questions.length?`<section class="agent-questions"><h3>需要补充</h3>${result.questions.map(q=>`<p>${esc(q)}</p>`).join('')}${button('补充回答','reply',{'data-run':run.id})}</section>`:''}${result.proposals.map(p=>{const applied=run.actions.find(a=>a.proposal_id===p.id);return `<section class="agent-proposal"><h3>${esc(p.reason)}</h3><p class="muted">${esc({report:'本地模板简报',unit_economics:'单件贡献测算',restock_plan:'补货测算',intel_review:'来源证据整理',organization_handoff:'岗位资料补齐待办',exposure_review:'经营关联复核待办'}[p.operation]||p.operation)} · 需审阅具体参数</p>${applied?`<p>${p.operation==='organization_handoff'?'已创建岗位补齐待办':'已提交共享任务'} <code>${esc(applied.task_id)}</code>，排队不代表完成。</p>`:button('审阅建议','review',{'data-proposal':p.id,'data-run':run.id})}${p.operation==='organization_handoff'?`${button('复验当前门禁','case-check',{'data-proposal':p.id,'data-run':run.id})}${caseCheckView(run.id,p.id)}`:''}</section>`}).join('')}<details><summary>工具依据（${result.observations.length}）</summary>${result.observations.map(o=>`<section class="agent-evidence"><strong>${esc(o.id)} · ${esc(o.tool)}</strong><p class="muted">读取于 ${esc(new Date(o.observed_at*1000).toLocaleString())}</p><pre>${esc(JSON.stringify(o.data,null,2))}</pre></section>`).join('')||'<p class="muted">尚无工具读取；请先补齐问题所需信息。</p>'}</details><p class="muted">结果标识：<code>${esc(run.result_sha256)}</code></p>`:result?.error?ui.alert(({agent_provider_outcome_unknown:'模型结果未知，不会自动重发。',agent_interrupted_no_automatic_resubmit:'处理过程已中断，不会自动重发。',agent_tool_outside_scope:'模型请求了范围外的工具，调用已拒绝。',agent_calculation_input_changed:'模型试图修改明确输入的测算值，调用已拒绝。',agent_budget_exhausted:'已达到本轮分析上限，请缩小问题范围。',agent_cancelled_generation_may_have_started:'本轮已取消；已经发出的模型生成可能仍产生用量。'}[result.error]||'本轮未完成，请查看记录后再明确提交新请求。'),'danger'):''}</section>`;
  }
  function view(){
    return `<div class="agent-root">${ui.alert('使用现有模型处理本轮问题及所选范围的精简资料。不会读取其它聊天或批量导入知识库；平台操作仍需独立授权。')}<section class="card"><div class="agent-heading"><h2>向运营角色提问</h2>${ui.badge(state.status?.worker==='running'?'运行器在线':'等待运行器状态','gray')}</div><form id="agent-request"><div class="agent-form-row">${ui.field('角色',ui.select({id:'agent-role',name:'role',value:state.role,options:(state.status?.roles||[]).map(r=>({value:r.id,label:r.name}))}))}${ui.field('本轮读取范围',ui.select({id:'agent-topic',name:'topic',value:state.topic,options:[{value:'runtime',label:'本机与连接状态'},{value:'intelligence',label:'公开情报资料'},{value:'calculation',label:'明确输入的测算'},...(state.status?.topics?.includes('organization_case')?[{value:'organization_case',label:'选定商品与岗位工作项'}]:[])]}))}</div>${state.topic==='organization_case'?caseFields():''}${state.parent?`<p class="muted">补充上一轮 ${esc(state.parent.slice(0,8))} 的问题，原记录保持可查。${button('改为新问题','new')}</p>`:''}${ui.field('问题或补充回答',`<textarea class="ui-control" id="agent-question" name="question" maxlength="2000" placeholder="例如：检查后台与公开源状态，指出当前缺项">${esc(state.question)}</textarea>`)}${state.topic==='organization_case'?'':`<details ${state.topic==='calculation'?'open':''}><summary>补充结构化数据（可选）</summary><p class="muted" data-ui-help>测算可填写 calculator 和 input；字段须来自已核对的运营测算资料。缺项会追问，模型不能自行补造数值。公开情报可填写 item_id。</p>${ui.field('补充数据 JSON',`<textarea class="ui-control" id="agent-parameters" name="parameters" maxlength="8000" placeholder='{"calculator":"unit_economics","input":{"currency":"USD"}}'>${esc(state.parameters)}</textarea>`)}</details>`}<div class="agent-controls">${button(state.busy?'正在提交…':'提交本轮分析','submit',{id:'agent-submit',disabled:state.busy||!state.status,'aria-describedby':'agent-limit'})}<span id="agent-limit" class="muted">每轮最多三次模型分析、四次受限读取；不自动启动下一轮。</span></div></form>${feedback()}</section><div class="agent-columns"><section class="card agent-history"><div class="agent-heading"><h2>共享记录</h2>${button('刷新','refresh')}</div>${state.runs.map(r=>button(`${labels[r.status]||r.status} · ${r.question.slice(0,40)}`,'select',{'data-run':r.id,'aria-pressed':state.selected?.id===r.id})).join('')||ui.empty('尚无分析记录。')}</section>${renderResult()}</div></div>`;
  }
  async function load(){
    const id=++state.loadId;
    try{
      const [status,history]=await Promise.all([api('commerce_agent_status'),api('commerce_agent_list')]);
      if(id!==state.loadId)return;
      state.status=status;state.runs=history.runs;if(status.topics.includes('organization_case'))state.cases=(await api('commerce_agent_cases')).cases;
      if(!status.roles.some(r=>r.id===state.role))state.role=status.roles[0]?.id||'';
      if(state.selected)state.selected=await api('commerce_agent_get',{run_id:state.selected.id});
      if(id!==state.loadId)return;
      state.error='';if(isActive())repaint();
    }catch(error){if(id===state.loadId){state.error='读取失败：'+error.message;if(isActive())repaint()}}
  }
  async function submit(){
    if(state.busy)return;
    const form=document.querySelector('#agent-request');if(!form)return;
    const values=new FormData(form);state.caseId=String(values.get('case_id')||'');state.stageId=String(values.get('stage_id')||'');state.role=String(values.get('role')||'');state.topic=String(values.get('topic')||'');state.question=String(values.get('question')||'');state.parameters=String(values.get('parameters')||'');
    try{
      if(!state.question.trim())throw Error('请填写本轮问题');
      const extra=state.topic==='organization_case'?{case_id:String(values.get('case_id')||''),...(values.get('stage_id')?{stage_id:String(values.get('stage_id'))}:{})}:parameters();
      if(state.topic==='organization_case'&&!extra.case_id)throw Error('请明确选择工作项，不会自动选择其它商品');
      const args={question:state.question.trim(),role:state.role,topic:state.topic,parameters:extra,...(state.parent?{parent_id:state.parent}:{})};
      const fingerprint=JSON.stringify(args);if(state.request?.fingerprint!==fingerprint)state.request={fingerprint,key:crypto.randomUUID()};
      state.busy=true;state.error='';repaint();
      state.selected=await api('commerce_agent_start',{...args,idempotency_key:state.request.key});await load();
    }catch(error){state.error='提交未完成：'+error.message}
    finally{state.busy=false;if(isActive())repaint()}
  }
  document.addEventListener('input',event=>{const e=event.target;if(e.id==='agent-question')state.question=e.value;if(e.id==='agent-parameters')state.parameters=e.value});
  document.addEventListener('change',event=>{if(event.target.id==='agent-case'){state.caseId=event.target.value;state.request=null}if(event.target.id==='agent-stage'){state.stageId=event.target.value;state.request=null}if(event.target.id==='agent-role')state.role=event.target.value;if(event.target.id==='agent-topic'){state.topic=event.target.value;state.request=null;repaint()}});
  document.addEventListener('submit',event=>{if(event.target.id==='agent-request'){event.preventDefault();submit()}});
  document.addEventListener('keydown',event=>{if(event.target.id==='agent-question'&&event.key==='Enter'&&(event.metaKey||event.ctrlKey)){event.preventDefault();submit()}});
  document.addEventListener('click',async event=>{
    const target=event.target.closest('[data-agent-action]');if(!target)return;
    const action=target.dataset.agentAction;
    try{
      if(action==='submit'){event.preventDefault();await submit()}
      else if(action==='refresh')await load();
      else if(action==='select'){state.selected=await api('commerce_agent_get',{run_id:target.dataset.run});repaint()}
      else if(action==='cancel'){await api('commerce_agent_cancel',{run_id:target.dataset.run});await load()}
      else if(action==='new'){state.parent=null;state.request=null;repaint();document.querySelector('#agent-question')?.focus()}
      else if(action==='reply'){const r=state.selected;if(r.topic==='business_exposure'){window.dispatchEvent(new CustomEvent('commerce:exposure-open',{detail:{assessmentId:r.parameters.assessment_id,runId:r.id}}));return}state.parent=r.id;state.role=r.role.id;state.topic=r.topic;state.caseId=r.parameters.case_id||'';state.stageId=r.parameters.stage_id||'';state.question='';state.parameters=Object.keys(r.parameters).length?JSON.stringify(r.parameters,null,2):'';state.request=null;repaint();document.querySelector('#agent-question')?.focus()}
      else if(action==='case-check'){target.disabled=true;state.caseChecks[target.dataset.run+':'+target.dataset.proposal]=await api('commerce_agent_case_check',{run_id:target.dataset.run,proposal_id:target.dataset.proposal});repaint()}
      else if(action==='review'){
        const run=state.selected,p=run.result.proposals.find(p=>p.id===target.dataset.proposal);target.focus();
        modal('审阅本地建议',`<p>${esc(p.reason)}</p><p class="muted">${p.operation==='organization_handoff'?'复用岗位模块创建补齐待办，不自动补造资料或关闭门禁。确认时会重新核对商品、阶段和证据版本。':'仅提交下列本地任务，不执行采购、发货、改价或消息发送。'}请核对输入和依据。</p><pre>${esc(JSON.stringify({operation:p.operation,input:p.input},null,2))}</pre>`,button('确认这些参数并提交','apply',{'data-run':run.id,'data-proposal':p.id,'data-hash':run.result_sha256}));
      }else if(action==='apply'){
        target.disabled=true;
        const r=await api('commerce_agent_apply',{run_id:target.dataset.run,proposal_id:target.dataset.proposal,result_sha256:target.dataset.hash});closeModal();await load();toast((r.approval_scope==='single_organization_handoff'?'已创建岗位资料补齐待办 ':'已提交共享本地任务 ')+r.task.id.slice(0,8)+'，请查看任务与复验结果');
      }
    }catch(error){toast('操作未完成：'+({agent_case_evidence_changed:'依据已变化，请重新分析后审阅；本次没有派单。',agent_case_unavailable:'原工作项已不可用，请核对当前连接；不会替换为其它商品。'}[error.message]||error.message));target.disabled=false}
  });
  setInterval(()=>{if(isActive()&&state.selected&&active.includes(state.selected.status)&&!state.busy&&!document.querySelector('.dialog'))load()},1500);
  return {view,enter:load};
};
