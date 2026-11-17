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
  function table(headers,rows,emptyText='当前范围暂无记录。'){
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
  function restockSources(current){
    return `<nav class="form-actions restock-sources" aria-label="补货资料来源">${[{id:'generic',label:'通用参数',attrs:{'data-analysis-mode':'stock'}},{id:'live',label:'Ozon 库存快照',attrs:{'data-tab':'live'}},{id:'manual',label:'手工核对资料',attrs:{'data-tab':'alerts','data-restock-source':'manual'}}].map(item=>button({label:item.label,variant:current===item.id?'primary':'secondary',attrs:{...item.attrs,'aria-current':current===item.id?'page':undefined}})).join('')}</nav>`;
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
    const saved=Number(preferred),fallback=Math.min(360,Math.round((area-24)*.3/8)*8);
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
  return Object.freeze({version:'1.4.0',applyTheme,getTheme,chatLayout,observeReadingRegions,icon,escape,attributes,legacyAttributes,button,badge,input,select,field,empty,alert,card,table,evidence,fieldDiff,receipt,restockSources,tabs,navigationGroups,moduleDetails,moduleDirectory,modal,status:(code,capabilities)=>globalThis.CommerceStatus.describe(code,capabilities)});
})();

/* Attribute-only enhancement keeps React-owned cells and existing controls intact. */
(()=>{
  if(typeof MutationObserver==='undefined'||typeof ResizeObserver==='undefined'||!document.querySelectorAll)return;
  const selector='.ui-table,.table-wrap,.r-table-wrap',observed=new Set(),rows=new WeakMap(),previewAttrs=new WeakMap();
  const interactive='button,a,input,select,textarea,details,[contenteditable=true],[tabindex]';
  let pending=false,detail=null;
  const text=node=>{
    if(node.nodeType===3)return node.textContent;
    if(node.nodeType!==1||node.matches('svg,script,style,[hidden],[aria-hidden=true]'))return '';
    if(node.tagName==='INPUT')return node.type==='password'?'密码字段':node.value;
    if(node.tagName==='TEXTAREA')return node.value;
    if(node.tagName==='SELECT')return [...node.selectedOptions].map(o=>o.textContent).join('、');
    if(node.tagName==='BR')return '\n';
    const value=[...node.childNodes].map(text).join('');
    return /^(P|DIV|SMALL|PRE|DETAILS|SUMMARY)$/.test(node.tagName)?value+'\n':value;
  };
  const value=cell=>text(cell).replace(/[ \t]+/g,' ').replace(/\n{3,}/g,'\n\n').trim();
  function prepare(table){
    const headers=[...(table.tHead?.rows[table.tHead.rows.length-1]?.cells||[])].flatMap(c=>Array(c.colSpan||1).fill(c.textContent.trim()));
    if(!headers.length)return [];
    table.setAttribute('role','table');table.tHead.setAttribute('role','rowgroup');
    for(const row of table.tHead.rows){row.setAttribute('role','row');for(const cell of row.cells)cell.setAttribute('role','columnheader')}
    const cells=[],carried=[];let index=0;
    for(const body of table.tBodies){body.setAttribute('role','rowgroup');for(const row of body.rows){
      row.setAttribute('role','row');const fields=[];let column=0;
      for(let i=0;i<carried.length;i++)if(carried[i]?.until>index)fields.push(carried[i].field);
      for(const cell of row.cells){
        while(carried[column]?.until>index)column++;
        const label=headers.slice(column,column+(cell.colSpan||1)).join(' / ')||'信息';
        cell.dataset.uiTableLabel=label;cell.setAttribute('role','cell');
        const field={cell,label};fields.push(field);cells.push(cell);
        for(let i=0;i<(cell.colSpan||1);i++)carried[column+i]={until:index+(cell.rowSpan||1),field};
        column+=cell.colSpan||1;
      }
      rows.set(row,[...new Set(fields)]);index++;
    }}
    return cells;
  }
  function refresh(){
    pending=false;
    for(const wrapper of observed)if(!wrapper.isConnected){resize.unobserve(wrapper);observed.delete(wrapper)}
    for(const wrapper of document.querySelectorAll(selector)){
      const table=wrapper.querySelector(':scope>table');if(!table||!wrapper.getClientRects().length)continue;
      if(!observed.has(wrapper)){observed.add(wrapper);resize.observe(wrapper)}
      const cells=prepare(table);if(!table.tHead?.rows.length)continue;
      wrapper.removeAttribute('data-ui-table-mode');
      const compact=wrapper.clientWidth<600;
      if(compact)wrapper.dataset.uiTableMode='compact';
      for(const cell of cells){
        // Ignore our own tab stop when deciding whether a cell contains a business control.
        const controls=cell.querySelector(interactive);
        cell.toggleAttribute('data-ui-table-copy',!controls);
        const clipped=compact&&!controls&&cell.scrollWidth>cell.clientWidth+1;
        cell.toggleAttribute('data-ui-table-preview',clipped);
        if(clipped){
          if(!previewAttrs.has(cell))previewAttrs.set(cell,Object.fromEntries(['tabindex','title','aria-haspopup'].map(a=>[a,cell.getAttribute(a)])));
          if(!cell.hasAttribute('tabindex'))cell.tabIndex=0;
          cell.setAttribute('aria-haspopup','dialog');cell.setAttribute('title','点击或按回车查看完整信息');
        }else if(previewAttrs.has(cell)){
          for(const [key,old] of Object.entries(previewAttrs.get(cell)))if(old===null)cell.removeAttribute(key);else cell.setAttribute(key,old);
          previewAttrs.delete(cell);
        }
      }
    }
  }
  const queue=()=>{if(!pending){pending=true;requestAnimationFrame(refresh)}};
  const resize=new ResizeObserver(queue);
  function open(cell){
    if(detail)return;
    const opener=cell,table=cell.closest('table'),row=cell.closest('tr'),fields=rows.get(row)||[];
    const record=value(row.cells[0]),heading=table?.tHead?.textContent;
    const dialog=document.createElement('dialog');dialog.className='dialog ui-dialog ui-table-detail';
    dialog.setAttribute('aria-labelledby','ui-table-detail-title');
    dialog.innerHTML='<header class="dialog-head"><h2 id="ui-table-detail-title">完整信息</h2>'+window.CommerceUI.button({label:'关闭',attrs:{'data-ui-table-close':true,'aria-label':'关闭完整信息'}})+'</header>';
    const list=document.createElement('dl');list.className='ui-table-detail-fields';
    for(const field of fields){const item=document.createElement('div'),label=document.createElement('dt'),copy=document.createElement('dd');label.textContent=field.label;copy.textContent=value(field.cell)||'—';item.append(label,copy);list.append(item)}
    dialog.append(list);document.body.append(dialog);detail=dialog;
    const close=()=>{
      dialog.close();dialog.remove();detail=null;
      let target=opener;
      if(!target.isConnected){
        const replacement=[...document.querySelectorAll(selector)].map(w=>w.querySelector(':scope>table')).find(t=>t?.tHead?.textContent===heading);
        target=[...(replacement?.tBodies[0]?.rows||[])].find(r=>value(r.cells[0])===record)?.querySelector('[data-ui-table-preview]');
      }
      if(target?.isConnected){
        if(!target.hasAttribute('tabindex')){target.tabIndex=-1;target.addEventListener('blur',()=>target.removeAttribute('tabindex'),{once:true})}
        target.focus({preventScroll:true});
      }
    };
    dialog.querySelector('[data-ui-table-close]').addEventListener('click',event=>{event.stopPropagation();close()});
    dialog.addEventListener('cancel',event=>{event.preventDefault();event.stopPropagation();close()});
    dialog.addEventListener('keydown',event=>{
      if(event.key!=='Tab')return;
      const buttons=[...dialog.querySelectorAll('button')];
      if(buttons.length===1){event.preventDefault();buttons[0].focus()}
    });
    dialog.showModal();dialog.querySelector('button').focus();
  }
  document.addEventListener('click',event=>{
    const cell=event.target.closest?.('[data-ui-table-preview]');
    const control=event.target.closest?.(interactive);
    if(cell&&(!control||control===cell)){event.preventDefault();event.stopPropagation();open(cell)}
  },true);
  document.addEventListener('keydown',event=>{
    const cell=event.target.closest?.('[data-ui-table-preview]');
    if(cell&&event.target===cell&&['Enter',' '].includes(event.key)){event.preventDefault();event.stopPropagation();open(cell)}
  },true);
  const start=()=>{
    new MutationObserver(records=>{if(records.some(r=>(r.target.nodeType===1?r.target:r.target.parentElement)?.closest('table')||[...r.addedNodes,...r.removedNodes].some(n=>n.nodeType===1&&(n.matches('table')||n.querySelector('table')))))queue()}).observe(document.body,{childList:true,subtree:true,characterData:true});
    queue();
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

/* Read-only product labels; object identity always remains the exact case id. */
(() => {
  'use strict';
  const text=value=>typeof value==='string'?value.trim():'';
  const platforms={ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu',shopify:'Shopify',woocommerce:'WooCommerce'};
  function scope(item={}) {
    const value={...(item.scope||{}),...(item.case?.scope||{})};
    for(const key of ['platform','market','sku','fulfillment','inventory_type'])if(text(item[key])||Array.isArray(item[key]))value[key]=item[key];
    return value;
  }
  const id=item=>text(item.id||item.case?.id);
  function shortId(item,peers=[]) {
    const value=id(item),plain=value.replace(/^(?:case|candidate|product|item)[_-]/,'');
    if(!value)return '';
    for(let size=8;size<plain.length;size+=4){const suffix=plain.slice(-size);if(!peers.some(other=>id(other)!==value&&id(other).endsWith(suffix)))return suffix;}
    return plain;
  }
  function meta(item) {
    const s=scope(item),inventory=text(s.inventory_type),fulfillment=['fbs','rfbs','fbo'].includes(inventory.toLowerCase())?inventory:Array.isArray(s.fulfillment)?s.fulfillment.map(text).filter(Boolean).join(' / '):text(s.fulfillment);
    return [platforms[s.platform]||text(s.platform)||'平台待核对',text(s.market)||'市场待核对',fulfillment?fulfillment.toUpperCase():'履约未提供'].join(' · ');
  }
  function label(item,peers=[]) {
    const s=scope(item),sku=text(s.sku),name=text(item.name)||text(s.label)||sku||'未命名商品';
    const primary=name+(sku&&sku!==name?' / '+sku:'');
    const same=peers.some(other=>id(other)!==id(item)&&(text(other.name)||text(scope(other).label)||text(scope(other).sku)||'未命名商品')===name&&text(scope(other).sku)===sku&&meta(other)===meta(item));
    const candidate=item.candidate===true||item.kind==='candidate'||s.inventory_type==='candidate'||s.origin==='research_candidate_not_inventory';
    return [primary,meta(item),candidate?'调研候选':'',!sku||same?shortId(item,peers):''].filter(Boolean).join(' · ');
  }
  function merge(items,records) {
    const exact=new Map(records.map(record=>[id(record),record]));
    return items.map(item=>{const found=exact.get(id(item));return found?{...item,scope:{...scope(found),...scope(item)}}:item;});
  }
  window.CommerceProductIdentity={scope,meta,label,merge};
})();

/* Registered UI metadata and visible error feedback; no cookies or arbitrary form scraping. */
(() => {
  const labels={overview:'运营台',workspace:'商品工作区',listing:'上架准备',workflow:'工作流画布',orders:'订单','store-ops':'日常运营','order-imports':'订单导入',products:'库存',operations:'成本与定价',restock:'补货计划',models:'模型管理',memory:'资料与知识',intelligence:'全球情报',research:'研究资料',pilots:'商品候选',creative:'创意工作室',agent:'模型分析',tasks:'任务中心',organization:'岗位交接',exposure:'经营关联',platforms:'平台数据',live:'Ozon 经营',alerts:'经营提醒',support:'客服',insights:'选品与评论',skills:'技能','assistant-team':'智能体团队','operating-control':'自动经营',connections:'连接与授权',phones:'手机墙',tools:'工具发现'};
  const sections={evidence:'证据与选品',shipping:'装箱与运费',social:'社交观察',overview:'概览',research:'市场研究',media:'图片与视频',tasks:'任务中心','sales-trend':'销售趋势','inventory-statistics':'库存统计','order-status':'发货单状态','platform-sales':'平台销售构成','order-detail':'订单详情','product-detail':'商品详情',cost:'成本测算',stock:'补货测算',plan:'工作计划',content:'商品内容',creative:'图片与视频',review:'资料核对',sources:'资料来源',delivery:'交付核对',details:'详情',list:'列表',map:'地图'};
  const filterKeys=new Set(['platform','market','store_id','store_ref','query','status','source','country','category','hours','scope','view','time','date_from','date_to']);
  const inputKeys=new Set(['sku','title','description','category_id','currency','price','purchase_cost','domestic_shipping','packaging','fulfillment_cost','electronic_fee','commission_rate','payment_rate','return_rate','ad_rate','sold_units','window_days','observed_days','lead_time_days','safety_days','available','on_order','pack_size','moq','quantity','budget']);
  const clean=value=>{
    if(!value||typeof value!=='object'||!Object.hasOwn(labels,value.page))return null;
    const out={page:value.page,demo:value.demo===true};
    if(['live','local','unavailable','stale'].includes(value.source))out.source=value.source;
    if(typeof value.section==='string'&&/^[a-zA-Z0-9_-]{1,64}$/.test(value.section))out.section=value.section;
    if(value.entity&&['case','order','product','intel','task','chart','skill','model','aircraft','vessel'].includes(value.entity.kind)&&typeof value.entity.id==='string'&&/^[a-zA-Z0-9_.:/-]{1,180}$/.test(value.entity.id))out.entity={kind:value.entity.kind,id:value.entity.id,...(typeof value.entity.name==='string'?{name:value.entity.name.slice(0,120)}:{})};
    for(const [key,allowed,max]of [['filters',filterKeys,160],['input',inputKeys,20000]])if(value[key]&&typeof value[key]==='object'){
      const fields=Object.entries(value[key]).filter(([k,v])=>allowed.has(k)&&(!['platform','market','store_id','store_ref'].includes(k)||v!=='')&&(typeof v==='string'&&v.length<=max&&!/\n|bearer\s|sk-[a-z0-9]{16}|\/Users\//i.test(v)||key==='input'&&(typeof v==='number'&&Number.isFinite(v)||v===null)));
      if(fields.length)out[key]=Object.fromEntries(fields.map(([k,v])=>[k,key==='input'&&typeof v==='string'&&v.length>220?v.slice(0,220)+'…[已截断]':v]));
    }
    if(value.source_refs&&typeof value.source_refs==='object')out.source_refs=Object.fromEntries(Object.entries(value.source_refs).filter(([k,v])=>/^[a-z_]{1,40}$/.test(k)&&typeof v==='string'&&/^[a-f0-9]{64}$/.test(v)).slice(0,8));
    if(Array.isArray(value.errors))out.errors=value.errors.filter(v=>typeof v==='string'&&!/bearer\s|sk-[a-z0-9]{16}|\/Users\//i.test(v)).slice(0,3).map(v=>v.slice(0,300));
    return out;
  };
  const marker=element=>{try{return JSON.parse(element?.getAttribute?.('data-ai-context')||'{}')}catch{return {}}};
  const label=value=>{const location=[labels[value?.page],sections[value?.section]||value?.section,value?.entity?.kind==='chart'?'':value?.entity?.name||value?.entity?.id].filter(Boolean).join(' › ');const details=[value?.filters?.platform&&value.filters.platform!=='all'?value.filters.platform==='ozon'?'Ozon':value.filters.platform:'',value?.filters?.store_id&&value.filters.store_id!=='all'?value.filters.store_id:'',value?.filters?.scope&&value.filters.scope!=='all'?(value.filters.scope==='unassigned'?'未关联店铺':'店铺视图 #'+value.filters.scope.slice(-6)):'',!value?.filters?.store_id||value.filters.store_id==='all'?value?.filters?.store_ref||'':'',value?.filters?.market&&value.filters.market!=='all'?value.filters.market:'',value?.filters?.date_from&&value.filters.date_to?value.filters.date_from+' — '+value.filters.date_to:'',value?.demo?'示例数据':({live:'真实数据',local:'本机资料',unavailable:'暂无真实数据',stale:'真实快照已过期'}[value?.source]||'按本页来源')].filter(Boolean).join(' · ');return [location,details].filter(Boolean).join(' · ')};
  window.CommercePageContext={clean,label,create({getBase,root=()=>document.body,onChange=()=>{}}){
    let selected=null,last='',disposed=false,scheduled=false,observed=null,observer=null,inputTimer=null;
    function snapshot(){
      const base=getBase()||{},node=root(),pageMarker=[...(node?.querySelectorAll?.('[data-ai-page]')||[])].find(el=>el.getAttribute('data-ai-page')===base.page&&!el.closest?.('[hidden]'));
      if(selected&&(!selected.isConnected||node&&!node.contains(selected)&&!selected.closest?.('.dialog,.r-dialog')))selected=null;
      const page={...base,...marker(pageMarker)},selection=marker(selected);
      const searches=[...(node?.querySelectorAll?.('input[type="search"],input[id$="-query"],input[id$="-keyword"]')||[])].filter(el=>el.getClientRects?.().length);const search=searches.find(el=>el===document.activeElement)||searches[0];if(search&&typeof search.value==='string')page.filters={...page.filters,query:search.value.slice(0,160)};
      const feedback=[...(node?.querySelectorAll?.('[role="alert"],.alert.error')||[])].filter(el=>el.getClientRects?.().length&&!el.closest?.('#commerce-copilot')).map(el=>el.textContent?.trim()).filter(Boolean);if(feedback.length)page.errors=feedback;
      return clean({...page,...selection,page:base.page,demo:typeof page.demo==='boolean'?page.demo:base.demo,filters:selection.replace_filters?selection.filters:{...page.filters,...selection.filters},source_refs:selection.source_refs||page.source_refs});
    }
    function changed(){if(disposed)return;const node=root();if(node!==observed){observer?.disconnect();observed=node;if(node&&typeof MutationObserver!=='undefined'){observer=new MutationObserver(notify);observer.observe(node,{subtree:true,childList:true,attributes:true,attributeFilter:['data-ai-context','data-ai-page','hidden']})}}const value=snapshot(),signature=JSON.stringify(value);if(signature!==last){last=signature;onChange(value)}}
    function notify(){if(scheduled||disposed)return;scheduled=true;Promise.resolve().then(()=>{scheduled=false;changed()})}
    function select(event){const node=root(),target=event.target;if(!node||!target||target.closest?.('#commerce-copilot')||!node.contains(target)&&!target.closest?.('.dialog,.r-dialog'))return;const next=target.closest?.('[data-ai-context]');if(next)selected=next;if(event.type==='input'||event.type==='change'){/* Trusted events may flush microtasks before the framework's bubbling input handler. */if(inputTimer===null)inputTimer=setTimeout(()=>{inputTimer=null;notify()},0)}else notify()}
    for(const name of ['pointerdown','focusin','change','input'])document.addEventListener(name,select,true);
    changed();
    return {snapshot,changed,reset(){selected=null;last='';changed()},dispose(){disposed=true;if(inputTimer!==null)clearTimeout(inputTimer);observer?.disconnect();for(const name of ['pointerdown','focusin','change','input'])document.removeEventListener(name,select,true)}};
  }};
})();

/* Shared selected-file transport. An explicit retry resumes the same local receipt. */
;(function(target){
  const base64=bytes=>{let text='';for(const byte of bytes)text+=String.fromCharCode(byte);return btoa(text)};
  target.CommerceMaterialUpload={create({api,onProgress=()=>{},shouldContinue=()=>true}){
    let request=null,disposed=false;
    const check=req=>{if(req.cancelled)throw Error('copilot_upload_cancelled');if(disposed||!shouldContinue())throw Error('copilot_upload_scope_changed')};
    const progress=(req,status,received=0)=>{req.status=status;if(!disposed)onProgress({status,received,total:req.size,id:req.id,cancellable:!!req.id&&!req.finishing&&['uploading','unconfirmed'].includes(status)})};
    async function upload({thread,selected,caps}){
      const {filename,mime_type,bytes}=selected,large=bytes.length>(caps.max_file_bytes||65536);
      if(!bytes.length||bytes.length>(caps.chunked_upload_available?caps.max_chunked_file_bytes:caps.max_file_bytes||65536))throw Error('copilot_material_size_or_encoding');
      if(caps.chunked_upload_available){const preflight=await api('commerce_copilot_material_preflight',{filename,mime_type,size_bytes:bytes.length});if(!preflight.allowed)throw Error('copilot_material_extraction_unavailable')}
      let content,digest;
      if(large){if(!crypto.subtle)throw Error('copilot_material_hash_unavailable');digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),byte=>byte.toString(16).padStart(2,'0')).join('')}
      else content=base64(bytes);
      const fingerprint=JSON.stringify({thread:thread.id,scope:thread.context_sha256,filename,mime_type,content:digest||content});
      if(request?.fingerprint!==fingerprint){if(request?.id&&!request.cancelled)throw Error('copilot_upload_pending_selection');request={fingerprint,key:crypto.randomUUID(),size:bytes.length,bound:{thread_id:thread.id,context_sha256:thread.context_sha256},id:null,cancelled:false}}
      const req=request;check(req);
      try{
        let item;
        if(!large){progress(req,'saving');item=await api('commerce_copilot_material_upload',{...req.bound,filename,mime_type,content_base64:content,idempotency_key:req.key})}
        else{
          const receipt=await api('commerce_copilot_material_upload_begin',{...req.bound,filename,mime_type,size_bytes:bytes.length,content_sha256:digest,idempotency_key:req.key});
          req.id=receipt.id;check(req);
          if(!['uploading','completed'].includes(receipt.status))throw Error('copilot_upload_not_active');
          const size=receipt.chunk_bytes,index=receipt.next_index;
          if(!Number.isInteger(size)||size<1||size>49152||!Number.isInteger(index)||index<0||index>Math.ceil(bytes.length/size))throw Error('copilot_upload_invalid_receipt');
          if(receipt.status!=='completed')for(let i=index;i*size<bytes.length;i++){
            check(req);progress(req,'uploading',i*size);
            await api('commerce_copilot_material_upload_chunk',{...req.bound,upload_id:req.id,index:i,content_base64:base64(bytes.subarray(i*size,Math.min(bytes.length,(i+1)*size)))});
          }
          check(req);req.finishing=true;progress(req,'finishing',bytes.length);
          item=await api('commerce_copilot_material_upload_finish',{...req.bound,upload_id:req.id});
        }
        progress(req,'completed',bytes.length);if(request===req)request=null;return item;
      }catch(error){if((error.code||error.message)==='copilot_upload_expired'&&request===req)request=null;progress(req,req.cancelConfirmed?'cancelled':'unconfirmed');if(req.cancelConfirmed)throw Error('copilot_upload_cancelled');throw error}
    }
    return {upload,async cancel(){const req=request;if(!req?.id||req.finishing||!['uploading','unconfirmed'].includes(req.status))throw Error('copilot_upload_not_cancellable');req.cancelled=true;try{const result=await api('commerce_copilot_material_upload_cancel',{...req.bound,upload_id:req.id});req.cancelConfirmed=true;if(request===req)request=null;progress(req,'cancelled');return result;}catch(error){progress(req,'unconfirmed');throw error}},dispose(){disposed=true}};
  }};
})(typeof window==='undefined'?globalThis:window);

/* A bounded DOM window over the original complete, paginated conversation. */
;(function(target){
  function create(size=40){
    size=Math.max(2,Math.min(80,size));
    let identity=null,first=null,following=true,start=0;
    const turnKey=turn=>turn.id||turn.run?.id||turn.question;
    function range(thread,reading){
      const turns=thread?.turns||[];
      if(identity!==thread?.id){identity=thread?.id;first=null;following=true;start=0}
      const last=Math.max(0,turns.length-size);
      if(following)start=last;
      else{const index=turns.findIndex(turn=>turnKey(turn)===first);start=index<0?Math.min(start,last):Math.min(index,last)}
      if(reading?.anchor&&!reading.bottom){const index=turns.findIndex(turn=>'turn:'+turnKey(turn)===reading.anchor||'run:'+turn.run?.id===reading.anchor);if(index>=0&&index<start){start=index;following=false}}
      first=turns[start]?turnKey(turns[start]):null;
      const end=Math.min(turns.length,start+size);
      return {turns:turns.slice(start,end),before:start,after:turns.length-end,total:turns.length,start,end};
    }
    return {range,move(thread,direction){range(thread);start=Math.max(0,Math.min(Math.max(0,thread.turns.length-size),start+Math.sign(direction)*size));following=start>=thread.turns.length-size;first=thread.turns[start]?turnKey(thread.turns[start]):null;return range(thread)},latest(thread){identity=thread?.id;following=true;first=null;return range(thread)}};
  }
  function capture(log){
    const selection=log?.ownerDocument?.getSelection?.();
    if(!selection||selection.isCollapsed||!log.contains(selection.anchorNode)||!log.contains(selection.focusNode))return null;
    const point=(node,offset)=>{const element=(node.nodeType===1?node:node.parentElement)?.closest('[data-message-key]');if(!element||!log.contains(element))return null;const range=log.ownerDocument.createRange();range.selectNodeContents(element);range.setEnd(node,offset);return {key:element.dataset.messageKey,offset:range.toString().length}};
    const anchor=point(selection.anchorNode,selection.anchorOffset),focus=point(selection.focusNode,selection.focusOffset);
    return anchor&&focus?{anchor,focus}:null;
  }
  function restore(log,saved){
    if(!log||!saved)return;
    const point=saved=>{const element=[...log.querySelectorAll('[data-message-key]')].find(el=>el.dataset.messageKey===saved.key);if(!element)return null;const walker=log.ownerDocument.createTreeWalker(element,4);let offset=saved.offset,node;while((node=walker.nextNode())){if(offset<=node.textContent.length)return {node,offset};offset-=node.textContent.length}return null};
    const a=point(saved.anchor),b=point(saved.focus);if(a&&b)log.ownerDocument.getSelection()?.setBaseAndExtent(a.node,a.offset,b.node,b.offset);
  }
  target.CommerceCopilotReading={create,capture,restore};
})(typeof window==='undefined'?globalThis:window);

/* AG-UI events over the original durable run. Detaching only stops observation. */
;(function(target){
  const active=new Set(['queued','running','cancel_requested']);
  const messages=thread=>(thread.turns||[]).flatMap(turn=>[
    {id:'q-'+turn.id,role:'user',content:turn.question},
    ...(turn.run.result?.answer?[{id:'a-'+turn.run.id,role:'assistant',content:turn.run.result.answer}]:[])
  ]);
  target.CommerceRunEvents={observe({api,thread,runId,pollMs=500,eventThreadId=thread?.id,eventRunId=runId,onEvent=()=>{},onComplete=()=>{},onError=()=>{}}){
    let detached=false,timer=null,wake=null;
    const emit=event=>{if(!detached)onEvent(event)};
    const delay=()=>new Promise(resolve=>{wake=resolve;timer=setTimeout(()=>{timer=null;wake=null;resolve()},Math.max(1,pollMs))});
    let finalThread;
    const execute=async()=>{
      if(!thread?.id||!runId)throw Error('missing_run_receipt');
      const id='a-'+runId,base=messages(thread).filter(message=>message.id!==id);
      let cursor=0,partial='',started=false;
      const deadline=Date.now()+10*60*1000;
      emit({type:'RUN_STARTED',threadId:eventThreadId,runId:eventRunId});
      while(!detached){
        if(Date.now()>deadline)throw Error('request_outcome_unknown');
        const value=await api('commerce_copilot_events',{thread_id:thread.id,run_id:runId,after:cursor});
        if(detached)return;
        const snapshot=value.snapshot;
        if(!snapshot||!Number.isSafeInteger(value.cursor)||value.cursor<0||typeof snapshot.answer!=='string'||!Array.isArray(snapshot.components))throw Error('invalid_run_events');
        cursor=value.cursor;
        emit({type:'STATE_SNAPSHOT',snapshot:{backend_thread_id:thread.id,backend_run_id:runId,status:value.status,cursor,provisional:snapshot.provisional,stream_mode:snapshot.mode,stream_answer:snapshot.answer,stream_truncated:snapshot.truncated===true,generative_components:snapshot.components}});
        if(!active.has(value.status))break;
        const text=snapshot.answer;
        if(text!==partial){
          if(!started&&text){emit({type:'TEXT_MESSAGE_START',messageId:id,role:'assistant'});started=true}
          if(text.startsWith(partial))emit({type:'TEXT_MESSAGE_CONTENT',messageId:id,delta:text.slice(partial.length)});
          else emit({type:'MESSAGES_SNAPSHOT',messages:[...base,...(text?[{id,role:'assistant',content:text}]:[])]});
          partial=text;
        }
        await delay();
      }
      if(detached)return;
      finalThread=await api('commerce_copilot_get',{thread_id:thread.id});
      if(detached)return;
      const run=finalThread.latest_run?.id===runId?finalThread.latest_run:finalThread.turns?.find(turn=>turn.run.id===runId)?.run;
      if(!run)throw Error('run_changed');
      emit({type:'STATE_SNAPSHOT',snapshot:{backend_thread_id:thread.id,backend_run_id:runId,status:run.status,provisional:false,generative_surface:run.presentation}});
      if(!run.result?.answer&&!['completed','review','needs_input','awaiting_input','awaiting_review'].includes(run.status)){
        emit({type:'MESSAGES_SNAPSHOT',messages:base});
        throw Error(run.error||'agent_run_'+run.status);
      }
      const answer=run.result?.answer||'本轮需要补充资料，请查看原任务。';
      if(!started)emit({type:'TEXT_MESSAGE_START',messageId:id,role:'assistant'});
      if(answer.startsWith(partial))emit({type:'TEXT_MESSAGE_CONTENT',messageId:id,delta:answer.slice(partial.length)});
      else emit({type:'MESSAGES_SNAPSHOT',messages:[...base,{id,role:'assistant',content:answer}]});
      emit({type:'TEXT_MESSAGE_END',messageId:id});
      emit({type:'RUN_FINISHED',threadId:eventThreadId,runId:eventRunId});
      if(!detached)onComplete(finalThread);
    };
    void execute().catch(error=>{if(!detached){emit({type:'RUN_ERROR',message:error.message||'run_observation_failed'});onError(error,finalThread)}});
    return ()=>{detached=true;if(timer!==null)clearTimeout(timer);timer=null;wake?.();wake=null};
  }};
})(typeof window==='undefined'?globalThis:window);

/* Readable, escaped projections of the shared assistant's retained evidence. */
window.CommerceAssistantEvidence=(()=>{
  const date=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'';
  function link(value){try{const u=new URL(value);if(!['http:','https:'].includes(u.protocol)||u.username||u.password||!u.hostname.includes('.')||/^(?:127\.|10\.|192\.168\.|169\.254\.)/.test(u.hostname)||u.hostname.endsWith('.local'))return '';return u.href}catch{return ''}}
  const error=code=>({web_provider_timeout:'检索超时，可重试',web_search_not_configured:'检索服务尚未配置',web_provider_unavailable:'检索来源暂不可用',web_http_403:'来源拒绝公开读取',web_http_404:'原文已不可访问',web_page_unavailable:'原文暂时无法读取',web_page_body_unavailable:'来源页面未提供可读取的正文',web_dns_unavailable:'来源网络解析失败',web_private_address_rejected:'该地址不属于可读取的公开来源'})[code]||'该来源暂未读取成功';
  function item(row,esc){
    const url=link(row.url),title=row.title||row.name||'公开来源',stamp=row.published_beijing||date(row.published_at??row.published);
    const publication=row.publication_status==='future_timestamp'?'来源时间晚于当前，待核对':row.publication_status==='outside_window'?'不在所选日期':stamp?'发布于 '+stamp:'发布时间待核对';
    const content=(row.content_status==='search_summary_only'?'搜索摘要':row.content_status==='page_text'?'正文已读取':row.content_status==='json_data'?'公开数据已读取':'')+(row.text_truncated?' · 内容已限量':'');
    return `<li class="copilot-source-item"><div>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>`:`<strong>${esc(title)}</strong>`}</div><small>${esc([row.publisher||row.source,publication,content].filter(Boolean).join(' · '))}</small>${row.status==='failed'?`<p role="status">${esc(error(row.error))}</p>`:row.summary||row.text?`<p>${esc((row.summary||row.text).slice(0,320))}${(row.summary||row.text).length>320?'…':''}</p>`:''}${row.source_sha256?`<details><summary>来源版本</summary><code>${esc(row.source_sha256)}</code></details>`:''}</li>`;
  }
  function render(observation,esc){
    const data=observation.data||{},refs=(observation.references||[observation.id]).join('、'),tag=`<small class="copilot-source-ref">${esc(refs)}</small>`;
    if(observation.tool==='commerce_web_search')return `<section class="copilot-public-sources"><header><strong>公开网络检索</strong>${tag}</header><p class="muted">${data.cached?'缓存读取 · ':'检索于 '}${esc(date(data.retrieved_at))} · ${esc(data.window?.date_beijing||'')} · 来源陈述待核实</p>${(data.groups||[]).map(group=>`<section><h4>${esc(group.label||'公开网络')} · ${group.items?.length||0} 条</h4>${group.status==='failed'?`<p role="status">${esc(error(group.error))}</p>`:!group.items?.length?'<p>本次检索未返回匹配结果。</p>':`<ul>${group.items.map(row=>item(row,esc)).join('')}</ul>`}${group.truncated?'<small>展示已限量，原检索范围保留。</small>':''}</section>`).join('')}</section>`;
    if(observation.tool==='commerce_web_read')return `<section class="copilot-public-sources"><header><strong>原文读取</strong>${tag}</header><ul>${(data.items||[]).map(row=>item(row,esc)).join('')}</ul></section>`;
    if(observation.tool==='commerce_intel_search')return `<section class="copilot-local-sources"><header><strong>本机资料 · ${esc(data.total??data.items?.length??0)} 条匹配</strong>${tag}</header>${data.items?.length?`<ul>${data.items.map(row=>item(row,esc)).join('')}</ul>`:'<p>仅检索已采集资料；无匹配不代表公开网络没有相关信息。</p>'}</section>`;
    if(observation.tool==='commerce_intel_item_get')return `<section class="copilot-public-sources"><header><strong>所选情报来源</strong>${tag}</header><ul>${item(data,esc)}</ul></section>`;
    if(observation.tool==='commerce_intel_live_get')return `<section class="copilot-local-sources"><header><strong>监测位置与行情快照</strong>${tag}</header>${Object.entries(data.sources||{}).map(([key,source])=>`<p><strong>${esc(({flights:'航空器',vessels:'船舶',markets:'行情'})[key]||key)}</strong> · 匹配 ${esc(source.matched??0)} 条 · 快照内有效 ${esc(source.fresh_count??0)} 条${source.availability==='expired'?' · 样本已过期':''}<br><small>${esc(source.provider||'')} · 观测 ${esc(source.observed_at_beijing||date(source.observed_at)||'未知')}${source.truncated?' · 明细已限量':''}</small></p>`).join('')}</section>`;
    if(observation.tool==='commerce_current_page')return `<section class="copilot-local-sources"><header><strong>提问时的页面范围</strong>${tag}</header><p>${esc([data.label,data.section_label,data.selection?.name].filter(Boolean).join(' · '))}</p></section>`;
    if(observation.tool==='commerce_live_status')return `<section class="copilot-local-sources"><header><strong>店铺数据状态</strong>${tag}</header><p>订单快照 ${esc(data.orders?.count??0)} 条${data.orders?.fresh?'':' · 待更新'}；库存快照 ${esc(data.stock?.count??0)} 条${data.stock?.fresh?'':' · 待更新'}。</p></section>`;
    return null;
  }
  function group(observations){const rows=[],seen=new Map();for(const observation of observations){const key=observation.sha256?observation.tool+':'+observation.sha256:observation.id;if(seen.has(key)){seen.get(key).references.push(observation.id);continue}const row={...observation,references:[observation.id]};rows.push(row);seen.set(key,row)}return rows}
  function progress(run){const trace=run.trace||[];for(let i=trace.length-1;i>=0;i--){if(trace[i].event==='read_tool')return '正在整理已读取资料…';if(trace[i].event==='tool_started')return ({commerce_web_search:'正在检索公开网络…',commerce_web_read:'正在读取来源原文…',commerce_intel_search:'正在检索本机资料…'})[trace[i].tool]||'正在读取任务所需资料…'}return '正在理解问题并选择处理方式…'}
  function prose(value,esc){
    const inline=value=>esc(value).replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
    let list=false;const rows=[];
    for(const line of String(value||'').split('\n')){
      const bullet=line.match(/^\s*[-*]\s+(.+)$/);
      if(bullet){if(!list){rows.push('<ul>');list=true}rows.push('<li>'+inline(bullet[1])+'</li>');continue}
      if(list){rows.push('</ul>');list=false}
      if(line.trim())rows.push(/^#{1,4}\s+/.test(line)?'<p><strong>'+inline(line.replace(/^#{1,4}\s+/,''))+'</strong></p>':'<p>'+inline(line)+'</p>');
    }
    if(list)rows.push('</ul>');return rows.join('');
  }
  function reportArchive(result,esc){return `<section class="copilot-saved-report"><div class="copilot-formatted">${prose(result.analysis||result.content||'',esc)}</div>${result.source_questions?.length?`<h4>原分析待补充</h4>${result.source_questions.map(q=>`<p>${esc(q)}</p>`).join('')}`:''}${result.source_links?.length?`<h4>原始来源</h4><ul>${result.source_links.map(row=>item(row,esc)).join('')}</ul>`:''}</section>`}
  function archive(result,esc){
    const local=result.model==='windowed_stock_cover'||result.model==='explicit_unit_contribution';
    if(local&&window.CommerceUI?.table){
      const value=(x,unit='')=>typeof x==='number'&&Number.isFinite(x)?String(x)+(unit?' '+unit:''):'未知';
      const restock=result.model==='windowed_stock_cover',currency=result.currency||'';
      const metrics=restock?[['销量速度',value(result.velocity,'件/天')],['库存覆盖',value(result.days_of_cover,'天')],['目标库存',value(result.target_units,'件')],['建议补货',value(result.suggested_qty,'件')]]:
        [['单件总成本',value(result.total_cost,currency)],['单件贡献',value(result.contribution,currency)],['贡献率',value(result.contribution_rate==null?null:result.contribution_rate*100,'%')]];
      const table=window.CommerceUI.table(['指标','本次测算'],metrics.map(([label,n])=>`<tr><td>${esc(label)}</td><td>${esc(n)}</td></tr>`));
      return `<section class="copilot-saved-report"><h3>${restock?'补货测算':'单件贡献测算'}</h3>${table}<p class="muted">${restock?'按所给销量窗口外推，未创建采购单、未修改库存；不保证未来需求。':'按所给币种和费用假设测算，不是真实利润或结算。'}</p>${result.missing?.length?'<p>测算资料仍有缺项，请返回原输入核对，不能把未知记为零。</p>':''}</section>`;
    }
    if(typeof result.analysis==='string'||typeof result.content==='string')return reportArchive(result,esc);
    return null;
  }
  function reviewStatus(run){
    if(run.status!=='awaiting_review'||!run.result?.proposals?.length)return null;
    const actions=run.actions||[],rows=run.result.proposals.map(p=>actions.find(a=>a.proposal_id===p.id));
    if(rows.some(row=>!row?.task_id))return null;
    const receipts=rows.map(row=>row.receipt||{});
    if(receipts.some(r=>r.outcome==='unknown'||!['succeeded','failed','pending'].includes(r.outcome)))return '任务结果待核对';
    if(receipts.some(r=>r.outcome==='failed'))return '本地任务失败';
    if(receipts.every(r=>r.outcome==='succeeded'&&r.status==='completed'&&r.result_sha256))return '本地任务已完成';
    return '本地任务处理中';
  }
  return {render,group,progress,archive,prose,reviewStatus};
})();

/* Pure reading helpers. Controlled Markdown subset; no raw HTML or media loading. */
((target)=>{
  const MAX_TEXT=5000;
  const plainText=value=>typeof value==='string'?value:typeof value==='number'||typeof value==='boolean'?String(value):'';
  const escape=value=>value.replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function linkURL(value){
    if(!/^https?:\/\//i.test(value)||/[\s\\<>\x00-\x1f\x7f]/.test(value))return null;
    try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&url.hostname&&!url.username&&!url.password?url.href:null}catch{return null}
  }
  function inline(text,depth=0,links=true){
    if(depth>3)return escape(text);
    let html='',index=0;
    while(index<text.length){
      const char=text[index];
      if(char==='\\'&&/[\\`*_\[\]{}()#!+\-.|]/.test(text[index+1]||'')){html+=escape(text[index+1]);index+=2;continue}
      if(char==='`'){
        const marker=text.slice(index).match(/^`+/)[0],end=text.indexOf(marker,index+marker.length);
        if(end>=0){html+='<code>'+escape(text.slice(index+marker.length,end))+'</code>';index=end+marker.length;continue}
      }
      const image=char==='!'&&text[index+1]==='[';
      if(links&&(char==='['||image)){
        const start=index+(image?2:1),middle=text.indexOf('](',start),end=middle<0?-1:text.indexOf(')',middle+2);
        if(end>=0){
          const url=linkURL(text.slice(middle+2,end));
          if(url){html+='<a href="'+escape(url)+'" target="_blank" rel="noopener noreferrer">'+(image?'图片：':'')+inline(text.slice(start,middle),depth+1,false)+'</a>';index=end+1;continue}
          // Consume an unsafe image/link as literal data; do not reinterpret a
          // nested label as a second opportunity to create an active anchor.
          html+=escape(text.slice(index,end+1));index=end+1;continue;
        }
      }
      if(char==='*'||char==='_'){
        const marker=text.startsWith(char+char,index)?char+char:char,end=text.indexOf(marker,index+marker.length);
        const insideWord=char==='_'&&/[\p{L}\p{N}]/u.test(text[index-1]||'');
        if(!insideWord&&end>index+marker.length){const tag=marker.length===2?'strong':'em';html+='<'+tag+'>'+inline(text.slice(index+marker.length,end),depth+1,links)+'</'+tag+'>';index=end+marker.length;continue}
      }
      html+=char==='\n'?'<br>':escape(char);index++;
    }
    return html;
  }
  function cells(line){
    const values=[];let value='',code='',index=0;
    while(index<line.length){
      const char=line[index];
      if(char==='\\'&&line[index+1]==='|'){value+='\\|';index+=2;continue}
      if(char==='`'){const marker=line.slice(index).match(/^`+/)[0];if(!code)code=marker;else if(code===marker)code='';value+=marker;index+=marker.length;continue}
      if(char==='|'&&!code){values.push(value.trim());value=''}else value+=char;
      index++;
    }
    values.push(value.trim());
    if(values[0]===''&&line.trimStart().startsWith('|'))values.shift();
    if(values.at(-1)===''&&line.trimEnd().endsWith('|'))values.pop();
    return values;
  }
  function tableAt(lines,index){
    if(!lines[index]?.includes('|')||!lines[index+1]?.includes('|'))return null;
    const header=cells(lines[index]),rules=cells(lines[index+1]);
    if(!header.length||header.length>12||header.length!==rules.length||!rules.every(rule=>/^:?-{3,}:?$/.test(rule)))return null;
    return {header,align:rules.map(rule=>rule.startsWith(':')&&rule.endsWith(':')?'center':rule.startsWith(':')?'left':rule.endsWith(':')?'right':'')};
  }
  const fence=line=>line.match(/^ {0,3}(`{3,}|~{3,})([a-zA-Z0-9_-]{0,32})\s*$/);
  const heading=line=>line.match(/^ {0,3}(#{1,6})[ \t]+(.+)$/);
  const listItem=line=>line.match(/^ {0,3}([-+*]|\d{1,6}[.)])[ \t]+(.+)$/);
  const ordered=item=>/^\d/.test(item[1]);
  function markdown(value){
    const source=plainText(value);if(!source)return '';
    let text=source.slice(0,MAX_TEXT);if(/[\uD800-\uDBFF]$/.test(text))text=text.slice(0,-1);
    const clipped=text.length<source.length,lines=text.replace(/\r\n?/g,'\n').split('\n');let html='',index=0;
    while(index<lines.length){
      const line=lines[index];if(!line.trim()){index++;continue}
      const code=fence(line);
      if(code){
        const content=[],marker=code[1];index++;
        const closing=new RegExp('^ {0,3}'+(marker[0]==='`'?'`':'~')+'{'+marker.length+',}\\s*$');
        while(index<lines.length&&!closing.test(lines[index]))content.push(lines[index++]);
        if(index<lines.length)index++;
        html+='<pre><code'+(code[2]?' class="language-'+escape(code[2])+'"':'')+'>'+escape(content.join('\n'))+'</code></pre>';continue;
      }
      const title=heading(line);
      if(title){html+='<h'+title[1].length+'>'+inline(title[2])+'</h'+title[1].length+'>';index++;continue}
      const table=tableAt(lines,index);
      if(table){
        const attr=column=>table.align[column]?' style="text-align:'+table.align[column]+'"':'';
        html+='<div class="copilot-markdown-table"><table><thead><tr>'+table.header.map((cell,column)=>'<th'+attr(column)+'>'+inline(cell)+'</th>').join('')+'</tr></thead><tbody>';index+=2;
        while(index<lines.length&&lines[index].trim()&&lines[index].includes('|')){
          const row=cells(lines[index]);if(row.length!==table.header.length)break;
          html+='<tr>'+row.map((cell,column)=>'<td'+attr(column)+'>'+inline(cell)+'</td>').join('')+'</tr>';index++;
        }
        html+='</tbody></table></div>';continue;
      }
      const item=listItem(line);
      if(item){
        const isOrdered=ordered(item),tag=isOrdered?'ol':'ul',start=isOrdered?parseInt(item[1],10):1;
        html+='<'+tag+(isOrdered&&start!==1?' start="'+start+'"':'')+'>';
        while(index<lines.length){const next=listItem(lines[index]);if(!next||ordered(next)!==isOrdered)break;html+='<li>'+inline(next[2])+'</li>';index++}
        html+='</'+tag+'>';continue;
      }
      const paragraph=[line];index++;
      while(index<lines.length&&lines[index].trim()&&!fence(lines[index])&&!heading(lines[index])&&!listItem(lines[index])&&!tableAt(lines,index))paragraph.push(lines[index++]);
      html+='<p>'+inline(paragraph.join('\n'))+'</p>';
    }
    return html+(clipped?'<p class="copilot-truncated">内容较长，仅展示前 5000 个字符。</p>':'');
  }
  function suggestions(context={},page={}){
    context=context&&typeof context==='object'?context:{};page=page&&typeof page==='object'?page:typeof page==='string'?{page}:{};
    const route=page.page||context.module||'',section=page.section||'';
    // An explicit visible page wins over a previous chat's selected object.
    const entity=page.entity||(!page.page||page.page===context.module?context.entity:null)||{};let rows;
    if(['operations','restock'].includes(route)||['cost','stock'].includes(section))rows=[
      ['核对测算口径','根据当前已填参数，解释成本或补货测算的口径，区分已知值、假设与未知项。'],
      ['找出缺失参数','检查当前测算还缺哪些实际参数，以及缺失参数会影响哪些结论。'],
      ['分析关键边界','根据当前已有数据，说明价格、费用或库存变化对测算结果的影响；缺少依据时保留未知。']];
    else if(route==='phones')rows=[['核对设备连接','解释当前设备连接、只读预览和控制租约状态；没有设备时列出缺少的接入条件。'],['排查预览问题','根据当前页面已有回执排查设备预览问题，缺少的连接信息保持未知。'],['说明控制状态','解释当前设备的控制权限、租约和停止方式；不要未经明确授权控制设备。']];
    else if(['intelligence','news'].includes(route))rows=[
      [entity.kind==='intel'?'解读这条情报':'解读当前情报',entity.kind==='intel'?'根据当前选中的情报与已有原文，概括主要事件、时间和仍待核实的信息。':'概括当前情报页面的主要事件，保留来源、时间和未核实状态。'],
      ['核对来源与时效','核对当前情报的来源、发布时间与本机采集时间，指出过期、缺证或互相矛盾的信息。'],
      ['分析潜在影响','根据当前情报与明确的业务范围，区分已观察事实和可能影响；没有经营关联依据时不要推断。']];
    else if(route==='overview')rows=[
      ['解读当前概览','结合当前筛选范围，解释经营概览与趋势，区分实际数据、示例数据和未知项。'],
      ['排查经营异常','根据当前概览，找出值得优先核对的经营异常，并说明还需要哪些证据。'],
      ['梳理待办优先级','根据当前经营概览与已有提醒，按影响和依据整理需要人工核对的下一步。']];
    else if(['orders','store-ops','order-imports','support'].includes(route))rows=[
      ['梳理订单状态',`根据${entity.kind==='order'?'这笔订单':'当前订单范围'}的已有数据，解释订单状态、时间与尚未确认的信息。`],
      ['核对异常原因','核对当前订单范围内的异常迹象，区分已知原因和需要补充的证据。'],
      ['整理处理建议','根据当前订单资料整理可审阅的处理建议，并标明需要人工确认的条件。']];
    else if(route==='products'||entity.kind==='product')rows=[
      ['分析当前库存','根据当前商品与库存口径，说明可售情况、预警和缺少的依据。'],
      ['核对商品资料','检查当前商品资料的一致性，区分已确认事实和待补充字段。'],
      ['梳理商品下一步','根据当前商品的资料和状态，整理下一步核对事项及所需输入。']];
    else if(route==='creative')rows=[
      ['梳理创意方向','根据当前创意项目与已提供素材，整理适合的表达方向和需要补充的素材。'],
      ['核对商品主张','核对当前创意内容里的商品主张，标出缺少商品事实支持的表述。'],
      ['整理制作清单','根据当前创意项目整理文案、图片与视频制作清单，保留未完成和未验证项。']];
    else if(['tasks','agent'].includes(route)||entity.kind==='task')rows=[
      ['解释当前进度','根据当前任务的真实状态与回执，解释已完成、等待中和结果未知的部分。'],
      ['核对阻塞原因','根据当前任务记录解释阻塞或失败原因，区分已观察原因和未验证推断。'],
      ['整理恢复条件','根据当前任务状态列出恢复所需的输入与确认条件，保留原任务和已有结果。']];
    else if(route==='listing'||section==='content')rows=[
      ['核对商品内容','根据当前商品事实核对内容草稿，指出不一致或缺少依据的字段。'],
      ['整理上架缺项','根据当前上架准备状态整理尚缺的资料与核对条件，不把草稿视为已发布。'],
      ['检查资料一致性','检查当前商品事实、内容与目标范围的一致性，并说明未验证项。']];
    else if(['research','pilots','insights'].includes(route))rows=[
      ['核对研究依据','核对当前研究或候选的来源、时间与证据强度，区分观察、推断和待核实信息。'],
      ['比较候选差异','根据当前已有资料比较候选差异；资料不足时说明缺口，不估造市场数据。'],
      ['列出验证清单','根据当前研究结论整理后续需要验证的问题、来源和必要输入。']];
    else if(entity.kind==='case'||['workspace','organization','workflow'].includes(route))rows=[
      ['梳理当前工作项','根据当前工作项的资料与状态，整理已完成事项和当前主线。'],
      ['核对资料缺项','检查当前工作项的资料缺项与版本一致性，说明哪些结论仍需核实。'],
      ['整理交接事项','根据当前工作项的缺项和责任范围，整理可审阅的交接事项及所需输入。']];
    else if(['models','connections','platforms','live','memory'].includes(route))rows=[
      ['核对可用能力','根据当前页面的实际连接与可用状态，区分已配置、已连接和已验证的能力。'],
      ['解释当前状态','解释当前连接或资料状态及其影响；缺少回执时保留未知。'],
      ['梳理配置缺项','根据当前页面整理需要补充的配置或资料，不包含密钥、令牌或密码。']];
    else rows=[
      ['解释当前页面','根据当前页面与明确范围，解释已有资料、状态和需要关注的信息。'],
      ['核对缺失信息','根据当前页面，说明还缺哪些信息，以及它们会影响哪些判断。'],
      ['整理下一步','根据当前已有依据整理需要人工核对的下一步，并保留未知与未验证项。']];
    return rows;
  }
  target.CommerceCopilotInteractions=Object.freeze({markdown,suggestions,plainText});
})(typeof window==='object'?window:globalThis);

/* Typed business views shared by browser/iframe; data is always escaped. */
(function(){
  // Transient display state only. Business images and version checks stay in
  // the original backend; repaint never loses a preview of the same version.
  const images=new Map();let imageBytes=0;
  const imageKey=a=>JSON.stringify([a.case_id,a.platform,a.store_ref,a.market,a.expected_binding_sha256,a.index]);
  function rememberImage(args,url){
    const key=imageKey(args);if(images.has(key)){imageBytes-=images.get(key).length;images.delete(key)}
    images.set(key,url);imageBytes+=url.length;
    while(images.size>12||imageBytes>16*1024*1024){const first=images.keys().next().value;imageBytes-=images.get(first).length;images.delete(first)}
  }
  const kinds=new Set(['Evidence','QuoteComparison','DeliveryReview','ListingReview','SkillReadiness','CostSummary','FieldDiff','Questions','ProposalReview','Receipt']);
  const labels={HOLD:'待补资料',BLOCKED:'受阻',PASS:'检查通过',FAIL:'检查不符',READY_FOR_SELECTION:'可审阅选择',EXPIRED:'已过期',needs_inputs:'待补资料',needs_mode:'待选模式',blocked:'受阻',source_unavailable:'来源不可用',draft_inputs_ready:'草稿输入齐备',local_check_available:'可请求本机检查',stale:'来源已变化',ready_for_local_review:'待本地审阅',local_review_recorded:'已记录本地审阅',review_expired_or_superseded:'审阅已过期或被替代',rejected:'已退回'};
  function render(surface,options={}){
    const ui=options.ui||window.CommerceUI;
    if(!ui||surface?.schema!=='commerce-generative-surface-v1'||surface.catalog_version!==1||!Array.isArray(surface.components)||surface.components.length>12)return null;
    const esc=ui.escape,value=v=>v==null||v===''?'待补充':typeof v==='object'?JSON.stringify(v):String(v),covered={answer:false,questions:new Set(),proposals:new Set()},seen=new Set();
    const pairs=(rows,prefix='')=>`<dl>${rows.map(([key,label,v])=>`<div data-field-id="${esc(prefix+key)}"><dt>${esc(label)}</dt><dd>${esc(value(v))}</dd></div>`).join('')}</dl>`;
    const list=items=>items?.length?`<ul>${items.slice(0,30).map(v=>`<li>${esc(value(v))}</li>`).join('')}</ul>${items.length>30?'<p class="muted">展示前30项，完整内容请核对原记录。</p>':''}`:'<p class="muted">暂无记录</p>';
    let html='';
    for(const c of surface.components){
      if(!c||!kinds.has(c.component)||typeof c.id!=='string'||!/^[a-zA-Z0-9_-]{1,100}$/.test(c.id)||seen.has(c.id)||!c.data||typeof c.data!=='object')return null;
      seen.add(c.id);const d=c.data,b=c.binding||{};let body='';
      if(c.component==='Evidence')body=options.evidence?.(c.observation)||ui.evidence({title:c.label,quote:value(d),sha256:b.observation_sha256,verification:'not_independently_verified'});
      else if(c.component==='QuoteComparison'){
        const rows=d.items||d.quotes?.items||[];
        body=rows.length?`<div class="ui-table-wrap" role="region" tabindex="0" aria-label="供应报价对照">${ui.table(['报价 / 版本','币种','单价','起订量','下单件数','商品小计','状态'],rows.slice(0,20).map(q=>{
          const f=q.fields||q,id='supply_quote:'+q.quote_id+':';
          return `<tr><th scope="row">${esc(value(q.supplier||q.quote_id))} · ${esc(value(q.revision))}</th><td>${esc(value(f.currency))}</td><td data-field-id="${esc(id+'unit_price')}">${esc(value(q.unit_price??f.purchase_cost))}</td><td>${esc(value(f.moq))}</td><td data-field-id="${esc(id+'order_units')}">${esc(q.order_units==null?'待明确数量':String(q.order_units)+(q.extra_units>0?'（多'+q.extra_units+'件）':''))}</td><td>${esc(value(q.goods_subtotal))}</td><td>${esc(labels[q.status]||q.status||'未知')}</td></tr>`;
        }))}</div>`:'<p>当前商品没有已记录报价。</p>';
        body+=d.quantity?`<p>比较需求：${esc(d.quantity)} 件，按起订量与整包数量向上取整。小计仅含报价商品；运费、税费及平台费用另行核对。</p>`:'<p class="muted">未提供明确采购数量，未推算订单件数或总价。</p>';
        if(rows.length>20||d.quotes?.truncated)body+='<p class="muted">报价已限量，完整列表请在对应商品工作区核对。</p>';
      }else if(c.component==='DeliveryReview'){
        const v=d.delivery_review||d;
        const checks={facts:'产品事实',translation:'目标语言与翻译',media_rights:'素材使用权',platform_rules:'平台规则与资质依据',images:'产品图片',content:'上架内容',draft:'内容草稿',cost:'成本测算',source:'产品来源'};
        body=pairs([['status','交付状态',labels[v.status]||'待核对'],['professional_gate','负责人核查门禁',labels[v.professional_gate]||'待核对'],['package_sha256','交付包版本',v.package_sha256]],'delivery:')+list([...(v.automatic_missing||[]),...(v.pending_checks||[])].map(k=>checks[k]||'待核对检查项'))+`<small class="muted">检查结果与经营负责人签收分别记录；不代表独立认证或已上架。</small>`;
      }else if(c.component==='ListingReview'){
        const p=d.product||{},target=d.target||{};
        body=pairs([['sku','SKU',p.sku],['title','商品标题',p.title],['price','售价',p.price==null||p.price===''?null:value(p.price)+' '+value(p.currency)],['quantity','计划数量',p.quantity],['category_id','目标类目',p.category_id],['image_count','产品图片',p.image_count==null?null:p.image_count+' 张']], 'listing:')+`<p class="copilot-prose">${esc(p.description||'产品描述待补充')}</p>`;
        if(p.description_truncated)body+='<p class="muted">长描述已限量，完整内容请在原方案核对。</p>';
        if(p.attributes?.length)body+=pairs(p.attributes.map((a,i)=>[String(i),a.name,a.value]),'listing:attribute:');
        if(p.publication)body+=pairs([['depth','包装深度',p.publication.depth],['width','包装宽度',p.publication.width],['height','包装高度',p.publication.height],['dimension_unit','尺寸单位',p.publication.dimension_unit],['weight','含包装重量',p.publication.weight],['weight_unit','重量单位',p.publication.weight_unit],['vat','适用税率',p.publication.vat]],'listing:publication:');
        body+=list((d.checks||[]).filter(x=>x.status!=='prepared').map(x=>x.label||x.id));
        const image=d.image_binding;
        if(image&&!surface.provisional){
          for(let index=0;index<Math.min(20,image.count);index++){
            const args={...image.target,expected_binding_sha256:image.expected_binding_sha256,index},url=images.get(imageKey(args));
            body+=`<div class="copilot-product-image"><button type="button" class="ui-button" data-generative-image="${esc(JSON.stringify(args))}">${url?'重新读取':'读取产品'}图片 ${index+1}</button><div role="status">${url?`<img src="${esc(url)}" alt="当前保存方案产品图片 ${index+1}" style="max-width:100%;max-height:280px">`:''}</div></div>`;
          }
        }else body+=`<p class="muted">${surface.provisional?'生成预览，尚未开放操作。':'图片内容请在准确保存方案的完整审阅页核对。'}</p>`;
        body+=`<small class="muted">${esc([target.platform,target.store_ref,target.market].filter(Boolean).join(' / '))} · 修订 ${esc(value(d.revision))}${d.stale?' · 来源已变化':''}。本卡片不批准或发布商品。</small>`;
      }else if(c.component==='SkillReadiness'){
        const fields={facts_with_source:'带来源的产品事实','scope.marketplace':'目标平台','scope.market':'目标市场',input:'技能输入',mode_id:'执行模式',references:'参考资料'};
        body=pairs([['state','当前条件',labels[d.state]||d.state],['source_intact','来源完整性',d.source_intact===true?'匹配':'待核对'],['account_entitlement','账号权限','未验证'],['offline_check','本机检查',d.offline_check?.can_request?'可明确请求检查':'条件未齐备'],['model_runtime','模型运行条件',d.model_draft?.runtime_status==='not_checked'?'未核对':'以原技能检查为准'],['authorization','外部执行授权',d.external_execution?.authorized===true?'以宿主逐项校验为准':'未授权']], 'skill:')+list([...(d.missing_fields||[]).map(k=>fields[k]||k),...(d.issues||[])]);
        if(d.external_prerequisites?.length)body+='<h4>外部前置条件</h4>'+list(d.external_prerequisites);
        body+='<p class="muted">输入齐备与可执行分开核对；未请求模型、外部工具或付费任务。</p>';
      }else if(c.component==='CostSummary'){
        const v=d.calculation||d;
        const names=d.cost_field_labels||{},rate=typeof v.contribution_rate==='number'?String(Math.round(v.contribution_rate*10000)/100)+'%':null;
        body=pairs([['status','测算状态',v.status==='CALCULATED'?'已测算，待核对':v.status==='HOLD'?'资料不足':'待核对'],['price',names.price||'单件售价',v.price],['total_cost','单件总成本',v.total_cost],['contribution','单件贡献',v.contribution],['contribution_rate','贡献率',rate],['currency',names.currency||'测算币种',v.currency]],'unit_economics:');
        if(v.cost_breakdown)body+=pairs(Object.entries(v.cost_breakdown).map(([key,amount])=>['cost_breakdown.'+key,({commission:'平台佣金',payment:'支付费用',return:'退货预留',ad:'广告费用'})[key]||names[key]||'费用分项',amount]),'unit_economics:');
        if(v.missing?.length)body+=list(v.missing.map(k=>names[k]||'待补参数'));
        if(v.stale)body+='<p>来源已变化，请在成本工作区重新测算。</p>';
        body+='<p class="muted">金额使用所列币种，缺失参数未补猜；该测算不代表结算或会计结果。</p>';
      }else if(c.component==='FieldDiff'){
        const before=d.data?.input||{};body=ui.fieldDiff({beforeLabel:'已读取值',afterLabel:'页面输入（未核实）',rows:Object.entries(d.ui_input||{}).slice(0,32).map(([key,after])=>({key,label:key,before:before[key],after}))})+list(d.ui_errors||[]);
      }else if(c.component==='Questions'){
        body=list(d.items);if(!surface.provisional){(d.items||[]).forEach(q=>covered.questions.add(q));body+=options.reply?.()||'';}
      }else if(c.component==='ProposalReview'){
        if(surface.provisional)body='<p>建议生成中，待最终校验后逐项审阅。</p>';
        else{body=(d.items||[]).map(p=>options.proposal?.(p)||`<p>${esc(p.reason||p.operation)}</p>`).join('');if(options.proposal)(d.items||[]).forEach(p=>covered.proposals.add(p.id));}
      }else if(c.component==='Receipt')body=(d.items||[]).length?(d.items||[]).map(a=>options.receipt?.(a)||ui.receipt(a.receipt)).join(''):'<p>尚无已提交的本地任务回执。</p>';
      if(!surface.provisional&&options.workspace&&(d.case_id||d.target?.case_id))body+=options.workspace(c);
      html+=`<section class="copilot-card copilot-generative-card" data-component-id="${esc(c.id)}" data-component-kind="${esc(c.component)}"><h3>${esc(c.label)}</h3>${body}<small class="muted">引用 ${esc(b.reference||'')} · ${surface.provisional?'生成预览，未完成校验':'本轮读取快照'}</small></section>`;
    }
    return {html,covered,captions:[]};
  }
  async function image(event,api){
    const button=event.target.closest?.('[data-generative-image]');if(!button||button.disabled)return false;
    const box=button.parentElement,feedback=box.querySelector('[role="status"]');button.disabled=true;feedback.textContent='正在读取准确版本图片…';
    try{
      const args=JSON.parse(button.dataset.generativeImage),data=await api('commerce_owner_review_image',args);
      if(!/^image\/(png|jpeg|webp)$/.test(data.mime)||typeof data.content_base64!=='string'||!/^[A-Za-z0-9+/=]+$/.test(data.content_base64)||data.content_base64.length>12000000)throw Error('invalid_image');
      const picture=button.ownerDocument.createElement('img');picture.src='data:'+data.mime+';base64,'+data.content_base64;rememberImage(args,picture.src);picture.alt='当前保存方案产品图片 '+(args.index+1);picture.style.maxWidth='100%';picture.style.maxHeight='280px';feedback.replaceChildren(picture);button.textContent='重新读取图片 '+(args.index+1);
    }catch{feedback.textContent='图片未读到，可能版本已变化；请刷新原方案后重试。';}
    finally{button.disabled=false;}
    return true;
  }
  window.CommerceGenerativeUI={render,image,components:[...kinds]};
})();

/* Shared picker. The parent owns conversation scope and actual sending. */
window.CommerceCopilotCapabilities=({api,ui=window.CommerceUI,getContext,isActive=()=>true,isComposing=()=>false,repaint=()=>{},onModule=()=>{},onChange=()=>{}})=>{
  const esc=ui.escape||ui.esc||((value)=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])));
  const canonical=value=>JSON.stringify(value,(_,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item);
  const context=()=>JSON.parse(JSON.stringify(getContext?.()||{}));
  const key=()=>canonical(context()),cache=new Map();
  let scopeKey=key(),open=false,tab='modules',query='',catalog=null,selection=null,ids=[],error='',loading=false,checking=false,request=0,checkRequest=0,disposed=false,timer=null,pending=null,detailsId=null,manualMode=null;
  let queries={modules:'',skills:'',tools:''};
  let composing=false,compositionScope=null,pendingPaint=false,pendingFocus=null;
  const tabs=[['modules','业务模块'],['skills','技能'],['tools','工具与连接']];
  const stateLabels={available:'可用',registered:'可用工具',source_registered:'参考技能',reference_available:'流程参考',host_only:'在宿主使用',needs_setup:'待连接',disabled:'未启用',source_unavailable:'原文未读到'};
  function layout(){
    const panel=document.getElementById('copilot-capability-panel'),trigger=document.getElementById('copilot-capability-trigger');if(!panel||!trigger)return;
    const anchor=trigger.getBoundingClientRect(),composer=trigger.closest('.copilot-composer')?.getBoundingClientRect(),width=Math.min(420,composer?.width||420,window.innerWidth-24),above=anchor.top-16,below=window.innerHeight-anchor.bottom-16;
    const height=Math.max(96,Math.min(540,above>=220?above:below));panel.style.width=width+'px';panel.style.maxHeight=height+'px';panel.style.left=Math.max(12,Math.min(anchor.left,window.innerWidth-width-12))+'px';
    if(above>=220){panel.style.bottom=Math.max(8,window.innerHeight-anchor.top+8)+'px';panel.style.top='auto'}else{panel.style.top=(anchor.bottom+8)+'px';panel.style.bottom='auto'}
  }
  function paint(focus){if(disposed)return;if(composing||isComposing()){pendingPaint=true;if(focus)pendingFocus=focus;return}pendingPaint=false;pendingFocus=null;repaint();const input=document.getElementById('copilot-capability-query');if(input&&input.value!==query)input.value=query;layout();if(focus)document.getElementById(focus)?.focus({preventScroll:true})}
  function dismiss(focus=false){open=false;composing=false;compositionScope=null;pendingPaint=false;pendingFocus=null;document.getElementById('copilot-capability-panel')?.remove();const trigger=document.getElementById('copilot-capability-trigger');trigger?.setAttribute('aria-expanded','false');if(focus)trigger?.focus({preventScroll:true})}
  function changed(){cache.set(scopeKey,{ids:[...ids],selection});onChange(selection);paint()}
  function contextChanged(){
    const next=key();if(next===scopeKey)return;
    cache.set(scopeKey,{ids:[...ids],selection});scopeKey=next;const saved=cache.get(next);ids=[...(saved?.ids||[])];selection=saved?.selection||null;
    request++;checkRequest++;clearTimeout(timer);open=false;query='';queries={modules:'',skills:'',tools:''};detailsId=null;catalog=null;error='';loading=false;checking=false;pending=null;composing=false;compositionScope=null;pendingPaint=false;pendingFocus=null;
  }
  async function load(more=false){
    contextChanged();const seq=++request,scope=scopeKey;loading=true;error='';paint();
    try{const value=await api('commerce_copilot_capabilities',{context:context(),query,offset:more?catalog?.next_offset||0:0,limit:30});
      if(disposed||seq!==request||scope!==key())return;
      if(value.schema!=='commerce-copilot-capabilities-v1'||!Array.isArray(value.modules)||!Array.isArray(value.items))throw Error('目录响应不完整');
      catalog=more&&catalog?{...value,items:[...new Map([...catalog.items,...value.items].map(item=>[item.id,item])).values()]}:value;
    }catch(failure){if(seq===request&&scope===key())error='能力目录未读到，请重试。'}finally{if(seq===request&&scope===key()){loading=false;paint()}}
  }
  async function check(){
    const seq=++checkRequest,scope=scopeKey,chosen=[...ids];checking=true;error='';paint();
    const work=(async()=>{try{const value=await api('commerce_copilot_capability_check',{context:context(),capability_ids:chosen});
      if(disposed||seq!==checkRequest||scope!==key())return;
      if(!Array.isArray(value.capability_ids)||typeof value.selection_sha256!=='string')throw Error('选择回执不完整');
      selection=value;if(!value.available)error='部分能力暂不可用，请移除或重新核对。';changed();
    }catch(failure){if(seq===checkRequest&&scope===key()){selection=null;error='能力条件未确认，请重试核对。'}}finally{if(seq===checkRequest&&scope===key()){checking=false;paint()}}})();
    pending=work;await work;
  }
  function restore(value){contextChanged();checkRequest++;checking=false;pending=null;ids=[...(value?.capability_ids||[])];selection=value||null;error='';cache.set(scopeKey,{ids:[...ids],selection});paint()}
  async function prepare(){
    contextChanged();if(pending)await pending;if(!ids.length)return {};
    if(!selection?.available||!selection.selection_sha256)throw Error('请先核对所选能力的可用条件。');
    return {capability_ids:[...selection.capability_ids],expected_capability_sha256:selection.selection_sha256};
  }
  // Rich labels below contain only fixed icons/markup and escaped registry text.
  const button=(html,action,attrs={})=>ui.button({label:'',attrs:{'data-copilot-capability-action':action,...attrs}}).replace('</button>',html+'</button>');
  const moduleIcons={overview:'grid',orders:'doc',products:'box',operations:'chart',alerts:'bell',support:'headset',analytics:'chart',research:'book',intelligence:'book',creative:'image',pilots:'store',agent:'code',exposure:'link',organization:'box',tasks:'doc',platforms:'store',live:'link',skills:'code',connections:'link'};
  const choiceId=id=>'copilot-capability-choice-'+encodeURIComponent(id);
  const descriptionFor=item=>!item.selectable?({needs_setup:'在宿主中连接后可用',disabled:'能力尚未启用，请在能力与连接中检查。',source_unavailable:'技能原文未读到，请重新核对。'}[item.status]||'当前条件未满足，暂不能选入。'):({pinned_method_reference:'作为本轮参考方法，发送前核对原文版本。',host_preference_only:'保存本轮制作偏好，实际操作仍在已连接的宿主中继续。',registered_method_reference:'带入已登记的流程参考，执行仍需核对原有条件。',existing_public_reads:'可检索公开资料、读取来源正文；检索结果仍需核实。',scoped_read_tools:'读取当前业务范围内的数据，不扩大执行权限。'}[item.selection_effect]||'选中后随下一条问题带入，执行前仍核对可用条件。');
  function view({manualModule=null}={}){
    contextChanged();manualMode=manualModule;
    const module=context().module,modules=catalog?.modules||[],names=new Map([...(catalog?.items||[]),...(selection?.capabilities||[])].map(item=>[item.id,item.name]));
    const moduleName=id=>modules.find(item=>item.id===id)?.label||ui.moduleDetails?.(id)?.description||id;
    const selected=ids.map(id=>`<span class="copilot-capability-chip"><span title="${esc(names.get(id)||id)}">${esc(names.get(id)||id)}</span>${button('×','remove',{'data-capability-id':id,'aria-label':'移除'+(names.get(id)||id)})}</span>`).join('');
    const state=checking?'正在核对':ids.length&&!selection?.available?'待核对':'';
    let body='';
    if(tab==='modules'){
      body=query?'':button(`${ui.icon('panelLeft')}<span class="copilot-capability-copy"><strong>跟随当前页面</strong><small>按当前所在页面继续</small></span><span class="copilot-capability-check" aria-hidden="true">${manualModule?'':'✓'}</span>`,'module',{'data-module':'','data-capability-choice':true,'aria-pressed':!manualModule,class:'copilot-capability-follow',id:choiceId('follow')});
      body+=`<div class="copilot-capability-modules">${modules.map(item=>button(`${ui.icon(moduleIcons[item.id]||'grid')}<span title="${esc(item.label)}">${esc(item.label)}</span>${item.id===manualModule?'<span class="copilot-capability-check" aria-hidden="true">✓</span>':''}`,'module',{'data-module':item.id,'data-capability-choice':true,'aria-pressed':item.id===manualModule,title:item.label,class:'copilot-capability-module',id:choiceId(item.id)})).join('')}</div>`;
      if(!loading&&catalog&&!modules.length)body+='<p class="copilot-capability-empty">没有匹配的业务模块。</p>';
    }else{
      const rows=(catalog?.items||[]).filter(item=>tab==='skills'?item.kind==='skill':item.kind!=='skill');
      body=rows.map(item=>`<div class="copilot-capability-item">${button(`<span class="copilot-capability-copy"><strong title="${esc(item.name)}">${esc(item.name)}</strong><small title="${esc(item.description)}">${esc(item.description)}</small></span><span class="copilot-capability-condition">${esc(stateLabels[item.status]||'待核对')}</span><span class="copilot-capability-check" aria-hidden="true">${ids.includes(item.id)?'✓':''}</span>`,'select',{'data-capability-id':item.id,'data-capability-choice':true,'aria-label':item.name+'，'+(stateLabels[item.status]||'待核对'),'aria-pressed':ids.includes(item.id),disabled:!item.selectable||loading,class:'copilot-capability-row',id:choiceId(item.id)})}${button(ui.icon('info'),'details',{'data-capability-id':item.id,'aria-label':'查看说明：'+item.name,'aria-expanded':detailsId===item.id,title:'查看完整名称、说明与使用条件',class:'copilot-capability-info'})}${detailsId===item.id?`<section class="copilot-capability-detail" aria-label="${esc(item.name)}说明"><strong>${esc(item.name)}</strong><p>${esc(item.description)}</p><p>${esc(descriptionFor(item))}</p></section>`:''}</div>`).join('')||(!loading&&catalog?'<p class="copilot-capability-empty">没有匹配的'+(tab==='skills'?'技能':'工具或连接')+'。</p>':'');
    }
    const mode=manualModule?'固定模块 · '+moduleName(manualModule):'跟随当前页 · '+moduleName(module);
    const placeholders={modules:'搜索业务模块',skills:'搜索技能名称或用途',tools:'搜索工具、插件或 MCP'};
    return `<div class="copilot-capability-picker">${button(`${ui.icon('grid')}<span>功能与工具</span>${ids.length?`<span class="copilot-capability-count">${ids.length}</span>`:''}${ui.icon('chevronDown')}`,'toggle',{id:'copilot-capability-trigger','aria-label':'功能与工具，已选 '+ids.length+' 项'+(state?'，'+state:''),'aria-haspopup':'dialog','aria-expanded':open,'aria-controls':'copilot-capability-panel',class:'copilot-capability-trigger'})}${open?`<section id="copilot-capability-panel" class="copilot-capability-panel" role="dialog" aria-label="选择功能与工具"><header><strong>功能与工具</strong>${button('×','close',{'aria-label':'关闭功能与工具',class:'copilot-capability-close'})}</header><div class="copilot-capability-mode"><span title="${esc(mode)}">${esc(mode)}</span>${manualModule?button('恢复跟随','module',{'data-module':''}):''}</div><div role="tablist" aria-label="功能类型">${tabs.map(([id,label])=>button(label,'tab',{'data-tab':id,id:'copilot-capability-tab-'+id,role:'tab','aria-selected':tab===id,'aria-controls':'copilot-capability-results',tabindex:tab===id?0:-1})).join('')}</div><label class="copilot-capability-search"><span class="sr-only">搜索功能或工具</span>${ui.icon('search')}<input id="copilot-capability-query" type="search" value="${esc(query)}" placeholder="${placeholders[tab]}" aria-label="搜索功能或工具" autocomplete="off"/></label>${selected?`<div class="copilot-capability-tags" aria-label="本轮所选能力">${selected}</div>`:''}${error?`<p role="alert" class="copilot-capability-error"><span>${esc(error)}</span>${button('重新核对','recheck')}</p>`:''}<div id="copilot-capability-results" class="copilot-capability-results" role="tabpanel" aria-labelledby="copilot-capability-tab-${tab}" aria-busy="${loading||checking}">${loading&&!catalog?'<p class="copilot-capability-empty" role="status">正在读取可用选项…</p>':body}${catalog?.next_offset!==null&&catalog?.next_offset!==undefined&&tab!=='modules'?button(loading?'正在读取…':'加载更多','more',{disabled:loading,class:'copilot-capability-more'}):''}</div><footer><span role="status">${checking?'正在核对…':'已选 '+ids.length+' / 6'+(state?' · '+state:'')}</span><div>${ids.length?button('清空','clear'):''}${button('完成','close',{'aria-label':'完成选择功能与工具'})}</div></footer></section>`:''}</div>`;
  }
  async function handleClick(event){
    if(disposed||!isActive())return false;const target=event.target.closest?.('[data-copilot-capability-action]');
    if(!target){if(open&&!event.target.closest?.('.copilot-capability-picker'))dismiss();return false}
    event.preventDefault?.();event.stopImmediatePropagation?.();const action=target.dataset.copilotCapabilityAction;
    if(action==='toggle'){open=!open;paint(open?'copilot-capability-query':null);if(open)await load()}
    else if(action==='close')dismiss(true);
    else if(action==='tab'){if(!tabs.some(([id])=>id===target.dataset.tab))return true;const previousQuery=query;queries[tab]=query;tab=target.dataset.tab;query=queries[tab];detailsId=null;clearTimeout(timer);if(query!==previousQuery||!catalog){catalog=null;await load()}paint('copilot-capability-tab-'+tab)}
    else if(action==='module'){const next=target.dataset.module||null;if(next===manualMode){dismiss(true);return true}open=false;await onModule(next);contextChanged();paint('copilot-capability-trigger')}
    else if(action==='details'){detailsId=detailsId===target.dataset.capabilityId?null:target.dataset.capabilityId;paint()}
    else if(action==='clear'){checkRequest++;ids=[];selection=null;checking=false;pending=null;error='';changed()}
    else if(action==='select'||action==='remove'){
      const id=target.dataset.capabilityId,row=catalog?.items.find(item=>item.id===id);if(action==='select'&&!row?.selectable)return true;
      if(ids.includes(id))ids=ids.filter(value=>value!==id);else if(ids.length<6)ids.push(id);else{error='每轮最多选择 6 项能力。';paint();return true}
      selection=null;await check();
    }else if(action==='more')await load(true);else if(action==='recheck'){await load();if(ids.length)await check()}
    return true;
  }
  function commitQuery(value){query=value.slice(0,100);queries[tab]=query;detailsId=null;request++;clearTimeout(timer);timer=setTimeout(()=>{void load()},180)}
  function handleInput(event){if(event.target.id!=='copilot-capability-query')return false;if(event.isComposing||composing||isComposing())return true;commitQuery(event.target.value);return true}
  function keydown(event){
    if(!open)return false;
    if(event.isComposing||event.keyCode===229||composing||isComposing())return false;
    if(event.key==='Escape'){event.preventDefault();dismiss(true);return true}
    const target=event.target.closest?.('[role="tab"]');if(target&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const index=tabs.findIndex(([id])=>id===tab),next=tabs[event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length][0];void handleClick({target:{closest:()=>({dataset:{copilotCapabilityAction:'tab',tab:next}})}});return true}
    if(event.isComposing||event.keyCode===229)return false;
    const choice=event.target.closest?.('[data-capability-choice]'),search=event.target.id==='copilot-capability-query';
    if((choice||search)&&['ArrowUp','ArrowDown','Home','End'].includes(event.key)&&(!search||['ArrowUp','ArrowDown'].includes(event.key))){event.preventDefault();const panel=document.getElementById('copilot-capability-panel'),rows=[...(panel?.querySelectorAll('[data-capability-choice]:not(:disabled)')||[])].filter(el=>el.getClientRects().length),at=rows.indexOf(choice),to=event.key==='Home'?0:event.key==='End'?rows.length-1:at<0?(event.key==='ArrowUp'?rows.length-1:0):Math.max(0,Math.min(rows.length-1,at+(event.key==='ArrowDown'?1:-1)));rows[to]?.focus({preventScroll:true});rows[to]?.scrollIntoView?.({block:'nearest'});return true}
    return false;
  }
  window.addEventListener?.('resize',layout);
  const compositionStart=event=>{if(event.target.id==='copilot-capability-query'){composing=true;compositionScope=scopeKey;}};
  const compositionEnd=event=>{if(event.target.id!=='copilot-capability-query')return;const owner=compositionScope;composing=false;compositionScope=null;if(owner!==scopeKey)return;commitQuery(event.target.value);if(pendingPaint){pendingPaint=false;const focus=pendingFocus;pendingFocus=null;paint(focus)}};
  document.addEventListener?.('compositionstart',compositionStart);
  document.addEventListener?.('compositionend',compositionEnd);
  function dispose(){disposed=true;request++;checkRequest++;clearTimeout(timer);window.removeEventListener?.('resize',layout);document.removeEventListener?.('compositionstart',compositionStart);document.removeEventListener?.('compositionend',compositionEnd)}
  return {view,handleClick,handleInput,keydown,prepare,restore,contextChanged,afterPaint:layout,dispose};
};

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
window.CommerceCopilot=({api,ui=window.CommerceUI,toast,modal,closeModal,getContext,getPageContext=null,isActive=()=>true,repaint,inline=false,renderContext=()=>'',scopeLabel=null,errorText=null,compact=false,onWorkspace=null,onResearch=null,onOpenCandidate=null,onModels=null})=>{
  const esc=ui.escape,active=new Set(['queued','running','cancel_requested']);
  const status={queued:'排队中',running:'正在分析',awaiting_input:'等待补充',awaiting_review:'等待审阅',completed:'已返回',failed:'未完成',unknown:'结果未知',interrupted:'已中断',cancelled:'已取消',cancel_requested:'请求停止中'};
  const s={open:false,thread:null,threads:[],drafts:{},busy:false,error:'',focus:null,opener:null,load:0,review:null,fields:{},answers:{},form:false,newThread:false,modelMenu:false,modelCatalogReady:false,history:false,historyQuery:'',historyFilter:'current',historyLoading:false,historyError:'',historyLoad:0};
  let capabilityPicker=null,materialUploader=null;s.manualModule=null;s.materialSelections={};s.features={};s.modelQuery='';s.sendKey='mod-enter';try{s.sendKey=localStorage.getItem('commerce-copilot-send-key-v1')==='enter'?'enter':'mod-enter'}catch{}
  const readingWindow=window.CommerceCopilotReading?.create(40);
  const reading=window.CommerceCopilotInteractions,readAnswer=text=>reading?.markdown(text)||esc(text);
  let disposed=false;let composerHeight=0,composerDrag=null;try{composerHeight=Math.max(0,Math.min(480,Number(localStorage.getItem('commerce-copilot-composer-height-v1'))||0))}catch{}
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
  const baseContext=()=>clone(getContext?.()||{}),current=()=>{const base=baseContext();return base.store_scope?base:s.manualModule?{module:s.manualModule,demo:!!base.demo,...Object.fromEntries(['platform','market','store_id'].filter(k=>base[k]).map(k=>[k,base[k]]))}:base},changed=()=>s.thread&&!(s.scopeOverride?.thread===s.thread.id&&s.scopeOverride.page===canonical(current())&&canonical(s.scopeOverride.context)===canonical(s.thread.context))&&canonical(s.thread.context)!==canonical(current());
  const replyingOriginal=()=>!!(s.replyScope&&s.thread&&s.replyScope.thread===s.thread.id&&s.replyScope.hash===s.thread.context_sha256&&s.replyScope.page===canonical(current())&&(!getPageContext||s.replyScope.location===canonical(pageSnapshot())));
  const pageSnapshot=()=>{if(baseContext().store_scope){const value=getPageContext?.();return value?clone(value):null;}if(s.manualModule){const c=current();return {page:c.module,demo:!!c.demo,source:'local',filters:Object.fromEntries(['platform','market','store_id'].filter(k=>c[k]).map(k=>[k,c[k]]))}}const value=getPageContext?.();return value?clone(value):null};
  function followPage(){if(!getPageContext||s.busy||replyingOriginal()||!changed())return;s.load++;s.thread=null;s.replyScope=null;s.scopeOverride=null;s.openKey=null;s.request=null;s.newThread=false;s.review=null;s.form=false;s.fields={};s.answers={};}
  const originalPage=()=>s.thread?.latest_run?.parameters?.page_context||{page:s.thread?.context.entity?.kind==='case'?'workspace':s.thread?.context.module,demo:!!s.thread?.context.demo,filters:Object.fromEntries(['platform','market','store_id'].filter(k=>s.thread?.context[k]).map(k=>[k,s.thread.context[k]])),...(s.thread?.context.entity?{entity:s.thread.context.entity}:{})};
  function pageRange(){const page=pageSnapshot();if(!page)return '';const original=replyingOriginal(),bound=original?originalPage():page,label=window.CommercePageContext?.label(bound)||bound.page;return `<div class="copilot-page-context" role="status" aria-label="本轮提问位置"><span>${original?'回复原问题':s.manualModule?'固定模块':'当前页面'}</span><strong title="${esc(Object.entries(bound.source_refs||{}).map(([key,sha])=>key+': '+sha).join(' · '))}">${esc(label)}</strong>${button('查看范围','context-details',{'aria-label':'查看范围：本轮带入的上下文',class:'copilot-context-inspect',id:'copilot-context-inspect'},'quiet')}</div>`;}
  const editorOwner=element=>{const owner=element?.dataset?.copilotDraftKey||s.compositionKey||key();return s.draftMigration?.from===owner&&s.draftMigration.to===key()?key():owner};
  const button=(label,action,attrs={},variant='secondary')=>ui.button({label,variant,leadingIcon:attrs.icon||'',attrs:{'data-copilot-action':action,...attrs}});
  const researchActive=job=>job&&['queued','running','cancelling'].includes(job.status);
  const researchJob=run=>run?.research_job||(s.thread?.research_job?.run_id===run?.id?s.thread.research_job:null);
  const researchBusy=()=>researchActive(s.thread?.research_job)||(s.thread?.turns||[]).some(t=>researchActive(researchJob(t.run)));
  const researchWatching=()=>[s.thread?.research_job,...(s.thread?.turns||[]).map(t=>researchJob(t.run))].some(job=>job&&['queued','running','awaiting_input','cancelling'].includes(job.status));
  const selectedModelId=()=>s.thread?.model_selection?.model_id||s.defaultModelId||'project-default';
  const defaultModelPending=()=>!s.thread?.model_selection&&!s.modelCatalogReady;
  const modelSelectionUnconfirmed=()=>s.modelUnconfirmed?.has(key());
  const modelUnavailable=()=>{const selection=s.thread?.model_selection,id=selectedModelId(),model=s.models?.find(m=>m.id===id);return !!modelSelectionUnconfirmed()||defaultModelPending()||selection?.available===false||model?.selectable===false||(id!=='project-default'&&Array.isArray(s.models)&&!model)};
  function runModel(run){const choice=run.model_choice||{},actual=typeof run.result?.model==='string'?run.result.model:choice.model,label=[choice.label,actual].filter((v,i,a)=>typeof v==='string'&&v&&a.indexOf(v)===i).join(' · ');return label?`<span class="copilot-run-model" title="${esc(label+(choice.profile_revision!=null?' · 配置版本 '+choice.profile_revision:''))}">${esc(label)}</span>`:''}
  const researchPrompts=()=>reading?.suggestions(current(),pageSnapshot())||(['overview','research','pilots'].includes(current().module)?[['俄罗斯市场调研','我要调研俄罗斯市场。请先确认品类与研究目标，再采集真实公开资料、分析并保存候选商品。'],['按条件选品','帮我选品。请先确认目标市场、品类和预算，再采集真实公开资料并保存候选。']]:[['核对资料缺项','梳理当前工作有哪些资料缺项']]);
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
  const scope=c=>{if(scopeLabel)return scopeLabel(c);const platforms={ozon:'Ozon',tiktok:'TikTok Shop',amazon:'Amazon',mercado:'Mercado Libre',temu:'Temu'},kinds={order:'订单',product:'商品',case:'工作项',intel:'情报'};return [ui.moduleDetails(c?.module||'').description,c?.demo?'合成示例':'按本页来源',!c?.platform||c.platform==='all'?'全部平台':platforms[c.platform]||c.platform,c?.store_scope?(c.store_scope==='unassigned'?'未关联店铺':`店铺视图 ${c.store_scope.slice(-8)}`):!c?.store_id||c.store_id==='all'?'全部店铺':`店铺 ${c.store_id}`,!c?.market||c.market==='all'?'全部市场':c.market,c?.entity?`${kinds[c.entity.kind]||'当前对象'} ${c.entity.id}`:''].filter(Boolean).join(' · ')};
  async function chooseModule(module){
    if(s.busy)return;
    if(baseContext().store_scope&&module!==null&&module!==baseContext().module)throw Error('当前问题已限定店铺，请先切回当前页面或在日常运营选择全部店铺。');
    if(module!==null&&!['overview','orders','products','operations','alerts','support','insights','research','intelligence','creative','pilots','agent','exposure','organization','tasks','platforms','live','skills','connections'].includes(module))throw Error('功能范围未登记');
    if(s.composing)finishComposition(s.compositionElement);
    s.capabilityComposing=false;s.manualModule=module;s.replyScope=null;s.scopeOverride=null;s.load++;s.thread=null;s.openKey=null;s.request=null;s.review=null;s.fields={};s.answers={};s.form=false;s.history=false;s.newThread=false;
    capabilityPicker?.contextChanged();update('copilot-message');await load();
  }
  capabilityPicker=window.CommerceCopilotCapabilities?.({api:originalApi,ui,getContext:()=>s.thread?.context||current(),isActive:()=>s.open&&isActive()&&!s.busy,isComposing:()=>!!s.capabilityComposing&&!!document.getElementById('copilot-capability-query'),repaint:()=>update(),onModule:chooseModule,onChange:()=>{s.request=null}})||null;
  let paintedKey=null;
  function remember(){
    if(paintedKey!==key())return;
    const e=document.activeElement,inside=e?.closest?.('#commerce-copilot');
    if(inside){const detail=e.closest?.('[data-view-key]');s.focus=e.id?{id:e.id,start:e.selectionStart,end:e.selectionEnd,direction:e.selectionDirection}:detail?{viewKey:detail.dataset.viewKey}:null}
    else s.focus=null;
    const root=document.querySelector('#commerce-copilot');
    s.disclosures=root?.querySelectorAll?[...root.querySelectorAll('details[data-view-key]')].filter(el=>el.open).map(el=>el.dataset.viewKey):[];
    const log=document.querySelector('#copilot-log');
    s.textSelection=window.CommerceCopilotReading?.capture(log);
    if(log){const top=log.getBoundingClientRect?.().top||0,anchor=[...(log.querySelectorAll?.('[data-message-key]')||[])].find(el=>el.getBoundingClientRect().bottom>top+1);s.scroll={top:log.scrollTop,bottom:log.scrollHeight-log.scrollTop-log.clientHeight<64,anchor:anchor?.dataset.messageKey,offset:anchor?anchor.getBoundingClientRect().top-top:0}}
  }
  function update(focus){
    if(disposed)return;
    if((s.composing&&document.getElementById('copilot-message')||s.capabilityComposing&&document.getElementById('copilot-capability-query'))&&s.open){s.pendingPaint=true;if(focus)s.pendingFocus=focus;return}
    remember();if(focus)s.focus={id:focus};
    const root=document.querySelector('#commerce-copilot');
    if(root){
      const editor=paintedKey===key()?document.getElementById('copilot-message'):null;
      const t=document.createElement('template');t.innerHTML=view();
      const next=t.content.querySelector?.('#copilot-message');
      if(editor&&next){for(const name of ['placeholder','rows','maxlength'])if(next.hasAttribute(name))editor.setAttribute(name,next.getAttribute(name));if(editor.value!==next.value)editor.value=next.value;next.replaceWith(editor)}
      const capabilityQuery=document.getElementById('copilot-capability-query'),nextQuery=t.content.querySelector?.('#copilot-capability-query');if(capabilityQuery&&nextQuery){capabilityQuery.placeholder=nextQuery.placeholder;nextQuery.replaceWith(capabilityQuery);}
      const modelQuery=document.getElementById('copilot-model-query'),nextModelQuery=t.content.querySelector?.('#copilot-model-query');if(modelQuery&&nextModelQuery){if(modelQuery.value!==nextModelQuery.value)modelQuery.value=nextModelQuery.value;nextModelQuery.replaceWith(modelQuery);}
      root.replaceWith(t.content);afterPaint();
    }else if(repaint)repaint();
  }
  function layout(){const docked=s.open&&(inline||window.innerWidth>=1280);if(s.open&&!inline&&!compact)document.querySelector('#commerce-copilot')?.setAttribute('aria-modal',String(!docked));window.dispatchEvent(new CustomEvent('commerce:copilot-layout',{detail:{open:s.open,docked}}))}
  function afterPaint(){
    if(disposed||!s.open)return;
    capabilityPicker?.afterPaint();layoutMore();
    const same=paintedKey===key(),textSelection=same?s.textSelection:null;paintedKey=key();layout();syncComposer();
    const root=document.querySelector('#commerce-copilot');
    if(same&&root?.querySelectorAll)for(const el of root.querySelectorAll('details[data-view-key]'))el.open=(s.disclosures||[]).includes(el.dataset.viewKey);
    const log=document.querySelector('#copilot-log');
    if(log&&s.forceLatest){log.scrollTop=log.scrollHeight;s.scroll={bottom:true};s.forceLatest=false}
    else if(log&&s.startAtTop){log.scrollTop=0;s.scroll={top:0,bottom:false};s.startAtTop=false}
    else if(log&&s.scroll){const anchor=same&&s.scroll.anchor?[...(log.querySelectorAll?.('[data-message-key]')||[])].find(el=>el.dataset.messageKey===s.scroll.anchor):null;if(s.scroll.bottom)log.scrollTop=log.scrollHeight;else if(anchor)log.scrollTop+=anchor.getBoundingClientRect().top-log.getBoundingClientRect().top-s.scroll.offset;else if(s.prependAnchor)log.scrollTop=s.prependAnchor.top+log.scrollHeight-s.prependAnchor.height;else log.scrollTop=s.scroll.top}
    s.prependAnchor=null;
    if(s.focus&&!document.querySelector('.dialog')){const e=s.focus.id?document.getElementById(s.focus.id):[...(root?.querySelectorAll?.('[data-view-key]')||[])].find(el=>el.dataset.viewKey===s.focus.viewKey)?.querySelector('summary');if(e){e.focus({preventScroll:true});if(typeof e.setSelectionRange==='function'&&s.focus.start!=null)e.setSelectionRange(s.focus.start,s.focus.end,s.focus.direction)}}
    if(textSelection)window.CommerceCopilotReading?.restore(log,textSelection);
  }
  function layoutMore(){
    const picker=document.querySelector('#copilot-more-picker[open]'),panel=picker?.querySelector('.copilot-compose-more-panel'),trigger=picker?.querySelector('summary');if(!panel||!trigger)return;
    const anchor=trigger.getBoundingClientRect(),width=Math.min(280,window.innerWidth-24),above=anchor.top-16;
    panel.style.width=width+'px';panel.style.left=Math.max(12,Math.min(anchor.right-width,window.innerWidth-width-12))+'px';
    panel.style.maxHeight=Math.max(96,Math.min(440,above>=160?above:window.innerHeight-anchor.bottom-16))+'px';
    if(above>=160){panel.style.top='auto';panel.style.bottom=(window.innerHeight-anchor.top+8)+'px'}else{panel.style.bottom='auto';panel.style.top=(anchor.bottom+8)+'px'}
  }
  function syncComposer(){
    const input=document.getElementById('copilot-message');if(!input)return;
    const send=document.querySelector('[data-copilot-action="send"]');if(send)send.disabled=!!(s.busy||s.unavailable||(changed()&&!replyingOriginal())||modelUnavailable()||(working()&&!features().followups)||!draft().trim());
    const steer=document.querySelector('[data-copilot-action="steer"]');if(steer)steer.disabled=!!(s.busy||!draft().trim()||selectedMaterials().length);
    const length=document.getElementById('copilot-length');if(length){length.textContent=draft().length+' / 2000';length.classList?.toggle('is-near-limit',draft().length>=1800)}
    if(!compact)return;
    const css=window.getComputedStyle(input),min=parseFloat(css.minHeight)||64,max=parseFloat(css.maxHeight)||180;
    input.style.height='auto';const height=Math.min(max,Math.max(min,composerHeight||input.scrollHeight));input.style.height=height+'px';input.style.overflowY=input.scrollHeight>height?'auto':'hidden';const handle=document.querySelector('[data-copilot-resize]');if(handle){handle.setAttribute('aria-valuenow',String(Math.round(height)));handle.setAttribute('aria-valuemax',String(Math.floor(max)))}
  }
  const receiptWatching=()=>[s.thread?.latest_run,...(s.thread?.turns||[]).map(t=>t.run)].some(run=>(run?.actions||[]).some(action=>action.receipt?.outcome==='pending'));
  function actionReceipt(action){return (ui.receipt?ui.receipt(action.receipt||{task_id:action.task_id,outcome:'unknown'}):`<p>已提交本地任务；请在任务模块核对执行回执。任务 ${esc(action.task_id)}</p>`)+button('查看任务结果','task-result',{'data-task':action.task_id})}
  function evidenceView(observation,runId){
    if(observation.tool==='commerce_reference_materials'){
      const items=observation.data?.items||[];
      return `<section class="copilot-reference-evidence"><h3>本轮所选资料</h3>${items.map(item=>`<details data-view-key="${esc('material:'+runId+':'+item.id)}"><summary>${esc(item.filename||item.title||'对象快照')}${item.text_truncated?' · 文字已限量':''}</summary><pre class="copilot-material-text">${esc(item.text||'未提取到可用文字')}</pre><small>本轮发送时保留的文字快照 · 未独立核实</small></details>`).join('')}</section>`;
    }
    const readable=window.CommerceAssistantEvidence?.render(observation,esc);if(readable!=null)return readable;
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
  function proposalCard(p,run){const actions=run.actions||[];return `<section class="copilot-card"><h3>${esc(p.reason||p.operation)}</h3><p class="muted">${p.authorization==='explicit_user_local_archive'?'按本轮明确要求保存分析与来源':'逐项确认后提交本地任务'}</p>${actions.some(a=>a.proposal_id===p.id)?actionReceipt(actions.find(a=>a.proposal_id===p.id)):p.authorization==='explicit_user_local_archive'?'<p role="status">正在提交本地简报…</p>':button('审阅建议','review',{'data-run':run.id,'data-proposal':p.id,disabled:s.busy||!!changed(),title:changed()?'当前页面与原会话范围不同，原建议仅供查看；请回到原工作范围后审阅。':''})}${changed()&&!actions.some(a=>a.proposal_id===p.id)?'<p class="muted" role="status">当前页面与原会话范围不同，原建议仅供查看；请回到原工作范围后审阅。</p>':''}</section>`;}
  function renderRun(run,generated){if(!run)return '';
    if(researchJob(run)?.schema==='commerce-market-research-v1'){
      const research=researchView(run),result=run.result||{};
      return `<article class="copilot-message copilot-assistant" data-message-key="run:${esc(run.id)}"><div class="copilot-message-meta">${ui.icon('spark')}<strong>智能助手</strong>${runModel(run)}</div>${research||[result.answer,...(result.questions||[])].filter(Boolean).map(text=>`<div class="copilot-formatted">${reading?.markdown(text)||window.CommerceAssistantEvidence?.prose(text,esc)||esc(text)}</div>`).join('')}</article>`;
    }
    const preview=active.has(run.status)&&run.stream?.provisional?run.stream:null;
    const presentation=preview?.components?.length?{schema:'commerce-generative-surface-v1',catalog_version:1,provisional:true,components:preview.components}:run.presentation;
    if(presentation?.components?.length){const typed=window.CommerceGenerativeUI?.render(presentation,{ui,evidence:o=>evidenceView(o,run.id),proposal:p=>proposalCard(p,run),receipt:actionReceipt,reply:()=>button('填写补充回答','reply'),workspace:onOpenCandidate?c=>button('打开对应商品工作区','generative-workspace',{'data-run':run.id,'data-component':c.id}):null});if(typed)generated=typed;}
    const nativeCode=run.host_diagnostic?.code,nativeFailure=nativeCode==='native_output_limit'?'已核对：模型输出额度耗尽，完整分析未生成。已有记录已保留，原请求未重发。':nativeCode==='native_invalid_json'?'已核对：模型返回的结果格式无效，未形成可采纳的分析。已有记录已保留，原请求未重发。':'';
    const r=run.result||{},failure=typeof r.error==='string'?r.error:typeof run.error==='string'?run.error:run.error?.code,covered=generated?.covered,questions=(r.questions||[]).filter(q=>!covered?.questions.has(q)),proposals=(r.proposals||[]).filter(p=>!covered?.proposals.has(p.id)),actions=run.actions||[];
    const observations=window.CommerceAssistantEvidence?.group(r.observations||[])||r.observations||[];
    return `<article class="copilot-message copilot-assistant" data-message-key="run:${esc(run.id)}"><div class="copilot-message-meta">${ui.icon('spark')}<strong>智能助手</strong>${runModel(run)}${compact&&run.status==='completed'?'':ui.badge(window.CommerceAssistantEvidence?.reviewStatus(run)||status[run.status]||run.status||'待处理',run.status==='failed'?'danger':'gray')}</div>${active.has(run.status)&&!researchJob(run)&&!compact?`<p role="status">${esc(window.CommerceAssistantEvidence?.progress(run)||'正在处理，本轮结果会保留。')}</p>${button('请求停止','cancel',{'data-run':run.id,disabled:s.busy})}`:''}${preview?.answer?`<section class="copilot-provisional" aria-label="生成中的预览"><small class="muted">${preview.truncated?'预览已限量，完成后读取完整结果':'正在生成，尚未完成来源与格式校验'}</small><div class="copilot-prose">${esc(preview.answer)}</div></section>`:''}${r.answer&&!covered?.answer?`<div class="copilot-formatted">${reading?.markdown(r.answer)||window.CommerceAssistantEvidence?.prose(r.answer,esc)||esc(r.answer)}</div>`:''}${failure||['failed','interrupted','unknown'].includes(run.status)?ui.alert(run.status==='unknown'?(nativeFailure||'结果尚未确认，请先核对原记录，不会自动重发。'):failure?(errorText?errorText({code:failure,message:failure}):({agent_model_setup_required:'模型运行入口尚未配置，请在模型管理中完成配置。',agent_evidence_reference_required:'模型回复缺少来源引用，本次结果未被采纳。',agent_interrupted_no_automatic_resubmit:'回复已中断，未自动重发。核对记录后可重新编辑问题。'}[failure]||'这次回复未完成，请核对原记录。')):(run.status==='interrupted'?'回复已中断，未自动重新发送。':'回复未完成，未自动重新发送。'),'danger')+(['failed','interrupted'].includes(run.status)?button('重新编辑问题','edit-question',{'data-run':run.id}):''):''}${questions.length?(compact?`<div class="copilot-answer">${questions.map(q=>`<p class="copilot-question">${esc(q)}</p>`).join('')}</div>`:`<section class="copilot-card"><h3>需要补充</h3>${questions.map(q=>`<p>${esc(q)}</p>`).join('')}${button('填写补充回答','reply')}${button('补充测算数据','fields')}</section>`):''}${proposals.map(p=>proposalCard(p,run)).join('')}${r.local_archive_error?ui.alert('分析已保留，本地简报保存未完成。请核对原问题范围后重试。','warning'):''}${generated?.html||''}${r.answer?`<div class="copilot-message-actions">${button('复制答复','copy-answer',{'data-run':run.id})}</div>`:''}${researchView(run)}${observations.length?`<details class="copilot-evidence" data-view-key="${esc('run:'+run.id+':evidence')}"><summary>查看依据${r.observations?.length?' · '+r.observations.length+' 项':''}</summary>${(generated?.captions||[]).map(v=>`<p>${esc(v)}</p>`).join('')}${observations.map(o=>evidenceView(o,run.id)).join('')}</details>`:''}</article>`;
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
    let count=0;const html=[...all.values()].map(sf=>{let hasQuestion=false,hasInput=false;const val=v=>{if(typeof v==='string')return v;if(v?.literalString!=null)return String(v.literalString);if(typeof v?.path==='string'){let o=sf.data;for(const p of v.path.split('/').filter(Boolean)){if(['__proto__','constructor','prototype'].includes(p))throw Error();o=o?.[p]}return ['string','number','boolean'].includes(typeof o)?String(o):''}return ''};const render=(id,seen=new Set(),depth=0)=>{if(depth>16||seen.has(id)||++count>256)throw Error();const obj=sf.nodes.get(id);if(!obj)throw Error();const [type,p]=Object.entries(obj)[0];const next=new Set(seen).add(id);if(['Column','Row'].includes(type)){if(!Array.isArray(p.children?.explicitList)||p.children.explicitList.length>64)throw Error();return `<div class="copilot-a2ui-${type.toLowerCase()}">${p.children.explicitList.map(c=>render(c,next,depth+1)).join('')}</div>`}if(type==='Text'){const text=val(p.text);if(id==='answer'&&!latest?.result?.answer)return '';if(compact&&p.usageHint==='caption'){captions.push(text);return ''}if(latest?.result?.answer&&text===latest.result.answer.slice(0,8000))covered.answer=true;return `<div class="copilot-formatted">${reading?.markdown(text)||window.CommerceAssistantEvidence?.prose(text,esc)||esc(text)}</div>`;}
      if(type==='Button'){const action=p.action;if(action?.name!=='commerce.review_proposal')throw Error();const ctx=Object.fromEntries((action.context||[]).map(c=>[c.key,val(c.value)]));const run=(s.thread?.turns||[]).map(t=>t.run).find(r=>r?.id===ctx.run_id);if(!run?.result?.proposals?.some(p=>p.id===ctx.proposal_id))throw Error();const label=p.child?val(sf.nodes.get(p.child)?.Text?.text):'审阅建议';if(run.id===latest?.id)covered.proposals.add(ctx.proposal_id);if((run.actions||[]).some(a=>a.proposal_id===ctx.proposal_id))return `<div><strong>${esc(run.result?.proposals?.find(p=>p.id===ctx.proposal_id)?.authorization==='explicit_user_local_archive'?'已保存本轮公开研究简报':label)}</strong>${actionReceipt(run.actions.find(a=>a.proposal_id===ctx.proposal_id))}</div>`;return button(label||'审阅建议','review',{'data-run':ctx.run_id,'data-proposal':ctx.proposal_id,disabled:!!changed()})}
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
  async function switchThread(id){if(s.busy)return;s.modelMenu=false;const seq=++s.load;s.busy=true;s.error='';update();try{const thread=await api('commerce_copilot_get',{thread_id:id});if(seq!==s.load)return;accept(thread);s.replyScope={thread:thread.id,hash:thread.context_sha256,page:canonical(current()),location:canonical(pageSnapshot())};s.newThread=false;s.review=null;s.fields={};s.answers={};s.form=false;s.history=false;s.focus={id:'copilot-message'};s.scroll={bottom:true}}catch(error){s.historyError='无法打开这条会话，请刷新后重试。'}finally{s.busy=false;update()}}
  const selectedMaterials=()=>s.materialSelections[key()]||[];
  const working=()=>active.has(s.thread?.latest_run?.status)||researchBusy();
  const features=()=>({...s.features,...s.thread?.interaction_capabilities});
  function materialView(){
    const items=s.thread?.materials||[],selected=selectedMaterials(),upload=s.materialUpload,progress=upload&&!['completed','cancelled'].includes(upload.status)?`<div class="copilot-upload-progress" role="status">${esc(({saving:'正在保存本机资料',uploading:'正在分片保存至本机',finishing:'正在核对完整文件并提取文字',unconfirmed:'添加结果待核对；请重新选择同一文件核对'})[upload.status]||'正在准备资料')} · ${Math.ceil(upload.received/1024)} / ${Math.ceil(upload.total/1024)} KB${upload.cancellable?button('取消添加','material-upload-cancel',{'aria-label':'取消未完成的资料添加'}):''}</div>`:'';if(!items.length)return progress;
    return `${progress}<div class="copilot-materials" aria-label="本轮参考资料">${items.map(item=>`<span class="copilot-material ${item.stale?'is-stale':''}">${button((selected.includes(item.id)?'已选 · ':'')+(item.filename||item.title||'对象资料'),'material-select',{'data-material':item.id,'aria-pressed':selected.includes(item.id),disabled:s.busy||item.stale||item.model_usable===false,title:item.stale?'范围已变化，请重新添加':item.visual_understanding===false?'图片或PDF只提取文字；不代表图像理解':'选中后发送时带入'})}${button('预览','material-preview',{'data-material':item.id,'aria-label':'预览'+(item.filename||item.title||'资料'),id:'copilot-material-preview-'+item.id})}${button('撤下','material-remove',{'data-material':item.id,disabled:s.busy,'aria-label':'撤下'+(item.filename||item.title||'资料')})}</span>`).join('')}</div>`;
  }
  function runBar(){
    const run=s.thread?.latest_run;if(!working()||!run)return '';
    const job=researchJob(run),event=[...(run.trace||[])].reverse().find(e=>['tool_started','read_tool','model_turn'].includes(e.event));
    const toolNames={commerce_web_search:'检索公开资料',commerce_web_read:'读取来源正文',commerce_current_page:'读取本页数据',commerce_project_memory_search:'检索业务记忆'};
    const detail=event?.event==='tool_started'?(toolNames[event.tool]||'读取范围内资料'):run.status==='queued'?'等待执行':run.status==='cancel_requested'?'等待后台确认停止':'正在分析';
    return `<div class="copilot-runbar" role="status"><span>${esc(job?.status==='cancelling'?'等待研究停止':detail)}${run.created?' · '+Math.max(0,Math.floor(Date.now()/1000-run.created))+'秒':''}</span>${job&&researchActive(job)?button(job.status==='cancelling'?'正在停止':'停止研究','research-cancel',{'data-task':job.task_id,disabled:s.busy||job.status==='cancelling'}):button(run.status==='cancel_requested'?'请求停止中':'请求停止','cancel',{'data-run':run.id,disabled:s.busy||run.status==='cancel_requested'})}</div>`;
  }
  function queueView(){
    const queue=s.thread?.followups,items=queue?.items?.filter(item=>(['queued','held','waiting','not_received'].includes(item.status)||item.status==='included'&&item.after_run_id===s.thread?.latest_run?.id))||[];if(!items.length)return '';
    const labels={queued:'排队下一轮',held:'已暂停',waiting:'等待本轮接收',not_received:'本轮结束前未接收',included:'已带入本轮分析'};
    const reasons={context_changed:'页面对象或范围已变化',model_changed:'模型配置已变化',page_source_changed:'资料版本已变化',previous_run_unknown:'上一轮结果未知',previous_run_failed:'上一轮未完成',previous_run_cancel_requested:'等待原请求停止',previous_run_cancelled:'上一轮已取消',previous_run_interrupted:'上一轮已中断'};
    return `<section class="copilot-queue" aria-label="后续消息"><header><strong>后续消息</strong>${queue.paused?button('继续后续队列','queue-resume',{disabled:s.busy}):''}</header>${items.map(item=>`<div class="copilot-queue-item"><p>${esc(item.message)}</p><small>${esc(labels[item.status])}${item.reason&&item.status==='held'?' · '+esc(reasons[item.reason]||'请核对原范围与资料'):''}</small><div>${['queued','held'].includes(item.status)?button('编辑','queue-edit',{'data-item':item.id,id:'copilot-queue-edit-'+item.id,disabled:s.busy})+button('上移','queue-up',{'data-item':item.id,disabled:s.busy})+button('下移','queue-down',{'data-item':item.id,disabled:s.busy}):''}${item.status==='not_received'?button('排队下一轮','queue-next',{'data-item':item.id,disabled:s.busy}):''}${['queued','held','waiting','not_received'].includes(item.status)?button('撤回','queue-cancel',{'data-item':item.id,disabled:s.busy}):''}</div></div>`).join('')}</section>`;
  }
  function composerView(thread,mismatch){
    const live=working(),canQueue=features().followups,label=s.busy?'正在提交':live&&canQueue?'排队发送':'发送';
    return `<footer class="copilot-composer"><div class="copilot-resize" data-copilot-resize role="separator" aria-label="调整输入区高度" aria-orientation="horizontal" aria-valuemin="64" aria-valuemax="480" aria-valuenow="${composerHeight||72}" tabindex="0" title="上下拖动或用方向键调整；Home 恢复自动高度"></div>${pageRange()}${materialView()}<label class="copilot-compose-label" for="copilot-message">问题或补充回答</label><textarea class="ui-control" id="copilot-message" data-copilot-draft-key="${esc(key())}" rows="2" maxlength="2000" placeholder="${live?'输入下一条问题，或补充本轮要求…':thread?.latest_run?.status==='awaiting_input'?'直接输入补充信息…':'输入问题或补充信息…'}">${esc(draft())}</textarea><div class="copilot-editor-meta"><span id="copilot-length" class="${draft().length>=1800?'is-near-limit':''}">${draft().length} / 2000</span></div>${runBar()}${queueView()}${modelNotices()}<div class="copilot-compose-actions">${capabilityPicker?.view({manualModule:s.manualModule})||''}${modelView()}<details id="copilot-more-picker" class="copilot-compose-more" data-view-key="composer-more"><summary id="copilot-more-trigger" aria-label="更多输入选项" title="添加资料、引用对象与展开编辑">${ui.icon('more')}</summary><div class="copilot-compose-more-panel" role="group" aria-label="输入选项"><label class="copilot-attach ui-button" title="仅保存到本机；较大资料分片传输，大小与文字提取能力以预检为准"><span>${ui.icon('plus')}<span class="sr-only">添加资料</span></span><input id="copilot-file" type="file" accept=".txt,.md,.csv,.json,.pdf,.png,.jpg,.jpeg" aria-label="添加本机参考资料" ${s.busy||!features().materials||mismatch&&!replyingOriginal()?'disabled':''}></label>${['case','product','order','intel'].includes((thread?.context||current()).entity?.kind)?button(replyingOriginal()?'@原会话对象':'@当前对象','reference-current',{disabled:s.busy||!features().materials||mismatch&&!replyingOriginal(),'aria-label':replyingOriginal()?'引用原会话业务对象':'引用当前业务对象',title:scope(thread?.context||current())}):''}${!compact?button('补充数据','fields',{disabled:s.busy}):''}${!capabilityPicker&&current().entity?.kind==='case'&&onWorkspace?button('成本','workspace',{disabled:s.busy,icon:'chart',class:'copilot-workspace-tool','aria-label':'打开成本参数'}):''}${button('展开编辑','expand-editor',{'aria-label':'展开编辑长问题',id:'copilot-editor-expand'})}${live&&canQueue&&thread?.followups?.can_steer?button('补充本轮','steer',{disabled:s.busy||!draft().trim()||selectedMaterials().length>0,title:selectedMaterials().length?'带资料的问题请排队下一轮':'在下一步分析中带入，保持本轮对象和权限'}):''}</div></details>${button(s.busy?'提交中':live&&canQueue?'排队':'','send',{disabled:s.busy||!!s.unavailable||(mismatch&&!replyingOriginal())||modelUnavailable()||(live&&!canQueue)||!draft().trim(),icon:s.busy?'':'arrowUp',class:'copilot-send','aria-label':label,title:live?'本轮结束后处理，不重发原问题':s.sendKey==='enter'?'Enter发送，Shift+Enter换行':'⌘ / Ctrl + Enter发送'},'primary')}</div></footer>`;
  }
  function readingControls(thread){
    const range=readingWindow?.range(thread,s.forceLatest||s.startAtTop?null:s.scroll);
    if(!range)return thread?.has_more?button('更早记录','older',{'data-cursor':thread.next_cursor,disabled:s.busy}):'';
    if(range.total<=40&&!thread?.has_more)return '';
    return `<nav class="copilot-reading-nav" aria-label="会话记录分页">${range.before||thread?.has_more?button('更早记录','older',{disabled:s.busy,'aria-label':range.before?'显示更早已加载记录':'读取更早记录'}):''}<span role="status">已加载 ${range.total} 轮 · ${range.start+1}–${range.end}</span>${range.after?button('较新记录','newer',{disabled:s.busy,'aria-label':'显示较新已加载记录'})+button('回到最新','newest',{disabled:s.busy,title:range.after+'轮较新记录'}):''}</nav>`;
  }
  function compactView(thread,turns,generated) {
    const mismatch=changed(),contextual=mismatch?'':renderContext();
    return `<aside id="commerce-copilot" class="copilot-shell copilot-compact" role="region" aria-labelledby="copilot-title"><section class="copilot-panel"><header class="copilot-header"><div class="copilot-title"><h2 id="copilot-title">智能助手</h2></div><div class="copilot-header-actions">${button('会话','history',{'aria-label':'查看会话列表','aria-expanded':s.history,'aria-controls':'copilot-history',id:'copilot-history-toggle',icon:'chat'})}${button('新建','new',{disabled:s.busy,icon:'plus','aria-label':'新建对话'})}<details class="copilot-options" data-view-key="options"><summary aria-label="会话选项">${ui.icon('more')}</summary><div class="copilot-options-panel"><p class="copilot-context-label">${esc(scope(thread?.context||current()))}</p><label for="copilot-send-key">发送快捷键</label><select id="copilot-send-key" class="ui-control"><option value="mod-enter" ${s.sendKey==='mod-enter'?'selected':''}>⌘ / Ctrl + Enter发送</option><option value="enter" ${s.sendKey==='enter'?'selected':''}>Enter发送，Shift+Enter换行</option></select>${s.settingsNotice?`<small role="status">${esc(s.settingsNotice)}</small>`:''}${methodView()}</div></details></div></header>${s.history?historyView()+(s.error?ui.alert(s.error,'danger'):''):`${mismatch?`<div class="copilot-scope ${replyingOriginal()?'copilot-original-reply':''}">${replyingOriginal()?`<span class="copilot-original-range" title="${esc(scope(thread.context))}">回复原会话 · ${esc(scope(thread.context))}</span>`:ui.alert('当前会话仍使用原业务范围。','warning')}${button(current().entity?'使用当前'+objectName():'使用当前页面','context',{disabled:s.busy})}</div>`:''}<div id="copilot-log" class="copilot-log" tabindex="0" aria-label="会话记录">${readingControls(thread)}${turns.map(t=>`<article class="copilot-message copilot-user" data-message-key="turn:${esc(t.id||t.run?.id||t.question)}"><div class="copilot-prose">${esc(t.question||t.message)}</div></article>${renderRun(t.run,t.run?.id===thread?.latest_run?.id?generated:null)}`).join('')}${s.form?form():''}${contextual||(!turns.length&&!mismatch?`<div class="copilot-welcome"><div class="copilot-suggestions">${researchPrompts().map(([label],index)=>button(label,'suggest',{'data-suggestion':index,title:'仅填入问题，发送后才开始处理'})).join('')}</div></div>`:'')}${s.error?ui.alert(s.error,'danger')+(s.errorCode?`<details class="copilot-evidence"><summary>错误详情</summary><code>${esc(s.errorCode)}</code></details>`:''):''}</div>`}${composerView(thread,mismatch)}</section></aside>`;
  }
  function view(){if(!s.open)return '<div id="commerce-copilot" hidden></div>';const thread=s.thread,turns=readingWindow?readingWindow.range(thread,s.forceLatest||s.startAtTop?null:s.scroll).turns:thread?.turns||[],generated=thread?.surfaces?surfaces(thread.surfaces):null;if(compact)return compactView(thread,turns,generated);return `<aside id="commerce-copilot" class="copilot-shell" role="${inline?'region':'dialog'}" aria-labelledby="copilot-title"${inline?'':` aria-modal="${window.innerWidth<1280}"`}><div class="copilot-backdrop" data-copilot-action="close" aria-hidden="true"></div><section class="copilot-panel"><header class="copilot-header"><div class="copilot-title"><div><h2 id="copilot-title">运营助手</h2></div></div>${button('关闭','close',{'aria-label':'关闭运营助手'})}</header><div class="copilot-threadbar">${ui.field('共享会话',ui.select({id:'copilot-thread',value:thread?.id||'',disabled:s.busy,options:[{value:'',label:'新会话'},...s.threads.map(t=>({value:t.id,label:t.title||'运营会话'}))]}))}${button('新建','new',{disabled:s.busy})}${button('刷新','refresh',{disabled:s.busy})}</div><div class="copilot-scope"><strong>本轮范围</strong><p>${esc(scope(thread?.context||current()))}</p>${changed()?`${ui.alert(replyingOriginal()?'补充将发送到原会话，业务操作仍需核对范围。':'页面范围已变化。当前会话仍保留原范围，请明确更新后再发送或审阅。')}${button('使用当前页面范围','context',{disabled:s.busy})}`:''}</div><div id="copilot-log" class="copilot-log" tabindex="0" aria-label="会话记录">${readingControls(thread)}${!turns.length?`<div class="copilot-welcome"><p data-ui-help>一起核对资料、分析问题，把下一步整理成可审阅的建议。</p><div class="copilot-suggestions">${researchPrompts().map(([label],index)=>button(label,'suggest',{'data-suggestion':index,title:'填入问题后点击发送'})).join('')}</div><p class="muted" data-ui-help>点击建议只填入输入框。发送后才会请求模型。会话记录保存在本机服务，未发送文字保存在本机；存储不可用时会提示。</p></div>`:turns.map(t=>`<article class="copilot-message copilot-user" data-message-key="turn:${esc(t.id||t.run?.id||t.question)}"><div class="copilot-message-meta"><strong>你</strong></div><div class="copilot-prose">${esc(t.question||t.message)}</div></article>${renderRun(t.run,t.run?.id===thread?.latest_run?.id?generated:null)}`).join('')}${inline?renderContext():''}${methodView()}${s.form?form():''}${s.error?ui.alert(s.error,'danger')+(s.errorCode?`<details class="copilot-evidence"><summary>错误详情</summary><code>${esc(s.errorCode)}</code></details>`:''):''}</div>${composerView(thread,changed())}</section></aside>`}
  function accept(thread,older=false){if(compact&&sameObject(thread.context))try{localStorage.setItem(selectionKey(),thread.id)}catch{}const previous=s.thread;if(previous?.id!==thread.id){s.thread=thread;capabilityPicker?.restore(thread.capability_selection);return}const turns=new Map();for(const t of older?[...(thread.turns||[]),...(previous.turns||[])]:[...(previous.turns||[]),...(thread.turns||[])])turns.set(t.id||t.run?.id||t.question,t);s.thread={...previous,...thread,turns:[...turns.values()]};if(!older&&Object.hasOwn(previous,'has_more')){s.thread.has_more=previous.has_more;s.thread.next_cursor=previous.next_cursor}}
  async function older(){if(s.busy||!s.thread?.has_more||!s.thread.next_cursor)return;const id=s.thread.id,cursor=s.thread.next_cursor;s.load++;s.busy=true;s.error='';update();try{const page=await api('commerce_copilot_get',{thread_id:id,before:cursor});if(s.thread?.id!==id)return;remember();const log=document.querySelector('#copilot-log');if(log)s.prependAnchor={top:log.scrollTop,height:log.scrollHeight};accept(page,true)}catch(e){s.error='读取更早记录失败：'+e.message}finally{s.busy=false;update()}}
  async function load(){const seq=++s.load;let models,defaultModelId,compatible=false,modelError='';try{const catalog=await originalApi('commerce_model_list',{});if(!Array.isArray(catalog.models))throw Error('invalid_model_catalog');defaultModelId=catalog.default_model_id??'project-default';if(typeof defaultModelId!=='string'||(catalog.default_model_id!=null&&!catalog.models.some(m=>m.id===defaultModelId)))throw Error('invalid_model_catalog');models=catalog.models}catch(error){compatible=(error.code||error.message)==='unknown_tool';modelError='模型选项暂不可用，请刷新或检查后台版本。'}if(seq!==s.load||disposed)return;if(models){s.models=models;s.defaultModelId=defaultModelId;s.modelCatalogReady=true}else if(compatible)s.modelCatalogReady=true;s.modelError=modelError;const list=await api('commerce_copilot_list');if(seq!==s.load)return;s.threads=list.threads||[];s.features=list.interaction_capabilities||{};let thread=null;
    if(s.thread)thread=await api('commerce_copilot_get',{thread_id:s.thread.id});
    else if(!s.newThread&&s.threads.length){let selected;try{if(compact)selected=localStorage.getItem(selectionKey())}catch{}const matches=s.threads.filter(t=>sameObject(t.context)),candidate=compact?(matches.find(t=>t.id===selected)||(current().entity?matches[0]:null)):s.threads[0];if(candidate)thread=await api('commerce_copilot_get',{thread_id:candidate.id})}
    if(seq===s.load){if(thread){accept(thread);s.modelUnconfirmed?.delete(thread.id);}update()}
  }
  function modelView(){
    const selected=selectedModelId(),models=[...(s.models||[{id:'project-default',label:'项目默认',selectable:true}])],running=active.has(s.thread?.latest_run?.status)||researchBusy(),disabled=s.busy||modelSelectionUnconfirmed()||defaultModelPending()||running;
    if(!models.some(m=>m.id===selected))models.push({id:selected,label:s.thread?.model_selection?.label||s.thread?.model_selection?.model||'当前模型',selectable:!modelUnavailable(),missing:true});
    const model=models.find(m=>m.id===selected),label=model?.label||'项目默认',automatic=m=>m.id==='project-auto'||m.provider==='host_auto';
    const description=m=>automatic(m)?'按可用执行端优先顺序选择':[m.model,m.id==='project-default'?'项目固定配置':m.auth_owner==='official_codex_cli'?'通过 Codex 账号':m.auth_owner==='harness'?'通过 Harness 账号':m.engine==='llama_cpp'?'本机运行':''].filter(Boolean).join(' · ');
    const unavailable=m=>m.missing?'已从模型列表移除':m.enabled===false?'未启用':automatic(m)?'暂无可用执行端':m.auth_owner==='harness'?'请在 Harness 登录并选择模型':m.auth_owner==='official_codex_cli'?'请检查 Codex 账号连接':m.test_status==='invalid_configuration'?'配置待修复':'未就绪，请在管理中检查配置';
    const short=modelSelectionUnconfirmed()?'切换待核对':defaultModelPending()?'模型待刷新':selected==='project-default'?(model?.model||label):label,full=defaultModelPending()?'默认模型尚未读取':[label,description(model)].filter(Boolean).join(' · ');
    const query=s.modelQuery.trim().toLowerCase(),shown=models.filter(m=>[m.label,m.model,description(m)].join(' ').toLowerCase().includes(query));
    const notice=running&&!s.modelsRefreshing?'处理结束后可切换模型。':s.modelFeedback||(s.modelError?'刷新未完成。保留上次模型列表，请重试。':defaultModelPending()?'正在读取模型列表，请稍后刷新。':''),failed=!!s.modelFeedbackError||!!s.modelError;
    return `<details class="copilot-modelbar" id="copilot-model-picker" ${s.modelMenu?'open':''}><summary id="copilot-model-trigger" title="${esc(full)}" aria-label="选择对话模型：${esc(full)}" aria-controls="copilot-model-menu" class="${modelUnavailable()?'is-unavailable':''}"><span>${esc(short)}</span>${ui.icon('chevronDown')}</summary><div class="copilot-model-menu" id="copilot-model-menu" role="group" aria-label="模型选项"><header class="copilot-model-menu-heading"><strong>对话模型</strong><span>当前对话</span></header><label class="sr-only" for="copilot-model-query">搜索模型</label><input class="ui-control" id="copilot-model-query" type="search" autocomplete="off" placeholder="搜索名称或模型" aria-controls="copilot-model-list" value="${esc(s.modelQuery)}"><div class="copilot-model-list" id="copilot-model-list" role="listbox" aria-label="可用对话模型" aria-busy="${!!s.modelsRefreshing}">${shown.map(m=>ui.button({label:m.label,description:[description(m),m.selectable===false?unavailable(m):''].filter(Boolean).join(' · '),attrs:{'data-copilot-action':'model-select','data-model':m.id,role:'option','aria-label':m.label+' '+[description(m),m.selectable===false?unavailable(m):''].filter(Boolean).join(' · '),'aria-selected':m.id===selected,disabled:disabled||m.selectable===false,class:'copilot-model-option',title:m.selectable===false?unavailable(m):description(m)}})).join('')||`<div class="copilot-model-empty"><p role="status">没有匹配的模型</p>${button('清除搜索','model-query-clear')}</div>`}</div>${notice?`<p class="copilot-model-feedback ${failed?'is-error':''}" role="status">${esc(notice)}</p>`:''}<div class="copilot-model-menu-actions">${button(s.modelsRefreshing?'正在刷新…':'刷新列表','models-refresh',{id:'copilot-model-refresh','aria-label':'刷新模型列表',disabled:s.busy})}${button('管理模型','models',{id:'copilot-model-manage','aria-label':'管理模型',disabled:s.busy})}</div></div></details>`;
  }
  function modelNotices(){const model=s.models?.find(m=>m.id===selectedModelId()),notice=modelSelectionUnconfirmed()?'模型切换结果未确认，请刷新核对后再发送。输入已保留。':defaultModelPending()?'默认模型尚未读取，请刷新模型列表。输入已保留。':modelUnavailable()?(model?.provider==='host_auto'?'暂无可用执行端，请选择固定模型或稍后刷新。输入已保留。':'当前模型不可用，请选择其它模型，或在管理中测试启用后刷新。输入已保留。'):s.modelError;return [s.draftSaveError,notice].filter(Boolean).map(text=>`<small class="copilot-model-status" role="status">${esc(text)}</small>`).join('')}
  async function selectModel(id){
    if(s.busy||modelSelectionUnconfirmed()||defaultModelPending()||active.has(s.thread?.latest_run?.status)||researchBusy())return;
    if(id===selectedModelId()){s.modelMenu=false;s.modelQuery='';update('copilot-model-trigger');return;}
    const model=s.models?.find(m=>m.id===id);if(!model||model.selectable===false)return;
    s.load++;s.busy=true;s.modelFeedback='正在切换模型…';s.modelFeedbackError=false;update();let succeeded=false,submittedThread=null;
    try{await ensure();submittedThread=s.thread.id;const thread=await api('commerce_copilot_model',{thread_id:submittedThread,model_id:id,expected_revision:s.thread.model_selection?.revision||'0'});if(s.thread?.id===submittedThread)accept(thread);s.request=null;succeeded=true;s.modelFeedback='';}
    catch(e){const rejected=!submittedThread||['model_not_ready','model_not_found','model_selection_changed','copilot_model_changed','host_plan_model_conflict','agent_provider_outcome_unknown','copilot_active_run','copilot_active_review_retry_required'].includes(e.code||e.message);if(!rejected){s.modelUnconfirmed||=new Set();s.modelUnconfirmed.add(submittedThread);}s.modelFeedback=rejected?'模型未切换，输入已保留。请刷新列表核对当前选择。':'切换结果未确认，请刷新核对后再发送。输入已保留。';s.modelFeedbackError=true;}
    finally{s.busy=false;s.modelMenu=!succeeded;if(succeeded)s.modelQuery='';update(succeeded?'copilot-model-trigger':'copilot-model-query');}
  }
  async function refreshModels(){
    if(s.busy)return;s.busy=true;s.modelsRefreshing=true;s.modelFeedback='正在刷新模型列表…';s.modelFeedbackError=false;update();
    try{await load();if(s.modelError)throw Error('model_catalog_unavailable');s.modelFeedback='已刷新 · '+(s.models?.length||0)+' 个模型';}
    catch(e){s.modelFeedback='刷新未完成，已保留原选择和输入。请重试或检查模型连接。';s.modelFeedbackError=true;}
    finally{s.busy=false;s.modelsRefreshing=false;update('copilot-model-refresh');}
  }
  function updateModelSearch(){
    const list=document.getElementById('copilot-model-list');if(!list){update();return;}
    // Keep the native search input mounted: WebKit otherwise resets its caret on every keystroke.
    const template=document.createElement('template');template.innerHTML=modelView();
    list.replaceWith(template.content.querySelector('#copilot-model-list'));
  }
  function modelKeys(e){
    const id=e.target.id,option=e.target.closest?.('.copilot-model-list [role=option]');
    if(id!=='copilot-model-trigger'&&id!=='copilot-model-query'&&!option)return false;
    if(e.isComposing||s.modelComposing||e.keyCode===229)return false;
    if(!['ArrowUp','ArrowDown','Home','End'].includes(e.key)||id==='copilot-model-query'&&['Home','End'].includes(e.key))return false;
    e.preventDefault();const picker=document.getElementById('copilot-model-picker');if(picker){picker.open=true;s.modelMenu=true;}
    const rows=[...(document.querySelectorAll?.('.copilot-model-list [role=option]:not(:disabled)')||[])].filter(el=>el.getClientRects().length),at=rows.indexOf(option);
    const to=e.key==='Home'?0:e.key==='End'?rows.length-1:at<0?(e.key==='ArrowUp'?rows.length-1:0):Math.max(0,Math.min(rows.length-1,at+(e.key==='ArrowDown'?1:-1)));
    rows[to]?.focus({preventScroll:true});rows[to]?.scrollIntoView?.({block:'nearest'});return true;
  }
  async function ensure(scope=current(),previousKey=key()){
    if(s.thread)return;
    const pending=s.drafts[previousKey]??'';
    const thread=await api('commerce_copilot_open',{context:scope,idempotency_key:s.openKey||(s.openKey=crypto.randomUUID())});
    s.thread=thread;
    const destination=key(),latest=s.drafts[previousKey]??pending,version=draftVersions.get(previousKey)||0;
    s.draftMigration={from:previousKey,to:destination};
    if(s.compositionKey===previousKey){s.compositionKey=destination;if(s.compositionElement?.dataset)s.compositionElement.dataset.copilotDraftKey=destination;}
    if(s.expandedDraftOwner===previousKey)s.expandedDraftOwner=destination;
    const expanded=document.getElementById('copilot-expanded-message');if(expanded?.dataset?.copilotDraftKey===previousKey)expanded.dataset.copilotDraftKey=destination;
    const migrated=await setDraft(destination,latest);
    if(migrated&&s.drafts[previousKey]===latest&&(draftVersions.get(previousKey)||0)===version)setDraft(previousKey,'');
    s.threads=[thread,...s.threads.filter(t=>t.id!==thread.id)];s.newThread=false;
  }
  async function send(mode){
    followPage();const live=working();mode=mode||(live&&features().followups?'queue':'send');
    if(s.busy||s.unavailable||(changed()&&!replyingOriginal())||modelUnavailable()||(live&&mode==='send'))return;
    const submitted=draft(),draftOwner=key(),scopeAtSend=current(),bound=replyingOriginal()?originalPage():pageSnapshot(),pageAtSend=bound?{...bound,intent:replyingOriginal()?'original_thread':'current_page'}:null,message=submitted.trim(),initialModelId=s.thread?null:selectedModelId(),materialIds=[...selectedMaterials()];
    if(!message){s.error='请填写问题或选择一个建议。';update();return}
    s.load++;s.busy=true;s.error='';s.errorCode='';update();
    try{
      const capabilityArgs=await capabilityPicker?.prepare()||{};
      if(capabilityPicker&&canonical(current())!==canonical(scopeAtSend)){const error=Error('copilot_send_scope_changed');error.code='copilot_send_scope_changed';throw error;}
      await ensure(scopeAtSend,draftOwner);
      if(initialModelId&&s.thread.model_selection?.model_id&&initialModelId!==s.thread.model_selection.model_id)throw Error('copilot_model_changed');
      if(mode!=='send'&&!features().followups)throw Error('当前后台尚未载入后续消息功能，输入已保留。');
      const modelSha=s.thread.model_selection?.sha256,fingerprint=canonical({thread:s.thread.id,message,hash:s.thread.context_sha256,pageAtSend,materialIds,capabilityArgs,mode,...(mode!=='send'?{after:s.thread.latest_run?.id}:{})});
      if(s.request?.fingerprint!==fingerprint)s.request={fingerprint,modelSha,capabilityArgs,key:crypto.randomUUID()};
      const args={thread_id:s.thread.id,message,context_sha256:s.thread.context_sha256,idempotency_key:s.request.key,...(pageAtSend?{page_context:pageAtSend}:{}),...(s.request.modelSha?{expected_model_sha256:s.request.modelSha}:{}),...(materialIds.length?{material_ids:materialIds}:{}),...s.request.capabilityArgs};
      if(mode==='send')accept(await api('commerce_copilot_send',args));
      else {const queue=await api('commerce_copilot_followup_add',{...args,mode,after_run_id:s.thread.latest_run.id});s.thread.followups=queue;toast?.(mode==='steer'?'补充已记录，等待本轮下一步接收。':'已排队，当前处理结束后再开始。');}
      if((key()===draftOwner||draftOwner.startsWith('new:'))&&draft()===submitted){setDraft(key(),'');s.materialSelections[key()]=[];}
      s.request=null;readingWindow?.latest(s.thread);s.forceLatest=true;s.scroll={bottom:true};s.focus={id:'copilot-message'};
    }catch(error){
      if((error.code||error.message)==='copilot_send_scope_changed')s.error='发送前页面范围已变化，原问题尚未提交；两处草稿均已保留。';
      else if((error.code||error.message)==='copilot_model_changed'){s.request=null;s.error='模型配置已变化，请核对最新选项后再次发送。输入已保留。';await load().catch(()=>{});}
      else s.error='提交未确认：'+error.message+'。未自动重试，输入已保留。';
    }finally{s.busy=false;followPage();update();}
  }

  function review(runId,proposalId){if(changed())throw Error('页面范围已变化，请先更新会话范围');const run=(s.thread?.turns||[]).map(t=>t.run).find(r=>r?.id===runId),p=run?.result?.proposals?.find(p=>p.id===proposalId);if(!p||!run.result_sha256)throw Error('建议已不可用，请刷新');s.review={thread_id:s.thread.id,run_id:runId,proposal_id:proposalId,result_sha256:run.result_sha256,context_sha256:s.thread.context_sha256,page:canonical(current()),location:canonical(pageSnapshot())};const proposed=p.input?.parameters||p.input||{},baseline=s.thread.context.input||{},fields=p.operation==='restock_plan'?stocks:units,rows=Object.keys(fields).filter(k=>Object.hasOwn(proposed,k)&&canonical(baseline[k])!==canonical(proposed[k])).map(k=>({key:k,label:fields[k],before:baseline[k],after:proposed[k]})),diff=ui.fieldDiff&&['unit_economics','restock_plan'].includes(p.operation)?ui.fieldDiff({rows,beforeLabel:'当前范围参数',afterLabel:'建议任务参数'}):'';modal('审阅本地建议',`<p>${esc(p.reason)}</p><p><strong>对象与范围：</strong>${esc(scope(s.thread.context))}</p><p><strong>操作：</strong>${esc(({report:'生成本地简报',unit_economics:'计算单件贡献',restock_plan:'计算补货草稿',intel_review:'整理来源证据',organization_handoff:'创建岗位补齐待办',exposure_review:'创建经营关联复核'})[p.operation]||p.operation)}</p>${diff}<p class="muted">仅提交这一项本地任务；队列接收不代表执行完成。</p><details><summary>查看完整参数与依据</summary><pre class="copilot-review">${esc(JSON.stringify({context:s.thread.context,operation:p.operation,input:p.input},null,2))}</pre></details>`,button('确认参数并提交','apply'))}
  async function updateQueue(operation,itemId,revision=s.thread?.followups?.revision,message){
    if(s.busy||!s.thread)return;const threadId=s.thread.id;s.busy=true;s.error='';update();
    try{const result=await api('commerce_copilot_followup_change',{thread_id:threadId,item_id:itemId,expected_revision:revision,operation,...(message!==undefined?{message}:{})});if(s.thread?.id===threadId)s.thread.followups=result;return result;}
    finally{s.busy=false;update();}
  }
  async function uploadMaterial(file){
    if(!file||s.busy)return;
    if(file.size>2097152||file.size===0){s.error='单份资料需为1字节–2MB；请精简文件后添加。';update();return;}
    const ownerContext=canonical(current());s.busy=true;s.error='';update();
    try{
      await ensure();if(ownerContext!==canonical(current()))throw Error('页面范围已变化，请在原页面重新添加资料。');
      if(!features().materials)throw Error('当前后台尚未载入资料功能，普通对话仍可使用。');
      if(selectedMaterials().length>=4)throw Error('每轮最多选中4份资料，请先取消选择。');
      const types={txt:'text/plain',md:'text/markdown',csv:'text/csv',json:'application/json',pdf:'application/pdf',png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg'},mime=types[file.name.split('.').at(-1)?.toLowerCase()];
      if(!mime)throw Error('请选择文本、Markdown、CSV、JSON、PDF或图片文字资料。');
      const caps=await api('commerce_copilot_material_capabilities');if(!caps.supported_mime_types.includes(mime))throw Error(mime.startsWith('image/')?'本机图片文字提取暂不可用，请先提供文字。':'本机暂不支持此类资料的文字提取。');
      const bytes=new Uint8Array(await file.arrayBuffer());let binary='';if(!window.CommerceMaterialUpload)for(const byte of bytes)binary+=String.fromCharCode(byte);const content=binary?btoa(binary):'',threadId=s.thread.id,fingerprint=canonical({threadId,name:file.name,mime,content});
      let item;
      if(window.CommerceMaterialUpload){
        s.uploadContext=ownerContext;s.uploadThread=threadId;
        materialUploader??=window.CommerceMaterialUpload.create({api:originalApi,shouldContinue:()=>!disposed&&s.open&&s.thread?.id===s.uploadThread&&canonical(current())===s.uploadContext,onProgress:value=>{s.materialUpload=value;update()}});
        item=await materialUploader.upload({thread:s.thread,selected:{filename:file.name,mime_type:mime,bytes},caps});
      }else{
        if(file.size>65536)throw Error('当前界面仅支持64KB资料，请刷新后核对分片能力。');
        if(s.uploadRequest?.fingerprint!==fingerprint)s.uploadRequest={fingerprint,key:crypto.randomUUID()};
        item=await api('commerce_copilot_material_upload',{thread_id:threadId,context_sha256:s.thread.context_sha256,filename:file.name,mime_type:mime,content_base64:content,idempotency_key:s.uploadRequest.key});
      }
      if(s.thread?.id===threadId){s.thread.materials=[item,...(s.thread.materials||[]).filter(m=>m.id!==item.id)];if(item.model_usable!==false)s.materialSelections[key()]=[...selectedMaterials().filter(id=>id!==item.id),item.id];}
      s.uploadRequest=null;toast?.(item.model_usable===false?'资料已保存在本机，但未提取到可用文字；请预览核对或提供文字资料。':'资料已保存在本机；发送时才带入选中的提取文字。');
    }catch(error){if((error.code||error.message)==='copilot_upload_cancelled'){s.error='';toast?.('资料添加已取消，未发送模型。');return;}s.error=({'copilot_material_size_or_encoding':'文件超过当前后台允许的大小，请核对预检能力或精简文件。','copilot_material_hash_unavailable':'当前宿主不能校验大文件，请使用64KB以内资料。','copilot_upload_cancelled':'资料添加已取消，未发送模型。','copilot_upload_scope_changed':'页面范围已变化，已停止继续传输。','copilot_upload_pending_selection':'上一份资料尚未核对完成，请先取消添加，或重新选择同一文件核对。','copilot_upload_expired':'上传已过期，请重新选择文件。','copilot_upload_active_limit':'未完成的上传已达上限，请先取消或核对已有上传。','copilot_material_extraction_unavailable':'本机暂不能提取此类资料文字，请提供文字资料。'})[error.code||error.message]||'资料未确认添加：'+(errorText?errorText(error):error.message);}
    finally{s.busy=false;update();}
  }
  async function act(action,target){
    if(action==='context-details'){
      const original=replyingOriginal(),bound=original?originalPage():pageSnapshot()||{},entity=bound.entity||s.thread?.context.entity;
      modal('本轮上下文',`<dl class="copilot-context-details"><dt>位置</dt><dd>${esc(window.CommercePageContext?.label(bound)||scope({...current(),module:bound.page||current().module}))}</dd>${entity?`<dt>对象</dt><dd>${esc(entity.name||entity.id)}</dd>`:''}${Object.entries(bound.filters||{}).filter(([,value])=>value!==''&&value!==null&&value!==undefined).map(([name,value])=>`<dt>${esc(({country:'国家',region:'地区',query:'搜索',status:'状态',platform:'平台',market:'市场',store_id:'店铺',store_ref:'店铺引用',scope:'店铺视图',date_from:'开始日期',date_to:'结束日期',days:'统计天数',category:'分类',layer:'图层',view:'视图',page:'页码',limit:'每页条数'})[name]||name)}</dt><dd>${esc(name==='scope'?(value==='unassigned'?'未关联店铺':value==='all'?'全部店铺':`店铺视图 #${value.slice(-6)}`):value==='all'?'全部':value)}</dd>`).join('')}</dl><p>${original?'当前回复绑定原问题。':'当前问题使用本页已读取的对象与筛选。'}页面输入和资料不会扩大执行权限。</p>${Object.keys(bound.source_refs||{}).length?`<details><summary>来源版本</summary><pre class="copilot-review">${esc(JSON.stringify(bound.source_refs,null,2))}</pre></details>`:''}`,button('完成','interaction-close'));return;
    }
    if(action==='interaction-close'||action==='editor-close'){closeModal('copilot-message');update('copilot-message');return;}
    if(action==='expand-editor'){
      s.expandedDraftOwner=key();
      document.getElementById('copilot-more-trigger')?.focus({preventScroll:true});
      modal('展开编辑',`<label for="copilot-expanded-message">问题或补充回答</label><textarea class="ui-control copilot-expanded-editor" id="copilot-expanded-message" autofocus data-copilot-draft-key="${esc(key())}" rows="12" maxlength="2000">${esc(draft())}</textarea><p><span id="copilot-expanded-length">${draft().length} / 2000</span> · 输入自动保留到当前草稿</p><p id="copilot-expanded-error" role="alert"></p>`,button('完成编辑','editor-close'));return;
    }
    if(action==='copy-answer'){
      const run=(s.thread?.turns||[]).map(t=>t.run).find(run=>run?.id===target.dataset.run);if(!run?.result?.answer)return;
      const text=reading?.plainText(run.result.answer)||run.result.answer;
      try{if(!window.navigator?.clipboard?.writeText)throw Error('clipboard_unavailable');await window.navigator.clipboard.writeText(text);toast?.('已复制答复原文。');}
      catch{modal('复制答复',`<label for="copilot-copy-text">可选择并复制原文</label><textarea id="copilot-copy-text" class="ui-control copilot-expanded-editor" rows="10" readonly>${esc(text)}</textarea>`,button('完成','interaction-close'));}return;
    }
    if(action==='model-query-clear'){s.modelQuery='';const query=document.getElementById('copilot-model-query');if(query)query.value='';updateModelSearch();query?.focus({preventScroll:true});return;}
    if(action==='models-refresh'){await refreshModels();return;}
    if(action==='model-select'){await selectModel(target.dataset.model);return;}
    if(action==='steer'){await send('steer');return;}
    if(action==='material-upload-cancel'){await materialUploader?.cancel();s.materialUpload=null;update();return;}
    if(action==='material-select'){
      const item=s.thread?.materials?.find(m=>m.id===target.dataset.material);if(!item||item.stale||item.model_usable===false)return;
      const selected=selectedMaterials();if(!selected.includes(item.id)&&selected.length>=4){s.error='每轮最多选中4份资料。';update();return;}
      s.materialSelections[key()]=selected.includes(item.id)?selected.filter(id=>id!==item.id):[...selected,item.id];update();return;
    }
    if(action==='material-preview'){
      const threadId=s.thread?.id;if(!threadId)return;const item=await api('commerce_copilot_material_get',{thread_id:threadId,material_id:target.dataset.material});if(s.thread?.id!==threadId)return;
      let image='';if(['image/png','image/jpeg'].includes(item.mime_type)){const preview=await api('commerce_copilot_material_preview',{thread_id:threadId,material_id:item.id});if(s.thread?.id!==threadId)return;if(/^[A-Za-z0-9+/=]+$/.test(preview.content_base64))image=`<img class="copilot-material-preview" alt="本机资料原图" src="data:${item.mime_type};base64,${preview.content_base64}">`;}
      modal(item.filename||'对象资料',`${image}<p>${item.kind==='reference'?'当前对象的只读版本快照':'发送时带入提取文字，原文件保留在本机'}${['application/pdf','image/png','image/jpeg'].includes(item.mime_type)&&item.visual_understanding===false?'；不代表图像视觉理解':''}。${item.text_truncated?'文字已限量，未读取部分不能据此推断。':''}</p><pre class="copilot-material-text">${esc(item.text||'未提取到文字，请补充说明。')}</pre><details><summary>来源版本</summary><code>${esc(item.sha256)}</code></details>`,button('完成','interaction-close'));return;
    }
    if(action==='material-remove'){
      const item=s.thread?.materials?.find(m=>m.id===target.dataset.material);if(!item||s.busy)return;
      const threadId=s.thread.id;s.busy=true;update();try{await api('commerce_copilot_material_remove',{thread_id:threadId,material_id:item.id,expected_sha256:item.sha256});if(s.thread?.id===threadId){s.thread.materials=s.thread.materials.filter(m=>m.id!==item.id);s.materialSelections[key()]=selectedMaterials().filter(id=>id!==item.id);}}finally{s.busy=false;update();}return;
    }
    if(action==='reference-current'){
      if(s.busy)return;if(changed()&&!replyingOriginal())throw Error('请先切换到本页范围，或明确打开原会话再引用。');const page=canonical(current());s.busy=true;s.error='';update();try{
        await ensure();if(page!==canonical(current()))throw Error('页面范围已变化，请重新选择对象。');const entity=s.thread.context.entity;if(!entity||!features().materials)throw Error('请先选择本会话范围内的业务对象。');
        if(selectedMaterials().length>=4)throw Error('每轮最多选中4份资料。');const threadId=s.thread.id;
        const item=await api('commerce_copilot_material_reference',{thread_id:threadId,context_sha256:s.thread.context_sha256,kind:entity.kind,object_id:entity.id,idempotency_key:crypto.randomUUID()});
        if(s.thread?.id===threadId){s.thread.materials=[item,...(s.thread.materials||[]).filter(m=>m.id!==item.id)];s.materialSelections[key()]=[...selectedMaterials().filter(id=>id!==item.id),item.id];}
      }finally{s.busy=false;update();}return;
    }
    if(action==='queue-edit'){
      const item=s.thread?.followups?.items.find(item=>item.id===target.dataset.item);if(!item)return;
      s.queueEdit={thread:s.thread.id,item:item.id,revision:s.thread.followups.revision,message:item.message};
      modal('编辑后续消息',`<label for="copilot-queue-message">排队问题</label><textarea id="copilot-queue-message" autofocus class="ui-control copilot-expanded-editor" rows="6" maxlength="2000">${esc(item.message)}</textarea><p id="copilot-queue-edit-error" role="alert"></p>`,button('保存修改','queue-edit-save')+button('取消','interaction-close'));return;
    }
    if(action==='queue-edit-save'){
      const edit=s.queueEdit;if(!edit||edit.thread!==s.thread?.id)return;
      try{await updateQueue('edit',edit.item,edit.revision,edit.message);closeModal();s.queueEdit=null;update();}
      catch(error){const label=document.getElementById('copilot-queue-edit-error');if(label)label.textContent='队列已变化或保存未确认，请关闭后重新读取。当前编辑内容仍保留。';}return;
    }
    if(['queue-up','queue-down','queue-cancel','queue-next'].includes(action)){await updateQueue({'queue-up':'move_up','queue-down':'move_down','queue-cancel':'cancel','queue-next':'queue'}[action],target.dataset.item);return;}
    if(action==='queue-resume'){
      if(s.busy||!s.thread)return;const id=s.thread.id;s.busy=true;update();try{const result=await api('commerce_copilot_followup_resume',{thread_id:id,expected_revision:s.thread.followups.revision,context_sha256:s.thread.context_sha256});if(s.thread?.id===id)s.thread.followups=result;}finally{s.busy=false;update();}return;
    }
    if(action==='task-result-close'){s.taskResultRequest=(s.taskResultRequest||0)+1;closeModal();return}
    if(action==='task-result'){
      const taskId=target.dataset.task,known=(s.thread?.turns||[]).some(t=>(t.run?.actions||[]).some(a=>a.task_id===taskId));
      if(!known)throw Error('任务已变化，请刷新原会话。');
      const revision=s.taskResultRequest=(s.taskResultRequest||0)+1,threadId=s.thread.id,page=canonical(pageSnapshot());
      const receipt=await api('commerce_task_result',{task_id:taskId}),output=receipt.execution?.result;
      if(disposed||revision!==s.taskResultRequest||threadId!==s.thread?.id||page!==canonical(pageSnapshot()))return;
      const states={queued:'任务排队中',running:'任务执行中',completed:'本地任务已完成',failed:'任务未完成',interrupted:'任务已中断',cancelled:'任务已取消'};
      modal('任务结果',`<p role="status">${esc(states[receipt.task.status]||'结果待核对')}</p>${receipt.execution?.error?ui.alert('任务未完成，请核对原资料后重试。','warning'):''}${output?(window.CommerceAssistantEvidence?.archive(output,esc)||`<pre class="copilot-prose">${esc(output.content||JSON.stringify(output,null,2))}</pre>`):'<p>尚无完成结果，请刷新查看后续回执。</p>'}`,button('刷新结果','task-result',{'data-task':taskId})+button('关闭','task-result-close'));
      return;
    }
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
    if(action==='generative-workspace'){const run=[s.thread?.latest_run,...(s.thread?.turns||[]).map(t=>t.run)].find(r=>r?.id===target.dataset.run),card=run?.presentation?.components?.find(c=>c.id===target.dataset.component),id=card?.data?.case_id||card?.data?.target?.case_id;if(id&&onOpenCandidate)onOpenCandidate(id);return}if(action==='workspace'){onWorkspace?.();return}if(action==='close'){close();return}if(action==='send'){await send();return}if(action==='older'){if(readingWindow?.range(s.thread).before){readingWindow.move(s.thread,-1);s.startAtTop=true;update('copilot-log')}else{await older();if(readingWindow&&s.thread){readingWindow.move(s.thread,-1);update()}}return}if(action==='newer'||action==='newest'){if(!s.thread||s.busy)return;if(action==='newest'){readingWindow?.latest(s.thread);s.forceLatest=true}else{readingWindow?.move(s.thread,1);s.startAtTop=true}update('copilot-log');return}if(action==='use-answers'){setDraft(key(),Object.entries(s.answers).filter(([,v])=>v.trim()).map(([k,v])=>k+'：'+v).join('\n'));s.focus={id:'copilot-message'};update();return}if(action==='reply'){s.focus={id:'copilot-message'};update();return}if(action==='suggest'){setDraft(key(),researchPrompts()[Number(target.dataset.suggestion)]?.[1]||'根据当前范围，建议下一步怎么做');s.focus={id:'copilot-message'};update();return}if(action==='fields'){s.form=!s.form;update();return}if(action==='review'){review(target.dataset.run,target.dataset.proposal);return}if(s.busy)return;s.load++;s.busy=true;s.error='';update();try{
    if(action==='refresh'||action==='models-refresh')await load();
    if(action==='new'){s.load++;s.thread=null;s.newThread=true;s.openKey=null;s.request=null;s.review=null;s.fields={};s.answers={};s.form=false;s.focus={id:'copilot-message'};s.scroll={bottom:true}}
    if(action==='context'){if(!s.thread)await ensure();accept(await api('commerce_copilot_context',{thread_id:s.thread.id,context:current(),expected_context_sha256:s.thread.context_sha256}));s.review=null}
    if(action==='cancel'&&s.thread){accept(await api('commerce_copilot_cancel',{thread_id:s.thread.id,run_id:target.dataset.run}))}
    if(action==='save-fields'){await ensure();const calc=s.fields.calculator||s.thread.context.calculator||'unit_economics',fields=calc==='restock_plan'?stocks:units,input={};for(const k of Object.keys(fields)){const v=s.fields[k]??s.thread.context.input?.[k];if(v!==undefined&&v!==''){if(k==='currency'){if(!/^[A-Z]{3}$/.test(v))throw Error('币种请填写三位大写代码');input[k]=v}else{const n=Number(v);if(!Number.isFinite(n)||n<0)throw Error('请核对 '+fields[k]);input[k]=n}}}accept(await api('commerce_copilot_context',{thread_id:s.thread.id,context:{...s.thread.context,calculator:calc,input},expected_context_sha256:s.thread.context_sha256}));s.form=false;s.scopeOverride={thread:s.thread.id,page:canonical(current()),context:clone(s.thread.context)};s.review=null;toast?.('测算数据已保存，请明确发送问题')}
    if(action==='apply'){const r=s.review;if(!r||r.thread_id!==s.thread?.id||r.context_sha256!==s.thread.context_sha256||r.page!==canonical(current())||r.location!==canonical(pageSnapshot())||changed())throw Error('范围已变化，请关闭并重新审阅');const {page,location,...args}=r;await api('commerce_copilot_apply',args);s.review=null;closeModal();await load();toast?.('已提交本地任务，请查看任务回执')}
  }finally{s.busy=false;update(action==='models-refresh'?'copilot-model-refresh':undefined)}}
  // Explicit calculator additions belong to the thread; compare page context separately.
  function open(context,options={}){if(disposed)return;followPage();if(context&&canonical(context)!==canonical(current())){s.error='打开时提供的范围与页面不同，请核对当前页面。'}s.opener=document.activeElement;s.open=true;s.focus=options.focus===false?null:{id:'copilot-message'};s.scroll||={top:0,bottom:!!s.thread?.turns?.length};if(repaint)repaint();else update();load().catch(e=>{s.error='读取会话失败：'+e.message;update()})}
  // Async navigation may select a different thread before this editor commits its composition.
  function finishComposition(element){const owner=editorOwner(element);s.composing=false;s.compositionKey=null;s.compositionElement=null;if(typeof element?.value==='string')setDraft(owner,element.value)}
  function close(){stopRunWatch();if(s.composing)finishComposition(s.compositionElement);s.pendingPaint=false;s.pendingFocus=null;s.open=false;s.capabilityComposing=false;s.modelMenu=false;s.load++;s.review=null;s.focus=null;update();layout();if(!inline){const opener=s.opener?.isConnected?s.opener:s.opener?.id?document.getElementById(s.opener.id):null;const target=opener||[...document.querySelectorAll('[data-action="copilot-open"]')].find(el=>el.getClientRects().length);target?.focus?.({preventScroll:true})}}
  function contextChanged(){if(disposed||!s.open)return;followPage();capabilityPicker?.contextChanged();const page=canonical(current());if(s.page!==page){s.capabilityComposing=false;s.modelMenu=false;s.page=page;if(compact&&!s.thread?.turns?.length)s.startAtTop=true}s.review=null;update();if(compact&&!s.thread&&!s.newThread&&!s.busy&&!draft().trim())load().catch(error=>{s.error='读取会话失败：'+error.message;update()})}
  function resizeComposer(value,save=false){const input=document.getElementById('copilot-message');if(!input)return;const css=window.getComputedStyle(input),min=parseFloat(css.minHeight)||64,max=parseFloat(css.maxHeight)||360;composerHeight=value===0?0:Math.max(min,Math.min(max,value));syncComposer();if(save)try{localStorage.setItem('commerce-copilot-composer-height-v1',String(composerHeight))}catch{}}
  listen(document,'pointerdown',e=>{const handle=e.target.closest?.('[data-copilot-resize]'),input=document.getElementById('copilot-message');if(!handle||!input||e.button!==0)return;e.preventDefault();handle.focus({preventScroll:true});composerDrag={id:e.pointerId,y:e.clientY,height:input.getBoundingClientRect().height,handle};try{handle.setPointerCapture(e.pointerId)}catch{}});
  listen(document,'pointermove',e=>{if(!composerDrag||e.pointerId!==composerDrag.id)return;e.preventDefault();resizeComposer(composerDrag.height+composerDrag.y-e.clientY)});
  const endResize=e=>{if(!composerDrag||e.pointerId!==composerDrag.id)return;try{composerDrag.handle.releasePointerCapture(e.pointerId)}catch{}composerDrag=null;resizeComposer(composerHeight,true)};
  listen(document,'pointerup',endResize);listen(document,'pointercancel',endResize);
  listen(document,'dblclick',e=>{if(e.target.closest?.('[data-copilot-resize]'))resizeComposer(0,true)});
  listen(document,'input',e=>{if(capabilityPicker?.handleInput(e))return;if(e.target.id==='copilot-model-query'){s.modelQuery=e.target.value;if(!e.isComposing&&!s.modelComposing)updateModelSearch();return}if(e.target.id==='copilot-queue-message'&&s.queueEdit){s.queueEdit.message=e.target.value;return}if(e.target.id==='copilot-expanded-message'){const owner=s.expandedDraftOwner||editorOwner(e.target);setDraft(owner,e.target.value);const count=document.getElementById('copilot-expanded-length');if(count)count.textContent=e.target.value.length+' / 2000';if(owner===key()){const main=document.getElementById('copilot-message');if(main)main.value=e.target.value;syncComposer();}return;}if(e.target.id==='copilot-history-query'){s.historyQuery=e.target.value;const list=document.getElementById('copilot-history-list');if(list&&!s.historyLoading)list.innerHTML=historyRows()}if(e.target.id==='copilot-message'){const owner=s.compositionKey||(e.target.isConnected===false?e.target.dataset?.copilotDraftKey:null)||key();if(e.target.dataset)e.target.dataset.copilotDraftKey=owner;setDraft(owner,e.target.value);syncComposer();}if(e.target.dataset?.copilotAnswer)s.answers[e.target.dataset.copilotAnswer]=e.target.value;if(e.target.dataset?.copilotField)s.fields[e.target.dataset.copilotField]=e.target.value});
  listen(document,'focusin',e=>{if(e.target.closest?.('#commerce-copilot')&&e.target.id)remember()});
  listen(document,'select',e=>{if(e.target.closest?.('#commerce-copilot'))remember()},true);
  listen(document,'keyup',e=>{if(e.target.closest?.('#commerce-copilot'))remember()});
  listen(document,'change',e=>{if(e.target.id==='copilot-file'){document.getElementById('copilot-more-picker')?.removeAttribute('open');const file=e.target.files?.[0];e.target.value='';void uploadMaterial(file);return}if(e.target.id==='copilot-send-key'){s.sendKey=e.target.value==='enter'?'enter':'mod-enter';try{localStorage.setItem('commerce-copilot-send-key-v1',s.sendKey);s.settingsNotice=''}catch{s.settingsNotice='快捷键偏好仅本次页面有效。'}update();return;}if(e.target.id==='copilot-model'){selectModel(e.target.value);return}if(e.target.id==='copilot-calculator'){s.fields.calculator=e.target.value;update()}if(e.target.id==='copilot-thread'&&!s.busy){if(!e.target.value){act('new',e.target);return}const id=e.target.value,seq=++s.load;s.busy=true;api('commerce_copilot_get',{thread_id:id}).then(t=>{if(seq===s.load){accept(t);s.newThread=false;s.review=null;s.fields={};s.answers={};s.form=false;s.focus={id:'copilot-thread'};s.scroll={bottom:true}}}).catch(e=>{s.error=e.message}).finally(()=>{s.busy=false;update()})}});
  listen(document,'click',e=>{if(e.target.closest?.('[data-copilot-capability-action]')){s.modelMenu=false;document.getElementById('copilot-model-picker')?.removeAttribute('open');document.getElementById('copilot-more-picker')?.removeAttribute('open');void capabilityPicker?.handleClick(e).catch(error=>{s.error=error.message;update()});return}void capabilityPicker?.handleClick(e);if(e.target.closest?.('[data-generative-image]')){e.preventDefault();void window.CommerceGenerativeUI?.image(e,api);return}const picker=document.querySelector('#copilot-model-picker[open]');if(picker&&!picker.contains(e.target)){s.modelMenu=false;picker.removeAttribute('open')}const options=document.querySelector('.copilot-options[open]');if(options&&!options.contains(e.target))options.removeAttribute('open');const t=e.target.closest?.('[data-copilot-action]');if(!t)return;e.preventDefault();t.closest('.copilot-options')?.removeAttribute('open');t.closest('.copilot-compose-more')?.removeAttribute('open');if(t.dataset.copilotAction==='models'){s.modelMenu=false;t.closest('#copilot-model-picker')?.removeAttribute('open')}act(t.dataset.copilotAction,t).catch(error=>{s.error='操作未完成：'+error.message;toast?.(s.error);update()})});
  listen(document,'toggle',e=>{if(e.target.id==='copilot-more-picker')layoutMore();if(e.target.id==='copilot-model-picker'){s.modelMenu=e.target.open;if(e.target.open&&document.activeElement?.id==='copilot-model-trigger')document.getElementById('copilot-model-query')?.focus({preventScroll:true})}},true);
  listen(document,'focusin',e=>{const picker=document.querySelector('#copilot-model-picker[open]');if(picker&&!picker.contains(e.target)){s.modelMenu=false;picker.removeAttribute('open')}});
  listen(document,'compositionstart',e=>{if(e.target.id==='copilot-capability-query'){s.capabilityComposing=true;return;}if(e.target.id==='copilot-model-query'){s.modelComposing=true;return}if(['copilot-message','copilot-expanded-message'].includes(e.target.id)){s.composing=true;s.compositionKey=e.target.id==='copilot-expanded-message'?(s.expandedDraftOwner||editorOwner(e.target)):editorOwner(e.target);if(e.target.dataset)e.target.dataset.copilotDraftKey=s.compositionKey;s.compositionElement=e.target}});
  listen(document,'compositionend',e=>{if(e.target.id==='copilot-capability-query'){s.capabilityComposing=false;capabilityPicker?.handleInput(e);s.pendingPaint=false;s.pendingFocus=null;update();return;}if(e.target.id==='copilot-model-query'){s.modelComposing=false;s.modelQuery=e.target.value;updateModelSearch();return}if(!['copilot-message','copilot-expanded-message'].includes(e.target.id))return;finishComposition(e.target);if(s.pendingPaint){s.pendingPaint=false;const focus=s.pendingFocus;s.pendingFocus=null;update(focus)}});
  listen(document,'keydown',e=>{if(capabilityPicker?.keydown(e))return;if(modelKeys(e))return;if(e.target.id==='copilot-expanded-message'&&e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.isComposing&&!s.composing&&e.keyCode!==229){e.preventDefault();if((s.expandedDraftOwner||editorOwner(e.target))!==key()){const text='此编辑框属于原会话，请返回原会话再发送；两处草稿均已保留。';const error=document.getElementById('copilot-expanded-error');if(error)error.textContent=text;toast?.(text);return;}closeModal('copilot-message');update('copilot-message');void send();return;}if(e.target.closest?.('[data-copilot-resize]')&&['ArrowUp','ArrowDown','Home','End'].includes(e.key)){e.preventDefault();const input=document.getElementById('copilot-message');resizeComposer(e.key==='Home'?0:e.key==='End'?480:input.getBoundingClientRect().height+(e.key==='ArrowUp'?16:-16),true);return}if(!s.open||!isActive()||document.querySelector('.dialog'))return;const picker=document.querySelector('#copilot-model-picker[open]');if(picker&&e.key==='Escape'){e.preventDefault();s.modelMenu=false;picker.removeAttribute('open');picker.querySelector('summary')?.focus();return}const more=document.querySelector('#copilot-more-picker[open]');if(more&&e.key==='Escape'){e.preventDefault();more.removeAttribute('open');more.querySelector('summary')?.focus();return}if(s.history&&e.key==='Escape'){e.preventDefault();s.history=false;s.historyLoad++;s.historyLoading=false;s.focus={id:'copilot-history-toggle'};update('copilot-history-toggle');return}const options=document.querySelector('.copilot-options[open]');if(compact&&options&&e.key==='Escape'){e.preventDefault();options.removeAttribute('open');options.querySelector('summary')?.focus();return}if(e.key==='Escape'&&!inline){e.preventDefault();close();return}if(e.target.id==='copilot-message'&&e.key==='Enter'&&((e.ctrlKey||e.metaKey)||(s.sendKey==='enter'&&!e.shiftKey&&!e.altKey))&&!e.isComposing&&!s.composing&&e.keyCode!==229){e.preventDefault();send();return}if(e.key==='Tab'&&!inline&&window.innerWidth<1280){const nodes=[...document.querySelectorAll('#commerce-copilot button:not(:disabled),#commerce-copilot input:not(:disabled),#commerce-copilot select:not(:disabled),#commerce-copilot textarea,#commerce-copilot [tabindex="0"]')].filter(n=>n.getClientRects().length),first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&(document.activeElement===first||!document.activeElement.closest?.('#commerce-copilot'))){e.preventDefault();last?.focus()}else if(!e.shiftKey&&(document.activeElement===last||!document.activeElement.closest?.('#commerce-copilot'))){e.preventDefault();first?.focus()}}});
  listen(window,'resize',()=>{if(s.open){layout();syncComposer()}});
  let pollRequest=null,pollError='',lastFullPoll=0,streamUnsupported=false,runWatch=null,streamRetryAt=0;
  function stopRunWatch(){const previous=runWatch;runWatch=null;previous?.dispose?.()}
  const currentWatch=watch=>!disposed&&runWatch===watch&&s.open&&isActive()&&!s.busy&&!document.querySelector('.dialog')&&s.load===watch.seq&&s.thread?.id===watch.id&&s.thread.latest_run?.id===watch.run&&canonical(current())===watch.page;
  function observeRun(){
    const watch={id:s.thread.id,run:s.thread.latest_run.id,seq:s.load,page:canonical(current()),dispose:null};
    runWatch=watch;
    const valid=()=>{if(currentWatch(watch))return true;if(runWatch===watch)stopRunWatch();return false};
    const clearError=()=>{if(pollError&&s.error===pollError)s.error='';pollError=''};
    watch.dispose=window.CommerceRunEvents.observe({api:originalApi,thread:s.thread,runId:watch.run,pollMs:500,
      onEvent:event=>{
        if(!valid()||event.type!=='STATE_SNAPSHOT')return;
        const value=event.snapshot;
        if(value.backend_thread_id!==watch.id||value.backend_run_id!==watch.run||!active.has(value.status))return;
        const run=s.thread.latest_run,stream={cursor:value.cursor,answer:value.stream_answer,components:value.generative_components,provisional:value.provisional,mode:value.stream_mode,truncated:value.stream_truncated};
        const changed=canonical(run.stream)!==canonical(stream)||run.status!==value.status,hadError=!!pollError;
        run.stream=stream;run.status=value.status;const turn=s.thread.turns.find(t=>t.run.id===run.id);if(turn)turn.run=run;
        clearError();if(changed||hadError)update();
      },
      onComplete:thread=>{if(!valid())return;stopRunWatch();streamRetryAt=0;lastFullPoll=Date.now();accept(thread);clearError();update()},
      onError:(error,thread)=>{
        if(!valid())return;stopRunWatch();streamRetryAt=Date.now()+2000;
        if(thread){accept(thread);clearError()}
        else{if((error.code||error.message)==='unknown_tool')streamUnsupported=true;pollError='状态读取未完成：'+(errorText?errorText(error):error.message);s.error=pollError}
        update();
      }
    });
  }
  async function pollThread(){
    if(runWatch&&!currentWatch(runWatch))stopRunWatch();
    if(disposed||!s.open||!isActive()||s.busy||document.querySelector('.dialog')||!s.thread||!(active.has(s.thread.latest_run?.status)||researchWatching()||receiptWatching()||s.thread?.followups?.items?.some(item=>['queued','waiting'].includes(item.status))))return;
    if(active.has(s.thread.latest_run?.status)&&!researchJob(s.thread.latest_run)&&!streamUnsupported&&window.CommerceRunEvents){
      if(runWatch||pollRequest)return;
      if(Date.now()>=streamRetryAt){observeRun();return}
    }
    const id=s.thread.id,seq=s.load,page=canonical(current());
    if(pollRequest?.id===id&&pollRequest.seq===seq&&pollRequest.page===page)return;
    const request={id,seq,page};pollRequest=request;
    const currentRequest=()=>!disposed&&s.open&&isActive()&&!s.busy&&pollRequest===request&&s.load===seq&&s.thread?.id===id&&canonical(current())===page&&!document.querySelector('.dialog');
    try{
      const run=s.thread.latest_run;
      if(active.has(run?.status)&&!researchJob(run)&&!streamUnsupported&&!window.CommerceRunEvents){
        try{
          const value=await originalApi('commerce_copilot_events',{thread_id:id,run_id:run.id,after:run.stream?.cursor||0});if(!currentRequest())return;
          if(active.has(value.status)){
            if((run.stream?.cursor||0)!==value.snapshot.cursor||run.status!==value.status){run.stream=value.snapshot;run.status=value.status;const turn=s.thread.turns.find(t=>t.run.id===run.id);if(turn)turn.run=run;update()}
            if(pollError&&s.error===pollError){s.error='';pollError='';update()}return;
          }
        }catch(error){if((error.code||error.message)==='unknown_tool')streamUnsupported=true;else throw error;}
      }else if(Date.now()-lastFullPoll<2000)return;
      const thread=await api('commerce_copilot_get',{thread_id:id});if(!currentRequest())return;lastFullPoll=Date.now();accept(thread);if(pollError&&s.error===pollError)s.error='';pollError='';update()
    }
    catch(error){if(currentRequest()){pollError='状态读取未完成：'+error.message;s.error=pollError;update()}}
    finally{if(pollRequest===request)pollRequest=null}
  }
  const polling=setInterval(pollThread,500);
  function dispose(){if(disposed)return;stopRunWatch();disposed=true;s.open=false;s.load++;s.historyLoad++;clearInterval(polling);materialUploader?.dispose();draftStorage.dispose();capabilityPicker?.dispose();listeners.splice(0).forEach(remove=>remove())}
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

/* Readable projections only: original platform documents remain unchanged. */
window.CommerceCatalogPresentation=(()=>{
  const e=value=>window.CommerceUI.escape(String(value??''));
  function plain(value){
    const entities={nbsp:' ',amp:'&',lt:'<',gt:'>',quot:'"',apos:"'"};
    return String(value??'').replace(/&(#x[0-9a-f]+|#\d+|nbsp|amp|lt|gt|quot|apos);/gi,(_,key)=>{
      if(key[0]!=='#')return entities[key.toLowerCase()]||_;
      const n=key[1]?.toLowerCase()==='x'?parseInt(key.slice(2),16):Number(key.slice(1));
      return Number.isInteger(n)&&n>0&&n<=0x10ffff&&!(n>=0xd800&&n<=0xdfff)?String.fromCodePoint(n):_;
    }).replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi,'').replace(/<(?:br\s*\/?|\/?p|\/?div|\/?li|\/?h[1-6])\b[^>]*>/gi,'\n').replace(/<[^>]*>/g,'').replace(/\r/g,'').replace(/[ \t]+/g,' ').replace(/\n\s*\n\s*\n/g,'\n\n').trim();
  }
  function readable(value,key){
    let data;try{data=typeof value==='string'?JSON.parse(value):value;}catch{return null;}
    if(key==='attributes'&&Array.isArray(data))return data.slice(0,100).map(row=>{
      if(!row||typeof row!=='object'||!Array.isArray(row.values))return null;
      const label=plain(row.name||row.label||('平台属性 '+String(row.id??'未知')));
      const values=row.values.slice(0,100).map(v=>typeof v?.value==='string'?plain(v.value):'').filter(Boolean);
      return values.length?{label,value:values.join('、')}:null;
    }).filter(Boolean);
    if(data&&typeof data==='object'&&!Array.isArray(data)){
      const labels={depth:'长 / 深',length:'长度',width:'宽度',height:'高度',dimension_unit:'尺寸单位',weight:'重量',weight_unit:'重量单位',status_name:'商品状态',status_description:'状态说明',moderate_status:'平台审核状态',validation_status:'平台校验状态'};
      return Object.entries(data).slice(0,40).map(([name,v])=>({label:labels[name]||name,value:plain(v&&typeof v==='object'?JSON.stringify(v):v)}));
    }
    return null;
  }
  function textBlock(value){const text=plain(value);if(!text)return '<span class="muted">未提供</span>';return text.length<=600?`<p class="catalog-readable-text">${e(text)}</p>`:`<p class="catalog-readable-text">${e(text.slice(0,600))}…</p><details><summary>展开完整内容</summary><p class="catalog-readable-text">${e(text)}</p></details>`;}
  function field(field){
    const rows=readable(field.original,field.key);
    const body=rows?.length?`<dl class="catalog-readable-pairs">${rows.slice(0,5).map(r=>`<div><dt>${e(r.label)}</dt><dd>${textBlock(r.value)}</dd></div>`).join('')}</dl>${rows.length>5?`<details><summary>其余 ${rows.length-5} 项属性</summary><dl class="catalog-readable-pairs">${rows.slice(5).map(r=>`<div><dt>${e(r.label)}</dt><dd>${textBlock(r.value)}</dd></div>`).join('')}</dl></details>`:''}`:textBlock(field.original);
    return `${body}<details class="catalog-original"><summary>查看原始字段</summary><pre>${e(typeof field.original==='string'?field.original:JSON.stringify(field.original,null,2))}</pre></details>`;
  }
  const storeLabel=item=>item?.store_identity?.label||(item?.store_identity?.kind==='research_candidate'||item?.kind==='candidate'?'调研候选 · 尚未绑定店铺':'店铺身份待核对');
  function scopes(item){return [...new Set((item?.inventory_scopes||[]).map(r=>r.inventory_type).filter(Boolean))].map(v=>({fbs:'FBS',rfbs:'realFBS',fbo:'FBO'})[v]||v).join(' / ');}
  return {plain,readable,field,textBlock,storeLabel,scopes};
})();

/* Read-only index over original local media. No copies, model calls or approvals. */
window.CommerceMediaLibrary=({api,repaint,isActive=()=>true,onProduct,synthetic=false})=>{
 const ui=window.CommerceUI,e=ui.escape,id=crypto.randomUUID(),LIMIT=20,MAX=8*1024*1024,CHUNK=48*1024;
 const kindNames={all:'全部素材',product_image:'产品原图',competitor_image:'竞品原图',supplier_image:'货源原图',generated_image:'AI生成图片',video:'视频',reference_image:'参考图片',audio:'音频',document:'文档与图文材料',other:'其他素材'};
 const storageNames={registered_local_file:'已登记本地文件 · 读取时核对',missing_local_file:'本地文件缺失',missing_or_invalid_local_file:'本地文件缺失或登记不符',link_only:'仅有来源链接 · 未保存本地文件',source_archived:'原来源已归档'};
 const s={query:'',appliedQuery:'',storeRef:'all',kind:'all',items:[],stores:[],total:null,offset:0,next:null,loading:false,error:'',issues:[],listGeneration:0,mediaGeneration:0,media:null,hidden:false,disposed:false};
 const urls=new Set(),timers=new Map();
 const active=()=>!s.disposed&&!s.hidden&&isActive();
 const paint=()=>{if(!active())return;const prior=document.activeElement,focusId=prior?.id,restore=!!focusId&&own(prior),start=prior?.selectionStart,end=prior?.selectionEnd;repaint();if(restore&&!prior.isConnected&&document.activeElement===document.body){const current=document.getElementById?.(focusId);if(current&&!current.disabled){current.focus({preventScroll:true});if(start!=null&&current.setSelectionRange)current.setSelectionRange(start,end)}}};
 const controlId=(action,rowId='')=>'media-library-'+id+'-'+action+(rowId?'-'+String(rowId).replace(/[^a-zA-Z0-9_-]/g,'-'):'');
 const button=(label,action,attrs={})=>ui.button({label,attrs:{id:controlId(action,attrs['data-media-id']),'data-media-library-action':action,...attrs}});
 const integer=v=>Number.isSafeInteger(v)&&v>=0;
 const sha=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
 const rowById=value=>s.items.find(row=>row.id===value);
 const scope=()=>JSON.stringify([synthetic,s.appliedQuery,s.storeRef,s.kind,s.offset]);
 function release(url){if(!url)return;clearTimeout(timers.get(url));timers.delete(url);if(urls.delete(url))URL.revokeObjectURL(url)}
 function closeMedia(){++s.mediaGeneration;for(const url of [...urls])release(url);s.media=null}
 function fileSize(value){return !integer(value)?'大小未知':value<1024?value+' B':value<1024*1024?(value/1024).toFixed(1)+' KB':(value/1024/1024).toFixed(2)+' MB'}
 function dimensions(row){return Number.isFinite(row.width)&&row.width>0&&Number.isFinite(row.height)&&row.height>0?row.width+' × '+row.height+' px':'尺寸未知'}
 function storeLabel(identity){return identity?.kind==='research_candidate'?'调研候选 · 未绑定店铺':identity?.kind==='store'?(identity.label||'店铺名称待核对'):'未知店铺 / 未绑定'}
 function sourceLabel(row){return row.origin==='product_evidence'?(row.source_kind==='supplier'?'货源证据':row.source_kind==='competitor'?'竞品证据':'商品证据'):'原创意项目'}
 function reviewLabel(row){return row.kind==='generated_image'||row.role==='generated'||String(row.asset_kind).startsWith('generated')?'AI生成 · 当前用途未审核':'当前用途待审核'}
 function canRead(row){
  if(row?.preview?.available!==true||!integer(row.size)||row.size<1||row.size>MAX||!sha(row.sha256))return false;
  const p=row.preview,args=p.arguments;
  if(!args||typeof args!=='object'||Array.isArray(args))return false;
  if(p.tool==='commerce_creative_asset_read')return row.origin==='creative'&&typeof args.project_id==='string'&&!!args.project_id&&typeof args.asset_id==='string'&&!!args.asset_id&&args.project_id===row.project_id&&args.asset_id===row.asset_id&&args.offset==='0'&&Object.keys(args).every(k=>['project_id','asset_id','offset'].includes(k));
  if(p.tool==='commerce_product_evidence_image')return row.origin==='product_evidence'&&typeof args.case_id==='string'&&!!args.case_id&&typeof args.entry_id==='string'&&!!args.entry_id&&args.case_id===row.case_id&&args.entry_id===row.entry_id&&args.expected_entry_sha256===row.entry_sha256&&sha(args.expected_entry_sha256)&&args.index===row.image_index&&integer(args.index)&&args.index<=11&&args.offset===0&&Object.keys(args).every(k=>['case_id','entry_id','expected_entry_sha256','index','offset'].includes(k));
  return false;
 }
 function unavailable(row){return row.size>MAX?'文件超过8 MB，请在原项目处理。':row.preview?.available!==true?(storageNames[row.storage_status]||'本地文件暂不可读。'):!integer(row.size)||row.size<1||!sha(row.sha256)?'大小或SHA登记不完整，暂不读取。':'读取范围尚未核对，暂不读取。'}
 function previewable(row){if(['video','audio'].includes(row.kind))return false;return row.kind!=='other'||Number.isFinite(row.width)&&row.width>0&&Number.isFinite(row.height)&&row.height>0}
 function matchesStore(row,filter){const x=row.store_identity;if(filter==='all')return true;if(filter==='unassigned')return x?.kind==='unassigned';if(filter==='research_candidates')return x?.kind==='research_candidate';return filter===x?.account_id||filter===x?.connection_id}
 function validList(result,request){return result&&result.synthetic===synthetic&&Array.isArray(result.items)&&result.items.length<=LIMIT&&integer(result.total)&&result.offset===request.offset&&result.limit===LIMIT&&result.items.length===Math.min(LIMIT,Math.max(0,result.total-request.offset))&&result.next_offset===(request.offset+result.items.length<result.total?request.offset+result.items.length:null)&&new Set(result.items.map(row=>row.id)).size===result.items.length&&result.items.every(row=>row&&typeof row.id==='string'&&row.synthetic===synthetic&&matchesStore(row,request.store_ref)&&(request.kind==='all'||row.kind===request.kind))&&Array.isArray(result.stores)&&result.store_facets_complete===true}
 async function load(offset=0){
  if(!active())return;closeMedia();s.appliedQuery=s.query.trim().slice(0,200);s.offset=offset;s.loading=true;s.error='';s.items=[];s.total=null;s.next=null;s.issues=[];
  const generation=++s.listGeneration,key=scope(),request={synthetic,query:s.appliedQuery,store_ref:s.storeRef,kind:s.kind,limit:LIMIT,offset};paint();
  try{const result=await api('commerce_media_library_list',request);if(!active()||generation!==s.listGeneration||key!==scope())return;if(!validList(result,request))throw Error('media_scope_invalid');s.items=result.items;s.stores=result.stores;s.total=result.total;s.next=result.next_offset;s.issues=Array.isArray(result.issues)?result.issues:[]}
  catch{if(active()&&generation===s.listGeneration&&key===scope()){s.error='本地素材索引暂不可读，请刷新后核对。';s.items=[];s.total=null;s.next=null}}
  finally{if(active()&&generation===s.listGeneration&&key===scope()){s.loading=false;paint()}}
 }
 async function enter(){if(s.disposed)return;s.hidden=false;await load(s.offset)}
 function requestCurrent(generation,key,row){return active()&&generation===s.mediaGeneration&&key===scope()&&rowById(row.id)===row}
 function packetBytes(packet,row,offset,firstMime){
  if(!packet||packet.size!==row.size||packet.sha256!==row.sha256||typeof packet.mime!=='string'||packet.mime.length>100||/[\r\n]/.test(packet.mime)||firstMime&&packet.mime!==firstMime||typeof packet.content_base64!=='string'||packet.content_base64.length>65536||packet.content_base64.length%4||!/^[A-Za-z0-9+/]*={0,2}$/.test(packet.content_base64))throw Error('media_packet_invalid');
  const raw=atob(packet.content_base64),bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));
  if(bytes.length!==Math.min(CHUNK,row.size-offset))throw Error('media_size_changed');
  const next=offset+bytes.length;
  if(row.preview.tool==='commerce_creative_asset_read'){
   if(packet.next_offset!==String(next)||typeof packet.done!=='boolean'||packet.done!==(next===row.size))throw Error('media_offset_invalid');
  }else if(packet.status!=='archived'||packet.next_offset!==(next===row.size?null:next))throw Error('media_offset_invalid');
  return bytes;
 }
 function imageType(bytes,mime){
  const prefix=(...values)=>values.every((v,i)=>bytes[i]===v);
  if(prefix(137,80,78,71,13,10,26,10))return 'image/png';
  if(prefix(255,216,255))return 'image/jpeg';
  if(prefix(82,73,70,70)&&[87,69,66,80].every((v,i)=>bytes[8+i]===v))return 'image/webp';
  if(prefix(71,73,70,56)&&(bytes[4]===55||bytes[4]===57)&&bytes[5]===97)return 'image/gif';
  return null;
 }
 function filename(row,mime){const extensions={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','image/gif':'.gif','application/json':'.json','text/plain':'.txt','text/csv':'.csv','video/mp4':'.mp4','video/webm':'.webm','audio/wav':'.wav'},type=mime.split(';')[0].trim().toLowerCase(),base=String(row.display_name||row.asset_id||'local-media').replace(/[\\/<>:"|?*\u0000-\u001f]/g,'-').replace(/^\.+/,'').slice(0,100)||'local-media';const ext=extensions[type]||'.bin';return base.toLowerCase().endsWith(ext)?base:base+ext}
 async function read(row,mode){
  if(!active()||!canRead(row)||s.media?.id===row.id&&s.media.phase==='loading')return;
  closeMedia();const generation=s.mediaGeneration,key=scope();s.media={id:row.id,label:row.display_name||kindNames[row.kind]||'本地素材',phase:'loading',mode,received:0,total:row.size};paint();document.querySelector?.(`[data-media-library-id="${id}"] .media-library-preview`)?.focus({preventScroll:false});
  try{
   if(!crypto.subtle?.digest)throw Error('media_hash_unavailable');
   let offset=0,mime='',parts=[];
   while(offset<row.size){
    if(!requestCurrent(generation,key,row))return;
    const args={...row.preview.arguments,offset:row.preview.tool==='commerce_creative_asset_read'?String(offset):offset},packet=await api(row.preview.tool,args);
    if(!requestCurrent(generation,key,row))return;
    const bytes=packetBytes(packet,row,offset,mime);mime=mime||packet.mime;parts.push(bytes);offset+=bytes.length;s.media.received=offset;paint();
   }
   const bytes=new Uint8Array(row.size);let position=0;for(const part of parts){bytes.set(part,position);position+=part.length}parts=[];
   const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
   if(!requestCurrent(generation,key,row))return;if(digest!==row.sha256)throw Error('media_hash_mismatch');
   if(mode==='download'){
    const url=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));urls.add(url);
    if(!requestCurrent(generation,key,row)){release(url);return}
    const link=document.createElement('a');link.href=url;link.download=filename(row,mime);document.body.append(link);link.click();link.remove();if(!requestCurrent(generation,key,row)){release(url);return}timers.set(url,setTimeout(()=>release(url),5000));
    s.media={id:row.id,label:s.media.label,phase:'downloaded',mode,total:row.size,mime};
   }else{
    const imageMime=imageType(bytes,mime),type=mime.split(';')[0].trim().toLowerCase();
    if(imageMime){const url=URL.createObjectURL(new Blob([bytes],{type:imageMime}));urls.add(url);s.media={id:row.id,label:s.media.label,phase:'ready',mode,url,total:row.size,mime:imageMime}}
    else if(['application/json','text/plain','text/csv','text/html'].includes(type)){const text=new TextDecoder('utf-8').decode(bytes);s.media={id:row.id,label:s.media.label,phase:'ready',mode,text:text.slice(0,100000),textTruncated:text.length>100000,total:row.size,mime}}
    else{s.media={id:row.id,label:s.media.label,phase:'unsupported',mode,total:row.size,mime}}
   }
  }catch{if(requestCurrent(generation,key,row)){closeMedia();s.media={id:row.id,label:row.display_name||'所选素材',phase:'failed',mode,error:'素材读取或SHA核对未通过，未展示或下载文件。请回原项目核对登记与本地文件。'}}}
  finally{if(active()&&key===scope())paint()}
 }
 function mediaView(){const m=s.media;if(!m)return '';return `<section id="${e(controlId('preview-panel'))}" class="card media-library-preview" tabindex="-1" aria-live="polite" aria-label="所选素材预览"><div class="media-library-heading"><h3>${e(m.label)}</h3>${button('关闭预览 / 回执','close')}</div>${m.phase==='loading'?`<p role="status">正在${m.mode==='download'?'核对下载文件':'读取所选素材'}… ${e(fileSize(m.received))} / ${e(fileSize(m.total))}</p>`:m.phase==='failed'?ui.alert(m.error,'danger'):m.phase==='downloaded'?ui.alert('文件SHA已核对，并已请求浏览器下载；请核对本机下载结果。'):m.phase==='unsupported'?ui.empty('文件SHA已核对；此格式不提供内嵌预览，请下载或在原项目查看。'):m.url?`<img src="${e(m.url)}" alt="${e(m.label)} · 本地素材预览">`:`<p class="muted">以下为本地文件原文；HTML标签仅作为文字展示。${m.textTruncated?'仅预览前100000字符，完整内容请下载核对。':''}</p><pre class="media-library-text">${e(m.text)}</pre>`}${['ready','downloaded','unsupported'].includes(m.phase)?'<p class="muted">文件SHA核对通过只确认当前字节与登记相符，不代表内容审核、商用权或发布批准。</p>':''}</section>`}
 function rowView(row){const identity=row.store_identity,readable=canRead(row),loading=s.media?.id===row.id&&s.media.phase==='loading';return `<article class="media-library-item"><div class="media-library-heading"><h3>${e(row.display_name||kindNames[row.kind]||'未命名素材')}</h3>${ui.badge(kindNames[row.kind]||'其他素材','gray')}</div><p class="media-library-product">${e(row.product_name||row.project_name||'商品名称待核对')}</p><p class="muted">${e(storeLabel(identity))} · ${e(identity?.platform||'平台未知')} / ${e(identity?.market||'市场未知')}<br>SKU ${e(row.sku||'未知')} · 商品编号 ${e(row.product_id||'未知')}</p><p>${ui.badge(reviewLabel(row),'gray')}${row.review_status==='local_review_recorded'?` ${ui.badge('原请求有本地审阅记录','gray')}`:''}</p><dl class="media-library-facts"><div><dt>来源</dt><dd>${e(sourceLabel(row))}${row.source_label?' · '+e(row.source_label):''}</dd></div><div><dt>本地状态</dt><dd>${e(storageNames[row.storage_status]||'状态待核对')}</dd></div><div><dt>尺寸 / 大小</dt><dd>${e(dimensions(row))} · ${e(fileSize(row.size))}${row.rendition==='thumbnail'?' · 已标记缩略图':''}${Number.isFinite(row.duration_seconds)&&row.duration_seconds>0?' · '+e(row.duration_seconds)+'秒':''}</dd></div><div><dt>来源记录</dt><dd>${e(row.source_url||row.source_reference||'来源未登记')}</dd></div><div><dt>原项目 / 证据</dt><dd>${e(row.project_name||row.project_id||row.entry_id||'未关联')}${row.entry_revision?' · 来源v'+e(row.entry_revision):''}</dd></div><div><dt>SHA-256</dt><dd class="media-library-sha">${e(sha(row.sha256)?row.sha256:'未登记')}</dd></div></dl><div class="media-library-actions">${button('预览图片 / 原文','preview',{'data-media-id':row.id,disabled:!readable||!previewable(row)||loading})}${button('下载本地文件','download',{'data-media-id':row.id,disabled:!readable||loading})}${row.product_readable===true&&row.case_id&&typeof onProduct==='function'?button('查看原商品','product',{'data-media-id':row.id}):''}</div>${!readable?`<p class="muted">${e(unavailable(row))}</p>`:!previewable(row)?'<p class="muted">视频、音频等格式请下载或在原项目处理，当前页面不播放。</p>':''}${identity?.kind==='store'&&identity.active===false?'<p class="muted">该素材属于已保存的非当前店铺；原商品入口不可用时，不会切换店铺。</p>':''}${row.review_status==='local_review_recorded'?'<p class="muted">原请求审阅仅适用于原请求，当前用途和发布仍待核对。</p>':''}</article>`}
 function storeOptions(){const values=[{value:'all',label:'全部本地素材'},{value:'unassigned',label:'未知店铺 / 未绑定'},{value:'research_candidates',label:'调研候选 · 未绑定店铺'}],seen=new Set(values.map(v=>v.value));for(const item of s.stores){if(typeof item.store_ref!=='string'||seen.has(item.store_ref))continue;seen.add(item.store_ref);values.push({value:item.store_ref,label:(item.label||'店铺名称待核对')+(item.active===true?' · 当前活跃':item.kind==='store'?' · 非当前店铺':'')})}if(!seen.has(s.storeRef))values.push({value:s.storeRef,label:'所选店铺 · 当前条件无素材选项'});return values}
 function view(){if(s.disposed||s.hidden)return '';const known=s.items.filter(row=>row.store_identity?.kind==='store'),research=s.items.filter(row=>row.store_identity?.kind==='research_candidate'),unknown=s.items.filter(row=>!['store','research_candidate'].includes(row.store_identity?.kind));return `<section class="media-library" data-media-library-id="${e(id)}" aria-busy="${s.loading}" aria-label="本地素材库"><header><h2>本地素材库</h2><p class="muted">按原店铺、商品和来源索引已登记素材。${synthetic?'当前为合成资料。':'当前为真实资料。'}仅显式点击读取本地文件，不自动访问远端来源。</p></header><form data-media-library-search><div class="media-library-controls">${ui.field('搜索商品、SKU或素材',ui.input({id:'media-library-query-'+id,type:'search',value:s.query,maxlength:200,placeholder:'输入名称、SKU或来源'}))}${ui.field('准确店铺归属',ui.select({id:'media-library-store-'+id,value:s.storeRef,options:storeOptions()}))}${ui.field('素材类型',ui.select({id:'media-library-kind-'+id,value:s.kind,options:Object.entries(kindNames).map(([value,label])=>({value,label}))}))}${button('搜索','search',{disabled:s.loading})}${button('刷新索引','refresh',{disabled:s.loading})}</div></form><p class="muted">AI生成素材默认当前用途未审核，文件名不能证明通过。原请求审阅不等于商用或发布批准；预览与下载上限为8 MB。</p>${s.error?ui.alert(s.error,'danger'):''}${s.loading?ui.empty('正在读取本地素材索引…'):''}${s.issues.length?ui.alert('部分来源完整性未能读取，当前列表可能不完整；请回原商品核对。'):''}${mediaView()}${[['已归属店铺素材',known],['调研候选素材',research],['未知店铺 / 未绑定素材',unknown]].filter(([,rows])=>rows.length).map(([title,rows])=>`<section class="media-library-group"><h3>${title}</h3><div class="media-library-grid">${rows.map(rowView).join('')}</div></section>`).join('')}${!s.loading&&!s.error&&s.total===0?ui.empty('当前筛选没有已登记的本地素材。'):''}<div class="media-library-pagination">${button('上一页','prev',{disabled:s.loading||s.offset===0})}<span>${s.total===null?'素材总数待核对':s.total===0?'共0项':!s.items.length?'共'+s.total+'项 · 当前页无记录':`${s.offset+1}–${s.offset+s.items.length} / 共${s.total}项`}</span>${button('下一页','next',{disabled:s.loading||s.next===null})}</div></section>`}
 const own=target=>target?.closest?.(`[data-media-library-id="${id}"]`);
 const submit=event=>{if(active()&&own(event.target)&&event.target.matches?.('[data-media-library-search]')){event.preventDefault();load(0)}};
 const input=event=>{if(active()&&event.target.id==='media-library-query-'+id)s.query=event.target.value.slice(0,200)};
 const change=event=>{if(!active())return;if(event.target.id==='media-library-store-'+id){const value=event.target.value;if(!storeOptions().some(v=>v.value===value))return;s.storeRef=value;load(0)}else if(event.target.id==='media-library-kind-'+id&&Object.hasOwn(kindNames,event.target.value)){s.kind=event.target.value;load(0)}};
 const click=event=>{if(!active())return;const b=event.target.closest?.('[data-media-library-action]');if(!b||!own(b)||b.disabled)return;event.preventDefault();const action=b.dataset.mediaLibraryAction,row=rowById(b.dataset.mediaId);if(action==='search'||action==='refresh')return load(0);if(action==='prev')return load(Math.max(0,s.offset-LIMIT));if(action==='next'&&s.next!==null)return load(s.next);if(action==='close'){const m=s.media;closeMedia();paint();if(m)document.getElementById?.(controlId(m.mode==='download'?'download':'preview',m.id))?.focus({preventScroll:true});return}if(action==='product'&&row?.product_readable===true&&row.case_id&&typeof onProduct==='function'){closeMedia();onProduct(row.case_id);return}if((action==='preview'||action==='download')&&row&&(action==='download'||previewable(row)))return read(row,action)};
 const listeners={submit,input,change,click};for(const [name,handler]of Object.entries(listeners))document.addEventListener(name,handler);
 function hide(){s.hidden=true;++s.listGeneration;closeMedia();s.loading=false;s.items=[];s.total=null;s.next=null}
 function dispose(){if(s.disposed)return;hide();s.disposed=true;for(const [name,handler]of Object.entries(listeners))document.removeEventListener(name,handler)}
 return {enter,view,hide,dispose};
};

/* Shared product/supply browsing. All media is read through the scoped backend. */
window.CommerceCatalog=({api,repaint,onSelect,onCreative,fixedKind,initialKind='all',getFilters,onItems,onQuery,directSelect=false,showStoreControls=true,showHeading=true})=>{
  const ui=window.CommerceUI,e=ui.escape,id=crypto.randomUUID(),identity=window.CommerceProductIdentity;
  const s={items:[],detail:null,query:'',kind:fixedKind||initialKind,page:0,importKind:'none',busy:false,error:'',epoch:0,image:0,store:null,storeError:'',storeNote:'',connection:'all',libraryActive:false};
  const presentation=window.CommerceCatalogPresentation||{storeLabel:d=>d.store_identity?.label||(d.kind==='candidate'?'调研候选 · 尚未绑定店铺':'店铺身份待核对'),scopes:()=>'',field:f=>e(f.original||'未提供'),textBlock:v=>e(v||'未提供')};
  const previews=new Map(),pending=new Set(),failed=new Set();let workers=0,disposed=false;
  const filters=()=>getFilters?.()||{};
  const filterKey=()=>JSON.stringify(filters());
  function matches(item,scope=filters()){return (scope.synthetic===undefined||item.synthetic===scope.synthetic)&&(!scope.market||scope.market==='all'||(item.market||item.case?.scope?.market)===scope.market)&&(!fixedKind||item.kind===fixedKind)&&(s.connection==='all'||(item.store_identity?.connection_id||'unassigned')===s.connection)}
  const scopedItems=()=>s.items.filter(item=>matches(item));
  const paint=()=>{if(!disposed)repaint()};
  let library=null,libraryMode=null;
  function ensureLibrary(){const mode=filters().synthetic===true;if(libraryMode!==mode){library?.dispose?.();library=null;libraryMode=mode;}if(!library)library=window.CommerceMediaLibrary?.({api,repaint:paint,synthetic:mode,isActive:()=>s.libraryActive&&!disposed&&filters().synthetic===mode,onProduct:caseId=>onSelect?.(caseId)});return library;}
  const quoteStatus={READY_FOR_SELECTION:'资料齐备 · 待选择',HOLD:'资料待补充',STALE:'资料已变化',EXPIRED:'已过期',CURRENCY_MISMATCH:'币种不一致',source_supplied:'来源提供 · 待核对'};
  const fieldLabels={title:'商品名称',description:'描述与卖点',attributes:'材质与规格',variants:'颜色与型号',price:'价格',images:'图片来源',dimensions:'尺寸',weight:'重量',category_id:'平台类目编号',type_id:'平台类型编号',platform_status:'平台状态',findings:'研究发现',limitations:'资料限制',category:'类目路径与编号',availability:'库存与可售状态',brand:'品牌与型号',barcode:'条码',fulfillment:'履约方式与仓库',policy_notes:'合规与资料冲突',product_id:'平台商品编号',reviews:'评论与评分',rich_content:'图文详情与媒体',search_context:'搜索与采集范围',subject:'调研主题与范围',video_context:'视频与直播样本',qualification:'品牌授权与类目资质',asin:'ASIN 与父子体关系',product_type:'商品类型与类目属性版本',bullet_points:'要点说明',gtin:'商品条码与豁免线索',item_id:'商品与站点编号',condition:'商品成色',listing_type:'刊登类型',shipping:'物流与配送条件',goods_id:'商品与SKU编号',operating_mode:'经营模式与站点',sales_attributes:'销售属性与变体',compliance:'产地与类目合规'};
  const button=(label,action,attrs={})=>ui.button({label,attrs:{'data-catalog-action':action,...attrs}});
  const money=d=>d.price==null?(d.price_text||'价格待补充'):`${d.currency||'币种待核对'} ${d.price}`;
  const imageKey=(d,i)=>d.id+':'+d.source_sha256+':'+(d.images[i]?.id||i);
  function picture(d,i=0){const key=imageKey(d,i),url=previews.get(key);return `<div class="catalog-picture${d.images.length?'':' is-empty'}" data-catalog-image="${e(key)}" data-case="${e(d.id)}" data-image-index="${i}">${url?`<img src="${url}" alt="${e(d.name)} · 商品图片 ${i+1}" loading="lazy">`:`<span class="muted">${!d.images.length?'暂无商品图片':failed.has(key)?'图片暂不可用': '正在读取商品图片…'}</span>${failed.has(key)?button('重试图片','retry-image',{'data-key':key}):''}`}</div>`}
  async function enter(){
    if(disposed)return;
    const epoch=++s.epoch,scope=filterKey();s.libraryActive=false;library?.hide?.();s.detail=null;s.busy=true;s.error='';paint();
    try{
      const result=await api('commerce_catalog_list',{query:s.query,kind:fixedKind||s.kind});
      if(disposed||epoch!==s.epoch||scope!==filterKey())return;
      s.items=result.items;s.page=0;onItems?.(s.items);enrichIdentity(epoch);
      if(showStoreControls)await readStore();
    }catch{if(!disposed&&epoch===s.epoch&&scope===filterKey())s.error='商品资料暂不可读，请重试。'}
    finally{if(!disposed&&epoch===s.epoch&&scope===filterKey()){s.busy=false;paint()}}
  }
  function repaintIdentityUpdate(){
    const prior=document.activeElement,focusId=prior?.id,start=prior?.selectionStart,end=prior?.selectionEnd,direction=prior?.selectionDirection;
    const restore=!!focusId&&document.querySelector(`[data-catalog-instance="${id}"]`)?.contains(prior);
    paint();
    if(!restore||prior.isConnected||document.activeElement!==document.body)return;
    const current=document.getElementById(focusId);if(!current||current.disabled)return;
    current.focus({preventScroll:true});
    if(start!=null&&current.setSelectionRange&&current.type!=='number')current.setSelectionRange(start,end,direction||undefined);
  }
  function enrichIdentity(epoch){const items=s.items;api('commerce_agent_cases',{}).then(value=>{if(disposed||epoch!==s.epoch||s.items!==items)return;s.items=identity.merge(items,value.cases||[]);repaintIdentityUpdate()}).catch(()=>{})}
  let storeTimer=null;
  async function readStore(){if(disposed||!showStoreControls)return;try{const store=await api('commerce_catalog_store_status',{});if(disposed)return;s.store=store;s.storeError='';if(s.store.refresh?.status==='running')pollStore()}catch{if(!disposed)s.storeError='店铺读取状态暂不可用，请重试。'}}
  function pollStore(){if(disposed)return;clearTimeout(storeTimer);storeTimer=setTimeout(async()=>{if(disposed||!document.querySelector(`[data-catalog-instance="${id}"]`))return;await readStore();if(s.storeError){paint();return}const job=s.store?.refresh;if(job?.status==='running'){paint();return}if(job?.status==='failed'){s.storeError='商品资料读取未完成，原资料和草稿保留。请核对连接与库存后重试。';paint();return}s.storeNote=job?.status==='partial'?'部分商品资料已读取，描述或属性仍有缺项。':'商品资料已接入，仍需核实产品信息和素材权利。';const cid=s.detail?.id;if(cid)await open(cid);else await enter()},1200)}
  async function refreshStore(current=false){if(disposed||!showStoreControls)return;s.storeError='';s.storeNote='';await readStore();if(disposed)return;if(s.storeError)return paint();try{await api('commerce_catalog_store_refresh',{expected_stock_sha256:s.store.stock_sha256,...(current?{case_id:s.detail.id}:{})});await readStore();pollStore()}catch{s.storeError='未启动读取。请先在连接设置同步最新库存；原商品资料和编辑保持。'}paint()}
  function storeControls(){const store=s.store,job=store?.refresh;return `<div class="catalog-store-sync">${store?.configured?button(s.detail?'读取当前商品完整资料':'读取店铺商品资料',s.detail?'store-one':'store-all',{disabled:s.busy||job?.status==='running'||!store.stock_fresh||!!s.detail?.synthetic||s.detail?.kind==='candidate'}):''}${button('刷新读取状态','store-status',{disabled:s.busy})}${job?.status==='running'?'<span role="status">正在只读获取商品资料…</span>':''}${store?.configured&&!store.stock_fresh?'<span class="muted">请先同步最新店铺库存，再读取图文资料。</span>':''}${s.storeError?ui.alert(s.storeError,'danger'):''}${s.storeNote?`<p role="status">${e(s.storeNote)}</p>`:''}</div>`}
  async function open(caseId){
    if(disposed)return;
    const epoch=++s.epoch,scope=filterKey();s.busy=true;s.error='';paint();
    try{const d=await api('commerce_catalog_get',{case_id:caseId});if(disposed||epoch!==s.epoch||scope!==filterKey())return;if(!matches(d))throw Error('catalog_scope_changed');s.detail=d;s.openerCase=caseId;s.image=0}
    catch{if(!disposed&&epoch===s.epoch&&scope===filterKey())s.error='这条商品资料已变化或不属于当前范围，请刷新列表。'}
    finally{if(!disposed&&epoch===s.epoch&&scope===filterKey()){s.busy=false;paint();document.querySelector(`[data-catalog-instance="${id}"] h2`)?.focus()}}
  }
  function schedule(){if(disposed)return;queueMicrotask(()=>{if(disposed)return;const host=document.querySelector(`[data-catalog-instance="${id}"]`);if(!host)return;for(const node of host.querySelectorAll('[data-catalog-image]')){if(workers>=2)break;const key=node.dataset.catalogImage;if(previews.has(key)||pending.has(key)||failed.has(key))continue;const d=s.detail?.id===node.dataset.case?s.detail:s.items.find(x=>x.id===node.dataset.case),index=Number(node.dataset.imageIndex);if(!d?.images[index])continue;pending.add(key);workers++;api('commerce_catalog_image',{case_id:d.id,expected_source_sha256:d.source_sha256,index,image_id:d.images[index].id}).then(r=>{if(disposed)return;if(previews.size>=40)previews.delete(previews.keys().next().value);previews.set(key,`data:${r.mime};base64,${r.content_base64}`)}).catch(()=>{if(!disposed)failed.add(key)}).finally(()=>{pending.delete(key);workers--;if(disposed)return;const current=document.querySelector(`[data-catalog-instance="${id}"] [data-catalog-image="${CSS.escape(key)}"]`);if(current){const url=previews.get(key);current.innerHTML=url?`<img src="${url}" alt="商品来源图片" loading="lazy">`:`<span class="muted">图片暂不可用</span>${button('重试图片','retry-image',{'data-key':key})}`}schedule()})}})}
  function projectLabel(project,projects){
    const name=project.name||'创意项目',peers=projects.filter(other=>(other.name||'创意项目')===name);
    if(peers.length<2)return name;
    const projectId=String(project.id);let width=Math.min(8,projectId.length);
    while(width<projectId.length&&peers.some(other=>other.id!==project.id&&String(other.id).slice(-width)===projectId.slice(-width)))width++;
    return name+' · #'+projectId.slice(-width);
  }
  function pageContext(){
    const d=s.detail,scope={...filters(),...(d?.case?.scope||{})};
    const current=Object.fromEntries(['platform','market','store_id','store_ref','scope'].filter(key=>typeof scope[key]==='string').map(key=>[key,scope[key]]));
    return {section:d?'product-detail':'list',source:'local',entity:d?{kind:'case',id:d.id,name:d.name}:null,replace_filters:true,filters:{...current,query:s.query,category:({candidate:'调研候选',inventory:'已有商品',supply:'已有货源',all:'全部'})[fixedKind||s.kind]||'全部'},source_refs:d?.source_sha256?{case:d.source_sha256}:{},input:{}};
  }
  function detail(){const d=s.detail;return `<header class="catalog-detail-header">${button('返回商品列表','back')}<h2 tabindex="-1">${e(d.name)}</h2><div>${d.synthetic?ui.badge('合成验收资料','gray'):ui.badge(d.kind==='candidate'?'调研候选':'已有商品','blue')}${ui.badge('资料待核实','gray')}</div></header><div class="catalog-detail-grid"><div>${picture(d,s.image)}${d.images[s.image]?.source_current===false?ui.badge('历史商品资料图片 · 待核对','warning'):''}<div class="catalog-thumbnails">${d.images.map((_,i)=>button('图片 '+(i+1),'image',{'data-index':i,'aria-pressed':s.image===i})).join('')}</div></div><div><p class="catalog-price">${e(money(d))}</p><dl class="catalog-meta"><dt>所属店铺</dt><dd>${e(presentation.storeLabel(d))}</dd><dt>平台 / 市场</dt><dd>${e(d.case.scope.platform||'待补充')} / ${e(d.case.scope.market||'待补充')}</dd><dt>履约范围</dt><dd>${e(identity.meta(d).split(' · ').at(-1))}</dd>${d.source_scopes?.length>1?`<dt>同商品库存范围</dt><dd>${ui.select({id:'catalog-scope-'+id,value:d.id,options:d.source_scopes.map(scope=>({value:scope.case_id,label:({fbs:'FBS',rfbs:'realFBS',fbo:'FBO'})[scope.inventory_type]||scope.inventory_type||'原工作项'}))})}</dd>`:''}<dt>SKU / 工作项</dt><dd>${e(d.case.scope.sku||'未提供 SKU · '+d.id.slice(-8))}</dd><dt>采集时间</dt><dd>${e(d.captured_at?new Date(d.captured_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'未记录')}</dd></dl>${d.source_url?`<a href="${e(d.source_url)}" target="_blank" rel="noopener noreferrer">查看原始来源</a>`:''}<div class="form-actions">${button('进入商品工作区','select')}${button('导出商品信息卡','export-card')}${onCreative&&d.images.length?ui.field('带入创意项目的图片用途',ui.select({'data-catalog-import':id,value:s.importKind,options:[{value:'none',label:'只建立项目'},{value:'product_image',label:'当前图作为产品资料图片'},{value:'reference_image',label:'当前图作为设计参考'}]})):''}${onCreative?button('建立图片与视频创意项目','creative',{'class':'primary',disabled:s.busy||!d.source_intact}):''}</div>${onCreative&&d.projects.length?`<h3>关联创意项目</h3>${d.projects.map(p=>button(projectLabel(p,d.projects)+(p.source_current?'':' · 资料待更新'),'project',{'data-project':p.id})).join('')}`:''}</div></div>${ui.card({title:'商品资料与规格',content:'<p class="muted">俄文为平台原文；属性已按结构展示。原始字段保留供核对，中文资料不会由猜测补齐。</p>'+ui.table(['项目','原文资料','中文校对','资料状态'],d.fields.map(f=>`<tr><td>${e(Object.hasOwn(fieldLabels,f.key)?fieldLabels[f.key]:f.key)}</td><td class="catalog-text">${presentation.field(f)}</td><td class="catalog-text">${f.zh?presentation.textBlock(f.zh):'<span class="muted">尚无中文校对</span>'}</td><td>${ui.badge(f.kind==='platform_unverified'?'平台返回 · 待核实':f.kind==='inference'?'推断':f.reviewed?'已校对 · 待核实':'待校对','gray')}</td></tr>`))})}${ui.card({title:'货源与报价',content:d.suppliers.length?ui.table(['供应方','原币采购价','起订量','交期','来源 / 状态'],d.suppliers.map(q=>`<tr><td>${e(q.supplier||'未提供')}</td><td>${e(q.purchase_cost==null?'未提供':(q.currency||'币种待核对')+' '+q.purchase_cost)}</td><td>${e(q.moq??'未提供')}</td><td>${e(q.lead_time_days==null?'未提供':q.lead_time_days+'天')}</td><td><span class="catalog-text">${e(q.source_ref||'未提供')}</span><small>${e(quoteStatus[q.status]||'资料待核对')}</small></td></tr>`)):ui.empty('尚无货源报价，可在商品工作区补充。')})}`}
  function view(){if(disposed)return '';if(s.libraryActive)return `<section class="catalog-browser" data-catalog-instance="${id}">${button('返回商品列表','library-back')}${library?library.view():ui.alert('素材库组件尚未载入，请刷新当前版本。','warning')}</section>`;schedule();if(s.detail&&!matches(s.detail))s.detail=null;const items=scopedItems(),rows=items.slice(s.page*20,s.page*20+20),title=fixedKind==='candidate'?'商品候选':'商品与货源';return `<section class="catalog-browser${fixedKind?' catalog-fixed-kind':''}" data-catalog-instance="${id}" data-ai-context="${e(JSON.stringify(pageContext()))}" aria-label="${fixedKind==='candidate'?'已保存商品候选':'商品与货源浏览'}" aria-busy="${s.busy}">${s.error?ui.alert(s.error,'danger'):''}${showStoreControls?storeControls():''}${button('本地素材库','library')}${s.detail?detail():`<header class="catalog-toolbar">${showHeading?`<h2>${title}</h2>`:''}<form data-catalog-search><div>${ui.select({id:'catalog-store-'+id,value:s.connection,'aria-label':'所属店铺筛选',options:[{value:'all',label:'全部已读店铺 / 候选'},...[...new Map(s.items.map(item=>[item.store_identity?.connection_id||'unassigned',presentation.storeLabel(item)])).entries()].map(([value,label])=>({value,label}))]})}${ui.input({id:'catalog-query-'+id,value:s.query,type:'search',placeholder:'搜索商品、规格或供应方','aria-label':fixedKind==='candidate'?'搜索商品候选':'搜索商品与货源'})}${fixedKind?'':ui.select({id:'catalog-kind-'+id,value:s.kind,'aria-label':'商品来源筛选',options:[{value:'all',label:'全部商品'},{value:'candidate',label:'调研候选'},{value:'inventory',label:'已有商品'},{value:'supply',label:'已有货源'}]})}${button('搜索','search',{disabled:s.busy})}</div></form></header>${s.busy?'<p role="status">正在读取商品资料…</p>':''}<div class="catalog-grid">${rows.map(d=>`<article class="catalog-product">${button(identity.label(d,items),'open',{'data-case':d.id,class:'catalog-product-title',disabled:s.busy})}${picture(d)}<p class="catalog-card-store">${e(presentation.storeLabel(d))}</p><p class="catalog-card-sku">SKU ${e(d.sku||'待补充')} · ${e(d.platform||'平台待补充')} / ${e(d.market||'市场待补充')}</p><p class="catalog-price">${e(money(d))}</p><p class="muted">${e(presentation.scopes(d))}${d.source_scopes?.length>1?' · '+d.source_scopes.length+'个库存范围':''}</p><div class="catalog-card-meta">${ui.badge(d.synthetic?'合成资料':d.kind==='candidate'?'调研候选':'已有商品','gray')}<span>${e(d.supplier_count?d.supplier_count+'条货源':'货源待补充')}</span></div>${directSelect?button('查看资料','preview',{'data-case':d.id,class:'link-btn catalog-product-preview',disabled:s.busy}):''}</article>`).join('')}</div>${!s.busy&&!rows.length?ui.empty(fixedKind==='candidate'?'当前范围暂无候选。':'当前范围暂无匹配商品。'):''}<div class="catalog-pagination">${button('上一页','prev',{disabled:s.busy||s.page===0})}<span>${items.length?`${s.page+1} / ${Math.ceil(items.length/20)}`:'0'} · ${items.length}件</span>${button('下一页','next',{disabled:s.busy||(s.page+1)*20>=items.length})}</div>`}</section>`}
  const submit=ev=>{if(ev.target.closest(`[data-catalog-instance="${id}"]`)&&ev.target.matches('[data-catalog-search]')){ev.preventDefault();enter()}};
  const input=ev=>{if(ev.target.id==='catalog-query-'+id){s.query=ev.target.value;onQuery?.(s.query)}};
  const change=ev=>{if(ev.target.id==='catalog-store-'+id){s.connection=ev.target.value;s.page=0;paint();return}if(ev.target.id==='catalog-scope-'+id){open(ev.target.value);return}if(ev.target.dataset.catalogImport===id)s.importKind=ev.target.value;if(ev.target.id==='catalog-kind-'+id){s.kind=ev.target.value;enter()}};
  const click=async ev=>{if(disposed)return;const b=ev.target.closest('[data-catalog-action]');if(!b||!b.closest(`[data-catalog-instance="${id}"]`))return;ev.preventDefault();if(b.disabled)return;const a=b.dataset.catalogAction;let working=false;try{if(a==='library'){s.libraryActive=true;ensureLibrary();paint();await library?.enter();return}if(a==='library-back'){s.libraryActive=false;library?.hide?.();paint();return}if(a.startsWith('store-')&&!showStoreControls)return;if(a==='store-all'||a==='store-one')return refreshStore(a==='store-one');if(a==='store-status'){await readStore();paint();return}if(a==='search')return enter();if(a==='preview')return open(b.dataset.case);if(a==='open'){if(directSelect){if(!scopedItems().some(item=>item.id===b.dataset.case))throw Error('catalog_scope_changed');return onSelect?.(b.dataset.case)}return open(b.dataset.case)}if(a==='back'){s.detail=null;paint();document.querySelector(`[data-catalog-instance="${id}"] [data-catalog-action=open][data-case="${s.openerCase}"]`)?.focus();return}if(a==='retry-image'){failed.delete(b.dataset.key);paint();return}if(a==='prev'||a==='next'){s.page=Math.max(0,Math.min(Math.max(0,Math.ceil(scopedItems().length/20)-1),s.page+(a==='next'?1:-1)));paint();return}if(a==='image'){s.image=Number(b.dataset.index);paint();return}if(a==='export-card'){const d=s.detail;if(!d)return;const card={schema:'commerce-product-information-card-v1',exported_at:new Date().toISOString(),case_id:d.id,product_key:d.product_key,store_identity:d.store_identity,sku:d.sku||d.case?.scope?.sku,product_id:d.product_id,name:d.name,source_sha256:d.source_sha256,captured_at:d.captured_at,inventory_scopes:d.inventory_scopes,fields:d.fields,images:d.images,quotes:d.suppliers,projects:d.projects,independently_verified:false,external_execution_allowed:false};const url=URL.createObjectURL(new Blob([JSON.stringify(card,null,2)],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download='product-'+String(card.sku||d.id).replace(/[^a-zA-Z0-9_-]/g,'_').slice(0,80)+'-info.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),2000);return;}if(a==='select')return onSelect?.(s.detail.id);if(a==='project')return onCreative?.({id:b.dataset.project});if(a==='creative'){working=true;s.busy=true;paint();const d=s.detail;if(!d.creativeKey)d.creativeKey=crypto.randomUUID();const p=await api('commerce_catalog_creative',{case_id:d.id,expected_source_sha256:d.source_sha256,idempotency_key:d.creativeKey});if(disposed)return;if(s.importKind!=='none'&&d.images.length)await api('commerce_catalog_image_import',{case_id:d.id,project_id:p.id,expected_source_sha256:d.source_sha256,index:s.image,image_id:d.images[s.image].id,kind:s.importKind});if(!disposed&&s.detail?.id===d.id)onCreative?.(p)}}catch{s.error='操作未完成，请核对当前商品资料后重试。';paint()}finally{if(working){s.busy=false;paint()}}};
  const listeners={submit,input,change,click};for(const [name,handler]of Object.entries(listeners))document.addEventListener(name,handler);
  function dispose(){disposed=true;library?.dispose?.();s.epoch++;clearTimeout(storeTimer);for(const [name,handler]of Object.entries(listeners))document.removeEventListener?.(name,handler);previews.clear();pending.clear();failed.clear()}
  return {view,enter,open,dispose,projectLabel};
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

/* Shared report view: technical checks never stand in for content review. */
window.CommerceMediaQualityView=report=>{
  if(!report)return '';
  const ui=window.CommerceUI,e=ui.escape,p=report.preflight||report,q=report.preflight?report:null;
  const labels={still_images_in_video:'包含静态图片',short_clip_looped:'短镜头将循环播放',repeated_source_media:'多个分镜复用同一素材',no_output_audio:'成片没有音轨',silent_output_audio:'仅保留静音轨道，没有素材原声',audio_padded_with_silence:'补充音轨较短，尾部补静音',audio_trimmed_to_timeline:'补充音轨较长，按成片时长裁剪',source_audio_has_silent_sections:'部分分镜没有原声',creative_clip_range_exceeded:'裁剪入点与时长超出素材范围',creative_local_tool_unavailable:'本机制作工具不可用',creative_invalid_media:'素材媒体信息无效',creative_timeline_invalid:'时间线存在缺口、重叠或时长不一致',creative_caption_too_long_shorten_product_facts:'字幕过长，请精简文字'};
  const kind={still_image_video_draft:'图文视频草稿',mixed_media_video_draft:'图片与视频混剪草稿',supplied_video_edit:'已有视频素材剪辑'};
  const message=x=>(labels[x.code]||'请核对素材与制作条件')+(x.shot_index==null?'':' · 分镜 '+(x.shot_index+1))+(x.tool?' · '+x.tool:'');
  const summary=p.summary;
  function observations(){
    const o=q?.media_observations;if(!o)return '';
    if(o.status==='unavailable')return ui.alert('画面与声音检测暂不可用；文件检查结果仍单独保留。','warning');
    const seconds=ms=>Math.round(ms/10)/100;
    const audio=o.audio?.status==='no_audio'?'没有音轨':`静音 ${seconds(o.audio.silent_duration_ms)}秒${o.audio.peak_dbfs==null?' · 未测得有限峰值电平':' · 峰值 '+o.audio.peak_dbfs+' dBFS'}`;
    const ranges=(label,rows)=>rows?.length?`<p>${e(label+'：'+rows.map(r=>seconds(r.start_ms)+'–'+seconds(r.end_ms)+'秒').join('，'))}</p>`:'';
    return `<div aria-label="画面与声音检测"><h4>画面与声音检测</h4>${o.status==='partial'?ui.alert('检测记录不完整，请结合实帧与原片核对。','warning'):''}<p>${e('黑场 '+seconds(o.video.black_duration_ms)+'秒 · 冻结画面 '+seconds(o.video.frozen_duration_ms)+'秒 · '+audio)}</p><p class="muted">黑场、冻结和静音可能来自有意的画面或转场，请结合原片审阅。</p><details><summary>检测位置与阈值</summary>${ranges('黑场',o.video.black_segments)}${ranges('冻结画面',o.video.frozen_segments)}${ranges('静音',o.audio.silent_segments)}<p class="muted">黑场至少0.1秒；冻结、低于−50 dBFS的静音至少0.5秒。</p></details></div>`;
  }
  const commitment=q?.delivery_commitment_check;
  const promise=commitment?`<p role="status">${e('交付要求检查：'+(commitment.status==='passed'?'通过 · 内容仍待人工审阅':'未通过 · 请调整后重新确认'))}</p>`:'';
  const reuse=q?.render_reuse;
  const reused=reuse?`<p class="muted">${e('本机制作：复用 '+reuse.reused_shot_indexes.length+'个镜头 · 新制作 '+reuse.rendered_shot_indexes.length+'个镜头')}</p>`:'';
  const frames=q?.review_frames?`<p class="muted">实帧总览包含 ${q.review_frames.samples.length}个成片取样，时间为近似位置。</p>`:'';
  return `<section class="media-review-report" aria-label="${q?'成片技术检查':'视频制作预检'}"><h3>${q?'成片技术检查':'视频制作预检'}</h3><p role="status">${e(q?(q.technical_status==='passed'?'文件技术检查通过 · 内容仍待人工审阅':'文件技术检查未通过'):(p.can_render?'可以本机制作':'请先解决制作问题'))}</p><p>${e(kind[p.delivery_kind]||'视频草稿')} · ${summary.duration_ms/1000}秒 · 静态图片 ${summary.still_duration_ms/1000}秒 · 视频素材 ${summary.video_duration_ms/1000}秒</p>${(p.errors||[]).map(x=>ui.alert(message(x),'danger')).join('')}${(p.warnings||[]).map(x=>ui.alert(message(x),'warning')).join('')}<p class="muted">视频占比按容器时长计算，实际动作、商品身份、台词与素材权利须人工审阅。</p>${q?`<p class="muted">${e(Object.entries({duration:'时长',dimensions:'画幅',audio_presence:'音轨',decode:'完整解码'}).map(([key,label])=>label+'：'+(q.checks[key]?'通过':'未通过')).join(' · '))}</p>`:''}${promise}${observations()}${frames}${reused}</section>`;
};

/* Local sample approval uses the existing request/review ledger. */
window.CommerceMediaDeliveryFlow=()=>{
  const ui=window.CommerceUI,e=ui.escape,settings=new Map(),acks=new Set(),keys=new Map();
  const defaults=r=>({source_policy:'allow_stills',audio_policy:'optional',allow_looping:false,sample_duration_ms:Math.min(1500,r.spec.duration_ms)});
  const options=r=>{if(!settings.has(r.id))settings.set(r.id,defaults(r));return settings.get(r.id)};
  const ackKey=r=>JSON.stringify([r.id,r.request_sha256,r.result_sha256,r.spec.delivery_commitment?.sha256]);
  const canApprove=r=>r.delivery?.role!=='sample'||acks.has(ackKey(r));
  const canExecute=r=>r.delivery?.role!=='full'||r.delivery.gate==='ready';
  const button=(label,id,busy)=>ui.button({label,attrs:{'data-media-action':'delivery-open','data-request':id,disabled:busy}});
  function view(r,busy){
    if(!r.spec.format?.endsWith('_video')&&!r.delivery)return '';
    const c=r.spec.delivery_commitment;
    if(!c){
      if(r.assets.length||r.job_id)return '';
      const d=options(r);
      const select=(label,key,values)=>ui.field(label,ui.select({'data-delivery-field':key,value:d[key],options:values.map(([value,label])=>({value,label}))}));
      return `<details class="media-editor"><summary>样片审批与交付承诺</summary><p class="muted">先选好分镜素材，再冻结本次时长、画幅、字幕和来源。样片取完整时间线的开头，通过后再明确启动完整制作。</p><div class="media-metric-fields">${select('画面来源','source_policy',[['allow_stills','允许图片与视频'],['video_only','全部使用视频素材']])}${select('声音要求','audio_policy',[['optional','音轨可选'],['audible_required','需要可听音轨'],['no_audio','不含音轨']])}${ui.field('样片时长（秒）',ui.input({type:'number',min:1,max:Math.min(5,r.spec.duration_ms/1000),step:0.001,value:d.sample_duration_ms/1000,'data-delivery-field':'sample_duration_ms'}))}</div><label class="media-check"><input type="checkbox" data-delivery-field="allow_looping" ${d.allow_looping?'checked':''}>允许短视频素材循环</label><div class="form-actions">${ui.button({label:'保存交付承诺并建立样片',variant:'primary',attrs:{'data-media-action':'delivery-prepare',disabled:busy||r.stale}})}</div></details>`;
    }
    const d=r.delivery,requirement=c.requirements;
    const status=d.role==='sample'?'样片用于核对本次完整制作要求':({ready:'样片已通过 · 可明确启动完整制作',sample_rejected:'样片已退回 · 请返回来源版本调整',sample_required:'等待样片产出并审批'})[d.gate];
    const ack=d.role==='sample'&&r.assets.length&&!r.review?`<label class="media-check"><input type="checkbox" data-delivery-field="ack" ${acks.has(ackKey(r))?'checked':''}>已完整观看本次样片，并确认符合本次交付要求</label>`:'';
    return `<section class="media-review-report" aria-label="样片审批与交付承诺"><h3>${d.role==='sample'?'样片审批':'完整制作交付承诺'}</h3><p>${e('完整成片 '+c.duration_ms/1000+'秒 · '+c.width+'×'+c.height+' · MP4 · 样片为开头 '+requirement.sample_duration_ms/1000+'秒')}</p><p>${e((requirement.source_policy==='video_only'?'全部使用视频素材':'允许图片与视频')+' · '+({optional:'音轨可选',audible_required:'需要可听音轨',no_audio:'不含音轨'})[requirement.audio_policy]+' · '+(requirement.allow_looping?'允许循环':'不循环'))}</p><p role="status">${e(status)}</p><p class="muted">素材、字幕与制作版本已固定；变更时从来源版本重新确认。样片通过仅允许本次本机制作，成片仍须单独审阅。</p>${button(d.role==='sample'?'查看完整制作版本':'查看样片与审阅',d.role==='sample'?d.full_request_id:d.sample_request_id,busy)}${button('返回来源版本调整',d.source_request_id,busy)}${ack}</section>`;
  }
  function input(ev,r){
    const key=ev.target.dataset.deliveryField;if(!key||!r)return false;
    if(key==='ack'){if(ev.target.checked)acks.add(ackKey(r));else acks.delete(ackKey(r));return 'repaint'}
    const d=options(r);d[key]=key==='allow_looping'?ev.target.checked:key==='sample_duration_ms'?Math.round(Number(ev.target.value)*1000):ev.target.value;
    return true;
  }
  async function prepare(api,r,asset_ids,audio_asset_id){
    if(asset_ids.some(x=>!x))throw Error('creative_shot_assets_required');
    const args={request_id:r.id,expected_request_sha256:r.request_sha256,asset_ids,requirements:{...options(r)},...(audio_asset_id?{audio_asset_id}:{})};
    const key=JSON.stringify(args);if(!keys.has(key))keys.set(key,crypto.randomUUID());
    const result=await api('commerce_media_delivery_prepare',{...args,idempotency_key:keys.get(key)});keys.delete(key);return result;
  }
  const reviewArgs=r=>r.delivery?.role==='sample'?{sample_review:{watched:true,matches_commitment:true,commitment_sha256:r.spec.delivery_commitment.sha256}}:{};
  return {view,input,prepare,canApprove,canExecute,reviewArgs};
};

/* One product/design contract for image sets and both video formats. */
window.CommerceMediaFlow=({api,repaint,getProject,onProject,onPreview,onPreparation,localDraftView})=>{
  const ui=window.CommerceUI,e=ui.escape;
  const labels={layout:'布局与信息层级',elements:'视觉元素',style:'视觉风格',colors:'色彩',typography:'文字与字级',selling_points:'卖点表达',shots:'镜头与特写',rhythm:'节奏与叙事',adaptation:'结合自己产品的调整',avoid:'避免照搬与失真'};
  const names={product_main:'商品主图',product_features:'卖点展示',product_detail:'细节特写',usage_scene:'使用场景',product_gallery:'产品展示',detail_page:'详情页图片',ugc_video:'UGC带货视频',showcase_video:'产品展示短视频'};
  const statuses={completed:'已完成',awaiting_media:'待制作 / 回收素材',queued:'已排队',running:'本机制作中',awaiting_review:'已产出 · 待审阅',approved:'已审阅通过',rejected:'已退回',failed:'制作失败',unknown:'结果未知',cancelled:'已取消',interrupted:'已中断'};
  const s={pid:'',revision:'',data:null,analysis:{},refs:[],analysisAsset:'',job:null,jobGeneration:0,analysisGeneration:0,analysisJobGeneration:0,actionGeneration:0,subtab:'direction',method:'local',busy:false,error:'',kind:'product_main',request:'',shots:{},attachment:'',audio:'',reviewNote:'',epoch:0,keys:new Map(),metrics:{},interval:'7',enabled:false,requestOpenGeneration:0,reportText:'',reportSource:'',reportPreview:null,reportOpen:false,preflight:null,edits:{},readinessError:false,imageProfile:"",imageRatio:"",imageCount:"6",imageLabel:"",imageFocus:"",directionBaseline:'',audioBaseline:'',shotsBaseline:{},editBaselines:{},optionsBaseline:null,policyBaseline:null};
  const delivery=window.CommerceMediaDeliveryFlow?.();
  const providers=window.CommerceMediaProvidersFlow?.({api,repaint,getProject,onProject,onPreview,onRefresh:()=>refresh(),onShots:(rid,index,asset)=>{s.shots[rid]||={};s.shots[rid][index]=asset}});
  const btn=(label,action,attrs={},primary=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{'data-media-action':action,...attrs}});
  const field=(label,key,value='',attrs={})=>ui.field(label,ui.input({value,'data-media-field':key,...attrs}));
  const area=(label,key,value='',rows=3)=>ui.field(label,`<textarea class="ui-control" id="media-${e(key.replaceAll('.','-'))}" data-media-field="${e(key)}" rows="${rows}" maxlength="${key==='reviewNote'?1200:key==='imageFocus'?1000:key==='reportText'?262144:2000}">${e(value)}</textarea>`);
  const assets=(p,kinds)=>p.assets.filter(a=>kinds.includes(a.kind)).map(a=>({value:a.id,label:(a.display_name||a.id.slice(0,8))+({image_layout_draft:' · 模板排版草稿',video_draft:' · 图文视频草稿'}[a.kind]||'')}));
  const select=(label,key,value,options)=>ui.field(label,ui.select({'data-media-field':key,value,options:[{value:'',label:'请选择实际素材'},...options]}));
  const directionSnapshot=(analysis=s.analysis,refs=s.refs)=>JSON.stringify([Object.keys(labels).map(key=>[key,String(analysis[key]??'')]),[...new Set(refs)].sort()]);
  const optionsSnapshot=()=>JSON.stringify(Object.fromEntries(['kind','imageProfile','imageRatio','imageCount','imageLabel','imageFocus'].map(key=>[key,s[key]])));
  const policySnapshot=()=>JSON.stringify([s.enabled,String(s.interval)]);
  function savedDirection(p,preserve=false){const analysis={...p.brief.design_direction?.analysis},refs=(p.brief.design_direction?.references||[]).map(r=>r.asset_id);s.directionBaseline=directionSnapshot(analysis,refs);if(!preserve){s.analysis=analysis;s.refs=refs;}}
  const draftValues=object=>Object.values(object).some(value=>value!==''&&value!==null&&value!==undefined);
  const shotSnapshot=shots=>JSON.stringify(Object.entries(shots||{}).filter(([,value])=>value!==''&&value!==null&&value!==undefined).sort(([a],[b])=>a<b?-1:a>b?1:0));
  const changedShots=()=>Object.keys({...s.shots,...s.shotsBaseline}).some(id=>shotSnapshot(s.shots[id])!==shotSnapshot(s.shotsBaseline[id]));
  function hasUnsavedChanges(){return !!getProject()&&s.pid===getProject().id&&(directionSnapshot()!==s.directionBaseline||!!s.reportText||!!s.reportSource||!!s.reviewNote||!!s.attachment||s.audio!==s.audioBaseline||draftValues(s.metrics)||changedShots()||Object.entries(s.edits).some(([id,edit])=>JSON.stringify(edit)!==s.editBaselines[id])||s.optionsBaseline!==null&&optionsSnapshot()!==s.optionsBaseline||s.policyBaseline!==null&&policySnapshot()!==s.policyBaseline);}
  function discardChanges(){const p=getProject();if(!p||s.pid!==p.id)return;savedDirection(p);s.analysisAsset='';s.analysisGeneration++;s.reportText='';s.reportSource='';s.reportPreview=null;s.reportOpen=false;s.reviewNote='';s.attachment='';s.metrics={};s.audio=s.audioBaseline;s.shots=structuredClone(s.shotsBaseline);s.edits=Object.fromEntries(Object.entries(s.editBaselines).map(([id,value])=>[id,JSON.parse(value)]));s.preflight=null;if(s.optionsBaseline!==null)Object.assign(s,JSON.parse(s.optionsBaseline));if(s.data?.policy){s.enabled=s.data.policy.enabled;s.interval=String(s.data.policy.interval_days);s.policyBaseline=policySnapshot();}}
  function resetProject(p){Object.assign(s,{pid:p.id,revision:'',data:null,request:'',refs:(p.brief.design_direction?.references||[]).map(r=>r.asset_id),analysis:{...p.brief.design_direction?.analysis},analysisAsset:'',shots:{},attachment:'',audio:'',reviewNote:'',job:null,analysisJobGeneration:0,metrics:{},error:'',subtab:'direction',method:'local',kind:'product_main',busy:false,reportText:'',reportSource:'',reportPreview:null,reportOpen:false,preflight:null,edits:{},readinessError:false,interval:'7',enabled:false,imageProfile:'',imageRatio:'',imageCount:'6',imageLabel:'',imageFocus:'',audioBaseline:'',shotsBaseline:{},editBaselines:{},optionsBaseline:null,policyBaseline:null});savedDirection(p);s.jobGeneration++;s.analysisGeneration++;s.actionGeneration++;}
  const analysisSource=p=>p.assets.find(a=>a.id===s.analysisAsset&&s.refs.includes(a.id)&&['reference_image','reference_video'].includes(a.kind));
  function repaintSelection(target){const id=target.id,focused=document.activeElement===target;repaint();if(focused&&id)queueMicrotask(()=>{if(document.activeElement===document.body||document.activeElement===document.documentElement)document.getElementById(id)?.focus({preventScroll:true})})}
  const currentAnalysis=()=>s.job?.input.kind==='design_analyze'&&s.analysisGeneration===s.analysisJobGeneration;
  const errorText=code=>({creative_sample_approval_required:'请先产出并明确审批本次样片，再启动完整制作。',creative_sample_review_required:'请完整观看本次样片，勾选确认并填写审阅说明。',creative_delivery_requirements_invalid:'请核对声音、画面来源及1–5秒的样片时长。',creative_delivery_video_required:'交付要求全部使用视频素材，请重新选择。',creative_delivery_audio_required:'交付要求可听音轨，请选择音轨或有原声的视频。',creative_delivery_audio_forbidden:'交付要求不含音轨，请关闭保留原音并取消配音。',creative_delivery_looping_forbidden:'交付要求不循环，请调整镜头时长或素材。',creative_delivery_renderer_changed:'制作工具已更新，请从来源版本重新建立样片与承诺。',creative_delivery_requirements_unmet:'成品未满足交付要求，请核对检查报告。',creative_delivery_selection_changed:'本次素材已固定，请返回来源版本调整并重新确认。',creative_delivery_immutable:'交付版本已固定，请返回来源版本重新确认。',creative_timeline_invalid:'请核对分镜时长与时间线。',creative_local_tool_unavailable:'本机制作工具不可用，请运行制作预检查看缺项。',creative_invalid_media:'素材媒体信息无效，请重新导入可用文件。',creative_delivery_check_failed:'成片技术检查未通过，请核对原任务回执。',creative_caption_too_long_shorten_product_facts:'字幕过长，请精简文案后保存新版本。',creative_report_preview_changed:'报表已变化，请重新预览。',creative_report_columns_invalid:'CSV 列名不符合支持字段，请按说明核对。',creative_report_count_invalid:'统计数量须为非负整数，未知项留空。',creative_clip_range_exceeded:'素材入点与时长超出了实际视频，请缩短镜头或更换素材。',creative_edit_invalid:'请核对画幅、镜头数量、字幕和剪辑时间。',creative_metrics_media_not_produced:'请先完成素材制作，再登记该版本的实际效果。',creative_metrics_result_changed:'素材版本已变化，请刷新后重新选择。',creative_image_options_invalid:'请核对图片设置与5–10张的套图计划。',creative_image_set_size_invalid:'整套商品图请规划5–10张。',creative_image_platform_count_exceeded:'计划张数超过所选平台的参考上限，请调整。',creative_image_platform_ratio_invalid:'该商品卡规格要求方图，请选择1:1。',creative_image_profile_unknown:'请选择有效的平台和站点。',creative_product_name_required:'请先补充商品名称。',creative_direction_required:'请先拆解参考素材并保存设计方向。',creative_analysis_source_required:'请从已选制作参考中选择一张参考图片或一条视频；关键帧可作为制作参考。',creative_reference_media_required:'请先导入并选择参考图片、参考视频或关键帧。',creative_product_facts_required:'请先补充产品卖点与资料依据。',creative_request_stale:'商品资料或设计方向已变化，请建立当前版本的新制作请求。',creative_shot_assets_required:'请为每个分镜选择对应的实际素材。',creative_output_media_required:'请选择与本次图片或视频格式对应的实际成品。',creative_result_immutable_create_new_version:'这个版本已经有产出，请新建制作版本。',creative_policy_conflict:'复查计划已有新版本，请刷新后核对。',creative_vision_model_not_configured_use_manual_analysis:'当前没有可用的视觉模型入口，可先人工填写参考拆解。',creative_analysis_required:'视频请先在“原片拆解”提取关键帧，再进行视觉分析。',creative_asset_changed:'素材文件已有变化，请重新导入并核对。',creative_metrics_count_conflict:'点击、完播或退货数量与对应总数冲突，请核对统计口径。',creative_metrics_invalid_period:'请填写有效且已经结束的统计日期范围。',workspace_source_changed:'原商品资料已经更新，请重新核对商品绑定和创意资料。',creative_review_record_immutable:'此版本的审阅结论已保存，需要调整时请建立新版本。'}[code]||'本次操作未完成，请核对所填资料和当前版本后重试。');
  function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  async function refresh(){const p=getProject();if(!p)return;const epoch=++s.epoch;if(s.pid!==p.id)resetProject(p);else savedDirection(p,directionSnapshot()!==s.directionBaseline);try{const data=await api('commerce_media_overview',{project_id:p.id});if(epoch!==s.epoch||getProject()?.id!==p.id)return;s.data=data;s.readinessError=false;if(!s.imageProfile&&data.image_planning){s.imageProfile=data.image_planning.default_profile;s.imageRatio=data.image_planning.profiles.find(x=>x.id===s.imageProfile)?.aspect_ratio||'1:1'}s.revision=p.revision;const policyDirty=s.policyBaseline!==null&&policySnapshot()!==s.policyBaseline;if(!policyDirty){s.interval=String(data.policy.interval_days);s.enabled=data.policy.enabled;}s.policyBaseline=JSON.stringify([data.policy.enabled,String(data.policy.interval_days)]);if(s.optionsBaseline===null)s.optionsBaseline=optionsSnapshot();repaint()}catch(err){if(epoch===s.epoch&&getProject()?.id===p.id){s.readinessError=true;s.error=errorText(err.message);repaint()}}}
  function direction(p){const refs=p.assets.filter(a=>['reference_image','reference_video','keyframe'].includes(a.kind)),analyzable=refs.filter(a=>s.refs.includes(a.id)&&['reference_image','reference_video'].includes(a.kind));return `<p>选择制作参考，填写或分析设计方向；商品事实沿用项目资料。</p><div class="media-reference-list" aria-label="制作参考（可多选）">${refs.length?refs.map(a=>`<label class="media-check"><input type="checkbox" id="media-reference-${e(a.id)}" data-media-reference="${a.id}" ${s.refs.includes(a.id)?'checked':''} ${s.busy||!s.refs.includes(a.id)&&s.refs.length>=8?'disabled':''}> ${e(a.display_name||a.id.slice(0,8))} <small>${e(a.kind==='reference_image'?'参考图片':a.kind==='reference_video'?'参考视频':'关键帧')}</small></label>`).join(''):ui.empty('先在“资料与素材”导入参考图片或视频。')}</div>${ui.field('AI拆解来源',ui.select({id:'media-analysis-source','data-media-field':'analysisAsset',value:s.analysisAsset,disabled:s.busy,options:[{value:'',label:'从已选制作参考中选择一张图片或一条视频'},...analyzable.map(a=>({value:a.id,label:a.display_name||a.id.slice(0,8)}))]}))}<div class="form-actions">${btn('AI拆解此来源','analyze',{disabled:s.busy||!analysisSource(p)})}<span class="muted">每次提交一张参考图片或一条视频的最多四张已提取关键帧；制作参考选择保持。</span></div>${s.job?`<p role="status">参考拆解：${e(statuses[s.job.status]||s.job.status)} ${s.job.result?.error?e(errorText(s.job.result.error)):''}${s.job.input.kind==='design_analyze'&&!currentAnalysis()?' · 来源或制作参考已变化，请重新拆解或人工核对设计方向。':''}</p>`:''}<div class="media-direction-fields">${Object.entries(labels).map(([k,l])=>area(l,'analysis.'+k,s.analysis[k]||'')).join('')}</div><div class="form-actions">${btn('已核对，保存设计方向','direction-save',{disabled:s.busy||!s.refs.length},true)}${s.data?.direction_current?ui.badge('设计方向已保存','success'):ui.badge('设计方向待确认','gray')}</div>`}
  function editState(r){if(!s.edits[r.id]){s.edits[r.id]=r.spec.editing?{...structuredClone(r.spec.editing),shots:r.spec.editing.shots.map((x,i)=>({...x,source_index:i}))}:{aspect_ratio:'9:16',keep_source_audio:true,shots:r.spec.shots.map((x,i)=>({source_index:i,source_start_ms:0,duration_ms:x.end_ms-x.start_ms,caption:i===0?r.spec.script.hook:i===4?r.spec.script.cta:r.spec.script.body.slice((i-1)*100,i*100)}))};s.editBaselines[r.id]=JSON.stringify(s.edits[r.id]);}return s.edits[r.id];}
  function editor(r){const d=editState(r);return `<details class="media-editor"><summary>剪辑、字幕与画幅</summary><p class="muted">保存为新的制作版本；原请求和成片保留。剪辑区间须在实际镜头范围内。</p>${ui.field('成片画幅',ui.select({'data-edit-field':'aspect_ratio',value:d.aspect_ratio,options:['9:16','1:1','16:9'].map(value=>({value,label:value}))}))}<label class="media-check"><input type="checkbox" data-edit-field="keep_source_audio" ${d.keep_source_audio?'checked':''}>保留镜头原音（配音另选）</label>${d.shots.map((x,i)=>`<fieldset><legend>镜头 ${i+1}</legend><div class="media-metric-fields">${ui.field('源分镜',ui.select({'data-edit-shot':i,'data-edit-key':'source_index',value:String(x.source_index),options:r.spec.shots.map((_,j)=>({value:String(j),label:'分镜 '+(j+1)}))}))}${ui.field('素材入点（秒）',ui.input({type:'number',min:0,max:120,step:0.001,value:x.source_start_ms/1000,'data-edit-shot':i,'data-edit-key':'source_start_ms'}))}${ui.field('时长（秒）',ui.input({type:'number',min:0.25,max:30,step:0.001,value:x.duration_ms/1000,'data-edit-shot':i,'data-edit-key':'duration_ms'}))}</div>${ui.field('画面字幕（留空不显示）',`<textarea class="ui-control" rows="2" maxlength="100" data-edit-shot="${i}" data-edit-key="caption">${e(x.caption)}</textarea>`)}</fieldset>`).join('')}${btn('保存新剪辑版本','edit-save',{disabled:s.busy||r.stale||['queued','running'].includes(r.status)},true)}</details>`}
  async function downloadAsset(p,id){let offset=0,parts=[],meta;do{const chunk=await api('commerce_creative_asset_read',{project_id:p.id,asset_id:id,offset:String(offset)});if(getProject()?.id!==p.id)return;meta=chunk;const raw=Uint8Array.from(atob(chunk.content_base64),c=>c.charCodeAt(0));if(!raw.length&&offset<Number(chunk.size))throw Error('creative_asset_changed');parts.push(raw);offset+=raw.length;if(offset>64*1024*1024)throw Error('creative_asset_changed')}while(offset<Number(meta.size));const blob=new Blob(parts,{type:meta.mime}),bytes=await blob.arrayBuffer(),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');if(sha!==meta.sha256)throw Error('creative_asset_changed');const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='delivery-'+id+meta.extension;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000)}
  const selectedAssets=r=>r.delivery?.asset_ids||Array.from({length:r.spec.shots.length||1},(_,i)=>s.shots[r.id]?.[i]||'');
  const selectedAudio=r=>r.delivery?r.delivery.audio_asset_id:s.audio;
  const selectionKey=r=>JSON.stringify([r.id,r.request_sha256,getProject()?.revision,selectedAssets(r),selectedAudio(r)]);
  const preflightView=r=>window.CommerceMediaQualityView?.(s.preflight?.key===selectionKey(r)?s.preflight.report:null)||'';
  function requestView(p){const requests=s.data?.requests||[],r=requests.find(x=>x.id===s.request)||requests[0];if(!r)return ui.empty('选择需要的图片或视频类型，建立第一份制作清单。');s.request=r.id;const video=r.spec.format.endsWith('_video');return `<div class="media-version-select">${ui.field('制作版本',ui.select({'data-media-field':'request',value:r.id,options:requests.map((x,i)=>({value:x.id,label:(x.delivery?(x.delivery.role==='sample'?'样片':'完整制作承诺'):(x.spec.image_options?.label||names[x.spec.format]))+' · '+new Date(x.created_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · '+(statuses[x.status]||x.status)}))}))}${ui.badge(r.stale?'依据已变化':statuses[r.status]||r.status,r.stale?'warning':r.status==='approved'?'success':'gray')}</div><p>${e(r.spec.objective)}</p>${r.spec.image_delivery?`<p>${e(r.spec.image_options.label||r.spec.label)} · ${e(r.spec.image_delivery.label)} · ${e(r.spec.image_delivery.aspect_ratio)} · 本套计划${r.spec.image_options.set_size}张，本次1张</p><p class="muted">${e(r.spec.image_delivery.note)} 通用参考，仍需核对店铺/类目和实际成品文件。</p>`:''}<details><summary>制作提示词与产品约束</summary><textarea class="ui-control media-prompt" readonly rows="9" aria-label="可复制的制作提示词">${e(r.spec.prompt)}</textarea>${btn('下载制作清单','export-request')}</details>${video?ui.table(['分镜','时间','画面与动作'],r.spec.shots.map(shot=>`<tr><td>${e({usage_scene:'使用场景',product_closeup:'产品特写',demonstration:'使用演示',call_to_action:'收尾引导'}[shot.role])}</td><td>${shot.start_ms/1000}–${shot.end_ms/1000}秒</td><td>${e(shot.framing+' · '+shot.action)}</td></tr>`)):''}${video&&!r.delivery?editor(r):''}${delivery?.view(r,s.busy)||''}${window.CommerceMediaQualityView?.(r.quality_report)||''}${s.method==='service'&&!r.spec.editing?providers?.view(r,p)||'':''}${r.job_error?ui.alert(errorText(r.job_error),'danger'):''}${r.job_status?`<p role="status">本机任务：${e(statuses[r.job_status]||r.job_status)} ${r.job_stage?e(r.job_stage.startsWith('render_shot_')?'正在制作镜头 '+r.job_stage.split('_').at(-1):r.job_stage.startsWith('layout_')?'正在排版':r.job_stage==='assemble_storyboard'?'正在合成分镜':''):''}</p>`:''}${r.assets.length?`<div class="media-output-assets">${r.assets.map(a=>btn((['image_layout_draft','video_draft'].includes(a.kind)?'预览草稿 · ':'预览文件 · ')+a.id.slice(0,8),'preview',{'data-asset':a.id})).join('')}</div>${(r.delivery_assets||[]).map(a=>btn(({delivery_package:'下载完整交付包',video_cover:'下载封面',captions:'下载字幕',quality_report:'下载检查报告',review_contact_sheet:'预览实帧总览',review_frame_index:'下载取样位置'})[a.kind]||'下载来源清单',a.kind==='review_contact_sheet'?'preview':'delivery',{'data-asset':a.id})).join('')}${r.review?`<p>审阅：${e(r.review.note)}</p>`:`${area('审阅说明','reviewNote',s.reviewNote)}<div class="form-actions">${btn(r.delivery?.role==='sample'?'通过样片，允许本次完整制作':'通过本地审阅','approve',{disabled:s.busy||r.stale||delivery?.canApprove(r)===false||r.quality_report?.delivery_commitment_check?.status==='failed'},true)}${btn('退回调整','reject',{disabled:s.busy||r.stale})}</div>`}`:`${s.method==='local'||video||r.delivery?`<h3>本机排版与剪辑</h3><p class="muted">${s.method==='service'?'生成的单个镜头可带入下方分镜，合成完整视频。':'使用已导入的图片、实拍或生成镜头，不调用生成服务。'}</p><div class="media-shot-inputs">${r.delivery?`<p>本次已固定 ${r.delivery.asset_ids.length}个分镜素材${r.delivery.audio_asset_id?"及音轨":""}。</p>`:video?r.spec.shots.map((shot,i)=>select((i+1)+'. '+shot.framing,'shot.'+i,s.shots[r.id]?.[i]||'',assets(p,['product_image','generated_image','generated_video','product_video']))).join(''):select('产品原图 / 已制作图片','shot.0',s.shots[r.id]?.[0]||'',assets(p,['product_image','generated_image']))}${video&&!r.delivery?select('配音或音轨（可选）','audio',s.audio,assets(p,['audio'])):''}</div>${video?preflightView(r):''}<div class="form-actions">${video?btn('检查本次制作','preflight',{disabled:s.busy||r.stale}):''}${btn(video?(r.delivery?.role==='sample'?'制作 '+r.spec.duration_ms/1000+'秒样片':r.delivery?.role==='full'?'启动 '+r.spec.duration_ms/1000+'秒完整制作':'按分镜渲染'+(r.spec.duration_ms/1000)+'秒视频'):'制作本机排版图','execute',{disabled:s.busy||r.stale||delivery?.canExecute(r)===false||['queued','running'].includes(r.status)},true)}</div>`:''}${r.delivery?'':`<h3>绑定文件与审阅</h3><p class="muted">从项目素材选择实际文件或模板草稿，绑定到当前制作版本后审阅。外部结果先在“资料与素材”导入。</p>${select('待审阅文件','attachment',s.attachment,assets(p,video?['generated_video','video_draft']:['product_image','generated_image','image_layout_draft']))}${btn('绑定文件，进入待审阅','attach',{disabled:s.busy||r.stale})}`}`}`}
  function imageSettings(){const planning=s.data?.image_planning;if(!planning||s.kind.endsWith('_video'))return '';const profile=planning.profiles.find(x=>x.id===s.imageProfile);return `<p class="muted">一套商品图通常规划5–10张，按产品需要安排；下面每次建立一张独立图片的制作版本。</p><div class="media-metric-fields">${ui.field('目标平台 / 站点',ui.select({'data-media-field':'imageProfile',value:s.imageProfile,options:planning.profiles.map(x=>({value:x.id,label:x.label}))}))}${field('本套计划张数','imageCount',s.imageCount,{type:'number',min:5,max:Math.min(10,profile?.max_images||10),step:1})}${ui.field('本张画幅',ui.select({'data-media-field':'imageRatio',value:s.imageRatio,options:(s.imageProfile==='tiktok_us'?['1:1']:['1:1','3:4','4:3']).map(value=>({value,label:value}))}))}${field('本张名称','imageLabel',s.imageLabel,{maxlength:120})}</div>${area('本张内容重点','imageFocus',s.imageFocus,2)}${profile?`<p class="muted">${e(profile.note)} 通用参考不代表类目核验或发布批准。</p>`:''}`}
  function production(p){const readiness=s.data?.readiness,current=!s.readinessError&&readiness?.project_revision===p.revision;return `<div class="media-production-method">${ui.field('制作方式',ui.select({id:'media-production-method','data-media-field':'method',value:s.method,options:[{value:'local',label:'本机排版 / 剪辑'},{value:'service',label:'生成服务'}]}))}<span class="muted">${s.method==='service'?'使用已配置模型或插件生成图片与镜头。':'使用项目内素材制作，模板草稿仍需审阅。'}</span></div>${imageSettings()}${window.CommerceCreativeReadinessView?.(current?readiness:null,s.kind,s.busy)||''}<div class="media-create-row">${ui.field('制作类型',ui.select({id:'media-production-kind','data-media-field':'kind',value:s.kind,options:Object.entries(names).map(([value,label])=>({value,label}))}))}${btn('建立制作版本','create',{disabled:s.busy||s.readinessError||!s.data?.direction_current||!!readiness&&(!current||!readiness.formats[s.kind]?.can_create_request)},true)}</div>${!readiness&&!s.data?.direction_current?ui.alert('先保存参考拆解与设计方向，再组织图片和视频生产。'):''}${requestView(p)}${s.method==='local'&&localDraftView?`<details class="media-quick-drafts" data-view-key="media-quick-drafts"><summary>快速模板草稿</summary>${localDraftView()}</details>`:''}`}
  function performance(){const m=s.metrics,sales=s.data?.sales_context,options=(s.data?.requests||[]).filter(r=>r.result_sha256&&r.assets.length).map(r=>({value:r.id,label:names[r.spec.format]+' · '+r.id.slice(0,8)}));return `<h3>销售与内容效果</h3>${sales?.status==='saved_order_snapshot'?ui.alert('已有商品发货单样本：'+sales.postings+'单、'+sales.units+'件。'+(sales.fresh?'快照在有效期内。':'快照已过期，待更新。')+(sales.scope_confirmed?'':'统计范围待核对。')+'销售额、曝光与素材转化仍需对应口径的数据。'):''}<p class="muted">空字段保持未知。统计数据保留来源、日期和素材版本；不直接将销量变化归因于设计。</p><div class="media-metric-fields">${field('开始日期','metric.period_start',m.period_start||'',{type:'date'})}${field('结束日期（不含当日）','metric.period_end',m.period_end||'',{type:'date'})}${field('数据来源','metric.source_ref',m.source_ref||'',{maxlength:1000})}${ui.field('素材版本',ui.select({'data-media-field':'metric.request_id',value:m.request_id||'',options:[{value:'',label:'商品整体 · 未归属具体素材'},...options]}))}${Object.entries({impressions:'曝光量',clicks:'点击量',orders:'订单数',returns:'退货数',video_views:'视频观看量',completed_views:'完整观看量'}).map(([k,l])=>field(l,'metric.'+k,m[k]??'',{type:'number',min:0,step:1})).join('')}</div>${area('购买疑问 / 评论 / 退货反馈','metric.feedback',m.feedback||'')}${btn('保存实际效果数据','metrics-save',{disabled:s.busy},true)}${ui.table(['统计范围','素材归属','点击率 / 订单比率','来源'],(s.data?.performance||[]).map(r=>`<tr><td>${e(r.payload.period_start.slice(0,10))} 至 ${e(r.payload.period_end.slice(0,10))}</td><td>${e(r.payload.request_id?.slice(0,8)||'商品整体')}</td><td>${r.metrics.ctr==null?'未知':(r.metrics.ctr*100).toFixed(2)+'%'} / ${r.metrics.conversion_rate==null?'未知':(r.metrics.conversion_rate*100).toFixed(2)+'%'}</td><td class="catalog-text">${e(r.payload.source_ref)}</td></tr>`),'尚未登记效果数据。填写上方来源、日期与指标，或导入效果报表。')}<details ${s.reportOpen?'open':''}><summary>导入效果 CSV 报表</summary><p class="muted">支持 period_start、period_end、request_id、request_result_sha256、impressions、clicks、orders、returns、video_views、completed_views、feedback。时间使用带时区 ISO 格式，空值保留未知；最多100行。先预览，再确认入库。</p>${field('报表来源','reportSource',s.reportSource,{maxlength:1000})}${area('CSV 内容','reportText',s.reportText,5)}${btn('预览报表','report-preview',{disabled:s.busy})}${s.reportPreview?`<p role="status">已校验 ${s.reportPreview.row_count} 行 · ${e(s.reportPreview.preview_sha256.slice(0,12))}</p>${btn('确认导入该报表','report-commit',{disabled:s.busy},true)}`:''}</details><h3>定期设计复查</h3><div class="media-policy"><label class="media-check"><input type="checkbox" data-media-field="enabled" ${s.enabled?'checked':''}> 启用本地周期复查</label>${field('间隔天数','interval',s.interval,{type:'number',min:1,max:90,step:1})}${btn('保存复查周期','policy',{disabled:s.busy})}${btn('立即分析已有数据','review',{disabled:s.busy})}</div><p class="muted">${s.data?.policy.enabled&&s.data?.policy.next_due?'下次复查：'+new Date(s.data.policy.next_due*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'。':'周期复查未启用。'}服务运行时按期生成调整建议；新的生成与线上发布按明确操作执行。</p>${(s.data?.reviews||[]).map(r=>`<article class="media-review-report"><strong>${e(new Date(r.created_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))}</strong><p>${e(r.reason)}</p>${r.recommendations.map((x,i)=>`<p><strong>${e(names[x.kind])}</strong> · ${e(x.reason)} ${r.status==='ready_for_review'?btn('准备调整版本','recommend',{'data-kind':x.kind,'data-review':r.id,'data-index':i}):''}</p>`).join('')}</article>`).join('')}`}
  function view(){const p=getProject();if(!p)return ui.empty('先选择或创建创意项目。');if(s.pid!==p.id){queueMicrotask(refresh);return '<p role="status">正在读取产品创意流程…</p>'}if(!s.data)return `<section class="media-flow">${s.error?ui.alert(s.error,'danger'):'正在读取创意流程…'}${btn('重新读取','refresh')}</section>`;return `<section class="media-flow" aria-label="商品图片与视频生产">${s.error?ui.alert(s.error,'danger'):''}${s.data?.binding_current===false?ui.alert('关联商品资料已有更新，请核对当前资料后建立新的创意版本。','warning'):''}<nav class="media-tabs" aria-label="创意生产步骤">${[['direction','参考与设计方向'],['production','图片与视频生产'],['performance','效果与周期调整']].map(([key,label])=>btn(label,'tab',{'data-tab':key,'aria-pressed':s.subtab===key})).join('')}</nav>${s.subtab==='direction'?direction(p):s.subtab==='production'?production(p):performance()}</section>`}
  async function poll(jobId,pid,generation,analysisGeneration){const current=()=>getProject()?.id===pid&&s.jobGeneration===generation&&(analysisGeneration===undefined||s.analysisGeneration===analysisGeneration);try{if(!current())return;const job=await api('commerce_creative_job_get',{job_id:jobId});if(!current())return;s.job=job;if(['queued','running'].includes(job.status)){repaint();setTimeout(()=>poll(jobId,pid,generation,analysisGeneration),1500)}else{if(job.input.kind==='design_analyze'&&job.status==='completed')s.analysis={...job.result.analysis};const p=await api('commerce_creative_get',{project_id:pid});if(!current())return;onProject(p);await refresh()}}catch{if(current()){s.error='任务状态暂不可读，保留原请求，不会重复生成。';repaint()}}}
  document.addEventListener('input',ev=>{if(!ev.target.closest('.media-editor'))return;const r=s.data?.requests.find(x=>x.id===s.request);if(!r)return;const d=editState(r),el=ev.target;if(el.dataset.editField)d[el.dataset.editField]=el.type==='checkbox'?el.checked:el.value;else if(el.dataset.editShot!==undefined){const key=el.dataset.editKey;d.shots[Number(el.dataset.editShot)][key]=key==='caption'?el.value:key==='source_index'?Number(el.value):Math.round(Number(el.value)*1000)}});
  document.addEventListener('input',ev=>{if(!ev.target.closest('.media-flow'))return;const handled=delivery?.input(ev,s.data?.requests.find(x=>x.id===s.request));if(handled){if(handled==='repaint')repaint();return}const key=ev.target.dataset.mediaField;if(!key)return;const [group,part]=key.split('.');if(group==='analysis')s.analysis[part]=ev.target.value;else if(group==='metric')s.metrics[part]=ev.target.value;else if(group==='shot'){s.shots[s.request]||={};s.shots[s.request][part]=ev.target.value}else if(['interval','reviewNote','imageCount','imageLabel','imageFocus','reportText','reportSource'].includes(key)){s[key]=ev.target.value;if(key==='reportText'||key==='reportSource')s.reportPreview=null}});
  document.addEventListener('change',ev=>{if(!ev.target.closest('.media-flow'))return;const ref=ev.target.dataset.mediaReference;if(ref){if(ev.target.checked&&!s.refs.includes(ref)&&s.refs.length>=8)return;s.refs=ev.target.checked?[...s.refs.filter(x=>x!==ref),ref]:s.refs.filter(x=>x!==ref);if(!s.refs.includes(s.analysisAsset))s.analysisAsset='';s.analysisGeneration++;repaintSelection(ev.target);return}const key=ev.target.dataset.mediaField;if(!key)return;const [group,part]=key.split('.');if(group==='shot'){s.shots[s.request]||={};s.shots[s.request][part]=ev.target.value;repaint()}else if(group==='metric')s.metrics[part]=ev.target.value;else if(key==='enabled')s.enabled=ev.target.checked;else{s[key]=ev.target.value;if(key==='analysisAsset'){s.analysisGeneration++;repaintSelection(ev.target)}if(key==='audio')repaint();if(key==='kind'||key==='method'){repaint()}if(key==='imageProfile'){s.imageRatio=s.data?.image_planning?.profiles.find(x=>x.id===s.imageProfile)?.aspect_ratio||'1:1';repaint()}if(key==='request'){s.requestOpenGeneration++;s.attachment='';s.reviewNote='';repaint()}}});
  document.addEventListener('click',async ev=>{const b=ev.target.closest('[data-media-action]');if(!b||!b.closest('.media-flow')||b.disabled)return;ev.preventDefault();const action=b.dataset.mediaAction,p=getProject();if(!p)return;if(action==='tab'){s.requestOpenGeneration++;s.subtab=b.dataset.tab;repaint();return}if(action==='preparation'){const item=s.data?.readiness?.checks.find(c=>c.key===b.dataset.preparationKey);if(!item)return;if(item.action.tab==='direction'){s.requestOpenGeneration++;s.subtab='direction';repaint();queueMicrotask(()=>document.getElementById('media-analysis-layout')?.focus({preventScroll:true}))}else onPreparation?.(item.action);return}if(action==='preview'){onPreview(b.dataset.asset);return}const requests=s.data?.requests||[],r=requests.find(x=>x.id===s.request)||requests[0];if(action==='delivery-open'){s.request=b.dataset.request;s.reviewNote='';s.attachment='';repaint();return}if(action==='export-request'){download(r,'product-media-production.json');return}if(s.busy)return;const restorePreflightFocus=action==='preflight'&&document.activeElement===b;let focusMoved=false;const trackFocus=event=>{if(event.target!==b&&event.target!==document.body&&event.target!==document.documentElement)focusMoved=true};if(restorePreflightFocus)document.addEventListener('focusin',trackFocus,true);if(action.startsWith('report-'))s.reportOpen=true;const actionGeneration=++s.actionGeneration;s.busy=true;s.error='';repaint();
    try{const args={project_id:p.id,expected_revision:p.revision};if(action==='refresh'){await refresh();return}if(action==='direction-save'){const analysis={...s.analysis},refs=[...s.refs],submitted=directionSnapshot(analysis,refs);const result=await api('commerce_media_direction_save',{...args,analysis,reference_asset_ids:refs,...(currentAnalysis()&&s.job.status==='completed'?{analysis_job_id:s.job.id}:{})});if(getProject()?.id===p.id){const preserve=directionSnapshot()!==submitted;onProject(result);savedDirection(result,preserve);s.subtab='production'}}
      else if(action==='analyze'){const asset=analysisSource(p);if(!asset)throw Error('creative_analysis_source_required');const generation=++s.jobGeneration,analysisGeneration=s.analysisGeneration,key='design:'+p.id+':'+p.revision+':'+asset.id;if(!s.keys.has(key))s.keys.set(key,crypto.randomUUID());const job=await api('commerce_creative_design_analyze',{project_id:p.id,asset_id:asset.id,idempotency_key:s.keys.get(key)});if(getProject()?.id===p.id&&s.jobGeneration===generation&&s.analysisGeneration===analysisGeneration){s.job=job;s.analysisJobGeneration=analysisGeneration;poll(job.id,p.id,generation,analysisGeneration)}}
      else if(action==='create'||action==='recommend'){const kind=action==='recommend'?b.dataset.kind:s.kind,originalKind=s.kind,submittedOptions=JSON.parse(optionsSnapshot());submittedOptions.kind=kind;const request=await api('commerce_media_request_create',{...args,kind,idempotency_key:crypto.randomUUID(),...(!kind.endsWith('_video')&&s.data?.image_planning?{image_options:{profile_id:s.imageProfile,set_size:Number(s.imageCount),aspect_ratio:s.imageRatio,label:s.imageLabel,focus:s.imageFocus}}:{}),...(action==='recommend'?{review_id:b.dataset.review,recommendation_index:Number(b.dataset.index)}:{})});if(getProject()?.id===p.id&&s.actionGeneration===actionGeneration){s.request=request.id;if(s.kind===originalKind)s.kind=kind;s.optionsBaseline=JSON.stringify(submittedOptions);s.subtab='production'}}
      else if(action==='delivery-prepare'){const shots={...(s.shots[r.id]||{})},audio=selectedAudio(r),pair=await delivery.prepare(api,r,selectedAssets(r),audio);if(getProject()?.id===p.id){s.shotsBaseline[r.id]=shots;if(!r.delivery)s.audioBaseline=audio||'';s.request=pair.sample.id;s.reviewNote=''}}
      else if(action==='edit-save'){const editing=structuredClone(editState(r)),key=JSON.stringify([r.id,editing]);if(!s.keys.has(key))s.keys.set(key,crypto.randomUUID());const next=await api('commerce_media_request_edit',{request_id:r.id,expected_request_sha256:r.request_sha256,editing,idempotency_key:s.keys.get(key)});if(getProject()?.id===p.id){s.shots[next.id]=Object.fromEntries(editing.shots.map((x,i)=>[i,s.shots[r.id]?.[x.source_index]||'']));s.request=next.id;s.editBaselines[r.id]=JSON.stringify(editing)}}
      else if(action==='delivery')await downloadAsset(p,b.dataset.asset);
      else if(action==='preflight'){const selected=selectedAssets(r),key=selectionKey(r);if(selected.some(x=>!x))throw Error('creative_shot_assets_required');const report=await api('commerce_media_request_preflight',{request_id:r.id,expected_revision:p.revision,asset_ids:selected,...(selectedAudio(r)?{audio_asset_id:selectedAudio(r)}:{})});if(getProject()?.id===p.id&&s.request===r.id&&key===selectionKey(r))s.preflight={key,report}}
      else if(action==='execute'){const selected=selectedAssets(r),shots={...(s.shots[r.id]||{})},audio=selectedAudio(r);if(selected.some(x=>!x))throw Error('creative_shot_assets_required');const result=await api('commerce_media_request_execute',{request_id:r.id,expected_revision:p.revision,asset_ids:selected,...(selectedAudio(r)?{audio_asset_id:selectedAudio(r)}:{})});if(result.job_id&&getProject()?.id===p.id&&s.actionGeneration===actionGeneration){s.shotsBaseline[r.id]=shots;if(!r.delivery)s.audioBaseline=audio||'';poll(result.job_id,p.id,++s.jobGeneration)}}
      else if(action==='attach'){if(!s.attachment)throw Error('creative_output_media_required');const attachment=s.attachment;await api('commerce_media_request_attach',{request_id:r.id,expected_revision:p.revision,asset_ids:[attachment]});if(getProject()?.id===p.id&&s.attachment===attachment)s.attachment=''}
      else if(action==='approve'||action==='reject'){const note=s.reviewNote;await api('commerce_media_request_review',{request_id:r.id,expected_result_sha256:r.result_sha256,decision:action==='approve'?'approved':'rejected',note,...(action==='approve'?delivery?.reviewArgs(r):{})});if(getProject()?.id===p.id&&s.reviewNote===note)s.reviewNote=''}
      else if(action==='metrics-save'){const submitted=JSON.stringify(s.metrics),payload={};for(const [k,v] of Object.entries(s.metrics)){if(v==='')continue;payload[k]=['impressions','clicks','orders','returns','video_views','completed_views'].includes(k)?Number(v):['period_start','period_end'].includes(k)?v+'T00:00:00+08:00':v}if(payload.request_id)payload.request_result_sha256=s.data.requests.find(x=>x.id===payload.request_id)?.result_sha256;const key=JSON.stringify(payload);if(!s.keys.has(key))s.keys.set(key,crypto.randomUUID());await api('commerce_media_performance_save',{project_id:p.id,payload,idempotency_key:s.keys.get(key)});if(getProject()?.id===p.id&&JSON.stringify(s.metrics)===submitted)s.metrics={}}
      else if(action==='report-preview'||action==='report-commit'){const reportText=s.reportText,reportSource=s.reportSource;const out=await api('commerce_media_performance_import',{project_id:p.id,csv_text:s.reportText,source_ref:s.reportSource,commit:action==='report-commit',...(action==='report-commit'?{expected_preview_sha256:s.reportPreview.preview_sha256}:{})});if(getProject()?.id===p.id){const unchanged=reportText===s.reportText&&reportSource===s.reportSource;s.reportPreview=out.committed||!unchanged?null:out;if(out.committed&&unchanged){s.reportText='';s.reportSource=''}}}
      else if(action==='policy')await api('commerce_media_policy_save',{project_id:p.id,expected_revision:s.data.policy.revision,enabled:s.enabled,interval_days:Number(s.interval)});
      else if(action==='review')await api('commerce_media_review_now',{project_id:p.id,idempotency_key:crypto.randomUUID()});
      if(getProject()?.id===p.id)await refresh();
    }catch(err){if(getProject()?.id===p.id)s.error=errorText(err.message)}finally{if(restorePreflightFocus)document.removeEventListener('focusin',trackFocus,true);if(actionGeneration===s.actionGeneration){s.busy=false;repaint()}if(restorePreflightFocus&&!focusMoved&&getProject()?.id===p.id&&s.request===r?.id&&s.subtab==='production')queueMicrotask(()=>{if(document.activeElement===document.body||document.activeElement===document.documentElement)document.querySelector('.media-flow [data-media-action=preflight]')?.focus({preventScroll:true})})}
  });
  async function openRequest(id,planId,isCurrent=()=>true){const generation=++s.requestOpenGeneration,pid=getProject()?.id;await refresh();if(generation!==s.requestOpenGeneration||getProject()?.id!==pid||!isCurrent())return;if(!s.data?.requests.some(r=>r.id===id))throw Error('creative_request_not_found');s.request=id;s.subtab='production';if(planId)s.method='service';providers?.selectPluginPlan(planId);repaint()}
  return {view,refresh,openRequest,hasUnsavedChanges,discardChanges};
};

/* Creative business module; primitives and themes belong to CommerceUI. */
window.CommerceCreative=({api,esc,toast,repaint,isActive,getBinding,onProduct})=>{
  const ui=window.CommerceUI;
  const emptyForm=()=>({name:'',facts:'',transcript:'',source:'',language:'zh',country:'',audience:'',useScene:''});
  const state={projects:[],project:null,tab:'brief',busy:false,error:'',progress:'',job:null,preview:null,file:null,kind:'reference_video',asset:'',revision:0,form:emptyForm(),pendingTransition:null,transcriptJob:null,transcriptText:'',transcriptBaseline:''};
  const formSnapshot=(form=state.form)=>JSON.stringify(Object.fromEntries(Object.keys(emptyForm()).map(key=>[key,String(form[key]??'')])));
  state.formBaseline=formSnapshot();
  const transcriptDirty=()=>!!state.transcriptJob&&state.transcriptText!==state.transcriptBaseline;
  const hasUnsavedChanges=()=>!!state.file||formSnapshot()!==state.formBaseline||transcriptDirty()||!!flow.hasUnsavedChanges?.();
  function discardChanges(){flow.discardChanges?.();state.form=JSON.parse(state.formBaseline);state.file=null;state.progress='';state.pendingSynthetic=false;state.pendingTransition=null;state.transcriptText=state.transcriptBaseline;}
  function resetEditor(){state.revision++;state.busy=false;state.project=null;state.job=null;state.watchedJob=null;state.preview=null;state.pendingSynthetic=false;state.audio='';state.templateAsset='';state.file=null;state.progress='';state.asset='';state.tab='brief';state.form=emptyForm();state.formBaseline=formSnapshot();state.pendingTransition=null;state.transcriptJob=null;state.transcriptText='';state.transcriptBaseline='';}
  function deferTransition(proceed,kind='project'){state.pendingTransition={proceed,kind,tab:state.tab};paint();queueMicrotask(()=>document.querySelector('[data-creative-action="keep-editing"]')?.focus({preventScroll:true}));return false;}
  state.scopeCase=getBinding?.()?.case_id||'';
  const scopeChanged=()=>state.scopeCase!==(getBinding?.()?.case_id||'');
  function syncScope(){const binding=getBinding?.(),key=binding?.case_id||'';if(key!==state.scopeCase){if(hasUnsavedChanges()){state.pendingTransition={kind:'scope',proceed:()=>{syncScope();paint()}};return binding;}state.scopeCase=key;resetEditor();}else if(state.pendingTransition?.kind==='scope')state.pendingTransition=null;return binding}
  const labels={brief:'资料与素材',analysis:'原片拆解',scripts:'文案与分镜',workflow:'制作与交付'};
  const status={queued:'已排队',running:'处理中',completed:'已完成',partial:'部分完成 · 有待补充项',failed:'处理失败',interrupted:'已中断 · 未自动重发',unknown:'结果未知 · 不会自动重发',cancelled:'已取消'};
  const kinds={reference_video:'参考视频',reference_image:'参考图片',product_image:'商品原图',audio:'补充音轨',captions:'字幕文件',generated_image:'已制作图片',generated_video:'已制作镜头',product_video:'产品实拍视频',keyframe:'关键帧',image_layout_draft:'模板排版图',editable_layout:'可编辑排版',video_draft:'图文视频草稿',subtitle_file:'可编辑字幕'};
  const flow=window.CommerceMediaFlow({api,repaint:paint,getProject:()=>state.project,onProject:p=>{state.project=p},onPreview:preview,onPreparation:prepareInputs,localDraftView:outputsView});
  const catalog=window.CommerceCatalog({api,repaint:paint,getFilters:()=>({synthetic:window.__COMMERCE_LEGACY__?.demo===true}),onSelect:id=>window.dispatchEvent(new CustomEvent('commerce:catalog-select',{detail:{case_id:id}})),onCreative:p=>openProject(p.id)});
  const errorText=e=>({creative_analysis_required:'请选择已完成的原片分析任务。',creative_transcript_review_text_required:'请填写不超过6000字的校对口播。',creative_project_busy:'该项目仍在处理，请先查看当前任务。',creative_workers_busy_try_later:'本机处理任务已满，请稍后再试。',creative_revision_conflict_refresh_first:'资料已有新版本，请刷新后重新编辑。',creative_render_requires_product_asset_and_facts:'请先填写商品名称、卖点依据，并选择商品图或已制作镜头。',creative_reference_video_required:'请选择已导入的参考视频。',creative_product_image_required:'请选择已导入的商品图片。',creative_caption_too_long_shorten_product_facts:'文案较长，请缩短商品名称或卖点后再制作30秒草稿。',creative_media_limits_exceeded:'素材超出当前处理范围：视频最长120秒，图片最多1600万像素。',creative_unsupported_media:'当前支持MP4、WebM、PNG、JPEG、WAV及UTF-8字幕文件。',creative_upload_hash_or_size_mismatch:'文件校验未通过，请重新选择原文件导入。',creative_chunk_out_of_order:'上传进度未确认，请使用同一原文件重新导入以恢复。',creative_upload_closed:'上传已结束，请刷新素材列表。'}[e.message]||'操作未完成，请刷新项目后重试。');
  const button=(label,action,attrs={},primary=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{'data-creative-action':action,...attrs}});
  const field=(key,label)=>ui.field(label,ui.input({id:'creative-'+key,'data-creative-field':key,value:state.form[key],maxlength:key==='name'?120:1000}));
  const area=(key,label,placeholder='')=>ui.field(label,`<textarea class="ui-control" id="creative-${key}" data-creative-field="${key}" rows="5" maxlength="6000" placeholder="${esc(placeholder)}">${esc(state.form[key])}</textarea>`);
  function projectForm(project){const b=project.brief;return {name:b.product?.name||'',facts:(b.product?.verified_facts||[]).map(f=>f.text+' | '+f.evidence_ref).join('\n'),transcript:b.reference?.transcript||'',source:b.reference?.source_url||'',language:b.target?.language||'zh',country:b.target?.country||'',audience:b.target?.audience||'',useScene:b.target?.use_scene||''}}
  function formFrom(project,preserve=false){const saved=projectForm(project);state.formBaseline=formSnapshot(saved);if(!preserve)state.form=saved;}
  function brief(){return {...(state.project?.brief||{}),...(!state.project&&getBinding?.()?{product_binding:getBinding()}:{}),synthetic:!!(state.pendingSynthetic||state.project?.brief.synthetic),product:{name:state.form.name.trim(),verified_facts:state.form.facts.split('\n').filter(x=>x.trim()).map((line,i)=>{const split=line.indexOf('|');if(split<0)throw Error('fact_format');const text=line.slice(0,split).trim(),source=line.slice(split+1).trim();if(!text||!source)throw Error('fact_format');return {id:'f'+(i+1),text,evidence_ref:source}})},reference:{...(state.project?.brief.reference||{}),source_url:state.form.source,transcript:state.form.transcript},target:{...(state.project?.brief.target||{}),language:state.form.language,country:state.form.country,audience:state.form.audience||'',use_scene:state.form.useScene||''}}}
  async function prepareInputs(action){if(!state.project||state.busy)return;if(action.tab==='catalog'){state.tab='catalog';await catalog.enter();paint();return}if(action.tab!=='brief')return;state.tab='brief';if(['product_image','reference_image','reference_video'].includes(action.asset_kind))state.kind=action.asset_kind;paint();if(['creative-name','creative-facts','creative-file','creative-audience','creative-useScene'].includes(action.focus))queueMicrotask(()=>document.getElementById(action.focus)?.focus({preventScroll:true}))}
  function paint(){if(isActive())repaint()}
  async function enter(){syncScope();if(scopeChanged()){paint();return;}try{state.projects=(await api('commerce_creative_list')).projects;paint()}catch(e){state.error=errorText(e);paint()}}
  async function open(id,isCurrent=()=>true,onContinue,expectedCase=''){syncScope();if(scopeChanged()){paint();return false;}if(state.project?.id!==id&&hasUnsavedChanges())return deferTransition(onContinue||(async()=>{if(await open(id,isCurrent)){state.tab='brief';paint()}}));const revision=++state.revision,same=state.project?.id===id;state.busy=true;paint();try{const project=await api('commerce_creative_get',{project_id:id});if(revision!==state.revision||!isCurrent()||scopeChanged())return false;if(getBinding?.()&&project.brief.product_binding?.case_id!==getBinding().case_id)throw Error('creative_project_outside_selected_product');if(expectedCase&&project.brief.product_binding?.case_id!==expectedCase)throw Error('creative_project_outside_selected_product');const preserve=same&&hasUnsavedChanges();state.project=project;if(state.originCase&&project.brief.product_binding?.case_id!==state.originCase)state.originCase='';if(!same){state.pendingSynthetic=false;state.audio='';state.templateAsset='';state.file=null;state.progress='';state.asset=project.assets.find(a=>a.kind==='product_image')?.id||project.assets.find(a=>a.kind==='reference_video')?.id||'';state.job=null;state.watchedJob=null;state.transcriptJob=null;state.transcriptText='';state.transcriptBaseline='';state.preview=null;}state.error='';formFrom(project,preserve);return true}catch(e){if(revision===state.revision&&isCurrent())state.error=errorText(e);return false}finally{if(revision===state.revision){state.busy=false;paint()}}}
  async function refresh(){if(!state.project)return;const id=state.project.id,revision=state.revision;const p=await api('commerce_creative_get',{project_id:id});if(state.project?.id===id&&revision===state.revision&&!scopeChanged()){const preserve=hasUnsavedChanges();state.project=p;formFrom(p,preserve);}await enter()}
  function recoveryView(){const scope=state.pendingTransition?.kind==='scope';return ui.card({title:'保留未保存的创意输入',content:`<p role="status">${scope?'当前商品范围已变化，原创意资料、制作输入与待导入文件仍保留。请从外层返回原商品继续保存，或明确放弃后载入当前商品。':'当前创意资料、制作输入或待导入文件尚未保存。可以返回编辑，或明确放弃后继续。'}</p><div class="form-actions">${scope?'':button('返回编辑','keep-editing')}${button(scope?'放弃输入并载入当前商品':'放弃输入并继续','discard-continue')}</div>`})}
  function briefView(){
    const briefCard=ui.card({title:'商品依据与参考资料',content:`<p class="muted">商品主张按资料依据填写，参考片用于研究叙事与镜头。草稿仍需校对。</p><form id="creative-brief-form" novalidate><div class="analysis-fields creative-brief-fields">${field('name','商品名称')}${field('language','目标语言')}${field('country','目标国家 / 市场')}${field('audience','目标人群')}${field('useScene','主要使用场景')}${field('source','参考视频来源链接（只记录来源）')}</div><div class="creative-text-fields">${area('facts','商品卖点与依据','每行：一条商品事实 | 规格表或资料依据')}${area('transcript','原片口播 / 已校对字幕（可选）','可粘贴已核对的原文，或导入字幕文件。')}</div><div class="form-actions">${button(state.project?'保存资料版本':'创建创意项目','save',{},true)}${getBinding?.()?'':button('填入合成示例','example')}</div></form>`});
    const assets=ui.card({title:'私有素材',content:state.project?`<p class="muted">视频、商品图与音轨保存在本机。视频最长120秒，单文件上限32MB；来源链接不自动下载。</p><div class="analysis-fields">${ui.field('素材类别',ui.select({id:'creative-kind',value:state.kind,options:['reference_video','reference_image','product_image','captions','generated_image','generated_video','product_video','audio'].map(k=>({value:k,label:kinds[k]}))}))}${ui.field('选择文件','<input class="ui-control" id="creative-file" type="file" accept="video/mp4,video/webm,image/png,image/jpeg,audio/wav,.srt,.vtt,.txt">')}</div><div class="form-actions">${button('导入所选素材','upload',{disabled:!state.file||state.busy},true)}<span role="status">${esc(state.progress||state.file?.name||'尚未选择文件')}</span></div>${assetTable()}`:ui.empty('先创建创意项目，再导入参考片、商品图或音轨。')});
    return `<div class="creative-brief-grid">${briefCard}${assets}</div>`;
  }
  function assetTable(onlyKinds){const assets=(state.project?.assets||[]).filter(a=>!onlyKinds||onlyKinds.includes(a.kind));return ui.table(['素材','类别','来源状态','操作'],assets.map(a=>`<tr><td>${esc(a.display_name||a.id.slice(0,8))}</td><td>${esc(kinds[a.kind]||a.kind)}</td><td>${a.origin==='derived'?'本机衍生草稿':'用户导入 · 待核实'}</td><td>${button('预览 / 下载','asset',{'data-asset':a.id})}</td></tr>`),onlyKinds?'尚无模板草稿。':'尚未导入素材。')}
  function analysisView(){return ui.card({title:'原片拆解',content:`<p>检测画面切换候选、提取关键帧和画面文字，并读取口播。检测依据画面差异，闪光或快速移动也可能触发；不是语义分镜。</p><p class="muted">无切点时保留四个时间采样。机器转写需校对后回填，才会进入后续AI改写。</p>${assetSelect(['reference_video'])}${button('读取参考视频','analyze',{disabled:state.busy},true)}${analysisResult()}${jobView()}${assetTable()}`})}
  function analysisResult(){const j=state.job;if(j?.input.kind!=='analyze'||!j.result?.media)return '';const r=j.result,shots=r.shot_analysis,transcript=r.transcript||{};
    const reviewed=state.project?.brief.reference?.transcript_review?.source_job_id===j.id;if(state.transcriptJob!==j.id){state.transcriptJob=j.id;state.transcriptText=(reviewed?state.project.brief.reference.transcript:transcript.text)||'';state.transcriptBaseline=state.transcriptText;}
    return `<section class="creative-analysis" aria-label="原片分析结果"><h3>画面与口播</h3><p>${Number(r.media.duration_seconds).toFixed(2)}秒 · ${r.media.width}×${r.media.height} · ${r.media.has_audio?'含音轨':'无音轨'}</p><p class="muted">${shots?.method==='ffmpeg_visual_difference_candidates'?`检测到${shots.detected_cut_count}个画面切点候选${shots.omitted_cut_count?'；清单省略'+shots.omitted_cut_count+'个，部分区间包含多个切点':''}`:'本次未检测切点，显示时间采样'}。语义角色仍待人工解读。</p>${shots?.segments?.length?ui.table(['画面区间','时间'],shots.segments.map((s,i)=>`<tr><td>区间 ${i+1}</td><td>${s.start_seconds.toFixed(2)}–${s.end_seconds.toFixed(2)}秒</td></tr>`)):''}<div class="creative-frame-grid">${(r.keyframes||[]).map(f=>{const o=(r.ocr||[]).find(o=>o.asset_id===f.id);return `<article class="creative-frame"><strong>${Number(f.requested_timestamp_seconds).toFixed(2)}秒${f.fallback_to_first_frame?' · 回退首帧':''}</strong><p>${esc(o?.items?.map(x=>x.text).join('；')||'未识别到文字 / 识别不可用')}</p>${button('查看该关键帧','asset',{'data-asset':f.id})}</article>`}).join('')}</div>${ui.field('校对口播 / 字幕',`<textarea class="ui-control" id="creative-transcript-review" rows="6" maxlength="6000">${esc(state.transcriptText)}</textarea>`)}<p class="muted" id="creative-review-note">来源：${esc(reviewed?'调用者已校对 · 未独立核实':transcript.source==='local_whisper_tiny'?'本地语音转写 · 待校对':transcript.source==='not_available'?'尚无口播': '已提供文本 · 未独立核实')}。回填作为参考文案，商品事实保持独立；旧AI制作稿需重新审阅。</p>${button('已校对，回填参考文案','review_transcript',{'data-job':j.id,disabled:state.busy},true)}${(r.missing||[]).length?ui.alert('部分分析未完成，请结合关键帧与原片人工核对。','warning'):''}</section>`}
  function aiDraftView(){const j=state.job;if(j?.input.kind!=='refine'||!j.result?.scripts)return '';return `<section class="card"><h2>AI升级稿 · 待审阅</h2><p class="muted">已按目标语言请求改写，事实主张和翻译仍需核对。采用后才会进入视频制作。</p>${j.result.scripts.map(s=>`<article class="creative-script"><h3>${esc(s.hook)}</h3><p>${esc(s.body)}</p><p>${esc(s.cta)}</p>${s.warnings.includes('new_numbers_not_in_product_facts')?ui.alert('这版包含商品资料之外的数字，请重点核对。','danger'):''}${button('已核对，采用此稿','approve',{'data-angle':s.angle,'data-job':j.id})}</article>`).join('')}</section>`}
  function scriptsView(){const p=state.project?.plan;if(!p)return ui.empty('请先创建创意项目。');return ui.card({title:'三种切入点与分镜草稿',content:`${ui.badge(p.status==='draft_ready'?'本地模板草稿 · 待审阅':'待补充商品资料',p.status==='draft_ready'?'blue':'warning')}<p class="muted">本地正文只组合有来源卖点。点击AI升级时，会将所填商品文字和参考文案发送给既有模型，不上传原视频文件。</p>${button('AI升级三种文案','refine',{disabled:state.busy||p.status!=='draft_ready'},true)}${state.project?.brief.reviewed_script?ui.alert('已采用一份人工核对的制作稿，仍未独立核实商品主张。'):''}${aiDraftView()}${jobView()}${p.scripts.length?p.scripts.map((s,i)=>`<article class="creative-script"><h3>本地方案 ${i+1} · ${esc({detail:'商品细节',selection:'选购信息',demonstration:'演示说明'}[s.angle]||s.angle)}</h3><p><strong>开头：</strong>${esc(s.hook)}</p><p>${esc(s.body)}</p><p><strong>引导：</strong>${esc(s.cta)}</p><small class="muted">卖点依据：${s.fact_ids.map(esc).join('、')}</small></article>`).join(''):ui.empty('先填写商品名称与至少一条带依据的卖点。')}${ui.table(['片段','时间','制作事项'],p.video_plan.segments.map(s=>`<tr><td>${esc({hook:'开头',problem:'使用问题',demonstration:'产品演示',evidence_or_objection:'证据 / 异议',call_to_action:'行动引导'}[s.role])}</td><td>${s.start_ms/1000}–${s.end_ms/1000}秒</td><td>补充实际镜头、动作与资料，保持商品事实一致</td></tr>`))}<div class="form-actions">${button('导出项目JSON','export')}${button('导出制作清单Markdown','export_markdown')}</div>`})}
  function assetSelect(allowed,id='creative-asset',value=state.asset){return ui.field('选择已导入素材',ui.select({id,value,options:[{value:'',label:'请选择'},...(state.project?.assets||[]).filter(a=>allowed.includes(a.kind)).map(a=>({value:a.id,label:(a.display_name||a.id.slice(0,8))+' · '+kinds[a.kind]}))]}))}
  function outputsView(){return ui.card({title:'快速模板草稿',content:`<p class="muted">使用现有商品素材制作三种排版图或30秒图文视频，不生成新场景。完成后在上方制作版本中绑定草稿，核对实际文件后审阅。</p>${assetSelect(['product_image','generated_image','generated_video','product_video'],'creative-template-asset',state.templateAsset||'')}${ui.field('已导入的配音 / 音轨（可选）',ui.select({id:'creative-audio',value:state.audio||'',options:[{value:'',label:'不添加；镜头原有音轨会保留'},...(state.project?.assets||[]).filter(a=>a.kind==='audio').map(a=>({value:a.id,label:a.display_name||a.id.slice(0,8)}))]}))}${state.project?.brief.reviewed_script?ui.alert('视频使用已审阅AI稿；切换版本请到文案与分镜采用另一版。'):''}${ui.field('视频开头方案',ui.select({id:'creative-variant',value:state.variant||'0',disabled:!!state.project?.brief.reviewed_script,options:[{value:'0',label:'方案一 · 商品细节'},{value:'1',label:'方案二 · 选购信息'},{value:'2',label:'方案三 · 演示说明'}]}))}<div class="form-actions">${button('制作三种模板排版图','image_layout',{disabled:state.busy})}${button('渲染30秒视频草稿','render',{disabled:state.busy},true)}</div>${jobView()}${assetTable(['image_layout_draft','editable_layout','video_draft','subtitle_file'])}`})}
  function previewView(){if(!state.preview)return '';const p=state.preview;return `<div class="creative-preview">${p.mime.startsWith('image/')?`<img alt="私有创作素材预览" src="${p.url}">`:p.mime.startsWith('video/')?`<video controls playsinline src="${p.url}" aria-label="视频草稿预览"></video>`:''}<p>${esc(p.name)}</p>${button('下载该素材','download')}</div>`}
  function jobView(){const j=state.job,p=state.project;return `${j?`<section class="creative-job" role="status"><strong>${esc(status[j.status]||j.status)}</strong><p class="muted">资料版本 ${esc(j.input.revision)} · ${['queued','running'].includes(j.status)?'正在本机处理素材':'可查看已保留的处理结果'}${p&&j.input.revision!==p.revision?'；这是历史资料版本的结果':''}</p>${['queued','running'].includes(j.status)?'<p>'+esc(({visual_cut_detection:'正在检测画面切点',keyframes:'正在提取关键帧',transcript:'正在整理口播',local_asr:'正在本地转写',model_rewrite:'正在改写文案',rendering:'正在渲染视频'})[j.stage]||'正在处理素材')+'</p>':''}${['queued','running'].includes(j.status)?button('请求取消','cancel',{'data-job':j.id}):''}${j.result?`<details><summary>处理结果与限制</summary><pre>${esc(JSON.stringify(j.result,null,2))}</pre></details>`:''}</section>`:''}${(p?.jobs||[]).length?`<div class="creative-job-list">${p.jobs.slice(0,6).map(x=>button(({analyze:'原片分析',refine:'文案改写',image_layout:'图片排版',render:'视频制作'}[x.kind]||'任务')+' · '+(status[x.status]||x.status),'job',{'data-job':x.id,'data-job-kind':x.kind||''})).join('')}</div>`:''}`}
  function view(){
    const binding=syncScope(),projects=state.projects.filter(p=>!binding||p.case_id===binding.case_id),project=state.project;
    if(project&&!projects.some(p=>p.id===project.id))projects.unshift({id:project.id,name:project.brief.product?.name||'未命名项目',synthetic:project.brief.synthetic});
    if(scopeChanged())return `<section class="creative-workspace">${recoveryView()}</section>`;
    const selectedName=project?(catalog.projectLabel?.(projects.find(p=>p.id===project.id),projects)||project.brief.product?.name||''):'';
    return `<section class="creative-workspace">${state.pendingTransition?recoveryView():''}${state.originCase&&onProduct?`<div class="creative-product-return">${button('返回商品工作区','return-product')}</div>`:''}${state.error?ui.alert(state.error,'danger'):''}<div class="creative-projects creative-project-toolbar">${ui.field('当前创意项目',ui.select({id:'creative-project-select',value:project?.id||'',title:selectedName||'填写新项目资料',disabled:state.busy,options:[{value:'',label:'填写新项目资料'},...projects.map(p=>({value:p.id,label:(p.synthetic?'合成示例 · ':'')+(catalog.projectLabel?.(p,projects)||p.name)}))]}))}<div class="creative-project-actions">${button('选择商品','catalog',{disabled:state.busy})}${project?button('开始新建','new',{disabled:state.busy}):''}</div></div>${project?`<div class="creative-project-meta"><span>资料版本 ${esc(project.revision)}${project.brief.synthetic?' · 合成测试资料':''}</span></div><div class="pills creative-steps" aria-label="创意项目工作阶段">${Object.entries(labels).map(([k,v])=>button(v,'tab',{'data-creative-tab':k,'aria-pressed':state.tab===k,title:v,class:'creative-tab '+(state.tab===k?'active':'')})).join('')}</div>`:''}${state.tab==='catalog'?catalog.view():['workflow','outputs'].includes(state.tab)?flow.view():state.tab==='brief'?briefView():state.tab==='analysis'?analysisView():state.tab==='scripts'?scriptsView():outputsView()}${state.tab==='outputs'?'':previewView()}${binding?'':'<details class="creative-privacy" data-view-key="creative-privacy"><summary>资料与模型使用说明</summary><p>文案、图片与视频共用一个项目，原片与图片保存在本机。点击文案AI升级时，仅提交商品文字与所填参考文案给既有模型。</p></details>'}</section>`;
  }
  function newProject(){if(hasUnsavedChanges())return deferTransition(newProject);resetEditor();paint();}
  function fillExample(){if(hasUnsavedChanges())return deferTransition(fillExample);resetEditor();state.form={...emptyForm(),name:'合成收纳盒',facts:'合成示例：容量为500毫升 | synthetic:spec-1',transcript:'这是合成参考文本，不代表真实商品或用户体验。',source:'synthetic:example',country:'示例市场'};state.pendingSynthetic=true;paint();}
  async function save(){if(!state.form.name.trim())throw Error('name_required');let b;try{b=brief()}catch{throw Error('fact_format')}const revision=state.revision,input=formSnapshot();let saved;
    if(state.project){saved=await api('commerce_creative_save',{project_id:state.project.id,brief:b,revision:state.project.revision})}
    else{const frozen=JSON.stringify(b);if(state.pendingCreate?.frozen!==frozen)state.pendingCreate={frozen,key:crypto.randomUUID()};saved=await api('commerce_creative_create',{brief:b,idempotency_key:state.pendingCreate.key})}
    if(revision!==state.revision||scopeChanged())return;state.project=saved;formFrom(saved,formSnapshot()!==input);if(!hasUnsavedChanges())state.pendingTransition=null;state.error='';await enter();toast('已保存私有创作资料，草稿仍需审阅。')}
  async function upload(){const file=state.file,p=state.project;if(!file||!p)return;if(file.size>32*1024*1024)throw Error('file_too_large');if(!crypto.subtle)throw Error('file_hash_unavailable');const data=new Uint8Array(await file.arrayBuffer()),sha=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(b=>b.toString(16).padStart(2,'0')).join('');const u=await api('commerce_creative_upload_begin',{project_id:p.id,filename:file.name,kind:state.kind,size:String(file.size),sha256:sha,source_ref:['reference_image','reference_video','captions'].includes(state.kind)?state.form.source||'user_provided_unverified':'user_provided_unverified'});
    if(!u.asset_id){for(let i=u.next_index;i<Math.ceil(data.length/u.chunk_bytes);i++){const bytes=data.subarray(i*u.chunk_bytes,(i+1)*u.chunk_bytes);let binary='';for(const b of bytes)binary+=String.fromCharCode(b);await api('commerce_creative_upload_chunk',{upload_id:u.upload_id,index:String(i),content_base64:btoa(binary)});state.progress='已导入 '+Math.min(100,Math.round((i+1)*u.chunk_bytes/data.length*100))+'%';paint()}}
    const completed=await api('commerce_creative_upload_finish',{upload_id:u.upload_id});if(state.project?.id===p.id){state.asset=completed.asset_id;state.progress='校验完成，素材已保存。';if(state.file===file)state.file=null;await refresh()}}
  async function job(action){const p=state.project,asset=['render','image_layout'].includes(action)?state.templateAsset:state.asset;if(!p||(action!=='refine'&&!asset))throw Error('asset_required');const args={project_id:p.id};if(action!=='refine')args.asset_id=asset;if(action==='render'){args.variant=state.variant||'0';if(state.audio)args.audio_asset_id=state.audio}const frozen=JSON.stringify([action,p.revision,args]);state.keys||=new Map();if(!state.keys.has(frozen))state.keys.set(frozen,crypto.randomUUID());args.idempotency_key=state.keys.get(frozen);state.job=null;state.watchedJob=null;paint();const result=await api('commerce_creative_'+action,args);if(state.project?.id===p.id){state.job=result;watch(result.id,p.id);await refresh()}}
  function watch(id,project){state.watchedJob=id;poll(id,project)}
  async function poll(id,project){if(state.watchedJob!==id)return;try{const j=await api('commerce_creative_job_get',{job_id:id});if(state.project?.id!==project||state.watchedJob!==id)return;state.job=j;if(['queued','running'].includes(j.status)){paint();setTimeout(()=>poll(id,project),1500)}else await refresh()}catch(e){state.error='任务状态暂不可读；保留原任务，不会重复提交。';paint()}}
  async function resumeAnalysis(){const revision=state.revision;state.busy=true;paint();try{await job('analyze')}finally{if(revision===state.revision){state.busy=false;paint()}}}
  async function selectJob(id){const revision=state.revision,project=state.project?.id;state.busy=true;paint();try{const job=await api('commerce_creative_job_get',{job_id:id});if(revision!==state.revision||state.project?.id!==project||scopeChanged())return;state.job=job;watch(job.id,project);}finally{if(revision===state.revision){state.busy=false;paint()}}}
  async function reviewTranscript(id){const revision=state.revision,project=state.project,submitted=state.transcriptText||'',formTranscript=state.form.transcript;const saved=await api('commerce_creative_review_transcript',{project_id:project.id,job_id:id,revision:project.revision,text:submitted});if(revision!==state.revision||state.project?.id!==project.id||scopeChanged())return;state.project=saved;if(state.form.transcript===formTranscript)state.form.transcript=saved.brief.reference.transcript;if(state.transcriptJob===id){state.transcriptBaseline=saved.brief.reference.transcript;if(state.transcriptText===submitted)state.transcriptText=state.transcriptBaseline;}await refresh();toast('已回填参考文案；请重新审阅AI制作稿。')}
  async function readAsset(asset){const p=state.project,parts=[];let offset='0',result;do{result=await api('commerce_creative_asset_read',{project_id:p.id,asset_id:asset,offset});const b=atob(result.content_base64);parts.push(Uint8Array.from(b,c=>c.charCodeAt(0)));offset=result.next_offset}while(!result.done);return {blob:new Blob(parts,{type:result.mime}),mime:result.mime,extension:result.extension||''}}
  async function preview(asset){const p=state.project;const a=p.assets.find(x=>x.id===asset);const result=await readAsset(asset);if(state.project?.id!==p.id)return;const bytes=new Uint8Array(await result.blob.arrayBuffer());let binary='';for(const b of bytes)binary+=String.fromCharCode(b);state.preview={name:(a.display_name||'素材')+((a.display_name||'').toLowerCase().endsWith(result.extension)?'':result.extension),mime:result.mime,url:'data:'+result.mime+';base64,'+btoa(binary),blob:result.blob};paint()}
  function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000)}
  document.addEventListener('input',e=>{if(e.target.dataset.creativeField)state.form[e.target.dataset.creativeField]=e.target.value;else if(e.target.id==='creative-transcript-review')state.transcriptText=e.target.value});
  document.addEventListener('change',async e=>{if(e.target.id==='creative-project-select'){if(state.busy)return;if(!e.target.value){newProject();return}if(await open(e.target.value)){state.tab='brief';paint()}}else if(e.target.id==='creative-file'){state.file=e.target.files[0]||null;state.progress='';paint()}else if(e.target.id==='creative-kind')state.kind=e.target.value;else if(e.target.id==='creative-asset')state.asset=e.target.value;else if(e.target.id==='creative-template-asset')state.templateAsset=e.target.value;else if(e.target.id==='creative-variant')state.variant=e.target.value;else if(e.target.id==='creative-audio')state.audio=e.target.value});
  document.addEventListener('submit',e=>{if(e.target.id==='creative-brief-form'){e.preventDefault();e.stopImmediatePropagation();document.querySelector('[data-creative-action="save"]')?.click()}});
  document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.form?.id==='creative-brief-form'&&e.target.tagName==='INPUT'){e.preventDefault();document.querySelector('[data-creative-action="save"]')?.click()}});
  document.addEventListener('click',async e=>{const returnTarget=e.target.closest('[data-creative-action=return-product]');if(returnTarget&&!returnTarget.disabled&&state.originCase){onProduct?.(state.originCase);return;}const b=e.target.closest('[data-creative-action]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();const action=b.dataset.creativeAction;if(state.busy&&!['cancel','tab'].includes(action))return;if(action==='keep-editing'){const tab=state.pendingTransition?.tab;state.pendingTransition=null;state.tab=tab||'brief';paint();queueMicrotask(()=>document.querySelector(state.tab==='analysis'?'#creative-transcript-review':'.creative-workspace [data-creative-field]')?.focus({preventScroll:true}));return}if(action==='discard-continue'){const pending=state.pendingTransition;discardChanges();try{await pending?.proceed()}catch(error){state.error=errorText(error)}finally{paint()}return}syncScope();if(scopeChanged()){paint();return;}state.error='';const actionRevision=state.revision;
    try{if(transcriptDirty()&&action==='job'&&b.dataset.job!==state.transcriptJob)return deferTransition(()=>selectJob(b.dataset.job),'transcript');if(transcriptDirty()&&action==='analyze')return deferTransition(resumeAnalysis,'transcript');if(action==='catalog'){state.tab='catalog';await catalog.enter();paint();return}if(action==='tab'){state.tab=b.dataset.creativeTab;if(['workflow','outputs'].includes(state.tab)){state.tab='workflow';flow.refresh()}const allowed=state.tab==='analysis'?['reference_video']:null;if(allowed&&!state.project?.assets.some(a=>a.id===state.asset&&allowed.includes(a.kind)))state.asset='';paint();return}if(action==='new'){newProject();return}if(action==='example'){fillExample();return}
      state.busy=true;b.disabled=true;paint();if(action==='open')await open(b.dataset.project);else if(action==='save'){await save();state.pendingSynthetic=false}else if(action==='upload')await upload();else if(['analyze','render','image_layout','refine'].includes(action))await job(action);else if(action==='approve'){state.project=await api('commerce_creative_approve_script',{project_id:state.project.id,job_id:b.dataset.job,angle:b.dataset.angle,revision:state.project.revision});await refresh()}else if(action==='job'){await selectJob(b.dataset.job)}else if(action==='cancel'){await api('commerce_creative_job_cancel',{job_id:b.dataset.job});watch(b.dataset.job,state.project.id)}else if(action==='review_transcript'){await reviewTranscript(b.dataset.job)}else if(action==='asset')await preview(b.dataset.asset);else if(action==='download')download(state.preview.blob,state.preview.name);else if(action==='export_markdown'){const pack=await api('commerce_creative_export',{project_id:state.project.id,format:'markdown'});download(new Blob([pack.content],{type:'text/markdown;charset=utf-8'}),'creative-production-brief.md')}else if(action==='export')download(new Blob([JSON.stringify(await api('commerce_creative_export',{project_id:state.project.id}),null,2)],{type:'application/json'}),'creative-project-draft.json');
    }catch(error){if(actionRevision===state.revision)state.error=({fact_format:'每条卖点请填写“商品事实 | 资料依据”。',name_required:'请填写商品名称。',asset_required:'请先选择已导入的素材。',file_too_large:'单文件最多32MB，请先截取需要研究的片段。',file_hash_unavailable:'当前窗口不支持文件校验，请在本机浏览器导入素材。'}[error.message]||errorText(error))}finally{if(actionRevision===state.revision){state.busy=false;paint()}}
  });
  async function openProject(id,requestId,planId,isCurrent=()=>true){if(!isCurrent()||!await open(id,isCurrent,()=>openProject(id,requestId,planId,isCurrent))||!isCurrent())return;const revision=state.revision;state.tab='workflow';if(requestId)await flow.openRequest(requestId,planId,()=>isCurrent()&&revision===state.revision);else await flow.refresh();if(isCurrent()&&revision===state.revision)paint()}
  async function openFromProduct(request,isCurrent=()=>true,onOpened=()=>{}){
    if(!isCurrent())return false;
    const generation=(state.productOpenGeneration||0)+1;state.productOpenGeneration=generation;const alive=()=>isCurrent()&&generation===state.productOpenGeneration;
    const {case_id:caseId,source_sha256:source,project_id:projectId,id}=request;
    if(!/^[a-zA-Z0-9_-]{1,160}$/.test(caseId||'')||!/^[a-f0-9]{64}$/.test(source||'')||!id||projectId&&!/^[a-zA-Z0-9_-]{1,160}$/.test(projectId))throw Error('creative_product_link_invalid');
    if((!projectId||state.project?.id!==projectId)&&hasUnsavedChanges())return deferTransition(()=>openFromProduct(request,isCurrent,onOpened),'product');
    try{
      let target=projectId;
      if(!target){state.busy=true;paint();const project=await api('commerce_catalog_creative',{case_id:caseId,expected_source_sha256:source,idempotency_key:'product-content:'+id});if(!alive())return false;target=project.id;}
      if(!await open(target,alive,()=>openFromProduct(request,isCurrent,onOpened),caseId)||!alive())return false;
      state.originCase=caseId;state.tab=projectId?'workflow':'brief';
      if(projectId)await flow.refresh();
      if(!alive())return false;paint();onOpened(target);return target;
    }catch(e){if(alive()){state.error=errorText(e);paint()}return false;}
    finally{if(generation===state.productOpenGeneration){state.busy=false;if(isCurrent())paint();}}
  }
  function clearProductOrigin(){state.originCase='';state.productOpenGeneration=(state.productOpenGeneration||0)+1;if(state.pendingTransition?.kind==='product')state.pendingTransition=null;paint();}
  function context(){const project=state.project,binding=project?.brief.product_binding;return {module:'creative',demo:!!project?.brief.synthetic,...(binding?.case_id?{entity:{kind:'case',id:binding.case_id}}:{})};}
  function pageContext(){const project=state.project,binding=project?.brief.product_binding;return {section:labels[state.tab]||({catalog:'商品与货源',outputs:'制作与交付'})[state.tab]||state.tab,filters:{project_id:project?.id||''},...(binding?.case_id?{entity:{kind:'case',id:binding.case_id,name:project.brief.product?.name||''}}:{}),source_refs:project?{creative_project:project.id,creative_revision:String(project.revision),...(binding?.source_sha256?{case:binding.source_sha256}:{})}:{}};}
  return {view,enter,openProject,openFromProduct,clearProductOrigin,context,pageContext,hasUnsavedChanges,discardChanges};
};

/* A product links to the shared creative editor; it never owns a second editor. */
window.CommerceProductCreativeLinks=({api,repaint,getBinding,onOpen,formatProjectLabel=p=>p.name||'未命名项目'})=>{
  const ui=window.CommerceUI,e=ui.escape;
  const state={caseId:'',items:[],busy:false,error:'',generation:0};
  function binding(){return getBinding?.()||null}
  function sync(){const id=binding()?.case_id||'';if(id!==state.caseId){state.caseId=id;state.items=[];state.error='';state.busy=false;state.generation++;}}
  async function enter(){sync();const id=state.caseId;if(!id)return;const generation=++state.generation;state.busy=true;state.error='';repaint();try{const result=await api('commerce_creative_list');if(generation!==state.generation||binding()?.case_id!==id)return;state.items=result.projects.filter(p=>p.case_id===id);}catch{if(generation===state.generation)state.error='内容项目尚未读回，请重新读取。';}finally{if(generation===state.generation){state.busy=false;repaint();}}}
  const button=(label,action,attrs={})=>ui.button({label,attrs:{'data-product-content-action':action,...attrs}});
  function view(){sync();return ui.card({title:'内容项目',content:`${state.error?ui.alert(state.error,'danger'):''}<div class="pw-form-actions">${button('新建内容项目','create',{disabled:state.busy})}${button('刷新项目','refresh',{disabled:state.busy})}</div>${state.busy?'<p role="status">正在读取当前商品的内容项目…</p>':state.items.length?ui.table(['项目','资料版本','操作'],state.items.map(p=>`<tr><td>${e(formatProjectLabel(p,state.items))}${p.synthetic?ui.badge('合成资料','gray'):''}</td><td>${e(p.revision??'未记录')}</td><td>${button('打开内容项目','open',{'data-project':p.id,'aria-label':'打开内容项目：'+formatProjectLabel(p,state.items)})}</td></tr>`)):ui.empty('当前商品还没有内容项目。')}`});}
  document.addEventListener('click',event=>{const target=event.target.closest('[data-product-content-action]');if(!target||target.disabled)return;const b=binding();if(!b?.case_id||!b.source_sha256)return;const action=target.dataset.productContentAction;if(action==='refresh'){void enter();return;}if(action==='open'){const project=state.items.find(p=>p.id===target.dataset.project);if(!project)return;onOpen({...b,project_id:project.id});}else if(action==='create')onOpen({...b});});
  return {view,enter,hasUnsavedChanges:()=>false,discardChanges(){}};
};

(() => {
  'use strict';
  window.CommerceSourcing=({api,repaint,onDirty=()=>{},onDraft=()=>false})=>{
    const ui=window.CommerceUI,e=ui.escape;
    const s={caseId:'',epoch:0,fileSequence:0,channels:[],history:[],platform:'yiwugo',query:'',url:'',content:'',format:'json',result:null,busy:false,error:'',keys:new Map()};
    const b=(label,action,attrs={})=>ui.button({label,attrs:{'data-pe-action':'sourcing-'+action,...attrs}});
    const dirty=()=>!!(s.url||s.content||s.result?.draft);
    const clearInputs=()=>{s.fileSequence++;s.url='';s.content='';s.result=null;s.error='';onDirty(false);};
    const channel=()=>s.channels.find(x=>x.id===s.platform);
    const field=(label,key,value)=>ui.field(label,ui.input({id:'sourcing-'+key,'data-pe-sourcing':key,value,disabled:s.busy}));
    const status=v=>({preview_ready:'已取得预览，待核对保存',preview_partial:'已取得部分页面资料，款式/报价待核',needs_export:'读取受限或缺少商品结构',export_required:'需正常导出资料',leads:'已取得公开线索',no_public_leads:'未取得公开线索',search_failed:'检索未完成'}[v]||'尚未实测');
    async function enter(caseId,{force=false,load=true}={}){
      if(s.busy)return false;
      if(caseId!==s.caseId){s.epoch++;s.fileSequence++;Object.assign(s,{caseId,url:'',content:'',result:null,history:[],channels:[],error:''});s.keys.clear();}
      if(!load)return;
      if(s.channels.length&&!force)return;
      const epoch=++s.epoch;
      try{const [c,h]=await Promise.all([api('commerce_product_evidence_sourcing_channels',{case_id:caseId}),api('commerce_product_evidence_sourcing_history',{case_id:caseId})]);if(epoch!==s.epoch)return;s.channels=c.items;s.history=h.items;}
      catch{if(epoch===s.epoch)s.error='渠道读取失败，请刷新；当前输入已保留。';}
      finally{if(epoch===s.epoch)repaint();}
    }
    function view(){
      const c=channel();
      return `<section class="pw-section"><header class="pe-card-heading"><div><h3>多渠道找货</h3><p>批发渠道与零售渠道分别核对；先取得原始资料，再维护报价和成本。</p></div>${b('刷新渠道与回执','refresh',{disabled:s.busy})}</header>${s.error?`<p role="alert" class="pe-notice pe-error">${e(s.error)}</p>`:''}<div class="pe-form-grid">${ui.field('进货渠道',ui.select({id:'sourcing-platform','data-pe-sourcing':'platform',value:s.platform,disabled:s.busy,options:s.channels.map(r=>({value:r.id,label:r.label+' · '+r.kind}))}))}${field('找货关键词','query',s.query)}</div>${b('检索该渠道公开线索','search',{disabled:s.busy||!c?.search_supported})}<p class="pw-meta">${e(c?.status_note||'正在读取渠道目录…')}。正式平台 API：${c?.authorized_api_connected?'已连接':'尚未连接'}。</p><div class="pe-form-grid">${field('准确商品原始链接（HTTPS）','url',s.url)}${ui.field('正常导出资料格式',ui.select({id:'sourcing-format','data-pe-sourcing':'format',value:s.format,disabled:s.busy,options:[{value:'json',label:'单商品 JSON'},{value:'html',label:'含商品元数据的 HTML'}]}))}</div><div class="form-actions">${b('读取公开商品信息','preview-public',{disabled:s.busy||!c?.public_preview_supported})}${b('清空找货输入','discard',{disabled:s.busy})}</div><details><summary>网页受限时导入商品资料</summary><p>在平台正常取得后导入；不会使用账号 Cookie、绕过登录或验证。JSON 可包含 title、model、variant、description、images、offers（price、currency、variant、moq）。</p><label class="ui-field">选择 JSON / HTML 文件<input type="file" data-pe-sourcing="file" accept=".json,.html,.htm,application/json,text/html" ${s.busy?'disabled':''}></label>${ui.field('原始商品资料',`<textarea id="sourcing-content" data-pe-sourcing="content" class="ui-control pe-textarea" maxlength="200000" ${s.busy?'disabled':''}>${e(s.content)}</textarea>`)}${b('解析导出资料并预览','preview-import',{disabled:s.busy})}</details>${s.busy?'<p role="status">正在处理当前渠道，结果返回前请保留此商品。</p>':''}${resultView()}<details><summary>渠道覆盖与实际状态 · ${s.channels.length} 个</summary>${ui.table(['渠道','获取方式','当前商品来源','最近实测'],s.channels.map(r=>`<tr><td>${e(r.label)}<br><small>${e(r.kind)}</small></td><td>${r.public_preview_supported?'公开线索 / 商品元数据 / 资料导入':'正常导出资料 / 待接授权接口'}</td><td>${r.source_count}</td><td>${e(status(r.last_attempt?.status))}</td></tr>`))}</details><details><summary>同商品找货回执 · ${s.history.length} 条</summary>${s.history.map(r=>`<article class="pe-review"><strong>${e(s.channels.find(c=>c.id===r.platform)?.label||r.platform)} · ${e(status(r.status))}</strong><p>${e(r.product?.title||r.query||r.request_url)}</p><small>${e(r.observed_at)}</small>${r.draft||r.items?.length?b('查看这次获取结果','restore',{'data-receipt':r.id}):''}</article>`).join('')||'<p>尚无检索、读取或资料导入回执。</p>'}</details></section>`;
    }
    function resultView(){
      const r=s.result;if(!r)return '';
      return `<section class="pe-review"><h4>${e(status(r.status))}</h4><p>${e(r.reason)}</p>${r.error?`<p class="pw-meta">原回执：${e(r.error)}</p>`:''}${(r.items||[]).map((x,i)=>`<article><strong>${e(x.title)}</strong><p class="pe-note">${e(x.snippet)}</p><p class="pe-note">${e(x.url)}</p>${b('选用此商品链接','choose',{'data-index':i,disabled:s.busy})}</article>`).join('')}${r.product?`<h4>${e(r.product.title)}</h4><p>型号：${e(r.product.model||'待补')} · 款式：${e(r.product.variant||'待锁定')} · 原图链接 ${r.product.images.length} 张</p><p class="pe-note">${e(r.product.description)}</p>${ui.table(['原文选项','标价','起订量','口径'],r.product.offers.map(o=>`<tr><td>${e(o.variant||'尚未锁定')}</td><td>${e(o.price??[o.low_price,o.high_price].filter(v=>v!==null).join('–'))} ${e(o.currency||'币种待核')}</td><td>${e(o.moq||'待核')}</td><td>${o.kind==='price_range_not_variant_quote'?'价格区间，不作为选定款报价':'公开/导出标价，非正式报价'}</td></tr>`))}<details><summary>查看原始图片地址</summary>${r.product.images.map(u=>`<p class="pe-note">${e(u)}</p>`).join('')}</details>${b('带入来源编辑，核对后保存','take',{disabled:s.busy})}<p class="pw-meta">原图留存沿用来源卡片；此处不自动创建报价、不把图片公开展示视为商用许可。</p>`:''}</section>`;
    }
    async function request(action,extra){
      if(s.busy)return;
      const caseId=s.caseId,epoch=s.epoch,args={case_id:caseId,platform:s.platform,...extra};const signature=JSON.stringify([action,args]);
      let key=s.keys.get(signature);if(!key){key=crypto.randomUUID();s.keys.set(signature,key);}
      s.fileSequence++;s.busy=true;s.error='';onDirty(true);repaint();
      try{
        const r=await api('commerce_product_evidence_sourcing_'+action,{...args,idempotency_key:key});
        if(epoch!==s.epoch||caseId!==s.caseId)return;
        s.result=r;
        // A failed follow-up read cannot make the received operation unknown.
        // Retain its original key until both the response and history settle.
        try{
          const h=await api('commerce_product_evidence_sourcing_history',{case_id:caseId});
          if(epoch===s.epoch&&caseId===s.caseId){s.history=h.items;s.keys.delete(signature);}
        }catch{if(epoch===s.epoch&&caseId===s.caseId)s.error='已取得本次结果；回执列表读取失败。输入与结果已保留，可刷新回执或以原请求重试。';}
      }
      catch{if(epoch===s.epoch)s.error='尚未确认处理结果。输入已保留；可先刷新回执，或以原请求重试。';}
      finally{if(epoch===s.epoch){s.busy=false;onDirty(dirty());repaint();}}
    }
    async function action(name,target){
      if(name==='refresh'){await enter(s.caseId,{force:true});return;}
      if(s.busy)return;
      if(name==='discard'){clearInputs();repaint();return;}
      if(name==='search'&&!s.query.trim()){s.error='请填写找货关键词。';repaint();return;}
      if(name.startsWith('preview-')&&(!s.url.trim()||(name==='preview-import'&&!s.content.trim()))){s.error='请填写准确商品链接；导入时还需提供单商品资料。';repaint();return;}
      if(name==='search'){await request('search',{query:s.query});return;}
      if(name.startsWith('preview-')){await request('preview',{url:s.url,mode:name==='preview-import'?'import':'public',format:s.format,content:name==='preview-import'?s.content:''});return;}
      if(name==='choose'){const r=s.result?.items?.[Number(target.dataset.index)];if(r){s.fileSequence++;s.url=r.url;onDirty(true);repaint();}return;}
      if(name==='restore'){const r=s.history.find(x=>x.id===target.dataset.receipt);if(r){s.fileSequence++;s.result=r;s.platform=r.platform;s.url=r.request_url;onDirty(true);repaint();}return;}
      if(name==='take'&&s.result?.draft){if(onDraft(JSON.parse(JSON.stringify(s.result.draft)))){s.fileSequence++;s.url='';s.content='';s.result=null;repaint();}return;}
    }
    async function input(target){
      const key=target.dataset.peSourcing;
      if(s.busy)return;
      if(key==='file'){
        const file=target.files?.[0],epoch=s.epoch,caseId=s.caseId,sequence=++s.fileSequence;
        const current=()=>epoch===s.epoch&&caseId===s.caseId&&sequence===s.fileSequence;
        if(!file)return;
        if(file.size>200000){s.error='资料文件请控制在200KB以内。';repaint();return;}
        try{const content=await file.text();if(!current())return;s.content=content;s.format=/\.html?$/i.test(file.name)?'html':'json';onDirty(true);repaint();}catch{if(current()){s.error='未能读取资料文件。';repaint();}}return;
      }
      if(!['query','platform','url','format','content'].includes(key))return;
      if(key==='platform'&&dirty()){s.error='请先带入保存或清空当前商品资料，再切换渠道。';repaint();return;}
      if(['platform','format','content'].includes(key))s.fileSequence++;
      s[key]=target.value;if(key==='platform')s.result=null;onDirty(dirty());if(['platform','format'].includes(key))repaint();
    }
    return {enter,view,action,input,hasUnsavedChanges:dirty,hasActiveMutation:()=>s.busy,discard:clearInputs,dispose(){s.epoch++;s.fileSequence++;}};
  };
})();

(() => {
  'use strict';
  const SOURCE_KEYS=['kind','platform','label','url','model','variant','observed_at','valid_until','review_state','verification_note','rights_status','rights_evidence','notes','quote_ids','images','metrics','archived'];
  const PROPOSAL_KEYS=['customer_need','selection_reason','differentiation','risks','currency','trial_quantity','trial_budget','max_loss','min_contribution_rate','conditions'];
  const kinds={supplier:'货源',competitor:'竞品',market:'市场数据',document:'样品与文件'};
  const states={unreviewed:'待核对',checked:'已本地核对',conflict:'信息冲突',rejected:'不采信'};
  const rights={unknown:'权利待确认',reference_only:'仅作参考',authorized:'已记录商用授权',self_owned:'自有素材'};
  const decisions={hold:'待补证',reject:'暂不进入',trial:'可有限试销'};
  const metricLabels={price:'竞品价格',currency:'原币',sales_units:'有来源的销量',window_days:'数据窗口（天）',searches:'搜索量',rating:'评分',review_count:'评论数'};
  const stamp=()=>new Date().toISOString();
  const clone=v=>JSON.parse(JSON.stringify(v));
  const isUrl=v=>{try{const u=new URL(v);return u.protocol==='https:'&&!u.username&&!u.password;}catch{return false;}};
  window.CommerceProductEvidence=({api,repaint,onNavigate=()=>{},onDirty=()=>{},onImagePreview=()=>{},formatProjectLabel=p=>p.name||'创意项目',formatQuoteStatus=()=> '待核对'})=>{
    const ui=window.CommerceUI,esc=ui.escape;
    const s={caseId:'',epoch:0,data:null,error:'',notice:'',loading:false,busy:false,uploading:false,section:'all',edit:null,history:null,actor:'当前操作者',showArchived:false,images:new Map(),loadingImages:new Set()};
    const button=(label,action,attrs={},primary=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{'data-pe-action':action,...attrs}});
    const pick=(label,key,value,options,attrs={})=>ui.field(label,ui.select({id:'pe-'+key.replaceAll('.','-'),'data-pe-field':key,value,options:Object.entries(options).map(([value,label])=>({value,label})),...attrs}));
    const input=(label,key,value,type='text',attrs={})=>ui.field(label,ui.input({id:'pe-'+key.replaceAll('.','-'),'data-pe-field':key,value:value??'',type,...attrs}));
    const area=(label,key,value,attrs={})=>ui.field(label,`<textarea id="pe-${esc(key.replaceAll('.','-'))}" data-pe-field="${esc(key)}" class="ui-control pe-textarea" ${attrs.disabled?'disabled':''}>${esc(value??'')}</textarea>`);
    const link=(url,label,row=null,index=-1)=>isUrl(url)?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" ${row?`data-pe-action="origin-open" data-entry="${row.id}" data-source-sha="${row.sha256}" data-index="${index}"`:""}>${esc(label)}</a>`:`<span>${esc(label||'原始链接待补')}</span>`;
    const when=v=>{const d=new Date(v);return Number.isFinite(d.getTime())?d.toLocaleString():v||'未记录';};
    const money=(v,c)=>v==null?'待补':esc(v)+' '+esc(c||'币种待补');
    const statusLabel=code=>ui.status?.(code)?.label||({queued:'等待执行',running:'执行中',completed:'已完成',succeeded:'已完成',failed:'失败',cancelled:'已取消',interrupted:'已中断'}[code]||'状态待核对');
    const assetLabel=kind=>kind.startsWith('generated')?'AI生成 / 待审阅':({reference_image:'参考图片',reference_video:'参考视频',source_video:'原始视频',video:'视频',image:'图片',document:'文件',audio:'音频',subtitle:'字幕'}[kind]||'素材');
    const executionLabel=row=>({analysis:'业务分析',analyze:'原片分析'}[row.title]||row.title||'执行记录');
    const codeMessage=error=>{
      const code=error?.message||String(error);
      if(/changed|conflict/.test(code))return '资料已变化，请核对当前版本；本次输入已保留。';
      if(code==='evidence_trial_not_ready')return '试销依据或约束尚未满足，请先补齐缺项。';
      if(/reference/.test(code))return '引用不属于当前商品或当前版本，请重新选择依据。';
      if(/rights/.test(code))return '记录商用或自有素材时，需要填写授权依据。';
      if(/invalid_url/.test(code))return '请填写与所选平台匹配的公开HTTPS商品链接，去除账号或令牌参数。';
      if(code==='evidence_invalid_date')return '请填写含时区的有效日期，并核对截止时间。';
      if(code==='evidence_future_observation')return '采集时间晚于当前时间，请核对后重新保存。';
      if(/image/.test(code))return '原图未完成读取或上传，请核对文件、来源与当前版本。';
      if(/^evidence_|^invalid_/.test(code))return '本次资料未保存，请核对必填项、日期和数值；输入已保留。';
      return '保存结果尚未确认，请先核对保存结果；不会自动重复创建。';
    };
    const sourcing=window.CommerceSourcing?.({api,repaint,onDirty:()=>onDirty(dirty()),onDraft(payload){if(s.edit||s.busy)return false;const row=s.data.sources.find(r=>!r.archived&&r.platform===payload.platform&&r.url===payload.url);if(row){payload.quote_ids=clone(row.quote_ids);const urls=new Set(row.images.map(i=>i.url));payload.images=[...clone(row.images),...payload.images.filter(i=>!urls.has(i.url))].slice(0,12);}s.edit={kind:'source',entryId:row?.id||'',revision:row?.revision||0,payload,base:s.data.dossier_sha256,key:crypto.randomUUID(),dirty:true,submitted:null,original:row?Object.fromEntries(SOURCE_KEYS.map(k=>[k,clone(row[k])])):clone(payload)};s.section='all';s.notice='已带入渠道商品资料，请核对款式、原图与价格口径后保存来源。';onDirty(true);return true;}});
    const dirty=()=>!!s.edit?.dirty||!!s.edit?.submitted||s.uploading||s.busy||!!sourcing?.hasUnsavedChanges()||!!sourcing?.hasActiveMutation();
    function changed(paint=false){if(s.edit)s.edit.dirty=true;onDirty(dirty());if(paint)repaint();}
    function clearImages(){s.images.clear();s.loadingImages.clear();}
    async function enter(caseId,{force=false}={}){
      if(caseId!==s.caseId&&dirty()){s.error='当前商品有未保存输入，请先保存或明确放弃。';repaint();return false;}
      if(caseId===s.caseId&&s.data&&!force)return true;
      if(caseId!==s.caseId){clearImages();s.edit=null;s.history=null;s.data=null;s.caseId=caseId;s.error='';if(sourcing)void sourcing.enter(caseId,{load:false});}
      const epoch=++s.epoch;s.loading=true;repaint();
      try{const d=await api('commerce_product_evidence_get',{case_id:caseId});if(epoch!==s.epoch||caseId!==s.caseId)return false;s.data=d;s.error='';if(s.section==='channels')await sourcing?.enter(caseId,{force:true});return epoch===s.epoch;}
      catch(error){if(epoch===s.epoch)s.error=codeMessage(error);return false;}
      finally{if(epoch===s.epoch){s.loading=false;repaint();}}
    }
    function sourceById(id){return s.data?.sources.find(r=>r.id===id);}
    function sourceEditor(id){
      if(dirty()){s.error='请先保存或放弃当前编辑。';repaint();return;}
      const row=id?sourceById(id):null;
      const payload=row?Object.fromEntries(SOURCE_KEYS.map(k=>[k,clone(row[k])])):{kind:'supplier',platform:'1688',label:'',url:'',model:'',variant:'',observed_at:stamp(),valid_until:'',review_state:'unreviewed',verification_note:'',rights_status:'unknown',rights_evidence:'',notes:'',quote_ids:[],images:[],metrics:{},archived:false};
      s.edit={kind:'source',entryId:id||'',revision:row?.revision||0,payload,base:s.data.dossier_sha256,key:crypto.randomUUID(),dirty:false,submitted:null,original:clone(payload)};s.error='';s.notice='';s.section='all';repaint();
    }
    function proposalEditor(){
      if(dirty()){s.error='请先保存或放弃当前编辑。';repaint();return;}
      s.edit={kind:'proposal',payload:Object.fromEntries(PROPOSAL_KEYS.map(k=>[k,s.data.proposal[k]??(k==='currency'?'':null)])),revision:s.data.proposal.revision,base:s.data.dossier_sha256,key:crypto.randomUUID(),dirty:false,submitted:null};s.edit.original=clone(s.edit.payload);s.error='';s.notice='';repaint();
    }
    function reviewEditor(){
      if(dirty()){s.error='请先保存或放弃当前编辑。';repaint();return;}
      s.edit={kind:'review',payload:{decision:'hold',reason:'',checks:Object.fromEntries(Object.keys(s.data.criteria).map(k=>[k,{status:'pending',note:'资料待核对',evidence_refs:[]}]))},base:s.data.dossier_sha256,key:crypto.randomUUID(),dirty:false,submitted:null};s.error='';s.notice='';s.section='reviews';repaint();
    }

    function currentPayload(e){
      if(e.kind==='source'){const row=sourceById(e.entryId);return row?Object.fromEntries(SOURCE_KEYS.map(k=>[k,clone(row[k])])):null;}
      if(e.kind==='proposal')return Object.fromEntries(PROPOSAL_KEYS.map(k=>[k,clone(s.data.proposal[k])]));
      return null;
    }
    function displayValue(v){
      if(v==null||v==='')return '未填写';
      if(Array.isArray(v))return v.map(x=>typeof x==='object'?(x.label||x.url||x.media_id):x).join('；')||'无';
      if(typeof v==='object')return Object.entries(v).map(([k,x])=>(metricLabels[k]||k)+'：'+(x??'未知')).join('；');
      if(typeof v==='boolean')return v?'是':'否';
      return String(v);
    }
    function conflictView(e){
      if(!e||e.submitted||e.base===s.data.dossier_sha256)return '';
      const current=currentPayload(e),original=e.original||{};
      const labels={kind:'来源类型',platform:'平台',label:'名称',url:'原始链接',model:'型号',variant:'款式',observed_at:'采集时间',valid_until:'有效至',review_state:'核对状态',verification_note:'核对依据',rights_status:'素材权利',rights_evidence:'授权依据',notes:'原文与备注',quote_ids:'报价关联',images:'图片引用',metrics:'市场数据',archived:'归档',customer_need:'客户需求',selection_reason:'选择理由',differentiation:'差异化',risks:'风险',currency:'币种',trial_quantity:'数量',trial_budget:'总投入',max_loss:'最大损失',min_contribution_rate:'最低贡献率',conditions:'进入条件'};
      const keys=current?Object.keys(e.payload).filter(k=>JSON.stringify(original[k])!==JSON.stringify(current[k])||JSON.stringify(original[k])!==JSON.stringify(e.payload[k])):[];
      return `<section class="pe-notice pe-conflict"><h4>当前资料已变化，请核对差异</h4><p>${e.kind==='review'?'继续编辑会把六项判断重置为待补证，并移除已失效的引用；原意见保留。':'继续编辑会保留你的修改，使用后台未被你修改的新字段。双方都改过的字段以你的输入为准；图片与报价关联按增删合并，请核对后再保存。'}</p>${keys.length?ui.table(['字段','编辑起点','后台当前值','你的输入'],keys.map(k=>`<tr><th>${esc(labels[k]||k)}</th><td>${esc(displayValue(original[k]))}</td><td>${esc(displayValue(current[k]))}</td><td>${esc(displayValue(e.payload[k]))}</td></tr>`)):'<p>关联证据版本已更新，当前输入仍然保留。</p>'}${button('核对差异后继续编辑','rebase',{disabled:s.busy})}</section>`;
    }
    function mergeValue(original,draft,current){
      if(JSON.stringify(original)===JSON.stringify(draft))return clone(current);
      if(Array.isArray(original)&&Array.isArray(draft)&&Array.isArray(current)){
        const id=x=>typeof x==='object'?(x.media_id||x.url)+':'+x.role:String(x);
        const base=new Set(original.map(id)),wanted=new Map(draft.map(x=>[id(x),x]));
        const merged=current.filter(x=>!base.has(id(x))||wanted.has(id(x))).map(x=>wanted.get(id(x))||x);
        const seen=new Set(merged.map(id));for(const x of draft)if(!base.has(id(x))&&!seen.has(id(x))){merged.push(x);seen.add(id(x));}
        return clone(merged);
      }
      if(original&&draft&&current&&typeof original==='object'&&typeof draft==='object'&&typeof current==='object'&&!Array.isArray(original)&&!Array.isArray(draft)&&!Array.isArray(current)){
        const result={...current};for(const k of new Set([...Object.keys(original),...Object.keys(draft)])){if(!Object.hasOwn(draft,k)){if(Object.hasOwn(original,k))delete result[k];}else if(!Object.hasOwn(original,k))result[k]=clone(draft[k]);else result[k]=mergeValue(original[k],draft[k],current[k]??null);}return result;
      }
      return clone(draft);
    }
    function rebase(){
      const e=s.edit;if(!e||s.busy||e.submitted)return;
      const current=currentPayload(e);
      if(e.kind==='review'){
        const valid=new Set(s.data.available_evidence.map(x=>x.id));
        for(const row of Object.values(e.payload.checks)){row.status='pending';row.evidence_refs=row.evidence_refs.filter(x=>valid.has(x));}
      }else if(current){
        e.payload=mergeValue(e.original||{},e.payload,current);e.original=clone(current);
        e.revision=e.kind==='source'?sourceById(e.entryId).revision:s.data.proposal.revision;
      }else if(e.kind==='source'&&e.entryId){s.error='当前来源未读到，请重新核对来源范围；输入保留。';repaint();return;}
      e.base=s.data.dossier_sha256;e.key=crypto.randomUUID();e.dirty=true;s.error='';s.notice='已按核对结果继续编辑，请检查字段和引用后保存。';onDirty(dirty());repaint();
    }
    function editView(){
      const e=s.edit;if(!e)return '';
      const disabled=s.busy||!!e.submitted,p=e.payload;let body='';
      if(e.kind==='source'){
        const platforms=Object.fromEntries(s.data.platforms.map(p=>[p.id,p.label]));
        body=`<div class="pe-form-grid">${pick('来源类型','kind',p.kind,kinds,{disabled})}${pick('来源平台','platform',p.platform,platforms,{disabled})}${input('供应商或商品名称','label',p.label,'text',{disabled,maxlength:1000})}${input('原始商品链接','url',p.url,'url',{disabled})}${input('型号','model',p.model,'text',{disabled})}${input('款式与配件','variant',p.variant,'text',{disabled})}${input('采集时间（含时区）','observed_at',p.observed_at,'text',{disabled})}${input('资料有效至（可留空）','valid_until',p.valid_until,'text',{disabled})}${pick('资料核对','review_state',p.review_state,states,{disabled})}${pick('图片与资料权利','rights_status',p.rights_status,rights,{disabled})}</div>${area('核对依据与冲突','verification_note',p.verification_note,{disabled})}${area('授权依据或文件说明','rights_evidence',p.rights_evidence,{disabled})}${area('原文、规格、包装和备注','notes',p.notes,{disabled})}`;
        if(p.kind!=='supplier')body+=`<fieldset class="pe-fieldset"><legend>有来源的市场数据，缺项保持空白</legend><div class="pe-form-grid">${Object.entries(metricLabels).map(([k,label])=>input(label,'metrics.'+k,p.metrics[k],k==='currency'?'text':'number',{disabled,min:0,step:'any'})).join('')}</div></fieldset>`;
        if(p.kind==='supplier')body+=`<fieldset class="pe-fieldset"><legend>关联原报价记录</legend>${s.data.quotes.length?s.data.quotes.map(q=>`<label class="pe-check"><input type="checkbox" data-pe-quote="${esc(q.quote_id)}" ${p.quote_ids.includes(q.quote_id)?'checked':''} ${disabled?'disabled':''}>${esc(q.fields.supplier||q.quote_id)} · ${money(q.fields.purchase_cost,q.fields.currency)}</label>`).join(''):'<p>尚无原报价。保存来源后可进入“管理报价”补充。</p>'}</fieldset>`;
        body+=`${area('原始图片地址（每行一个，上传图片会保留）','image_links',p.images.filter(i=>!i.media_id).map(i=>i.url).join('\n'),{disabled})}${p.images.filter(i=>i.media_id).map((i,n)=>`<p>${esc(i.label||'已存原图')} ${button('移除本版本引用','image-remove',{'data-index':p.images.indexOf(i),disabled})}</p>`).join('')}<label class="pe-check"><input type="checkbox" data-pe-field="archived" ${p.archived?'checked':''} ${disabled?'disabled':''}>归档此来源，保留历史记录</label>`;
      }else if(e.kind==='proposal'){
        body=`${area('目标客户与需求','customer_need',p.customer_need,{disabled})}${area('为什么选择这个商品','selection_reason',p.selection_reason,{disabled})}${area('能兑现的差异化','differentiation',p.differentiation,{disabled})}${area('风险与放弃条件','risks',p.risks,{disabled})}<div class="pe-form-grid">${input('经营币种','currency',p.currency,'text',{disabled})}${input('首测数量','trial_quantity',p.trial_quantity,'number',{disabled,min:1})}${input('总投入上限','trial_budget',p.trial_budget,'number',{disabled,min:0,step:'any'})}${input('最大损失上限','max_loss',p.max_loss,'number',{disabled,min:0,step:'any'})}${input('最低贡献率（%）','min_contribution_rate',p.min_contribution_rate==null?'':p.min_contribution_rate*100,'number',{disabled,min:0,max:100,step:'any'})}</div>${area('进入条件与复查安排','conditions',p.conditions,{disabled})}`;
      }else{
        body=`${pick('本次结论','review.decision',p.decision,decisions,{disabled})}${area('总体理由与下一步','review.reason',p.reason,{disabled})}${Object.entries(s.data.criteria).map(([key,label])=>`<fieldset class="pe-fieldset"><legend>${esc(label)}</legend>${pick('判断','checks.'+key+'.status',p.checks[key].status,{pending:'待补证',pass:'本地核对通过',fail:'不满足'},{disabled})}${area('依据与理由','checks.'+key+'.note',p.checks[key].note,{disabled})}<details><summary>引用当前版本证据 · ${p.checks[key].evidence_refs.length}条</summary><div class="pe-evidence-options">${s.data.available_evidence.map(r=>`<label class="pe-check"><input type="checkbox" data-pe-check="${key}" data-ref="${esc(r.id)}" ${p.checks[key].evidence_refs.includes(r.id)?'checked':''} ${disabled?'disabled':''}>${esc(r.label)}</label>`).join('')||'<p>先补充来源资料。</p>'}</div></details></fieldset>`).join('')}<p class="pw-meta">评审只记录本地选品结论；采购、投放与发布仍走原授权和核查。</p>`;
      }
      return `<section class="pw-section pe-editor" aria-label="${esc(e.kind==='source'?'来源编辑':e.kind==='proposal'?'选品理由编辑':'选品评审编辑')}"><h3>${e.kind==='source'?(e.entryId?'维护原始来源':'新增原始来源'):e.kind==='proposal'?'维护选品理由与约束':'记录正式选品评审'}</h3>${conflictView(e)}${body}${input('记录人','actor',s.actor,'text',{disabled})}<div class="pw-form-actions">${e.submitted?button('核对保存结果','reconcile',{},true)+button('使用原请求安全重试','retry',{disabled:s.busy}):button('保存'+(e.kind==='source'?'来源':e.kind==='proposal'?'理由与约束':'评审'),e.kind+'-save',{disabled:s.busy},true)}${button('放弃未保存修改','discard',{disabled:s.busy})}</div></section>`;
    }

    function historyView(){
      const row=s.history;if(!row)return '';
      return `<section class="pw-section pe-history-view"><header class="pe-card-heading"><div><h3>${esc(row.label)} · 历史v${row.revision}</h3><p>${esc(row.actor)} · ${esc(when(row.saved_at))}</p></div>${button('关闭历史版本','history-close')}</header><p class="pw-meta">只读查看原始版本，不覆盖当前来源。</p><p>${link(row.url,'该版本原始链接',row)}</p><p>${esc([row.model,row.variant].filter(Boolean).join(' / '))}</p><p class="pe-note">${esc(row.notes)}</p><p>${esc(row.verification_note)}</p>${imagesView(row,true)}<small>SHA-256 ${esc(row.sha256)}</small></section>`;
    }
    function imagePreview(row,index,src){return `<button class="pe-image-preview" type="button" data-pe-action="image-preview" data-entry="${row.id}" data-source-sha="${row.sha256}" data-index="${index}" aria-label="放大原图：${esc(row.images[index].label||'来源图片')}"><img src="${esc(src)}" alt="${esc(row.images[index].label||'来源图片')}" loading="lazy"></button>`;}
    function imagesView(row,historical=false){
      if(!row.images.length)return '<p class="pe-missing">原始图片尚未取得。</p>';
      return `<div class="pe-images">${row.images.map((image,index)=>{
        const key=row.id+':'+row.sha256+':'+index,blob=s.images.get(key);
        return `<figure>${blob?imagePreview(row,index,blob):image.media_id?`<div class="pe-image-placeholder" data-pe-image="${esc(key)}" data-entry="${row.id}" data-source-sha="${row.sha256}" data-index="${index}">原图读取中…</div>`:`<div class="pe-image-placeholder">尚未留存图片<br>${historical?'':button('读取并留存原图','image-capture',{'data-entry':row.id,'data-index':index,disabled:s.busy||dirty()})}</div>`}<figcaption>${ui.badge(image.role==='generated'?'AI生成':image.role==='document'?'文件图片':'原始参考图',image.role==='generated'?'blue':'gray')}<span>${esc(image.label||'来源图片')}</span>${image.url?link(image.url,'图片原始地址',row,index):''}</figcaption></figure>`;
      }).join('')}</div>`;
    }
    function sourceCard(row){
      const quoteRows=s.data.quotes.filter(q=>row.quote_ids.includes(q.quote_id));
      return `<article class="pw-section pe-source-card" data-pe-source="${row.id}"><header class="pe-card-heading"><div><h3>${esc(row.label)}</h3><p>${esc(kinds[row.kind])} · ${esc(s.data.platforms.find(p=>p.id===row.platform)?.label||row.platform)} · v${row.revision}</p></div><div>${ui.badge(row.archived?'已归档':states[row.review_state],row.review_state==='conflict'?'danger':'gray')}${!row.fresh||!row.recent?ui.badge('日期待复核','warning'):''}</div></header><p>${link(row.url,'打开原始商品或资料',row)}</p><dl class="pe-facts"><div><dt>型号 / 款式</dt><dd>${esc([row.model,row.variant].filter(Boolean).join(' / ')||'待确认')}</dd></div><div><dt>采集时间</dt><dd>${esc(when(row.observed_at))}</dd></div><div><dt>素材权利</dt><dd>${esc(rights[row.rights_status])}</dd></div></dl>${row.notes?`<p class="pe-note">${esc(row.notes)}</p>`:''}${row.verification_note?`<p><strong>核对：</strong>${esc(row.verification_note)}</p>`:''}${row.rights_evidence?`<p><strong>授权依据：</strong>${esc(row.rights_evidence)}</p>`:''}${Object.keys(row.metrics).length?`<dl class="pe-facts">${Object.entries(row.metrics).map(([k,v])=>`<div><dt>${esc(metricLabels[k]||k)}</dt><dd>${v==null||v===''?'待补':esc(v)}</dd></div>`).join('')}</dl>`:''}${imagesView(row)}${quoteRows.length?`<div class="pe-quote-summary"><h4>原报价</h4>${quoteRows.map(q=>`<p>${money(q.fields.purchase_cost,q.fields.currency)} · 起订${esc(q.fields.moq??'待补')} · ${esc(formatQuoteStatus(q.status))} · v${q.revision}</p>`).join('')}</div>`:''}<div class="pw-form-actions">${button('维护来源','source-edit',{'data-entry':row.id,disabled:s.busy})}${row.kind==='supplier'?button('管理原报价','quotes'):''}<label class="pe-upload-label">上传原始图片<input type="file" data-pe-upload="${row.id}" aria-label="上传原始图片：${esc(row.label)}" accept="image/png,image/jpeg,image/webp" ${s.busy||dirty()?'disabled':''}></label></div><details><summary>来源历史 · ${row.history.length}个版本</summary><ol class="pe-history">${row.history.map(h=>`<li><strong>v${h.revision} · ${esc(h.actor)}</strong><p>${esc(when(h.at))} · ${esc(h.payload.label)} · ${esc(states[h.payload.review_state])}</p><p>${link(h.payload.url,'该版本原始链接',{id:row.id,sha256:h.sha256})} · 图片${h.payload.images.length}张</p>${button('查看此版本','source-version',{'data-entry':row.id,'data-revision':h.revision})}${h.payload.notes?`<p class="pe-note">${esc(h.payload.notes)}</p>`:''}<small>SHA-256 ${esc(h.sha256)}</small></li>`).join('')}</ol></details></article>`;
    }
    function proposalView(){
      const p=s.data.proposal;
      return `<section class="pw-section"><header class="pe-card-heading"><h3>选品理由与试销约束</h3>${button('维护理由与约束','proposal-edit',{disabled:s.busy})}</header><dl class="pe-facts">${[['目标客户与需求',p.customer_need],['选择理由',p.selection_reason],['差异化',p.differentiation],['风险与退出条件',p.risks],['币种',p.currency],['首测数量',p.trial_quantity],['总投入上限',p.trial_budget],['最大损失',p.max_loss],['最低贡献率',p.min_contribution_rate==null?null:(p.min_contribution_rate*100)+'%'],['进入条件',p.conditions]].map(([k,v])=>`<div><dt>${k}</dt><dd>${v==null||v===''?'待确定':esc(v)}</dd></div>`).join('')}</dl><details><summary>理由历史 · v${p.revision}</summary>${(p.history||[]).map(h=>`<p>v${h.revision} · ${esc(h.actor)} · ${esc(when(h.at))}</p><p class="pe-note">${esc(h.payload.selection_reason)}</p>`).join('')||'<p>尚未保存理由版本。</p>'}</details></section>`;
    }
    function reviewView(){
      return `<section class="pw-section"><header class="pe-card-heading"><h3>正式选品评审</h3>${button('记录本次评审','review-new',{disabled:s.busy},true)}</header><div class="pe-readiness">${s.data.readiness.gaps.length?`<p>有限试销仍缺以下依据：</p><ul>${s.data.readiness.gaps.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'<p>基础资料条件已满足，可由经营负责人逐项评审。</p>'}</div>${s.data.reviews.map(r=>`<article class="pe-review"><header>${ui.badge(decisions[r.decision],r.decision==='reject'?'danger':r.decision==='trial'?'blue':'warning')}${ui.badge(r.current?'依据版本当前':'依据已变化 · 需重评',r.current?'gray':'warning')}</header><p class="pe-note">${esc(r.reason)}</p><p class="pw-meta">${esc(r.actor)} · ${esc(when(r.at))}</p><details><summary>六项判断与引用</summary>${Object.entries(r.checks).map(([k,v])=>`<p><strong>${esc(s.data.criteria[k])}</strong> · ${esc({pending:'待补证',pass:'本地核对通过',fail:'不满足'}[v.status])}</p><p>${esc(v.note)}</p><ul>${v.evidence_refs.map(ref=>`<li>${esc(ref)}</li>`).join('')}</ul>`).join('')}<small>证据版本 ${esc(r.dossier_sha256)}</small></details></article>`).join('')||'<p class="pe-missing">尚未保存正式评审；有图片或任务回执不等于选品通过。</p>'}<p class="pw-meta">结论随当前证据版本核对，不授予任何采购、广告或平台发布权限。</p></section>`;
    }
    function originalViews(){
      const c=s.data.economics,values=s.data.cost_checkpoint.payload?.input||{};
      return `<section class="pw-section"><header class="pe-card-heading"><h3>原成本与报价</h3><div>${button('管理报价','quotes')}${button('进入成本测算','cost')}</div></header><p>当前测算：${c.status==='CALCULATED'?'已计算，仍需核对经营依据':'费用待补'}</p><dl class="pe-facts"><div><dt>采购参考</dt><dd>${money(values.purchase_cost,values.currency)}</dd></div><div><dt>售价</dt><dd>${money(values.price,values.currency)}</dd></div><div><dt>贡献</dt><dd>${money(c.contribution,c.currency)}</dd></div></dl>${c.missing?.length?`<p class="pw-meta">缺项：${c.missing.map(esc).join('、')}</p>`:''}</section><section class="pw-section"><header class="pe-card-heading"><h3>关联内容与 AI 素材</h3>${button('查看图片与视频','media')}</header>${s.data.projects.map(p=>`<h4>${esc(formatProjectLabel(p,s.data.projects))}</h4><p>${p.assets.length}个已登记素材</p><ul>${p.assets.map(a=>`<li>${esc(a.name)} · ${esc(assetLabel(a.kind))}</li>`).join('')}</ul>`).join('')||'<p>尚无关联创意项目。</p>'}</section>`;
    }
    function executionView(){
      return `<section class="pw-section"><header class="pe-card-heading"><h3>执行与维护记录</h3>${button('打开原任务记录','tasks')}</header>${(s.data.activity||[]).length?ui.table(['维护动作','记录人','时间'],s.data.activity.map(x=>`<tr><td>${esc(x.title)}</td><td>${esc(x.actor)}</td><td>${esc(when(x.at))}</td></tr>`)):''}<h4>原任务与媒体处理</h4>${s.data.executions.length?ui.table(['事项','来源','原状态','记录ID'],s.data.executions.map(x=>`<tr><td>${esc(executionLabel(x))}</td><td>${x.origin==='creative'?'媒体处理':'原任务'}</td><td>${esc(statusLabel(x.status))}</td><td><code title="${esc(x.id)}">#${esc(x.id.slice(-8))}</code></td></tr>`)):'<p>当前商品尚无关联执行记录。</p>'}<p class="pw-meta">来源保存与评审版本在各自历史中保留；任务是否成功不代替需求、成本或发布核验。</p></section>`;
    }
    function view(){
      if(!s.data)return `<section class="pw-section"><h2>商品证据档案</h2><p>${s.loading?'正在读取当前商品的证据…':'尚未读取当前商品。'}</p>${s.error?`<p role="alert">${esc(s.error)}</p>`:''}${button('重新读取','refresh')}</section>`;
      const filtered=s.data.sources.filter(r=>(s.showArchived||!r.archived)&&(s.section==='suppliers'?r.kind==='supplier':s.section==='competitors'?r.kind==='competitor':true));
      return `<div class="pe-workbench" data-pe-case="${esc(s.caseId)}"><section class="pw-section pe-heading"><header class="pe-card-heading"><div><h2>商品证据档案</h2><p>${esc(s.data.name)} · ${esc(s.data.case.scope.platform)} / ${esc(s.data.case.scope.market)}</p></div><div>${button('刷新证据','refresh',{disabled:s.busy||s.loading})}${button('导出当前档案','export',{disabled:s.busy})}</div></header><nav class="pe-sections" aria-label="证据档案分区">${Object.entries({all:'全部证据',suppliers:'货源',channels:'多渠道找货',competitors:'竞品',proposal:'理由与约束',reviews:'正式评审',executions:'执行记录'}).map(([key,label])=>button(label,'section',{'data-section':key,'aria-pressed':s.section===key})).join('')}</nav></section>${s.error?`<div class="pe-notice pe-error" role="alert">${esc(s.error)}</div>`:''}${s.notice?`<div class="pe-notice" role="status">${esc(s.notice)}</div>`:''}${historyView()}${editView()}${s.section==='channels'?(sourcing?.view()||'<p>渠道模块尚未加载，请刷新页面。</p>'):''}${['all','suppliers','competitors'].includes(s.section)?`<section class="pw-section"><header class="pe-card-heading"><h3>货源、竞品与原始资料</h3>${button('新增来源','source-new',{disabled:s.busy},true)}</header><label class="pe-check"><input type="checkbox" data-pe-show-archived ${s.showArchived?'checked':''}>显示已归档来源</label></section>${filtered.map(sourceCard).join('')||'<p class="pe-missing">该范围尚无来源记录。</p>'}`:''}${['all','proposal'].includes(s.section)?proposalView():''}${['all','reviews'].includes(s.section)?reviewView():''}${s.section==='all'?originalViews():''}${['all','executions'].includes(s.section)?executionView():''}</div>`;
    }
    function inputEvent(target){
      if(target.dataset.peSourcing!==undefined){void sourcing?.input(target);return;}
      if(target.dataset.peUpload){const row=sourceById(target.dataset.peUpload);if(row)void upload(row,target.files?.[0]);return;}
      if(target.dataset.peShowArchived!==undefined){s.showArchived=target.checked;repaint();return;}
      const e=s.edit;if(!e||e.submitted||s.busy)return;
      if(target.dataset.peQuote!==undefined){e.payload.quote_ids=target.checked?[...new Set([...e.payload.quote_ids,target.dataset.peQuote])]:e.payload.quote_ids.filter(x=>x!==target.dataset.peQuote);changed();return;}
      if(target.dataset.peCheck){const row=e.payload.checks[target.dataset.peCheck],ref=target.dataset.ref;row.evidence_refs=target.checked?[...new Set([...row.evidence_refs,ref])]:row.evidence_refs.filter(x=>x!==ref);changed();return;}
      const key=target.dataset.peField;if(!key)return;
      if(key==='actor'){s.actor=target.value;changed();return;}
      const value=target.type==='checkbox'?target.checked:target.value;
      if(key.startsWith('review.'))e.payload[key.split('.')[1]]=value;
      else if(key.startsWith('checks.')){const [,criterion,field]=key.split('.');e.payload.checks[criterion][field]=value;}
      else if(key.startsWith('metrics.')){const k=key.split('.')[1];e.payload.metrics[k]=k==='currency'?value.toUpperCase():value===''?null:Number(value);}
      else if(key==='image_links'){
        const previous=new Map(e.payload.images.filter(i=>!i.media_id).map(i=>[i.url,i])),kept=e.payload.images.filter(i=>i.media_id),existing=new Set(kept.map(i=>i.url));
        e.payload.images=[...kept,...[...new Set(value.split('\n').map(x=>x.trim()).filter(Boolean))].filter(u=>!existing.has(u)).map(u=>previous.has(u)?clone(previous.get(u)):({url:u,media_id:'',label:'页面原始图片（待核对）',role:'original'}))];
      }else if(['trial_quantity','trial_budget','max_loss','min_contribution_rate'].includes(key))e.payload[key]=value===''?null:Number(value)/(key==='min_contribution_rate'?100:1);
      else if(Object.hasOwn(e.payload,key))e.payload[key]=value;
      changed(key==='kind'||key==='platform');
    }
    async function performWrite(op,args){
      const caseId=s.caseId,e=s.edit;s.busy=true;s.error='';e.submitted={op,args:clone(args)};repaint();
      try{await api(op,args);if(caseId!==s.caseId)return;s.edit=null;onDirty(false);s.notice='已保存当前商品的新版本。';await enter(caseId,{force:true});}
      catch(error){if(caseId!==s.caseId)return;s.error=codeMessage(error);if(/^evidence_|^invalid_/.test(error.message||''))e.submitted=null;}
      finally{if(caseId===s.caseId){s.busy=false;onDirty(dirty());repaint();}}
    }
    async function save(kind){
      const e=s.edit;if(!e||e.kind!==kind||s.busy)return;
      let invalid;
      if(kind==='source'&&!e.payload.label.trim())invalid=['label','请填写供应商或商品名称。'];
      else if(kind==='source'&&['supplier','competitor'].includes(e.payload.kind)&&!e.payload.url.trim())invalid=['url','请填写原始商品链接。'];
      else if(kind==='review'&&!e.payload.reason.trim())invalid=['review-reason','请填写总体理由与下一步。'];
      else if(!s.actor.trim())invalid=['actor','请填写记录人。'];
      if(invalid){s.error=invalid[1];repaint();document.getElementById('pe-'+invalid[0])?.focus();return;}
      const args={case_id:s.caseId,payload:clone(e.payload),expected_dossier_sha256:e.base,idempotency_key:e.key,actor:s.actor};
      if(kind==='source'){args.entry_id=e.entryId;args.expected_revision=e.revision;}
      if(kind==='proposal')args.expected_revision=e.revision;
      if(kind==='review'&&e.payload.decision==='trial'&&!s.data.readiness.trial_prerequisites_met){s.error='试销条件尚未满足，请先补齐资料。';repaint();return;}
      await performWrite('commerce_product_evidence_'+(kind==='source'?'source_save':kind==='proposal'?'proposal_save':'review_save'),args);
    }
    async function reconcile(){
      const e=s.edit;if(!e?.submitted||s.busy)return;
      s.busy=true;repaint();const caseId=s.caseId;
      try{const r=await api('commerce_product_evidence_operation_get',{case_id:s.caseId,idempotency_key:e.key});if(caseId!==s.caseId)return;if(r.status==='saved'){s.edit=null;onDirty(false);s.notice='已核对原保存回执。';await enter(s.caseId,{force:true});}else{s.notice='尚未查到回执，可使用原请求安全重试。';}}
      catch(error){if(caseId===s.caseId)s.error=codeMessage(error);}
      finally{if(caseId===s.caseId){s.busy=false;onDirty(dirty());repaint();}}
    }
    async function readImage(row,index,epoch){
      const key=row.id+':'+row.sha256+':'+index,pendingKey=key+':'+epoch;if(s.images.has(key)||s.loadingImages.has(pendingKey))return;
      s.loadingImages.add(pendingKey);let offset=0,parts=[],mime='image/png';
      try{do{const r=await api('commerce_product_evidence_image',{case_id:s.caseId,entry_id:row.id,expected_entry_sha256:row.sha256,index,offset});if(epoch!==s.epoch)return;if(r.status!=='archived')return;mime=r.mime;parts.push(r.content_base64);offset=r.next_offset;}while(offset!==null);
        if(epoch!==s.epoch)return;const src='data:'+mime+';base64,'+parts.join('');s.images.set(key,src);
        const node=document.getElementById('pe-image-node-'+row.id+'-'+row.revision+'-'+index);if(node)node.innerHTML=imagePreview(row,index,src);
      }catch{const node=document.getElementById('pe-image-node-'+row.id+'-'+row.revision+'-'+index);if(node&&epoch===s.epoch)node.textContent='原图未读到，请刷新后重试。';}
      finally{s.loadingImages.delete(pendingKey);}
    }
    function afterRender(){
      const epoch=s.epoch;
      for(const node of document.querySelectorAll('[data-pe-image]')){
        const row=[...(s.data?.sources||[]),...(s.history?[s.history]:[])].find(r=>r.id===node.dataset.entry&&(!node.dataset.sourceSha||r.sha256===node.dataset.sourceSha)),index=Number(node.dataset.index);if(row)node.id='pe-image-node-'+node.dataset.entry+'-'+row.revision+'-'+index;
        if(row)void readImage(row,index,epoch);
      }
    }
    async function upload(row,file){
      if(!file||s.busy||dirty())return;
      if(file.size>5*1024*1024){s.error='单张原图请控制在5MB以内。';repaint();return;}
      const caseId=s.caseId;s.busy=true;s.uploading=true;onDirty(true);s.error='';s.notice='正在上传原图…';repaint();
      try{
        const bytes=new Uint8Array(await file.arrayBuffer()),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
        const start=await api('commerce_product_evidence_upload_begin',{case_id:caseId,entry_id:row.id,expected_entry_sha256:row.sha256,filename:file.name,size:bytes.length,sha256:sha,source_url:'',role:'original',actor:s.actor});
        for(let n=start.next_index;n<Math.ceil(bytes.length/start.chunk_bytes);n++){
          const part=bytes.subarray(n*start.chunk_bytes,(n+1)*start.chunk_bytes);let binary='';for(const b of part)binary+=String.fromCharCode(b);
          await api('commerce_product_evidence_upload_chunk',{case_id:caseId,upload_id:start.upload_id,index:n,content_base64:btoa(binary)});
        }
        await api('commerce_product_evidence_upload_finish',{case_id:caseId,upload_id:start.upload_id});
        if(caseId===s.caseId){s.notice='原图已保存，来源形成新版本。';await enter(caseId,{force:true});}
      }catch(error){if(caseId===s.caseId)s.error=codeMessage(error);}
      finally{if(caseId===s.caseId){s.busy=false;s.uploading=false;onDirty(dirty());repaint();}}
    }
    async function action(name,target={dataset:{}}){
      if(name.startsWith('sourcing-')){await sourcing?.action(name.slice(9),target);return;}
      if(name==='origin-open'){const caseId=s.caseId;try{const r=await api('commerce_product_evidence_origin_open',{case_id:caseId,entry_id:target.dataset.entry,expected_entry_sha256:target.dataset.sourceSha,index:Number(target.dataset.index)});if(caseId===s.caseId){s.notice=r.status==='requested'?'已请求本机浏览器打开原始地址，请在浏览器核对页面。':'本机浏览器未能打开，请复制原始链接后查看。';repaint();}}catch(error){if(caseId===s.caseId){s.error=codeMessage(error);repaint();}}return;}
      if(name==='refresh'){await enter(s.caseId,{force:true});return;}
      if(name==='section'){s.section=target.dataset.section;if(s.section==='channels')await sourcing?.enter(s.caseId,{force:true});repaint();return;}
      if(name==='history-close'){s.history=null;repaint();return;}
      if(name==='source-version'){const epoch=s.epoch;try{const r=await api('commerce_product_evidence_source_get',{case_id:s.caseId,entry_id:target.dataset.entry,revision:Number(target.dataset.revision)});if(epoch===s.epoch){s.history=r.entry;repaint();}}catch(error){if(epoch===s.epoch){s.error=codeMessage(error);repaint();}}return;}
      if(name==='image-preview'){const key=target.dataset.entry+':'+target.dataset.sourceSha+':'+Number(target.dataset.index),src=s.images.get(key),row=[...(s.data?.sources||[]),...(s.history?[s.history]:[])].find(r=>r.id===target.dataset.entry&&r.sha256===target.dataset.sourceSha);if(src&&row)onImagePreview(src,row.images[Number(target.dataset.index)]?.label||'来源原图');return;}
      if(name==='source-new'){sourceEditor('');return;}
      if(name==='source-edit'){sourceEditor(target.dataset.entry);return;}
      if(name==='proposal-edit'){proposalEditor();return;}
      if(name==='review-new'){reviewEditor();return;}
      if(name==='rebase'){rebase();return;}
      if(name==='discard'){s.edit=null;s.error='';onDirty(false);repaint();return;}
      if(name.endsWith('-save')){await save(name.split('-')[0]);return;}
      if(name==='reconcile'){await reconcile();return;}
      if(name==='retry'){const e=s.edit;if(e?.submitted)await performWrite(e.submitted.op,e.submitted.args);return;}
      if(name==='image-remove'&&s.edit?.kind==='source'&&!s.edit.submitted){s.edit.payload.images.splice(Number(target.dataset.index),1);changed(true);return;}
      if(name==='image-capture'){
        const row=sourceById(target.dataset.entry);if(!row||s.busy||dirty())return;const caseId=s.caseId;s.busy=true;s.error='';repaint();
        try{await api('commerce_product_evidence_image_capture',{case_id:s.caseId,entry_id:row.id,expected_entry_sha256:row.sha256,index:Number(target.dataset.index),actor:s.actor});if(caseId===s.caseId){s.notice='已留存原图，来源形成新版本。';await enter(s.caseId,{force:true});}}
        catch(error){if(caseId===s.caseId)s.error=codeMessage(error);}finally{if(caseId===s.caseId){s.busy=false;onDirty(dirty());repaint();}}return;
      }
      if(name==='export'){const blob=URL.createObjectURL(new Blob([JSON.stringify(s.data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=blob;a.download='product-evidence-'+s.caseId+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(blob),1000);return;}
      if(['quotes','cost','media','tasks'].includes(name))onNavigate(name);
    }
    return {enter,view,afterRender,action,input:inputEvent,hasUnsavedChanges:dirty,hasActiveMutation:()=>s.busy||!!sourcing?.hasActiveMutation(),discardChanges(){sourcing?.discard();s.edit=null;s.error='';onDirty(dirty());},dispose(){s.epoch++;sourcing?.dispose();clearImages();}};
  };
})();

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
