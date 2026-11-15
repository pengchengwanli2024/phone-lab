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
  const permitted=/^(class|id|type|title|role|tabindex|name|value|placeholder|maxlength|min|max|step|autocomplete|disabled|readonly|required|checked|aria-[a-z-]+|data-[a-z0-9-]+)$/;
  function attributes(values={}){
    return Object.entries(values).filter(([key,value])=>permitted.test(key)&&value!==undefined&&value!==null&&(key!=='tabindex'||['-1','0'].includes(String(value)))&&(value!==false||key.startsWith('aria-')||key.startsWith('data-'))).map(([key,value])=>value===true&&['disabled','readonly','required','checked'].includes(key)?key:`${key}="${escape(value)}"`).join(' ');
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
  // These views accept data only. Source text never becomes markup or an action.
  function evidence({title='来源依据',quote='',sourceId='',version='',recordKey='',recordId='',sha256='',verification='unknown',detailKey=''}={}){
    const states={imported_unverified:'导入资料 · 未独立核实',confirmed:'人工确认 · 未独立核实',active:'有效摘要 · 未独立核实',not_independently_verified:'未独立核实',stale:'来源已变化 · 待核对',withdrawn:'已撤回'};
    const label=states[verification]||'核实状态未知';
    const provenance=[['记忆记录',recordId],['来源',sourceId],['版本',version],['记录',recordKey],['SHA-256',sha256]].filter(([,v])=>v!==''&&v!=null);
    return `<section class="ui-evidence" aria-label="来源依据"><header><strong>${escape(title)}</strong>${badge(label,['stale','withdrawn'].includes(verification)?'warning':'gray')}</header>${quote?`<blockquote>${escape(quote)}</blockquote>`:''}${provenance.length?`<details ${attributes({'data-view-key':detailKey||undefined})}><summary>来源与版本</summary><dl>${provenance.map(([k,v])=>`<div><dt>${escape(k)}</dt><dd>${escape(v)}</dd></div>`).join('')}</dl></details>`:''}</section>`;
  }
  function fieldDiff({rows=[],beforeLabel='当前参数',afterLabel='建议参数',emptyText='参数一致。'}={}){
    const value=v=>v==null||v===''?'未知':typeof v==='object'?JSON.stringify(v):String(v);
    return rows.length?`<div class="ui-field-diff">${table(['字段',beforeLabel,afterLabel],rows.map(row=>`<tr ${attributes({'data-field-id':row.key})}><th scope="row">${escape(row.label||row.key)}</th><td>${escape(value(row.before))}</td><td>${escape(value(row.after))}</td></tr>`))}</div>`:`<p class="muted ui-field-diff-empty">${escape(emptyText)}</p>`;
  }
  function receipt(value={}){
    const outcome=['succeeded','failed','cancelled','pending'].includes(value.outcome)?value.outcome:'unknown';
    const label=outcome==='succeeded'?'本地处理完成':outcome==='failed'?'本地处理失败':outcome==='cancelled'?'已取消':outcome==='pending'?(value.status==='running'?'本地处理中':'排队中'):'结果待核对';
    const note=outcome==='pending'?'尚未完成，请核对后续回执。':outcome==='unknown'?'执行结果尚未确认，请核对原任务；不会自动重试。':outcome==='succeeded'?'本地任务已完成；资料核实状态仍以原依据为准。':'请核对原任务；不会自动重试。';
    return `<section class="ui-receipt" aria-label="任务回执" ${attributes({'data-task-id':value.task_id})}><header><strong>任务回执</strong>${badge(label,outcome==='succeeded'?'success':outcome==='failed'?'danger':'gray')}</header><p>${escape(note)}</p><dl><div><dt>任务</dt><dd>${escape(value.task_id||'待核对')}</dd></div>${value.finished_at?`<div><dt>完成时间</dt><dd>${escape(value.finished_at)}</dd></div>`:''}${value.result_sha256?`<div><dt>结果 SHA-256</dt><dd>${escape(value.result_sha256)}</dd></div>`:''}</dl>${value.external_operations_executed===false?'<small class="muted">未执行外部操作</small>':''}</section>`;
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
  const icon=(name='grid')=>{const paths={plus:'<path d="M12 5v14M5 12h14"/>',arrowUp:'<path d="M12 19V5m-6 6 6-6 6 6"/>',panelLeft:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',chevronDown:'<path d="m6 9 6 6 6-6"/>',more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',bell:'<path d="M5 9a7 7 0 0 1 14 0v6l2 3H3l2-3zM9 21h6"/>',chart:'<path d="M3 3v18h18M7 16v-5m5 5V6m5 10V9"/>',person:'<circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/>',image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-7 5 8"/>',grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',chat:'<path d="M3 4h18v13H9l-6 4z"/><path d="M8 9h8M8 13h5"/>',store:'<path d="M4 10v11h16V10M3 3h18l1 7H2zM9 21v-7h6v7"/>',cart:'<path d="M2 3h3l3 13h11l3-10H6"/><circle cx="9" cy="21" r="1"/><circle cx="19" cy="21" r="1"/>',clock:'<circle cx="12" cy="12" r="10"/><path d="M12 5v7l5 3"/>',box:'<path d="m12 2 10 5v11l-10 5-10-5V7zM2 7l10 5 10-5M12 12v11M7 4l10 6v5"/>',bolt:'<path d="m14 1-12 13h9l-1 9 12-14h-9z"/>',book:'<path d="M2 3h8l2 2 2-2h8v17h-8l-2 2-2-2H2zM12 5v17"/>',code:'<path d="m8 4-7 8 7 8m8-16 7 8-7 8M14 2l-4 20"/>',link:'<path d="m9 15 6-6M8 6l2-2a5 5 0 0 1 7 7l-2 2M16 18l-2 2a5 5 0 0 1-7-7l2-2"/>',info:'<circle cx="12" cy="12" r="10"/><path d="M12 11v6m0-11v1"/>',gear:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 1v3m0 16v3M1 12h3m16 0h3"/>',headset:'<path d="M3 14v-3a9 9 0 0 1 18 0v3M3 12h4v7H3zM17 12h4v7h-4zM17 20l-5 2"/>',doc:'<path d="M5 2h10l5 5v15H5zM15 2v6h5M9 12h7M9 16h7"/>',phone:'<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',spark:'<path d="m12 1 3 8 8 3-8 3-3 8-3-8-8-3 8-3z"/>'};return `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${paths[name]||paths.grid}</svg>`};
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
  function chatLayout(areaWidth,preferred){
    const area=Number.isFinite(Number(areaWidth))&&Number(areaWidth)>0?Number(areaWidth):1024;
    const min=320,max=Math.max(min,Math.min(area>=1800?960:640,Math.round((area-24)*.5),area-514));
    const saved=Number(preferred),fallback=Math.min(400,Math.round((area-24)*.3/8)*8);
    return {min,max,width:Math.round(Math.max(min,Math.min(max,Number.isFinite(saved)&&saved>0?saved:fallback)))};
  }
  function observeReadingRegions(root=document){
    if(typeof ResizeObserver!=='function'||typeof MutationObserver!=='function')return ()=>{};
    const selector='.ui-table,.r-table-wrap,.r-section-tabs,.r-business-nav,.pw-tabs';
    const regions=new Map();let scheduled=false,disposed=false;
    const restore=(el,previous)=>{for(const key of ['tabindex','role','aria-label']){const value=previous[key];if(value===null)el.removeAttribute(key);else el.setAttribute(key,value)}el.removeAttribute('data-ui-scrollable')};
    const update=el=>{
      const overflow=el.clientWidth>0&&el.scrollWidth>el.clientWidth+1;
      const previous=regions.get(el);if(!previous)return;
      if(!overflow){if(el.hasAttribute('data-ui-scrollable'))restore(el,previous);return}
      if(!el.hasAttribute('data-ui-scrollable')){
        if(previous.tabindex===null)el.setAttribute('tabindex','0');
        if(el.matches('.ui-table,.r-table-wrap')){
          if(previous.role===null)el.setAttribute('role','region');
          if(previous['aria-label']===null){const title=el.closest('section,.card')?.querySelector('h2,h3')?.textContent?.trim().slice(0,60);el.setAttribute('aria-label',(title||'数据表')+'，可横向滚动')}
        }
        el.setAttribute('data-ui-scrollable','true');
      }
    };
    const resize=new ResizeObserver(entries=>entries.forEach(entry=>update(entry.target)));
    const sync=()=>{
      scheduled=false;if(disposed)return;
      for(const [el,previous] of regions)if(!el.isConnected){resize.unobserve(el);restore(el,previous);regions.delete(el)}
      for(const el of root.querySelectorAll(selector)){
        if(!regions.has(el)){regions.set(el,Object.fromEntries(['tabindex','role','aria-label'].map(key=>[key,el.getAttribute(key)])));resize.observe(el)}
        update(el);
      }
    };
    const mutation=new MutationObserver(()=>{if(!scheduled&&!disposed){scheduled=true;requestAnimationFrame(sync)}});
    mutation.observe(root.documentElement||root,{childList:true,subtree:true});sync();
    return ()=>{disposed=true;resize.disconnect();mutation.disconnect();for(const [el,previous] of regions)restore(el,previous);regions.clear()};
  }
  if(typeof document.querySelectorAll==='function'&&typeof ResizeObserver==='function'){
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>observeReadingRegions(),{once:true});
    else observeReadingRegions();
  }
  applyTheme('system');
  return Object.freeze({version:'1.4.0',applyTheme,getTheme,chatLayout,observeReadingRegions,icon,escape,attributes,legacyAttributes,button,badge,input,select,field,empty,alert,card,table,evidence,fieldDiff,receipt,tabs,navigationGroups,moduleDetails,moduleDirectory,modal,status:(code,capabilities)=>globalThis.CommerceStatus.describe(code,capabilities)});
})();

/* Shared browser / Harness conversational sidecar. Drafts never enter model tools. */
window.CommerceCopilotDraftStorage=(target=window)=>{
  const nonce='__COMMERCE_BRIDGE_NONCE__',pending=new Map();let disposed=false;
  const receive=event=>{if(event.source!==target.parent||event.data?.nonce!==nonce||event.data?.type!=='commerce:copilot-draft-result')return;const item=pending.get(event.data.id);if(!item)return;clearTimeout(item.timer);pending.delete(event.data.id);event.data.error?item.reject(Error(event.data.error)):item.resolve(event.data.value)};
  target.addEventListener('message',receive);
  const request=async(op,key,value,expected)=>{
    if(disposed)throw Error('draft_storage_unavailable');
    if(typeof key!=='string'||key.length>8000||!key.startsWith('commerce-copilot-draft-v1:'))throw Error('invalid_draft_key');
    const scope=key.slice(26);if(scope.startsWith('new:')){let context;try{context=JSON.parse(scope.slice(4))}catch{}if(!context||typeof context.module!=='string'||!/^[a-z_]{1,40}$/.test(context.module)||typeof context.demo!=='boolean')throw Error('invalid_draft_key')}else if(!/^[a-zA-Z0-9_-]{1,160}$/.test(scope))throw Error('invalid_draft_key');
    if(op!=='read'&&(op!=='write'||typeof value!=='string'||value.length>2000||typeof expected!=='string'||expected.length>2000))throw Error('invalid_draft_value');
    if(target.parent&&target.parent!==target){const id=crypto.randomUUID();return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{pending.delete(id);reject(Error('draft_storage_unavailable'))},5000);pending.set(id,{resolve,reject,timer});target.parent.postMessage({type:'commerce:copilot-draft',nonce,id,op,key,value,expected},'*')})}
    const operate=()=>{if(disposed)throw Error('draft_storage_unavailable');const stored=localStorage.getItem(key)||'';if(op==='read')return stored;if(stored!==expected)throw Error('draft_storage_conflict');localStorage.setItem(key,value);return value};
    return target.navigator?.locks?target.navigator.locks.request(key,operate):operate();
  };
  return {request,dispose(){disposed=true;target.removeEventListener('message',receive);for(const item of pending.values()){clearTimeout(item.timer);item.reject(Error('draft_storage_unavailable'))}pending.clear()}};
};
window.CommerceCopilot=({api,ui=window.CommerceUI,toast,modal,closeModal,getContext,isActive=()=>true,repaint,inline=false,renderContext=()=>'',scopeLabel=null,errorText=null,compact=false,onWorkspace=null,onResearch=null,onOpenCandidate=null,onModels=null})=>{
  const esc=ui.escape,active=new Set(['queued','running','cancel_requested']);
  const status={queued:'排队中',running:'正在分析',awaiting_input:'等待补充',awaiting_review:'等待审阅',completed:'已返回',failed:'未完成',unknown:'结果未知',interrupted:'已中断',cancelled:'已取消',cancel_requested:'请求停止中'};
  const s={open:false,thread:null,threads:[],drafts:{},busy:false,error:'',focus:null,opener:null,load:0,review:null,fields:{},answers:{},form:false,newThread:false,modelMenu:false,modelCatalogReady:false,history:false,historyQuery:'',historyFilter:'current',historyLoading:false,historyError:'',historyLoad:0};
  let disposed=false;
  const listeners=[];
  const listen=(target,type,handler,options)=>{const guarded=event=>{if(!disposed)handler(event)};target.addEventListener(type,guarded,options);listeners.push(()=>target.removeEventListener(type,guarded,options))};
  const originalApi=api;
  api=async(name,args)=>{try{const value=await originalApi(name,args);s.unavailable=false;return value}catch(error){if(error.code==='unknown_tool'||error.message==='unknown_tool'){s.unavailable=true;throw Error('当前共享后台尚未启用运营助手，请在服务更新后刷新重试。')}if(errorText){const code=error.code||error.message;s.errorCode=typeof code==='string'&&/^[a-z][a-z0-9_]{0,79}$/.test(code)?code:'';const mapped=Error(errorText(error));mapped.code=code;throw mapped}throw error}};
  const draftStorage=window.CommerceCopilotDraftStorage(),draftLoads=new Map(),draftWrites=new Map(),draftVersions=new Map(),draftSaved=new Map();
  const key=()=>s.thread?.id||'new:'+canonical(current()),draft=()=>{restoreDraft(key());return s.drafts[key()]||''};
  const draftKey=k=>'commerce-copilot-draft-v1:'+k;
  function restoreDraft(k){if(draftLoads.has(k))return draftLoads.get(k);const version=draftVersions.get(k)||0;const load=draftStorage.request('read',draftKey(k)).then(value=>{if(typeof value!=='string'||value.length>2000)throw Error('invalid_draft_value');draftSaved.set(k,value);if((draftVersions.get(k)||0)===version){s.drafts[k]=value;if(!disposed&&key()===k)update()}else if(value)throw Error('draft_storage_conflict')}).catch(()=>{draftSaved.delete(k);s.draftSaveError='草稿暂未保存在本机，关闭前请保留当前输入。';if(!disposed)update()});draftLoads.set(k,load);return load}
  function setDraft(k,value){const ready=restoreDraft(k);s.drafts[k]=value;draftVersions.set(k,(draftVersions.get(k)||0)+1);const write=(draftWrites.get(k)||ready).then(async()=>{if(!draftSaved.has(k))return false;const saved=await draftStorage.request('write',draftKey(k),value,draftSaved.get(k));draftSaved.set(k,saved);s.draftSaveError='';return true}).catch(()=>{draftSaved.delete(k);s.draftSaveError='草稿保存遇到冲突或连接中断，当前输入仍保留。';if(!disposed)update();return false});draftWrites.set(k,write);return write}
  const clone=v=>JSON.parse(JSON.stringify(v||{}));
  const canonical=v=>JSON.stringify(v&&typeof v==='object'?(Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))]))):v??null);
  const current=()=>clone(getContext?.()||{}),changed=()=>s.thread&&!(s.scopeOverride?.thread===s.thread.id&&s.scopeOverride.page===canonical(current())&&canonical(s.scopeOverride.context)===canonical(s.thread.context))&&canonical(s.thread.context)!==canonical(current());
  const replyingOriginal=()=>!!(s.replyScope&&s.thread&&s.replyScope.thread===s.thread.id&&s.replyScope.hash===s.thread.context_sha256&&s.replyScope.page===canonical(current()));
  const button=(label,action,attrs={},variant='secondary')=>ui.button({label,variant,leadingIcon:attrs.icon||'',attrs:{'data-copilot-action':action,...attrs}});
  const researchActive=job=>job&&['queued','running','cancelling'].includes(job.status);
  const researchJob=run=>run?.research_job||(s.thread?.research_job?.run_id===run?.id?s.thread.research_job:null);
  const researchBusy=()=>researchActive(s.thread?.research_job)||(s.thread?.turns||[]).some(t=>researchActive(researchJob(t.run)));
  const researchWatching=()=>[s.thread?.research_job,...(s.thread?.turns||[]).map(t=>researchJob(t.run))].some(job=>job&&['queued','running','awaiting_input','cancelling'].includes(job.status));
  const selectedModelId=()=>s.thread?.model_selection?.model_id||s.defaultModelId||'project-default';
  const defaultModelPending=()=>!s.thread?.model_selection&&!s.modelCatalogReady;
  const modelUnavailable=()=>{const selection=s.thread?.model_selection,id=selectedModelId(),model=s.models?.find(m=>m.id===id);return defaultModelPending()||selection?.available===false||model?.selectable===false||(id!=='project-default'&&Array.isArray(s.models)&&!model)};
  function runModel(run){const choice=run.model_choice||{},actual=typeof run.result?.model==='string'?run.result.model:choice.model,label=[choice.label,actual].filter((v,i,a)=>typeof v==='string'&&v&&a.indexOf(v)===i).join(' · ');return label?`<span class="copilot-run-model" title="${esc(label+(choice.profile_revision!=null?' · 配置版本 '+choice.profile_revision:''))}">${esc(label)}</span>`:''}
  const researchPrompts=()=>['overview','research','pilots'].includes(current().module)?[['俄罗斯市场调研','我要调研俄罗斯市场。请先确认品类与研究目标，再采集真实公开资料、分析并保存候选商品。'],['按条件选品','帮我选品。请先确认目标市场、品类和预算，再采集真实公开资料并保存候选。']]:[['核对资料缺项','梳理当前工作有哪些资料缺项']];
  function researchView(run){
    const job=researchJob(run);if(!job||job.schema!=='commerce-market-research-v1')return '';
    const later=(s.thread?.turns||[]).findLast(t=>researchJob(t.run)?.task_id===job.task_id);if(later&&later.run.id!==run.id)return '';
    const phases={planning:'明确研究范围',collecting:'采集公开资料',analyzing:'分析市场证据',saving:'保存商品候选',finished:'研究结束'},states={queued:'排队中',running:'研究中',awaiting_input:'待补充',completed:'已完成',partial:'部分完成',failed:'未完成',unknown:'结果待核对',interrupted:'已中断',cancelling:'正在停止',cancelled:'已停止'};
    const count=n=>Number.isInteger(n)&&n>=0?n:'待核对';
    const provided=Array.isArray(job.questions)?job.questions.filter(q=>typeof q==='string'&&q.trim()):[];
    const questions=job.status==='awaiting_input'?[...new Set(provided.length?provided:job.run_id===run.id&&Array.isArray(run.result?.questions)?run.result.questions.filter(q=>typeof q==='string'&&q.trim()):[])]:[];
    const supplemented=Number.isInteger(job.supplemental_source_count)&&job.supplemental_source_count>0;
    const candidates=job.candidates||[],shown=candidates.some(c=>c.research_run_id)?candidates.filter(c=>c.research_run_id===job.run_id):candidates;
    return `<section class="copilot-research" aria-label="市场研究任务" data-research-task="${esc(job.task_id)}"><header><strong>${esc(researchActive(job)?phases[job.phase]||'研究中':states[job.status]||'状态待核对')}</strong>${ui.badge(job.market==='RU'?'俄罗斯':job.market||'市场待核对','gray')}</header><div class="copilot-research-counts"><span>${supplemented?'采集来源':'来源'} ${count(job.source_count)}</span>${supplemented?`<span>补充资料 ${count(job.supplemental_source_count)}</span>`:''}<span>已保存候选 ${count(job.candidate_count)}</span></div>${job.error?ui.alert(job.error.message||'研究未完成，请核对原任务。','warning'):''}${job.report?.summary?`<p class="copilot-research-summary">${esc(job.report.summary.length>180?job.report.summary.slice(0,180)+'…':job.report.summary)}</p>`:''}${questions.map(q=>`<p class="copilot-question">${esc(q)}</p>`).join('')}${shown.slice(0,3).map(c=>`<div class="copilot-research-candidate"><span>${esc(c.name)}</span>${onOpenCandidate?button('打开候选','research-candidate',{'data-task':job.task_id,'data-case':c.case_id}):''}</div>`).join('')}<div class="copilot-research-actions">${onResearch?button('查看研究','research-open',{'data-task':job.task_id}):''}${researchActive(job)?button(job.status==='cancelling'?'正在停止':'停止研究','research-cancel',{'data-task':job.task_id,disabled:s.busy||job.status==='cancelling'}):''}${['interrupted','failed','unknown'].includes(job.status)?button('继续原任务','research-resume',{'data-task':job.task_id,disabled:s.busy}):''}${job.status==='awaiting_input'?button('补充研究要求','reply',{icon:'chat'}):''}</div></section>`;
  }
  const scope=c=>{if(scopeLabel)return scopeLabel(c);const platforms={ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu'},kinds={order:'订单',product:'商品',case:'工作项',intel:'情报'};return [ui.moduleDetails(c?.module||'').description,c?.demo?'合成示例':'按本页来源',!c?.platform||c.platform==='all'?'全部平台':platforms[c.platform]||c.platform,!c?.store_id||c.store_id==='all'?'全部店铺':`店铺 ${c.store_id}`,!c?.market||c.market==='all'?'全部市场':c.market,c?.entity?`${kinds[c.entity.kind]||'当前对象'} ${c.entity.id}`:''].filter(Boolean).join(' · ')};
  let paintedKey=null;
  function remember(){
    if(paintedKey!==key())return;
    const e=document.activeElement,inside=e?.closest?.('#commerce-copilot');
    if(inside){const detail=e.closest?.('[data-view-key]');s.focus=e.id?{id:e.id,start:e.selectionStart,end:e.selectionEnd,direction:e.selectionDirection}:detail?{viewKey:detail.dataset.viewKey}:null}
    else s.focus=null;
    const root=document.querySelector('#commerce-copilot');
    s.disclosures=root?.querySelectorAll?[...root.querySelectorAll('details[data-view-key]')].filter(el=>el.open).map(el=>el.dataset.viewKey):[];
    const log=document.querySelector('#copilot-log');
    if(log){const top=log.getBoundingClientRect?.().top||0,anchor=[...(log.querySelectorAll?.('[data-message-key]')||[])].find(el=>el.getBoundingClientRect().bottom>top+1);s.scroll={top:log.scrollTop,bottom:log.scrollHeight-log.scrollTop-log.clientHeight<64,anchor:anchor?.dataset.messageKey,offset:anchor?anchor.getBoundingClientRect().top-top:0}}
  }
  function update(focus){
    if(disposed)return;
    if(s.composing&&s.open&&document.getElementById('copilot-message')){s.pendingPaint=true;if(focus)s.pendingFocus=focus;return}
    remember();if(focus)s.focus={id:focus};
    const root=document.querySelector('#commerce-copilot');
    if(root){
      const editor=paintedKey===key()?document.getElementById('copilot-message'):null;
      const t=document.createElement('template');t.innerHTML=view();
      const next=t.content.querySelector?.('#copilot-message');
      if(editor&&next){for(const name of ['placeholder','rows','maxlength'])if(next.hasAttribute(name))editor.setAttribute(name,next.getAttribute(name));if(editor.value!==next.value)editor.value=next.value;next.replaceWith(editor)}
      root.replaceWith(t.content);afterPaint();
    }else if(repaint)repaint();
  }
  function layout(){const docked=s.open&&(inline||window.innerWidth>=1280);document.querySelector('#commerce-copilot')?.setAttribute('aria-modal',String(!docked));window.dispatchEvent(new CustomEvent('commerce:copilot-layout',{detail:{open:s.open,docked}}))}
  function afterPaint(){
    if(disposed||!s.open)return;
    const same=paintedKey===key();paintedKey=key();layout();syncComposer();
    const root=document.querySelector('#commerce-copilot');
    if(same&&root?.querySelectorAll)for(const el of root.querySelectorAll('details[data-view-key]'))el.open=(s.disclosures||[]).includes(el.dataset.viewKey);
    const log=document.querySelector('#copilot-log');
    if(log&&s.startAtTop){log.scrollTop=0;s.scroll={top:0,bottom:false};s.startAtTop=false}
    else if(log&&s.scroll){const anchor=same&&s.scroll.anchor?[...(log.querySelectorAll?.('[data-message-key]')||[])].find(el=>el.dataset.messageKey===s.scroll.anchor):null;if(s.scroll.bottom)log.scrollTop=log.scrollHeight;else if(anchor)log.scrollTop+=anchor.getBoundingClientRect().top-log.getBoundingClientRect().top-s.scroll.offset;else if(s.prependAnchor)log.scrollTop=s.prependAnchor.top+log.scrollHeight-s.prependAnchor.height;else log.scrollTop=s.scroll.top}
    s.prependAnchor=null;
    if(s.focus&&!document.querySelector('.dialog')){const e=s.focus.id?document.getElementById(s.focus.id):[...(root?.querySelectorAll?.('[data-view-key]')||[])].find(el=>el.dataset.viewKey===s.focus.viewKey)?.querySelector('summary');if(e){e.focus({preventScroll:true});if(typeof e.setSelectionRange==='function'&&s.focus.start!=null)e.setSelectionRange(s.focus.start,s.focus.end,s.focus.direction)}}
  }
  function syncComposer(){
    const input=document.getElementById('copilot-message');if(!input||!compact)return;
    const send=document.querySelector('[data-copilot-action="send"]');if(send)send.disabled=!!(s.busy||s.unavailable||(changed()&&!replyingOriginal())||modelUnavailable()||active.has(s.thread?.latest_run?.status)||researchBusy()||!draft().trim());
    const css=window.getComputedStyle(input),min=parseFloat(css.minHeight)||64,max=parseFloat(css.maxHeight)||180;
    input.style.height='auto';input.style.height=Math.min(max,Math.max(min,input.scrollHeight))+'px';
  }
  const receiptWatching=()=>[s.thread?.latest_run,...(s.thread?.turns||[]).map(t=>t.run)].some(run=>(run?.actions||[]).some(action=>action.receipt?.outcome==='pending'));
  function actionReceipt(action){return ui.receipt?ui.receipt(action.receipt||{task_id:action.task_id,outcome:'unknown'}):`<p>已提交本地任务；请在任务模块核对执行回执。任务 ${esc(action.task_id)}</p>`}
  function evidenceView(observation,runId){
    const data=observation.data||{},detailKey='evidence:'+runId+':'+observation.id;
    const render=value=>ui.evidence?ui.evidence(value):`<p>${esc(value.title)} · ${esc(value.quote)}</p>`;
    if(observation.tool==='commerce_project_memory_search'){
      const hits=(data.hits||[]).map((hit,i)=>{
        const key=detailKey+':hit:'+i,citations=hit.citations||[],first=hit.layer==='L1'?citations[0]:null;
        return render({title:({L1:'导入原文',L2:'已确认事实',L3:'项目摘要'})[hit.layer]||'项目记忆',recordId:hit.id,quote:hit.content,verification:hit.status,version:first?.version??hit.revision,sha256:first?.sha256||hit.sha256,sourceId:first?.source_id,recordKey:first?.record_key,detailKey:key})+(hit.layer!=='L1'&&citations.length?`<details class="copilot-memory-citations" data-view-key="${esc(key+':citations')}"><summary>原文依据 · ${citations.length} 项</summary>${citations.map((c,j)=>render({title:'原文依据',quote:c.quote,sourceId:c.source_id,version:c.version,recordKey:c.record_key,sha256:c.sha256,verification:'imported_unverified',detailKey:key+':citation:'+j})).join('')}</details>`:'');
      }).join('');
      return `<section class="copilot-memory-evidence"><p>${data.scope_status==='unavailable'?'当前任务缺少明确的记忆范围，未检索项目记忆。':data.hits?.length?'本轮范围内读取的项目记忆':'当前任务范围没有匹配的有效项目记忆。'}${data.truncated?' 结果已限量，保留来源版本以便核对。':''}</p><small class="muted">历史读取快照；当前有效性以最新检索为准。</small>${hits}</section>`;
    }
    if(observation.tool==='commerce_workspace_get'){
      const labels={HOLD:'待补资料',FAIL:'检查不符',BLOCKED:'受阻',PASS:'检查通过'};
      const stages=(data.stages||[]).filter(stage=>stage.missing>0||stage.status!=='PASS');
      return `<section class="copilot-workspace-evidence">${render({title:'当前商品与阶段依据',quote:stages.length?`${stages.length} 个阶段仍需处理`:'本轮支持的阶段检查通过，不代表经营操作完成。',verification:'not_independently_verified',sha256:data.source_sha256,detailKey})}<small class="muted">历史读取快照；补齐资料后须重新读取并复验。</small>${stages.map(stage=>`<details class="copilot-card" data-view-key="${esc(detailKey+':stage:'+stage.id)}"><summary>${esc(stage.name||stage.id)} · ${esc(labels[stage.status]||'状态未知')} · ${esc(stage.missing)} 项</summary>${(stage.gaps||[]).map(gap=>`<section><p><strong>${esc(labels[gap.status]||'状态未知')}</strong> · ${esc(gap.reason)}</p><dl><div><dt>责任岗位</dt><dd>${esc(gap.owner)}</dd></div><div><dt>复验方法</dt><dd>${esc(gap.verify)}</dd></div></dl></section>`).join('')}${stage.gaps_truncated?'<p class="muted">展示已限量；其余缺项和完整内容请在商品工作区核对。</p>':!stage.gaps?.length?'<p class="muted">此历史记录仅保留缺项数量，需重新读取当前工作项。</p>':''}</details>`).join('')}</section>`;
    }
    const caption=observation.tool==='commerce_unit_economics'?'单件贡献测算':observation.tool==='commerce_restock_plan'?'补货测算':'本轮只读观察';
    return render({title:caption,quote:observation.tool+' · '+observation.id,verification:'not_independently_verified',sha256:data.source_sha256||data.result_sha256||data.record_sha256,detailKey})+`<details data-view-key="${esc(detailKey+':raw')}"><summary>查看观察数据</summary><pre>${esc(JSON.stringify(data,null,2))}</pre></details>`;
  }
  function renderRun(run,generated){if(!run)return '';
    if(researchJob(run)?.schema==='commerce-market-research-v1'){
      const research=researchView(run),result=run.result||{};
      return `<article class="copilot-message copilot-assistant" data-message-key="run:${esc(run.id)}"><div class="copilot-message-meta">${ui.icon('spark')}<strong>智能助手</strong>${runModel(run)}</div>${research||[result.answer,...(result.questions||[])].filter(Boolean).map(text=>`<p class="copilot-prose">${esc(text)}</p>`).join('')}</article>`;
    }
    const r=run.result||{},failure=typeof r.error==='string'?r.error:typeof run.error==='string'?run.error:run.error?.code,covered=generated?.covered,questions=(r.questions||[]).filter(q=>!covered?.questions.has(q)),proposals=(r.proposals||[]).filter(p=>!covered?.proposals.has(p.id)),actions=run.actions||[];
    return `<article class="copilot-message copilot-assistant" data-message-key="run:${esc(run.id)}"><div class="copilot-message-meta">${ui.icon('spark')}<strong>智能助手</strong>${runModel(run)}${compact&&run.status==='completed'?'':ui.badge(status[run.status]||run.status||'待处理',run.status==='failed'?'danger':'gray')}</div>${active.has(run.status)&&!researchJob(run)?`<p role="status">后台正在处理。本轮结果会保留，可稍后回来查看。</p>${button('请求停止','cancel',{'data-run':run.id,disabled:s.busy})}`:''}${r.answer&&!covered?.answer?`<div class="copilot-prose">${esc(r.answer)}</div>`:''}${failure||['failed','interrupted','unknown'].includes(run.status)?ui.alert(run.status==='unknown'?'结果尚未确认，请先核对原记录，不会自动重发。':failure?(errorText?errorText({code:failure,message:failure}):({agent_model_setup_required:'模型运行入口尚未配置，请在模型管理中完成配置。',agent_evidence_reference_required:'模型回复缺少来源引用，本次结果未被采纳。',agent_interrupted_no_automatic_resubmit:'回复已中断，未自动重发。核对记录后可重新编辑问题。'}[failure]||'这次回复未完成，请核对原记录。')):(run.status==='interrupted'?'回复已中断，未自动重新发送。':'回复未完成，未自动重新发送。'),'danger')+(['failed','interrupted'].includes(run.status)?button('重新编辑问题','edit-question',{'data-run':run.id}):''):''}${questions.length?(compact?`<div class="copilot-answer">${questions.map(q=>`<p class="copilot-question">${esc(q)}</p>`).join('')}</div>`:`<section class="copilot-card"><h3>需要补充</h3>${questions.map(q=>`<p>${esc(q)}</p>`).join('')}${button('填写补充回答','reply')}${button('补充测算数据','fields')}</section>`):''}${proposals.map(p=>`<section class="copilot-card"><h3>${esc(p.reason||p.operation)}</h3><p class="muted">${esc(p.operation)} · 逐项确认后提交本地任务</p>${actions.some(a=>a.proposal_id===p.id)?actionReceipt(actions.find(a=>a.proposal_id===p.id)):button('审阅建议','review',{'data-run':run.id,'data-proposal':p.id,disabled:s.busy||!!changed()})}</section>`).join('')}${generated?.html||''}${researchView(run)}${((r.observations||[]).length||generated?.captions?.length)?`<details class="copilot-evidence" data-view-key="${esc('run:'+run.id+':evidence')}"><summary>查看依据${r.observations?.length?' · '+r.observations.length+' 项':''}</summary>${(generated?.captions||[]).map(v=>`<p>${esc(v)}</p>`).join('')}${(r.observations||[]).map(o=>evidenceView(o,run.id)).join('')}</details>`:''}</article>`;
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
      if(type==='Button'){const action=p.action;if(action?.name!=='commerce.review_proposal')throw Error();const ctx=Object.fromEntries((action.context||[]).map(c=>[c.key,val(c.value)]));const run=(s.thread?.turns||[]).map(t=>t.run).find(r=>r?.id===ctx.run_id);if(!run?.result?.proposals?.some(p=>p.id===ctx.proposal_id))throw Error();const label=p.child?val(sf.nodes.get(p.child)?.Text?.text):'审阅建议';if(run.id===latest?.id)covered.proposals.add(ctx.proposal_id);if((run.actions||[]).some(a=>a.proposal_id===ctx.proposal_id))return `<div><strong>${esc(label)}</strong>${actionReceipt(run.actions.find(a=>a.proposal_id===ctx.proposal_id))}</div>`;return button(label||'审阅建议','review',{'data-run':ctx.run_id,'data-proposal':ctx.proposal_id,disabled:!!changed()})}
      if(type==='TextField'){const field=val(p.label);if(compact&&(latest?.result?.questions||[]).some(q=>q.slice(0,400)===field)){hasQuestion=true;for(const q of latest.result.questions)if(q.slice(0,400)===field)covered.questions.add(q);return `<p class="copilot-question">${esc(field)}</p>`;}hasInput=true;for(const q of latest?.result?.questions||[])if(q.slice(0,400)===field)covered.questions.add(q);return ui.field(field,ui.input({id:'copilot-a2ui-'+count,value:s.answers[field]??val(p.text),'data-copilot-answer':field,maxlength:2000}))}throw Error();};return sf.root?`<${compact?'div':'section'} class="${compact?'copilot-answer':'copilot-card'}">${render(sf.root)}${hasInput?button('将补充内容填入输入框','use-answers'):hasQuestion&&!compact?button('补充回答','reply',{icon:'chat'}):''}</${compact?'div':'section'}>`:''}).join('');return {html,covered,captions};
  }catch{return {html:ui.alert('生成的卡片暂不支持或结构无效，请使用文字回答和建议审阅。')}}}
  const units={currency:'币种（三位代码）',price:'售价',purchase_cost:'采购成本',domestic_shipping:'境内运费',packaging:'包装成本',fulfillment_cost:'履约费用',electronic_fee:'电子费用',commission_rate:'佣金比例（0–1）',payment_rate:'支付比例（0–1）',return_rate:'退货比例（0–1）',ad_rate:'广告比例（0–1）'};
  const stocks={available:'可用库存',sold_units:'窗口销量',window_days:'统计天数',lead_time_days:'补货提前天数',safety_days:'安全天数',pack_size:'整包数量'};
  function methodView(){const m=s.thread?.method;if(!m||typeof m!=='object')return '';const text=v=>typeof v==='string'?v:JSON.stringify(v);return `<details class="copilot-evidence" data-view-key="method"><summary>${esc(m.title||'本轮工作方法')}</summary>${m.guidance?`<p>${esc(text(m.guidance))}</p>`:''}${['steps','checks'].map(k=>Array.isArray(m[k])?`<ol>${m[k].slice(0,12).map(v=>`<li>${esc(text(v))}</li>`).join('')}</ol>`:'').join('')}</details>`}
  function form(){const calc=s.fields.calculator||s.thread?.context?.calculator||'unit_economics',fields=calc==='restock_plan'?stocks:units;return `<section class="copilot-card"><h3>补充已核对的测算数据</h3>${ui.field('测算类型',ui.select({id:'copilot-calculator',value:calc,options:[{value:'unit_economics',label:'单件贡献'},{value:'restock_plan',label:'补货计划'}]}))}<div class="copilot-fields">${Object.entries(fields).map(([k,label])=>ui.field(label,ui.input({id:'copilot-field-'+k,type:k==='currency'?'text':'number',min:k==='currency'?undefined:0,step:k==='currency'?undefined:'any',value:s.fields[k]??s.thread?.context?.input?.[k]??'','data-copilot-field':k}))).join('')}</div><p class="muted" data-ui-help>空项保留为缺项，不推测数值。保存范围后，需手动发送本轮问题。</p>${button('保存为本会话测算范围','save-fields',{disabled:s.busy})}${button('收起','fields')}</section>`}
  const sameObject=context=>{const c=current();return c.entity?context?.entity?.kind===c.entity.kind&&context.entity.id===c.entity.id&&context.platform===c.platform&&context.market===c.market&&context.store_id===c.store_id&&context.demo===c.demo:canonical(context)===canonical(c)};
  const objectName=()=>({order:'订单',product:'商品',case:'商品',intel:'情报'})[current().entity?.kind]||'对象';
  const currentRange=()=>current().entity?'本'+objectName():'本页';
  const currentRangeStatus=()=>current().entity?'当前'+objectName():current().module==='organization'?'尚未选择商品':'当前页面';
  const selectionKey=()=> 'commerce-copilot-selection:'+canonical(current());
  function historyRows(){const query=s.historyQuery.trim().toLocaleLowerCase(),threads=s.threads.filter(t=>(s.historyFilter!=='current'||sameObject(t.context))&&(!query||(t.title+' '+scope(t.context)).toLocaleLowerCase().includes(query)));return threads.length?threads.map(t=>`<button type="button" class="ui-button copilot-history-row" data-copilot-action="switch-thread" data-thread="${esc(t.id)}" ${s.busy?'disabled':''} aria-current="${t.id===s.thread?.id?'true':'false'}"><span><strong>${esc(t.title||'业务对话')}</strong><small>${esc(scope(t.context))}</small></span><span class="copilot-history-meta">${t.id===s.thread?.id?'<span>当前</span>':''}<time datetime="${new Date(t.updated*1000).toISOString()}">${new Date(t.updated*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</time>${s.drafts[t.id]?'<span>未发送</span>':''}</span></button>`).join(''):`<p class="copilot-history-empty" role="status">${query?'没有匹配的会话':s.historyFilter==='current'?(current().entity?'这个'+objectName()+'还没有已保存会话':'本页还没有已保存会话'):'暂无已保存会话'}</p>`}
  function historyView(){return `<section id="copilot-history" class="copilot-history" aria-labelledby="copilot-history-title"><header><h3 id="copilot-history-title">业务会话</h3>${button('返回对话','history-close',{'aria-label':'返回当前对话'})}</header>${ui.field('搜索会话',ui.input({id:'copilot-history-query',type:'search',value:s.historyQuery,placeholder:'搜索标题、商品或市场'}))}<div class="copilot-history-filters" role="group" aria-label="会话范围">${button(currentRange(),'history-current',{'aria-pressed':s.historyFilter==='current'})}${button('全部业务','history-all',{'aria-pressed':s.historyFilter==='all'})}${button('刷新','history-refresh',{disabled:s.historyLoading})}</div>${s.historyError?ui.alert(s.historyError,'danger'):''}<div id="copilot-history-list" class="copilot-history-list" aria-label="会话列表" aria-busy="${s.historyLoading}">${s.historyLoading?'<p role="status">正在读取会话…</p>':historyRows()}</div><p class="copilot-history-note">本平台最近 50 个业务会话</p></section>`}
  async function loadHistory(){const seq=++s.historyLoad;s.historyLoading=true;s.historyError='';update();try{const value=await api('commerce_copilot_list');if(seq===s.historyLoad)s.threads=value.threads||[]}catch(error){if(seq===s.historyLoad)s.historyError='会话读取失败，可刷新重试。'}finally{if(seq===s.historyLoad){s.historyLoading=false;update()}}}
  async function switchThread(id){if(s.busy)return;s.modelMenu=false;const seq=++s.load;s.busy=true;s.error='';update();try{const thread=await api('commerce_copilot_get',{thread_id:id});if(seq!==s.load)return;accept(thread);s.replyScope={thread:thread.id,hash:thread.context_sha256,page:canonical(current())};s.newThread=false;s.review=null;s.fields={};s.answers={};s.form=false;s.history=false;s.focus={id:'copilot-message'};s.scroll={bottom:true}}catch(error){s.historyError='无法打开这条会话，请刷新后重试。'}finally{s.busy=false;update()}}
  function compactView(thread,turns,generated) {
    const mismatch=changed(),contextual=mismatch?'':renderContext();
    return `<aside id="commerce-copilot" class="copilot-shell copilot-compact" role="region" aria-labelledby="copilot-title"><section class="copilot-panel">
      <header class="copilot-header"><div class="copilot-title"><h2 id="copilot-title">智能助手</h2></div><div class="copilot-header-actions">${button('会话','history',{'aria-label':'查看会话列表','aria-expanded':s.history,'aria-controls':'copilot-history',id:'copilot-history-toggle',icon:'chat'})}${button('新建','new',{disabled:s.busy,icon:'plus','aria-label':'新建对话'})}<details class="copilot-options" data-view-key="options"><summary aria-label="会话选项">${ui.icon('more')}</summary><div class="copilot-options-panel"><p class="copilot-context-label">${esc(scope(thread?.context||current()))}</p>${methodView()}</div></details></div></header>
      ${s.history?historyView():`${mismatch?`<div class="copilot-scope ${replyingOriginal()?'copilot-original-reply':''}">${replyingOriginal()?`<span class="copilot-original-range" title="${esc(scope(thread.context))}">回复原会话 · ${esc(scope(thread.context))}</span>`:ui.alert('当前会话仍使用原业务范围。','warning')}${button(current().entity?'使用当前'+objectName():'使用当前页面','context',{disabled:s.busy})}</div>`:''}<div id="copilot-log" class="copilot-log" tabindex="0" aria-label="会话记录">${thread?.has_more?button('更早记录','older',{'data-cursor':thread.next_cursor,disabled:s.busy}):''}${turns.map(t=>`<article class="copilot-message copilot-user" data-message-key="turn:${esc(t.id||t.run?.id||t.question)}"><div class="copilot-prose">${esc(t.question||t.message)}</div></article>${renderRun(t.run,t.run?.id===thread?.latest_run?.id?generated:null)}`).join('')}${s.form?form():''}${contextual||(!turns.length&&!mismatch?`<div class="copilot-welcome"><div class="copilot-suggestions">${researchPrompts().map(([label],index)=>button(label,'suggest',{'data-suggestion':index,title:'仅填入问题，发送后才开始处理'})).join('')}</div></div>`:'')}${s.error?ui.alert(s.error,'danger')+(s.errorCode?`<details class="copilot-evidence"><summary>错误详情</summary><code>${esc(s.errorCode)}</code></details>`:''):''}</div><footer class="copilot-composer"><label class="copilot-compose-label" for="copilot-message">问题或补充回答</label><textarea class="ui-control" id="copilot-message" data-copilot-draft-key="${esc(key())}" rows="2" maxlength="2000" placeholder="${(thread?.latest_run?.status==='awaiting_input'||thread?.research_job?.status==='awaiting_input')?'直接输入补充信息…':'输入问题或补充信息…'}">${esc(draft())}</textarea>${modelNotices()}<div class="copilot-compose-actions">${button(current().entity?.kind==='case'?'成本':'工作区','workspace',{disabled:s.busy||!onWorkspace,icon:current().entity?.kind==='case'?'chart':'box',class:'copilot-workspace-tool','aria-label':current().entity?.kind==='case'?'打开成本参数':'打开商品工作区',title:current().entity?.kind==='case'?'打开当前商品成本参数':'打开商品工作区'})}${modelView()}<span class="muted copilot-shortcut">⌘ ↵</span>${button(s.busy?'提交中':'','send',{disabled:s.busy||!!s.unavailable||(mismatch&&!replyingOriginal())||modelUnavailable()||active.has(thread?.latest_run?.status)||researchBusy()||!draft().trim(),icon:s.busy?'':'arrowUp',class:'copilot-send','aria-label':s.busy?'正在提交':'发送',title:active.has(thread?.latest_run?.status)?'等待本轮处理完成':'发送（⌘ / Ctrl + Enter）'},'primary')}</div></footer>`}</section></aside>`;
  }
  function view(){if(!s.open)return '<div id="commerce-copilot" hidden></div>';const thread=s.thread,turns=thread?.turns||[],generated=thread?.surfaces?surfaces(thread.surfaces):null;if(compact)return compactView(thread,turns,generated);return `<aside id="commerce-copilot" class="copilot-shell" role="${inline?'region':'dialog'}" aria-labelledby="copilot-title" aria-modal="${!inline&&window.innerWidth<1280}"><div class="copilot-backdrop" data-copilot-action="close" aria-hidden="true"></div><section class="copilot-panel"><header class="copilot-header"><div class="copilot-title"><div><h2 id="copilot-title">运营助手</h2></div></div>${button('关闭','close',{'aria-label':'关闭运营助手'})}</header><div class="copilot-threadbar">${ui.field('共享会话',ui.select({id:'copilot-thread',value:thread?.id||'',disabled:s.busy,options:[{value:'',label:'新会话'},...s.threads.map(t=>({value:t.id,label:t.title||'运营会话'}))]}))}${button('新建','new',{disabled:s.busy})}${button('刷新','refresh',{disabled:s.busy})}</div><div class="copilot-scope"><strong>本轮范围</strong><p>${esc(scope(thread?.context||current()))}</p>${changed()?`${ui.alert(replyingOriginal()?'补充将发送到原会话，业务操作仍需核对范围。':'页面范围已变化。当前会话仍保留原范围，请明确更新后再发送或审阅。')}${button('使用当前页面范围','context',{disabled:s.busy})}`:''}</div><div id="copilot-log" class="copilot-log" tabindex="0" aria-label="会话记录">${thread?.has_more?button('加载更早记录','older',{'data-cursor':thread.next_cursor,disabled:s.busy}):''}${!turns.length?`<div class="copilot-welcome"><p data-ui-help>一起核对资料、分析问题，把下一步整理成可审阅的建议。</p><div class="copilot-suggestions">${researchPrompts().map(([label],index)=>button(label,'suggest',{'data-suggestion':index,title:'填入问题后点击发送'})).join('')}</div><p class="muted" data-ui-help>点击建议只填入输入框。发送后才会请求模型。会话记录保存在本机服务，未发送文字保存在本机；存储不可用时会提示。</p></div>`:turns.map(t=>`<article class="copilot-message copilot-user" data-message-key="turn:${esc(t.id||t.run?.id||t.question)}"><div class="copilot-message-meta"><strong>你</strong></div><div class="copilot-prose">${esc(t.question||t.message)}</div></article>${renderRun(t.run,t.run?.id===thread?.latest_run?.id?generated:null)}`).join('')}${inline?renderContext():''}${methodView()}${s.form?form():''}${s.error?ui.alert(s.error,'danger')+(s.errorCode?`<details class="copilot-evidence"><summary>错误详情</summary><code>${esc(s.errorCode)}</code></details>`:''):''}</div><footer class="copilot-composer">${ui.field('问题或补充回答',`<textarea class="ui-control" id="copilot-message" data-copilot-draft-key="${esc(key())}" rows="3" maxlength="2000" placeholder="描述问题，或补充上一轮所需信息…">${esc(draft())}</textarea>`)}${modelNotices()}<div class="copilot-compose-actions">${button('补充数据','fields',{disabled:s.busy})}${modelView()}<span class="muted copilot-shortcut">⌘ / Ctrl + Enter</span>${button(s.busy?'正在提交…':'发送','send',{disabled:s.busy||!!s.unavailable||(changed()&&!replyingOriginal())||modelUnavailable()||active.has(thread?.latest_run?.status)||researchBusy()},'primary')}</div><small class="muted"></small></footer></section></aside>`}
  function accept(thread,older=false){if(compact&&sameObject(thread.context))try{localStorage.setItem(selectionKey(),thread.id)}catch{}const previous=s.thread;if(previous?.id!==thread.id){s.thread=thread;return}const turns=new Map();for(const t of older?[...(thread.turns||[]),...(previous.turns||[])]:[...(previous.turns||[]),...(thread.turns||[])])turns.set(t.id||t.run?.id||t.question,t);s.thread={...previous,...thread,turns:[...turns.values()]};if(!older&&Object.hasOwn(previous,'has_more')){s.thread.has_more=previous.has_more;s.thread.next_cursor=previous.next_cursor}}
  async function older(){if(s.busy||!s.thread?.has_more||!s.thread.next_cursor)return;const id=s.thread.id,cursor=s.thread.next_cursor;s.load++;s.busy=true;s.error='';update();try{const page=await api('commerce_copilot_get',{thread_id:id,before:cursor});if(s.thread?.id!==id)return;remember();const log=document.querySelector('#copilot-log');if(log)s.prependAnchor={top:log.scrollTop,height:log.scrollHeight};accept(page,true)}catch(e){s.error='读取更早记录失败：'+e.message}finally{s.busy=false;update()}}
  async function load(){const seq=++s.load;let models,defaultModelId,compatible=false,modelError='';try{const catalog=await originalApi('commerce_model_list',{});if(!Array.isArray(catalog.models))throw Error('invalid_model_catalog');defaultModelId=catalog.default_model_id??'project-default';if(typeof defaultModelId!=='string'||(catalog.default_model_id!=null&&!catalog.models.some(m=>m.id===defaultModelId)))throw Error('invalid_model_catalog');models=catalog.models}catch(error){compatible=(error.code||error.message)==='unknown_tool';modelError='模型选项暂不可用，请刷新或检查后台版本。'}if(seq!==s.load||disposed)return;if(models){s.models=models;s.defaultModelId=defaultModelId;s.modelCatalogReady=true}else if(compatible)s.modelCatalogReady=true;s.modelError=modelError;const list=await api('commerce_copilot_list');if(seq!==s.load)return;s.threads=list.threads||[];let thread=null;
    if(s.thread)thread=await api('commerce_copilot_get',{thread_id:s.thread.id});
    else if(!s.newThread&&s.threads.length){let selected;try{if(compact)selected=localStorage.getItem(selectionKey())}catch{}const matches=s.threads.filter(t=>sameObject(t.context)),candidate=compact?(current().entity?(matches.find(t=>t.id===selected)||matches[0]):null):s.threads[0];if(candidate)thread=await api('commerce_copilot_get',{thread_id:candidate.id})}
    if(seq===s.load){if(thread)accept(thread);update()}
  }
  function modelView(){
    const selected=selectedModelId(),models=[...(s.models||[{id:'project-default',label:'项目默认',selectable:true}])],disabled=s.busy||defaultModelPending()||active.has(s.thread?.latest_run?.status)||researchBusy();
    if(!models.some(m=>m.id===selected))models.push({id:selected,label:s.thread?.model_selection?.label||s.thread?.model_selection?.model||'当前模型',selectable:!modelUnavailable()});
    const model=models.find(m=>m.id===selected),label=model?.label||'项目默认',short=defaultModelPending()?'默认模型待刷新':selected==='project-default'?(model?.model||label):label,full=defaultModelPending()?'默认模型尚未读取':[label,model?.model].filter((v,i,a)=>v&&a.indexOf(v)===i).join(' · ');
    return `<details class="copilot-modelbar" id="copilot-model-picker" ${s.modelMenu?'open':''}><summary id="copilot-model-trigger" title="${esc(full)}" aria-label="选择对话模型：${esc(full)}" class="${modelUnavailable()?'is-unavailable':''}"><span>${esc(short)}</span>${ui.icon('chevronDown')}</summary><div class="copilot-model-menu" id="copilot-model-menu" role="group" aria-label="模型选项"><label for="copilot-model">对话模型</label><select id="copilot-model" class="ui-control" aria-label="对话模型" ${disabled?'disabled':''}>${models.map(m=>`<option value="${esc(m.id)}" ${m.id===selected?'selected':''} ${!m.selectable?'disabled':''}>${esc(m.label)}${m.model?' · '+esc(m.model):''}${!m.selectable?'（未就绪）':''}</option>`).join('')}</select><div class="copilot-model-menu-actions">${button('刷新列表','models-refresh',{id:'copilot-model-refresh','aria-label':'刷新模型列表',title:'刷新模型列表，保留未发送内容',disabled:s.busy})}${button('管理模型','models',{id:'copilot-model-manage','aria-label':'管理模型',disabled:s.busy})}</div></div></details>`;
  }
  function modelNotices(){const model=s.models?.find(m=>m.id===selectedModelId()),notice=defaultModelPending()?'默认模型尚未读取，请刷新模型列表。输入已保留。':modelUnavailable()?(model?.provider==='host_auto'?'暂无可用执行端，请选择固定模型或稍后刷新。输入已保留。':'当前模型不可用，请选择其它模型，或在管理中测试启用后刷新。输入已保留。'):s.modelError;return [s.draftSaveError,notice].filter(Boolean).map(text=>`<small class="copilot-model-status" role="status">${esc(text)}</small>`).join('')}
  async function selectModel(id){if(s.busy||active.has(s.thread?.latest_run?.status)||researchBusy())return;s.load++;s.busy=true;s.error='';update();try{await ensure();accept(await api('commerce_copilot_model',{thread_id:s.thread.id,model_id:id,expected_revision:s.thread.model_selection?.revision||'0'}));s.request=null}catch(e){s.error='模型未切换：'+e.message;await load().catch(()=>{})}finally{s.busy=false;update('copilot-model')}}
  async function ensure(){if(s.thread)return;const previousKey=key(),pending=draft();s.thread=await api('commerce_copilot_open',{context:current(),idempotency_key:s.openKey||(s.openKey=crypto.randomUUID())});if(await setDraft(key(),s.drafts[previousKey]??pending))setDraft(previousKey,'');s.threads=[s.thread,...s.threads.filter(t=>t.id!==s.thread.id)];s.newThread=false}
  async function send(){if(s.busy||s.unavailable||(changed()&&!replyingOriginal())||modelUnavailable()||active.has(s.thread?.latest_run?.status)||researchBusy())return;const submitted=draft(),message=submitted.trim(),initialModelId=s.thread?null:selectedModelId();if(!message){s.error='请填写问题或选择一个建议。';update();return}s.load++;s.busy=true;s.error='';s.errorCode='';update();try{await ensure();if(initialModelId&&s.thread.model_selection?.model_id&&initialModelId!==s.thread.model_selection.model_id)throw Error('copilot_model_changed');const draftFingerprint=canonical({thread:s.thread.id,message,hash:s.thread.context_sha256}),modelSha=s.request?.draftFingerprint===draftFingerprint?s.request.modelSha:s.thread.model_selection?.sha256,fingerprint=canonical({thread:s.thread.id,message,hash:s.thread.context_sha256,expected_model_sha256:modelSha});if(s.request?.fingerprint!==fingerprint)s.request={fingerprint,draftFingerprint,modelSha,key:crypto.randomUUID()};accept(await api('commerce_copilot_send',{thread_id:s.thread.id,message,context_sha256:s.thread.context_sha256,idempotency_key:s.request.key,...(s.request.modelSha?{expected_model_sha256:s.request.modelSha}:{})}));if(draft()===submitted)setDraft(key(),'');s.request=null;s.scroll={bottom:true};s.focus={id:'copilot-message'}}catch(e){if((e.code||e.message)==='copilot_model_changed'){s.request=null;s.error='模型配置已变化，请核对最新选项后再次发送。输入已保留。';try{await load()}catch{s.error='模型配置已变化，最新选项暂未读回。请刷新核对后再次发送。输入已保留。'}}else s.error='提交未完成：'+e.message+'。未自动重试，输入已保留。'}finally{s.busy=false;update()}}
  function review(runId,proposalId){if(changed())throw Error('页面范围已变化，请先更新会话范围');const run=(s.thread?.turns||[]).map(t=>t.run).find(r=>r?.id===runId),p=run?.result?.proposals?.find(p=>p.id===proposalId);if(!p||!run.result_sha256)throw Error('建议已不可用，请刷新');s.review={thread_id:s.thread.id,run_id:runId,proposal_id:proposalId,result_sha256:run.result_sha256,context_sha256:s.thread.context_sha256,page:canonical(current())};const proposed=p.input?.parameters||p.input||{},baseline=s.thread.context.input||{},fields=p.operation==='restock_plan'?stocks:units,rows=Object.keys(fields).filter(k=>Object.hasOwn(proposed,k)&&canonical(baseline[k])!==canonical(proposed[k])).map(k=>({key:k,label:fields[k],before:baseline[k],after:proposed[k]})),diff=ui.fieldDiff&&['unit_economics','restock_plan'].includes(p.operation)?ui.fieldDiff({rows,beforeLabel:'当前范围参数',afterLabel:'建议任务参数'}):'';modal('审阅本地建议',`<p>${esc(p.reason)}</p><p><strong>对象与范围：</strong>${esc(scope(s.thread.context))}</p><p><strong>操作：</strong>${esc(({report:'生成本地简报',unit_economics:'计算单件贡献',restock_plan:'计算补货草稿',intel_review:'整理来源证据',organization_handoff:'创建岗位补齐待办',exposure_review:'创建经营关联复核'})[p.operation]||p.operation)}</p>${diff}<p class="muted">仅提交这一项本地任务；队列接收不代表执行完成。</p><details><summary>查看完整参数与依据</summary><pre class="copilot-review">${esc(JSON.stringify({context:s.thread.context,operation:p.operation,input:p.input},null,2))}</pre></details>`,button('确认参数并提交','apply'))}
  async function act(action,target){
    if(action==='models'){if(onModels){onModels();return}const r=await api('commerce_model_open_setup',{});toast?.(r.opened?'已打开本机模型管理，返回后点击“刷新模型列表”读取配置。':'浏览器打开尚未确认，请重试。');return}
    if(action==='history'){s.history=true;s.focus={id:'copilot-history-query'};update('copilot-history-query');await loadHistory();return}
    if(action==='history-close'){s.history=false;s.historyLoad++;s.historyLoading=false;s.focus={id:'copilot-history-toggle'};update('copilot-history-toggle');return}
    if(action==='history-current'||action==='history-all'){s.historyFilter=action==='history-current'?'current':'all';s.focus=null;update();return}
    if(action==='history-refresh'){await loadHistory();return}
    if(action==='switch-thread'){await switchThread(target.dataset.thread);return}
    if(action==='new'&&compact){if(s.busy)return;s.load++;s.busy=true;s.error='';update();try{const context=current(),fingerprint=canonical(context),previousKey=key(),migrate=!s.thread,pending=migrate?draft():'';if(s.newRequest?.fingerprint!==fingerprint)s.newRequest={fingerprint,key:crypto.randomUUID()};const thread=await api('commerce_copilot_open',{context,idempotency_key:s.newRequest.key});const latest=migrate?(s.drafts[previousKey]??pending):'',version=draftVersions.get(previousKey)||0;accept(thread);if(latest){if(await setDraft(thread.id,latest)&&s.drafts[previousKey]===latest&&(draftVersions.get(previousKey)||0)===version)setDraft(previousKey,'')}s.newRequest=null;s.threads=[thread,...s.threads.filter(t=>t.id!==thread.id)];s.newThread=false;s.history=false;s.review=null;s.fields={};s.answers={};s.form=false;s.focus={id:'copilot-message'};s.scroll={bottom:true}}catch(error){s.error='新对话未确认创建，请重试查询；已有输入仍保留。';if(s.history)s.historyError=s.error}finally{s.busy=false;update()}return}
    if(action.startsWith('research-')){
      const job=[s.thread?.research_job,...(s.thread?.turns||[]).map(t=>researchJob(t.run))].find(j=>j?.task_id===target.dataset.task);
      if(!job)throw Error('研究任务已变化，请刷新当前会话。');
      if(action==='research-open'){onResearch?.(job.task_id);return}
      if(action==='research-candidate'){const candidate=(job.candidates||[]).find(c=>c.case_id===target.dataset.case);if(candidate)onOpenCandidate?.(candidate.case_id,job.task_id);return}
      if(s.busy)return;s.load++;s.busy=true;s.error='';update();
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
    if(action==='edit-question'){const turn=(s.thread?.turns||[]).find(t=>t.run?.id===target.dataset.run);if(!turn||!['failed','interrupted'].includes(turn.run.status))return;if(!draft().trim())setDraft(key(),String(turn.question||turn.message||''));else toast?.('输入框已有草稿，已保留。');update('copilot-message');return}
    if(action==='workspace'){onWorkspace?.();return}if(action==='close'){close();return}if(action==='send'){await send();return}if(action==='older'){await older();return}if(action==='use-answers'){setDraft(key(),Object.entries(s.answers).filter(([,v])=>v.trim()).map(([k,v])=>k+'：'+v).join('\n'));s.focus={id:'copilot-message'};update();return}if(action==='reply'){s.focus={id:'copilot-message'};update();return}if(action==='suggest'){setDraft(key(),researchPrompts()[Number(target.dataset.suggestion)]?.[1]||'根据当前范围，建议下一步怎么做');s.focus={id:'copilot-message'};update();return}if(action==='fields'){s.form=!s.form;update();return}if(action==='review'){review(target.dataset.run,target.dataset.proposal);return}if(s.busy)return;s.load++;s.busy=true;s.error='';update();try{
    if(action==='refresh'||action==='models-refresh')await load();
    if(action==='new'){s.load++;s.thread=null;s.newThread=true;s.openKey=null;s.request=null;s.review=null;s.fields={};s.answers={};s.form=false;s.focus={id:'copilot-message'};s.scroll={bottom:true}}
    if(action==='context'){if(!s.thread)await ensure();accept(await api('commerce_copilot_context',{thread_id:s.thread.id,context:current(),expected_context_sha256:s.thread.context_sha256}));s.review=null}
    if(action==='cancel'&&s.thread){accept(await api('commerce_copilot_cancel',{thread_id:s.thread.id,run_id:target.dataset.run}))}
    if(action==='save-fields'){await ensure();const calc=s.fields.calculator||s.thread.context.calculator||'unit_economics',fields=calc==='restock_plan'?stocks:units,input={};for(const k of Object.keys(fields)){const v=s.fields[k]??s.thread.context.input?.[k];if(v!==undefined&&v!==''){if(k==='currency'){if(!/^[A-Z]{3}$/.test(v))throw Error('币种请填写三位大写代码');input[k]=v}else{const n=Number(v);if(!Number.isFinite(n)||n<0)throw Error('请核对 '+fields[k]);input[k]=n}}}accept(await api('commerce_copilot_context',{thread_id:s.thread.id,context:{...s.thread.context,calculator:calc,input},expected_context_sha256:s.thread.context_sha256}));s.form=false;s.scopeOverride={thread:s.thread.id,page:canonical(current()),context:clone(s.thread.context)};s.review=null;toast?.('测算数据已保存，请明确发送问题')}
    if(action==='apply'){const r=s.review;if(!r||r.thread_id!==s.thread?.id||r.context_sha256!==s.thread.context_sha256||r.page!==canonical(current())||changed())throw Error('范围已变化，请关闭并重新审阅');const {page,...args}=r;await api('commerce_copilot_apply',args);s.review=null;closeModal();await load();toast?.('已提交本地任务，请查看任务回执')}
  }finally{s.busy=false;update(action==='models-refresh'?'copilot-model-refresh':undefined)}}
  // Explicit calculator additions belong to the thread; compare page context separately.
  function open(context,options={}){if(disposed)return;if(context&&canonical(context)!==canonical(current())){s.error='打开时提供的范围与页面不同，请核对当前页面。'}s.opener=document.activeElement;s.open=true;s.focus=options.focus===false?null:{id:'copilot-message'};s.scroll||={top:0,bottom:!!s.thread?.turns?.length};if(repaint)repaint();else update();load().catch(e=>{s.error='读取会话失败：'+e.message;update()})}
  // Async navigation may select a different thread before this editor commits its composition.
  function finishComposition(element){const owner=element?.dataset?.copilotDraftKey||s.compositionKey||key();s.composing=false;s.compositionKey=null;s.compositionElement=null;if(typeof element?.value==='string')setDraft(owner,element.value)}
  function close(){if(s.composing)finishComposition(s.compositionElement);s.pendingPaint=false;s.pendingFocus=null;s.open=false;s.modelMenu=false;s.load++;s.review=null;s.focus=null;update();layout();if(!inline){const opener=s.opener?.isConnected?s.opener:s.opener?.id?document.getElementById(s.opener.id):null;const target=opener||[...document.querySelectorAll('[data-action="copilot-open"]')].find(el=>el.getClientRects().length);target?.focus?.({preventScroll:true})}}
  function contextChanged(){if(disposed||!s.open)return;const page=canonical(current());if(s.page!==page){s.modelMenu=false;s.page=page;if(compact&&!s.thread?.turns?.length)s.startAtTop=true}s.review=null;update();if(compact&&!s.thread&&!s.newThread&&!s.busy&&!draft().trim())load().catch(error=>{s.error='读取会话失败：'+error.message;update()})}
  listen(document,'input',e=>{if(e.target.id==='copilot-history-query'){s.historyQuery=e.target.value;const list=document.getElementById('copilot-history-list');if(list&&!s.historyLoading)list.innerHTML=historyRows()}if(e.target.id==='copilot-message'){const owner=s.compositionKey||(e.target.isConnected===false?e.target.dataset?.copilotDraftKey:null)||key();if(e.target.dataset)e.target.dataset.copilotDraftKey=owner;setDraft(owner,e.target.value);syncComposer();}if(e.target.dataset?.copilotAnswer)s.answers[e.target.dataset.copilotAnswer]=e.target.value;if(e.target.dataset?.copilotField)s.fields[e.target.dataset.copilotField]=e.target.value});
  listen(document,'focusin',e=>{if(e.target.closest?.('#commerce-copilot')&&e.target.id)remember()});
  listen(document,'select',e=>{if(e.target.closest?.('#commerce-copilot'))remember()},true);
  listen(document,'keyup',e=>{if(e.target.closest?.('#commerce-copilot'))remember()});
  listen(document,'change',e=>{if(e.target.id==='copilot-model'){selectModel(e.target.value);return}if(e.target.id==='copilot-calculator'){s.fields.calculator=e.target.value;update()}if(e.target.id==='copilot-thread'&&!s.busy){if(!e.target.value){act('new',e.target);return}const id=e.target.value,seq=++s.load;s.busy=true;api('commerce_copilot_get',{thread_id:id}).then(t=>{if(seq===s.load){accept(t);s.newThread=false;s.review=null;s.fields={};s.answers={};s.form=false;s.focus={id:'copilot-thread'};s.scroll={bottom:true}}}).catch(e=>{s.error=e.message}).finally(()=>{s.busy=false;update()})}});
  listen(document,'click',e=>{const picker=document.querySelector('#copilot-model-picker[open]');if(picker&&!picker.contains(e.target)){s.modelMenu=false;picker.removeAttribute('open')}const options=document.querySelector('.copilot-options[open]');if(options&&!options.contains(e.target))options.removeAttribute('open');const t=e.target.closest?.('[data-copilot-action]');if(!t)return;e.preventDefault();t.closest('.copilot-options')?.removeAttribute('open');if(t.dataset.copilotAction==='models'){s.modelMenu=false;t.closest('#copilot-model-picker')?.removeAttribute('open')}act(t.dataset.copilotAction,t).catch(error=>{s.error='操作未完成：'+error.message;toast?.(s.error);update()})});
  listen(document,'toggle',e=>{if(e.target.id==='copilot-model-picker')s.modelMenu=e.target.open},true);
  listen(document,'compositionstart',e=>{if(e.target.id==='copilot-message'){s.composing=true;s.compositionKey=key();if(e.target.dataset)e.target.dataset.copilotDraftKey=s.compositionKey;s.compositionElement=e.target}});
  listen(document,'compositionend',e=>{if(e.target.id!=='copilot-message')return;finishComposition(e.target);if(s.pendingPaint){s.pendingPaint=false;const focus=s.pendingFocus;s.pendingFocus=null;update(focus)}});
  listen(document,'keydown',e=>{if(!s.open||!isActive()||document.querySelector('.dialog'))return;const picker=document.querySelector('#copilot-model-picker[open]');if(picker&&e.key==='Escape'){e.preventDefault();s.modelMenu=false;picker.removeAttribute('open');picker.querySelector('summary')?.focus();return}if(s.history&&e.key==='Escape'){e.preventDefault();s.history=false;s.historyLoad++;s.historyLoading=false;s.focus={id:'copilot-history-toggle'};update('copilot-history-toggle');return}const options=document.querySelector('.copilot-options[open]');if(compact&&options&&e.key==='Escape'){e.preventDefault();options.removeAttribute('open');options.querySelector('summary')?.focus();return}if(e.key==='Escape'&&!inline){e.preventDefault();close();return}if(e.target.id==='copilot-message'&&e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.isComposing&&!s.composing&&e.keyCode!==229){e.preventDefault();send();return}if(e.key==='Tab'&&!inline&&window.innerWidth<1280){const nodes=[...document.querySelectorAll('#commerce-copilot button:not(:disabled),#commerce-copilot input:not(:disabled),#commerce-copilot select:not(:disabled),#commerce-copilot textarea,#commerce-copilot [tabindex="0"]')].filter(n=>n.getClientRects().length),first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&(document.activeElement===first||!document.activeElement.closest?.('#commerce-copilot'))){e.preventDefault();last?.focus()}else if(!e.shiftKey&&(document.activeElement===last||!document.activeElement.closest?.('#commerce-copilot'))){e.preventDefault();first?.focus()}}});
  listen(window,'resize',()=>{if(s.open)layout()});
  let pollRequest=null,pollError='';
  async function pollThread(){
    if(disposed||!s.open||!isActive()||s.busy||document.querySelector('.dialog')||!s.thread||!(active.has(s.thread.latest_run?.status)||researchWatching()||receiptWatching()))return;
    const id=s.thread.id,seq=s.load,page=canonical(current());
    if(pollRequest?.id===id&&pollRequest.seq===seq&&pollRequest.page===page)return;
    const request={id,seq,page};pollRequest=request;
    const currentRequest=()=>!disposed&&s.open&&isActive()&&!s.busy&&pollRequest===request&&s.load===seq&&s.thread?.id===id&&canonical(current())===page&&!document.querySelector('.dialog');
    try{const thread=await api('commerce_copilot_get',{thread_id:id});if(!currentRequest())return;accept(thread);if(pollError&&s.error===pollError)s.error='';pollError='';update()}
    catch(error){if(currentRequest()){pollError='状态读取未完成：'+error.message;s.error=pollError;update()}}
    finally{if(pollRequest===request)pollRequest=null}
  }
  const polling=setInterval(pollThread,2000);
  function dispose(){if(disposed)return;disposed=true;s.open=false;s.load++;s.historyLoad++;clearInterval(polling);draftStorage.dispose();listeners.splice(0).forEach(remove=>remove())}
  return {view,open,close,afterPaint,contextChanged,dispose,openThread:switchThread};
};

