/* Product surface: same domain identities and components in browser and native iframe. */
(() => {
  'use strict';
  const root = document.getElementById('product-app');
  if (!root) return;
  const ui = window.CommerceUI, esc = ui.escape, researchContext = window.CommerceResearchContext;
  const bootstrap = window.__COMMERCE_WORKSPACE_BOOTSTRAP__ || {};
  const reactHost = bootstrap.reactHost === true;
  const embedded = bootstrap.embedded === true && !reactHost;
  const bridged = bootstrap.embedded === true || bootstrap.bridge === true;
  const hosted = bootstrap.hosted === true || reactHost;
  const navigation = [['运营台','运营台','overview','grid'],['商品','商品工作区','workspace','box'],['店铺管理','店铺管理','orders','store'],['内容','创意工作室','creative','image'],['情报','全球情报','intelligence','book'],['任务','任务中心','tasks','clock'],['能力库','能力库','skills','bolt']];
  const nonce = '__COMMERCE_BRIDGE_NONCE__', pending = new Map();
  const tabs = {overview:'概览',research:'市场研究',cost:'成本测算',content:'商品内容',review:'方案审阅',tasks:'任务记录'};
  const fields = {currency:'币种',price:'销售单价',purchase_cost:'采购成本',domestic_shipping:'境内运费',packaging:'包装成本',fulfillment_cost:'履约费用',electronic_fee:'其他平台费用',commission_rate:'佣金比例',payment_rate:'支付比例',return_rate:'退货比例',ad_rate:'广告比例'};
  const listingFields = {sku:'SKU',title:'标题',description:'商品描述',category_id:'类目 ID',price:'售价',currency:'币种',quantity:'数量',image_refs:'素材引用'};
  const itemLabel = c => c.name+(s.items.filter(x=>x.name===c.name).length>1?' · '+(platformNames[c.platform]||c.platform)+' / '+(c.market||'市场待核对')+' · '+c.id.slice(0,8):'');
  const platformNames = {ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu'};
  const s = {id:bootstrap.case_id || new URL(location.href).searchParams.get('case_id') || '',tab:'overview',items:[],data:null,busy:false,error:'',errorCode:'',generation:0,edits:{},dirty:new Set(),changes:0,mobile:'product',chatVisible:true,fieldErrors:{},opener:null,dialogAction:null};
  s.researchTaskId=bootstrap.research_task_id||(!bridged?new URL(location.href).searchParams.get('research_task_id'):'')||'';s.researchSequence=0;s.researchLoading=false;s.researchContextError='';
  let copilot, applyChatWidth, viewQueue=Promise.resolve();
  s.actionEpoch=0;
  const btn = (label,action,primary=false,attrs={}) => ui.button({label,leadingIcon:attrs.icon||'',variant:attrs.quiet?'quiet':primary?'primary':'secondary',attrs:{'data-pw-action':action,...attrs}});
  const alert = (text,tone='info') => ui.alert(text,tone);
  const empty = text => `<div class="pw-empty" role="status">${esc(text)}</div>`;
  const stamp = value => value ? new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}) : '未提供';
  const decimal = value => Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
  const amount = (value,currency) => value == null ? '待补充' : `${decimal(value)} ${esc(currency || '币种待核对')}`;
  const json = value => JSON.stringify(value,null,2);
  function message(error) {
    const code = error.code || error.message;
    const known = {workspace_research_context_invalid:'研究链接无效，请从原研究任务重新打开。',workspace_research_context_mismatch:'本次研究与商品不匹配，请从原研究任务重新打开。',workspace_research_artifact_invalid:'本次研究快照完整性检查未通过，请回原研究核对。',workspace_research_context_unavailable:'本次研究快照未读回，请回原研究核对。当前商品输入仍保留。',agent_evidence_reference_required:'模型答复缺少来源引用，未采纳本轮结果；核对资料后可明确发送新问题。',workspace_source_changed:'资料已更新，输入已保留。请核对后重新保存。',form_draft_conflict:'草稿已有新版本，输入已保留。请核对后合并。',organization_case_not_found:'当前连接中找不到这个工作项。请核对连接与商品范围。',workspace_content_checkpoint_required:'请先保存当前内容编辑，再生成待审阅版本。',workspace_currency_required:'请先明确工作项币种，并使用相同币种测算。',workspace_artifact_changed:'原产物完整性检查未通过，请先核对来源。',workspace_handoff_held:'成本产物交接尚未确认，请核对原记录。',business_preflight_incomplete:'草稿仍有缺项、无效引用或过期来源，请补齐后再审阅。',business_draft_changed:'草稿版本已变化，请重新读取并审阅。',agent_provider_outcome_unknown:'模型结果尚未确认。请核对原请求记录，不会自动重发。',agent_model_setup_required:'当前模型入口尚未配置，请完成本机接入后继续。',agent_current_evidence_required:'当前依据不足或已改变，请重新核对来源后再分析。',authentication_required:'本次连接没有有效授权，请通过项目正常入口重新打开。',unknown_tool:'当前后台尚未加载商品工作区接口，请核对运行版本。',commerce_service_unavailable:'共享后台暂不可用。输入已保留，请恢复连接后查询原记录。'};
    if (known[code]) return known[code];
    if (code.startsWith('invalid_')) return '请核对输入的格式、数值范围、币种及单位。';
    return '本次操作未完成，当前输入已保留。请核对连接或展开技术详情。';
  }
  async function api(tool,args={}) {
    if (bridged) return new Promise((resolve,reject) => {
      const id = crypto.randomUUID();
      const timer = setTimeout(() => {pending.delete(id);const e=Error('commerce_service_unavailable');e.code=e.message;reject(e)},20000);
      pending.set(id,{resolve,reject,timer});
      parent.postMessage({type:'commerce:call',nonce,id,tool,arguments:args},'*');
    });
    const response = await fetch('/v1/invoke',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'browser'})});
    const result = await response.json();
    if (!response.ok) {const error=Error(result.error||'commerce_service_unavailable');error.code=error.message;throw error}
    return result;
  }
  window.addEventListener('message',event => {
    if (!bridged || event.source!==parent || event.data?.nonce!==nonce) return;
    const m=event.data;
    if(m.type==='commerce:workspace-research-context'&&m.case_id===s.id&&typeof m.research_task_id==='string'){if(m.research_task_id!==s.researchTaskId)loadResearchContext(m.research_task_id);return;}
    if(reactHost&&m.type==='commerce:workspace-assistant-toggle'){if(innerWidth<1024)s.mobile=s.mobile==='chat'?'product':'chat';else s.chatVisible=!s.chatVisible;applyMobile();return;}
    if(reactHost&&m.type==='commerce:workspace-layout'){if(typeof m.chat_width==='number'&&Number.isFinite(m.chat_width)&&m.chat_width>=320&&m.chat_width<=960){s.hostChatWidth=m.chat_width;applyChatWidth?.(m.chat_width)}return;}
    if (m.type==='commerce:theme' && ['light','dark','system'].includes(m.theme)) {ui.applyTheme(m.theme);return}
    if(reactHost&&m.type==='commerce:workspace-tab') {if(Object.hasOwn(tabs,m.tab))selectTab(m.tab);return}
    if(reactHost&&m.type==='commerce:workspace-refresh') {
      if(!s.id||(m.case_id&&m.case_id!==s.id))return;
      const caseId=s.id;
      const reply=status=>parent.postMessage({type:'commerce:workspace-refresh-result',nonce,case_id:caseId,status},'*');
      // Reading a new base while edits exist would silently rebase their CAS revision.
      if(s.busy||s.dirty.size){announce('当前输入已保留，请核对并保存后刷新商品资料。');if(s.dirty.size){s.error='商品资料待刷新，当前输入已保留。请先核对当前版本，再继续保存。';s.errorCode='workspace_refresh_deferred';render()}reply('deferred');return}
      const generation=s.generation+1;
      reload({select:caseId}).then(status=>reply(s.generation!==generation||s.id!==caseId?'superseded':status));
      return;
    }
    if (m.type!=='commerce:result') return;
    const request=pending.get(m.id);if(!request)return;
    clearTimeout(request.timer);pending.delete(m.id);
    if(m.error){const error=Error(m.error);error.code=m.error;request.reject(error)}else request.resolve(m.result);
  });
  function announce(text) {document.getElementById('pw-announcement').textContent=text}
  function closeDialog() {
    root.inert=false;
    document.getElementById('modal-root').innerHTML='';s.dialogAction=null;
    s.opener?.focus?.({preventScroll:true});
  }
  function dialog(title,body,actions='',callback=null) {
    s.opener=document.activeElement;s.dialogAction=callback;root.inert=true;
    document.getElementById('modal-root').innerHTML=ui.modal({title,body,actions});
    document.querySelector('.dialog button')?.focus();
  }
  function modelContext() {
    const c=s.data?.case;
    return c?{module:'organization',demo:c.scope.synthetic===true,platform:c.scope.platform,market:c.scope.market,entity:{kind:'case',id:c.id}}:{module:'organization',demo:false};
  }
  function renderChat() {
    const host=document.getElementById('pw-chat');if(!host||!copilot)return;
    host.innerHTML=copilot.view();copilot.afterPaint();
  }
  function shell() {
    document.documentElement.dataset.embedded=String(embedded);
    root.innerHTML=`<div class="pw-frame ${embedded?'pw-embedded':''} ${hosted?'pw-hosted':''} ${reactHost?'pw-react-host':''}">
      ${embedded?'':`<aside class="pw-sidebar" aria-label="平台导航"><a class="pw-brand" href="/"><span>${ui.icon('store')}</span><strong>AI 跨境运营平台</strong></a><nav>${navigation.map(([,label,tab,icon])=>[label,tab,icon]).map(([label,tab,icon])=>`<a href="/?tab=${tab}" class="${tab==='workspace'?'active':''}">${ui.icon(icon)}<span>${label}</span></a>`).join('')}</nav><div class="pw-sidebar-bottom"><a href="/">${ui.icon('grid')}完整运营后台</a></div></aside>`}
      <div class="pw-body">${embedded?'':`<header class="pw-topbar">${!reactHost?`<nav class="pw-business-nav" aria-label="平台业务导航">${navigation.map(([short,label,tab,icon])=>`<button class="ui-button" data-pw-action="navigate" data-tab="${tab}" aria-label="${label}" ${tab==='workspace'?'aria-current="page"':''}>${ui.icon(icon)}<span>${short}</span></button>`).join('')}</nav>`:''}<span class="pw-topbar-title">商品工作区</span><div>${ui.field('外观',ui.select({id:'pw-theme','aria-label':'界面主题',value:ui.getTheme().preference,options:[{value:'system',label:'跟随系统'},{value:'light',label:'浅色'},{value:'dark',label:'深色'}]}))}</div></header>`}
      <div class="pw-mode-switch" role="group" aria-label="工作视图">${btn('AI 对话','mobile-chat')}${btn('商品工作区','mobile-product')}</div>
      <div class="pw-columns"><section class="pw-conversation" aria-label="AI 业务对话"><div id="pw-chat"></div></section>${embedded?'':'<div class="pw-splitter" role="separator" tabindex="0" aria-orientation="vertical" aria-label="调整对话区宽度" aria-controls="pw-chat pw-main" aria-valuemin="320" aria-valuemax="640" aria-valuenow="480"></div>'}<main class="pw-main" id="pw-main" aria-busy="true"><div id="pw-product"></div></main></div></div></div>`;
    if(!embedded){
      copilot=window.CommerceCopilot({api,ui,toast:announce,modal:dialog,closeModal:closeDialog,getContext:modelContext,inline:true,compact:true,onModels:()=>{if(bridged)parent.postMessage({type:'commerce:workspace-navigate',nonce,tab:'models'},'*');else location.assign('/workspace?tab=models')},onResearch:id=>{if(bridged)parent.postMessage({type:'commerce:workspace-research',nonce,task_id:id},'*');else location.assign('/workspace?tab=pilots&research_task_id='+encodeURIComponent(id))},onOpenCandidate:openResearchCandidate,onWorkspace:()=>{if(s.data)selectTab('cost');else{if(innerWidth<1024){s.mobile='product';applyMobile()}document.querySelector('#pw-case')?.focus()}},renderContext:taskSummary,errorText:message,scopeLabel:c=>[platformNames[c?.platform]||c?.platform,c?.market,s.items.find(x=>x.id===c?.entity?.id)?.name||(c?.entity?.id?'工作项 '+c.entity.id.slice(0,8):''),c?.demo?'合成示例':'本机资料 · 待核实'].filter(Boolean).join(' · '),repaint:renderChat});
      if(innerWidth>=1024)copilot.open(undefined,{focus:false});
    }
    applyMobile();
    setupSplitter();
    if(!reactHost&&visualViewport){const updateKeyboard=()=>{root.dataset.keyboardOpen=String(innerWidth<=767&&visualViewport.scale===1&&document.documentElement.clientHeight-visualViewport.height>150)};visualViewport.addEventListener('resize',updateKeyboard);updateKeyboard();}
  }
  function setupSplitter() {
    const handle=document.querySelector('.pw-splitter');if(!handle)return;
    const columns=handle.parentElement;let origin=0,initial=480;
    const limits=()=>({min:320,max:Math.max(320,Math.min(columns.clientWidth>=1800?960:640,Math.round((columns.clientWidth-24)*.5),columns.clientWidth-514))});
    const set=(value,save=true)=>{const {min,max}=limits();value=Math.round(Math.max(min,Math.min(max,value)));columns.style.setProperty('--pw-chat-width',value+'px');handle.setAttribute('aria-valuenow',String(value));handle.setAttribute('aria-valuemax',String(max));if(save){if(reactHost){s.hostChatWidth=value;parent.postMessage({type:'commerce:workspace-chat-width',nonce,width:value},'*')}else try{localStorage.setItem('commerce-product-chat-width-v2',String(value))}catch{}}};
    const preferred=()=>{if(reactHost&&s.hostChatWidth)return s.hostChatWidth;try{return Number(localStorage.getItem('commerce-product-chat-width-v2'))||Math.round((columns.clientWidth-24)*.38)}catch{return Math.round((columns.clientWidth-24)*.38)}};
    applyChatWidth=value=>set(value,false);
    set(preferred(),false);
    handle.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();origin=e.clientX;initial=Number(handle.getAttribute('aria-valuenow'));handle.setPointerCapture(e.pointerId);handle.classList.add('dragging')});
    handle.addEventListener('pointermove',e=>{if(handle.hasPointerCapture(e.pointerId))set(initial+e.clientX-origin)});
    const end=e=>{if(handle.hasPointerCapture(e.pointerId))handle.releasePointerCapture(e.pointerId);handle.classList.remove('dragging')};
    handle.addEventListener('pointerup',end);handle.addEventListener('pointercancel',end);
    handle.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const {min,max}=limits();set(e.key==='Home'?min:e.key==='End'?max:Number(handle.getAttribute('aria-valuenow'))+(e.key==='ArrowRight'?16:-16))});
    new ResizeObserver(()=>{if(innerWidth>=1024&&columns.clientWidth>0)set(preferred(),false)}).observe(columns);
  }
  function applyMobile() {
    root.dataset.mobileView=s.mobile;root.dataset.chatVisible=String(s.chatVisible);
    if(reactHost)parent.postMessage({type:'commerce:workspace-assistant-state',nonce,visible:innerWidth<1024?s.mobile==='chat':s.chatVisible},'*');
    const compact=!embedded&&innerWidth<1024;
    if(copilot){if((compact&&s.mobile==='product')||(!compact&&!s.chatVisible))copilot.close();else if(!document.querySelector('#commerce-copilot:not([hidden])'))copilot.open(undefined,{focus:false})}
    document.querySelector('[data-pw-action="mobile-chat"]')?.setAttribute('aria-pressed',String(s.mobile==='chat'));
    document.querySelector('[data-pw-action="mobile-product"]')?.setAttribute('aria-pressed',String(s.mobile==='product'));
  }
  function formData(name) {return s.edits[name] || s.data?.forms[name]?.payload || (name==='cost'?{input:s.data?.artifacts.economics?.payload||{}}:name==='plan'?{goal:'',steps:[]}:{source_id:'',fields:{}})}
  function formStatus(name) {
    const f=s.data.forms[name];const value=s.dirty.has(name)?'<span class="pw-unsaved">未保存</span>':f.stale?ui.badge('依据已变更','warning'):f.revision?'<span class="pw-meta">已保存 · 修订 '+f.revision+'</span>':'';return `<span data-pw-form-status="${name}">${value}</span>`;
  }
  function section(title,content,actions='',attrs='') {actions=actions.replaceAll('class="ui-button ','class="ui-button link-btn ');return `<section class="pw-section" ${attrs}><header class="pw-section-header"><h2>${title}</h2>${actions}</header>${content}</section>`}
  function workflow() {
    if(!s.data)return [];
    const d=s.data,gate=id=>d.stages.find(x=>x.id===id),draft=d.content_drafts[0];
    const checked=id=>gate(id)?.status==='PASS';
    const stage=(id,title,target)=>{const g=gate(id),status=g?.status;return {id,title,target,label:({PASS:'检查通过',FAIL:'需处理',HOLD:'待核对',BLOCKED:'依赖待补'})[status]||'待读取',tone:status==='PASS'?'success':status==='FAIL'?'danger':'warning',complete:status==='PASS'}};
    const rows=[stage('S1','研究与资料核对','research'),stage('S3','供应与报价','research')];
    const valid=d.calculation.status==='CALCULATED'&&!d.calculation.stale&&!s.dirty.has('cost');
    rows.push({id:'calculation',title:'成本测算与定价',target:'cost',label:valid?'已测算':s.dirty.has('cost')?'待重算':'待补参数',tone:valid?'blue':'warning',complete:valid,hint:valid&&!checked('S2')?'来源门禁待复核':''});
    const contentCurrent=draft?.preflight.status==='current',mediaReady=d.artifacts.images?.intact===true;
    rows.push({id:'content',title:'商品内容与素材',target:'content',label:!draft?'待准备':!contentCurrent?'来源已变化':!draft.preflight.ready_for_local_review?'待补内容':!mediaReady?'待补素材':'草稿已备',tone:draft&&contentCurrent&&draft.preflight.ready_for_local_review&&mediaReady?'blue':'warning',complete:!!draft&&contentCurrent&&draft.preflight.ready_for_local_review&&mediaReady,hint:draft&&contentCurrent&&draft.preflight.ready_for_local_review&&!mediaReady?'内容草稿已保存':''});
    const reviewed=draft?.status==='local_review_recorded'&&contentCurrent;
    rows.push({id:'review',title:'方案审阅与交付',target:'review',label:reviewed?'已记录':draft?.preflight.ready_for_local_review?'待审阅':'待准备',tone:reviewed?'success':'gray',complete:reviewed});
    return rows;
  }
  function pendingItems(limit=3) {
    const seen=new Set();
    return s.data.stages.filter(v=>['S1','S3','S2','S4','S5'].includes(v.id)).flatMap(v=>v.gaps).filter(g=>{
      if(String(g.reason).startsWith('上游 ')||seen.has(g.reason))return false;seen.add(g.reason);return true;
    }).slice(0,limit);
  }
  const pendingLabel=reason=>reason.includes('译文待校对')?'研究资料、译文或范围待核对':({'缺少 research 岗位产物':'研究资料待补充','缺少 supply 岗位产物':'供应与报价待补充','缺少 images 岗位产物':'商品素材待补充','缺少 economics 岗位产物':'成本测算产物待补充'}[reason]||reason);
  function taskSummary() {
    const d=s.data;if(!d)return '';
    const plan=formData('plan'),rows=workflow(),pending=pendingItems(2),tasks=d.tasks;
    return `<section class="pw-task-summary"><header><div><strong>${esc(d.name)} · 商品推进</strong></div>${btn(plan.steps.length?'目标 · '+plan.steps.length+' 步':'目标','goal',false,{quiet:true})}</header>${plan.goal?`<p class="pw-task-goal">${esc(plan.goal)}</p>`:''}<ol class="pw-workflow">${rows.map((row,i)=>`<li class="${row.complete?'is-ready':''}" data-workflow-stage="${row.id}"><span class="pw-step-index">${i+1}</span><div>${btn(row.title,'tab-'+row.target,false,{quiet:true,title:row.hint||row.title})}</div>${ui.badge(row.label,row.tone)}</li>`).join('')}</ol>${pending.length?`<div class="pw-task-pending"><strong>待处理</strong><ul>${pending.map(g=>`<li title="${esc(g.reason)}">${esc(pendingLabel(g.reason))}</li>`).join('')}</ul></div>`:''}<footer><span>${tasks.length?tasks.length+' 个关联任务':'尚无关联任务'}</span>${btn('任务记录','tab-tasks',false,{quiet:true})}</footer></section>`;
  }
  function header() {
    const d=s.data,c=d.case,scope=c.scope,hasContent=d.content_drafts.length>0;
    const next=!d.artifacts.research?['补充研究','tab-research']:d.calculation.status!=='CALCULATED'?['下一步：成本测算','tab-cost']:[hasContent?'审阅方案':'准备内容',hasContent?'tab-review':'tab-content'];
    return `<header class="pw-object-header"><span class="pw-object-symbol">${ui.icon('box')}</span><div class="pw-object-title"><div class="pw-title-row"><h1 title="${esc(d.name)}">${esc(d.name)}</h1>${btn('','choose-product',false,{quiet:true,icon:'chevronDown','aria-label':'切换商品',title:'切换商品',disabled:s.busy})}</div><div class="pw-object-meta"><span>${esc(platformNames[scope.platform]||scope.platform)} · ${esc(scope.market||'市场待核对')}</span>${scope.synthetic===true?ui.badge('合成数据','gray'):scope.origin==='research_candidate_not_inventory'?ui.badge('调研候选','gray'):''}<span>${esc(c.currency||'币种待核对')}</span>${scope.sku?`<span>SKU · ${esc(scope.sku)}</span>`:''}</div></div><div class="pw-header-actions">${s.tab==='overview'?btn(next[0],next[1],true,{disabled:s.busy}):''}${btn('','more',false,{quiet:true,icon:'more','aria-label':'更多商品操作',title:'更多商品操作'})}</div></header><nav class="pw-tabs" role="tablist" aria-label="商品工作区内容">${Object.entries(tabs).map(([key,label])=>`<button role="tab" type="button" data-pw-tab="${key}" id="pw-tab-${key}" aria-controls="pw-tabpanel" aria-selected="${key===s.tab}" tabindex="${key===s.tab?'0':'-1'}">${label}</button>`).join('')}</nav>`;
  }
  function researchControls(){
    const context=s.data.research_context,refs=s.data.research_contexts||[];
    if(!context&&!s.researchTaskId&&!refs.length)return '';
    const options=[{value:'',label:'商品当前研究'},...refs.map(ref=>({value:ref.task_id,label:'研究快照 · '+ref.task_id.slice(0,8)}))];
    if(s.researchTaskId&&!options.some(option=>option.value===s.researchTaskId))options.push({value:s.researchTaskId,label:'指定研究 · '+s.researchTaskId.slice(0,8)});
    const selected=s.researchTaskId||context?.task_id;
    return `<div class="pw-research-context">${ui.field('研究记录',ui.select({id:'pw-research-context',value:s.researchTaskId,options,disabled:s.busy||s.researchLoading}))}<div class="pw-inline-meta">${ui.badge(context?.is_current_artifact===false?'历史研究快照':'研究快照','gray')}<span>只读</span>${selected?btn('回到原研究','research-task',false,{'data-task':selected}):''}</div></div>`;
  }
  function reportResearchSelection(){
    if(bridged)parent.postMessage({type:'commerce:workspace-selected',nonce,case_id:s.id,research_task_id:s.researchTaskId},'*');
    else{const url=new URL(location.href);if(s.researchTaskId)url.searchParams.set('research_task_id',s.researchTaskId);else url.searchParams.delete('research_task_id');history.replaceState(null,'',url)}
  }
  async function loadResearchContext(taskId){
    const selectedCase=s.id,sequence=++s.researchSequence;s.tab='research';s.researchTaskId=taskId;s.researchContextError='';
    if(!s.data){if(s.id)await reload({select:s.id,researchTaskId:taskId});return;}
    s.researchLoading=true;render();
    try{const requested=researchContext.task(taskId),data=await api('commerce_workspace_get',{case_id:selectedCase,...(requested?{research_task_id:requested}:{})});if(sequence!==s.researchSequence||selectedCase!==s.id)return;s.data=researchContext.merge(s.data,data,requested);s.researchContextError='';reportResearchSelection()}
    catch(error){if(sequence===s.researchSequence&&selectedCase===s.id)s.researchContextError=message(error)}
    finally{if(sequence===s.researchSequence&&selectedCase===s.id){s.researchLoading=false;render()}}
  }
  function researchView(compact=false) {
    const controls=researchControls();
    if(s.researchLoading)return section('市场研究',controls+empty('正在读取研究快照…'));
    if(s.researchContextError)return section('市场研究',controls+alert(s.researchContextError,'danger'));
    let a;try{a=researchContext.artifact(s.data,s.researchTaskId)}catch(error){return section('市场研究',controls+alert(message(error),'danger'))}
    if(!a)return section('市场研究',controls+empty('尚无研究资料。')+(compact?'':gaps(['S1','S5'])),btn(compact?'补充资料':'导入资料',compact?'tab-research':'research-source'));
    const record=a.payload.record,priority=['description','attributes','specifications','title','price','reviews'];
    const rows=Object.entries(record.fields||{}).filter(([key,f])=>key!=='subject'&&(f.original||f.zh)).sort(([a],[b])=>(priority.includes(a)?priority.indexOf(a):99)-(priority.includes(b)?priority.indexOf(b):99));
    const unique=rows.filter(([,f],i)=>rows.findIndex(([,v])=>(v.zh||v.original)===(f.zh||f.original))===i);
    const labels={findings:'研究结论',limitations:'资料限制',title:'商品标题',description:'商品描述',price:'价格依据',reviews:'评价依据',specifications:'规格',attributes:'商品属性',availability:'可售范围',barcode:'条码',brand:'品牌',category:'类目',dimensions:'包装尺寸',weight:'重量',images:'素材',quantity:'数量',stock:'库存',sku:'SKU',name:'商品名称'};
    const state=!a.intact?'完整性异常':rows.every(([,f])=>f.reviewed)?'已校对':'待校对';
    if(compact)return section('市场研究 '+ui.badge(state,a.intact?'gray':'danger'),`${controls}${!a.intact?alert('资料完整性异常，请核对来源。','danger'):''}<dl class="pw-research-fields pw-research-brief">${(unique.filter(([k])=>k!=='title').length?unique.filter(([k])=>k!=='title'):unique).slice(0,2).map(([key,f])=>`<div><dt>${esc(labels[key]||key)}</dt><dd><p class="pw-research-summary">${esc(f.zh||f.original)}</p></dd></div>`).join('')}</dl><div class="pw-research-note"><span>${esc(record.language||'')} · ${stamp(record.captured_at).split(' ')[0]}</span></div>`,btn('查看研究','tab-research'));
    return section('市场研究',`${controls}<div class="pw-inline-meta">${ui.badge(state,a.intact?'gray':'danger')}<span>${esc(record.language||'')} · ${stamp(record.captured_at)}</span></div>${!a.intact?alert('资料完整性异常，请核对来源。','danger'):''}<dl class="pw-research-fields">${unique.map(([key,f])=>`<div><dt>${esc(labels[key]||key)}</dt><dd><p>${esc(f.zh||f.original)}</p><details><summary>${f.reviewed?'原文与校对记录':'原文 · 待校对'}</summary>${f.zh?`<p lang="${esc(record.language||'en')}">${esc(f.original)}</p>`:''}<p>${esc(f.locator||'无定位信息')}</p></details></dd></div>`).join('')}</dl><details class="pw-disclosure"><summary>来源资料</summary><p class="pw-source-text">${esc(record.source_url||'来源未提供')}</p><p>${esc(record.raw_excerpt||'无原始摘录')}</p>${record.fields?.subject?`<p class="pw-source-text">研究需求：${esc(record.fields.subject.zh||record.fields.subject.original)}</p>`:''}<p class="pw-meta">资料尚未独立核实。</p></details>`,s.data.research_context?'':btn('补充资料','research-source'))+supplyView();
  }
  function supplyView(compact=false) {
    const a=s.data.artifacts.supply,p=a?.payload;
    if(!p)return section('供应与报价',empty('尚无报价资料。'),compact?btn('补充资料','research-source'):'');
    const rows=[['供应商',p.supplier],['采购报价',p.purchase_cost==null?'待补充':amount(p.purchase_cost,p.currency)],['交期',p.lead_time_days==null?'待补充':esc(p.lead_time_days)+' 天'],['报价来源',p.source_ref]];
    return section('供应与报价 '+ui.badge(a.intact?'待核实':'完整性异常',a.intact?'gray':'danger'),`<dl class="pw-evidence-grid">${rows.map(([label,value])=>`<div><dt>${label}</dt><dd>${label==='采购报价'?value:esc(value??'待补充')}</dd></div>`).join('')}</dl>`,compact?btn('查看资料','tab-research'):'');
  }
  function reviewSummary() {
    const draft=s.data.content_drafts[0];
    if(!draft)return section('审阅准备',empty('准备内容草稿后检查来源与字段。'),btn('准备内容','tab-content'));
    const c=draft.preflight;
    const checks=[['来源版本',c.status==='current'?'当前版本':'需更新',c.status==='current'],['必填与格式',c.missing_fields.length+c.invalid_fields.length?`${c.missing_fields.length+c.invalid_fields.length} 项待补充`:'已检查',!c.missing_fields.length&&!c.invalid_fields.length],['字段引用',c.uncited_fields.length?`${c.uncited_fields.length} 项待核对`:'引用齐备',!c.uncited_fields.length]];
    const calculation=s.data.calculation,fields=draft.draft.content.fields;
    if(calculation.status==='CALCULATED'&&!calculation.stale&&!s.dirty.has('cost')&&fields.price!=null&&fields.currency){
      const sameCurrency=fields.currency===calculation.currency,samePrice=sameCurrency&&Number(fields.price)===calculation.price;
      checks.push(['测算与草稿售价',samePrice?'相符':sameCurrency?'售价待核对':'币种待核对',samePrice]);
    }
    return section('审阅准备',`<dl class="pw-review-checks">${checks.map(([label,value,ok])=>`<div><dt>${label}</dt><dd>${ui.badge(value,ok?'success':'warning')}</dd></div>`).join('')}</dl><p class="pw-meta pw-review-boundary">仅记录本地审阅</p>`,btn('查看方案','tab-review'));
  }
  function gaps(ids) {
    const values=s.data.stages.filter(v=>ids.includes(v.id)).flatMap(v=>v.gaps.filter(g=>!String(g.reason).startsWith('上游 ')));
    return values.length?`<ul class="pw-gap-list">${values.slice(0,4).map(g=>`<li><span>${esc(g.reason)}</span><small>${esc(g.owner)} · ${esc(g.verify)}</small></li>`).join('')}</ul>`:'';
  }
  function costSummary(compact=false) {
    const r=s.data.calculation,dirty=s.dirty.has('cost'),valid=r.status==='CALCULATED'&&!r.stale&&!dirty;
    if(!valid){const state=r.stale?'依据已变更':dirty?'输入已修改':'待补充';const missing=(r.stale?[]:r.missing||[]).map(k=>fields[k]||k);return section('成本测算',`${ui.badge(state,'warning')}<p class="pw-muted">${r.stale?'核对来源后重新测算。':dirty?'保存后更新测算结果。':missing.length?`缺少${missing.length}项参数`:'尚未测算'}</p>${!compact&&missing.length?`<p class="pw-missing">${missing.map(esc).join('、')}</p>`:''}`,compact?btn('补充参数','tab-cost'):'')}
    const b=r.cost_breakdown,labels={purchase_cost:'采购',domestic_shipping:'境内运费',packaging:'包装',fulfillment_cost:'履约',electronic_fee:'其他平台费用',commission:'佣金',payment:'支付费用',returns:'退货费用',return:'退货费用',ad:'广告费用'};
    const rows=compact?[['采购成本',b.purchase_cost],['物流与履约',b.domestic_shipping+b.fulfillment_cost],['包装成本',b.packaging],['其他平台费用',b.electronic_fee],['佣金',b.commission],['支付 / 退货 / 广告',b.payment+(b.returns??b.return??0)+b.ad]]:Object.entries(b).map(([key,value])=>[labels[key]||key,value]);
    const percent=value=>r.price>0?(100*value/r.price).toLocaleString('zh-CN',{maximumFractionDigits:1})+'%':'—';
    return section('成本测算',`<div class="pw-cost-table-head"><span>成本构成（单件）</span><span>${esc(r.currency)}</span><span>售价占比</span></div><dl class="pw-cost-breakdown">${rows.map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${decimal(value)}</dd><dd class="pw-cost-share">${percent(value)}</dd></div>`).join('')}<div class="pw-total"><dt>总成本</dt><dd>${decimal(r.total_cost)}</dd><dd class="pw-cost-share">${percent(r.total_cost)}</dd></div><div><dt>测算售价</dt><dd>${decimal(r.price)}</dd><dd class="pw-cost-share">100%</dd></div><div class="pw-contribution ${r.contribution<0?'pw-negative':''}"><dt>单件贡献估算</dt><dd>${decimal(r.contribution)}</dd><dd class="pw-cost-share">${percent(r.contribution)}</dd></div></dl>`,compact?btn('调整参数','tab-cost'):'');
  }
  function costView() {
    const values=formData('cost').input,advanced=['payment_rate','return_rate','ad_rate'];
    const field=(key,label)=>'<div class="pw-form-field">'+ui.field(label+(key.endsWith('_rate')?'（0–1）':''),ui.input({id:'pw-cost-'+key,'data-pw-cost':key,value:values[key]??'',type:key==='currency'?'text':'number',step:key==='currency'?undefined:'any',min:key==='currency'?undefined:0,max:key.endsWith('_rate')?1:undefined,maxlength:key==='currency'?3:undefined,'aria-invalid':!!s.fieldErrors[key],'aria-describedby':s.fieldErrors[key]?'pw-error-'+key:'pw-cost-boundary'}))+(s.fieldErrors[key]?`<span class="pw-field-error" id="pw-error-${key}">${esc(s.fieldErrors[key])}</span>`:'')+'</div>';
    const missing=advanced.some(k=>values[k]===undefined||values[k]===''),extra=gaps(['S3','S2']);
    return `<div class="pw-cost-layout">${section('测算参数',`<form id="pw-cost-form"><div class="pw-input-grid">${Object.entries(fields).filter(([k])=>!advanced.includes(k)).map(([k,v])=>field(k,v)).join('')}</div><details class="pw-disclosure" ${missing?'open':''}><summary>支付、退货与广告费率</summary><div class="pw-input-grid">${advanced.map(k=>field(k,fields[k])).join('')}</div></details><p class="pw-meta" id="pw-cost-boundary">同币种金额；费率填 0–1。</p>${!s.data.case.currency||s.data.case.currency!==values.currency?btn('确认使用此币种','set-currency',false,{disabled:s.busy||!values.currency}):''}<div class="pw-form-actions">${btn('保存并测算','save-calculate',true,{disabled:s.busy})}${reactHost?btn('动态成本测算','dynamic-cost',false,{disabled:s.busy||s.dirty.has('cost'),title:s.dirty.has('cost')?'请先保存当前成本参数':'使用当前商品及来源版本'}):''}${formStatus('cost')}</div></form>`)}<div id="pw-cost-result">${costSummary()}${extra?`<details class="pw-disclosure"><summary>资料缺项</summary>${extra}</details>`:''}</div></div>`;
  }
  function contentView(compact=false) {
    const f=formData('content'),sources=s.data.content_sources,d=s.data.content_drafts[0];
    if(compact){
      if(!d)return section('商品内容',empty('尚无内容草稿。'),btn('准备草稿','tab-content'));
      const values=d.draft.content.fields,rows=[['SKU',values.sku],['类目',values.category_id],['售价',values.price==null?'待补充':amount(values.price,values.currency)],['数量',values.quantity],['素材引用',Array.isArray(values.image_refs)?values.image_refs.length+' 项':'待补充']];
      return section('商品内容',`<div class="pw-content-preview"><div class="pw-content-state"><span>已保存版本</span>${ui.badge(({local_review_recorded:'已审阅',needs_input:'待补充',ready_for_review:'待审阅',stale:'来源已变化',review_expired:'审阅已过期',rejected:'已退回'})[d.status]||'本地草稿','gray')}</div><strong>${esc(values.title||'标题待补充')}</strong><p>${esc(values.description||'描述待补充')}</p><dl class="pw-content-facts">${rows.map(([label,value])=>`<div><dt>${label}</dt><dd>${label==='售价'?value:esc(value??'待补充')}</dd></div>`).join('')}</dl></div>`,btn('编辑草稿','tab-content'));
    }
    return section('商品内容草稿',`${sources.length?`${ui.field('商品资料',ui.select({id:'pw-content-source',value:f.source_id||'',options:[{value:'',label:'选择当前商品的事实资料'},...sources.map(x=>({value:x.id,label:x.document.label+' · v'+x.version}))]}))}<div class="pw-form-actions">${btn('填入资料','fill-content',false,{disabled:!f.source_id||s.busy})}</div>`:alert('请先导入当前商品的事实资料。')}<form id="pw-content-form"><div class="pw-input-grid">${Object.entries(listingFields).map(([key,label])=>ui.field(label,key==='description'?`<textarea class="ui-control" id="pw-content-${key}" data-pw-content="${key}" rows="6">${esc(f.fields?.[key]??'')}</textarea>`:ui.input({id:'pw-content-'+key,'data-pw-content':key,type:key==='quantity'?'number':'text',min:key==='quantity'?0:undefined,value:Array.isArray(f.fields?.[key])?f.fields[key].join('\n'):f.fields?.[key]??''}))).join('')}</div><div class="pw-form-actions">${btn('保存并预览','preview-content',true,{disabled:s.busy||!f.source_id})}${btn('保存草稿','save-content',false,{disabled:s.busy})}${formStatus('content')}</div></form>`,d?btn('查看已保存版本','tab-review'):'');
  }
  function reviewView() {
    const drafts=s.data.content_drafts,draft=drafts[0];
    if(!draft)return section('方案审阅',empty('尚无可审阅的内容版本。保存内容草稿后生成待审阅版本。'),btn('准备商品内容','tab-content'));
    const previous=drafts.find(x=>x.id===draft.parent_id),check=draft.preflight,blocked=[...check.missing_fields,...check.invalid_fields,...check.uncited_fields];
    const fields=draft.draft.content.fields,old=previous?.draft.content.fields||{},keys=[...new Set([...Object.keys(fields),...Object.keys(old)])],changed=keys.filter(k=>JSON.stringify(fields[k])!==JSON.stringify(old[k]));
    const diffTable=names=>ui.table(['字段','此前版本','当前草稿'],names.map(k=>`<tr><th scope="row">${esc(listingFields[k]||k)}</th><td>${Object.hasOwn(old,k)?esc(format(old[k])):'新增'}</td><td>${Object.hasOwn(fields,k)?k==='price'?amount(fields[k],fields.currency):esc(format(fields[k])):'未填写'}</td></tr>`),'');
    return section('方案审阅',`<div class="pw-inline-meta">${ui.badge(({local_review_recorded:'本地审阅已记录',needs_input:'待补充',ready_for_review:'待审阅',stale:'来源已失效',rejected:'已退回'})[draft.status]||'待核对','gray')}<span>${stamp(draft.created_at*1000)}</span></div>${check.status!=='current'?alert('来源版本已变化，旧确认动作已撤下。请依据当前来源生成新版本。','warning'):''}${blocked.length?alert('待补充或核对字段：'+[...new Set(blocked)].map(k=>listingFields[k]||k).join('、'),'warning'):''}${previous?changed.length?diffTable(changed):empty('与上一版本内容一致。'):diffTable(keys)}${previous&&changed.length<keys.length?`<details class="pw-disclosure"><summary>全部字段 · ${keys.length} 项</summary>${diffTable(keys)}</details>`:''}<p class="pw-meta">仅审阅本地草稿，不提交平台。</p><div class="pw-form-actions">${btn('审阅此版本','review-confirm',true,{disabled:s.busy||!check.ready_for_local_review||draft.status==='local_review_recorded'})}${btn('退回修改','review-reject',false,{disabled:s.busy})}${btn('导出记录','export-content',false,{disabled:s.busy})}</div><details class="pw-disclosure"><summary>来源引用与原回执</summary><pre>${esc(json({sources:draft.draft.sources,receipts:draft.receipts,preflight:check}))}</pre></details>`);
  }
  const format = v => v==null?'尚无此前版本':Array.isArray(v)?v.join('\n'):typeof v==='object'?json(v):String(v);
  function tasksView() {
    return section('任务记录',s.data.tasks.length?`<div class="pw-task-list">${s.data.tasks.map(t=>`<article><div><h3>${esc(t.input?.title||'关联任务')}</h3></div>${ui.badge(ui.status(t.status).label,ui.status(t.status).tone)}${btn('核对回执','task-receipt',false,{'data-task-id':t.id})}</article>`).join('')}</div>`:empty('暂无关联任务。'));
  }
  function overview() {
    const r=s.data.calculation,valid=r.status==='CALCULATED'&&!r.stale&&!s.dirty.has('cost');
    const metrics=valid?[
      ['测算售价',decimal(r.price),r.currency,''],['单件总成本',decimal(r.total_cost),r.currency,''],['单件贡献估算',decimal(r.contribution),r.currency,r.contribution<0?'negative':'positive'],['贡献率估算',(r.contribution_rate*100).toLocaleString('zh-CN',{maximumFractionDigits:1})+'%','',r.contribution<0?'negative':'positive']
    ]:[];
    const summary=metrics.length?`<dl class="pw-summary-band">${metrics.map(([label,value,unit,tone])=>`<div class="${tone}"><dt>${label}</dt><dd><span>${value}</span> <small>${esc(unit)}</small></dd></div>`).join('')}</dl>`:'';
    return `${summary}<div class="pw-overview-grid"><div>${researchView(true)}${supplyView(true)}${reviewSummary()}</div><div>${costSummary(true)}${contentView(true)}</div></div>`;
  }
  function render() {
    const host=document.getElementById('pw-product');if(!host)return;
    document.getElementById('pw-main').setAttribute('aria-busy',String(s.busy));
    if(!s.data){host.innerHTML=`<div class="pw-start"><h1>商品工作区</h1>${s.error?alert(s.error,'danger'):empty(s.busy?'正在读取商品工作项…':s.items.length?'选择一个已有商品，继续原工作。':'当前连接尚无商品工作项。')}${s.items.length?ui.field('商品工作项',ui.select({id:'pw-case',value:'',options:[{value:'',label:'选择已有商品'},...s.items.map(c=>({value:c.id,label:itemLabel(c)}))]})):''}<div class="pw-form-actions">${btn('重新读取','refresh')}${btn('打开完整后台','backend')}</div></div>`;return}
    const focused=document.activeElement,focus=focused?.id,focusAction=focused?.dataset?.pwAction,start=focused?.selectionStart,end=focused?.selectionEnd;
    host.innerHTML=`${header()}${s.error?`<div class="pw-page-error">${alert(s.error,'danger')}<div class="pw-form-actions">${btn('核对当前版本','inspect-saved')}${btn('刷新资料','refresh')}</div><details><summary>技术详情</summary><code>${esc(s.errorCode)}</code></details></div>`:''}<div id="pw-tabpanel" role="tabpanel" aria-labelledby="pw-tab-${s.tab}" tabindex="0" class="pw-tabpanel">${({overview,research:researchView,cost:costView,content:contentView,review:reviewView,tasks:tasksView})[s.tab]()}</div>`;
    const summary=document.querySelector('#copilot-log .pw-task-summary');if(summary)summary.outerHTML=taskSummary();
    if(focus||focusAction){const element=focus?document.getElementById(focus):document.querySelector('#pw-product [data-pw-action="'+focusAction+'"]');if(element){element.focus({preventScroll:true});if(start!=null&&element.setSelectionRange&&element.type!=='number')element.setSelectionRange(start,end)}}
  }
  async function reload({select=s.id,clearEditors=false,researchTaskId=select===s.id?s.researchTaskId:''}={}) {
    s.researchTaskId=researchTaskId;const researchSequence=++s.researchSequence;s.researchLoading=false;s.researchContextError='';
    const previousContext=JSON.stringify(modelContext()),restoreView=!s.data||select!==s.id,generation=++s.generation;s.busy=true;render();
    const current=()=>generation===s.generation&&researchSequence===s.researchSequence&&researchTaskId===s.researchTaskId;
    try {
      const list=await api('commerce_workspace_list');if(!current())return 'superseded';
      s.items=list.items;
      if(!select&&list.items.length===1)select=list.items[0].id;
      if(select){const requestedResearch=researchContext.task(researchTaskId),data=await api('commerce_workspace_get',{case_id:select,...(requestedResearch?{research_task_id:requestedResearch}:{})});if(!current())return 'superseded';researchContext.artifact(data,requestedResearch);s.id=select;s.data=data;if(restoreView){const requested=!bridged?new URL(location.href).searchParams.get('tab'):null;s.tab=requestedResearch?'research':tabs[requested]?requested:data.forms.view?.payload?.tab||'overview'}
        if(clearEditors){s.edits={};s.dirty.clear()}
        if(!bridged){const url=new URL(location.href);url.searchParams.set('case_id',select);history.replaceState(null,'',url)}
        if(!embedded&&previousContext!==JSON.stringify(modelContext()))copilot?.contextChanged();
        reportResearchSelection();
      }else{s.id='';s.data=null}
      s.error='';s.errorCode='';
      return 'refreshed';
    } catch(error){if(!current())return 'superseded';s.error=message(error);s.errorCode=error.code||error.message;return 'failed'}
    finally{if(generation===s.generation){s.busy=false;render()}}
  }
  function selectTab(tab) {if(!tabs[tab])return;s.tab=tab;if(!embedded&&innerWidth<1024&&s.mobile!=='product'){s.mobile='product';applyMobile()}if(!bridged){const url=new URL(location.href);url.searchParams.set('tab',tab);history.replaceState(null,'',url)}persistView(tab);render();document.getElementById('pw-tab-'+tab)?.focus({preventScroll:true});document.getElementById('pw-tab-'+tab)?.scrollIntoView({block:'nearest',inline:'nearest'})}
  function persistView(tab) {
    const id=s.id;if(!id)return;
    viewQueue=viewQueue.catch(()=>{}).then(async()=>{
      if(s.id!==id||s.tab!==tab||!s.data)return;const source=s.data.source_sha256;
      try{const value=await api('commerce_workspace_save',{case_id:id,form:'view',payload:{tab},expected_revision:s.data.forms.view.revision,expected_source_sha256:source});if(s.id===id&&s.data.source_sha256===source)s.data.forms.view={...value,stale:false}}
      catch(error){if(s.id===id)announce('视图位置尚未保存：'+message(error))}
    });
  }
  function dirty(name) {s.dirty.add(name);s.changes++;document.querySelectorAll('[data-pw-form-status="'+name+'"]').forEach(x=>{x.innerHTML='<span class="pw-unsaved">未保存</span>'});if(name==='content')document.querySelector('[data-pw-action="submit-content"]')?.setAttribute('disabled','');if(name==='cost'){const save=document.querySelector('[data-pw-action="save-calculate"]');if(save){save.disabled=false;save.classList.add('primary')}const result=document.getElementById('pw-cost-result');if(result)result.innerHTML=costSummary()}const summary=document.querySelector('#copilot-log .pw-task-summary');if(summary)summary.outerHTML=taskSummary();announce('输入已修改，旧结果不再作为当前结果')}
  async function saveForm(form) {
    const generation=s.generation,edit=s.changes,data=s.data,payload=structuredClone(formData(form));
    await api('commerce_workspace_save',{case_id:data.case.id,form,payload,expected_revision:data.forms[form].revision,expected_source_sha256:data.source_sha256});
    if(generation!==s.generation)return;
    if(edit===s.changes){s.dirty.delete(form);delete s.edits[form]}
    await reload();announce('已保存当前商品的'+({plan:'工作目标',cost:'测算输入',content:'编辑草稿'})[form]);
  }
  function openResearchCandidate(id,taskId='') {
    if(!id||s.busy)return;
    if(id===s.id){s.tab='research';loadResearchContext(taskId);return}
    const proceed=()=>{closeDialog();return reload({select:id,clearEditors:true,researchTaskId:taskId})};
    if(s.dirty.size)dialog('打开调研候选','<p>当前商品有未保存输入，请先返回保存，或明确放弃后打开候选。</p>',btn('放弃修改并打开','dialog-proceed')+btn('返回编辑','dialog-close'),proceed);
    else proceed();
  }
  function goalDialog() {
    const plan=formData('plan');
    dialog('工作目标',`${ui.field('本次目标',`<textarea class="ui-control" id="pw-goal" maxlength="2000" rows="4">${esc(plan.goal)}</textarea>`)}${ui.field('已确认的步骤（每行一步）',`<textarea class="ui-control" id="pw-steps" rows="5" maxlength="2000">${esc(plan.steps.map(x=>x.title).join('\n'))}</textarea>`)}<p class="pw-meta">保存目标与步骤不会自动派发任务。</p>`,btn('保存目标','save-plan',true)+btn('取消','dialog-close'));
  }
  function download(result) {const url=URL.createObjectURL(new Blob([result.content],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=result.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  async function act(action,target) {
    if(action==='research-task'){const taskId=target.dataset.task;if(taskId){if(bridged)parent.postMessage({type:'commerce:workspace-research',nonce,task_id:taskId},'*');else location.assign('/workspace?tab=pilots&research_task_id='+encodeURIComponent(taskId))}return;}
    if(action.startsWith('tab-')){selectTab(action.slice(4));return}
    if(action==='dialog-close'){closeDialog();return}
    if(action==='dialog-proceed'){const callback=s.dialogAction;closeDialog();await callback?.();return}
    if(action==='mobile-chat'||action==='mobile-product'){s.mobile=action==='mobile-chat'?'chat':'product';applyMobile();return}
    if(action==='navigate'){const tab=target.dataset.tab;if(!navigation.some(item=>item[2]===tab))return;closeDialog();if(bridged)parent.postMessage({type:'commerce:workspace-navigate',nonce,tab},'*');else location.assign('/?tab='+encodeURIComponent(tab));return}
    if(action==='dynamic-cost'){if(!reactHost||s.busy||s.dirty.has('cost')||!s.data?.case?.id)return;parent.postMessage({type:'commerce:workspace-dynamic-cost',nonce,case_id:s.data.case.id},'*');return}
    if(action==='backend'){if(bridged)parent.postMessage({type:'commerce:workspace-backend',nonce},'*');else location.assign('/');return}
    if(action==='more'){dialog('商品操作',`<div class="pw-action-menu">${btn('工作目标','goal')}${btn('来源与版本','source-details')}${btn('刷新资料','refresh')}${btn('完整后台','backend')}</div>`);return}
    if(action==='goal'){closeDialog();goalDialog();return}
    if(action==='choose-product'){if(s.busy)return;s.actionEpoch++;dialog('切换商品工作项',ui.field('商品工作项',ui.select({id:'pw-case',value:s.id,options:s.items.map(c=>({value:c.id,label:itemLabel(c)}))})));return}
    if(action==='source-details'){closeDialog();dialog('对象与依据',`<dl class="pw-source-detail"><dt>工作项</dt><dd>${esc(s.id)}</dd><dt>平台与市场</dt><dd>${esc(s.data.case.scope.platform)} · ${esc(s.data.case.scope.market)}</dd><dt>来源版本</dt><dd><code>${esc(s.data.source_sha256)}</code></dd></dl><p>AI 仅在明确请求后读取允许的资料；有工作项标识不代表所有资料已读或已核实。</p>`);return}
    if(action==='research-source'){dialog('研究资料入口',gaps(['S1','S5'])+`<p>在完整后台的调研采集或岗位交接中选择此工作项，保存产物后回到这里刷新。</p>`,btn('打开完整后台','backend')+btn('关闭','dialog-close'));return}
    if(action==='inspect-saved'){dialog('已保存的当前修订',`<p>请先核对当前修订；关闭窗口后仍保留你的输入。</p><pre>${esc(json(s.data.forms))}</pre>`,btn('读取最新修订','reload-dialog')+btn('关闭','dialog-close'));return}
    if(s.busy)return;
    const id=s.id,epoch=++s.actionEpoch,startTab=s.tab,current=()=>s.id===id&&s.actionEpoch===epoch;
    s.busy=true;s.error='';s.errorCode='';s.fieldErrors={};
    try {
      if(action==='refresh'){closeDialog();await reload();return}
      if(action==='reload-dialog'){closeDialog();await reload();return}
      if(action==='save-plan'){const goal=document.getElementById('pw-goal').value;const steps=document.getElementById('pw-steps').value.split('\n').map(x=>x.trim()).filter(Boolean).map(title=>({...formData('plan').steps.find(x=>x.title===title),title}));s.edits.plan={goal,steps};dirty('plan');closeDialog();await saveForm('plan')}
      if(action==='set-currency'){await api('commerce_workspace_currency',{case_id:s.id,currency:formData('cost').input.currency,expected_source_sha256:s.data.source_sha256});await reload();announce('已明确工作项币种；请按新范围保存测算输入')}
      if(action==='save-content')await saveForm('content');
      if(action==='save-calculate'){if(s.dirty.has('cost')||s.data.forms.cost.stale||!s.data.forms.cost.revision)await saveForm('cost');if(!current())return;const result=await api('commerce_workspace_calculate',{case_id:s.id,expected_source_sha256:s.data.source_sha256,expected_revision:s.data.forms.cost.revision});if(!current())return;await reload();announce(result.status==='HOLD'?'草稿已保存，请补齐参数':'测算已保存')}
      if(action==='fill-content'){
        const source=s.data.content_sources.find(x=>x.id===formData('content').source_id);if(!source)throw Error('workspace_source_outside_scope');
        s.edits.content={source_id:source.id,fields:Object.fromEntries(source.document.records.filter(x=>Object.hasOwn(listingFields,x.key)).map(x=>[x.key,x.value]))};dirty('content');
      }
      if(action==='preview-content'){if(s.dirty.has('content')||s.data.forms.content.stale||!s.data.forms.content.revision)await saveForm('content');if(!current())return}
      if(action==='preview-content'){
        if(s.dirty.has('content'))throw Error('workspace_content_checkpoint_required');
        const result=await api('commerce_workspace_submit_content',{case_id:id,expected_revision:s.data.forms.content.revision,expected_source_sha256:s.data.source_sha256});
        if(!current())return;await reload();if(!current())return;if(s.tab===startTab)selectTab('review');announce(result.preflight.ready_for_local_review?'已生成待审阅版本':'草稿已保存，仍有待补字段与引用');
      }
      if(action==='review-gaps'){selectTab('review')}
      if(action==='review-confirm'||action==='review-reject'){
        const draft=s.data.content_drafts[0],decision=action==='review-confirm'?'reviewed':'rejected';
        dialog(decision==='reviewed'?'记录本地审阅':'退回本地草稿',`<p>${esc(s.data.name)} · 版本 ${esc(draft.draft.draft_sha256.slice(0,12))}</p><p>仅记录这一份本地草稿的${decision==='reviewed'?'审阅':'退回'}。不会提交平台。</p>`,btn('确认记录','review-apply',true,{'data-draft-id':draft.id,'data-draft-sha':draft.draft.draft_sha256,'data-decision':decision,'data-review-key':crypto.randomUUID()})+btn('取消','dialog-close'));
      }
      if(action==='review-apply'){await api('commerce_business_review',{draft_id:target.dataset.draftId,expected_sha256:target.dataset.draftSha,decision:target.dataset.decision,confirmed:true,idempotency_key:'workspace-review:'+target.dataset.reviewKey});if(!current())return;closeDialog();await reload();if(!current())return;announce('已记录本地草稿审阅，不代表平台执行')}
      if(action==='export-content'){const result=await api('commerce_business_export',{draft_id:s.data.content_drafts[0].id});if(current())download(result)}
      if(action==='task-receipt'){const result=await api('commerce_task_result',{task_id:target.dataset.taskId});if(!current())return;dialog('原任务与回执',`<pre>${esc(json(result))}</pre><p>结果未知时先核对原回执，不会自动重发。</p>`)}
    } catch(error){if(!current())return;s.error=message(error);s.errorCode=error.code||error.message;const key=s.errorCode.replace(/^invalid_/,'');if(Object.hasOwn(fields,key))s.fieldErrors[key]='请核对'+fields[key]+'的格式或数值范围。';announce(s.error)}
    finally{if(current()){s.busy=false;render();if(document.activeElement===document.body){const restore=target?.id?document.getElementById(target.id):document.querySelector('[data-pw-action="'+(target?.dataset?.pwAction==='review-apply'?s.opener?.dataset?.pwAction:target?.dataset?.pwAction)+'"]');restore?.focus({preventScroll:true})}}}
  }
  document.addEventListener('click',event=>{const tab=event.target.closest('[data-pw-tab]');if(tab){selectTab(tab.dataset.pwTab);return}const action=event.target.closest('[data-pw-action]');if(action){event.preventDefault();act(action.dataset.pwAction,action).catch(error=>{s.error=message(error);s.errorCode=error.message;s.busy=false;render()})}else if(event.target.closest('.dialog [data-action="close"]'))closeDialog()});
  document.addEventListener('submit',event=>{if(event.target.id==='pw-cost-form'||event.target.id==='pw-content-form'){event.preventDefault();act(event.target.id==='pw-cost-form'?'save-calculate':'preview-content',event.target)}});
  document.addEventListener('input',event=>{
    const target=event.target;
    if(target.dataset.pwCost){const f=structuredClone(formData('cost'));const key=target.dataset.pwCost;if(target.value==='')delete f.input[key];else f.input[key]=key==='currency'?target.value.toUpperCase():Number(target.value);s.edits.cost=f;dirty('cost')}
    if(target.dataset.pwContent){const f=structuredClone(formData('content')),key=target.dataset.pwContent;f.fields[key]=key==='quantity'?(target.value===''?null:Number(target.value)):key==='image_refs'?target.value.split('\n').filter(Boolean):target.value;s.edits.content=f;dirty('content')}
  });
  document.addEventListener('change',event=>{
    if(event.target.id==='pw-research-context'){loadResearchContext(event.target.value);return;}
    if(event.target.id==='pw-case'){
      const selected=event.target.value,prior=s.id;if(!selected||s.busy)return;s.actionEpoch++;
      if(s.dirty.size){event.target.value=prior;dialog('切换商品',`<p>当前商品有未保存输入。可以返回保存，或明确放弃本页未保存修改后切换。</p>`,btn('放弃修改并切换','dialog-proceed')+btn('返回编辑','dialog-close'),()=>reload({select:selected,clearEditors:true}))}
      else {closeDialog();reload({select:selected,clearEditors:true})}
    }
    if(event.target.id==='pw-theme')api('commerce_ui_set_preferences',{theme:event.target.value}).then(()=>ui.applyTheme(event.target.value)).catch(error=>{s.error=message(error);render()});
    if(event.target.id==='pw-content-source'){s.edits.content={...structuredClone(formData('content')),source_id:event.target.value};dirty('content');render()}
  });
  document.addEventListener('keydown',event=>{
    const modal=document.querySelector('.dialog');
    if(modal){if(event.key==='Escape'){event.preventDefault();closeDialog();return}if(event.key==='Tab'){const nodes=[...modal.querySelectorAll('button:not(:disabled),input,textarea,select,[tabindex="0"]')].filter(x=>x.getClientRects().length);if(event.shiftKey&&document.activeElement===nodes[0]){event.preventDefault();nodes.at(-1)?.focus()}else if(!event.shiftKey&&document.activeElement===nodes.at(-1)){event.preventDefault();nodes[0]?.focus()}}return}
    const current=event.target.closest('[data-pw-tab]');if(current&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const keys=Object.keys(tabs),i=keys.indexOf(current.dataset.pwTab);selectTab(event.key==='Home'?keys[0]:event.key==='End'?keys.at(-1):keys[(i+(event.key==='ArrowRight'?1:-1)+keys.length)%keys.length])}
  });
  window.addEventListener('beforeunload',event=>{if(s.dirty.size){event.preventDefault();event.returnValue=''}});
  window.addEventListener('resize',applyMobile);
  shell();
  const initialLoad=reload();
  if(bridged){const ready=()=>parent.postMessage({type:'commerce:workspace-ready',nonce},'*');if(reactHost)initialLoad.finally(ready);else ready()}
  if(!embedded)api('commerce_ui_get_preferences').then(value=>{ui.applyTheme(value.theme);document.getElementById('pw-theme').value=value.theme}).catch(()=>{});
})();
