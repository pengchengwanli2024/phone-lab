window.CommerceOrganization=({api,repaint,toast,getCostBase})=>{
  const ui=window.CommerceUI,esc=ui.escape;
  const state={board:null,caseId:'',busy:false,error:'',kind:'supply',projectId:'',project:null,assets:[],scopeReviewed:false,bindings:{},exchange:null};
  const text={PASS:'检查通过',FAIL:'实测不符',BLOCKED:'依赖或能力阻断',HOLD:'资料待补或待核实'};
  const isCandidate=c=>c?.scope.origin==='research_candidate_not_inventory';
  const caseLabel=c=>isCandidate(c)?`${c.scope.label} · 调研候选 · 尚未绑定店铺商品`:`${c.scope.sku} · ${c.scope.inventory_type} · 产品 ${c.scope.product_id}`;
  const button=(label,action,extra={})=>ui.button({label,attrs:{'data-org-action':action,disabled:state.busy,...extra}});
  const download=(content,name)=>{const u=URL.createObjectURL(new Blob([content],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),2000)};
  async function load(){state.busy=true;try{state.board=await api('commerce_organization_board',state.caseId?{case_id:state.caseId}:{});state.caseId=state.board.case?.id||'';state.exchange=await api('commerce_organization_exchange_status',state.caseId?{case_id:state.caseId}:{});state.error=''}catch(e){state.error=e.message}finally{state.busy=false;repaint()}}
  function render(){
    const b=state.board,c=b?.case;
    const controls=`<div class="form-actions">${button('从现有库存建立工作项','import')}${button('重新检查','refresh')}${button('同步已完成产物','exchange-sync')}${button('保存体检快照','capture')}${button('导出当前看板','export')}</div>`;
    if(!b)return ui.card({title:'岗位与闭环',content:controls+(state.error?ui.alert(state.error,'danger'):ui.empty('正在读取本项目契约与证据…'))});
    const cases=ui.field('当前工作项',ui.select({id:'org-case',value:state.caseId,disabled:state.busy,options:[{value:'',label:'项目体检（尚未选择工作项）'},...b.cases.map(c=>({value:c.id,label:caseLabel(c)}))]}));
    const scope=c?`<p>平台 ${esc(c.scope.platform)} · 市场 ${esc(c.scope.market)} · ${isCandidate(c)?`调研候选 ${esc(c.scope.label)}；内部标识 ${esc(c.scope.sku)}。尚未绑定店铺商品、SKU 或库存`:`SKU ${esc(c.scope.sku)} · 库存范围 ${esc(c.scope.inventory_type)}`}。币种：<strong>${esc(c.currency||'未知')}</strong>。</p><div class="analysis-fields">${ui.field('明确工作项金额币种（不换算）',ui.input({id:'org-currency',value:c.currency||'',disabled:state.busy,maxlength:3,placeholder:'例如 CNY 或 RUB'}))}</div>${button('保存明确币种','currency')}`:ui.empty('可从已有库存建立本地工作项。旧快照和未核对口径会如实显示，不会冒充已完成。');
    const stages=b.stages.map(s=>ui.card({title:s.id+' · '+s.name,content:`${ui.badge(text[s.status],s.status==='PASS'?'success':s.status==='FAIL'?'danger':'warning')} <span class="muted">责任岗位：${esc(s.role)}；本段 ${s.passed}/${s.total} 项检查通过。</span>${s.gaps.length?ui.table(['缺什么 / 原因','谁补','补完如何验'],s.gaps.map(g=>`<tr><td>${esc(g.reason)}</td><td>${esc(g.owner)}</td><td>${esc(g.verify)}</td></tr>`)):'<p data-ui-help>当前受支持检查已通过。仍需按范围和事实核查要求使用产物。</p>'}${c?`<div class="form-actions">${button('岗位简报','brief',{'data-stage':s.id})}${s.status!=='PASS'?button('创建补齐任务','handoff',{'data-stage':s.id}):''}</div>`:''}`})).join('');
    const assets=state.project?.assets.filter(a=>['product_image','generated_image'].includes(a.kind))||[];
    const work=c?ui.card({title:'补齐资料与交付',content:`<p class="muted" data-ui-help>资料绑定当前工作项。导入的来源声明仍需核实；程序检查格式和交接，不代替独立合规或事实审查。</p><div class="form-actions">${ui.field('资料类型',ui.select({id:'org-kind',value:state.kind,options:[{value:'supply',label:'供应链成本与交期'},{value:'economics',label:'经济测算输入'},{value:'research',label:'采集原文与中文校对'}]}))}${button('下载当前工作项模板','template')}<label class="ui-field">导入已补齐 JSON<input id="org-record-file" type="file" accept=".json,application/json" ${state.busy?'disabled':''}></label></div><div class="form-actions">${ui.button({label:'前往成本测算',attrs:{'data-analysis-mode':'cost'}})}${button('保存当前成本测算资料','cost')}</div><h3>创意图片交付</h3><p class="muted" data-ui-help>只交付创意工作室已登记的图片。需要明确素材属于本工作项；交付成功不代表规格、使用权或商品事实已审核。</p><div class="analysis-fields">${ui.field('创意项目 ID',ui.input({id:'org-project-id',value:state.projectId,disabled:state.busy,placeholder:'从创意工作室复制对应项目 ID'}))}</div>${button('读取该项目图片','project')}${assets.length?`<div>${assets.map(a=>`<label class="review-check">${ui.input({type:'checkbox','data-org-asset':a.id,checked:state.assets.includes(a.id)})}${esc(a.display_name||a.id)} · ${esc(a.kind)}</label>`).join('')}</div><label class="review-check">${ui.input({type:'checkbox',id:'org-scope-confirm',checked:state.scopeReviewed})}我已核对所选素材与当前工作项的 SKU、变体对应关系</label>${button('交付所选图片到本机工作项','deliver')} ${button('保存所选图片的交接绑定','bind-images')}`:state.project?ui.empty('该项目没有已登记的商品图片。'):''}` }):'';
    return ui.card({title:'工作项与检查',content:`${controls}${cases}${scope}<div class="org-check-summary">${ui.badge(b.passed+'/'+b.total+' 项检查通过',b.passed===b.total?'success':'warning')}</div><p class="muted" data-ui-help>供应链资料先于经济测算采集；没有岗位拥有批准权。未接入广告、结算或客户来源的阶段会保留阻断，不显示虚构的零值。</p>${state.error?ui.alert(state.error,'danger'):''}${b.changes.length?`<p>与上轮相比：${b.changes.map(v=>esc(v.stage+' '+text[v.before]+' → '+text[v.after])).join('；')}</p>`:''}<details><summary>岗位职责与调用契约</summary><p>${esc(b.notice)}</p>${b.roles.map(r=>`<p><strong>${esc(r.name)} · ${esc(r.id)}</strong><br>${esc(r.mission)}<br><span class="muted">${r.skill_pod.tools.map(esc).join(' / ')}；已配置契约，不代表模型正在运行。</span></p>`).join('')}</details>`})+exchangeView()+work+stages;
  }
  function receiptHtml(r){if(!r)return '';return ui.alert(r.status==='saved'&&r.context_current!==false&&r.artifact_current!==false?'产物已交接到工作项；门禁仍按原文、校对与来源判据复验。':r.status==='waiting_for_source'?'交接已登记，等待原任务完成；不会重复提交模型。':'产物交接待处理：'+(r.code||r.status),r.status==='saved'?'info':'danger')}
  function exchangeView(){const receipts=state.exchange?.receipts||[];return ui.card({title:'产物交接回执',content:`<p class="muted" data-ui-help>先在调研或成本页明确选择工作项，完成检查/测算后会直接留存产物；重开页面后可同步已完成的绑定任务，译文保持待校对。</p>${ui.table(['产物','状态','当前绑定','回执'],receipts.map(r=>`<tr><td>${esc(r.kind)}</td><td>${esc(({saved:'已保存',held:'待处理',pending:'待恢复'})[r.status]||r.status)}</td><td>${!r.context_current?'范围变化，需重新绑定':r.artifact_current?'当前产物':'历史版本'}</td><td>${esc(r.code||'')}</td></tr>`),'尚无产物交接回执。')}`})}
  function bindingView(kind){const selected=state.bindings[kind]?.case_id||'';return ui.card({title:'工作项自动交接',content:`<p class="muted" data-ui-help>只在明确绑定后保存本地产物。演示测算不会交接；资料完整性不代表事实或合规已核实。</p>${!state.board?button('载入工作项以选择绑定','binding-load'):ui.field('将本页产物交接到',ui.select({id:'org-binding-'+kind,'data-org-binding':kind,value:selected,disabled:state.busy,options:[{value:'',label:'不绑定，仅在本页使用'},...state.board.cases.map(c=>({value:c.id,label:caseLabel(c)}))]}))}${selected?button('按当前范围更新绑定','binding-refresh',{'data-kind':kind}):''}`})}
  async function produce(tool,args,options={}){const kind=tool==='commerce_unit_economics'?'economics':'research';const context=state.bindings[kind];if(!context||options.origin&&options.origin!=='manual')return api(tool,args);return api('commerce_organization_exchange_produce',{context,source_tool:tool,source_arguments:args,...(options.record?{source_record:options.record}:{})})}
  async function afterTranslation(job){if(job.artifact_handoff?.case_id)await api('commerce_organization_exchange_sync',{case_id:job.artifact_handoff.case_id})}
  document.addEventListener('change',async e=>{
    if(e.target.dataset.orgBinding){const kind=e.target.dataset.orgBinding,id=e.target.value;state.busy=true;try{if(id)state.bindings[kind]=(await api('commerce_organization_exchange_status',{case_id:id})).context;else delete state.bindings[kind]}catch(error){state.error=error.message;delete state.bindings[kind]}finally{state.busy=false;repaint()}return}
    if(e.target.id==='org-case'){state.caseId=e.target.value;state.project=null;state.projectId='';state.assets=[];state.scopeReviewed=false;await load()}
    else if(e.target.dataset.orgAsset){state.assets=[...document.querySelectorAll('[data-org-asset]:checked')].map(e=>e.dataset.orgAsset)}
    else if(e.target.id==='org-scope-confirm')state.scopeReviewed=e.target.checked;
    else if(e.target.id==='org-kind')state.kind=e.target.value;
    else if(e.target.id==='org-record-file'){
      const captured=state.caseId,file=e.target.files[0];if(!file)return;state.busy=true;repaint();
      try{if(file.size>120000)throw Error('请分批导入，文件最大 120 KB');const data=JSON.parse(await file.text());if(data.case_id!==captured)throw Error('文件所属工作项与当前选择不一致');await api('commerce_organization_record',{case_id:captured,kind:data.kind,payload:data.payload,idempotency_key:crypto.randomUUID()});toast('已保存资料，正在重新检查门禁。');await load()}catch(error){state.error=error.message}finally{state.busy=false;repaint()}
    }
  });
  document.addEventListener('click',async event=>{
    const el=event.target.closest('[data-org-action]');if(!el||state.busy)return;event.stopImmediatePropagation();const action=el.dataset.orgAction;const form={currency:document.querySelector('#org-currency')?.value.trim().toUpperCase(),project:document.querySelector('#org-project-id')?.value.trim()};state.busy=true;repaint();
    try{
      if(action==='binding-load'){}
      else if(action==='binding-refresh'){const kind=el.dataset.kind;state.bindings[kind]=(await api('commerce_organization_exchange_status',{case_id:state.bindings[kind].case_id})).context;toast('已更新绑定范围；请重新核对本页参数与商品。')}
      else if(action==='exchange-sync'){await api('commerce_organization_exchange_sync',state.caseId?{case_id:state.caseId}:{});toast('已同步已有产物，不重新提交模型任务。')}
      else if(action==='bind-images'){if(!state.scopeReviewed)throw Error('请先核对所选素材与工作项的对应关系');const context=(await api('commerce_organization_exchange_status',{case_id:state.caseId})).context;await api('commerce_organization_exchange_bind_images',{context,project_id:state.projectId,asset_ids:[...state.assets],include_new_images:false});toast('已保存图片交接绑定，可重复同步并校验文件。')}
      else if(action==='import')await api('commerce_organization_import_inventory');
      else if(action==='currency'){const currency=form.currency;await api('commerce_organization_currency',{case_id:state.caseId,currency})}
      else if(action==='capture'){await api('commerce_organization_capture',state.caseId?{case_id:state.caseId}:{});toast('已保存私有 JSON、Markdown 和 HTML 体检快照。')}
      else if(action==='export')download(JSON.stringify(state.board,null,2),'organization-board.json');
      else if(action==='brief'){const brief=await api('commerce_organization_brief',{case_id:state.caseId,stage_id:el.dataset.stage});download(JSON.stringify(brief,null,2),el.dataset.stage+'-brief.json')}
      else if(action==='handoff'){await api('commerce_organization_handoff',{case_id:state.caseId,stage_id:el.dataset.stage});toast('已创建或复用本地补齐任务；门禁尚未因此关闭。')}
      else if(action==='cost'){const base=getCostBase();if(base.origin!=='manual')throw Error('成本表当前是演示资料，请核对真实来源后填写');await api('commerce_organization_record',{case_id:state.caseId,kind:'economics',payload:base.input,idempotency_key:crypto.randomUUID()});toast('已保存测算输入；缺项和币种不一致会保留。')}
      else if(action==='template'){
        const c=state.board.case;let payload;
        if(state.kind==='research'){const spec=await api('commerce_collection_template',{platform:c.scope.platform});payload={sku:c.scope.sku,row_key:c.scope.row_key,record:{...spec.record,market:c.scope.market}}}
        else if(state.kind==='economics')payload={currency:c.currency,price:null,purchase_cost:null,domestic_shipping:null,packaging:null,fulfillment_cost:null,electronic_fee:null,commission_rate:null,payment_rate:null,return_rate:null,ad_rate:null};
        else payload={currency:c.currency,purchase_cost:null,lead_time_days:null,supplier:'',source_ref:''};
        download(JSON.stringify({case_id:c.id,kind:state.kind,scope:c.scope,payload},null,2),'organization-'+state.kind+'-template.json')
      }
      else if(action==='project'){state.projectId=form.project;state.project=await api('commerce_creative_get',{project_id:state.projectId});state.assets=[];state.scopeReviewed=false}
      else if(action==='deliver'){
        if(!state.scopeReviewed)throw Error('请先核对图片与当前工作项 SKU、变体的对应关系');
        const ids=[...state.assets];await api('commerce_organization_deliver',{case_id:state.caseId,project_id:state.projectId,asset_ids:ids,idempotency_key:crypto.randomUUID()});toast('图片与清单已交付到本机工作项，正在核验交付文件。')
      }
      if(['template','export','brief','project'].includes(action)){state.busy=false;state.error='';repaint()}else await load();
    }catch(e){state.error=e.message;state.busy=false;repaint()}
  });
  return {load,render,bindingView,produce,afterTranslation,receiptHtml};
};