/* Read-side research identity. It never replaces the current item's write base. */
((target)=>{
  const valid=value=>typeof value==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(value);
  function task(value){if(value==null||value==='')return '';if(!valid(value))throw Error('workspace_research_context_invalid');return value}
  function resource(caseId,taskId=''){if(!valid(caseId))throw Error('workspace_research_context_invalid');const value=new URL('dsh-resource://commerce/product/'+caseId);if(task(taskId))value.searchParams.set('research_task_id',taskId);return value.href}
  function parseResource(address){try{const value=new URL(address);if(value.protocol!=='dsh-resource:'||value.host!=='commerce'||value.username||value.password||value.hash)return null;const match=value.pathname.match(/^\/product\/([a-zA-Z0-9_-]{1,160})$/);if(!match||[...value.searchParams.keys()].some(key=>key!=='research_task_id')||value.searchParams.getAll('research_task_id').length>1)return null;return {caseId:match[1],researchTaskId:task(value.searchParams.get('research_task_id'))}}catch{return null}}
  function artifact(data,requested=''){
    const selected=data.research_context;
    if(requested&&(!selected||selected.task_id!==task(requested)))throw Error('workspace_research_context_unavailable');
    if(selected){if(selected.read_only!==true||!selected.artifact||selected.artifact.id!==selected.artifact_id)throw Error('workspace_research_context_unavailable');return selected.artifact}
    return data.artifacts.research;
  }
  function merge(data,readback,requested){
    if(data.case.id!==readback.case.id)throw Error('workspace_research_context_invalid');
    artifact(readback,requested);
    return {...data,research_context:readback.research_context,research_contexts:readback.research_contexts};
  }
  const revision=value=>{const number=typeof value==='number'?value:typeof value==='string'&&/^[1-9]\d*$/.test(value)?Number(value):NaN;return Number.isSafeInteger(number)&&number>=1?number:NaN};
  const newer=(current,readback)=>current&&revision(current.revision)>revision(readback.revision)?current:readback;
  const mergeJob=(jobs,readback)=>jobs.map(job=>job.task_id===readback.task_id?newer(job,readback):job);
  const mergeJobs=(jobs,readback)=>{const known=new Map(jobs.map(job=>[job.task_id,job]));return readback.map(job=>newer(known.get(job.task_id),job))};
  target.CommerceResearchContext=Object.freeze({task,artifact,merge,mergeJob,mergeJobs,resource,parseResource});
})(typeof window==='object'?window:globalThis);

