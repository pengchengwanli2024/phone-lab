/* Shared local-state descriptions; capability flags come from each domain. */
(()=>{
  const definitions=Object.freeze({
    queued:['等待执行','blue',false],running:['执行中','blue',false],cancelling:['正在取消','warning',false],
    awaiting_input:['等待补充信息','warning',false],awaiting_review:['待审核','warning',false],pending_review:['待审核','warning',false],
    partial:['部分完成','warning',true],completed:['已完成','success',true],succeeded:['已完成','success',true],success:['已完成','success',true],
    failed:['失败','danger',true],interrupted:['已中断','warning',true],cancelled:['已取消','gray',true]
  });
  const cancellable=new Set(['queued','running','awaiting_input','awaiting_review','pending_review']);
  const retryable=new Set(['failed','interrupted','cancelled']);
  function describe(code,capabilities={}){
    const row=typeof code==='string'&&Object.hasOwn(definitions,code)?definitions[code]:['状态未知','gray',false];
    return Object.freeze({label:row[0],tone:row[1],terminal:row[2],
      canCancel:capabilities?.cancel===true&&cancellable.has(code),canRetry:capabilities?.retry===true&&retryable.has(code)});
  }
  globalThis.CommerceStatus=Object.freeze({describe});
})();

/* Commerce UI: dependency-free shared renderers for browser and Harness. */
window.CommerceUI = (() => {
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const permitted=/^(class|id|type|title|role|name|value|placeholder|maxlength|min|max|step|autocomplete|disabled|readonly|required|checked|aria-[a-z-]+|data-[a-z0-9-]+)$/;
  function attributes(values={}){
    return Object.entries(values).filter(([key,value])=>permitted.test(key)&&value!==undefined&&value!==null&&(value!==false||key.startsWith('aria-')||key.startsWith('data-'))).map(([key,value])=>value===true&&['disabled','readonly','required','checked'].includes(key)?key:`${key}="${escape(value)}"`).join(' ');
  }
  // Compatibility adapter for pre-existing local templates. DOM parsing decodes
  // escaped values; the attribute allowlist removes event handlers and URLs.
  function legacyAttributes(source=''){
    const template=document.createElement('template');template.innerHTML=`<button ${source}></button>`;
    const button=template.content.firstElementChild;
    return button?Object.fromEntries([...button.attributes].filter(a=>permitted.test(a.name)).map(a=>[a.name,a.value])):{};
  }
  function button({label,description='',leadingIcon='',shortcut='',variant='secondary',action,attrs={}}){
    const kind=['primary','secondary','danger','quiet'].includes(variant)?variant:'secondary';
    const content=description?`<span class="ui-button-copy"><strong>${escape(label)}</strong><small>${escape(description)}</small></span>`:escape(label);
    return `<button ${attributes({type:'button',...attrs,class:`ui-button ${kind==='primary'?'primary':''} ${kind==='danger'?'ui-danger':''} ${kind==='quiet'?'link-btn':''} ${attrs.class||''}`,'data-action':action})}>${leadingIcon?icon(leadingIcon):''}${content}${shortcut?`<kbd aria-hidden="true">${escape(shortcut)}</kbd>`:''}</button>`;
  }
  function badge(label,tone='warning'){
    const kind=['blue','gray','success','warning','danger'].includes(tone)?tone:'warning';
    return `<span class="badge ui-badge ${kind}" data-ui-tone="${kind}">${escape(label)}</span>`;
  }
  function input({value='',type='text',...attrs}={}){
    const kind=['text','password','search','number','email','url','date','checkbox'].includes(type)?type:'text';
    return `<input ${attributes({...attrs,type:kind,value,class:`ui-control ${attrs.class||''}`})}>`;
  }
  function select({options=[],value='',...attrs}={}){
    return `<select ${attributes({...attrs,class:`ui-control ${attrs.class||''}`})}>${options.map(option=>`<option value="${escape(option.value)}" ${String(option.value)===String(value)?'selected':''}>${escape(option.label)}</option>`).join('')}</select>`;
  }
  const field=(label,control)=>`<label class="ui-field">${escape(label)}${control}</label>`;
  const empty=(message='暂无记录')=>`<div class="empty ui-empty" role="status">${escape(message)}</div>`;
  const alert=(message,tone='info')=>`<div class="alert ui-alert ${tone==='danger'?'error':''}" role="${tone==='danger'?'alert':'status'}">${escape(message)}</div>`;
  function card({title='',content='',attrs={}}){
    return `<section ${attributes({...attrs,class:`card ui-card ${attrs.class||''}`})}>${title?`<h2>${escape(title)}</h2>`:''}${content}</section>`;
  }
  function table(headers,rows,emptyText='没有匹配的数据。未授权店铺时真实数据为空。'){
    return `<div class="table-wrap ui-table"><table class="data-table"><thead><tr>${headers.map(h=>`<th scope="col">${escape(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>${rows.length?'':empty(emptyText)}</div>`;
  }
  function tabs(items,value){
    return `<div class="ui-navigation"><nav class="tabs ui-tabs" aria-label="电商模块">${Object.entries(items).map(([key,name])=>`<button type="button" class="tab ${value===key?'active':''}" data-tab="${escape(key)}" data-module-category="${escape(moduleDetails(key).group)}" aria-current="${value===key?'page':'false'}">${escape(name)}</button>`).join('')}</nav><div class="ui-module-picker">${field('工作台模块',select({id:'ui-module',value,options:Object.entries(items).map(([value,label])=>({value,label}))}))}</div></div>`;
  }

  const moduleMeta={
    overview:['经营数据','查看销售、订单与待处理事项','dashboard overview'],
    orders:['经营数据','查询订单、履约状态与来源明细','order fulfillment'],
    products:['经营数据','核对SKU、库存与平台原币价格','sku stock inventory'],
    operations:['经营数据','补齐成本，测算单件贡献和补货数量','cost margin restock economics'],
    alerts:['经营数据','查看提醒、人工记录与活动测算','notification campaign'],
    support:['经营数据','导入会话及业务依据，编辑并审阅本地回复草稿','customer draft'],
    insights:['研究与内容','导入评论并查看规则主题与原文依据','review selection'],
    research:['研究与内容','采集来源，核对原文与中文资料','collect translation'],
    intelligence:['研究与内容','检索公开来源、事件与本机积累','news source map'],
    creative:['研究与内容','整理素材，制作图片和视频草稿','image video storyboard'],
    pilots:['研究与内容','读取候选商品来源，接续已有试点任务','pilot product candidate'],
    agent:['协作执行','补充经营问题，审阅有依据的AI建议','ai model assistant'],
    exposure:['协作执行','按国家、仓库和路线核对经营关联','risk mapping warehouse'],
    organization:['协作执行','核对岗位门禁、资料缺项与产物交接','role handoff gate'],
    tasks:['协作执行','跟踪共享队列、本地执行和处理回执','task queue runtime device'],
    platforms:['连接与能力','配置私有授权，确认范围后手动读取','amazon tiktok temu mercado integration'],
    live:['连接与能力','核对Ozon快照、飞书提醒与补货草稿','ozon feishu inventory'],
    skills:['连接与能力','查找固定版本技能、离线工具与使用依据','skill offline calculator'],
    connections:['连接与能力','查看连接边界，检索业务知识与原文','knowledge obsidian codex hermes settings']
  };
  const workspaceGroups=[
    {id:'home',label:'运营台',icon:'grid',modules:['overview']},
    {id:'product',label:'商品与机会',icon:'box',modules:['products','pilots','research','insights','operations']},
    {id:'store',label:'店铺经营',icon:'store',modules:['orders','live','alerts','support']},
    {id:'content',label:'内容与增长',icon:'chart',modules:['creative']},
    {id:'task',label:'任务与智能体',icon:'spark',modules:['agent','organization','tasks']},
    {id:'knowledge',label:'知识与集成',icon:'book',modules:['intelligence','exposure','skills','platforms','connections']}
  ];
  function navigationGroups(items){
    const known=new Set(workspaceGroups.flatMap(g=>g.modules));
    const groups=workspaceGroups.map(g=>({...g,modules:g.modules.filter(key=>Object.hasOwn(items,key))})).filter(g=>g.modules.length);
    const extra=Object.keys(items).filter(key=>!known.has(key));
    if(extra.length)groups.push({id:'other',label:'其它模块',icon:'grid',modules:extra});
    return groups;
  }
  function moduleDetails(key){const [legacyGroup,description,keywords]=Object.hasOwn(moduleMeta,key)?moduleMeta[key]:['其它模块','打开页面，查看当前资料与可用操作',''];return {group:workspaceGroups.find(g=>g.modules.includes(key))?.label||legacyGroup,description,keywords}}
  function moduleDirectory(items,query=''){
    const normalize=s=>String(s).normalize('NFKC').toLocaleLowerCase();
    const tokens=normalize(query).trim().split(/\s+/).filter(Boolean),groups=new Map(workspaceGroups.map(group=>[group.label,[]]));let count=0;
    for(const [key,label]of Object.entries(items)){
      const detail=moduleDetails(key),haystack=normalize([key,label,detail.group,detail.description,detail.keywords].join(' '));
      if(!tokens.every(token=>haystack.includes(token)))continue;
      if(!groups.has(detail.group))groups.set(detail.group,[]);
      const symbol={overview:'grid',orders:'doc',products:'box',operations:'chart',alerts:'bell',support:'headset',research:'book',intelligence:'grid',creative:'image',pilots:'store',agent:'spark',exposure:'link',organization:'gear',tasks:'doc',platforms:'store',live:'link',skills:'code',connections:'link'}[key]||'grid';
      groups.get(detail.group).push(button({label,description:detail.description,leadingIcon:symbol,attrs:{'data-module-target':key,class:'ui-module-result'}}));count++;
    }
    const html=count?[...groups].filter(([,buttons])=>buttons.length).map(([group,buttons])=>`<section class="ui-module-group"><h3>${escape(group)} <span>共 ${buttons.length} 项</span></h3><div class="ui-module-grid">${buttons.join('')}</div></section>`).join(''):empty('没有匹配的模块。可尝试“库存”“成本”“视频”或英文关键词。');
    return {html,count};
  }
  function modal({title,body,actions=''}){
    return `<div class="overlay"><section class="dialog ui-dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><div class="dialog-head"><h2 id="dialog-title">${escape(title)}</h2>${button({label:'×',action:'close',attrs:{'aria-label':'关闭'}})}</div>${body}<div class="dialog-actions">${actions||button({label:'关闭',action:'close'})}</div></section></div>`;
  }
  const icon=(name='grid')=>{const paths={plus:'<path d="M12 5v14M5 12h14"/>',arrowUp:'<path d="M12 19V5m-6 6 6-6 6 6"/>',panelLeft:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',chevronDown:'<path d="m6 9 6 6 6-6"/>',more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',bell:'<path d="M5 9a7 7 0 0 1 14 0v6l2 3H3l2-3zM9 21h6"/>',chart:'<path d="M3 3v18h18M7 16v-5m5 5V6m5 10V9"/>',person:'<circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/>',image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-7 5 8"/>',grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',chat:'<path d="M3 4h18v13H9l-6 4z"/><path d="M8 9h8M8 13h5"/>',store:'<path d="M4 10v11h16V10M3 3h18l1 7H2zM9 21v-7h6v7"/>',cart:'<path d="M2 3h3l3 13h11l3-10H6"/><circle cx="9" cy="21" r="1"/><circle cx="19" cy="21" r="1"/>',clock:'<circle cx="12" cy="12" r="10"/><path d="M12 5v7l5 3"/>',box:'<path d="m12 2 10 5v11l-10 5-10-5V7zM2 7l10 5 10-5M12 12v11M7 4l10 6v5"/>',bolt:'<path d="m14 1-12 13h9l-1 9 12-14h-9z"/>',book:'<path d="M2 3h8l2 2 2-2h8v17h-8l-2 2-2-2H2zM12 5v17"/>',code:'<path d="m8 4-7 8 7 8m8-16 7 8-7 8M14 2l-4 20"/>',link:'<path d="m9 15 6-6M8 6l2-2a5 5 0 0 1 7 7l-2 2M16 18l-2 2a5 5 0 0 1-7-7l2-2"/>',info:'<circle cx="12" cy="12" r="10"/><path d="M12 11v6m0-11v1"/>',gear:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 1v3m0 16v3M1 12h3m16 0h3"/>',headset:'<path d="M3 14v-3a9 9 0 0 1 18 0v3M3 12h4v7H3zM17 12h4v7h-4zM17 20l-5 2"/>',doc:'<path d="M5 2h10l5 5v15H5zM15 2v6h5M9 12h7M9 16h7"/>',spark:'<path d="m12 1 3 8 8 3-8 3-3 8-3-8-8-3 8-3z"/>'};return `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${paths[name]||paths.grid}</svg>`};
  const systemScheme=window.matchMedia('(prefers-color-scheme: dark)');
  let theme='system';
  const getTheme=()=>({preference:theme,resolved:theme==='system'?(systemScheme.matches?'dark':'light'):theme});
  function applyTheme(value){
    if(!['light','dark','system'].includes(value))throw Error('invalid_ui_theme');
    theme=value;const current=getTheme();document.documentElement.dataset.theme=value;
    document.documentElement.dataset.resolvedTheme=current.resolved;
    window.dispatchEvent(new CustomEvent('commerce:themechange',{detail:current}));
    return current;
  }
  systemScheme.addEventListener('change',()=>{if(theme==='system')applyTheme('system')});
  applyTheme('system');
  return Object.freeze({version:'1.3.0',applyTheme,getTheme,icon,escape,attributes,legacyAttributes,button,badge,input,select,field,empty,alert,card,table,tabs,navigationGroups,moduleDetails,moduleDirectory,modal,status:(code,capabilities)=>globalThis.CommerceStatus.describe(code,capabilities)});
})();

/* Shared browser / Harness conversational sidecar. No host storage or model HTML. */
window.CommerceCopilot=({api,ui=window.CommerceUI,toast,modal,closeModal,getContext,isActive=()=>true,repaint,inline=false,renderContext=()=>'',scopeLabel=null,errorText=null,compact=false,onWorkspace=null,onResearch=null,onOpenCandidate=null})=>{
  const esc=ui.escape,active=new Set(['queued','running','cancel_requested']);
  const status={queued:'排队中',running:'正在分析',awaiting_input:'等待补充',awaiting_review:'等待审阅',completed:'已返回',failed:'未完成',unknown:'结果未知',interrupted:'已中断',cancelled:'已取消',cancel_requested:'请求停止中'};
  const s={open:false,thread:null,threads:[],drafts:{},busy:false,error:'',focus:null,opener:null,load:0,review:null,fields:{},answers:{},form:false,newThread:false,history:false,historyQuery:'',historyFilter:'current',historyLoading:false,historyError:'',historyLoad:0};
  let disposed=false;
  const listeners=[];
  const listen=(target,type,handler,options)=>{const guarded=event=>{if(!disposed)handler(event)};target.addEventListener(type,guarded,options);listeners.push(()=>target.removeEventListener(type,guarded,options))};
  const originalApi=api;
  api=async(name,args)=>{try{const value=await originalApi(name,args);s.unavailable=false;return value}catch(error){if(error.code==='unknown_tool'||error.message==='unknown_tool'){s.unavailable=true;throw Error('当前共享后台尚未启用运营助手，请在服务更新后刷新重试。')}if(errorText){const code=error.code||error.message;s.errorCode=typeof code==='string'&&/^[a-z][a-z0-9_]{0,79}$/.test(code)?code:'';const mapped=Error(errorText(error));mapped.code=code;throw mapped}throw error}};
  const key=()=>s.thread?.id||'new:'+canonical(current()),draft=()=>s.drafts[key()]||'';
  const clone=v=>JSON.parse(JSON.stringify(v||{}));
  const canonical=v=>JSON.stringify(v&&typeof v==='object'?(Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))]))):v??null);
  const current=()=>clone(getContext?.()||{}),changed=()=>s.thread&&!(s.scopeOverride?.thread===s.thread.id&&s.scopeOverride.page===canonical(current())&&canonical(s.scopeOverride.context)===canonical(s.thread.context))&&canonical(s.thread.context)!==canonical(current());
  const button=(label,action,attrs={},variant='secondary')=>ui.button({label,variant,leadingIcon:attrs.icon||'',attrs:{'data-copilot-action':action,...attrs}});
  const researchActive=job=>job&&['queued','running','cancelling'].includes(job.status);
  const researchJob=run=>run?.research_job||(s.thread?.research_job?.run_id===run?.id?s.thread.research_job:null);
  const researchBusy=()=>researchActive(s.thread?.research_job)||(s.thread?.turns||[]).some(t=>researchActive(researchJob(t.run)));
  const researchWatching=()=>[s.thread?.research_job,...(s.thread?.turns||[]).map(t=>researchJob(t.run))].some(job=>job&&['queued','running','awaiting_input','cancelling'].includes(job.status));
  const modelUnavailable=()=>{const selection=s.thread?.model_selection,id=selection?.model_id||'project-default',model=s.models?.find(m=>m.id===id);return selection?.available===false||model?.selectable===false||(id!=='project-default'&&Array.isArray(s.models)&&!model)};
  function runModel(run){const choice=run.model_choice||{},actual=typeof run.result?.model==='string'?run.result.model:choice.model,label=[choice.label,actual].filter((v,i,a)=>typeof v==='string'&&v&&a.indexOf(v)===i).join(' · ');return label?`<span class="copilot-run-model" title="${esc(label+(choice.profile_revision!=null?' · 配置版本 '+choice.profile_revision:''))}">${esc(label)}</span>`:''}
  const researchPrompts=()=>['overview','research','pilots'].includes(current().module)?[['俄罗斯市场调研','我要调研俄罗斯市场。请先确认品类与研究目标，再采集真实公开资料、分析并保存候选商品。'],['按条件选品','帮我选品。请先确认目标市场、品类和预算，再采集真实公开资料并保存候选。']]:[['核对资料缺项','梳理当前工作有哪些资料缺项']];
  function researchView(run){
    const job=researchJob(run);if(!job||job.schema!=='commerce-market-research-v1')return '';
    const later=(s.thread?.turns||[]).findLast(t=>researchJob(t.run)?.task_id===job.task_id);if(later&&later.run.id!==run.id)return '';
    const phases={planning:'明确研究范围',collecting:'采集公开资料',analyzing:'分析市场证据',saving:'保存商品候选',finished:'研究结束'},states={queued:'排队中',running:'研究中',awaiting_input:'待补充',completed:'已完成',partial:'部分完成',failed:'未完成',unknown:'结果待核对',interrupted:'已中断',cancelling:'正在停止',cancelled:'已停止'};
    const count=n=>Number.isInteger(n)&&n>=0?n:'待核对';
    return `<section class="copilot-research" aria-label="市场研究任务" data-research-task="${esc(job.task_id)}"><header><strong>${esc(researchActive(job)?phases[job.phase]||'研究中':states[job.status]||'状态待核对')}</strong>${ui.badge(job.market==='RU'?'俄罗斯':job.market||'市场待核对','gray')}</header><div class="copilot-research-counts"><span>来源 ${count(job.source_count)}</span><span>已保存候选 ${count(job.candidate_count)}</span></div>${job.error?ui.alert(job.error.message||'研究未完成，请核对原任务。','warning'):''}${job.report?.summary?`<p class="copilot-research-summary">${esc(job.report.summary.length>180?job.report.summary.slice(0,180)+'…':job.report.summary)}</p>`:''}${(job.questions||[]).map(q=>`<p class="copilot-question">${esc(q)}</p>`).join('')}${(job.candidates||[]).slice(0,3).map(c=>`<div class="copilot-research-candidate"><span>${esc(c.name)}</span>${onOpenCandidate?button('打开候选','research-candidate',{'data-task':job.task_id,'data-case':c.case_id}):''}</div>`).join('')}<div class="copilot-research-actions">${onResearch?button('查看研究','research-open',{'data-task':job.task_id}):''}${researchActive(job)?button(job.status==='cancelling'?'正在停止':'停止研究','research-cancel',{'data-task':job.task_id,disabled:s.busy||job.status==='cancelling'}):''}${['interrupted','failed','unknown'].includes(job.status)?button('继续原任务','research-resume',{'data-task':job.task_id,disabled:s.busy}):''}${job.status==='awaiting_input'?button('补充研究要求','reply',{icon:'chat'}):''}</div></section>`;
  }
  const scope=c=>{if(scopeLabel)return scopeLabel(c);const platforms={ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu'},kinds={order:'订单',product:'商品',case:'工作项',intel:'情报'};return [ui.moduleDetails(c?.module||'').description,c?.demo?'合成示例':'按本页来源',!c?.platform||c.platform==='all'?'全部平台':platforms[c.platform]||c.platform,!c?.store_id||c.store_id==='all'?'全部店铺':`店铺 ${c.store_id}`,!c?.market||c.market==='all'?'全部市场':c.market,c?.entity?`${kinds[c.entity.kind]||'当前对象'} ${c.entity.id}`:''].filter(Boolean).join(' · ')};
  function remember(){const e=document.activeElement;if(e?.closest?.('#commerce-copilot')&&e.id)s.focus={id:e.id,start:e.selectionStart,end:e.selectionEnd};else if(inline&&!e?.closest?.('#commerce-copilot'))s.focus=null;const log=document.querySelector('#copilot-log');if(log)s.scroll={top:log.scrollTop,bottom:log.scrollHeight-log.scrollTop-log.clientHeight<64}}
  function update(focus){if(disposed)return;remember();if(focus)s.focus={id:focus};const root=document.querySelector('#commerce-copilot');if(root){const t=document.createElement('template');t.innerHTML=view();root.replaceWith(t.content);afterPaint()}else if(repaint)repaint()}
  function layout(){const docked=s.open&&(inline||window.innerWidth>=1280);document.querySelector('#commerce-copilot')?.setAttribute('aria-modal',String(!docked));window.dispatchEvent(new CustomEvent('commerce:copilot-layout',{detail:{open:s.open,docked}}))}
  function afterPaint(){if(disposed||!s.open)return;layout();syncComposer();const log=document.querySelector('#copilot-log');if(log&&s.startAtTop){log.scrollTop=0;s.scroll={top:0,bottom:false};s.startAtTop=false}else if(log&&s.prependAnchor){log.scrollTop=s.prependAnchor.top+log.scrollHeight-s.prependAnchor.height;s.scroll={top:log.scrollTop,bottom:false};s.prependAnchor=null}else if(log&&s.scroll)log.scrollTop=s.scroll.bottom?log.scrollHeight:s.scroll.top;if(s.focus&&!document.querySelector('.dialog')){const e=document.getElementById(s.focus.id);if(e){e.focus({preventScroll:true});if(typeof e.setSelectionRange==='function'&&s.focus.start!=null)e.setSelectionRange(s.focus.start,s.focus.end)}}}
  function syncComposer(){
    const input=document.getElementById('copilot-message');if(!input||!compact)return;
    const send=document.querySelector('[data-copilot-action="send"]');if(send)send.disabled=!!(s.busy||s.unavailable||changed()||modelUnavailable()||active.has(s.thread?.latest_run?.status)||researchBusy()||!draft().trim());
    const css=window.getComputedStyle(input),min=parseFloat(css.minHeight)||64,max=parseFloat(css.maxHeight)||180;
    input.style.height='auto';input.style.height=Math.min(max,Math.max(min,input.scrollHeight))+'px';
  }
  function renderRun(run,generated){if(!run)return '';
    if(researchJob(run)?.schema==='commerce-market-research-v1'){
      const research=researchView(run),result=run.result||{};
      return `<article class="copilot-message copilot-assistant"><div class="copilot-message-meta">${ui.icon('spark')}<strong>智能助手</strong>${runModel(run)}</div>${research||[result.answer,...(result.questions||[])].filter(Boolean).map(text=>`<p class="copilot-prose">${esc(text)}</p>`).join('')}</article>`;
    }
    const r=run.result||{},covered=generated?.covered,questions=(r.questions||[]).filter(q=>!covered?.questions.has(q)),proposals=(r.proposals||[]).filter(p=>!covered?.proposals.has(p.id)),actions=run.actions||[];
    return `<article class="copilot-message copilot-assistant"><div class="copilot-message-meta">${ui.icon('spark')}<strong>智能助手</strong>${runModel(run)}${compact&&run.status==='completed'?'':ui.badge(status[run.status]||run.status||'待处理',run.status==='failed'?'danger':'gray')}</div>${active.has(run.status)&&!researchJob(run)?`<p role="status">后台正在处理。本轮结果会保留，可稍后回来查看。</p>${button('请求停止','cancel',{'data-run':run.id,disabled:s.busy})}`:''}${r.answer&&!covered?.answer?`<div class="copilot-prose">${esc(r.answer)}</div>`:''}${r.error?ui.alert((run.status==='unknown'||run.status==='interrupted'?'结果状态不确定，不会自动重新提交。请核对记录，再明确发送新问题。':'本轮没有完成，可核对依赖后明确发送新问题。')+' '+(errorText?errorText({code:r.error,message:r.error}):r.error==='agent_model_setup_required'?'模型运行入口尚未配置，请在本机完成模型接入后再明确发送问题。':r.error),'danger'):''}${questions.length?`<section class="copilot-card"><h3>需要补充</h3>${questions.map(q=>`<p>${esc(q)}</p>`).join('')}${button('填写补充回答','reply')}${compact?'':button('补充测算数据','fields')}</section>`:''}${proposals.map(p=>`<section class="copilot-card"><h3>${esc(p.reason||p.operation)}</h3><p class="muted">${esc(p.operation)} · 逐项确认后提交本地任务</p>${actions.some(a=>a.proposal_id===p.id)?`<p>已提交本地任务；请在任务模块核对执行回执。</p>`:button('审阅建议','review',{'data-run':run.id,'data-proposal':p.id,disabled:s.busy||!!changed()})}</section>`).join('')}${generated?.html||''}${researchView(run)}${((r.observations||[]).length||generated?.captions?.length)?`<details class="copilot-evidence"><summary>查看依据${r.observations?.length?' · '+r.observations.length+' 项':''}</summary>${(generated?.captions||[]).map(v=>`<p>${esc(v)}</p>`).join('')}${(r.observations||[]).map(o=>`<section><strong>${esc(o.tool)} · ${esc(o.id)}</strong><pre>${esc(JSON.stringify(o.data,null,2))}</pre></section>`).join('')}</details>`:''}</article>`;
  }
  // Bounded, fail-closed A2UI 0.8 standard subset. Never accepts HTML, URLs or scripts.
  function surfaces(messages){try{
    if(!Array.isArray(messages)||messages.length>128||JSON.stringify(messages).length>100000)throw Error();
    const latest=s.thread?.latest_run,covered={answer:false,questions:new Set(),proposals:new Set()},captions=[];
    const all=new Map();for(const m of messages){if(!m||typeof m!=='object')throw Error();const kind=Object.keys(m);if(kind.length!==1||!['surfaceUpdate','dataModelUpdate','beginRendering','deleteSurface'].includes(kind[0]))throw Error();const v=m[kind[0]];if(typeof v.surfaceId!=='string')throw Error();if(kind[0]==='deleteSurface'){all.delete(v.surfaceId);continue}if(!all.has(v.surfaceId))all.set(v.surfaceId,{nodes:new Map(),data:{}});const sf=all.get(v.surfaceId);
      if(m.surfaceUpdate){if(!Array.isArray(v.components)||v.components.length>128)throw Error();for(const n of v.components){if(!n||typeof n.id!=='string'||!n.component||Object.keys(n.component).length!==1)throw Error();sf.nodes.set(n.id,n.component)}}
      if(m.beginRendering)sf.root=v.root;
      if(m.dataModelUpdate){const parts=String(v.path||'/').split('/').filter(Boolean);if(parts.length>8||parts.some(p=>['__proto__','constructor','prototype'].includes(p)))throw Error();let dst=sf.data;for(const p of parts)dst=dst[p]||(dst[p]={});const unpack=entries=>{if(!Array.isArray(entries)||entries.length>128)throw Error();return Object.fromEntries(entries.map(e=>{if(!e||typeof e.key!=='string'||['__proto__','constructor','prototype'].includes(e.key))throw Error();return [e.key,e.valueString??e.valueNumber??e.valueBoolean??(e.valueMap?unpack(e.valueMap):'')]}))};Object.assign(dst,unpack(v.contents));}
    }
    let count=0;const html=[...all.values()].map(sf=>{let hasQuestion=false,hasInput=false;const val=v=>{if(typeof v==='string')return v;if(v?.literalString!=null)return String(v.literalString);if(typeof v?.path==='string'){let o=sf.data;for(const p of v.path.split('/').filter(Boolean)){if(['__proto__','constructor','prototype'].includes(p))throw Error();o=o?.[p]}return ['string','number','boolean'].includes(typeof o)?String(o):''}return ''};const render=(id,seen=new Set(),depth=0)=>{if(depth>16||seen.has(id)||++count>256)throw Error();const obj=sf.nodes.get(id);if(!obj)throw Error();const [type,p]=Object.entries(obj)[0];const next=new Set(seen).add(id);if(['Column','Row'].includes(type)){if(!Array.isArray(p.children?.explicitList)||p.children.explicitList.length>64)throw Error();return `<div class="copilot-a2ui-${type.toLowerCase()}">${p.children.explicitList.map(c=>render(c,next,depth+1)).join('')}</div>`}if(type==='Text'){const text=val(p.text);if(compact&&p.usageHint==='caption'){captions.push(text);return ''}if(latest?.result?.answer&&text===latest.result.answer.slice(0,8000))covered.answer=true;return `<p class="copilot-prose">${esc(text)}</p>`;}
      if(type==='Button'){const action=p.action;if(action?.name!=='commerce.review_proposal')throw Error();const ctx=Object.fromEntries((action.context||[]).map(c=>[c.key,val(c.value)]));const run=(s.thread?.turns||[]).map(t=>t.run).find(r=>r?.id===ctx.run_id);if(!run?.result?.proposals?.some(p=>p.id===ctx.proposal_id))throw Error();const label=p.child?val(sf.nodes.get(p.child)?.Text?.text):'审阅建议';if(run.id===latest?.id)covered.proposals.add(ctx.proposal_id);if((run.actions||[]).some(a=>a.proposal_id===ctx.proposal_id))return `<div><strong>${esc(label)}</strong><p>已提交本地任务；请在任务模块核对执行回执。</p></div>`;return button(label||'审阅建议','review',{'data-run':ctx.run_id,'data-proposal':ctx.proposal_id,disabled:!!changed()})}
      if(type==='TextField'){const field=val(p.label);if(compact&&(latest?.result?.questions||[]).some(q=>q.slice(0,400)===field)){hasQuestion=true;for(const q of latest.result.questions)if(q.slice(0,400)===field)covered.questions.add(q);return `<p class="copilot-question">${esc(field)}</p>`;}hasInput=true;for(const q of latest?.result?.questions||[])if(q.slice(0,400)===field)covered.questions.add(q);return ui.field(field,ui.input({id:'copilot-a2ui-'+count,value:s.answers[field]??val(p.text),'data-copilot-answer':field,maxlength:2000}))}throw Error();};return sf.root?`<${compact?'div':'section'} class="${compact?'copilot-answer':'copilot-card'}">${render(sf.root)}${hasInput?button('将补充内容填入输入框','use-answers'):hasQuestion?button('补充回答','reply',{icon:'chat'}):''}</${compact?'div':'section'}>`:''}).join('');return {html,covered,captions};
  }catch{return {html:ui.alert('生成的卡片暂不支持或结构无效，请使用文字回答和建议审阅。')}}}
  const units={currency:'币种（三位代码）',price:'售价',purchase_cost:'采购成本',domestic_shipping:'境内运费',packaging:'包装成本',fulfillment_cost:'履约费用',electronic_fee:'电子费用',commission_rate:'佣金比例（0–1）',payment_rate:'支付比例（0–1）',return_rate:'退货比例（0–1）',ad_rate:'广告比例（0–1）'};
  const stocks={available:'可用库存',sold_units:'窗口销量',window_days:'统计天数',lead_time_days:'补货提前天数',safety_days:'安全天数',pack_size:'整包数量'};
  function methodView(){const m=s.thread?.method;if(!m||typeof m!=='object')return '';const text=v=>typeof v==='string'?v:JSON.stringify(v);return `<details class="copilot-evidence"><summary>${esc(m.title||'本轮工作方法')}</summary>${m.guidance?`<p>${esc(text(m.guidance))}</p>`:''}${['steps','checks'].map(k=>Array.isArray(m[k])?`<ol>${m[k].slice(0,12).map(v=>`<li>${esc(text(v))}</li>`).join('')}</ol>`:'').join('')}</details>`}
  function form(){const calc=s.fields.calculator||s.thread?.context?.calculator||'unit_economics',fields=calc==='restock_plan'?stocks:units;return `<section class="copilot-card"><h3>补充已核对的测算数据</h3>${ui.field('测算类型',ui.select({id:'copilot-calculator',value:calc,options:[{value:'unit_economics',label:'单件贡献'},{value:'restock_plan',label:'补货计划'}]}))}<div class="copilot-fields">${Object.entries(fields).map(([k,label])=>ui.field(label,ui.input({id:'copilot-field-'+k,type:k==='currency'?'text':'number',min:k==='currency'?undefined:0,step:k==='currency'?undefined:'any',value:s.fields[k]??s.thread?.context?.input?.[k]??'','data-copilot-field':k}))).join('')}</div><p class="muted" data-ui-help>空项保留为缺项，不推测数值。保存范围后，需手动发送本轮问题。</p>${button('保存为本会话测算范围','save-fields',{disabled:s.busy})}${button('收起','fields')}</section>`}
  const sameObject=context=>{const c=current();return c.entity?context?.entity?.kind===c.entity.kind&&context.entity.id===c.entity.id&&context.platform===c.platform&&context.market===c.market&&context.store_id===c.store_id&&context.demo===c.demo:canonical(context)===canonical(c)};
  const objectName=()=>({order:'订单',product:'商品',case:'商品',intel:'情报'})[current().entity?.kind]||'对象';
  const currentRange=()=>current().entity?'本'+objectName():'本页';
  const currentRangeStatus=()=>current().entity?'当前'+objectName():current().module==='organization'?'尚未选择商品':'当前页面';
  const selectionKey=()=> 'commerce-copilot-selection:'+canonical(current());
  function historyRows(){const query=s.historyQuery.trim().toLocaleLowerCase(),threads=s.threads.filter(t=>(s.historyFilter!=='current'||sameObject(t.context))&&(!query||(t.title+' '+scope(t.context)).toLocaleLowerCase().includes(query)));return threads.length?threads.map(t=>`<button type="button" class="ui-button copilot-history-row" data-copilot-action="switch-thread" data-thread="${esc(t.id)}" ${s.busy?'disabled':''} aria-current="${t.id===s.thread?.id?'true':'false'}"><span><strong>${esc(t.title||'业务对话')}</strong><small>${esc(scope(t.context))}</small></span><span class="copilot-history-meta">${t.id===s.thread?.id?'<span>当前</span>':''}<time datetime="${new Date(t.updated*1000).toISOString()}">${new Date(t.updated*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</time>${s.drafts[t.id]?'<span>未发送</span>':''}</span></button>`).join(''):`<p class="copilot-history-empty" role="status">${query?'没有匹配的会话':s.historyFilter==='current'?(current().entity?'这个'+objectName()+'还没有已保存会话':'本页还没有已保存会话'):'暂无已保存会话'}</p>`}
  function historyView(){return `<section id="copilot-history" class="copilot-history" aria-labelledby="copilot-history-title"><header><h3 id="copilot-history-title">业务会话</h3>${button('返回对话','history-close',{'aria-label':'返回当前对话'})}</header>${ui.field('搜索会话',ui.input({id:'copilot-history-query',type:'search',value:s.historyQuery,placeholder:'搜索标题、商品或市场'}))}<div class="copilot-history-filters" role="group" aria-label="会话范围">${button(currentRange(),'history-current',{'aria-pressed':s.historyFilter==='current'})}${button('全部业务','history-all',{'aria-pressed':s.historyFilter==='all'})}${button('刷新','history-refresh',{disabled:s.historyLoading})}</div>${s.historyError?ui.alert(s.historyError,'danger'):''}<div id="copilot-history-list" class="copilot-history-list" aria-label="会话列表" aria-busy="${s.historyLoading}">${s.historyLoading?'<p role="status">正在读取会话…</p>':historyRows()}</div><p class="copilot-history-note">本平台最近 50 个业务会话</p></section>`}
  async function loadHistory(){const seq=++s.historyLoad;s.historyLoading=true;s.historyError='';update();try{const value=await api('commerce_copilot_list');if(seq===s.historyLoad)s.threads=value.threads||[]}catch(error){if(seq===s.historyLoad)s.historyError='会话读取失败，可刷新重试。'}finally{if(seq===s.historyLoad){s.historyLoading=false;update()}}}
  async function switchThread(id){if(s.busy)return;const seq=++s.load;s.busy=true;s.error='';update();try{const thread=await api('commerce_copilot_get',{thread_id:id});if(seq!==s.load)return;accept(thread);s.newThread=false;s.review=null;s.fields={};s.answers={};s.form=false;s.history=false;s.focus={id:'copilot-message'};s.scroll={bottom:true}}catch(error){s.historyError='无法打开这条会话，请刷新后重试。'}finally{s.busy=false;update()}}
  function compactView(thread,turns,generated) {
    const mismatch=changed(),contextual=mismatch?'':renderContext();
    return `<aside id="commerce-copilot" class="copilot-shell copilot-compact" role="region" aria-labelledby="copilot-title"><section class="copilot-panel">
      <header class="copilot-header"><div class="copilot-title"><h2 id="copilot-title">智能助手</h2></div><div class="copilot-header-actions">${button('会话','history',{'aria-label':'查看会话列表','aria-expanded':s.history,'aria-controls':'copilot-history',id:'copilot-history-toggle',icon:'chat'})}${button('新建','new',{disabled:s.busy,icon:'plus','aria-label':'新建对话'})}<details class="copilot-options"><summary aria-label="会话选项">${ui.icon('more')}</summary><div class="copilot-options-panel"><p class="copilot-context-label">${esc(scope(thread?.context||current()))}</p>${methodView()}</div></details></div></header>
      ${s.history?historyView():`${mismatch?`<div class="copilot-scope">${ui.alert('当前会话仍使用原业务范围。','warning')}${button(current().entity?'使用当前'+objectName():'使用当前页面','context',{disabled:s.busy})}</div>`:''}<div id="copilot-log" class="copilot-log" tabindex="0" aria-label="会话记录">${thread?.has_more?button('更早记录','older',{'data-cursor':thread.next_cursor,disabled:s.busy}):''}${turns.map(t=>`<article class="copilot-message copilot-user"><div class="copilot-prose">${esc(t.question||t.message)}</div></article>${renderRun(t.run,t.run?.id===thread?.latest_run?.id?generated:null)}`).join('')}${s.form?form():''}${contextual||(!turns.length&&!mismatch?`<div class="copilot-welcome"><div class="copilot-suggestions">${researchPrompts().map(([label],index)=>button(label,'suggest',{'data-suggestion':index,title:'仅填入问题，发送后才开始处理'})).join('')}</div></div>`:'')}${s.error?ui.alert(s.error,'danger')+(s.errorCode?`<details class="copilot-evidence"><summary>错误详情</summary><code>${esc(s.errorCode)}</code></details>`:''):''}</div><footer class="copilot-composer">${modelView()}<label class="copilot-compose-label" for="copilot-message">问题或补充回答</label><textarea class="ui-control" id="copilot-message" rows="2" maxlength="2000" placeholder="${thread?.latest_run?.status==='awaiting_input'?'补充上面的信息…':'输入问题或补充信息…'}">${esc(draft())}</textarea><div class="copilot-compose-actions">${button(current().entity?.kind==='case'?'成本':'工作区','workspace',{disabled:s.busy||!onWorkspace,icon:current().entity?.kind==='case'?'chart':'box',class:'copilot-workspace-tool','aria-label':current().entity?.kind==='case'?'打开成本参数':'打开商品工作区',title:current().entity?.kind==='case'?'打开当前商品成本参数':'打开商品工作区'})}<span class="muted">⌘ ↵</span>${button(s.busy?'提交中':'','send',{disabled:s.busy||!!s.unavailable||!!mismatch||modelUnavailable()||active.has(thread?.latest_run?.status)||researchBusy()||!draft().trim(),icon:s.busy?'':'arrowUp',class:'copilot-send','aria-label':s.busy?'正在提交':'发送',title:active.has(thread?.latest_run?.status)?'等待本轮处理完成':'发送（⌘ / Ctrl + Enter）'},'primary')}</div></footer>`}</section></aside>`;
  }
  function view(){if(!s.open)return '<div id="commerce-copilot" hidden></div>';const thread=s.thread,turns=thread?.turns||[],generated=thread?.surfaces?surfaces(thread.surfaces):null;if(compact)return compactView(thread,turns,generated);return `<aside id="commerce-copilot" class="copilot-shell" role="${inline?'region':'dialog'}" aria-labelledby="copilot-title" aria-modal="${!inline&&window.innerWidth<1280}"><div class="copilot-backdrop" data-copilot-action="close" aria-hidden="true"></div><section class="copilot-panel"><header class="copilot-header"><div class="copilot-title"><div><h2 id="copilot-title">运营助手</h2></div></div>${button('关闭','close',{'aria-label':'关闭运营助手'})}</header><div class="copilot-threadbar">${ui.field('共享会话',ui.select({id:'copilot-thread',value:thread?.id||'',disabled:s.busy,options:[{value:'',label:'新会话'},...s.threads.map(t=>({value:t.id,label:t.title||'运营会话'}))]}))}${button('新建','new',{disabled:s.busy})}${button('刷新','refresh',{disabled:s.busy})}</div><div class="copilot-scope"><strong>本轮范围</strong><p>${esc(scope(thread?.context||current()))}</p>${changed()?`${ui.alert('页面范围已变化。当前会话仍保留原范围，请明确更新后再发送或审阅。')}${button('使用当前页面范围','context',{disabled:s.busy})}`:''}</div><div id="copilot-log" class="copilot-log" tabindex="0" aria-label="会话记录">${thread?.has_more?button('加载更早记录','older',{'data-cursor':thread.next_cursor,disabled:s.busy}):''}${!turns.length?`<div class="copilot-welcome"><p data-ui-help>一起核对资料、分析问题，把下一步整理成可审阅的建议。</p><div class="copilot-suggestions">${researchPrompts().map(([label],index)=>button(label,'suggest',{'data-suggestion':index,title:'填入问题后点击发送'})).join('')}</div><p class="muted" data-ui-help>点击建议只填入输入框。发送后才会请求模型。会话记录保存在本机服务，未发送文字仅在当前页面保留。</p></div>`:turns.map(t=>`<article class="copilot-message copilot-user"><div class="copilot-message-meta"><strong>你</strong></div><div class="copilot-prose">${esc(t.question||t.message)}</div></article>${renderRun(t.run,t.run?.id===thread?.latest_run?.id?generated:null)}`).join('')}${inline?renderContext():''}${methodView()}${s.form?form():''}${s.error?ui.alert(s.error,'danger')+(s.errorCode?`<details class="copilot-evidence"><summary>错误详情</summary><code>${esc(s.errorCode)}</code></details>`:''):''}</div><footer class="copilot-composer">${modelView()}${ui.field('问题或补充回答',`<textarea class="ui-control" id="copilot-message" rows="3" maxlength="2000" placeholder="描述问题，或补充上一轮所需信息…">${esc(draft())}</textarea>`)}<div class="copilot-compose-actions">${button('补充数据','fields',{disabled:s.busy})}<span class="muted">⌘ / Ctrl + Enter</span>${button(s.busy?'正在提交…':'发送','send',{disabled:s.busy||!!s.unavailable||!!changed()||modelUnavailable()||active.has(thread?.latest_run?.status)||researchBusy()},'primary')}</div><small class="muted"></small></footer></section></aside>`}
  function accept(thread,older=false){if(compact&&sameObject(thread.context))try{localStorage.setItem(selectionKey(),thread.id)}catch{}const previous=s.thread;if(previous?.id!==thread.id){s.thread=thread;return}const turns=new Map();for(const t of older?[...(thread.turns||[]),...(previous.turns||[])]:[...(previous.turns||[]),...(thread.turns||[])])turns.set(t.id||t.run?.id||t.question,t);s.thread={...previous,...thread,turns:[...turns.values()]};if(!older&&Object.hasOwn(previous,'has_more')){s.thread.has_more=previous.has_more;s.thread.next_cursor=previous.next_cursor}}
  async function older(){if(s.busy||!s.thread?.has_more||!s.thread.next_cursor)return;const id=s.thread.id,cursor=s.thread.next_cursor;s.busy=true;s.error='';update();try{const page=await api('commerce_copilot_get',{thread_id:id,before:cursor});if(s.thread?.id!==id)return;remember();const log=document.querySelector('#copilot-log');if(log)s.prependAnchor={top:log.scrollTop,height:log.scrollHeight};accept(page,true)}catch(e){s.error='读取更早记录失败：'+e.message}finally{s.busy=false;update()}}
  async function load(){const seq=++s.load;let models,modelError='';try{const catalog=await originalApi('commerce_model_list',{});if(!Array.isArray(catalog.models))throw Error('invalid_model_catalog');models=catalog.models}catch{modelError='模型选项暂不可用，请刷新或检查后台版本。'}if(seq!==s.load||disposed)return;if(models)s.models=models;s.modelError=modelError;const list=await api('commerce_copilot_list');if(seq!==s.load)return;s.threads=list.threads||[];let thread=null;
    if(s.thread)thread=await api('commerce_copilot_get',{thread_id:s.thread.id});
    else if(!s.newThread&&s.threads.length){let selected;try{if(compact)selected=localStorage.getItem(selectionKey())}catch{}const matches=s.threads.filter(t=>sameObject(t.context)),candidate=compact?(current().entity?(matches.find(t=>t.id===selected)||matches[0]):null):s.threads[0];if(candidate)thread=await api('commerce_copilot_get',{thread_id:candidate.id})}
    if(seq===s.load){if(thread)accept(thread);update()}
  }
  function modelView(){const selected=s.thread?.model_selection?.model_id||'project-default',models=[...(s.models||[{id:'project-default',label:'项目默认',selectable:true}])],disabled=s.busy||active.has(s.thread?.latest_run?.status)||researchBusy();if(!models.some(m=>m.id===selected))models.push({id:selected,label:s.thread?.model_selection?.label||s.thread?.model_selection?.model||'当前模型',selectable:!modelUnavailable()});return `<div class="copilot-modelbar"><label class="sr-only" for="copilot-model">对话模型</label><select id="copilot-model" class="ui-control" aria-label="对话模型" ${disabled?'disabled':''}>${models.map(m=>`<option value="${esc(m.id)}" ${m.id===selected?'selected':''} ${!m.selectable?'disabled':''}>${esc(m.label)}${m.model?' · '+esc(m.model):''}${!m.selectable?'（未就绪）':''}</option>`).join('')}</select>${button('刷新','models-refresh',{'aria-label':'刷新模型列表',title:'刷新模型列表，保留未发送内容',disabled:s.busy})}${button('管理模型','models',{'aria-label':'管理模型','disabled':s.busy})}</div>${modelUnavailable()?'<small class="copilot-model-status" role="status">当前模型不可用，请在管理模型中测试并启用后刷新，或选择其它可用模型。输入已保留。</small>':''}${s.modelError?`<small class="copilot-model-status" role="status">${esc(s.modelError)}</small>`:''}`}
  async function selectModel(id){if(s.busy||active.has(s.thread?.latest_run?.status)||researchBusy())return;s.busy=true;s.error='';update();try{await ensure();accept(await api('commerce_copilot_model',{thread_id:s.thread.id,model_id:id,expected_revision:s.thread.model_selection?.revision||'0'}));s.request=null}catch(e){s.error='模型未切换：'+e.message;await load().catch(()=>{})}finally{s.busy=false;update('copilot-model')}}
  async function ensure(){if(s.thread)return;const previousKey=key(),pending=draft();s.thread=await api('commerce_copilot_open',{context:current(),idempotency_key:s.openKey||(s.openKey=crypto.randomUUID())});s.drafts[key()]=s.drafts[previousKey]??pending;delete s.drafts[previousKey];s.threads=[s.thread,...s.threads.filter(t=>t.id!==s.thread.id)];s.newThread=false}
  async function send(){if(s.busy||s.unavailable||changed()||modelUnavailable()||active.has(s.thread?.latest_run?.status)||researchBusy())return;const submitted=draft(),message=submitted.trim();if(!message){s.error='请填写问题或选择一个建议。';update();return}s.load++;s.busy=true;s.error='';s.errorCode='';update();try{await ensure();const draftFingerprint=canonical({thread:s.thread.id,message,hash:s.thread.context_sha256}),modelSha=s.request?.draftFingerprint===draftFingerprint?s.request.modelSha:s.thread.model_selection?.sha256,fingerprint=canonical({thread:s.thread.id,message,hash:s.thread.context_sha256,expected_model_sha256:modelSha});if(s.request?.fingerprint!==fingerprint)s.request={fingerprint,draftFingerprint,modelSha,key:crypto.randomUUID()};accept(await api('commerce_copilot_send',{thread_id:s.thread.id,message,context_sha256:s.thread.context_sha256,idempotency_key:s.request.key,...(s.request.modelSha?{expected_model_sha256:s.request.modelSha}:{})}));if(draft()===submitted)s.drafts[key()]='';s.request=null;s.scroll={bottom:true};s.focus={id:'copilot-message'}}catch(e){if((e.code||e.message)==='copilot_model_changed'){s.request=null;s.error='模型配置已变化，请核对最新选项后再次发送。输入已保留。';try{await load()}catch{s.error='模型配置已变化，最新选项暂未读回。请刷新核对后再次发送。输入已保留。'}}else s.error='提交未完成：'+e.message+'。未自动重试，输入已保留。'}finally{s.busy=false;update()}}
  function review(runId,proposalId){if(changed())throw Error('页面范围已变化，请先更新会话范围');const run=(s.thread?.turns||[]).map(t=>t.run).find(r=>r?.id===runId),p=run?.result?.proposals?.find(p=>p.id===proposalId);if(!p||!run.result_sha256)throw Error('建议已不可用，请刷新');s.review={thread_id:s.thread.id,run_id:runId,proposal_id:proposalId,result_sha256:run.result_sha256,context_sha256:s.thread.context_sha256,page:canonical(current())};modal('审阅本地建议',`<p>${esc(p.reason)}</p><p><strong>对象与范围：</strong>${esc(scope(s.thread.context))}</p><p><strong>操作：</strong>${esc(({report:'生成本地简报',unit_economics:'计算单件贡献',restock_plan:'计算补货草稿',intel_review:'整理来源证据',organization_handoff:'创建岗位补齐待办',exposure_review:'创建经营关联复核'})[p.operation]||p.operation)}</p><p class="muted">仅提交这一项本地任务；队列接收不代表执行完成。</p><details><summary>查看完整参数与依据</summary><pre class="copilot-review">${esc(JSON.stringify({context:s.thread.context,operation:p.operation,input:p.input},null,2))}</pre></details>`,button('确认参数并提交','apply'))}
  async function act(action,target){
    if(action==='models'){const r=await api('commerce_model_open_setup',{});toast?.(r.opened?'已打开本机模型管理，返回后点击“刷新模型列表”读取配置。':'浏览器打开尚未确认，请重试。');return}
    if(action==='history'){s.history=true;s.focus={id:'copilot-history-query'};update('copilot-history-query');await loadHistory();return}
    if(action==='history-close'){s.history=false;s.historyLoad++;s.historyLoading=false;s.focus={id:'copilot-history-toggle'};update('copilot-history-toggle');return}
    if(action==='history-current'||action==='history-all'){s.historyFilter=action==='history-current'?'current':'all';s.focus=null;update();return}
    if(action==='history-refresh'){await loadHistory();return}
    if(action==='switch-thread'){await switchThread(target.dataset.thread);return}
    if(action==='new'&&compact){if(s.busy)return;s.load++;s.busy=true;s.error='';update();try{const context=current(),fingerprint=canonical(context),previousKey=key(),pending=s.thread?'':draft();if(s.newRequest?.fingerprint!==fingerprint)s.newRequest={fingerprint,key:crypto.randomUUID()};const thread=await api('commerce_copilot_open',{context,idempotency_key:s.newRequest.key});accept(thread);if(pending){s.drafts[thread.id]=pending;delete s.drafts[previousKey]}s.newRequest=null;s.threads=[thread,...s.threads.filter(t=>t.id!==thread.id)];s.newThread=false;s.history=false;s.review=null;s.fields={};s.answers={};s.form=false;s.focus={id:'copilot-message'};s.scroll={bottom:true}}catch(error){s.error='新对话未确认创建，请重试查询；已有输入仍保留。';if(s.history)s.historyError=s.error}finally{s.busy=false;update()}return}
    if(action.startsWith('research-')){
      const job=[s.thread?.research_job,...(s.thread?.turns||[]).map(t=>researchJob(t.run))].find(j=>j?.task_id===target.dataset.task);
      if(!job)throw Error('研究任务已变化，请刷新当前会话。');
      if(action==='research-open'){onResearch?.(job.task_id);return}
      if(action==='research-candidate'){const candidate=(job.candidates||[]).find(c=>c.case_id===target.dataset.case);if(candidate)onOpenCandidate?.(candidate.case_id);return}
      if(s.busy)return;s.busy=true;s.error='';update();
      try{
        if(action==='research-cancel')await api('commerce_market_research_cancel',{task_id:job.task_id});
        if(action==='research-resume'){
          const fingerprint=canonical({task:job.task_id,revision:job.revision});
          if(s.researchResume?.fingerprint!==fingerprint)s.researchResume={fingerprint,key:crypto.randomUUID()};
          await api('commerce_market_research_resume',{task_id:job.task_id,expected_revision:job.revision,idempotency_key:s.researchResume.key});s.researchResume=null;
        }
        await load();
      }catch(error){s.error='研究操作未确认，请刷新原任务核对；不会自动重试。'}finally{s.busy=false;update()}
      return;
    }
    if(action==='workspace'){onWorkspace?.();return}if(action==='close'){close();return}if(action==='send'){await send();return}if(action==='older'){await older();return}if(action==='use-answers'){s.drafts[key()]=Object.entries(s.answers).filter(([,v])=>v.trim()).map(([k,v])=>k+'：'+v).join('\n');s.focus={id:'copilot-message'};update();return}if(action==='reply'){s.focus={id:'copilot-message'};update();return}if(action==='suggest'){s.drafts[key()]=researchPrompts()[Number(target.dataset.suggestion)]?.[1]||'根据当前范围，建议下一步怎么做';s.focus={id:'copilot-message'};update();return}if(action==='fields'){s.form=!s.form;update();return}if(action==='review'){review(target.dataset.run,target.dataset.proposal);return}if(s.busy)return;s.busy=true;s.error='';update();try{
    if(action==='refresh'||action==='models-refresh')await load();
    if(action==='new'){s.load++;s.thread=null;s.newThread=true;s.openKey=null;s.request=null;s.review=null;s.fields={};s.answers={};s.form=false;s.focus={id:'copilot-message'};s.scroll={bottom:true}}
    if(action==='context'){if(!s.thread)await ensure();accept(await api('commerce_copilot_context',{thread_id:s.thread.id,context:current(),expected_context_sha256:s.thread.context_sha256}));s.review=null}
    if(action==='cancel'&&s.thread){accept(await api('commerce_copilot_cancel',{thread_id:s.thread.id,run_id:target.dataset.run}))}
    if(action==='save-fields'){await ensure();const calc=s.fields.calculator||s.thread.context.calculator||'unit_economics',fields=calc==='restock_plan'?stocks:units,input={};for(const k of Object.keys(fields)){const v=s.fields[k]??s.thread.context.input?.[k];if(v!==undefined&&v!==''){if(k==='currency'){if(!/^[A-Z]{3}$/.test(v))throw Error('币种请填写三位大写代码');input[k]=v}else{const n=Number(v);if(!Number.isFinite(n)||n<0)throw Error('请核对 '+fields[k]);input[k]=n}}}accept(await api('commerce_copilot_context',{thread_id:s.thread.id,context:{...s.thread.context,calculator:calc,input},expected_context_sha256:s.thread.context_sha256}));s.form=false;s.scopeOverride={thread:s.thread.id,page:canonical(current()),context:clone(s.thread.context)};s.review=null;toast?.('测算数据已保存，请明确发送问题')}
    if(action==='apply'){const r=s.review;if(!r||r.thread_id!==s.thread?.id||r.context_sha256!==s.thread.context_sha256||r.page!==canonical(current())||changed())throw Error('范围已变化，请关闭并重新审阅');const {page,...args}=r;await api('commerce_copilot_apply',args);s.review=null;closeModal();await load();toast?.('已提交本地任务，请查看任务回执')}
  }finally{s.busy=false;update()}}
  // Explicit calculator additions belong to the thread; compare page context separately.
  function open(context,options={}){if(disposed)return;if(context&&canonical(context)!==canonical(current())){s.error='打开时提供的范围与页面不同，请核对当前页面。'}s.opener=document.activeElement;s.open=true;s.focus=options.focus===false?null:{id:'copilot-message'};s.scroll||={top:0,bottom:!!s.thread?.turns?.length};if(repaint)repaint();else update();load().catch(e=>{s.error='读取会话失败：'+e.message;update()})}
  function close(){s.open=false;s.load++;s.review=null;s.focus=null;update();layout();if(!inline){const opener=s.opener?.isConnected?s.opener:s.opener?.id?document.getElementById(s.opener.id):null;const target=opener||[...document.querySelectorAll('[data-action="copilot-open"]')].find(el=>el.getClientRects().length);target?.focus?.({preventScroll:true})}}
  function contextChanged(){if(disposed||!s.open)return;const page=canonical(current());if(s.page!==page){s.page=page;if(compact&&!s.thread?.turns?.length)s.startAtTop=true}s.review=null;update();if(compact&&!s.thread&&!s.newThread&&!s.busy&&!draft().trim())load().catch(error=>{s.error='读取会话失败：'+error.message;update()})}
  listen(document,'input',e=>{if(e.target.id==='copilot-history-query'){s.historyQuery=e.target.value;const list=document.getElementById('copilot-history-list');if(list&&!s.historyLoading)list.innerHTML=historyRows()}if(e.target.id==='copilot-message'){s.drafts[key()]=e.target.value;syncComposer();}if(e.target.dataset?.copilotAnswer)s.answers[e.target.dataset.copilotAnswer]=e.target.value;if(e.target.dataset?.copilotField)s.fields[e.target.dataset.copilotField]=e.target.value});
  listen(document,'focusin',e=>{if(e.target.closest?.('#commerce-copilot')&&e.target.id)remember()});
  listen(document,'select',e=>{if(e.target.closest?.('#commerce-copilot'))remember()},true);
  listen(document,'keyup',e=>{if(e.target.closest?.('#commerce-copilot'))remember()});
  listen(document,'change',e=>{if(e.target.id==='copilot-model'){selectModel(e.target.value);return}if(e.target.id==='copilot-calculator'){s.fields.calculator=e.target.value;update()}if(e.target.id==='copilot-thread'&&!s.busy){if(!e.target.value){act('new',e.target);return}const id=e.target.value,seq=++s.load;s.busy=true;api('commerce_copilot_get',{thread_id:id}).then(t=>{if(seq===s.load){accept(t);s.newThread=false;s.review=null;s.fields={};s.answers={};s.form=false;s.focus={id:'copilot-thread'};s.scroll={bottom:true}}}).catch(e=>{s.error=e.message}).finally(()=>{s.busy=false;update()})}});
  listen(document,'click',e=>{const options=document.querySelector('.copilot-options[open]');if(options&&!options.contains(e.target))options.removeAttribute('open');const t=e.target.closest?.('[data-copilot-action]');if(!t)return;e.preventDefault();t.closest('.copilot-options')?.removeAttribute('open');act(t.dataset.copilotAction,t).catch(error=>{s.error='操作未完成：'+error.message;toast?.(s.error);update()})});
  listen(document,'compositionstart',e=>{if(e.target.id==='copilot-message')s.composing=true});
  listen(document,'compositionend',e=>{if(e.target.id==='copilot-message')s.composing=false});
  listen(document,'keydown',e=>{if(!s.open||!isActive()||document.querySelector('.dialog'))return;if(s.history&&e.key==='Escape'){e.preventDefault();s.history=false;s.historyLoad++;s.historyLoading=false;s.focus={id:'copilot-history-toggle'};update('copilot-history-toggle');return}const options=document.querySelector('.copilot-options[open]');if(compact&&options&&e.key==='Escape'){e.preventDefault();options.removeAttribute('open');options.querySelector('summary')?.focus();return}if(e.key==='Escape'&&!inline){e.preventDefault();close();return}if(e.target.id==='copilot-message'&&e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.isComposing&&!s.composing&&e.keyCode!==229){e.preventDefault();send();return}if(e.key==='Tab'&&!inline&&window.innerWidth<1280){const nodes=[...document.querySelectorAll('#commerce-copilot button:not(:disabled),#commerce-copilot input:not(:disabled),#commerce-copilot select:not(:disabled),#commerce-copilot textarea,#commerce-copilot [tabindex="0"]')].filter(n=>n.getClientRects().length),first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&(document.activeElement===first||!document.activeElement.closest?.('#commerce-copilot'))){e.preventDefault();last?.focus()}else if(!e.shiftKey&&(document.activeElement===last||!document.activeElement.closest?.('#commerce-copilot'))){e.preventDefault();first?.focus()}}});
  listen(window,'resize',()=>{if(s.open)layout()});
  const polling=setInterval(()=>{if(s.open&&isActive()&&!s.busy&&!document.querySelector('.dialog')&&(active.has(s.thread?.latest_run?.status)||researchWatching()))load().catch(e=>{s.error='状态读取未完成：'+e.message;update()})},2000);
  function dispose(){if(disposed)return;disposed=true;s.open=false;s.load++;s.historyLoad++;clearInterval(polling);listeners.splice(0).forEach(remove=>remove())}
  return {view,open,close,afterPaint,contextChanged,dispose,openThread:switchThread};
};

