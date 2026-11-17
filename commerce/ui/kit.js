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