/* Shared product/supply browsing. All media is read through the scoped backend. */
window.CommerceCatalog=({api,repaint,onSelect,onCreative})=>{
  const ui=window.CommerceUI,e=ui.escape,id=crypto.randomUUID();
  const s={items:[],detail:null,query:'',kind:'all',page:0,importKind:'none',busy:false,error:'',epoch:0,image:0,store:null,storeError:'',storeNote:''};
  const previews=new Map(),pending=new Set(),failed=new Set();let workers=0;
  const quoteStatus={READY_FOR_SELECTION:'资料齐备 · 待选择',HOLD:'资料待补充',STALE:'资料已变化',EXPIRED:'已过期',CURRENCY_MISMATCH:'币种不一致',source_supplied:'来源提供 · 待核对'};
  const button=(label,action,attrs={})=>ui.button({label,attrs:{'data-catalog-action':action,...attrs}});
  const money=d=>d.price==null?(d.price_text||'价格待补充'):`${d.currency||'币种待核对'} ${d.price}`;
  const imageKey=(d,i)=>d.id+':'+d.source_sha256+':'+(d.images[i]?.id||i);
  function picture(d,i=0){const key=imageKey(d,i),url=previews.get(key);return `<div class="catalog-picture" data-catalog-image="${e(key)}" data-case="${e(d.id)}" data-image-index="${i}">${url?`<img src="${url}" alt="${e(d.name)} · 商品图片 ${i+1}" loading="lazy">`:`<span class="muted">${!d.images.length?'暂无商品图片':failed.has(key)?'图片暂不可用': '正在读取商品图片…'}</span>${failed.has(key)?button('重试图片','retry-image',{'data-key':key}):''}`}</div>`}
  async function enter(){const epoch=++s.epoch;s.detail=null;s.busy=true;s.error='';repaint();try{const r=await api('commerce_catalog_list',{query:s.query,kind:s.kind});if(epoch!==s.epoch)return;s.items=r.items;s.page=0;await readStore()}catch{if(epoch===s.epoch)s.error='商品资料暂不可读，请重试。'}finally{if(epoch===s.epoch){s.busy=false;repaint()}}}
  let storeTimer=null;
  async function readStore(){try{s.store=await api('commerce_catalog_store_status',{});s.storeError='';if(s.store.refresh?.status==='running')pollStore()}catch{s.storeError='店铺读取状态暂不可用，请重试。'}}
  function pollStore(){clearTimeout(storeTimer);storeTimer=setTimeout(async()=>{if(!document.querySelector(`[data-catalog-instance="${id}"]`))return;await readStore();if(s.storeError){repaint();return}const job=s.store?.refresh;if(job?.status==='running'){repaint();return}if(job?.status==='failed'){s.storeError='商品资料读取未完成，原资料和草稿保留。请核对连接与库存后重试。';repaint();return}s.storeNote=job?.status==='partial'?'部分商品资料已读取，描述或属性仍有缺项。':'商品资料已接入，仍需核实产品信息和素材权利。';const cid=s.detail?.id;if(cid)await open(cid);else await enter()},1200)}
  async function refreshStore(current=false){s.storeError='';s.storeNote='';await readStore();if(s.storeError)return repaint();try{await api('commerce_catalog_store_refresh',{expected_stock_sha256:s.store.stock_sha256,...(current?{case_id:s.detail.id}:{})});await readStore();pollStore()}catch{s.storeError='未启动读取。请先在连接设置同步最新库存；原商品资料和编辑保持。'}repaint()}
  function storeControls(){const store=s.store,job=store?.refresh;return `<div class="catalog-store-sync">${store?.configured?button(s.detail?'读取当前商品完整资料':'读取店铺商品资料',s.detail?'store-one':'store-all',{disabled:s.busy||job?.status==='running'||!store.stock_fresh||!!s.detail?.synthetic||s.detail?.kind==='candidate'}):''}${button('刷新读取状态','store-status',{disabled:s.busy})}${job?.status==='running'?'<span role="status">正在只读获取商品资料…</span>':''}${store?.configured&&!store.stock_fresh?'<span class="muted">请先同步最新店铺库存，再读取图文资料。</span>':''}${s.storeError?ui.alert(s.storeError,'danger'):''}${s.storeNote?`<p role="status">${e(s.storeNote)}</p>`:''}</div>`}
  async function open(caseId){const epoch=++s.epoch;s.busy=true;s.error='';repaint();try{const d=await api('commerce_catalog_get',{case_id:caseId});if(epoch!==s.epoch)return;s.detail=d;s.openerCase=caseId;s.image=0}catch{if(epoch===s.epoch)s.error='这条商品资料已变化或不属于当前连接，请刷新列表。'}finally{if(epoch===s.epoch){s.busy=false;repaint();document.querySelector(`[data-catalog-instance="${id}"] h2`)?.focus()}}}
  function schedule(){queueMicrotask(()=>{const host=document.querySelector(`[data-catalog-instance="${id}"]`);if(!host)return;for(const node of host.querySelectorAll('[data-catalog-image]')){if(workers>=2)break;const key=node.dataset.catalogImage;if(previews.has(key)||pending.has(key)||failed.has(key))continue;const d=s.detail?.id===node.dataset.case?s.detail:s.items.find(x=>x.id===node.dataset.case),index=Number(node.dataset.imageIndex);if(!d?.images[index])continue;pending.add(key);workers++;api('commerce_catalog_image',{case_id:d.id,expected_source_sha256:d.source_sha256,index,image_id:d.images[index].id}).then(r=>{if(previews.size>=40)previews.delete(previews.keys().next().value);previews.set(key,`data:${r.mime};base64,${r.content_base64}`)}).catch(()=>failed.add(key)).finally(()=>{pending.delete(key);workers--;const current=document.querySelector(`[data-catalog-instance="${id}"] [data-catalog-image="${CSS.escape(key)}"]`);if(current){const url=previews.get(key);current.innerHTML=url?`<img src="${url}" alt="商品来源图片" loading="lazy">`:`<span class="muted">图片暂不可用</span>${button('重试图片','retry-image',{'data-key':key})}`}schedule()})}})}
  function detail(){const d=s.detail;return `<header class="catalog-detail-header">${button('返回商品列表','back')}<h2 tabindex="-1">${e(d.name)}</h2><div>${d.synthetic?ui.badge('合成验收资料','gray'):ui.badge(d.kind==='candidate'?'调研候选':'已有商品','blue')}${ui.badge('资料待核实','gray')}</div></header><div class="catalog-detail-grid"><div>${picture(d,s.image)}${d.images[s.image]?.source_current===false?ui.badge('历史商品资料图片 · 待核对','warning'):''}<div class="catalog-thumbnails">${d.images.map((_,i)=>button('图片 '+(i+1),'image',{'data-index':i,'aria-pressed':s.image===i})).join('')}</div></div><div><p class="catalog-price">${e(money(d))}</p><dl class="catalog-meta"><dt>平台 / 市场</dt><dd>${e(d.case.scope.platform||'待补充')} / ${e(d.case.scope.market||'待补充')}</dd><dt>SKU</dt><dd>${e(d.case.scope.sku||'未提供')}</dd><dt>采集时间</dt><dd>${e(d.captured_at?new Date(d.captured_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'未记录')}</dd></dl>${d.source_url?`<a href="${e(d.source_url)}" target="_blank" rel="noopener noreferrer">查看原始来源</a>`:''}<div class="form-actions">${button('进入商品工作区','select')}${d.images.length?ui.field('带入创意项目的图片用途',ui.select({'data-catalog-import':id,value:s.importKind,options:[{value:'none',label:'只建立项目'},{value:'product_image',label:'当前图作为产品资料图片'},{value:'reference_image',label:'当前图作为设计参考'}]})):''}${button('建立图片与视频创意项目','creative',{'class':'primary',disabled:s.busy||!d.source_intact})}</div>${d.projects.length?`<h3>关联创意项目</h3>${d.projects.map(p=>button((p.name||'创意项目')+(p.source_current?'':' · 资料待更新'),'project',{'data-project':p.id})).join('')}`:''}</div></div>${ui.card({title:'商品资料与规格',content:ui.table(['项目','采集原文','中文资料','资料状态'],d.fields.map(f=>`<tr><td>${e(({title:'商品名称',description:'描述与卖点',attributes:'材质与规格',variants:'颜色与型号',price:'价格',images:'图片来源',dimensions:'尺寸',weight:'重量',category_id:'平台类目编号',type_id:'平台类型编号',platform_status:'平台状态',findings:'研究发现',limitations:'资料限制'})[f.key]||f.key)}</td><td class="catalog-text">${e(f.original||'未提供')}</td><td class="catalog-text">${e(f.zh||'未提供')}</td><td>${ui.badge(f.kind==='platform_unverified'?'平台返回 · 待核实':f.kind==='inference'?'推断':f.reviewed?'已校对 · 待核实':'待校对','gray')}</td></tr>`))})}${ui.card({title:'货源与报价',content:d.suppliers.length?ui.table(['供应方','原币采购价','起订量','交期','来源 / 状态'],d.suppliers.map(q=>`<tr><td>${e(q.supplier||'未提供')}</td><td>${e(q.purchase_cost==null?'未提供':(q.currency||'币种待核对')+' '+q.purchase_cost)}</td><td>${e(q.moq??'未提供')}</td><td>${e(q.lead_time_days==null?'未提供':q.lead_time_days+'天')}</td><td><span class="catalog-text">${e(q.source_ref||'未提供')}</span><small>${e(quoteStatus[q.status]||'资料待核对')}</small></td></tr>`)):ui.empty('尚无货源报价，可在商品工作区补充。')})}`}
  function view(){schedule();const rows=s.items.slice(s.page*20,s.page*20+20);return `<section class="catalog-browser" data-catalog-instance="${id}" aria-label="商品与货源浏览" aria-busy="${s.busy}">${s.error?ui.alert(s.error,'danger'):''}${storeControls()}${s.detail?detail():`<header class="catalog-toolbar"><h2>商品与货源</h2><form data-catalog-search><div>${ui.input({id:'catalog-query-'+id,value:s.query,type:'search',placeholder:'搜索商品、规格或供应方','aria-label':'搜索商品与货源'})}${ui.select({id:'catalog-kind-'+id,value:s.kind,'aria-label':'商品来源筛选',options:[{value:'all',label:'全部商品'},{value:'candidate',label:'调研候选'},{value:'inventory',label:'已有商品'},{value:'supply',label:'已有货源'}]})}${button('搜索','search',{disabled:s.busy})}</div></form></header>${s.busy?'<p role="status">正在读取商品资料…</p>':''}<div class="catalog-grid">${rows.map(d=>`<article class="catalog-product">${button(d.name,'open',{'data-case':d.id,class:'catalog-product-title'})}${picture(d)}<p class="catalog-price">${e(money(d))}</p><div class="catalog-card-meta">${ui.badge(d.synthetic?'合成资料':d.kind==='candidate'?'调研候选':'已有商品','gray')}<span>${e(d.supplier_count?d.supplier_count+'条货源':'货源待补充')}</span></div></article>`).join('')}</div>${!s.busy&&!rows.length?ui.empty('当前范围暂无匹配商品。已采集并保存到商品工作项的资料会显示在这里。'):''}<div class="catalog-pagination">${button('上一页','prev',{disabled:s.page===0})}<span>${s.items.length?`${s.page+1} / ${Math.ceil(s.items.length/20)}`:'0'} · ${s.items.length}件</span>${button('下一页','next',{disabled:(s.page+1)*20>=s.items.length})}</div>`}</section>`}
  document.addEventListener('submit',ev=>{if(ev.target.closest(`[data-catalog-instance="${id}"]`)&&ev.target.matches('[data-catalog-search]')){ev.preventDefault();enter()}});
  document.addEventListener('input',ev=>{if(ev.target.id==='catalog-query-'+id)s.query=ev.target.value});
  document.addEventListener('change',ev=>{if(ev.target.dataset.catalogImport===id)s.importKind=ev.target.value;if(ev.target.id==='catalog-kind-'+id){s.kind=ev.target.value;enter()}});
  document.addEventListener('click',async ev=>{const b=ev.target.closest('[data-catalog-action]');if(!b||!b.closest(`[data-catalog-instance="${id}"]`))return;ev.preventDefault();if(b.disabled)return;const a=b.dataset.catalogAction;try{if(a==='store-all'||a==='store-one')return refreshStore(a==='store-one');if(a==='store-status'){await readStore();repaint();return}if(a==='search')return enter();if(a==='open')return open(b.dataset.case);if(a==='back'){s.detail=null;repaint();document.querySelector(`[data-catalog-instance="${id}"] [data-catalog-action=open][data-case="${s.openerCase}"]`)?.focus();return}if(a==='retry-image'){failed.delete(b.dataset.key);repaint();return}if(a==='prev'||a==='next'){s.page+=a==='next'?1:-1;repaint();return}if(a==='image'){s.image=Number(b.dataset.index);repaint();return}if(a==='select')return onSelect?.(s.detail.id);if(a==='project')return onCreative?.({id:b.dataset.project});if(a==='creative'){s.busy=true;repaint();const d=s.detail;if(!d.creativeKey)d.creativeKey=crypto.randomUUID();const p=await api('commerce_catalog_creative',{case_id:d.id,expected_source_sha256:d.source_sha256,idempotency_key:d.creativeKey});if(s.importKind!=='none'&&d.images.length)await api('commerce_catalog_image_import',{case_id:d.id,project_id:p.id,expected_source_sha256:d.source_sha256,index:s.image,image_id:d.images[s.image].id,kind:s.importKind});if(s.detail?.id===d.id)onCreative?.(p)}}catch{s.error='操作未完成，请核对当前商品资料后重试。'}finally{s.busy=false;repaint()}});
  return {view,enter,open};
};