/* Product surface: same domain identities and components in browser and native iframe. */
(() => {
  'use strict';
  const root = document.getElementById('product-app');
  if (!root) return;
  const ui = window.CommerceUI, esc = ui.escape;
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
    const known = {agent_evidence_reference_required:'模型答复缺少来源引用，未采纳本轮结果；核对资料后可明确发送新问题。',workspace_source_changed:'资料已更新，输入已保留。请核对后重新保存。',form_draft_conflict:'草稿已有新版本，输入已保留。请核对后合并。',organization_case_not_found:'当前连接中找不到这个工作项。请核对连接与商品范围。',workspace_content_checkpoint_required:'请先保存当前内容编辑，再生成待审阅版本。',workspace_currency_required:'请先明确工作项币种，并使用相同币种测算。',workspace_artifact_changed:'原产物完整性检查未通过，请先核对来源。',workspace_handoff_held:'成本产物交接尚未确认，请核对原记录。',business_preflight_incomplete:'草稿仍有缺项、无效引用或过期来源，请补齐后再审阅。',business_draft_changed:'草稿版本已变化，请重新读取并审阅。',agent_provider_outcome_unknown:'模型结果尚未确认。请核对原请求记录，不会自动重发。',agent_model_setup_required:'当前模型入口尚未配置，请完成本机接入后继续。',agent_current_evidence_required:'当前依据不足或已改变，请重新核对来源后再分析。',authentication_required:'本次连接没有有效授权，请通过项目正常入口重新打开。',unknown_tool:'当前后台尚未加载商品工作区接口，请核对运行版本。',commerce_service_unavailable:'共享后台暂不可用。输入已保留，请恢复连接后查询原记录。'};
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
      reload({select:caseId}).then(()=>reply(s.generation!==generation||s.id!==caseId?'superseded':s.error?'failed':'refreshed'));
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
    return c?{module:'organization',demo:c.scope.synthetic===true,platform:c.scope.platform,market:c.scope.market,entity:{kind:'case',id:c.id}}:{module:'organization'};
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
      copilot=window.CommerceCopilot({api,ui,toast:announce,modal:dialog,closeModal:closeDialog,getContext:modelContext,inline:true,compact:true,onResearch:id=>{if(bridged)parent.postMessage({type:'commerce:workspace-research',nonce,task_id:id},'*');else location.assign('/workspace?tab=pilots&research_task_id='+encodeURIComponent(id))},onOpenCandidate:openResearchCandidate,onWorkspace:()=>{if(s.data)selectTab('cost');else{if(innerWidth<1024){s.mobile='product';applyMobile()}document.querySelector('#pw-case')?.focus()}},renderContext:taskSummary,errorText:message,scopeLabel:c=>[platformNames[c?.platform]||c?.platform,c?.market,s.items.find(x=>x.id===c?.entity?.id)?.name||(c?.entity?.id?'工作项 '+c.entity.id.slice(0,8):''),c?.demo?'合成示例':'本机资料 · 待核实'].filter(Boolean).join(' · '),repaint:renderChat});
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
  function researchView(compact=false) {
    const a=s.data.artifacts.research;
    if(!a)return section('市场研究',empty('尚无研究资料。')+(compact?'':gaps(['S1','S5'])),btn(compact?'补充资料':'导入资料',compact?'tab-research':'research-source'));
    const record=a.payload.record,priority=['description','attributes','specifications','title','price','reviews'];
    const rows=Object.entries(record.fields||{}).filter(([,f])=>f.original||f.zh).sort(([a],[b])=>(priority.includes(a)?priority.indexOf(a):99)-(priority.includes(b)?priority.indexOf(b):99));
    const unique=rows.filter(([,f],i)=>rows.findIndex(([,v])=>(v.zh||v.original)===(f.zh||f.original))===i);
    const labels={findings:'研究结论',limitations:'资料限制',title:'商品标题',description:'商品描述',price:'价格依据',reviews:'评价依据',specifications:'规格',attributes:'商品属性',availability:'可售范围',barcode:'条码',brand:'品牌',category:'类目',dimensions:'包装尺寸',weight:'重量',images:'素材',quantity:'数量',stock:'库存',sku:'SKU',name:'商品名称'};
    const state=!a.intact?'完整性异常':rows.every(([,f])=>f.reviewed)?'已校对':'待校对';
    if(compact)return section('市场研究 '+ui.badge(state,a.intact?'gray':'danger'),`${!a.intact?alert('资料完整性异常，请核对来源。','danger'):''}<dl class="pw-research-fields pw-research-brief">${(unique.filter(([k])=>k!=='title').length?unique.filter(([k])=>k!=='title'):unique).slice(0,2).map(([key,f])=>`<div><dt>${esc(labels[key]||key)}</dt><dd><p class="pw-research-summary">${esc(f.zh||f.original)}</p></dd></div>`).join('')}</dl><div class="pw-research-note"><span>${esc(record.language||'')} · ${stamp(record.captured_at).split(' ')[0]}</span></div>`,btn('查看研究','tab-research'));
    return section('市场研究',`<div class="pw-inline-meta">${ui.badge(state,a.intact?'gray':'danger')}<span>${esc(record.language||'')} · ${stamp(record.captured_at)}</span></div>${!a.intact?alert('资料完整性异常，请核对来源。','danger'):''}<dl class="pw-research-fields">${unique.map(([key,f])=>`<div><dt>${esc(labels[key]||key)}</dt><dd><p>${esc(f.zh||f.original)}</p><details><summary>${f.reviewed?'原文与校对记录':'原文 · 待校对'}</summary>${f.zh?`<p lang="${esc(record.language||'en')}">${esc(f.original)}</p>`:''}<p>${esc(f.locator||'无定位信息')}</p></details></dd></div>`).join('')}</dl><details class="pw-disclosure"><summary>来源资料</summary><p class="pw-source-text">${esc(record.source_url||'来源未提供')}</p><p>${esc(record.raw_excerpt||'无原始摘录')}</p><p class="pw-meta">资料尚未独立核实。</p></details>`,btn('补充资料','research-source'))+supplyView();
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
  async function reload({select=s.id,clearEditors=false}={}) {
    const previousContext=JSON.stringify(modelContext()),restoreView=!s.data||select!==s.id,generation=++s.generation;s.busy=true;render();
    try {
      const list=await api('commerce_workspace_list');if(generation!==s.generation)return;
      s.items=list.items;
      if(!select&&list.items.length===1)select=list.items[0].id;
      if(select){const data=await api('commerce_workspace_get',{case_id:select});if(generation!==s.generation)return;s.id=select;s.data=data;if(restoreView){const requested=!bridged?new URL(location.href).searchParams.get('tab'):null;s.tab=tabs[requested]?requested:data.forms.view?.payload?.tab||'overview'}
        if(clearEditors){s.edits={};s.dirty.clear()}
        if(!bridged){const url=new URL(location.href);url.searchParams.set('case_id',select);history.replaceState(null,'',url)}
        if(!embedded&&previousContext!==JSON.stringify(modelContext()))copilot?.contextChanged();
        if(bridged)parent.postMessage({type:'commerce:workspace-selected',nonce,case_id:select},'*');
      }else{s.id='';s.data=null}
      s.error='';s.errorCode='';
    } catch(error){if(generation===s.generation){s.error=message(error);s.errorCode=error.code||error.message}}
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
  function openResearchCandidate(id) {
    if(!id||s.busy)return;
    if(id===s.id){selectTab('research');return}
    const proceed=()=>{closeDialog();return reload({select:id,clearEditors:true})};
    if(s.dirty.size)dialog('打开调研候选','<p>当前商品有未保存输入，请先返回保存，或明确放弃后打开候选。</p>',btn('放弃修改并打开','dialog-proceed')+btn('返回编辑','dialog-close'),proceed);
    else proceed();
  }
  function goalDialog() {
    const plan=formData('plan');
    dialog('工作目标',`${ui.field('本次目标',`<textarea class="ui-control" id="pw-goal" maxlength="2000" rows="4">${esc(plan.goal)}</textarea>`)}${ui.field('已确认的步骤（每行一步）',`<textarea class="ui-control" id="pw-steps" rows="5" maxlength="2000">${esc(plan.steps.map(x=>x.title).join('\n'))}</textarea>`)}<p class="pw-meta">保存目标与步骤不会自动派发任务。</p>`,btn('保存目标','save-plan',true)+btn('取消','dialog-close'));
  }
  function download(result) {const url=URL.createObjectURL(new Blob([result.content],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=result.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  async function act(action,target) {
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
