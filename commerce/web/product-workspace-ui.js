/* Product surface: same domain identities and components in browser and native iframe. */
(() => {
  'use strict';
  const root = document.getElementById('product-app');
  if (!root) return;
  const ui = window.CommerceUI, esc = ui.escape, researchContext = window.CommerceResearchContext;
  const bootstrap = window.__COMMERCE_WORKSPACE_BOOTSTRAP__ || {};
  const reactHost = bootstrap.reactHost === true;
  const embedded = bootstrap.embedded === true;
  const bridged = bootstrap.embedded === true || bootstrap.bridge === true;
  const hosted = bootstrap.hosted === true || reactHost;
  const navigation = [['运营台','运营台','overview','grid'],['商品','商品工作区','workspace','box'],['店铺管理','店铺管理','orders','store'],['内容','创意工作室','creative','image'],['情报','全球情报','intelligence','book'],['任务','任务中心','tasks','clock'],['能力库','能力库','skills','bolt']];
  const nonce = '__COMMERCE_BRIDGE_NONCE__', pending = new Map();
  const tabs = {overview:'概览',evidence:'证据与选品',research:'市场研究',cost:'成本测算',content:'商品内容',review:'方案审阅',tasks:'任务记录',media:'图片与视频'};
  const fields = {currency:'币种',price:'销售单价',purchase_cost:'采购成本',domestic_shipping:'境内运费',packaging:'包装成本',fulfillment_cost:'履约费用',electronic_fee:'其他平台费用',commission_rate:'佣金比例',payment_rate:'支付比例',return_rate:'退货比例',ad_rate:'广告比例'};
  const listingFields = {sku:'SKU',title:'标题',description:'商品描述',category_id:'类目 ID',price:'售价',currency:'币种',quantity:'数量',image_refs:'素材引用'};
  let quoteEdit=null,quoteError='',quoteEpoch=0,deliveryEdit=null,deliveryError='',deliveryNotice='',deliveryEpoch=0;
  let quoteComparison={caseId:'',quantity:'',result:null};
  const identity=window.CommerceProductIdentity;
  const itemLabel = c => identity.label(c,s.items);
  const platformNames = {ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu'};
  const s = {id:bootstrap.case_id || new URL(location.href).searchParams.get('case_id') || '',tab:'overview',items:[],data:null,busy:false,error:'',errorCode:'',generation:0,edits:{},dirty:new Set(),changes:0,mobile:'product',chatVisible:true,fieldErrors:{},opener:null,dialogAction:null};
  s.researchTaskId=bootstrap.research_task_id||(!bridged?new URL(location.href).searchParams.get('research_task_id'):'')||'';s.researchSequence=0;s.researchLoading=false;s.researchContextError='';
  function openCreativeMaster(value,fromCatalog=false){
    if(bridged)parent.postMessage({type:fromCatalog?'commerce:workspace-catalog-creative':'commerce:workspace-creative',nonce,...value},'*');
    else{const url=new URL('/workspace',location.href);url.searchParams.set('tab','creative');url.searchParams.set('creative_case_id',value.case_id);url.searchParams.set('creative_source',value.source_sha256);url.searchParams.set('creative_intent_id',crypto.randomUUID());if(value.project_id)url.searchParams.set('creative_project_id',value.project_id);location.assign(url);}
  }
  const catalog=window.CommerceCatalog({api,repaint:render,initialKind:'inventory',getFilters:()=>({synthetic:typeof bootstrap!=='undefined'&&bootstrap.demo===true}),onSelect:async id=>{if(hasPendingProductEdits()){s.error='当前商品有未保存输入，请先保存后再切换。';render();return}s.catalogOpen=false;await reload({select:id,clearEditors:true})},onCreative:async p=>{const generation=s.generation,request=crypto.randomUUID();s.catalogCreativeRequest=request;if(bridged)parent.postMessage({type:'commerce:workspace-catalog-creative-pending',nonce,id:request},'*');try{const project=p.brief?.product_binding?p:await api('commerce_creative_get',{project_id:p.id});if(generation!==s.generation||s.catalogCreativeRequest!==request)return;const binding=project?.brief?.product_binding;if(project?.id!==p.id||!binding?.case_id||!binding.source_sha256){s.error='内容项目关联尚未读回，请重新读取商品资料。';render();return;}openCreativeMaster({...binding,project_id:project.id,catalog_request_id:request},true);}catch{if(generation===s.generation&&s.catalogCreativeRequest===request){s.error='内容项目关联未能确认，请重新读取后打开。';render();}}}});
  const studio=window.CommerceProductCreativeLinks({api,repaint:render,getBinding:()=>s.data?{case_id:s.data.case.id,source_sha256:s.data.source_sha256}:null,onOpen:openCreativeMaster,formatProjectLabel:catalog.projectLabel});
  const evidence=window.CommerceProductEvidence?.({api,repaint:render,onDirty:evidenceEditStateChanged,formatProjectLabel:catalog.projectLabel,formatQuoteStatus:code=>quoteStates[code]||'待核对',onNavigate:action=>{if(action==='quotes')quoteDialog();else selectTab(action);},onImagePreview:(src,label)=>dialog('来源原图',`<figure><img style="display:block;max-width:100%;max-height:65vh;object-fit:contain;margin:auto" src="${esc(src)}" alt="${esc(label)}"><figcaption>${esc(label)} · 原始参考资料</figcaption></figure>`,btn('关闭','dialog-close'))});
  let copilot, applyChatWidth, viewQueue=Promise.resolve(),planEdit=null,modalEdited=false,lastEditState='',hostRefreshDeferred=false;
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
    const known = {copilot_page_scope_changed:'页面对象或店铺范围已变化，请重新核对后发送。输入已保留。',copilot_invalid_page_context:'页面资料未能安全带入，请刷新当前页面后重试。输入已保留。',agent_workspace_evidence_changed:'商品资料、报价或交付审阅版本已变化，请重新读取当前工作项。旧建议未提交，原记录保留。',workspace_research_context_invalid:'研究链接无效，请从原研究任务重新打开。',workspace_research_context_mismatch:'本次研究与商品不匹配，请从原研究任务重新打开。',workspace_research_artifact_invalid:'本次研究快照完整性检查未通过，请回原研究核对。',workspace_research_context_unavailable:'本次研究快照未读回，请回原研究核对。当前商品输入仍保留。',agent_evidence_reference_required:'模型答复缺少来源引用，未采纳本轮结果；核对资料后可明确发送新问题。',workspace_source_changed:'资料已更新，输入已保留。请核对后重新保存。',form_draft_conflict:'草稿已有新版本，输入已保留。请核对后合并。',organization_case_not_found:'当前连接中找不到这个工作项。请核对连接与商品范围。',workspace_content_checkpoint_required:'请先保存当前内容编辑，再生成待审阅版本。',workspace_currency_required:'请先明确工作项币种，并使用相同币种测算。',workspace_artifact_changed:'原产物完整性检查未通过，请先核对来源。',workspace_handoff_held:'成本产物交接尚未确认，请核对原记录。',business_preflight_incomplete:'草稿仍有缺项、无效引用或过期来源，请补齐后再审阅。',business_draft_changed:'草稿版本已变化，请重新读取并审阅。',agent_provider_outcome_unknown:'模型结果尚未确认。请核对原请求记录，不会自动重发。',agent_model_setup_required:'当前模型入口尚未配置，请完成本机接入后继续。',agent_current_evidence_required:'当前依据不足或已改变，请重新核对来源后再分析。',authentication_required:'本次连接没有有效授权，请通过项目正常入口重新打开。',unknown_tool:'当前后台尚未加载商品工作区接口，请核对运行版本。',commerce_service_unavailable:'共享后台暂不可用。输入已保留，请恢复连接后查询原记录。'};
    if (known[code]) return known[code];
    if(code==='workspace_quote_conflict')return '报价已有新版本，当前输入已保留。请重新读取并核对。';
    if(code==='invalid_quantity'||code==='workspace_quote_invalid_quantity')return '需求数量须为1至1,000,000,000件的整数。';
    if(code==='workspace_quote_not_ready')return '报价不完整、已过期或范围已变化，请核对当前报价后再选用或测算。';
    if(code==='workspace_quote_currency_mismatch')return '报价与工作项币种不同，请核对原币金额。';
    if(code.startsWith('workspace_quote_invalid_'))return '请核对报价字段、正数单位，以及带时区的有效期。';
    if(code==='workspace_delivery_review_conflict')return '审阅清单已有新版本，输入已保留。请核对当前记录。';
    if(code==='workspace_delivery_package_changed')return '交付内容或依据已经变化，请读取当前版本并重新核对。';
    if(code==='workspace_delivery_incomplete')return '当前内容、校对、图片、测算或人工核对仍有缺项，请先补齐。';
    if(code.startsWith('workspace_delivery_'))return '请核对交付清单的状态与依据；这次未完成审阅记录。';
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
    if(reactHost&&m.type==='commerce:workspace-resume'){requestAnimationFrame(revealActiveTab);const page=pageLocation?.snapshot();if(page)parent.postMessage({type:'commerce:page-context',nonce,page_context:page,context:modelContext()},'*');reportEditState(true);return;}
    if(reactHost&&m.type==='commerce:workspace-assistant-toggle'){if(innerWidth<1024)s.mobile=s.mobile==='chat'?'product':'chat';else s.chatVisible=!s.chatVisible;applyMobile();return;}
    if(reactHost&&m.type==='commerce:workspace-layout'){if(typeof m.chat_width==='number'&&Number.isFinite(m.chat_width)&&m.chat_width>=320&&m.chat_width<=960){s.hostChatWidth=m.chat_width;applyChatWidth?.(m.chat_width)}return;}
    if (m.type==='commerce:theme' && ['light','dark','system'].includes(m.theme)) {ui.applyTheme(m.theme);return}
    if(m.type==='commerce:workspace-creative-error'){s.error='内容项目关联未能确认，请重新读取后打开。';render();return;}
    if(reactHost&&m.type==='commerce:workspace-tab') {if(m.tab==='delivery'&&s.deliveryReturnCase===s.id&&deliveryEdit?.caseId===s.id){selectTab('review');deliveryDialog();}else if(Object.hasOwn(tabs,m.tab))selectTab(m.tab);return}
    if(reactHost&&m.type==='commerce:workspace-refresh') {
      if(!s.id||(m.case_id&&m.case_id!==s.id))return;
      const caseId=s.id;
      const reply=status=>parent.postMessage({type:'commerce:workspace-refresh-result',nonce,case_id:caseId,status},'*');
      // Reading a new base while edits exist would silently rebase their CAS revision.
      if(s.busy||hasPendingProductEdits()){hostRefreshDeferred=true;announce('当前输入已保留，请核对并保存后刷新商品资料。');if(hasPendingProductEdits()){s.error='商品资料待刷新，当前输入已保留。请先核对当前版本，再继续保存。';s.errorCode='workspace_refresh_deferred';render()}reply('deferred');return}
      hostRefreshDeferred=false;
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
  function focusPeer(prior){
    if(prior?.isConnected&&!prior.disabled&&prior.getClientRects().length)return prior;
    const identified=prior?.id?document.getElementById(prior.id):null;
    if(identified&&!identified.disabled&&identified.getClientRects().length)return identified;
    const candidates=[...root.querySelectorAll('[data-pw-action]')].filter(node=>node.dataset.pwAction===prior?.dataset?.pwAction&&node.getClientRects().length&&!node.disabled);
    return candidates.find(node=>node.textContent.trim()===prior?.textContent.trim()&&JSON.stringify(node.dataset)===JSON.stringify(prior?.dataset))||candidates[0];
  }
  function closeDialog() {
    quoteEpoch++;deliveryEpoch++;planEdit=null;modalEdited=false;
    root.inert=false;
    document.getElementById('modal-root').innerHTML='';s.dialogAction=null;
    const prior=s.opener;
    // A completed read can repaint the product behind the open dialog.
    const opener=focusPeer(prior);
    opener?.focus?.({preventScroll:true});reportEditState();
  }
  function dialog(title,body,actions='',callback=null) {
    if(!document.getElementById('modal-root').firstElementChild){s.opener=document.activeElement;modalEdited=false;}
    s.dialogAction=callback;root.inert=true;
    document.getElementById('modal-root').innerHTML=ui.modal({title,body,actions});
    document.querySelector('.dialog button')?.focus();
  }
  function pendingProductSection(){return studio.hasUnsavedChanges?.()?'media':s.dirty.has('cost')?'cost':s.dirty.has('content')?'content':s.tab;}
  function hasPendingProductEdits(){return s.dirty.size>0||modalEdited||!!studio.hasUnsavedChanges?.()||(typeof evidence!=='undefined'&&!!evidence?.hasUnsavedChanges?.());}
  function reportEditState(force=false){if(!reactHost)return;const value={case_id:s.id,dirty:hasPendingProductEdits(),section:pendingProductSection()},signature=JSON.stringify(value);if(force||signature!==lastEditState){lastEditState=signature;parent.postMessage({type:'commerce:workspace-edit-state',nonce,...value},'*');}}
  function evidenceEditStateChanged(){
    reportEditState();
    if(reactHost&&hostRefreshDeferred&&!s.busy&&!hasPendingProductEdits())void reload({select:s.id});
  }
  function modelContext() {
    const c=s.data?.case;
    return c?{module:'organization',demo:c.scope.synthetic===true,platform:c.scope.platform,market:c.scope.market,entity:{kind:'case',id:c.id}}:{module:'organization',demo:false};
  }
  const pageLocation=window.CommercePageContext?.create({root:()=>document.getElementById('pw-main'),getBase:()=>({page:'workspace',section:s.tab,demo:!!modelContext().demo,entity:s.data?{kind:'case',id:s.data.case.id,name:s.data.name}:undefined,filters:{...(s.data?.case.scope.platform?{platform:s.data.case.scope.platform}:{}),...(s.data?.case.scope.market?{market:s.data.case.scope.market}:{})},source_refs:s.data?.source_sha256?{case:s.data.source_sha256}:{},input:s.tab==='cost'?formData('cost').input:s.tab==='content'?formData('content').fields:undefined,errors:[s.error,quoteError,deliveryError].filter(Boolean).slice(0,3)}),onChange:value=>{if(value&&bridged)parent.postMessage({type:'commerce:page-context',nonce,page_context:value,context:modelContext()},'*');copilot?.contextChanged();reportEditState()}});
  function renderChat() {
    const host=document.getElementById('pw-chat');if(!host||!copilot)return;
    host.innerHTML=copilot.view();copilot.afterPaint();
  }
  function shell() {
    document.documentElement.dataset.embedded=String(embedded);
    root.innerHTML=`<div class="pw-frame ${embedded?'pw-embedded':''} ${hosted?'pw-hosted':''} ${reactHost?'pw-react-host':''}">
      ${embedded?'':`<aside class="pw-sidebar" aria-label="平台导航"><a class="pw-brand" href="/"><span>${ui.icon('store')}</span><strong>AI 跨境运营平台</strong></a><nav>${navigation.map(([,label,tab,icon])=>[label,tab,icon]).map(([label,tab,icon])=>`<a href="/?tab=${tab}" class="${tab==='workspace'?'active':''}">${ui.icon(icon)}<span>${label}</span></a>`).join('')}</nav><div class="pw-sidebar-bottom"><a href="/">${ui.icon('grid')}完整运营后台</a></div></aside>`}
      <div class="pw-body">${embedded?'':`<header class="pw-topbar">${!reactHost?`<nav class="pw-business-nav" aria-label="平台业务导航">${navigation.map(([short,label,tab,icon])=>`<button class="ui-button" data-pw-action="navigate" data-tab="${tab}" aria-label="${short} · ${label}" ${tab==='workspace'?'aria-current="page"':''}>${ui.icon(icon)}<span>${short}</span></button>`).join('')}</nav>`:''}<span class="pw-topbar-title">商品工作区</span><div>${ui.field('外观',ui.select({id:'pw-theme','aria-label':'界面主题',value:ui.getTheme().preference,options:[{value:'system',label:'跟随系统'},{value:'light',label:'浅色'},{value:'dark',label:'深色'}]}))}</div></header>`}
      <div class="pw-mode-switch" role="group" aria-label="工作视图">${btn('AI 对话','mobile-chat')}${btn('商品工作区','mobile-product')}</div>
      <div class="pw-columns"><section class="pw-conversation" aria-label="AI 业务对话"><div id="pw-chat"></div></section>${embedded?'':'<div class="pw-splitter" role="separator" tabindex="0" aria-orientation="vertical" aria-label="调整对话区宽度" aria-controls="pw-chat pw-main" aria-valuemin="320" aria-valuemax="640" aria-valuenow="480"></div>'}<main class="pw-main" id="pw-main" aria-busy="true"><div id="pw-product"></div></main></div></div></div>`;
    if(!embedded){
      copilot=window.CommerceCopilot({api,ui,toast:announce,modal:dialog,closeModal:closeDialog,getContext:modelContext,getPageContext:()=>pageLocation?.snapshot(),inline:true,compact:true,onModels:()=>{if(bridged)parent.postMessage({type:'commerce:workspace-navigate',nonce,tab:'models'},'*');else location.assign('/workspace?tab=models')},onResearch:id=>{if(bridged)parent.postMessage({type:'commerce:workspace-research',nonce,task_id:id},'*');else location.assign('/workspace?tab=pilots&research_task_id='+encodeURIComponent(id))},onOpenCandidate:openResearchCandidate,onWorkspace:()=>{if(s.data)selectTab('cost');else{if(innerWidth<1024){s.mobile='product';applyMobile()}document.querySelector('#pw-case')?.focus()}},renderContext:taskSummary,errorText:message,scopeLabel:c=>[platformNames[c?.platform]||c?.platform,c?.market,s.items.find(x=>x.id===c?.entity?.id)?.name||(c?.entity?.id?'工作项 '+c.entity.id.slice(0,8):''),c?.demo?'合成示例':'本机资料 · 待核实'].filter(Boolean).join(' · '),repaint:renderChat});
      if(innerWidth>=1024)copilot.open(undefined,{focus:false});
    }
    applyMobile();
    setupSplitter();
    if(!reactHost&&visualViewport){const updateKeyboard=()=>{root.dataset.keyboardOpen=String(innerWidth<=767&&visualViewport.scale===1&&document.documentElement.clientHeight-visualViewport.height>150)};visualViewport.addEventListener('resize',updateKeyboard);updateKeyboard();}
  }
  function setupSplitter() {
    const handle=document.querySelector('.pw-splitter');if(!handle)return;
    const columns=handle.parentElement;let origin=0,initial=480;
    const limits=()=>ui.chatLayout(columns.clientWidth);
    const set=(value,save=true)=>{const {min,max}=limits();value=Math.round(Math.max(min,Math.min(max,value)));columns.style.setProperty('--pw-chat-width',value+'px');handle.setAttribute('aria-valuenow',String(value));handle.setAttribute('aria-valuemax',String(max));if(save){if(reactHost){s.hostChatWidth=value;parent.postMessage({type:'commerce:workspace-chat-width',nonce,width:value},'*')}else try{localStorage.setItem('commerce-product-chat-width-v2',String(value))}catch{}}};
    const preferred=()=>{if(reactHost&&s.hostChatWidth)return s.hostChatWidth;let saved=null;try{saved=localStorage.getItem('commerce-product-chat-width-v2')}catch{}return ui.chatLayout(columns.clientWidth,saved).width};
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
    if(embedded){root.dataset.mobileView='product';return;}
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
    const stage=(id,title,target)=>{const g=gate(id),status=g?.status;return {id,title,target,action:id==='S3'?'quotes':'tab-'+target,label:({PASS:'检查通过',FAIL:'需处理',HOLD:'待核对',BLOCKED:'依赖待补'})[status]||'待读取',tone:status==='PASS'?'success':status==='FAIL'?'danger':'warning',complete:status==='PASS'}};
    const research=stage('S1','研究与资料核对','research');
    if(research.complete&&!checked('S5'))Object.assign(research,{complete:false,label:'待校对',tone:'warning'});
    const rows=[research,stage('S3','供应与报价','research')];
    const valid=d.calculation.status==='CALCULATED'&&!d.calculation.stale&&!s.dirty.has('cost');
    rows.push({id:'calculation',title:'成本测算与定价',target:'cost',action:'tab-cost',label:valid?'已测算':s.dirty.has('cost')?'待重算':'待补参数',tone:valid?'blue':'warning',complete:valid,hint:valid&&!checked('S2')?'来源门禁待复核':''});
    const contentCurrent=draft?.preflight.status==='current',contentReady=!!draft&&contentCurrent&&draft.preflight.ready_for_local_review&&!s.dirty.has('content'),mediaReady=d.artifacts.images?.intact===true&&checked('S4');
    rows.push({id:'content',title:'商品内容',target:'content',action:'tab-content',label:s.dirty.has('content')?'编辑未保存':!draft?'待准备':!contentCurrent?'来源已变化':!contentReady?'待补内容':'草稿已备',tone:contentReady?'blue':'warning',complete:contentReady});
    rows.push({id:'media',title:'商品素材交付',target:'media',action:'tab-media',label:mediaReady?'检查通过':'待补素材',tone:mediaReady?'success':'warning',complete:mediaReady});
    const reviewed=d.delivery_review?.status==='local_review_recorded'&&contentReady&&valid&&mediaReady;
    rows.push({id:'review',title:'方案审阅与交付',target:'review',action:'tab-review',label:reviewed?'本地已审阅':contentReady&&mediaReady?'待审阅':'待准备',tone:reviewed?'success':'gray',complete:reviewed});
    rows.push({id:'listing',title:'店铺方案与发布申请',action:'listing',label:'查看目标与回执',tone:'gray',complete:false});
    return rows;
  }
  function taskSummary() {
    const d=s.data;if(!d)return '';
    const plan=formData('plan'),rows=workflow(),tasks=d.tasks;
    return `<section class="pw-task-summary"><header><div><strong>${esc(d.name)} · 商品推进</strong></div>${btn(plan.steps.length?'目标 · '+plan.steps.length+' 步':'目标','goal',false,{quiet:true})}</header>${plan.goal?`<p class="pw-task-goal">${esc(plan.goal)}</p>`:''}<ol class="pw-workflow">${rows.map((row,i)=>`<li class="${row.complete?'is-ready':''}" data-workflow-stage="${row.id}"><span class="pw-step-index">${i+1}</span><div>${btn(row.title,row.action,false,{quiet:true,title:row.hint||row.title})}</div>${ui.badge(row.label,row.tone)}</li>`).join('')}</ol><details class="pw-disclosure"><summary>计划与检查</summary><div class="pw-form-actions">${btn('计划视图','workflow')}${btn('岗位检查','organization')}${btn('任务记录'+(tasks.length?' · '+tasks.length:''),'tab-tasks')}</div></details></section>`;
  }
  function header() {
    const d=s.data,c=d.case,scope=c.scope;
    const next=workflow().find(row=>!row.complete);
    return `<header class="pw-object-header"><span class="pw-object-symbol">${ui.icon('box')}</span><div class="pw-object-title"><div class="pw-title-row"><h1 title="${esc(d.name)}">${esc(d.name)}</h1>${btn('','choose-product',false,{quiet:true,icon:'chevronDown','aria-label':'切换商品',title:'切换商品',disabled:s.busy})}</div><div class="pw-object-meta"><strong class="pw-store-label">${esc(d.product_card?.store_identity?.label||(scope.origin==='research_candidate_not_inventory'?'调研候选 · 尚未绑定店铺':'店铺身份待核对'))}</strong><span>${esc(identity.meta(c))}</span>${scope.synthetic===true?ui.badge('合成数据','gray'):scope.origin==='research_candidate_not_inventory'?ui.badge('调研候选','gray'):''}<span>${esc(c.currency||'币种待核对')}</span><span>${scope.sku?'SKU · '+esc(scope.sku):'工作项 · '+esc(c.id.slice(-8))}</span></div></div><div class="pw-header-actions">${reactHost&&embedded?'':btn('上架准备','listing',false,{disabled:s.busy})}${s.tab==='overview'&&next?btn('下一步：'+next.title,next.action,true,{disabled:s.busy}):''}${btn('','more',false,{quiet:true,icon:'more','aria-label':'更多商品操作',title:'更多商品操作'})}</div></header><nav class="pw-tabs" role="tablist" aria-label="商品工作区内容">${Object.entries(tabs).map(([key,label])=>`<button role="tab" type="button" data-pw-tab="${key}" id="pw-tab-${key}" aria-controls="pw-tabpanel" aria-selected="${key===s.tab}" tabindex="${key===s.tab?'0':'-1'}">${label}</button>`).join('')}</nav>`;
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
    const presentation=window.CommerceCatalogPresentation;
    const summary=(key,f)=>{const value=f.zh||f.original;const pairs=presentation?.readable?.(value,key);return pairs?pairs.slice(0,3).map(x=>x.label+'：'+x.value).join('；'):presentation?.plain?.(value)||value;};
    const labels={findings:'研究结论',limitations:'资料限制',title:'商品标题',description:'商品描述',price:'价格依据',reviews:'评价依据',specifications:'规格',attributes:'商品属性',availability:'可售范围',barcode:'条码',brand:'品牌',category:'类目',dimensions:'包装尺寸',weight:'重量',images:'素材',quantity:'数量',stock:'库存',sku:'SKU',name:'商品名称'};
    const state=!a.intact?'完整性异常':rows.every(([,f])=>f.reviewed)?'已校对':'待校对';
    if(compact)return section('市场研究 '+ui.badge(state,a.intact?'gray':'danger'),`${controls}${!a.intact?alert('资料完整性异常，请核对来源。','danger'):''}<dl class="pw-research-fields pw-research-brief">${(unique.filter(([k])=>k!=='title').length?unique.filter(([k])=>k!=='title'):unique).slice(0,2).map(([key,f])=>`<div><dt>${esc(labels[key]||key)}</dt><dd><p class="pw-research-summary">${esc(summary(key,f))}</p></dd></div>`).join('')}</dl><div class="pw-research-note"><span>${esc(record.language||'')} · ${stamp(record.captured_at).split(' ')[0]}</span></div>`,btn('查看研究','tab-research'));
    return section('市场研究',`${controls}<div class="pw-inline-meta">${ui.badge(state,a.intact?'gray':'danger')}<span>${esc(record.language||'')} · ${stamp(record.captured_at)}</span></div>${!a.intact?alert('资料完整性异常，请核对来源。','danger'):''}<dl class="pw-research-fields">${unique.map(([key,f])=>`<div><dt>${esc(labels[key]||key)}</dt><dd>${presentation?.field?.({key,...f})||'<p>'+esc(f.zh||f.original)+'</p>'}<details><summary>${f.reviewed?'原文与校对记录':'原文 · 待校对'}</summary>${f.zh?`<p lang="${esc(record.language||'en')}">${esc(f.original)}</p>`:''}<p>${esc(f.locator||'无定位信息')}</p></details></dd></div>`).join('')}</dl><details class="pw-disclosure"><summary>来源资料</summary><p class="pw-source-text">${esc(record.source_url||'来源未提供')}</p><p>${esc(record.raw_excerpt||'无原始摘录')}</p>${record.fields?.subject?`<p class="pw-source-text">研究需求：${esc(record.fields.subject.zh||record.fields.subject.original)}</p>`:''}<p class="pw-meta">资料尚未独立核实。</p></details>`,s.data.research_context?'':btn('补充资料','research-source'))+supplyView();
  }
  function supplyView(compact=false) {
    const a=s.data.artifacts.supply,p=a?.payload;
    if(!p)return section('供应与报价',empty('尚无选用的报价资料。'),btn('管理报价','quotes'));
    const rows=[['供应商',p.supplier],['采购报价',p.purchase_cost==null?'待补充':amount(p.purchase_cost,p.currency)],['交期',p.lead_time_days==null?'待补充':esc(p.lead_time_days)+' 天'],['报价来源',p.source_ref]];
    return section('供应与报价 '+ui.badge(a.intact?'待核实':'完整性异常',a.intact?'gray':'danger'),`<dl class="pw-evidence-grid">${rows.map(([label,value])=>`<div><dt>${label}</dt><dd>${label==='采购报价'?value:esc(value??'待补充')}</dd></div>`).join('')}</dl>`,btn('管理报价','quotes'));
  }
  const quoteLabels={supplier:'供应商',currency:'币种',purchase_cost:'采购单价（每件）',lead_time_days:'交期（天）',moq:'起订量（件）',source_ref:'报价来源',valid_until:'有效期（含时区）',length_cm:'包装长（cm）',width_cm:'包装宽（cm）',height_cm:'包装高（cm）',weight_kg:'包装重量（kg）',units_per_pack:'每包装件数'};
  const quoteStates={HOLD:'资料待补',STALE:'范围或完整性异常',EXPIRED:'已过期',CURRENCY_MISMATCH:'币种不一致',READY_FOR_SELECTION:'可明确选用 · 未核实'};
  const quoteAmount=(value,currency)=>value==null?'待补充':esc(value)+' '+esc(currency||'币种待核对');
  function quoteComparisonView(){
    if(quoteComparison.caseId!==s.id)quoteComparison={caseId:s.id,quantity:'',result:null};
    const result=quoteComparison.result;
    const form=`<form id="pw-quote-compare-form" class="pw-input-grid pw-quote-compare-form">${ui.field('需求数量（件）',ui.input({id:'pw-quote-quantity',type:'number',min:1,max:1000000000,step:1,required:true,value:quoteComparison.quantity,disabled:s.busy}))}${btn(s.busy?'正在比较…':'比较当前报价','quote-compare',false,{type:'submit',disabled:s.busy||!s.data.supply_quotes.items.length})}</form><p id="pw-quote-compare-state" class="pw-meta" role="status"></p>`;
    if(!result)return section('按需求数量比较',form);
    const rows=result.items.map(row=>`<tr><td>${esc(row.supplier||'供应商待补充')}<small>版本 ${row.revision} · ${esc(row.quote_id)}</small></td><td>${quoteAmount(row.unit_price,row.currency)}<small>交期 ${esc(row.lead_time_days??'待补充')} 天</small></td><td>${esc(row.moq??'待补充')} 件起订<small>${esc(row.units_per_pack??'待补充')} 件 / 包装</small></td><td>${row.order_units==null?'待核对':row.order_units+' 件'}${row.extra_units==null?'':`<small>超出需求 ${row.extra_units} 件 · ${row.packages} 包装</small>`}</td><td>${row.goods_subtotal==null?'—':quoteAmount(row.goods_subtotal,row.currency)}</td><td>${esc(quoteStates[row.status]||'待核对')}<details><summary>报价依据</summary><p>${esc(row.source_ref||'待补充')}</p><p>有效期：${esc(row.valid_until||'待补充')}</p><p class="pw-meta">${esc(row.sha256)}</p></details>${row.selected?'<strong>已选用</strong>':row.goods_subtotal==null?'':btn('选用此报价','quote-select',true,{'data-quote':row.quote_id,'data-quote-sha':row.sha256,'data-source-sha':result.source_sha256,'data-request-key':crypto.randomUUID(),disabled:s.busy})}</td></tr>`);
    return section('按需求数量比较',form+`<div id="pw-quote-compare-result" class="pw-quote-comparison" aria-label="报价比较结果" data-comparison-sha="${esc(result.comparison_sha256)}"><p role="status">按 ${result.quantity} 件需求比较 · ${result.comparable_count} 项可计算 · 供应资料未独立核实</p>${ui.table(['供应商 / 版本','单价 / 交期','起订 / 包装','采购数量','货款小计','状态 / 依据'],rows)}<p class="pw-meta">数量按需求、起订量与整包装约束计算；货款小计仅含报价货款，运费、税费及其他费用另行核对。比较不选定供应商或创建采购。</p></div>`);
  }
  function quoteDialog(){
    if(quoteEdit?.caseId!==s.id)quoteEdit=null;
    const items=s.data.supply_quotes?.items||[],selected=s.data.artifacts.supply?.payload.quote_ref;
    let body=quoteError?alert(quoteError,'danger'):'';
    if(quoteEdit){
      const p=quoteEdit.fields;
      body+=`<p>${esc(s.data.name)} · ${quoteEdit.revision?'修改版本 '+quoteEdit.revision:'新报价'} · 操作者提供，未独立核实</p><div class="pw-input-grid">${Object.entries(quoteLabels).map(([key,label])=>ui.field(label,ui.input({id:'pw-quote-'+key,'data-pw-quote':key,value:(Object.hasOwn(p,key)?p[key]:p.packaging?.[key])??'',type:['supplier','currency','source_ref','valid_until'].includes(key)?'text':'number',step:'any',placeholder:key==='valid_until'?'2026-12-01T18:00:00+08:00':undefined}))).join('')}</div>`;
      dialog('编辑供应链报价',body,btn('保存报价','quote-save',true,{disabled:s.busy})+btn('放弃本次输入','quote-discard')+btn('关闭','dialog-close'));
    }else{
      body+=`<p>报价按原币、每件单价对照；不同币种不换算。保存资料后须明确选用，才更新当前供应产物。</p>`;
      body+=quoteComparisonView();
      body+=items.map(row=>`<section class="pw-section"><h3>${esc(row.fields.supplier||'供应商待补充')}</h3><p><span>版本 ${row.revision}</span> · ${esc(quoteStates[row.status]||'待核对')}${selected?.sha256===row.sha256?' · <strong>已选用</strong>':''}</p><dl class="pw-evidence-grid"><div><dt>采购单价</dt><dd>${row.fields.purchase_cost==null?'待补充':amount(row.fields.purchase_cost,row.fields.currency)}</dd></div><div><dt>起订量</dt><dd>${esc(row.fields.moq??'待补充')} 件</dd></div><div><dt>有效期</dt><dd>${esc(row.fields.valid_until||'待补充')}</dd></div><div><dt>报价来源</dt><dd>${esc(row.fields.source_ref||'待补充')}</dd></div></dl>${row.missing.length?`<p>待补：${row.missing.map(k=>esc(quoteLabels[k.replace('packaging.','')]||k)).join('、')}</p>`:''}<div class="pw-form-actions">${btn('编辑报价','quote-edit',false,{'data-quote':row.quote_id})}${btn('选用此报价','quote-select',true,{'data-quote':row.quote_id,'data-quote-sha':row.sha256,'data-source-sha':s.data.source_sha256,'data-request-key':crypto.randomUUID(),disabled:s.busy||row.status!=='READY_FOR_SELECTION'||selected?.sha256===row.sha256})}</div><details><summary>历史版本与包装 · ${row.history.length} 项</summary>${ui.table(['版本','单价','起订量','有效期','包装资料'],row.history.map(h=>`<tr><td>${h.revision}</td><td>${h.fields.purchase_cost==null?'待补充':amount(h.fields.purchase_cost,h.fields.currency)}</td><td>${esc(h.fields.moq??'待补充')}</td><td>${esc(h.fields.valid_until||'待补充')}</td><td>${Object.entries(h.fields.packaging||{}).map(([k,v])=>esc(quoteLabels[k]||k)+': '+esc(v)).join('；')}</td></tr>`))}${row.history_truncated?'<p>仅显示最近20个版本。</p>':''}</details></section>`).join('')||empty('尚无结构化报价。');
      dialog('供应链报价',body,btn('新增报价','quote-new',true)+btn('关闭','dialog-close'));
      document.querySelector('#modal-root .dialog')?.classList.add('pw-quote-dialog');
    }
  }
  async function quoteAction(action,target){
    if(s.busy)return;
    if(action==='quote-discard'){quoteEdit=null;quoteError='';quoteDialog();return}
    if(action==='catalog'){s.catalogOpen=true;render();await catalog.enter();return}
    if(action==='catalog-close'){s.catalogOpen=false;render();return}
    if(action==='quotes'||action==='quote-edit'||action==='quote-new'){
      quoteError='';
      if(action==='quotes')quoteComparison.result=null;
      if(action==='quote-new')quoteEdit={caseId:s.id,quote_id:crypto.randomUUID(),revision:0,fields:{},source:s.data.source_sha256,key:crypto.randomUUID()};
      if(action==='quote-edit'){const row=s.data.supply_quotes.items.find(q=>q.quote_id===target.dataset.quote);if(!row)return;quoteEdit={caseId:s.id,quote_id:row.quote_id,revision:row.revision,fields:structuredClone(row.fields),source:s.data.source_sha256,key:crypto.randomUUID()}}
      quoteDialog();return;
    }
    const id=s.id,epoch=++quoteEpoch,current=()=>s.id===id&&epoch===quoteEpoch;
    s.busy=true;quoteError='';
    try{
      if(action==='quote-compare'){
        const quantity=Number(quoteComparison.quantity);
        if(!Number.isSafeInteger(quantity)||quantity<1||quantity>1000000000)throw Error('workspace_quote_invalid_quantity');
        quoteDialog();
        const result=await api('commerce_workspace_quote_compare',{case_id:id,quantity});
        if(current())quoteComparison.result=result;
        return;
      }
      if(action==='quote-save')await api('commerce_workspace_quote_save',{case_id:id,quote_id:quoteEdit.quote_id,payload:quoteEdit.fields,expected_revision:quoteEdit.revision,expected_source_sha256:quoteEdit.source,idempotency_key:quoteEdit.key});
      else await api('commerce_workspace_quote_select',{case_id:id,quote_id:target.dataset.quote,expected_quote_sha256:target.dataset.quoteSha,expected_source_sha256:target.dataset.sourceSha,idempotency_key:target.dataset.requestKey});
      if(!current())return;await reload();if(!current())return;quoteEdit=null;quoteComparison.result=null;
    }catch(error){if(current()){quoteError=message(error);if(['workspace_source_changed','workspace_quote_conflict','workspace_quote_not_ready','workspace_quote_currency_mismatch'].includes(error.code||error.message))quoteComparison.result=null}}finally{if(current()){s.busy=false;render();quoteDialog()}else if(s.id===id){s.busy=false;render()}}
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
  function costSummary(compact=false,action='') {
    const r=s.data.calculation,dirty=s.dirty.has('cost'),valid=r.status==='CALCULATED'&&!r.stale&&!dirty;
    if(!valid){const state=r.stale?'依据已变更':dirty?'输入已修改':'待补充';const missing=(r.stale?[]:r.missing||[]).map(k=>fields[k]||k);return section('成本测算',`${ui.badge(state,'warning')}<p class="pw-muted">${r.stale?'核对来源后重新测算。':dirty?'保存后更新测算结果。':missing.length?`缺少${missing.length}项参数`:'尚未测算'}</p>${!compact&&missing.length?`<p class="pw-missing">${missing.map(esc).join('、')}</p>`:''}`,compact?btn('补充参数','tab-cost'):action)}
    const b=r.cost_breakdown,labels={purchase_cost:'采购',domestic_shipping:'境内运费',packaging:'包装',fulfillment_cost:'履约',electronic_fee:'其他平台费用',commission:'佣金',payment:'支付费用',returns:'退货费用',return:'退货费用',ad:'广告费用'};
    const rows=compact?[['采购成本',b.purchase_cost],['物流与履约',b.domestic_shipping+b.fulfillment_cost],['包装成本',b.packaging],['其他平台费用',b.electronic_fee],['佣金',b.commission],['支付 / 退货 / 广告',b.payment+(b.returns??b.return??0)+b.ad]]:Object.entries(b).map(([key,value])=>[labels[key]||key,value]);
    const percent=value=>r.price>0?(100*value/r.price).toLocaleString('zh-CN',{maximumFractionDigits:1})+'%':'—';
    return section('成本测算',`<div class="pw-cost-table-head"><span>成本构成（单件）</span><span>${esc(r.currency)}</span><span>售价占比</span></div><dl class="pw-cost-breakdown">${rows.map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${decimal(value)}</dd><dd class="pw-cost-share">${percent(value)}</dd></div>`).join('')}<div class="pw-total"><dt>总成本</dt><dd>${decimal(r.total_cost)}</dd><dd class="pw-cost-share">${percent(r.total_cost)}</dd></div><div><dt>测算售价</dt><dd>${decimal(r.price)}</dd><dd class="pw-cost-share">100%</dd></div><div class="pw-contribution ${r.contribution<0?'pw-negative':''}"><dt>单件贡献估算</dt><dd>${decimal(r.contribution)}</dd><dd class="pw-cost-share">${percent(r.contribution)}</dd></div></dl>`,compact?btn('调整参数','tab-cost'):action);
  }
  function costDisplayValue(key,value) {
    return value==null||value===''?'':key.endsWith('_rate')?Number((Number(value)*100).toPrecision(12)):value;
  }
  function costInputValue(key,value) {return key==='currency'?value.toUpperCase():Number(value)/(key.endsWith('_rate')?100:1)}
  function costScenarioValue(key,value) {return value==null||value===''?'待补充':String(costDisplayValue(key,value))+(key.endsWith('_rate')?'%':'')}
  function validateCostInput(input) {
    for(const [key,value] of Object.entries(input))if(key.endsWith('_rate')&&(!Number.isFinite(value)||value<0||value>1))throw Error('invalid_'+key);
  }
  function costView(){return `${s.deliveryReturnCase&&s.deliveryReturnCase===s.id&&deliveryEdit?.caseId===s.id?`<div class="pw-form-actions">${btn('返回交付审阅','delivery-return')}</div>`:''}${s.data.forms.cost.stale?alert('成本依据已有变化，请在成本工作台核对并重新保存。','warning'):''}${costSummary(false,btn('编辑成本','edit-cost',true,{disabled:s.busy}))}`;}
  function contentView(compact=false) {
    const f=formData('content'),sources=s.data.content_sources,d=s.data.content_drafts[0];
    if(compact){
      if(!d&&f.fields?.title)return section('商品内容',`<div class="pw-content-preview">${ui.badge('候选文案 · 待核对','gray')}<strong>${esc(f.fields.title)}</strong><p>${esc(f.fields.description||'描述待补充')}</p><p class="muted">已保存本机编辑稿，尚未提交平台。</p></div>`,btn('核对候选文案','tab-content'));
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
    return section('方案审阅',`<div class="pw-inline-meta">${ui.badge(({local_review_recorded:'本地审阅已记录',needs_input:'待补充',ready_for_review:'待审阅',stale:'来源已失效',rejected:'已退回'})[draft.status]||'待核对','gray')}<span>${stamp(draft.created_at*1000)}</span></div>${check.status!=='current'?alert('来源版本已变化，旧确认动作已撤下。请依据当前来源生成新版本。','warning'):''}${blocked.length?alert('待补充或核对字段：'+[...new Set(blocked)].map(k=>listingFields[k]||k).join('、'),'warning'):''}${previous?changed.length?diffTable(changed):empty('与上一版本内容一致。'):diffTable(keys)}${previous&&changed.length<keys.length?`<details class="pw-disclosure"><summary>全部字段 · ${keys.length} 项</summary>${diffTable(keys)}</details>`:''}<p class="pw-meta">仅审阅本地草稿，不提交平台。</p><div class="pw-form-actions">${btn('交付审阅清单','delivery-checklist',true,{disabled:s.busy})}${btn('导出交付清单','delivery-export',false,{disabled:s.busy})}${btn('退回修改','review-reject',false,{disabled:s.busy})}${btn('导出记录','export-content',false,{disabled:s.busy})}</div><details class="pw-disclosure"><summary>来源引用与原回执</summary><pre>${esc(json({sources:draft.draft.sources,receipts:draft.receipts,preflight:check}))}</pre></details>`);
  }
  function deliveryEnabled(){
    const view=s.data.delivery_review;
    return !s.busy&&!deliveryEdit?.stale&&view.status!=='local_review_recorded'&&!s.dirty.has('content')&&!s.dirty.has('cost')&&deliveryEdit?.package===view.package_sha256&&view.automatic_checks.every(c=>c.passed)&&Object.values(deliveryEdit.checks).every(c=>c.status==='confirmed'&&c.source_ref.trim());
  }
  function deliveryDialog(reset=false){
    const view=s.data.delivery_review;
    if(reset||deliveryEdit?.caseId!==s.id)deliveryEdit={caseId:s.id,package:view.package_sha256,source:view.source_sha256,review:view.latest?.sha256||'',checks:structuredClone(view.checks),key:crypto.randomUUID()};
    const stale=deliveryEdit.stale||deliveryEdit.package!==view.package_sha256;
    const body=`${deliveryError?alert(deliveryError,'danger'):''}${deliveryNotice?`<p role="status">${esc(deliveryNotice)}</p>`:''}${stale?alert('当前交付版本已改变，输入保留供核对；请读取当前版本后重新确认。','warning'):''}<p>${esc(s.data.name)} · 本地交付审阅；发布前核查状态为 ${esc(view.professional_gate)}（经营负责人签收不属于独立认证）。</p><dl class="pw-review-checks">${view.automatic_checks.map(c=>`<div><dt>${esc(c.label)}</dt><dd>${ui.badge(c.passed?'本轮检查通过':'待补齐或复验',c.passed?'success':'warning')}${c.id==='cost'&&!c.passed?btn('去成本测算','delivery-open-cost',false,{disabled:s.busy}):''}</dd></div>`).join('')}</dl>${Object.entries(view.requirements).map(([key,label])=>{const row=deliveryEdit.checks[key];return `<section class="pw-section"><h3>${esc(label)}</h3><div class="pw-input-grid">${ui.field('人工核对状态',ui.select({id:'pw-delivery-'+key+'-status','data-pw-delivery':key,'data-part':'status',value:row.status,options:[{value:'pending',label:'待核对'},{value:'confirmed',label:'已人工核对'},{value:'rejected',label:'需修改'}]}))}${ui.field('依据或记录位置',ui.input({id:'pw-delivery-'+key+'-source','data-pw-delivery':key,'data-part':'source_ref',value:row.source_ref,maxlength:500}))}</div>${ui.field('说明',ui.input({'data-pw-delivery':key,'data-part':'note',value:row.note,maxlength:1000}))}</section>`}).join('')}<p class="muted">人工核对记录不等于独立合规认证，也不触发平台发布。</p>`;
    dialog('商品交付审阅清单',body,btn('保存待核清单','delivery-save',false,{disabled:s.busy})+btn('确认本地交付审阅','delivery-confirm',true,{disabled:!deliveryEnabled()})+btn('读取当前版本并重新核对','delivery-reset')+btn('关闭','dialog-close'));
  }
  async function deliveryAction(action){
    if(s.busy)return;
    if(action==='delivery-checklist'){deliveryError='';deliveryNotice='';deliveryDialog();return}
    if(action==='delivery-open-cost'){if(deliveryEdit?.caseId!==s.id)return;s.deliveryReturnCase=s.id;closeDialog();selectTab('cost');if(bridged)parent.postMessage({type:'commerce:workspace-dynamic-cost',nonce,case_id:s.id,return_delivery:true},'*');else location.assign('/workspace?tab=operations&case_id='+encodeURIComponent(s.id)+'&cost_return=delivery');announce('审阅意见已保留。保存测算后可返回原交付审阅清单。');return}
    if(action==='delivery-return'){if(s.deliveryReturnCase!==s.id||deliveryEdit?.caseId!==s.id)return;closeDialog();selectTab('review');deliveryError='';deliveryNotice='已返回当前商品的交付审阅清单，原意见已保留；版本变化后需读取当前版本并重新核对。';deliveryDialog();return}
    if(action==='delivery-reset'){const id=s.id,epoch=++deliveryEpoch,prior=structuredClone(deliveryEdit?.checks||{});s.busy=true;try{const status=await reload();if(s.id===id&&deliveryEpoch===epoch){if(status!=='refreshed'){deliveryNotice='';deliveryError=status==='superseded'?'读取已被后续请求替代，原清单与输入仍保留，请重新读取当前版本。':'当前版本未能读取，原清单与输入仍保留，请检查连接后重试。';s.busy=false;deliveryDialog();return;}deliveryError='';deliveryNotice='已读取当前版本，文字已保留，请重新核对。';s.busy=false;render();deliveryEdit=null;deliveryDialog(true);for(const [key,row] of Object.entries(prior))if(deliveryEdit.checks[key])deliveryEdit.checks[key]={...row,status:'pending'};deliveryDialog()}}finally{if(s.id===id)s.busy=false}return}
    const id=s.id,epoch=++deliveryEpoch,current=()=>s.id===id&&epoch===deliveryEpoch;
    s.busy=true;deliveryError='';
    try{
      if(action==='delivery-export'){
        const v=s.data.delivery_review,result=await api('commerce_workspace_delivery_export',{case_id:id,expected_package_sha256:v.package_sha256});if(current())download(result);return;
      }
      await api('commerce_workspace_delivery_record',{case_id:id,expected_package_sha256:deliveryEdit.package,expected_source_sha256:deliveryEdit.source,expected_review_sha256:deliveryEdit.review,checks:deliveryEdit.checks,decision:action==='delivery-confirm'?'reviewed':'save',confirmed:action==='delivery-confirm',idempotency_key:deliveryEdit.key});
      if(!current())return;await reload();if(!current())return;deliveryEdit=null;deliveryNotice=action==='delivery-confirm'?'本地交付审阅已记录':'待核清单已保存';
    }catch(error){if(current()){deliveryError=message(error);if(deliveryEdit&&['workspace_source_changed','workspace_delivery_package_changed','workspace_delivery_review_conflict'].includes(error.code||error.message))deliveryEdit.stale=true}}finally{if(current()){s.busy=false;render();if(action!=='delivery-export')deliveryDialog()}else if(s.id===id){s.busy=false;render()}}
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
    const plan=formData('plan'),goal=plan.goal?`<div class="pw-goal-summary"><strong>工作目标</strong><p>${esc(plan.goal)}</p>${btn('编辑目标','goal',false,{quiet:true})}</div>`:'';
    return `${summary}${goal}<div class="pw-overview-grid"><div>${researchView(true)}${supplyView(true)}${reviewSummary()}</div><div>${costSummary(true)}${contentView(true)}</div></div>`;
  }
  function revealActiveTab(){const tab=document.getElementById('pw-tab-'+s.tab),nav=tab?.closest('.pw-tabs');if(!nav)return;const item=tab.getBoundingClientRect(),bar=nav.getBoundingClientRect();if(!bar.width)return;if(item.left<bar.left)nav.scrollLeft+=item.left-bar.left;else if(item.right>bar.right)nav.scrollLeft+=item.right-bar.right;}
  function render() {
    const host=document.getElementById('pw-product');if(!host)return;reportEditState();
    document.getElementById('pw-main').setAttribute('aria-busy',String(s.busy));pageLocation?.changed();enrichIdentity();
    if(!s.data){host.innerHTML=`<div class="pw-start"><h1>商品工作区</h1>${s.error?alert(s.error,'danger'):s.busy?empty('正在读取商品工作项…'):s.items.length?'':empty('当前连接尚无商品工作项。')}${catalog.view()}<div class="pw-form-actions">${btn('重新读取','refresh')}${btn('岗位交接','organization')}</div></div>`;return}
    if(s.catalogOpen){host.innerHTML=`<div class="pw-form-actions">${btn('返回当前商品','catalog-close')}</div>${catalog.view()}`;return}
    const tabScroll=host.querySelector('.pw-tabs')?.scrollLeft||0;
    const focused=document.activeElement,focus=focused?.id,focusAction=focused?.dataset?.pwAction,start=focused?.selectionStart,end=focused?.selectionEnd;
    host.innerHTML=`${header()}${s.error?`<div class="pw-page-error">${alert(s.error,'danger')}<div class="pw-form-actions">${btn('核对当前版本','inspect-saved')}${btn('刷新资料','refresh')}</div><details><summary>技术详情</summary><code>${esc(s.errorCode)}</code></details></div>`:''}<div id="pw-tabpanel" role="tabpanel" aria-labelledby="pw-tab-${s.tab}" tabindex="0" class="pw-tabpanel">${({overview,research:researchView,cost:costView,content:contentView,review:reviewView,tasks:tasksView,evidence:()=>evidence?.view()||empty('证据模块尚未载入，请刷新当前版本。'),media:()=>studio.view()})[s.tab]()}</div>`;
    const tabNav=host.querySelector('.pw-tabs');if(tabNav)tabNav.scrollLeft=tabScroll;revealActiveTab();if(s.tab==='evidence')evidence?.afterRender();
    const summary=document.querySelector('#copilot-log .pw-task-summary');if(summary)summary.outerHTML=taskSummary();
    if(focus||focusAction){const element=focusPeer(focused);if(element){element.focus({preventScroll:true});if(start!=null&&element.setSelectionRange&&element.type!=='number')element.setSelectionRange(start,end)}}
  }
  let identityItems;
  function renderIdentityUpdate() {
    const prior=document.activeElement,id=prior?.id,start=prior?.selectionStart,end=prior?.selectionEnd,direction=prior?.selectionDirection;
    const restore=!!id&&root.contains(prior);
    render();
    // Read focus at response time, and leave any focus deliberately set by render alone.
    if(!restore||prior.isConnected||document.activeElement!==document.body)return;
    const current=document.getElementById(id);if(!current||current.disabled)return;
    current.focus({preventScroll:true});
    if(start!=null&&current.setSelectionRange&&current.type!=='number')current.setSelectionRange(start,end,direction||undefined);
  }
  function enrichIdentity() {
    const items=s.items;if(!items.length||identityItems===items)return;identityItems=items;
    // Optional scope metadata must never delay the current product read.
    api('commerce_agent_cases').then(value=>{if(s.items!==items)return;s.items=identity.merge(items,value.cases||[]);identityItems=s.items;renderIdentityUpdate()}).catch(()=>{});
  }
  async function reload({select=s.id,clearEditors=false,researchTaskId=select===s.id?s.researchTaskId:''}={}) {
    if(select!==s.id&&typeof evidence!=='undefined'&&evidence?.hasActiveMutation?.()){s.error='证据资料正在保存或核对，请完成后再切换商品。';render();return 'deferred';}
    s.researchTaskId=researchTaskId;const researchSequence=++s.researchSequence;s.researchLoading=false;s.researchContextError='';
    const previousContext=JSON.stringify(modelContext()),restoreView=!s.data||select!==s.id,generation=++s.generation;s.busy=true;render();
    const current=()=>generation===s.generation&&researchSequence===s.researchSequence&&researchTaskId===s.researchTaskId;
    try {
      const list=await api('commerce_workspace_list');if(!current())return 'superseded';
      s.items=list.items;
      if(!select&&list.items.length===1)select=list.items[0].id;
      if(select){const requestedResearch=researchContext.task(researchTaskId),data=await api('commerce_workspace_get',{case_id:select,...(requestedResearch?{research_task_id:requestedResearch}:{})});if(!current())return 'superseded';if(select!==s.id&&typeof evidence!=='undefined'&&(evidence?.hasActiveMutation?.()||evidence?.hasUnsavedChanges?.())){s.error='原商品在读取期间有新的证据编辑或保存，请完成后再切换。';return 'deferred';}researchContext.artifact(data,requestedResearch);s.id=select;s.data=data;if(restoreView){const requested=!bridged?new URL(location.href).searchParams.get('tab'):null;s.tab=requestedResearch?'research':tabs[requested]?requested:data.forms.view?.payload?.tab||'overview'}
        if(clearEditors){s.edits={};s.dirty.clear();if(typeof evidence!=='undefined')evidence?.discardChanges();}
        if(typeof evidence!=='undefined'&&(s.tab==='evidence'||evidence?.hasUnsavedChanges?.()))void evidence?.enter(select,{force:true});
        if(!bridged){const url=new URL(location.href);url.searchParams.set('case_id',select);history.replaceState(null,'',url)}
        if(!embedded&&previousContext!==JSON.stringify(modelContext()))copilot?.contextChanged();
        reportResearchSelection();
      }else{s.id='';s.data=null}
      s.error='';s.errorCode='';
      if(reactHost&&hostRefreshDeferred&&!hasPendingProductEdits()){hostRefreshDeferred=false;announce('商品资料已刷新。');parent.postMessage({type:'commerce:workspace-refresh-result',nonce,case_id:s.id,status:'refreshed'},'*')}
      return 'refreshed';
    } catch(error){if(!current())return 'superseded';s.error=message(error);s.errorCode=error.code||error.message;return 'failed'}
    finally{if(generation===s.generation){s.busy=false;render();
      // Let the essential picker/current-item read finish before the optional
      // catalog. This also restores browsing after an explicit connection retry.
      if(current()&&!s.error&&s.data&&s.tab==='media')void studio.enter();
      if(current()&&!s.error&&!s.data)catalog.enter();
    }}
  }
  function selectTab(tab) {if(!tabs[tab])return;s.tab=tab;if(tab==='media')studio.enter();if(tab==='evidence'&&s.data&&typeof evidence!=='undefined')void evidence?.enter(s.id,{force:true});if(!embedded&&innerWidth<1024&&s.mobile!=='product'){s.mobile='product';applyMobile()}if(!bridged){const url=new URL(location.href);url.searchParams.set('tab',tab);history.replaceState(null,'',url)}persistView(tab);render();document.getElementById('pw-tab-'+tab)?.focus({preventScroll:true});revealActiveTab()}
  function persistView(tab) {
    const id=s.id;if(!id)return;
    viewQueue=viewQueue.catch(()=>{}).then(async()=>{
      if(s.id!==id||s.tab!==tab||!s.data)return;const source=s.data.source_sha256;
      try{const value=await api('commerce_workspace_save',{case_id:id,form:'view',payload:{tab},expected_revision:s.data.forms.view.revision,expected_source_sha256:source});if(s.id===id&&s.data.source_sha256===source)s.data.forms.view={...value,stale:false}}
      catch(error){if(s.id===id)announce('视图位置尚未保存：'+message(error))}
    });
  }
  function dirty(name) {s.dirty.add(name);s.changes++;document.querySelectorAll('[data-pw-form-status="'+name+'"]').forEach(x=>{x.innerHTML='<span class="pw-unsaved">未保存</span>'});if(name==='content')document.querySelector('[data-pw-action="submit-content"]')?.setAttribute('disabled','');if(name==='cost'){document.querySelector('[data-pw-action="scenario-open-save"]')?.setAttribute('disabled','');const save=document.querySelector('[data-pw-action="save-calculate"]');if(save){save.disabled=false;save.classList.add('primary')}const result=document.getElementById('pw-cost-result');if(result)result.innerHTML=costSummary()}const summary=document.querySelector('#copilot-log .pw-task-summary');if(summary)summary.outerHTML=taskSummary();announce('输入已修改，旧结果不再作为当前结果')}
  async function saveForm(form) {
    const generation=s.generation,edit=s.changes,data=s.data,payload=structuredClone(formData(form));
    if(form==='cost')validateCostInput(payload.input);
    await api('commerce_workspace_save',{case_id:data.case.id,form,payload,expected_revision:data.forms[form].revision,expected_source_sha256:data.source_sha256});
    if(generation!==s.generation)return;
    if(edit===s.changes){s.dirty.delete(form);delete s.edits[form]}
    await reload();announce('已保存当前商品的'+({plan:'工作目标',cost:'测算输入',content:'编辑草稿'})[form]);
  }
  function openResearchCandidate(id,taskId='') {
    if(!id||s.busy)return;
    if(id===s.id){s.tab='research';loadResearchContext(taskId);return}
    const proceed=()=>{studio.discardChanges?.();evidence?.discardChanges();closeDialog();return reload({select:id,clearEditors:true,researchTaskId:taskId})};
    if(hasPendingProductEdits())dialog('打开调研候选','<p>当前商品有未保存输入，请先返回保存，或明确放弃后打开候选。</p>',btn('放弃修改并打开','dialog-proceed')+btn('返回编辑','dialog-close'),proceed);
    else proceed();
  }
  function goalDialog(focus='pw-goal') {
    if(!planEdit){const plan=formData('plan');planEdit={caseId:s.id,goal:plan.goal,steps:plan.steps.map(step=>({...step,id:step.id||'step_'+crypto.randomUUID().replaceAll('-','')})),error:''};}
    const rows=planEdit.steps.map((step,index)=>`<div class="pw-plan-row">${ui.field('步骤 '+(index+1),ui.input({id:'pw-plan-title-'+step.id,'data-pw-plan-step':step.id,value:step.title,maxlength:200}))}<div class="pw-plan-row-actions">${btn('','plan-step-up',false,{'data-step':step.id,icon:'arrowUp','aria-label':'上移第'+(index+1)+'步',disabled:index===0})}${btn('','plan-step-down',false,{'data-step':step.id,icon:'arrowDown','aria-label':'下移第'+(index+1)+'步',disabled:index===planEdit.steps.length-1})}${btn('删除','plan-step-remove',false,{'data-step':step.id,'aria-label':'删除第'+(index+1)+'步'})}</div></div>`).join('');
    dialog('工作目标',`${planEdit.error?alert(planEdit.error,'danger'):''}${ui.field('本次目标',`<textarea class="ui-control" id="pw-goal" maxlength="2000" rows="4">${esc(planEdit.goal)}</textarea>`)}<div class="pw-plan-rows">${rows}</div>${btn('添加步骤','plan-step-add',false,{id:'pw-plan-add',disabled:planEdit.steps.length>=12})}<p class="pw-meta">保存目标与步骤不会自动派发任务。</p>`,btn('保存目标','save-plan',true)+btn('取消','dialog-close'));
    document.getElementById(focus)?.focus({preventScroll:true});
  }
  function download(result) {const url=URL.createObjectURL(new Blob([result.content],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=result.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  async function act(action,target) {
    if(action==='catalog'){s.catalogOpen=true;render();await catalog.enter();return}
    if(action==='catalog-close'){s.catalogOpen=false;render();return}
    if(action==='quotes'||action.startsWith('quote-'))return quoteAction(action,target);
    if(action.startsWith('delivery-'))return deliveryAction(action);
    if(action==='research-task'){const taskId=target.dataset.task;if(taskId){if(bridged)parent.postMessage({type:'commerce:workspace-research',nonce,task_id:taskId},'*');else location.assign('/workspace?tab=pilots&research_task_id='+encodeURIComponent(taskId))}return;}
    if(action==='edit-cost'||action==='dynamic-cost'||action==='tab-cost'){if(s.busy||!s.data?.case?.id)return;if(bridged)parent.postMessage({type:'commerce:workspace-dynamic-cost',nonce,case_id:s.data.case.id},'*');else location.assign('/workspace?tab=operations&case_id='+encodeURIComponent(s.id));return}
    if(action.startsWith('tab-')){selectTab(action.slice(4));return}
    if(action==='dialog-close'){closeDialog();return}
    if(action==='dialog-proceed'){const callback=s.dialogAction;closeDialog();await callback?.();return}
    if(action==='mobile-chat'||action==='mobile-product'){s.mobile=action==='mobile-chat'?'chat':'product';applyMobile();return}
    if(action==='navigate'){const tab=target.dataset.tab;if(!navigation.some(item=>item[2]===tab))return;closeDialog();if(bridged)parent.postMessage({type:'commerce:workspace-navigate',nonce,tab},'*');else location.assign('/?tab='+encodeURIComponent(tab));return}
    if(['listing','workflow','organization'].includes(action)){if(!s.data&&action!=='organization')return;if(reactHost)parent.postMessage({type:'commerce:workspace-navigate',nonce,tab:action,...(s.id?{case_id:s.id}:{})},'*');else location.assign('/workspace?tab='+action+(s.id?'&case_id='+encodeURIComponent(s.id):''));return}
    if(action==='backend'){if(bridged)parent.postMessage({type:'commerce:workspace-backend',nonce},'*');else location.assign('/');return}
    if(action==='more'){dialog('商品操作',`<div class="pw-action-menu">${btn('工作目标','goal')}${btn('来源与版本','source-details')}${btn('刷新资料','refresh')}${btn('岗位检查','organization')}</div>`);return}
    if(action==='goal'){closeDialog();goalDialog();return}
    if(action==='choose-product'){if(s.busy)return;s.actionEpoch++;s.catalogOpen=true;render();await catalog.enter();return}
    if(action==='source-details'){closeDialog();dialog('对象与依据',`<dl class="pw-source-detail"><dt>工作项</dt><dd>${esc(s.id)}</dd><dt>平台与市场</dt><dd>${esc(s.data.case.scope.platform)} · ${esc(s.data.case.scope.market)}</dd><dt>来源版本</dt><dd><code>${esc(s.data.source_sha256)}</code></dd></dl><p>来源资料尚未独立核实。</p>`);return}
    if(action==='research-source'){dialog('研究资料入口',gaps(['S1','S5'])+`<p>在岗位交接中补充当前商品资料，保存后回到这里刷新。</p>`,btn('前往岗位交接','organization')+btn('关闭','dialog-close'));return}
    if(action==='inspect-saved'){dialog('已保存的当前修订',`<p>请先核对当前修订；关闭窗口后仍保留你的输入。</p><pre>${esc(json(s.data.forms))}</pre>`,btn('读取最新修订','reload-dialog')+btn('关闭','dialog-close'));return}
    if(action.startsWith('plan-step-')){if(s.busy||!planEdit)return;modalEdited=true;const index=planEdit.steps.findIndex(step=>step.id===target.dataset.step);let focus='pw-plan-add';if(action==='plan-step-add'&&planEdit.steps.length<12){const step={id:'step_'+crypto.randomUUID().replaceAll('-',''),title:''};planEdit.steps.push(step);focus='pw-plan-title-'+step.id;}else if(action==='plan-step-remove'&&index>=0){planEdit.steps.splice(index,1);if(planEdit.steps.length)focus='pw-plan-title-'+planEdit.steps[Math.min(index,planEdit.steps.length-1)].id;}else if((action==='plan-step-up'||action==='plan-step-down')&&index>=0){const next=index+(action==='plan-step-up'?-1:1);if(next>=0&&next<planEdit.steps.length){[planEdit.steps[index],planEdit.steps[next]]=[planEdit.steps[next],planEdit.steps[index]];focus='pw-plan-title-'+planEdit.steps[next].id;}}planEdit.error='';goalDialog(focus);reportEditState();return;}
    if(s.busy)return;
    const id=s.id,epoch=++s.actionEpoch,startTab=s.tab,current=()=>s.id===id&&s.actionEpoch===epoch;
    s.busy=true;s.error='';s.errorCode='';s.fieldErrors={};
    try {
      if(action==='refresh'){closeDialog();await reload();return}
      if(action==='reload-dialog'){closeDialog();await reload();return}
      if(action==='save-plan'){if(!planEdit)return;if(planEdit.caseId!==s.id){planEdit.error='工作项已变化，请关闭后重新打开目标。';goalDialog();return;}const steps=planEdit.steps.map(step=>({...step,title:step.title.trim()}));const missing=steps.find(step=>!step.title);if(missing){planEdit.error='请填写每一步的名称。';goalDialog('pw-plan-title-'+missing.id);return;}s.edits.plan={goal:planEdit.goal,steps};dirty('plan');closeDialog();await saveForm('plan')}
      if(action==='set-currency'){await api('commerce_workspace_currency',{case_id:s.id,currency:formData('cost').input.currency,expected_source_sha256:s.data.source_sha256});await reload();announce('已明确工作项币种；请按新范围保存测算输入')}
      if(action==='save-content')await saveForm('content');
      if(action==='save-calculate'){if(s.dirty.has('cost')||s.data.forms.cost.stale||!s.data.forms.cost.revision)await saveForm('cost');if(!current())return;const result=await api('commerce_workspace_calculate',{case_id:s.id,expected_source_sha256:s.data.source_sha256,expected_revision:s.data.forms.cost.revision});if(!current())return;await reload();announce(result.status==='HOLD'?'草稿已保存，请补齐参数':'测算已保存')}
      if(action==='scenario-open-save'){dialog('保存成本情景',ui.field('情景名称',ui.input({id:'pw-scenario-label',maxlength:80,placeholder:'例如：当前报价、调整售价'}))+`<p class="pw-meta">固定当前已保存参数和依据，不更改当前报价或平台价格。</p>`,btn('保存情景','scenario-save',true,{'data-key':crypto.randomUUID()})+btn('取消','dialog-close'));}
      if(action==='scenario-save'){const label=document.getElementById('pw-scenario-label')?.value||'';await api('commerce_cost_scenarios_save',{case_id:s.id,label,expected_source_sha256:s.data.source_sha256,expected_revision:s.data.forms.cost.revision,idempotency_key:target.dataset.key});if(!current())return;closeDialog();announce('成本情景已保存；当前参数和报价保持。')}
      if(action==='scenario-compare'){const result=await api('commerce_cost_scenarios_get',{case_id:s.id});if(!current())return;dialog('成本情景对比',result.items.length?'<div class="pw-scenario-comparison">'+ui.table(['情景 / 依据','售价','单件总成本','单件贡献估算','贡献率'],result.items.map(row=>`<tr><td><strong>${esc(row.label)}</strong>${ui.badge(row.stale?'依据已变化':'当前依据',row.stale?'warning':'gray')}<details><summary>参数与版本</summary><p>成本修订 ${row.cost_revision}</p><dl>${Object.entries(row.input).map(([key,value])=>`<dt>${esc(fields[key]||key)}</dt><dd>${esc(costScenarioValue(key,value))}</dd>`).join('')}</dl><small>${esc(row.sha256)}</small></details></td><td>${amount(row.result.price,row.result.currency)}</td><td>${amount(row.result.total_cost,row.result.currency)}</td><td>${amount(row.result.contribution,row.result.currency)}</td><td>${decimal(row.result.contribution_rate*100)}%</td></tr>`))+'</div>'+`<p class="pw-meta">仅同币种情景可直接比较；依据变化的结果保留供复核，不作为当前测算。最多显示最近20项。</p>`:empty('尚无已保存情景。先保存完整成本参数，再保存情景。'))}
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
    } catch(error){if(!current())return;s.error=message(error);s.errorCode=error.code||error.message;const key=s.errorCode.replace(/^invalid_/,'');if(Object.hasOwn(fields,key))s.fieldErrors[key]=key.endsWith('_rate')?fields[key]+'须为 0–100% 的数值。':'请核对'+fields[key]+'的格式或数值范围。';announce(s.error)}
    finally{if(current()){s.busy=false;render();if(document.activeElement===document.body){const restore=target?.id?document.getElementById(target.id):document.querySelector('[data-pw-action="'+(target?.dataset?.pwAction==='review-apply'?s.opener?.dataset?.pwAction:target?.dataset?.pwAction)+'"]');restore?.focus({preventScroll:true})}}}
  }
  document.addEventListener('click',event=>{const pe=event.target.closest('[data-pe-action]');if(pe){event.preventDefault();Promise.resolve(evidence?.action(pe.dataset.peAction,pe)).catch(error=>{s.error=message(error);render()});return}const tab=event.target.closest('[data-pw-tab]');if(tab){selectTab(tab.dataset.pwTab);return}const action=event.target.closest('[data-pw-action]');if(action){event.preventDefault();act(action.dataset.pwAction,action).catch(error=>{s.error=message(error);s.errorCode=error.message;s.busy=false;render()})}else if(event.target.closest('.dialog [data-action="close"]'))closeDialog();Promise.resolve().then(()=>reportEditState())});
  document.addEventListener('submit',event=>{if(event.target.id==='pw-quote-compare-form'){event.preventDefault();act('quote-compare',event.target)}else if(event.target.id==='pw-cost-form'||event.target.id==='pw-content-form'){event.preventDefault();act(event.target.id==='pw-cost-form'?'save-calculate':'preview-content',event.target)}});
  document.addEventListener('input',event=>{
    const target=event.target;
    if(target.closest?.('.pe-workbench')){evidence?.input(target);return;}
    if(target.id!=='pw-case'&&target.closest?.('.dialog')&&!target.readOnly)modalEdited=true;
    if(planEdit&&target.id==='pw-goal')planEdit.goal=target.value;
    if(planEdit&&target.dataset.pwPlanStep){const step=planEdit.steps.find(row=>row.id===target.dataset.pwPlanStep);if(step)step.title=target.value;}
    if(target.id==='pw-quote-quantity'){
      quoteComparison.quantity=target.value;quoteComparison.result=null;
      document.getElementById('pw-quote-compare-result')?.remove();
      const status=document.getElementById('pw-quote-compare-state');if(status)status.textContent='需求已修改，请重新比较。';
    }
    if(target.dataset.pwDelivery&&deliveryEdit?.caseId===s.id){const key=target.dataset.pwDelivery,part=target.dataset.part;if(Object.hasOwn(deliveryEdit.checks,key)&&['source_ref','note'].includes(part)){deliveryEdit.checks[key][part]=target.value;deliveryEdit.key=crypto.randomUUID();const confirm=document.querySelector('[data-pw-action="delivery-confirm"]');if(confirm)confirm.disabled=!deliveryEnabled()}}
    if(target.dataset.pwQuote&&quoteEdit?.caseId===s.id){const key=target.dataset.pwQuote;if(!Object.hasOwn(quoteLabels,key))return;const pack=['length_cm','width_cm','height_cm','weight_kg','units_per_pack'].includes(key),data=pack?(quoteEdit.fields.packaging||=( {})):quoteEdit.fields;if(target.value==='')delete data[key];else data[key]=['supplier','currency','source_ref','valid_until'].includes(key)?key==='currency'?target.value.toUpperCase():target.value:Number(target.value);quoteEdit.key=crypto.randomUUID()}
    if(target.dataset.pwCost){const f=structuredClone(formData('cost'));const key=target.dataset.pwCost;if(target.value==='')delete f.input[key];else f.input[key]=costInputValue(key,target.value);s.edits.cost=f;dirty('cost')}
    if(target.dataset.pwContent){const f=structuredClone(formData('content')),key=target.dataset.pwContent;f.fields[key]=key==='quantity'?(target.value===''?null:Number(target.value)):key==='image_refs'?target.value.split('\n').filter(Boolean):target.value;s.edits.content=f;dirty('content')}
    reportEditState();
  });
  document.addEventListener('change',event=>{if(event.target.id!=='pw-case'&&event.target.closest?.('.dialog')&&!event.target.readOnly)modalEdited=true;Promise.resolve().then(()=>reportEditState());
    if(event.target.dataset.pwDelivery&&deliveryEdit?.caseId===s.id){const key=event.target.dataset.pwDelivery;if(Object.hasOwn(deliveryEdit.checks,key)&&event.target.dataset.part==='status'){deliveryEdit.checks[key].status=event.target.value;deliveryEdit.key=crypto.randomUUID();const confirm=document.querySelector('[data-pw-action="delivery-confirm"]');if(confirm)confirm.disabled=!deliveryEnabled()}return;}
    if(event.target.id==='pw-research-context'){loadResearchContext(event.target.value);return;}
    if(event.target.id==='pw-case'){
      const selected=event.target.value,prior=s.id;if(!selected||s.busy)return;s.actionEpoch++;
      if(hasPendingProductEdits()){event.target.value=prior;dialog('切换商品',`<p>当前商品有未保存输入。可以返回保存，或明确放弃本页未保存修改后切换。</p>`,btn('放弃修改并切换','dialog-proceed')+btn('返回编辑','dialog-close'),()=>{studio.discardChanges?.();evidence?.discardChanges();return reload({select:selected,clearEditors:true});})}
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
  window.addEventListener('beforeunload',event=>{if(hasPendingProductEdits()){event.preventDefault();event.returnValue=''}});
  window.addEventListener('resize',applyMobile);
  shell();
  const initialLoad=reload();
  if(bridged){const ready=()=>parent.postMessage({type:'commerce:workspace-ready',nonce},'*');if(reactHost)initialLoad.finally(ready);else ready()}
  if(!embedded)api('commerce_ui_get_preferences').then(value=>{ui.applyTheme(value.theme);document.getElementById('pw-theme').value=value.theme}).catch(()=>{});
})();