/* Human-reviewed content versions; generation has a separate exact-plan approval. */
window.CommerceMediaVideoReview=({api,repaint,getProject,onPlan})=>{
 const ui=window.CommerceUI,e=ui.escape;
 const s={plan:null,epoch:0,content:null,confirmed:false,editing:false,busy:false,stale:false,error:'',keys:new Map()};
 const inputId=key=>'video-review-'+s.plan.id+'-'+key.replaceAll('.','-');
 const btn=(label,action,attrs={},primary=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{id:inputId(action),'data-video-review-action':action,disabled:s.busy,...attrs}});
 const field=(key,label,value,max=1200)=>ui.field(label,`<textarea class="ui-control" id="${e(inputId(key))}" data-video-review-field="${e(key)}" rows="3" maxlength="${max}">${e(value)}</textarea>`);
 function initial(plan){const old=plan.video_review?.content,spec=plan.source_request.spec,script=spec.script;return old?{...old,shots:old.shots.map(x=>({index:x.index,framing:x.framing,action:x.action}))}:{presenter_mode:'',presenter_description:'',use_scene:getProject()?.brief.target?.use_scene||'',speech_mode:'voiceover',script_text:[script?.hook,script?.body,script?.cta].filter(Boolean).join('\n'),shots:spec.shots.map((x,index)=>({index,framing:x.framing,action:x.action})).filter(x=>plan.shot_index==null||x.index===plan.shot_index)};}
 function valid(){const c=s.content;return !!(c&&s.confirmed&&c.presenter_mode&&c.use_scene.trim()&&(c.presenter_mode==='faceless'||c.presenter_description.trim())&&(c.speech_mode==='none'||c.script_text.trim())&&c.shots.every(x=>x.framing.trim()&&x.action.trim()))}
 function error(code){return ({media_plugin_connection_changed:'账号版本已有变化，请重新准备方案并核对内容。',creative_request_stale:'商品资料已有变化，请建立当前版本的制作清单。',media_video_review_prompt_too_long:'内容超过当前视频模型限制，请缩短台词或镜头描述。',media_plugin_generation_already_submitted:'此制作版本已有未决提交，请继续原任务查询结果。',media_plugin_idempotency_conflict:'本次保存的内容已有变化，请重新核对后再保存。'}[code]||'内容审阅未保存，请核对人物方式、场景、台词和完整镜头，再重试原方案。')}
 function view(plan,stale=false){if(plan.provider!=='heygen')return '';if(s.plan?.id!==plan.id){s.epoch++;s.plan=plan;s.content=initial(plan);s.confirmed=false;s.editing=!plan.video_review;s.busy=false;s.error=''}else s.plan=plan;
  s.stale=stale;const c=s.content,spec=plan.source_request.spec;return `<section class="media-video-review" data-video-review-plan="${e(plan.id)}" aria-label="视频内容审阅"><h4>人物、场景与分镜</h4>${s.error?ui.alert(s.error,'danger'):''}${plan.video_review?`<p>这份方案已记录内容审阅。生成前仍需核对插件连接，并批准这一次生成。</p>${!s.editing?btn('修改内容并保存新方案','edit',{disabled:s.busy||stale}):''}`:''}${s.editing?`<fieldset ${s.busy?'disabled':''} class="video-review-editor"><legend>核对本次视频内容</legend>${ui.field('人物方式',ui.select({id:inputId('presenter_mode'),'data-video-review-field':'presenter_mode',value:c.presenter_mode,options:[{value:'',label:'请选择人物方式'},{value:'fictional_adult',label:'虚构成年讲解角色'},{value:'faceless',label:'不出镜 · 仅产品与场景'}]}))}<div data-video-person ${c.presenter_mode==='fictional_adult'?'':'hidden'}>${field('presenter_description','虚构成年角色的外观与呈现',c.presenter_description,800)}</div>${field('use_scene','具体使用场景',c.use_scene)}${ui.field('声音安排',ui.select({id:inputId('speech_mode'),'data-video-review-field':'speech_mode',value:c.speech_mode,options:[{value:'voiceover',label:'使用下面的台词'},{value:'none',label:'无口播 · 场景环境声'}]}))}<div data-video-speech ${c.speech_mode==='none'?'hidden':''}>${field('script_text',plan.shot_index==null?'本次完整台词':'仅此镜头的台词',c.script_text,3000)}</div><div class="video-review-shots">${c.shots.map(x=>{const shot=spec.shots[x.index];return `<section><h5>镜头 ${x.index+1} · ${shot.start_ms/1000}–${shot.end_ms/1000} 秒</h5>${field('shot.'+x.index+'.framing','景别与构图',x.framing,400)}${field('shot.'+x.index+'.action','展示动作与产品细节',x.action)}</section>`}).join('')}</div><label class="media-check"><input type="checkbox" id="${e(inputId('claims_confirmed'))}" data-video-review-confirm ${s.confirmed?'checked':''}> 我已对照本商品资料核对台词和展示动作，不含虚构使用经历或未提供的产品效果。</label><div class="form-actions">${btn('确认内容并保存新方案','save',{disabled:s.busy||stale||!valid()},true)}</div><p class="muted">保存内容不上传素材，也不提交生成。每次修改都会形成新方案，原方案和执行记录保留。</p></fieldset>`:`<details><summary>已审阅的人物、台词与镜头</summary><pre>${e(JSON.stringify(plan.video_review.content,null,2))}</pre></details>`}</section>`;
 }
 function updateButton(root){const b=root.querySelector('[data-video-review-action=save]');if(b)b.disabled=s.busy||s.stale||!valid()}
 function update(ev){const root=ev.target.closest('[data-video-review-plan]');if(!root||root.dataset.videoReviewPlan!==s.plan?.id||s.busy)return;
  if(ev.target.hasAttribute('data-video-review-confirm'))s.confirmed=ev.target.checked;
  else{const key=ev.target.dataset.videoReviewField;if(!key)return;if(key.startsWith('shot.')){const [,index,field]=key.split('.'),shot=s.content.shots.find(x=>x.index===Number(index));if(shot)shot[field]=ev.target.value}else s.content[key]=ev.target.value;
   if(key==='presenter_mode'){root.querySelector('[data-video-person]').hidden=s.content.presenter_mode!=='fictional_adult';if(s.content.presenter_mode==='faceless'){s.content.presenter_description='';root.querySelector('[data-video-review-field=presenter_description]').value=''}}
   if(key==='speech_mode'){root.querySelector('[data-video-speech]').hidden=s.content.speech_mode==='none';if(s.content.speech_mode==='none'){s.content.script_text='';root.querySelector('[data-video-review-field=script_text]').value=''}}
   s.confirmed=false;root.querySelector('[data-video-review-confirm]').checked=false;
  }updateButton(root);
 }
 document.addEventListener('input',update);document.addEventListener('change',update);
 document.addEventListener('click',async ev=>{const b=ev.target.closest('[data-video-review-action]');if(!b||b.disabled||!b.closest('.media-provider-flow'))return;ev.preventDefault();ev.stopImmediatePropagation();if(s.busy)return;const plan=s.plan,epoch=s.epoch,pid=getProject()?.id;if(!plan||pid!==plan.project_id)return;
  if(b.dataset.videoReviewAction==='edit'){s.editing=true;s.confirmed=false;repaint();queueMicrotask(()=>document.getElementById(inputId('presenter_mode'))?.focus({preventScroll:true}));return}if(s.stale||!valid())return;
  const content={...s.content,shots:s.content.shots.map(x=>({...x})),claims_confirmed:true},intent=JSON.stringify([plan.id,content]);if(!s.keys.has(intent))s.keys.set(intent,crypto.randomUUID());s.busy=true;s.error='';repaint();
  try{const result=await api('commerce_media_plugin_plan_review_video',{plan_id:plan.id,expected_plan_sha256:plan.plan_sha256,content,idempotency_key:s.keys.get(intent)});if(epoch===s.epoch&&getProject()?.id===pid&&s.plan?.id===plan.id){onPlan(result,plan.id);queueMicrotask(()=>document.getElementById('video-review-'+result.id+'-edit')?.focus({preventScroll:true}))}}
  catch(err){if(epoch===s.epoch&&s.plan?.id===plan.id)s.error=error(err.message)}finally{if(epoch===s.epoch&&s.plan?.id===plan.id){s.busy=false;repaint()}}
 });
 return {view};
};

/* Exact-plan approvals and provider receipts; never a browser OAuth proxy. */
window.CommerceMediaPluginExecutionFlow=({api,repaint,getProject,onProject,onRefresh,onPreview,onShots})=>{
 const ui=window.CommerceUI,e=ui.escape;
 const s={plan:null,execution:null,epoch:0,timer:null,busy:false,error:'',keys:new Map(),loaded:false};
 const labels={awaiting_approval:'等待你确认',rejected:'已拒绝',awaiting_host:'等待插件会话接续',claimed:'插件会话已领取',submitting:'已记录提交意图 · 等待真实回执',unknown:'远端结果未知 · 禁止重提',submitted:'生成服务处理中',retrieving:'正在回收并校验实际文件',download_failed:'文件回收未完成',result_held:'文件已保留 · 尚未用于当前版本',awaiting_review:'实际文件已回收 · 待审阅',failed:'生成服务返回失败',cancelled:'本地已停止采用结果'};
 const terminal=new Set(['rejected','awaiting_review','failed','cancelled','download_failed','result_held','unknown']);
 const btn=(label,action,attrs={},primary=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{'data-plugin-execution-action':action,disabled:s.busy,...attrs}});
 function current(planId,pid){return s.plan?.id===planId&&getProject()?.id===pid}
 function error(code){return ({media_plugin_connection_requires_attention:'插件连接需要重新核对或重新登录。',media_plugin_plan_requires_review:'当前方案仍有待确认条件，请先处理方案中的提示。',media_plugin_generation_already_submitted:'该制作版本存在未决远端任务，请先核对原回执。',creative_request_stale:'商品依据已有变化，请建立当前版本的新制作方案。',media_plugin_execution_approval_closed:'此方案的批准阶段已结束，请重新读取原任务。',media_plugin_execution_not_cancellable:'此任务已经有实际产出，请按当前审阅状态处理。',media_plugin_execution_download_retry_not_available:'当前任务不满足安全重试下载的条件，请先核对原回执。'}[code]||'操作未完成，原任务及已有回执已保留。请重新读取状态后核对。')}
 async function read(){const plan=s.plan,pid=getProject()?.id;if(!plan||pid!==plan.project_id)return;const epoch=++s.epoch;try{
   const result=await api('commerce_media_plugin_execution_list',{request_id:plan.request_id});if(epoch!==s.epoch||!current(plan.id,pid))return;
   const previous=s.execution;s.execution=(result.executions||[]).find(x=>x.plan_id===plan.id)||null;s.loaded=true;
   if(s.execution?.actual_bytes_verified&&!previous?.actual_bytes_verified){const p=await api('commerce_creative_get',{project_id:pid});if(epoch!==s.epoch||!current(plan.id,pid))return;onProject?.(p);await onRefresh?.()}else if(s.execution?.status!==previous?.status){await onRefresh?.()}
   clearTimeout(s.timer);if(s.execution&&!terminal.has(s.execution.status))s.timer=setTimeout(()=>{if(current(plan.id,pid)&&document.querySelector('[data-plugin-execution]'))read()},2000);
 }catch(err){if(current(plan.id,pid))s.error=error(err.message)}finally{if(current(plan.id,pid))repaint()}}
 function view(plan,stale=false){if(s.plan?.id!==plan.id){clearTimeout(s.timer);s.epoch++;s.plan=plan;s.execution=null;s.loaded=false;s.error='';s.busy=false;queueMicrotask(read)}else s.plan=plan;
   const x=s.execution,p=getProject();return `<section data-plugin-execution="${e(plan.id)}" class="plugin-execution" aria-label="插件执行与回执">${s.error?ui.alert(s.error,'danger'):''}${!s.loaded?'<p role="status">正在读取原执行记录…</p>':!x?`<p>先核对这份方案，再创建一条待确认的执行记录。此步骤不会上传或生成。</p>${btn('核对并创建执行记录','start',{disabled:s.busy||stale||!!plan.blockers.length},true)}`:`<h4>${e(labels[x.status]||'状态待核对')}</h4><p class="muted">原任务 ${e(x.task_id)} · ${e(x.id)}</p>${x.status==='awaiting_approval'?`<section class="plugin-execution-approval"><p><strong>${e(p?.brief.product.name||'当前商品')}</strong> · ${e(plan.account_label)} · ${plan.generation_count}${plan.provider==='lovart'?'张图片':'段视频'}</p><p>批准会允许当前插件会话按这份方案上传所选原图，并提交一次可能消耗额度的生成。批准绑定当前商品、账号和方案哈希。</p><div class="form-actions">${plan.sources.map(source=>btn('核对原图','source',{'data-asset':source.asset_id})).join('')}</div><details><summary>本次制作参数与约束</summary><pre>${e(JSON.stringify({model:plan.tool_call.arguments.model,settings:plan.tool_call.arguments.params,prompt:plan.tool_call.arguments.prompt,sources:plan.sources.map(a=>({id:a.asset_id,sha256:a.sha256})),plan_sha256:plan.plan_sha256},null,2))}</pre></details><div class="form-actions">${btn('批准这一次生成','approve',{disabled:s.busy||stale||!!plan.blockers.length},true)}${btn('拒绝','reject')}</div></section>`:''}${x.status==='awaiting_host'?`<p>在已连接 ${e(plan.provider==='lovart'?'Lovart':'HeyGen')} 的会话中继续此执行：<code>${e(x.id)}</code>。宿主领取后才能获得一次提交参数。</p>`:''}${x.status==='unknown'?ui.alert('原提交的结果尚未确认。请用原远端任务查询或补录真实回执，不要重新创建生成。','warning'):''}${x.provider_status?`<p>服务回执：${e(x.provider_status)}。${x.actual_bytes_verified?'文件字节与媒体信息已经校验。':'实际文件仍未完成校验。'}</p>`:''}${x.error_code?ui.alert(error(x.error_code),'warning'):''}${x.assets?.length?`<div class="form-actions">${x.assets.map(a=>btn('预览实际文件','preview',{'data-asset':a.id})).join('')}${x.shot_index!=null?btn('将此镜头带入本机剪辑','use-shot',{disabled:s.busy||stale||x.review_status!=='awaiting_review'}):''}</div>`:''}<div class="form-actions">${btn('读取原任务状态','refresh')}${x.status==='download_failed'?btn('只重试文件回收','retry'):''}${!['awaiting_review','rejected','failed','cancelled'].includes(x.status)?btn('停止本地采用','cancel'):''}</div>`}</section>`;
 }
 document.addEventListener('click',async ev=>{const b=ev.target.closest('[data-plugin-execution-action]');if(!b||!b.closest('.media-provider-flow')||b.disabled)return;ev.preventDefault();ev.stopImmediatePropagation();const action=b.dataset.pluginExecutionAction,plan=s.plan,pid=getProject()?.id;if(!plan||pid!==plan.project_id)return;
   if(action==='preview'||action==='source'){onPreview?.(b.dataset.asset);return}if(s.busy)return;if(action==='use-shot'){const x=s.execution;if(x?.assets.length&&x.shot_index!=null){onShots?.(plan.request_id,x.shot_index,x.assets[0].id);repaint()}return}
   s.busy=true;s.error='';repaint();try{if(action==='start'){if(!s.keys.has(plan.id))s.keys.set(plan.id,crypto.randomUUID());const x=await api('commerce_media_plugin_execution_start',{plan_id:plan.id,expected_plan_sha256:plan.plan_sha256,idempotency_key:s.keys.get(plan.id)});if(current(plan.id,pid))s.execution=x}
     else if(action==='approve'||action==='reject'){const x=await api('commerce_media_plugin_execution_approve',{execution_id:s.execution.id,expected_plan_sha256:plan.plan_sha256,decision:action==='approve'?'approve':'reject'});if(current(plan.id,pid))s.execution=x}
     else if(action==='cancel'){const x=await api('commerce_media_plugin_execution_cancel',{execution_id:s.execution.id});if(current(plan.id,pid))s.execution=x}
     else if(action==='retry'){const x=await api('commerce_media_plugin_execution_retry_download',{execution_id:s.execution.id});if(current(plan.id,pid))s.execution=x}
     if(current(plan.id,pid))await read();
   }catch(err){if(current(plan.id,pid))s.error=error(err.message)}finally{if(current(plan.id,pid)){s.busy=false;repaint()}}
 });
 return {view,refresh:read};
};

/* Host OAuth is never treated as an independently callable backend API. */
window.CommerceMediaPluginFlow=({api,repaint,getProject,onProject,onRefresh,onPreview,onShots})=>{
 const ui=window.CommerceUI,e=ui.escape;
 const s={rid:'',pid:'',preferredPlan:'',request:null,selected:[],shot:'full',plans:[],busy:false,error:'',epoch:0,keys:new Map()};
 const execution=window.CommerceMediaPluginExecutionFlow?.({api,repaint,getProject,onProject,onRefresh,onPreview,onShots});
 const videoReview=window.CommerceMediaVideoReview?.({api,repaint,getProject,onPlan:(plan,sourceId)=>{const selected=s.plans.find(x=>x.id===s.preferredPlan)||s.plans[0];if(selected?.id!==sourceId||plan.request_id!==s.rid||plan.project_id!==s.pid)return;s.plans=[plan,...s.plans.filter(x=>x.id!==plan.id)];s.preferredPlan=plan.id;s.epoch++;repaint()}});
 const labels={unbound:'尚未绑定账号',available_to_host:'宿主已读取模型 · 生成待核对',needs_reauthentication:'需要在插件中重新登录',not_verified:'待宿主复核',recheck_required:'连接检查已过期，需重新复核'};
 const blockers={needs_reauthentication:'插件需要重新授权',recheck_required:'请在插件会话重新检查连接',not_verified:'插件连接尚未核实',upload_exceeds_plugin_inline_limit:'原图超过插件单次传输限制',person_script_storyboard_approval_required:'人物、口播和分镜需要先确认',prompt_exceeds_plugin_limit:'制作说明超过当前插件长度限制'};
 const btn=(label,action,attrs={},primary=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{'data-plugin-media-action':action,disabled:s.busy,...attrs}});
 function error(code){return ({media_plugin_connection_changed:'账号绑定已有变化，请刷新后重新准备方案。',media_plugin_idempotency_conflict:'方案输入已变化，请刷新并核对当前版本。',creative_request_stale:'产品或设计方向已有变化，请建立当前版本的制作清单。'}[code]||'方案未能准备，请核对账号、商品版本和产品原图。')}
 async function load(rid,pid){const epoch=++s.epoch;try{const result=await api('commerce_media_plugin_plan_list',{request_id:rid});if(epoch!==s.epoch||getProject()?.id!==pid||s.rid!==rid)return;s.plans=result.plans||[];repaint()}catch(err){if(epoch===s.epoch){s.error=error(err.message);repaint()}}}
 function view(request,project,catalog){
  if(s.rid!==request.id||s.pid!==project.id){s.rid=request.id;s.pid=project.id;s.request=request;s.selected=project.assets.filter(a=>a.kind==='product_image').slice(0,1).map(a=>a.id);s.shot='full';s.plans=[];s.error='';s.busy=false;queueMicrotask(()=>load(request.id,project.id))}s.request=request;
  if(!catalog)return '';
  const video=request.spec.format.endsWith('_video'),provider=video?catalog.preferred_ugc_video:catalog.preferred_image;
  const binding=catalog.connections.find(x=>x.provider===provider);if(!binding)return '';
  const assets=project.assets.filter(a=>a.kind==='product_image'),plan=s.plans.find(x=>x.id===s.preferredPlan)||s.plans[0],planStale=plan&&(plan.stale||request.stale||plan.connection_revision!==binding.revision||plan.project_revision!==project.revision);s.binding=binding;
  return ui.card({title:(video?'视频优先 · ':'图片优先 · ')+binding.label+' 插件',content:`<p>${e(binding.account_label||'尚未选择账号')} ${e(binding.account_suffix||'')} · ${e(labels[binding.status]||'待核对')}</p><p class="muted">宿主插件在已连接的聊天会话中执行。这里先准备绑定商品版本的方案；后台不会直接复用插件授权。</p>${s.error?ui.alert(s.error,'danger'):''}<fieldset class="provider-assets"><legend>本方案使用的产品原图</legend>${assets.map(a=>`<label><input type="checkbox" data-plugin-media-asset="${e(a.id)}" ${s.selected.includes(a.id)?'checked':''}> ${e(a.display_name||a.id.slice(0,8))}</label>`).join('')||'<p>先在资料与素材中导入产品原图。</p>'}</fieldset>${video?ui.field('制作范围',ui.select({'data-plugin-media-field':'shot',value:s.shot,options:[{value:'full',label:'完整30秒视频'},...request.spec.shots.map((shot,i)=>({value:String(i),label:'镜头 '+(i+1)+' · '+shot.framing}))]})):''}${btn('准备插件制作方案','prepare',{disabled:s.busy||request.stale||!!request.result_sha256||!binding.revision||!s.selected.length},true)}${plan?`<section class="plugin-media-plan" aria-label="插件制作方案"><h4>${request.result_sha256?'本制作版本已有实际产出':planStale?'依据已变化，请重新准备':'方案已准备 · 等待插件会话核对'}</h4><p>${e(plan.account_label)} · ${plan.generation_count}${video?'段视频':'张图片'}。实际生成状态见下方执行回执。</p>${plan.blockers.length?ui.alert(plan.blockers.map(x=>blockers[x]||'当前条件仍需核对').join('；'),'warning'):''}<p>制作方案：<code>${e(plan.id)}</code>。实际提交以执行记录中的一次批准为准。</p>${btn('下载完整插件制作方案','download',{'data-id':plan.id})}${videoReview?.view(plan,planStale)||''}${execution?.view(plan,planStale)||''}<details><summary>产品约束与制作说明</summary><pre>${e(plan.tool_call.arguments.prompt)}</pre></details></section>`:''}`});
 }
 document.addEventListener('change',ev=>{const parent=ev.target.closest('.media-provider-flow');if(!parent)return;const asset=ev.target.dataset.pluginMediaAsset;if(asset){s.selected=ev.target.checked?[...new Set([...s.selected,asset])].slice(0,8):s.selected.filter(x=>x!==asset);repaint()}else if(ev.target.dataset.pluginMediaField){s.shot=ev.target.value;repaint()}});
 document.addEventListener('click',async ev=>{const b=ev.target.closest('[data-plugin-media-action]');if(!b||!b.closest('.media-provider-flow')||b.disabled)return;ev.preventDefault();ev.stopImmediatePropagation();const action=b.dataset.pluginMediaAction;if(action==='download'){const plan=s.plans.find(x=>x.id===b.dataset.id);if(!plan)return;const url=URL.createObjectURL(new Blob([JSON.stringify(plan,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='plugin-production-plan.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return}if(s.busy)return;
  const rid=s.rid,pid=s.pid,p=getProject(),binding=s.binding,shot=s.shot,selected=[...s.selected];if(!p||p.id!==pid)return;s.busy=true;s.error='';repaint();try{const intent=JSON.stringify([rid,p.revision,binding.provider,binding.revision,shot,selected]);if(!s.keys.has(intent))s.keys.set(intent,crypto.randomUUID());const plan=await api('commerce_media_plugin_plan_prepare',{request_id:rid,expected_revision:p.revision,provider:binding.provider,expected_connection_revision:binding.revision,asset_ids:selected,idempotency_key:s.keys.get(intent),...(shot==='full'?{}:{shot_index:Number(shot)})});if(getProject()?.id===pid&&s.rid===rid){s.plans=[plan,...s.plans.filter(x=>x.id!==plan.id)];s.preferredPlan=plan.id;s.epoch++}}catch(err){if(s.rid===rid)s.error=error(err.message)}finally{if(s.rid===rid){s.busy=false;repaint()}}
 });
 return {view,selectPlan:id=>{s.preferredPlan=id||''}};
};

/* Configured provider jobs share the existing product request and asset review. */
window.CommerceMediaProvidersFlow=({api,repaint,getProject,onProject,onPreview,onRefresh,onShots})=>{
 const ui=window.CommerceUI,e=ui.escape;
 const s={request:null,pid:'',catalog:null,jobs:[],profile:'',selected:[],shot:'full',loading:false,busy:false,error:'',notice:'',epoch:0,timer:null,keys:new Map()};
 const labels={pending:'等待提交',submitted:'服务处理中',succeeded:'文件已回收 · 待审阅',failed:'失败',unknown:'结果未知 · 未自动重发',cancelled:'本地已停止接收'};
 const btn=(label,action,attrs={},primary=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{'data-provider-action':action,disabled:s.busy,...attrs}});
 const plugins=window.CommerceMediaPluginFlow?.({api,repaint,getProject,onProject,onRefresh,onPreview,onShots});
 const video=()=>s.request?.spec.format.endsWith('_video');
 const profile=()=>s.catalog?.profiles.find(x=>x.id===s.profile);
 const current=()=>getProject()?.id===s.pid;
 function matches(job){return job.request_id===s.request?.id&&job.profile_id===s.profile&&(job.shot_index??'full')==s.shot}
 function message(code){return ({media_provider_not_ready:'请先检查并启用该服务的当前配置。',media_provider_profile_changed:'服务配置已有变化，请重新读取并核对。',media_provider_input_image_limit_exceeded:'选图数量超过当前模型的实际输入上限，请保留可用的产品原图。',media_provider_output_duration_mismatch:'返回视频的时长与提交要求不符，文件没有作为成品采用。请核对服务输出。',media_provider_duration_unsupported:'该模型无法覆盖所需时长，请逐镜头生成或更换配置。',creative_request_stale:'产品资料或设计方向已变化，请建立新的制作版本。',media_provider_existing_job_unknown:'原任务结果未知，请先核对回执。',media_plugin_generation_already_submitted:'原插件任务的远端结果尚未确认，当前制作版本不能改用其他服务重提。请先读取原插件回执。',media_provider_product_image_input_unsupported:'该配置不支持产品图片输入，无法保持本商品的身份。'}[code]||'操作未完成。请读取原任务状态，核对服务、产品图片和时长配置。')}
 async function read(quiet=false){if(!s.request||!current())return;const epoch=++s.epoch,pid=s.pid,rid=s.request.id;if(!quiet){s.loading=true;s.error='';repaint()}try{
   const [catalog,result]=await Promise.all([api('commerce_media_provider_catalog'),api('commerce_media_provider_jobs',{request_id:rid})]);if(epoch!==s.epoch||getProject()?.id!==pid||s.request?.id!==rid)return;
   const prior=new Map(s.jobs.map(j=>[j.id,j.status]));s.catalog=catalog;s.jobs=result.jobs||[];
   if(!catalog.profiles.some(x=>x.id===s.profile&&x.media_kind===(video()?'video':'image')))s.profile=catalog.profiles.find(x=>x.media_kind===(video()?'video':'image')&&x.selectable)?.id||'';
   const changed=s.jobs.some(j=>j.status==='succeeded'&&prior.get(j.id)!=='succeeded');
   if(changed){const p=await api('commerce_creative_get',{project_id:pid});if(epoch!==s.epoch||!current())return;onProject(p);await onRefresh()}
   clearTimeout(s.timer);if(s.jobs.some(j=>['pending','submitted'].includes(j.status)))s.timer=setTimeout(()=>read(true),1800);
 }catch(err){if(epoch===s.epoch)s.error=message(err.message)}finally{if(epoch===s.epoch){s.loading=false;repaint()}}}
 function choose(r,p){if(s.request?.id===r.id&&s.pid===p.id){s.request=r;return}clearTimeout(s.timer);s.epoch++;s.request=r;s.pid=p.id;s.jobs=[];s.profile='';s.selected=[];s.shot='full';s.error='';s.notice='';s.loading=true;queueMicrotask(()=>read())}
 function view(r,p){choose(r,p);const profiles=(s.catalog?.profiles||[]).filter(x=>x.media_kind===(video()?'video':'image')),assets=p.assets.filter(x=>x.kind==='product_image'),active=s.jobs.find(j=>matches(j)&&['pending','submitted','unknown','succeeded'].includes(j.status));
   const options=[{value:'full',label:video()?'完整30秒视频':'完整图片版本'},...(video()?r.spec.shots.map((shot,i)=>({value:String(i),label:'镜头 '+(i+1)+' · '+(shot.end_ms-shot.start_ms)/1000+'秒 · '+shot.framing})):[])];
   return `<section class="media-provider-flow" aria-label="生成服务制作" aria-busy="${s.loading||s.busy}"><div class="provider-heading"><h3>生成服务制作</h3>${btn('模型服务接入','setup')}${btn('读取任务状态','refresh')}</div>${plugins?.view(r,p,s.catalog?.plugin_connections)||''}${s.error?ui.alert(s.error,'danger'):''}${s.notice?ui.alert(s.notice):''}${s.loading?'<p role="status">正在读取已配置服务与原任务…</p>':''}${s.catalog?`${profiles.length?`<div class="provider-fields">${ui.field('使用哪个已配置服务',ui.select({'data-provider-field':'profile',value:s.profile,options:[{value:'',label:'请选择服务'},...profiles.map(x=>({value:x.id,label:x.label+' · '+x.model+(x.selectable?'':' · 待检查或启用')}))]}))}${ui.field('本次生成范围',ui.select({'data-provider-field':'shot',value:s.shot,options}))}</div>${profile()?`<p class="muted">${e(profile().test_status==='passed'?'只读连接探测通过':'连接未验证；以实际生成回执为准')} · 已占用 ${profile().occupied_slots||0} / ${profile().capabilities.max_concurrent_jobs||1} 个任务位。</p>`:''}<fieldset class="provider-assets"><legend>用于保持商品身份的产品原图（最多 ${profile()?.capabilities.max_input_images||1} 张）</legend>${assets.map(a=>`<label><input type="checkbox" data-provider-asset="${e(a.id)}" ${s.selected.includes(a.id)?'checked':''}> ${e(a.display_name||a.id.slice(0,8))}</label>`).join('')||'<p class="muted">请先在资料与素材中导入产品原图。</p>'}</fieldset><p class="muted">沿用本版本的参考拆解、产品卖点和分镜约束。提交到外部服务可能产生费用；服务完成后仍需审阅实际文件。</p>${btn(active?'已存在本范围任务 · 查看下方回执':'提交此版本生成','generate',{disabled:s.busy||r.stale||!profile()?.selectable||!s.selected.length||!!active||!!r.plugin_executions?.some(x=>x.external_generation_submitted&&!x.provider_terminal)},true)}`:ui.empty('尚无适用于本次图片或视频的服务，请在“模型服务接入”中配置。')}`:''}${s.jobs.length?ui.table(['范围与服务','真实状态','实际文件 / 操作'],s.jobs.map(j=>`<tr><td>${j.shot_index==null?'完整版本':'镜头 '+(j.shot_index+1)}<br>${e(j.model)}${j.submitted_duration_seconds?`<p class="muted">要求 ${j.requested_duration_seconds}秒 · 提交 ${j.submitted_duration_seconds}秒</p>`:''}</td><td>${e(labels[j.status]||j.status)}${j.stage==='queued'?'<p>等待本配置的并发空位</p>':''}${j.error?`<p>${e(message(j.error))}</p>`:''}${j.stale?'<p>依据已变化 · 文件尚未用于当前版本</p>':''}<small>${e(j.remote_task_id||j.id)}</small></td><td>${(j.assets||[]).map(a=>btn('预览实际文件','preview',{'data-asset':a.id})).join('')}${j.status==='succeeded'&&j.shot_index!=null?btn('将此镜头带入本机剪辑','use-shot',{'data-job':j.id,disabled:s.busy||j.stale}):''}${['pending','submitted','unknown'].includes(j.status)?btn('停止本地接收','cancel',{'data-job':j.id}):''}</td></tr>`)):''}</section>`;
 }
 document.addEventListener('change',ev=>{if(!ev.target.closest('.media-provider-flow'))return;if(ev.target.dataset.providerAsset){const id=ev.target.dataset.providerAsset;const limit=profile()?.capabilities.max_input_images||1;if(ev.target.checked&&!s.selected.includes(id)&&s.selected.length>=limit){ev.target.checked=false;s.error='该服务最多使用 '+limit+' 张产品原图。'}else{s.selected=ev.target.checked?[...new Set([...s.selected,id])]:s.selected.filter(x=>x!==id);s.error=''}repaint()}else if(ev.target.dataset.providerField){s[ev.target.dataset.providerField]=ev.target.value;if(ev.target.dataset.providerField==='profile'){const limit=profile()?.capabilities.max_input_images||1;s.selected=s.selected.slice(0,limit)}repaint()}});
 document.addEventListener('click',async ev=>{const b=ev.target.closest('[data-provider-action]');if(!b||!b.closest('.media-provider-flow')||b.disabled)return;ev.preventDefault();ev.stopImmediatePropagation();if(s.busy)return;const action=b.dataset.providerAction,pid=s.pid,rid=s.request?.id,epoch=s.epoch;if(action==='preview'){onPreview(b.dataset.asset);return}s.busy=true;s.error='';s.notice='';repaint();try{
   if(action==='setup'){const result=await api('commerce_capability_open_setup');if(current())s.notice=result.opened?'已在本机浏览器打开私有接入设置。':'浏览器未确认打开，请从后台设置进入私有接入页。'}
   else if(action==='refresh')await read();
   else if(action==='generate'){const p=profile(),intent=JSON.stringify([rid,p.id,p.revision,s.shot,[...s.selected].sort()]);if(!s.keys.has(intent))s.keys.set(intent,crypto.randomUUID());await api('commerce_media_provider_generate',{request_id:rid,profile_id:p.id,expected_profile_revision:p.revision,asset_ids:s.selected,idempotency_key:s.keys.get(intent),...(s.shot==='full'?{}:{shot_index:Number(s.shot)})});if(getProject()?.id===pid&&s.request?.id===rid)await read()}
   else if(action==='cancel'){await api('commerce_media_provider_cancel',{job_id:b.dataset.job});if(current())await read()}
   else if(action==='use-shot'){const j=s.jobs.find(x=>x.id===b.dataset.job);if(j?.assets.length&&!j.stale){onShots(rid,j.shot_index,j.assets[0].id);s.notice='已选择该镜头。补齐全部分镜后，可在本机制作区合成完整视频。'}}
 }catch(err){if(current()&&s.request?.id===rid)s.error=message(err.message)}finally{s.busy=false;if(getProject()?.id===pid)repaint()}});
 return {view,refresh:read,selectPluginPlan:id=>plugins?.selectPlan(id)};
};

/* Preparation diagnostics share the server's current contract, not generation permission. */
window.CommerceCreativeReadinessView=(data,kind,busy=false)=>{
 const ui=window.CommerceUI,e=ui.escape,button=(label,action,attrs={})=>ui.button({label,attrs:{id:action==='refresh'?'media-readiness-refresh':undefined,'data-media-action':action,disabled:busy,...attrs}});
 if(!data)return `<section class="media-readiness" aria-label="制作准备检查">${ui.alert('制作准备状态尚未读取，请重新检查当前资料。','warning')}${button('检查准备情况','refresh')}</section>`;
 const checks=data.checks||[],byKey=Object.fromEntries(checks.map(c=>[c.key,c])),canCreate=data.formats[kind]?.can_create_request;
 const needs=checks.filter(c=>c.status!=='ready'&&(c.stage==='planning'||c.key==='product_image'||c.key==='reference_media'&&(byKey.design_direction?.status!=='ready'||c.status!=='missing')));
 const labels={product_name:'补充商品名称',product_facts:'补充卖点及资料依据',product_image:'导入或核对产品原图',reference_media:'导入或核对参考素材',design_direction:'核对并保存设计方向',product_source:'核对当前商品来源'};
 const status={missing:'尚未提供',stale:'依据已有变化',unavailable:'登记文件不可读取或已变化',unchecked:'部分文件尚未检查'};
 return `<section class="media-readiness" aria-label="制作准备检查"><div class="media-readiness-heading"><strong>制作准备检查</strong>${button('重新检查','refresh')}</div><p>${canCreate?'当前商品依据与设计方向可以建立制作清单。':'先核对商品依据、参考素材与设计方向。产品原图可在建立清单后导入。'}${!data.plugin_inputs_ready&&canCreate?'插件制作还需有效产品原图。':''}</p>${needs.length?`<ul>${needs.map(c=>`<li><div><strong>${e(c.label)}</strong> · ${e(status[c.status]||'待核对')}${c.unchecked_count?`<small>本次检查 ${c.checked_count} 项，另有 ${c.unchecked_count} 项未检查。</small>`:''}</div>${button(labels[c.key]||'补齐资料','preparation',{'data-preparation-key':c.key,id:'media-preparation-'+c.key})}</li>`).join('')}</ul>`:''}</section>`;
};

/* One product/design contract for image sets and both video formats. */
window.CommerceMediaFlow=({api,repaint,getProject,onProject,onPreview,onPreparation})=>{
  const ui=window.CommerceUI,e=ui.escape;
  const labels={layout:'布局与信息层级',elements:'视觉元素',style:'视觉风格',colors:'色彩',typography:'文字与字级',selling_points:'卖点表达',shots:'镜头与特写',rhythm:'节奏与叙事',adaptation:'结合自己产品的调整',avoid:'避免照搬与失真'};
  const names={product_main:'商品主图',product_features:'卖点展示',product_detail:'细节特写',usage_scene:'使用场景',product_gallery:'产品展示',detail_page:'详情页图片',ugc_video:'UGC带货视频',showcase_video:'产品展示短视频'};
  const statuses={awaiting_media:'待制作 / 回收素材',queued:'已排队',running:'本机制作中',awaiting_review:'已产出 · 待审阅',approved:'已审阅通过',rejected:'已退回',failed:'制作失败',unknown:'结果未知',cancelled:'已取消',interrupted:'已中断'};
  const s={pid:'',revision:'',data:null,analysis:{},refs:[],job:null,subtab:'direction',busy:false,error:'',kind:'product_main',request:'',shots:{},attachment:'',audio:'',reviewNote:'',epoch:0,keys:new Map(),metrics:{},interval:'7',enabled:false,requestOpenGeneration:0,readinessError:false,imageProfile:"",imageRatio:"",imageCount:"6",imageLabel:"",imageFocus:""};
  const providers=window.CommerceMediaProvidersFlow?.({api,repaint,getProject,onProject,onPreview,onRefresh:()=>refresh(),onShots:(rid,index,asset)=>{s.shots[rid]||={};s.shots[rid][index]=asset}});
  const btn=(label,action,attrs={},primary=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{'data-media-action':action,...attrs}});
  const field=(label,key,value='',attrs={})=>ui.field(label,ui.input({value,'data-media-field':key,...attrs}));
  const area=(label,key,value='',rows=3)=>ui.field(label,`<textarea class="ui-control" id="media-${e(key.replaceAll('.','-'))}" data-media-field="${e(key)}" rows="${rows}" maxlength="${key==='reviewNote'?1200:key==='imageFocus'?1000:2000}">${e(value)}</textarea>`);
  const assets=(p,kinds)=>p.assets.filter(a=>kinds.includes(a.kind)).map(a=>({value:a.id,label:(a.display_name||a.id.slice(0,8))}));
  const select=(label,key,value,options)=>ui.field(label,ui.select({'data-media-field':key,value,options:[{value:'',label:'请选择实际素材'},...options]}));
  const errorText=code=>({creative_image_options_invalid:'请核对图片设置与5–10张的套图计划。',creative_image_set_size_invalid:'整套商品图请规划5–10张。',creative_image_platform_count_exceeded:'计划张数超过所选平台的参考上限，请调整。',creative_image_platform_ratio_invalid:'该商品卡规格要求方图，请选择1:1。',creative_image_profile_unknown:'请选择有效的平台和站点。',creative_product_name_required:'请先补充商品名称。',creative_direction_required:'请先拆解参考素材并保存设计方向。',creative_reference_media_required:'请先导入并选择参考图片、参考视频或关键帧。',creative_product_facts_required:'请先补充产品卖点与资料依据。',creative_request_stale:'商品资料或设计方向已变化，请建立当前版本的新制作请求。',creative_shot_assets_required:'请为每个分镜选择对应的实际素材。',creative_output_media_required:'请选择与本次图片或视频格式对应的实际成品。',creative_result_immutable_create_new_version:'这个版本已经有产出，请新建制作版本。',creative_policy_conflict:'复查计划已有新版本，请刷新后核对。',creative_vision_model_not_configured_use_manual_analysis:'当前没有可用的视觉模型入口，可先人工填写参考拆解。',creative_analysis_required:'视频请先在“原片拆解”提取关键帧，再进行视觉分析。',creative_asset_changed:'素材文件已有变化，请重新导入并核对。',creative_metrics_count_conflict:'点击、完播或退货数量与对应总数冲突，请核对统计口径。',creative_metrics_invalid_period:'请填写有效且已经结束的统计日期范围。',workspace_source_changed:'原商品资料已经更新，请重新核对商品绑定和创意资料。',creative_review_record_immutable:'此版本的审阅结论已保存，需要调整时请建立新版本。'}[code]||'本次操作未完成，请核对所填资料和当前版本后重试。');
  function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  async function refresh(){const p=getProject();if(!p)return;const epoch=++s.epoch;if(s.pid!==p.id){s.pid=p.id;s.data=null;s.request='';s.refs=(p.brief.design_direction?.references||[]).map(r=>r.asset_id);s.analysis={...p.brief.design_direction?.analysis};s.shots={};s.attachment='';s.job=null;s.metrics={};s.error='';s.subtab='direction';s.imageProfile='';s.imageRatio='';s.imageCount='6';s.imageLabel='';s.imageFocus=''}try{const data=await api('commerce_media_overview',{project_id:p.id});if(epoch!==s.epoch||getProject()?.id!==p.id)return;s.data=data;s.readinessError=false;if(!s.imageProfile&&data.image_planning){s.imageProfile=data.image_planning.default_profile;s.imageRatio=data.image_planning.profiles.find(x=>x.id===s.imageProfile)?.aspect_ratio||'1:1'}if(s.pid!==p.id){s.pid=p.id;s.request='';s.refs=(p.brief.design_direction?.references||[]).map(r=>r.asset_id);s.analysis={...p.brief.design_direction?.analysis};s.shots={};s.attachment='';s.job=null;s.metrics={};s.error='';s.subtab='direction';s.imageProfile='';s.imageRatio='';s.imageCount='6';s.imageLabel='';s.imageFocus=''}s.revision=p.revision;s.interval=String(data.policy.interval_days);s.enabled=data.policy.enabled;repaint()}catch(err){if(epoch===s.epoch){s.readinessError=true;s.error=errorText(err.message);repaint()}}}
  function direction(p){const refs=p.assets.filter(a=>['reference_image','reference_video','keyframe'].includes(a.kind));return `<p>先拆解参考的设计规律，再确定自己的产品如何表达。参考内容与商品事实分别保存。</p><div class="media-reference-list">${refs.length?refs.map(a=>`<label class="media-check"><input type="checkbox" data-media-reference="${a.id}" ${s.refs.includes(a.id)?'checked':''}> ${e(a.display_name||a.id.slice(0,8))} <small>${e(a.kind==='reference_image'?'参考图片':a.kind==='reference_video'?'参考视频':'关键帧')}</small></label>`).join(''):ui.empty('先在“资料与素材”导入参考图片或视频。')}</div><div class="form-actions">${btn('AI拆解选定参考','analyze',{disabled:s.busy||!refs.length})}<span class="muted">点击后向既有视觉模型提交选定图片，视频使用最多四张已提取关键帧。</span></div>${s.job?`<p role="status">参考拆解：${e(statuses[s.job.status]||s.job.status)} ${s.job.result?.error?e(errorText(s.job.result.error)):''}</p>`:''}<div class="media-direction-fields">${Object.entries(labels).map(([k,l])=>area(l,'analysis.'+k,s.analysis[k]||'')).join('')}</div><div class="form-actions">${btn('已核对，保存设计方向','direction-save',{disabled:s.busy},true)}${s.data?.direction_current?ui.badge('设计方向已保存','success'):ui.badge('设计方向待确认','gray')}</div>`}
  function requestView(p){const requests=s.data?.requests||[],r=requests.find(x=>x.id===s.request)||requests[0];if(!r)return ui.empty('选择需要的图片或视频类型，建立第一份制作清单。');s.request=r.id;const video=r.spec.format.endsWith('_video');return `<div class="media-version-select">${ui.field('制作版本',ui.select({'data-media-field':'request',value:r.id,options:requests.map((x,i)=>({value:x.id,label:(x.spec.image_options?.label||names[x.spec.format])+' · '+new Date(x.created_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · '+(statuses[x.status]||x.status)}))}))}${ui.badge(r.stale?'依据已变化':statuses[r.status]||r.status,r.stale?'warning':r.status==='approved'?'success':'gray')}</div><p>${e(r.spec.objective)}</p>${r.spec.image_delivery?`<p>${e(r.spec.image_options.label||r.spec.label)} · ${e(r.spec.image_delivery.label)} · ${e(r.spec.image_delivery.aspect_ratio)} · 本套计划${r.spec.image_options.set_size}张，本次1张</p><p class="muted">${e(r.spec.image_delivery.note)} 通用参考，仍需核对店铺/类目和实际成品文件。</p>`:''}<details><summary>制作提示词与产品约束</summary><textarea class="ui-control media-prompt" readonly rows="9" aria-label="可复制的制作提示词">${e(r.spec.prompt)}</textarea>${btn('下载制作清单','export-request')}</details>${video?ui.table(['分镜','时间','画面与动作'],r.spec.shots.map(shot=>`<tr><td>${e({usage_scene:'使用场景',product_closeup:'产品特写',demonstration:'使用演示',call_to_action:'收尾引导'}[shot.role])}</td><td>${shot.start_ms/1000}–${shot.end_ms/1000}秒</td><td>${e(shot.framing+' · '+shot.action)}</td></tr>`)):''}${providers?.view(r,p)||''}${r.job_status?`<p role="status">本机任务：${e(statuses[r.job_status]||r.job_status)} ${r.job_stage?e(r.job_stage.startsWith('render_shot_')?'正在制作镜头 '+r.job_stage.split('_').at(-1):r.job_stage.startsWith('layout_')?'正在排版':r.job_stage==='assemble_storyboard'?'正在合成分镜':''):''}</p>`:''}${r.assets.length?`<div class="media-output-assets">${r.assets.map(a=>btn('预览成品 · '+a.id.slice(0,8),'preview',{'data-asset':a.id})).join('')}</div>${r.review?`<p>审阅：${e(r.review.note)}</p>`:`${area('审阅说明','reviewNote',s.reviewNote)}<div class="form-actions">${btn('通过本地审阅','approve',{disabled:s.busy||r.stale},true)}${btn('退回调整','reject',{disabled:s.busy||r.stale})}</div>`}`:`<h3>本机制作</h3><p class="muted">使用实际图片或已制作镜头排版、剪辑。生成服务返回的单个镜头可直接带入；也可导入已制作的实际文件。</p><div class="media-shot-inputs">${video?r.spec.shots.map((shot,i)=>select((i+1)+'. '+shot.framing,'shot.'+i,s.shots[r.id]?.[i]||'',assets(p,['product_image','generated_image','generated_video']))).join(''):select('产品原图 / 已制作图片','shot.0',s.shots[r.id]?.[0]||'',assets(p,['product_image','generated_image']))}${video?select('配音或音轨（可选）','audio',s.audio,assets(p,['audio'])):''}</div>${btn(video?'按分镜渲染30秒草稿':'制作本机排版图','execute',{disabled:s.busy||r.stale||['queued','running'].includes(r.status)},true)}<h3>回收已制作的成品</h3><p class="muted">先在“资料与素材”导入实际生成结果，再绑定到当前制作版本。</p>${select('实际成品文件','attachment',s.attachment,assets(p,video?['generated_video','video_draft']:['product_image','generated_image','image_layout_draft']))}${btn('绑定成品，进入待审阅','attach',{disabled:s.busy||r.stale})}`}`}
  function imageSettings(){const planning=s.data?.image_planning;if(!planning||s.kind.endsWith('_video'))return '';const profile=planning.profiles.find(x=>x.id===s.imageProfile);return `<p class="muted">一套商品图通常规划5–10张，按产品需要安排；下面每次建立一张独立图片的制作版本。</p><div class="media-metric-fields">${ui.field('目标平台 / 站点',ui.select({'data-media-field':'imageProfile',value:s.imageProfile,options:planning.profiles.map(x=>({value:x.id,label:x.label}))}))}${field('本套计划张数','imageCount',s.imageCount,{type:'number',min:5,max:Math.min(10,profile?.max_images||10),step:1})}${ui.field('本张画幅',ui.select({'data-media-field':'imageRatio',value:s.imageRatio,options:(s.imageProfile==='tiktok_us'?['1:1']:['1:1','3:4','4:3']).map(value=>({value,label:value}))}))}${field('本张名称','imageLabel',s.imageLabel,{maxlength:120})}</div>${area('本张内容重点','imageFocus',s.imageFocus,2)}${profile?`<p class="muted">${e(profile.note)} 通用参考不代表类目核验或发布批准。</p>`:''}`}
  function production(p){const readiness=s.data?.readiness,current=!s.readinessError&&readiness?.project_revision===p.revision;return `${imageSettings()}${window.CommerceCreativeReadinessView?.(current?readiness:null,s.kind,s.busy)||''}<div class="media-create-row">${ui.field('制作类型',ui.select({id:'media-production-kind','data-media-field':'kind',value:s.kind,options:Object.entries(names).map(([value,label])=>({value,label}))}))}${btn('建立制作版本','create',{disabled:s.busy||s.readinessError||!s.data?.direction_current||!!readiness&&(!current||!readiness.formats[s.kind]?.can_create_request)},true)}</div>${!readiness&&!s.data?.direction_current?ui.alert('先保存参考拆解与设计方向，再组织图片和视频生产。'):''}${requestView(p)}`}
  function performance(){const m=s.metrics,sales=s.data?.sales_context,options=(s.data?.requests||[]).map(r=>({value:r.id,label:names[r.spec.format]+' · '+r.id.slice(0,8)}));return `<h3>销售与内容效果</h3>${sales?.status==='saved_order_snapshot'?ui.alert('已有商品发货单样本：'+sales.postings+'单、'+sales.units+'件。'+(sales.fresh?'快照在有效期内。':'快照已过期，待更新。')+(sales.scope_confirmed?'':'统计范围待核对。')+'销售额、曝光与素材转化仍需对应口径的数据。'):''}<p class="muted">空字段保持未知。统计数据保留来源、日期和素材版本；不直接将销量变化归因于设计。</p><div class="media-metric-fields">${field('开始日期','metric.period_start',m.period_start||'',{type:'date'})}${field('结束日期（不含当日）','metric.period_end',m.period_end||'',{type:'date'})}${field('数据来源','metric.source_ref',m.source_ref||'',{maxlength:1000})}${ui.field('素材版本',ui.select({'data-media-field':'metric.request_id',value:m.request_id||'',options:[{value:'',label:'商品整体 · 未归属具体素材'},...options]}))}${Object.entries({impressions:'曝光量',clicks:'点击量',orders:'订单数',returns:'退货数',video_views:'视频观看量',completed_views:'完整观看量'}).map(([k,l])=>field(l,'metric.'+k,m[k]??'',{type:'number',min:0,step:1})).join('')}</div>${area('购买疑问 / 评论 / 退货反馈','metric.feedback',m.feedback||'')}${btn('保存实际效果数据','metrics-save',{disabled:s.busy},true)}${ui.table(['统计范围','素材归属','点击率 / 订单比率','来源'],(s.data?.performance||[]).map(r=>`<tr><td>${e(r.payload.period_start.slice(0,10))} 至 ${e(r.payload.period_end.slice(0,10))}</td><td>${e(r.payload.request_id?.slice(0,8)||'商品整体')}</td><td>${r.metrics.ctr==null?'未知':(r.metrics.ctr*100).toFixed(2)+'%'} / ${r.metrics.conversion_rate==null?'未知':(r.metrics.conversion_rate*100).toFixed(2)+'%'}</td><td class="catalog-text">${e(r.payload.source_ref)}</td></tr>`))}<h3>定期设计复查</h3><div class="media-policy"><label class="media-check"><input type="checkbox" data-media-field="enabled" ${s.enabled?'checked':''}> 启用本地周期复查</label>${field('间隔天数','interval',s.interval,{type:'number',min:1,max:90,step:1})}${btn('保存复查周期','policy',{disabled:s.busy})}${btn('立即分析已有数据','review',{disabled:s.busy})}</div><p class="muted">${s.data?.policy.enabled&&s.data?.policy.next_due?'下次复查：'+new Date(s.data.policy.next_due*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'。':'周期复查未启用。'}服务运行时按期生成调整建议；新的生成与线上发布按明确操作执行。</p>${(s.data?.reviews||[]).map(r=>`<article class="media-review-report"><strong>${e(new Date(r.created_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))}</strong><p>${e(r.reason)}</p>${r.recommendations.map((x,i)=>`<p><strong>${e(names[x.kind])}</strong> · ${e(x.reason)} ${r.status==='ready_for_review'?btn('准备调整版本','recommend',{'data-kind':x.kind,'data-review':r.id,'data-index':i}):''}</p>`).join('')}</article>`).join('')}`}
  function view(){const p=getProject();if(!p)return ui.empty('先选择或创建创意项目。');if(s.pid!==p.id&&!s.busy){queueMicrotask(refresh);return '<p role="status">正在读取产品创意流程…</p>'}if(!s.data)return `<section class="media-flow">${s.error?ui.alert(s.error,'danger'):'正在读取创意流程…'}${btn('重新读取','refresh')}</section>`;return `<section class="media-flow" aria-label="商品图片与视频生产">${s.error?ui.alert(s.error,'danger'):''}${s.data?.binding_current===false?ui.alert('关联商品资料已有更新，请核对当前资料后建立新的创意版本。','warning'):''}<nav class="media-tabs" aria-label="创意生产步骤">${[['direction','参考与设计方向'],['production','图片与视频生产'],['performance','效果与周期调整']].map(([key,label])=>btn(label,'tab',{'data-tab':key,'aria-pressed':s.subtab===key})).join('')}</nav>${s.subtab==='direction'?direction(p):s.subtab==='production'?production(p):performance()}</section>`}
  async function poll(jobId,pid){try{const job=await api('commerce_creative_job_get',{job_id:jobId});if(getProject()?.id!==pid)return;s.job=job;if(['queued','running'].includes(job.status)){repaint();setTimeout(()=>poll(jobId,pid),1500)}else{if(job.input.kind==='design_analyze'&&job.status==='completed'){s.analysis={...job.result.analysis};s.refs=job.result.references.map(r=>r.asset_id)}const p=await api('commerce_creative_get',{project_id:pid});if(getProject()?.id!==pid)return;onProject(p);await refresh()}}catch{if(getProject()?.id===pid){s.error='任务状态暂不可读，保留原请求，不会重复生成。';repaint()}}}
  document.addEventListener('input',ev=>{if(!ev.target.closest('.media-flow'))return;const key=ev.target.dataset.mediaField;if(!key)return;const [group,part]=key.split('.');if(group==='analysis')s.analysis[part]=ev.target.value;else if(group==='metric')s.metrics[part]=ev.target.value;else if(group==='shot'){s.shots[s.request]||={};s.shots[s.request][part]=ev.target.value}else if(['interval','reviewNote','imageCount','imageLabel','imageFocus'].includes(key))s[key]=ev.target.value});
  document.addEventListener('change',ev=>{if(!ev.target.closest('.media-flow'))return;const ref=ev.target.dataset.mediaReference;if(ref){s.refs=ev.target.checked?[...s.refs.filter(x=>x!==ref),ref]:s.refs.filter(x=>x!==ref);return}const key=ev.target.dataset.mediaField;if(!key)return;const [group,part]=key.split('.');if(group==='shot'){s.shots[s.request]||={};s.shots[s.request][part]=ev.target.value}else if(group==='metric')s.metrics[part]=ev.target.value;else if(key==='enabled')s.enabled=ev.target.checked;else{s[key]=ev.target.value;if(key==='kind'){repaint()}if(key==='imageProfile'){s.imageRatio=s.data?.image_planning?.profiles.find(x=>x.id===s.imageProfile)?.aspect_ratio||'1:1';repaint()}if(key==='request'){s.requestOpenGeneration++;s.attachment='';s.reviewNote='';repaint()}}});
  document.addEventListener('click',async ev=>{const b=ev.target.closest('[data-media-action]');if(!b||!b.closest('.media-flow')||b.disabled)return;ev.preventDefault();const action=b.dataset.mediaAction,p=getProject();if(!p)return;if(action==='tab'){s.requestOpenGeneration++;s.subtab=b.dataset.tab;repaint();return}if(action==='preparation'){const item=s.data?.readiness?.checks.find(c=>c.key===b.dataset.preparationKey);if(!item)return;if(item.action.tab==='direction'){s.requestOpenGeneration++;s.subtab='direction';repaint();queueMicrotask(()=>document.getElementById('media-analysis-layout')?.focus({preventScroll:true}))}else onPreparation?.(item.action);return}if(action==='preview'){onPreview(b.dataset.asset);return}const requests=s.data?.requests||[],r=requests.find(x=>x.id===s.request)||requests[0];if(action==='export-request'){download(r,'product-media-production.json');return}if(s.busy)return;s.busy=true;s.error='';repaint();
    try{const args={project_id:p.id,expected_revision:p.revision};if(action==='refresh'){await refresh();return}if(action==='direction-save'){const result=await api('commerce_media_direction_save',{...args,analysis:s.analysis,reference_asset_ids:s.refs,...(s.job?.input.kind==='design_analyze'&&s.job.status==='completed'?{analysis_job_id:s.job.id}:{})});if(getProject()?.id===p.id){onProject(result);s.subtab='production'}}
      else if(action==='analyze'){const asset=p.assets.find(a=>a.id===s.refs[0]);if(!asset)throw Error('creative_reference_media_required');const key='design:'+p.id+':'+p.revision+':'+asset.id;if(!s.keys.has(key))s.keys.set(key,crypto.randomUUID());const job=await api('commerce_creative_design_analyze',{project_id:p.id,asset_id:asset.id,idempotency_key:s.keys.get(key)});s.job=job;poll(job.id,p.id)}
      else if(action==='create'||action==='recommend'){const kind=action==='recommend'?b.dataset.kind:s.kind;const request=await api('commerce_media_request_create',{...args,kind,idempotency_key:crypto.randomUUID(),...(!kind.endsWith('_video')&&s.data?.image_planning?{image_options:{profile_id:s.imageProfile,set_size:Number(s.imageCount),aspect_ratio:s.imageRatio,label:s.imageLabel,focus:s.imageFocus}}:{}),...(action==='recommend'?{review_id:b.dataset.review,recommendation_index:Number(b.dataset.index)}:{})});s.request=request.id;s.kind=kind;s.subtab='production'}
      else if(action==='execute'){const count=r.spec.shots.length||1,selected=Array.from({length:count},(_,i)=>s.shots[r.id]?.[i]||'');if(selected.some(x=>!x))throw Error('creative_shot_assets_required');const result=await api('commerce_media_request_execute',{request_id:r.id,expected_revision:p.revision,asset_ids:selected,...(s.audio?{audio_asset_id:s.audio}:{})});if(result.job_id)poll(result.job_id,p.id)}
      else if(action==='attach'){if(!s.attachment)throw Error('creative_output_media_required');await api('commerce_media_request_attach',{request_id:r.id,expected_revision:p.revision,asset_ids:[s.attachment]})}
      else if(action==='approve'||action==='reject')await api('commerce_media_request_review',{request_id:r.id,expected_result_sha256:r.result_sha256,decision:action==='approve'?'approved':'rejected',note:s.reviewNote});
      else if(action==='metrics-save'){const payload={};for(const [k,v] of Object.entries(s.metrics)){if(v==='')continue;payload[k]=['impressions','clicks','orders','returns','video_views','completed_views'].includes(k)?Number(v):['period_start','period_end'].includes(k)?v+'T00:00:00+08:00':v}const key=JSON.stringify(payload);if(!s.keys.has(key))s.keys.set(key,crypto.randomUUID());await api('commerce_media_performance_save',{project_id:p.id,payload,idempotency_key:s.keys.get(key)})}
      else if(action==='policy')await api('commerce_media_policy_save',{project_id:p.id,expected_revision:s.data.policy.revision,enabled:s.enabled,interval_days:Number(s.interval)});
      else if(action==='review')await api('commerce_media_review_now',{project_id:p.id,idempotency_key:crypto.randomUUID()});
      if(getProject()?.id===p.id)await refresh();
    }catch(err){if(getProject()?.id===p.id)s.error=errorText(err.message)}finally{s.busy=false;repaint()}
  });
  async function openRequest(id,planId,isCurrent=()=>true){const generation=++s.requestOpenGeneration,pid=getProject()?.id;await refresh();if(generation!==s.requestOpenGeneration||getProject()?.id!==pid||!isCurrent())return;if(!s.data?.requests.some(r=>r.id===id))throw Error('creative_request_not_found');s.request=id;s.subtab='production';providers?.selectPluginPlan(planId);repaint()}
  return {view,refresh,openRequest};
};

/* Creative business module; primitives and themes belong to CommerceUI. */
window.CommerceCreative=({api,esc,toast,repaint,isActive,getBinding})=>{
  const ui=window.CommerceUI;
  const state={projects:[],project:null,tab:'brief',busy:false,error:'',progress:'',job:null,preview:null,file:null,kind:'reference_video',asset:'',revision:0,form:{name:'',facts:'',transcript:'',source:'',language:'zh',country:''}};
  state.scopeCase=getBinding?.()?.case_id||'';
  function syncScope(){const binding=getBinding?.(),key=binding?.case_id||'';if(key!==state.scopeCase){state.scopeCase=key;state.revision++;state.project=null;state.job=null;state.watchedJob=null;state.preview=null;state.file=null;state.asset='';state.pendingSynthetic=false;state.tab='brief';state.form={name:'',facts:'',transcript:'',source:'',language:'zh',country:''}}return binding}
  const labels={brief:'资料与素材',analysis:'原片拆解',scripts:'文案与分镜',outputs:'图片与视频',workflow:'产品创意流程'};
  const status={queued:'已排队',running:'处理中',completed:'已完成',partial:'部分完成 · 有待补充项',failed:'处理失败',interrupted:'已中断 · 未自动重发',unknown:'结果未知 · 不会自动重发',cancelled:'已取消'};
  const kinds={reference_video:'参考视频',reference_image:'参考图片',product_image:'商品原图',audio:'补充音轨',captions:'字幕文件',generated_image:'已制作图片',generated_video:'已制作镜头',keyframe:'关键帧',image_layout_draft:'模板排版图',editable_layout:'可编辑排版',video_draft:'图文视频草稿',subtitle_file:'可编辑字幕'};
  const flow=window.CommerceMediaFlow({api,repaint:paint,getProject:()=>state.project,onProject:p=>{state.project=p},onPreview:preview,onPreparation:prepareInputs});
  const catalog=window.CommerceCatalog({api,repaint:paint,onSelect:id=>window.dispatchEvent(new CustomEvent('commerce:catalog-select',{detail:{case_id:id}})),onCreative:p=>openProject(p.id)});
  const errorText=e=>({creative_analysis_required:'请选择已完成的原片分析任务。',creative_transcript_review_text_required:'请填写不超过6000字的校对口播。',creative_project_busy:'该项目仍在处理，请先查看当前任务。',creative_workers_busy_try_later:'本机处理任务已满，请稍后再试。',creative_revision_conflict_refresh_first:'资料已有新版本，请刷新后重新编辑。',creative_render_requires_product_asset_and_facts:'请先填写商品名称、卖点依据，并选择商品图或已制作镜头。',creative_reference_video_required:'请选择已导入的参考视频。',creative_product_image_required:'请选择已导入的商品图片。',creative_caption_too_long_shorten_product_facts:'文案较长，请缩短商品名称或卖点后再制作30秒草稿。',creative_media_limits_exceeded:'素材超出当前处理范围：视频最长120秒，图片最多1600万像素。',creative_unsupported_media:'当前支持MP4、WebM、PNG、JPEG、WAV及UTF-8字幕文件。',creative_upload_hash_or_size_mismatch:'文件校验未通过，请重新选择原文件导入。',creative_chunk_out_of_order:'上传进度未确认，请使用同一原文件重新导入以恢复。',creative_upload_closed:'上传已结束，请刷新素材列表。'}[e.message]||'操作未完成，请刷新项目后重试。');
  const button=(label,action,attrs={},primary=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{'data-creative-action':action,...attrs}});
  const field=(key,label)=>ui.field(label,ui.input({id:'creative-'+key,'data-creative-field':key,value:state.form[key],maxlength:key==='name'?120:1000}));
  const area=(key,label,placeholder='')=>ui.field(label,`<textarea class="ui-control" id="creative-${key}" data-creative-field="${key}" rows="5" maxlength="6000" placeholder="${esc(placeholder)}">${esc(state.form[key])}</textarea>`);
  function formFrom(project){const b=project.brief;state.form={name:b.product?.name||'',facts:(b.product?.verified_facts||[]).map(f=>f.text+' | '+f.evidence_ref).join('\n'),transcript:b.reference?.transcript||'',source:b.reference?.source_url||'',language:b.target?.language||'zh',country:b.target?.country||'',audience:b.target?.audience||'',useScene:b.target?.use_scene||''}}
  function brief(){return {...(state.project?.brief||{}),...(!state.project&&getBinding?.()?{product_binding:getBinding()}:{}),synthetic:!!(state.pendingSynthetic||state.project?.brief.synthetic),product:{name:state.form.name.trim(),verified_facts:state.form.facts.split('\n').filter(x=>x.trim()).map((line,i)=>{const split=line.indexOf('|');if(split<0)throw Error('fact_format');const text=line.slice(0,split).trim(),source=line.slice(split+1).trim();if(!text||!source)throw Error('fact_format');return {id:'f'+(i+1),text,evidence_ref:source}})},reference:{...(state.project?.brief.reference||{}),source_url:state.form.source,transcript:state.form.transcript},target:{...(state.project?.brief.target||{}),language:state.form.language,country:state.form.country,audience:state.form.audience||'',use_scene:state.form.useScene||''}}}
  async function prepareInputs(action){if(!state.project||state.busy)return;if(action.tab==='catalog'){state.tab='catalog';await catalog.enter();paint();return}if(action.tab!=='brief')return;state.tab='brief';if(['product_image','reference_image','reference_video'].includes(action.asset_kind))state.kind=action.asset_kind;paint();if(['creative-name','creative-facts','creative-file','creative-audience','creative-useScene'].includes(action.focus))queueMicrotask(()=>document.getElementById(action.focus)?.focus({preventScroll:true}))}
  function paint(){if(isActive())repaint()}
  async function enter(){syncScope();try{state.projects=(await api('commerce_creative_list')).projects;paint()}catch(e){state.error=errorText(e);paint()}}
  async function open(id,isCurrent=()=>true){syncScope();const revision=++state.revision;state.busy=true;paint();try{const project=await api('commerce_creative_get',{project_id:id});if(revision!==state.revision||!isCurrent())return false;if(getBinding?.()&&project.brief.product_binding?.case_id!==getBinding().case_id)throw Error('creative_project_outside_selected_product');state.project=project;state.audio='';state.file=null;state.progress='';state.asset=project.assets.find(a=>a.kind==='product_image')?.id||project.assets.find(a=>a.kind==='reference_video')?.id||'';state.job=null;state.watchedJob=null;state.transcriptJob=null;state.preview=null;state.error='';formFrom(project);return true}catch(e){if(revision===state.revision&&isCurrent())state.error=errorText(e);return false}finally{if(revision===state.revision){state.busy=false;paint()}}}
  async function refresh(){if(!state.project)return;const id=state.project.id;const p=await api('commerce_creative_get',{project_id:id});if(state.project?.id===id)state.project=p;await enter()}
  function briefView(){return ui.card({title:'商品依据与参考资料',content:`<p class="muted">参考片用于研究叙事与镜头；商品主张以你填写的资料依据为准。当前草稿仍需校对。</p><form id="creative-brief-form" novalidate><div class="analysis-fields">${field('name','商品名称')}${field('language','目标语言')}${field('country','目标国家 / 市场')}${field('audience','目标人群')}${field('useScene','主要使用场景')}${field('source','参考视频来源链接（只记录来源）')}</div>${area('facts','商品卖点与依据','每行：一条商品事实 | 规格表或资料依据')}${area('transcript','原片口播 / 已校对字幕（可选）','尚无语音模型时可先粘贴原文，或导入字幕文件。')}<div class="form-actions">${button(state.project?'保存资料版本':'创建创意项目','save',{},true)}${getBinding?.()?'':button('填入合成示例','example')}</div></form>`})+ui.card({title:'私有素材',content:`<p class="muted">导入实际文件后才能读取画面。链接本身不会自动下载视频。视频最长120秒，单文件上限32MB。</p><div class="analysis-fields">${ui.field('素材类别',ui.select({id:'creative-kind',value:state.kind,options:['reference_video','reference_image','product_image','captions','generated_image','generated_video','audio'].map(k=>({value:k,label:kinds[k]}))}))}${ui.field('选择文件','<input class="ui-control" id="creative-file" type="file" accept="video/mp4,video/webm,image/png,image/jpeg,audio/wav,.srt,.vtt,.txt">')}</div><div class="form-actions">${button('导入所选素材','upload',{disabled:!state.project||!state.file||state.busy},true)}<span role="status">${esc(state.progress||state.file?.name||'尚未选择文件')}</span></div>${assetTable()}`})}
  function assetTable(){const assets=state.project?.assets||[];return ui.table(['素材','类别','来源状态','操作'],assets.map(a=>`<tr><td>${esc(a.display_name||a.id.slice(0,8))}</td><td>${esc(kinds[a.kind]||a.kind)}</td><td>${a.origin==='derived'?'本机衍生草稿':'用户导入 · 待核实'}</td><td>${button('预览 / 下载','asset',{'data-asset':a.id})}</td></tr>`),'尚未导入素材。')}
  function analysisView(){return ui.card({title:'原片拆解',content:`<p>检测画面切换候选、提取关键帧和画面文字，并读取口播。检测依据画面差异，闪光或快速移动也可能触发；不是语义分镜。</p><p class="muted">无切点时保留四个时间采样。机器转写需校对后回填，才会进入后续AI改写。</p>${assetSelect(['reference_video'])}${button('读取参考视频','analyze',{disabled:state.busy},true)}${analysisResult()}${jobView()}${assetTable()}`})}
  function analysisResult(){const j=state.job;if(j?.input.kind!=='analyze'||!j.result?.media)return '';const r=j.result,shots=r.shot_analysis,transcript=r.transcript||{};
    const reviewed=state.project?.brief.reference?.transcript_review?.source_job_id===j.id;if(state.transcriptJob!==j.id){state.transcriptJob=j.id;state.transcriptText=(reviewed?state.project.brief.reference.transcript:transcript.text)||''}
    return `<section class="creative-analysis" aria-label="原片分析结果"><h3>画面与口播</h3><p>${Number(r.media.duration_seconds).toFixed(2)}秒 · ${r.media.width}×${r.media.height} · ${r.media.has_audio?'含音轨':'无音轨'}</p><p class="muted">${shots?.method==='ffmpeg_visual_difference_candidates'?`检测到${shots.detected_cut_count}个画面切点候选${shots.omitted_cut_count?'；清单省略'+shots.omitted_cut_count+'个，部分区间包含多个切点':''}`:'本次未检测切点，显示时间采样'}。语义角色仍待人工解读。</p>${shots?.segments?.length?ui.table(['画面区间','时间'],shots.segments.map((s,i)=>`<tr><td>区间 ${i+1}</td><td>${s.start_seconds.toFixed(2)}–${s.end_seconds.toFixed(2)}秒</td></tr>`)):''}<div class="creative-frame-grid">${(r.keyframes||[]).map(f=>{const o=(r.ocr||[]).find(o=>o.asset_id===f.id);return `<article class="creative-frame"><strong>${Number(f.requested_timestamp_seconds).toFixed(2)}秒${f.fallback_to_first_frame?' · 回退首帧':''}</strong><p>${esc(o?.items?.map(x=>x.text).join('；')||'未识别到文字 / 识别不可用')}</p>${button('查看该关键帧','asset',{'data-asset':f.id})}</article>`}).join('')}</div>${ui.field('校对口播 / 字幕',`<textarea class="ui-control" id="creative-transcript-review" rows="6" maxlength="6000">${esc(state.transcriptText)}</textarea>`)}<p class="muted" id="creative-review-note">来源：${esc(reviewed?'调用者已校对 · 未独立核实':transcript.source==='local_whisper_tiny'?'本地语音转写 · 待校对':transcript.source==='not_available'?'尚无口播': '已提供文本 · 未独立核实')}。回填作为参考文案，商品事实保持独立；旧AI制作稿需重新审阅。</p>${button('已校对，回填参考文案','review_transcript',{'data-job':j.id,disabled:state.busy},true)}${(r.missing||[]).length?ui.alert('部分分析未完成，请结合关键帧与原片人工核对。','warning'):''}</section>`}
  function aiDraftView(){const j=state.job;if(j?.input.kind!=='refine'||!j.result?.scripts)return '';return `<section class="card"><h2>AI升级稿 · 待审阅</h2><p class="muted">已按目标语言请求改写，事实主张和翻译仍需核对。采用后才会进入视频制作。</p>${j.result.scripts.map(s=>`<article class="creative-script"><h3>${esc(s.hook)}</h3><p>${esc(s.body)}</p><p>${esc(s.cta)}</p>${s.warnings.includes('new_numbers_not_in_product_facts')?ui.alert('这版包含商品资料之外的数字，请重点核对。','danger'):''}${button('已核对，采用此稿','approve',{'data-angle':s.angle,'data-job':j.id})}</article>`).join('')}</section>`}
  function scriptsView(){const p=state.project?.plan;if(!p)return ui.empty('请先创建创意项目。');return ui.card({title:'三种切入点与分镜草稿',content:`${ui.badge(p.status==='draft_ready'?'本地模板草稿 · 待审阅':'待补充商品资料',p.status==='draft_ready'?'blue':'warning')}<p class="muted">本地正文只组合有来源卖点。点击AI升级时，会将所填商品文字和参考文案发送给既有模型，不上传原视频文件。</p>${button('AI升级三种文案','refine',{disabled:state.busy||p.status!=='draft_ready'},true)}${state.project?.brief.reviewed_script?ui.alert('已采用一份人工核对的制作稿，仍未独立核实商品主张。'):''}${aiDraftView()}${jobView()}${p.scripts.length?p.scripts.map((s,i)=>`<article class="creative-script"><h3>本地方案 ${i+1} · ${esc({detail:'商品细节',selection:'选购信息',demonstration:'演示说明'}[s.angle]||s.angle)}</h3><p><strong>开头：</strong>${esc(s.hook)}</p><p>${esc(s.body)}</p><p><strong>引导：</strong>${esc(s.cta)}</p><small class="muted">卖点依据：${s.fact_ids.map(esc).join('、')}</small></article>`).join(''):ui.empty('先填写商品名称与至少一条带依据的卖点。')}${ui.table(['片段','时间','制作事项'],p.video_plan.segments.map(s=>`<tr><td>${esc({hook:'开头',problem:'使用问题',demonstration:'产品演示',evidence_or_objection:'证据 / 异议',call_to_action:'行动引导'}[s.role])}</td><td>${s.start_ms/1000}–${s.end_ms/1000}秒</td><td>补充实际镜头、动作与资料，保持商品事实一致</td></tr>`))}<div class="form-actions">${button('导出项目JSON','export')}${button('导出制作清单Markdown','export_markdown')}</div>`})}
  function assetSelect(allowed){return ui.field('选择已导入素材',ui.select({id:'creative-asset',value:state.asset,options:[{value:'',label:'请选择'},...(state.project?.assets||[]).filter(a=>allowed.includes(a.kind)).map(a=>({value:a.id,label:(a.display_name||a.id.slice(0,8))+' · '+kinds[a.kind]}))]}))}
  function outputsView(){return ui.card({title:'图片与视频草稿',content:`<p>图片输出保留原图的三种模板排版和可编辑SVG。视频将商品素材与所选方案字幕组合成30秒图文草稿。</p><p class="muted">尚未自动抠图、生成真实使用场景或合成人物。可以导入已制作的图片、镜头和配音继续剪辑。</p>${assetSelect(['product_image','generated_image','generated_video'])}${ui.field('已导入的配音 / 音轨（可选）',ui.select({id:'creative-audio',value:state.audio||'',options:[{value:'',label:'不添加；镜头原有音轨会保留'},...(state.project?.assets||[]).filter(a=>a.kind==='audio').map(a=>({value:a.id,label:a.display_name||a.id.slice(0,8)}))]}))}${state.project?.brief.reviewed_script?ui.alert('视频使用已审阅AI稿；切换版本请到文案与分镜采用另一版。'):''}${ui.field('视频开头方案',ui.select({id:'creative-variant',value:state.variant||'0',disabled:!!state.project?.brief.reviewed_script,options:[{value:'0',label:'方案一 · 商品细节'},{value:'1',label:'方案二 · 选购信息'},{value:'2',label:'方案三 · 演示说明'}]}))}<div class="form-actions">${button('制作三种模板排版图','image_layout',{disabled:state.busy})}${button('渲染30秒视频草稿','render',{disabled:state.busy},true)}</div>${jobView()}${previewView()}${assetTable()}`})}
  function previewView(){if(!state.preview)return '';const p=state.preview;return `<div class="creative-preview">${p.mime.startsWith('image/')?`<img alt="私有创作素材预览" src="${p.url}">`:p.mime.startsWith('video/')?`<video controls playsinline src="${p.url}" aria-label="视频草稿预览"></video>`:''}<p>${esc(p.name)}</p>${button('下载该素材','download')}</div>`}
  function jobView(){const j=state.job,p=state.project;return `${j?`<section class="creative-job" role="status"><strong>${esc(status[j.status]||j.status)}</strong><p class="muted">资料版本 ${esc(j.input.revision)} · ${['queued','running'].includes(j.status)?'正在本机处理素材':'可查看已保留的处理结果'}${p&&j.input.revision!==p.revision?'；这是历史资料版本的结果':''}</p>${['queued','running'].includes(j.status)?'<p>'+esc(({visual_cut_detection:'正在检测画面切点',keyframes:'正在提取关键帧',transcript:'正在整理口播',local_asr:'正在本地转写',model_rewrite:'正在改写文案',rendering:'正在渲染视频'})[j.stage]||'正在处理素材')+'</p>':''}${['queued','running'].includes(j.status)?button('请求取消','cancel',{'data-job':j.id}):''}${j.result?`<details><summary>处理结果与限制</summary><pre>${esc(JSON.stringify(j.result,null,2))}</pre></details>`:''}</section>`:''}${(p?.jobs||[]).length?`<div class="creative-job-list">${p.jobs.slice(0,6).map(x=>button(({analyze:'原片分析',refine:'文案改写',image_layout:'图片排版',render:'视频制作'}[x.kind]||'任务')+' · '+(status[x.status]||x.status),'job',{'data-job':x.id,'data-job-kind':x.kind||''})).join('')}</div>`:''}`}
  function view(){const binding=syncScope();return `<section class="creative-workspace">${binding?'':'<div class="alert">文案、图片与视频共用一个项目。原片与图片保存在本机；点击AI升级时，仅提交商品文字与所填参考文案给既有模型。</div>'}${state.error?ui.alert(state.error,'danger'):''}<div class="creative-projects">${button('商品与货源','catalog')}${button('新建项目','new',{},true)}${state.projects.filter(p=>!binding||p.case_id===binding.case_id).map(p=>button((p.synthetic?'合成示例 · ':'')+p.name,'open',{'data-project':p.id,'aria-pressed':p.id===state.project?.id})).join('')}</div>${state.project?`<p class="muted">${esc(state.project.brief.product?.name||'未命名项目')} · 资料版本 ${esc(state.project.revision)} ${state.project.brief.synthetic?'· 合成测试资料':''}</p><div class="pills">${Object.entries(labels).map(([k,v])=>button(v,'tab',{'data-creative-tab':k,'aria-pressed':state.tab===k,class:'creative-tab '+(state.tab===k?'active':'')})).join('')}</div>`:''}${state.tab==='catalog'?catalog.view():state.tab==='workflow'?flow.view():state.tab==='brief'?briefView():state.tab==='analysis'?analysisView():state.tab==='scripts'?scriptsView():outputsView()}${state.tab==='outputs'?'':previewView()}</section>`}
  async function save(){if(!state.form.name.trim())throw Error('name_required');let b;try{b=brief()}catch{throw Error('fact_format')}
    if(state.project){state.project=await api('commerce_creative_save',{project_id:state.project.id,brief:b,revision:state.project.revision})}
    else{const frozen=JSON.stringify(b);if(state.pendingCreate?.frozen!==frozen)state.pendingCreate={frozen,key:crypto.randomUUID()};state.project=await api('commerce_creative_create',{brief:b,idempotency_key:state.pendingCreate.key})}
    state.error='';await enter();toast('已保存私有创作资料，草稿仍需审阅。')}
  async function upload(){const file=state.file,p=state.project;if(!file||!p)return;if(file.size>32*1024*1024)throw Error('file_too_large');if(!crypto.subtle)throw Error('file_hash_unavailable');const data=new Uint8Array(await file.arrayBuffer()),sha=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(b=>b.toString(16).padStart(2,'0')).join('');const u=await api('commerce_creative_upload_begin',{project_id:p.id,filename:file.name,kind:state.kind,size:String(file.size),sha256:sha,source_ref:['reference_image','reference_video','captions'].includes(state.kind)?state.form.source||'user_provided_unverified':'user_provided_unverified'});
    if(!u.asset_id){for(let i=u.next_index;i<Math.ceil(data.length/u.chunk_bytes);i++){const bytes=data.subarray(i*u.chunk_bytes,(i+1)*u.chunk_bytes);let binary='';for(const b of bytes)binary+=String.fromCharCode(b);await api('commerce_creative_upload_chunk',{upload_id:u.upload_id,index:String(i),content_base64:btoa(binary)});state.progress='已导入 '+Math.min(100,Math.round((i+1)*u.chunk_bytes/data.length*100))+'%';paint()}}
    const completed=await api('commerce_creative_upload_finish',{upload_id:u.upload_id});if(state.project?.id===p.id){state.asset=completed.asset_id;state.progress='校验完成，素材已保存。';state.file=null;await refresh()}}
  async function job(action){const p=state.project;if(!p||(action!=='refine'&&!state.asset))throw Error('asset_required');const args={project_id:p.id};if(action!=='refine')args.asset_id=state.asset;if(action==='render'){args.variant=state.variant||'0';if(state.audio)args.audio_asset_id=state.audio}const frozen=JSON.stringify([action,p.revision,args]);state.keys||=new Map();if(!state.keys.has(frozen))state.keys.set(frozen,crypto.randomUUID());args.idempotency_key=state.keys.get(frozen);state.job=null;state.watchedJob=null;paint();const result=await api('commerce_creative_'+action,args);if(state.project?.id===p.id){state.job=result;watch(result.id,p.id);await refresh()}}
  function watch(id,project){state.watchedJob=id;poll(id,project)}
  async function poll(id,project){if(state.watchedJob!==id)return;try{const j=await api('commerce_creative_job_get',{job_id:id});if(state.project?.id!==project||state.watchedJob!==id)return;state.job=j;if(['queued','running'].includes(j.status)){paint();setTimeout(()=>poll(id,project),1500)}else await refresh()}catch(e){state.error='任务状态暂不可读；保留原任务，不会重复提交。';paint()}}
  async function readAsset(asset){const p=state.project,parts=[];let offset='0',result;do{result=await api('commerce_creative_asset_read',{project_id:p.id,asset_id:asset,offset});const b=atob(result.content_base64);parts.push(Uint8Array.from(b,c=>c.charCodeAt(0)));offset=result.next_offset}while(!result.done);return {blob:new Blob(parts,{type:result.mime}),mime:result.mime,extension:result.extension||''}}
  async function preview(asset){const p=state.project;const a=p.assets.find(x=>x.id===asset);const result=await readAsset(asset);if(state.project?.id!==p.id)return;const bytes=new Uint8Array(await result.blob.arrayBuffer());let binary='';for(const b of bytes)binary+=String.fromCharCode(b);state.preview={name:(a.display_name||'素材')+((a.display_name||'').toLowerCase().endsWith(result.extension)?'':result.extension),mime:result.mime,url:'data:'+result.mime+';base64,'+btoa(binary),blob:result.blob};paint()}
  function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000)}
  document.addEventListener('input',e=>{if(e.target.dataset.creativeField)state.form[e.target.dataset.creativeField]=e.target.value;else if(e.target.id==='creative-transcript-review')state.transcriptText=e.target.value});
  document.addEventListener('change',e=>{if(e.target.id==='creative-file'){state.file=e.target.files[0]||null;state.progress='';paint()}else if(e.target.id==='creative-kind')state.kind=e.target.value;else if(e.target.id==='creative-asset')state.asset=e.target.value;else if(e.target.id==='creative-variant')state.variant=e.target.value;else if(e.target.id==='creative-audio')state.audio=e.target.value});
  document.addEventListener('submit',e=>{if(e.target.id==='creative-brief-form'){e.preventDefault();e.stopImmediatePropagation();document.querySelector('[data-creative-action="save"]')?.click()}});
  document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.form?.id==='creative-brief-form'&&e.target.tagName==='INPUT'){e.preventDefault();document.querySelector('[data-creative-action="save"]')?.click()}});
  document.addEventListener('click',async e=>{const b=e.target.closest('[data-creative-action]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();const action=b.dataset.creativeAction;if(state.busy&&!['cancel','tab'].includes(action))return;state.error='';
    try{if(action==='catalog'){state.tab='catalog';await catalog.enter();paint();return}if(action==='tab'){state.tab=b.dataset.creativeTab;if(state.tab==='workflow')flow.refresh();const allowed=state.tab==='analysis'?['reference_video']:state.tab==='outputs'?['product_image','generated_image','generated_video']:null;if(allowed&&!state.project?.assets.some(a=>a.id===state.asset&&allowed.includes(a.kind)))state.asset='';paint();return}if(action==='new'){state.project=null;state.job=null;state.watchedJob=null;state.preview=null;state.pendingSynthetic=false;state.audio='';state.file=null;state.progress='';state.tab='brief';state.form={name:'',facts:'',transcript:'',source:'',language:'zh',country:''};paint();return}if(action==='example'){state.project=null;state.job=null;state.watchedJob=null;state.preview=null;state.audio='';state.file=null;state.progress='';state.form={name:'合成收纳盒',facts:'合成示例：容量为500毫升 | synthetic:spec-1',transcript:'这是合成参考文本，不代表真实商品或用户体验。',source:'synthetic:example',language:'zh',country:'示例市场'};state.pendingSynthetic=true;paint();return}
      state.busy=true;b.disabled=true;paint();if(action==='open')await open(b.dataset.project);else if(action==='save'){await save();state.pendingSynthetic=false}else if(action==='upload')await upload();else if(['analyze','render','image_layout','refine'].includes(action))await job(action);else if(action==='approve'){state.project=await api('commerce_creative_approve_script',{project_id:state.project.id,job_id:b.dataset.job,angle:b.dataset.angle,revision:state.project.revision});await refresh()}else if(action==='job'){state.job=await api('commerce_creative_job_get',{job_id:b.dataset.job});watch(state.job.id,state.project.id)}else if(action==='cancel'){await api('commerce_creative_job_cancel',{job_id:b.dataset.job});watch(b.dataset.job,state.project.id)}else if(action==='review_transcript'){state.project=await api('commerce_creative_review_transcript',{project_id:state.project.id,job_id:b.dataset.job,revision:state.project.revision,text:state.transcriptText||''});state.form.transcript=state.project.brief.reference.transcript;await refresh();toast('已回填参考文案；请重新审阅AI制作稿。')}else if(action==='asset')await preview(b.dataset.asset);else if(action==='download')download(state.preview.blob,state.preview.name);else if(action==='export_markdown'){const pack=await api('commerce_creative_export',{project_id:state.project.id,format:'markdown'});download(new Blob([pack.content],{type:'text/markdown;charset=utf-8'}),'creative-production-brief.md')}else if(action==='export')download(new Blob([JSON.stringify(await api('commerce_creative_export',{project_id:state.project.id}),null,2)],{type:'application/json'}),'creative-project-draft.json');
    }catch(error){state.error=({fact_format:'每条卖点请填写“商品事实 | 资料依据”。',name_required:'请填写商品名称。',asset_required:'请先选择已导入的素材。',file_too_large:'单文件最多32MB，请先截取需要研究的片段。',file_hash_unavailable:'当前窗口不支持文件校验，请在本机浏览器导入素材。'}[error.message]||errorText(error))}finally{state.busy=false;paint()}
  });
  async function openProject(id,requestId,planId,isCurrent=()=>true){if(!isCurrent()||!await open(id,isCurrent)||!isCurrent())return;const revision=state.revision;state.tab='workflow';if(requestId)await flow.openRequest(requestId,planId,()=>isCurrent()&&revision===state.revision);else await flow.refresh();if(isCurrent()&&revision===state.revision)paint()}
  return {view,enter,openProject};
};

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
  const tabs = {overview:'概览',research:'市场研究',cost:'成本测算',content:'商品内容',review:'方案审阅',tasks:'任务记录',media:'图片与视频'};
  const fields = {currency:'币种',price:'销售单价',purchase_cost:'采购成本',domestic_shipping:'境内运费',packaging:'包装成本',fulfillment_cost:'履约费用',electronic_fee:'其他平台费用',commission_rate:'佣金比例',payment_rate:'支付比例',return_rate:'退货比例',ad_rate:'广告比例'};
  const listingFields = {sku:'SKU',title:'标题',description:'商品描述',category_id:'类目 ID',price:'售价',currency:'币种',quantity:'数量',image_refs:'素材引用'};
  let quoteEdit=null,quoteError='',quoteEpoch=0,deliveryEdit=null,deliveryError='',deliveryNotice='',deliveryEpoch=0;
  let quoteComparison={caseId:'',quantity:'',result:null};
  const itemLabel = c => c.name+(s.items.filter(x=>x.name===c.name).length>1?' · '+(platformNames[c.platform]||c.platform)+' / '+(c.market||'市场待核对')+' · '+c.id.slice(0,8):'');
  const platformNames = {ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu'};
  const s = {id:bootstrap.case_id || new URL(location.href).searchParams.get('case_id') || '',tab:'overview',items:[],data:null,busy:false,error:'',errorCode:'',generation:0,edits:{},dirty:new Set(),changes:0,mobile:'product',chatVisible:true,fieldErrors:{},opener:null,dialogAction:null};
  s.researchTaskId=bootstrap.research_task_id||(!bridged?new URL(location.href).searchParams.get('research_task_id'):'')||'';s.researchSequence=0;s.researchLoading=false;s.researchContextError='';
  const catalog=window.CommerceCatalog({api,repaint:render,onSelect:async id=>{if(s.dirty.size){s.error='当前商品有未保存输入，请保存后再切换。';render();return}s.catalogOpen=false;await reload({select:id,clearEditors:true})},onCreative:async p=>{s.catalogOpen=false;s.tab='media';render();await studio.openProject(p.id);render();document.getElementById('pw-tab-media')?.scrollIntoView({block:'nearest',inline:'nearest'})}});
  const studio=window.CommerceCreative({api,esc,toast:text=>announce(text),repaint:render,isActive:()=>s.tab==='media'&&!s.catalogOpen,getBinding:()=>s.data?{case_id:s.data.case.id,source_sha256:s.data.source_sha256}:null});
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
    const known = {agent_workspace_evidence_changed:'商品资料、报价或交付审阅版本已变化，请重新读取当前工作项。旧建议未提交，原记录保留。',workspace_research_context_invalid:'研究链接无效，请从原研究任务重新打开。',workspace_research_context_mismatch:'本次研究与商品不匹配，请从原研究任务重新打开。',workspace_research_artifact_invalid:'本次研究快照完整性检查未通过，请回原研究核对。',workspace_research_context_unavailable:'本次研究快照未读回，请回原研究核对。当前商品输入仍保留。',agent_evidence_reference_required:'模型答复缺少来源引用，未采纳本轮结果；核对资料后可明确发送新问题。',workspace_source_changed:'资料已更新，输入已保留。请核对后重新保存。',form_draft_conflict:'草稿已有新版本，输入已保留。请核对后合并。',organization_case_not_found:'当前连接中找不到这个工作项。请核对连接与商品范围。',workspace_content_checkpoint_required:'请先保存当前内容编辑，再生成待审阅版本。',workspace_currency_required:'请先明确工作项币种，并使用相同币种测算。',workspace_artifact_changed:'原产物完整性检查未通过，请先核对来源。',workspace_handoff_held:'成本产物交接尚未确认，请核对原记录。',business_preflight_incomplete:'草稿仍有缺项、无效引用或过期来源，请补齐后再审阅。',business_draft_changed:'草稿版本已变化，请重新读取并审阅。',agent_provider_outcome_unknown:'模型结果尚未确认。请核对原请求记录，不会自动重发。',agent_model_setup_required:'当前模型入口尚未配置，请完成本机接入后继续。',agent_current_evidence_required:'当前依据不足或已改变，请重新核对来源后再分析。',authentication_required:'本次连接没有有效授权，请通过项目正常入口重新打开。',unknown_tool:'当前后台尚未加载商品工作区接口，请核对运行版本。',commerce_service_unavailable:'共享后台暂不可用。输入已保留，请恢复连接后查询原记录。'};
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
    quoteEpoch++;deliveryEpoch++;
    root.inert=false;
    document.getElementById('modal-root').innerHTML='';s.dialogAction=null;
    const prior=s.opener;
    // A completed read can repaint the product behind the open dialog.
    const opener=prior?.isConnected?prior:prior?.id?document.getElementById(prior.id):[...root.querySelectorAll('[data-pw-action]')].find(node=>node.dataset.pwAction===prior?.dataset.pwAction&&node.getClientRects().length&&!node.disabled);
    opener?.focus?.({preventScroll:true});
  }
  function dialog(title,body,actions='',callback=null) {
    if(!document.getElementById('modal-root').firstElementChild)s.opener=document.activeElement;
    s.dialogAction=callback;root.inert=true;
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
    const reviewed=d.delivery_review?.status==='local_review_recorded'&&contentCurrent;
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
    return `<section class="pw-task-summary"><header><div><strong>${esc(d.name)} · 商品推进</strong></div>${btn(plan.steps.length?'目标 · '+plan.steps.length+' 步':'目标','goal',false,{quiet:true})}</header>${plan.goal?`<p class="pw-task-goal">${esc(plan.goal)}</p>`:''}<ol class="pw-workflow">${rows.map((row,i)=>`<li class="${row.complete?'is-ready':''}" data-workflow-stage="${row.id}"><span class="pw-step-index">${i+1}</span><div>${btn(row.title,row.id==='S3'?'quotes':'tab-'+row.target,false,{quiet:true,title:row.hint||row.title})}</div>${ui.badge(row.label,row.tone)}</li>`).join('')}</ol>${pending.length?`<div class="pw-task-pending"><strong>待处理</strong><ul>${pending.map(g=>`<li title="${esc(g.reason)}">${esc(pendingLabel(g.reason))}</li>`).join('')}</ul></div>`:''}<footer><span>${tasks.length?tasks.length+' 个关联任务':'尚无关联任务'}</span>${btn('任务记录','tab-tasks',false,{quiet:true})}</footer></section>`;
  }
  function header() {
    const d=s.data,c=d.case,scope=c.scope,hasContent=d.content_drafts.length>0;
    const next=!d.artifacts.research?['补充研究','tab-research']:d.calculation.status!=='CALCULATED'?['下一步：成本测算','tab-cost']:[hasContent?'审阅方案':'准备内容',hasContent?'tab-review':'tab-content'];
    return `<header class="pw-object-header"><span class="pw-object-symbol">${ui.icon('box')}</span><div class="pw-object-title"><div class="pw-title-row"><h1 title="${esc(d.name)}">${esc(d.name)}</h1>${btn('','choose-product',false,{quiet:true,icon:'chevronDown','aria-label':'切换商品',title:'切换商品',disabled:s.busy})}</div><div class="pw-object-meta"><span>${scope.origin==='research_candidate_not_inventory'?'目标 ':''}${esc(platformNames[scope.platform]||scope.platform)} · ${esc(scope.market||'市场待核对')}</span>${scope.synthetic===true?ui.badge('合成数据','gray'):scope.origin==='research_candidate_not_inventory'?ui.badge('调研候选','gray'):''}<span>${esc(c.currency||'币种待核对')}</span>${scope.sku?`<span>SKU · ${esc(scope.sku)}</span>`:''}</div></div><div class="pw-header-actions">${btn('商品列表','catalog',false,{disabled:s.busy})}${btn('上架准备','listing',false,{disabled:s.busy})}${s.tab==='overview'?btn(next[0],next[1],true,{disabled:s.busy}):''}${btn('','more',false,{quiet:true,icon:'more','aria-label':'更多商品操作',title:'更多商品操作'})}</div></header><nav class="pw-tabs" role="tablist" aria-label="商品工作区内容">${Object.entries(tabs).map(([key,label])=>`<button role="tab" type="button" data-pw-tab="${key}" id="pw-tab-${key}" aria-controls="pw-tabpanel" aria-selected="${key===s.tab}" tabindex="${key===s.tab?'0':'-1'}">${label}</button>`).join('')}</nav>`;
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
    return `<div class="pw-cost-layout">${section('测算参数',`<form id="pw-cost-form"><div class="pw-input-grid">${Object.entries(fields).filter(([k])=>!advanced.includes(k)).map(([k,v])=>field(k,v)).join('')}</div><details class="pw-disclosure" ${missing?'open':''}><summary>支付、退货与广告费率</summary><div class="pw-input-grid">${advanced.map(k=>field(k,fields[k])).join('')}</div></details><p class="pw-meta" id="pw-cost-boundary">同币种金额；费率填 0–1。</p>${!s.data.case.currency||s.data.case.currency!==values.currency?btn('确认使用此币种','set-currency',false,{disabled:s.busy||!values.currency}):''}<div class="pw-form-actions">${btn('保存并测算','save-calculate',true,{disabled:s.busy})}${reactHost?btn('动态成本测算','dynamic-cost',false,{disabled:s.busy||s.dirty.has('cost'),title:s.dirty.has('cost')?'请先保存当前成本参数':'使用当前商品及来源版本'}):''}${btn('保存成本情景','scenario-open-save',false,{disabled:s.busy||s.dirty.has('cost')||s.data.forms.cost.stale||s.data.calculation.status!=='CALCULATED'})}${btn('对比已存情景','scenario-compare',false,{disabled:s.busy})}${formStatus('cost')}</div></form>`)}<div id="pw-cost-result">${costSummary()}${extra?`<details class="pw-disclosure"><summary>资料缺项</summary>${extra}</details>`:''}</div></div>`;
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
    const body=`${deliveryError?alert(deliveryError,'danger'):''}${deliveryNotice?`<p role="status">${esc(deliveryNotice)}</p>`:''}${stale?alert('当前交付版本已改变，输入保留供核对；请读取当前版本后重新确认。','warning'):''}<p>${esc(s.data.name)} · 本地交付审阅；发布前核查状态为 ${esc(view.professional_gate)}（经营负责人签收不属于独立认证）。</p><dl class="pw-review-checks">${view.automatic_checks.map(c=>`<div><dt>${esc(c.label)}</dt><dd>${ui.badge(c.passed?'本轮检查通过':'待补齐或复验',c.passed?'success':'warning')}</dd></div>`).join('')}</dl>${Object.entries(view.requirements).map(([key,label])=>{const row=deliveryEdit.checks[key];return `<section class="pw-section"><h3>${esc(label)}</h3><div class="pw-input-grid">${ui.field('人工核对状态',ui.select({id:'pw-delivery-'+key+'-status','data-pw-delivery':key,'data-part':'status',value:row.status,options:[{value:'pending',label:'待核对'},{value:'confirmed',label:'已人工核对'},{value:'rejected',label:'需修改'}]}))}${ui.field('依据或记录位置',ui.input({id:'pw-delivery-'+key+'-source','data-pw-delivery':key,'data-part':'source_ref',value:row.source_ref,maxlength:500}))}</div>${ui.field('说明',ui.input({'data-pw-delivery':key,'data-part':'note',value:row.note,maxlength:1000}))}</section>`}).join('')}<p class="muted">人工核对记录不等于独立合规认证，也不触发平台发布。</p>`;
    dialog('商品交付审阅清单',body,btn('保存待核清单','delivery-save',false,{disabled:s.busy})+btn('确认本地交付审阅','delivery-confirm',true,{disabled:!deliveryEnabled()})+btn('读取当前版本并重新核对','delivery-reset')+btn('关闭','dialog-close'));
  }
  async function deliveryAction(action){
    if(s.busy)return;
    if(action==='delivery-checklist'){deliveryError='';deliveryNotice='';deliveryDialog();return}
    if(action==='delivery-reset'){const id=s.id,epoch=++deliveryEpoch,prior=structuredClone(deliveryEdit?.checks||{});s.busy=true;try{await reload();if(s.id===id&&deliveryEpoch===epoch){deliveryError='';deliveryNotice='已读取当前版本，文字已保留，请重新核对。';s.busy=false;render();deliveryEdit=null;deliveryDialog(true);for(const [key,row] of Object.entries(prior))if(deliveryEdit.checks[key])deliveryEdit.checks[key]={...row,status:'pending'};deliveryDialog()}}finally{if(s.id===id)s.busy=false}return}
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
    return `${summary}<div class="pw-overview-grid"><div>${researchView(true)}${supplyView(true)}${reviewSummary()}</div><div>${costSummary(true)}${contentView(true)}</div></div>`;
  }
  function render() {
    const host=document.getElementById('pw-product');if(!host)return;
    document.getElementById('pw-main').setAttribute('aria-busy',String(s.busy));
    if(!s.data){host.innerHTML=`<div class="pw-start"><h1>商品工作区</h1>${s.error?alert(s.error,'danger'):empty(s.busy?'正在读取商品工作项…':s.items.length?'选择一个已有商品，继续原工作。':'当前连接尚无商品工作项。')}${s.items.length?ui.field('商品工作项',ui.select({id:'pw-case',value:'',options:[{value:'',label:'选择已有商品'},...s.items.map(c=>({value:c.id,label:itemLabel(c)}))]})):''}${catalog.view()}<div class="pw-form-actions">${btn('重新读取','refresh')}${btn('打开完整后台','backend')}</div></div>`;return}
    if(s.catalogOpen){host.innerHTML=`<div class="pw-form-actions">${btn('返回当前商品','catalog-close')}</div>${catalog.view()}`;return}
    const focused=document.activeElement,focus=focused?.id,focusAction=focused?.dataset?.pwAction,start=focused?.selectionStart,end=focused?.selectionEnd;
    host.innerHTML=`${header()}${s.error?`<div class="pw-page-error">${alert(s.error,'danger')}<div class="pw-form-actions">${btn('核对当前版本','inspect-saved')}${btn('刷新资料','refresh')}</div><details><summary>技术详情</summary><code>${esc(s.errorCode)}</code></details></div>`:''}<div id="pw-tabpanel" role="tabpanel" aria-labelledby="pw-tab-${s.tab}" tabindex="0" class="pw-tabpanel">${({overview,research:researchView,cost:costView,content:contentView,review:reviewView,tasks:tasksView,media:()=>studio.view()})[s.tab]()}</div>`;
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
  function selectTab(tab) {if(!tabs[tab])return;s.tab=tab;if(tab==='media')studio.enter();if(!embedded&&innerWidth<1024&&s.mobile!=='product'){s.mobile='product';applyMobile()}if(!bridged){const url=new URL(location.href);url.searchParams.set('tab',tab);history.replaceState(null,'',url)}persistView(tab);render();document.getElementById('pw-tab-'+tab)?.focus({preventScroll:true});document.getElementById('pw-tab-'+tab)?.scrollIntoView({block:'nearest',inline:'nearest'})}
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
    if(action==='catalog'){s.catalogOpen=true;render();await catalog.enter();return}
    if(action==='catalog-close'){s.catalogOpen=false;render();return}
    if(action==='quotes'||action.startsWith('quote-'))return quoteAction(action,target);
    if(action.startsWith('delivery-'))return deliveryAction(action);
    if(action==='research-task'){const taskId=target.dataset.task;if(taskId){if(bridged)parent.postMessage({type:'commerce:workspace-research',nonce,task_id:taskId},'*');else location.assign('/workspace?tab=pilots&research_task_id='+encodeURIComponent(taskId))}return;}
    if(action.startsWith('tab-')){selectTab(action.slice(4));return}
    if(action==='dialog-close'){closeDialog();return}
    if(action==='dialog-proceed'){const callback=s.dialogAction;closeDialog();await callback?.();return}
    if(action==='mobile-chat'||action==='mobile-product'){s.mobile=action==='mobile-chat'?'chat':'product';applyMobile();return}
    if(action==='navigate'){const tab=target.dataset.tab;if(!navigation.some(item=>item[2]===tab))return;closeDialog();if(bridged)parent.postMessage({type:'commerce:workspace-navigate',nonce,tab},'*');else location.assign('/?tab='+encodeURIComponent(tab));return}
    if(action==='listing'){if(!s.data)return;if(reactHost)parent.postMessage({type:'commerce:workspace-navigate',nonce,tab:'listing'},'*');else location.assign('/workspace?tab=listing&case_id='+encodeURIComponent(s.id));return}
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
      if(action==='scenario-open-save'){dialog('保存成本情景',ui.field('情景名称',ui.input({id:'pw-scenario-label',maxlength:80,placeholder:'例如：当前报价、调整售价'}))+`<p class="pw-meta">固定当前已保存参数和依据，不更改当前报价或平台价格。</p>`,btn('保存情景','scenario-save',true,{'data-key':crypto.randomUUID()})+btn('取消','dialog-close'));}
      if(action==='scenario-save'){const label=document.getElementById('pw-scenario-label')?.value||'';await api('commerce_cost_scenarios_save',{case_id:s.id,label,expected_source_sha256:s.data.source_sha256,expected_revision:s.data.forms.cost.revision,idempotency_key:target.dataset.key});if(!current())return;closeDialog();announce('成本情景已保存；当前参数和报价保持。')}
      if(action==='scenario-compare'){const result=await api('commerce_cost_scenarios_get',{case_id:s.id});if(!current())return;dialog('成本情景对比',result.items.length?'<div class="pw-scenario-comparison">'+ui.table(['情景 / 依据','售价','单件总成本','单件贡献估算','贡献率'],result.items.map(row=>`<tr><td><strong>${esc(row.label)}</strong>${ui.badge(row.stale?'依据已变化':'当前依据',row.stale?'warning':'gray')}<details><summary>参数与版本</summary><p>成本修订 ${row.cost_revision}</p><dl>${Object.entries(row.input).map(([key,value])=>`<dt>${esc(fields[key]||key)}</dt><dd>${esc(value)}</dd>`).join('')}</dl><small>${esc(row.sha256)}</small></details></td><td>${amount(row.result.price,row.result.currency)}</td><td>${amount(row.result.total_cost,row.result.currency)}</td><td>${amount(row.result.contribution,row.result.currency)}</td><td>${decimal(row.result.contribution_rate*100)}%</td></tr>`))+'</div>'+`<p class="pw-meta">仅同币种情景可直接比较；依据变化的结果保留供复核，不作为当前测算。最多显示最近20项。</p>`:empty('尚无已保存情景。先保存完整成本参数，再保存情景。'))}
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
  document.addEventListener('submit',event=>{if(event.target.id==='pw-quote-compare-form'){event.preventDefault();act('quote-compare',event.target)}else if(event.target.id==='pw-cost-form'||event.target.id==='pw-content-form'){event.preventDefault();act(event.target.id==='pw-cost-form'?'save-calculate':'preview-content',event.target)}});
  document.addEventListener('input',event=>{
    const target=event.target;
    if(target.id==='pw-quote-quantity'){
      quoteComparison.quantity=target.value;quoteComparison.result=null;
      document.getElementById('pw-quote-compare-result')?.remove();
      const status=document.getElementById('pw-quote-compare-state');if(status)status.textContent='需求已修改，请重新比较。';
    }
    if(target.dataset.pwDelivery&&deliveryEdit?.caseId===s.id){const key=target.dataset.pwDelivery,part=target.dataset.part;if(Object.hasOwn(deliveryEdit.checks,key)&&['source_ref','note'].includes(part)){deliveryEdit.checks[key][part]=target.value;deliveryEdit.key=crypto.randomUUID();const confirm=document.querySelector('[data-pw-action="delivery-confirm"]');if(confirm)confirm.disabled=!deliveryEnabled()}}
    if(target.dataset.pwQuote&&quoteEdit?.caseId===s.id){const key=target.dataset.pwQuote;if(!Object.hasOwn(quoteLabels,key))return;const pack=['length_cm','width_cm','height_cm','weight_kg','units_per_pack'].includes(key),data=pack?(quoteEdit.fields.packaging||=( {})):quoteEdit.fields;if(target.value==='')delete data[key];else data[key]=['supplier','currency','source_ref','valid_until'].includes(key)?key==='currency'?target.value.toUpperCase():target.value:Number(target.value);quoteEdit.key=crypto.randomUUID()}
    if(target.dataset.pwCost){const f=structuredClone(formData('cost'));const key=target.dataset.pwCost;if(target.value==='')delete f.input[key];else f.input[key]=key==='currency'?target.value.toUpperCase():Number(target.value);s.edits.cost=f;dirty('cost')}
    if(target.dataset.pwContent){const f=structuredClone(formData('content')),key=target.dataset.pwContent;f.fields[key]=key==='quantity'?(target.value===''?null:Number(target.value)):key==='image_refs'?target.value.split('\n').filter(Boolean):target.value;s.edits.content=f;dirty('content')}
  });
  document.addEventListener('change',event=>{
    if(event.target.dataset.pwDelivery&&deliveryEdit?.caseId===s.id){const key=event.target.dataset.pwDelivery;if(Object.hasOwn(deliveryEdit.checks,key)&&event.target.dataset.part==='status'){deliveryEdit.checks[key].status=event.target.value;deliveryEdit.key=crypto.randomUUID();const confirm=document.querySelector('[data-pw-action="delivery-confirm"]');if(confirm)confirm.disabled=!deliveryEnabled()}return;}
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
  const initialLoad=reload();catalog.enter();
  if(bridged){const ready=()=>parent.postMessage({type:'commerce:workspace-ready',nonce},'*');if(reactHost)initialLoad.finally(ready);else ready()}
  if(!embedded)api('commerce_ui_get_preferences').then(value=>{ui.applyTheme(value.theme);document.getElementById('pw-theme').value=value.theme}).catch(()=>{});
})();
