/* Shared workspace navigation and view continuity; navigation, explicit private form checkpoints and view continuity. */
window.CommerceWorkspaceContinuity=(options)=>{
 'use strict';
 const {ui,api}=options;
 const views=new Map();
 const navExpanded=new Map();
 let navScroll=0,navTab=null;
 const esc=ui.escape;
 const open=(label,target,description='',primary=false)=>ui.button({label,description,variant:primary?'primary':'secondary',action:'workspace-open',attrs:{'data-target':target,class:'workspace-next-action'}});
 const contextualDetails={organization:'选择明确的商品工作项，核对资料缺项与产物交接。',alerts:'核对订单、库存的来源与时间；已阅和处理完成分别记录。',agent:'选择岗位和读取范围后提问，审阅建议再提交本地任务。',tasks:'读取共享处理回执；排队与产物验收分别记录。',operations:'填写已核对的币种、采购与履约成本，获得本地测算。',orders:'先核对订单来源、时间与范围，再准备处理草稿。',connections:'查阅业务知识原文；参考资料仍须对照来源核实。',research:'保留原文、中文和出处，补齐本次分析依据。',pilots:'选择已有候选，沿用来源、补证模板与原任务。'};
 function actions(input){return window.CommerceNextActions.plan(input)}
 function nextSteps(input,{aside=false}={}){
  const items=actions(input),title=input.tab==='overview'?'优先事项':'当前工作可继续';
  if(!items.length)return '';
  return `<section class="workspace-next ${aside?'workspace-next-aside':''}" aria-label="${title}"><div class="workspace-next-heading"><h2>${ui.icon('doc')}${title}</h2></div><div class="workspace-next-list">${items.map(item=>`<div class="workspace-next-item" data-next-id="${esc(item.id)}">${open(item.title,item.target,input.tab==='overview'?item.detail:contextualDetails[item.target]||item.detail)}${item.tone==='warning'?ui.badge('待核对','warning'):ui.icon('chevronDown')}</div>`).join('')}</div></section>`;
 }
 function contextual(input){
  if(['overview','intelligence'].includes(input.tab))return '';
  return `<details class="workspace-related" id="workspace-related-${esc(input.tab)}"><summary>相关资料与后续步骤</summary>${nextSteps(input)}</details>`;
 }
 function journey(tab){
  const path=[['pilots','商品试点'],['research','调研来源'],['operations','成本测算'],['creative','创意草稿'],['organization','交付复验']];
  if(!path.some(([key])=>key===tab))return '';
  return `<details class="workspace-path" id="workspace-path-${esc(tab)}"><summary>试点路径 · ${esc(path.find(([key])=>key===tab)[1])}</summary><nav aria-label="试点工作路径">${path.map(([key,label])=>ui.button({label,action:'workspace-open',attrs:{'data-target':key,'aria-current':key===tab?'step':false}})).join('')}</nav><p class="muted" data-ui-help>入口按工作顺序排列；资料、草稿与实际验收分别核对。</p></details>`;
 }
 function scopeLabel(tab){return ({operations:'运营测算 · 本次填写 / 本地结果待审阅',research:'调研资料 · 原文与中文 / 来源待核实',alerts:'经营提醒 · 按本页来源 / 已阅不代表处理完成',tasks:'共享任务 · 排队、执行与产物分别记录',connections:'连接与知识 · 配置、调用与授权分别核对'})[tab]||''}
 function disclosure(content,{id,title,open:expanded=false}={}){return `<details class="workspace-disclosure" id="${esc(id)}" ${expanded?'open':''}><summary>${esc(title)}</summary>${content}</details>`}
 function inputIdentity(element){
  if(!element||!element.matches('button,input,select,textarea,a,[tabindex]'))return null;
  if(element.id)return '#'+CSS.escape(element.id);
  const attributes=[...element.attributes].filter(a=>a.name==='name'||a.name.startsWith('data-'));
  if(!attributes.length)return null;
  return element.tagName.toLowerCase()+attributes.map(a=>`[${a.name}="${CSS.escape(a.value)}"]`).join('');
 }
 function detailsState(root){const counts=new Map();return [...root.querySelectorAll('.main-scroll details')].map(d=>{const label=d.id||d.querySelector(':scope > summary')?.textContent.trim()||'',n=counts.get(label)||0;counts.set(label,n+1);return {key:label+'#'+n,open:d.open}})}
 function capture(){
  const root=document.querySelector('.app');if(!root?.dataset.workspaceTab)return;
  navTab=root.dataset.workspaceTab;
  const nav=root.querySelector('.admin-sidebar-nav');if(nav)navScroll=nav.scrollTop;
  for(const group of root.querySelectorAll('[data-nav-group]'))navExpanded.set(group.dataset.navGroup,group.open);
  const tab=root.dataset.workspaceTab,scroll=root.querySelector('.main-scroll');
  if(root.dataset.viewReady!=='true')return;
  const focused=root.contains(document.activeElement)?document.activeElement:null;
  views.set(tab,{scroll:scroll?.scrollTop||0,details:detailsState(root),selector:inputIdentity(focused),start:focused?.selectionStart,end:focused?.selectionEnd});
 }
 function restore(tab,{focusTitle=false,ready=true}={}){
  const root=document.querySelector('.app'),saved=views.get(tab);if(!root)return;
  const nav=root.querySelector('.admin-sidebar-nav');if(nav)nav.scrollTop=navScroll;
  if(saved){const states=new Map(saved.details.map(d=>[d.key,d.open])),counts=new Map();for(const d of root.querySelectorAll('.main-scroll details')){const label=d.id||d.querySelector(':scope > summary')?.textContent.trim()||'',n=counts.get(label)||0;counts.set(label,n+1);if(states.has(label+'#'+n))d.open=states.get(label+'#'+n)}}
  if(!document.querySelector('.dialog')){
   const target=focusTitle?document.querySelector('#workspace-title'):saved?.selector?root.querySelector(saved.selector):null;
   if(target&&!target.disabled&&target.getClientRects().length){target.focus({preventScroll:true});if(!focusTitle&&typeof saved?.start==='number'&&target.setSelectionRange&&(target.tagName==='TEXTAREA'||['text','search','url','tel','password'].includes(target.type)))target.setSelectionRange(saved.start,saved.end)}
  }
  if(ready){const scroll=root.querySelector('.main-scroll');if(scroll)scroll.scrollTop=saved?.scroll||0;}
 }
 function sidebar(items,tab){
  const groups=ui.navigationGroups(items);
  const link=key=>ui.button({label:key==='overview'?'运营台':items[key],leadingIcon:key==='overview'?'grid':'',attrs:{class:'admin-nav-link','data-tab':key,'aria-current':key===tab?'page':false}});
  const expanded=group=>(tab!==navTab&&group.modules.includes(tab))||(navExpanded.get(group.id)??group.modules.includes(tab));
  return `<aside class="admin-sidebar" aria-label="平台导航"><a class="admin-brand" href="/">${ui.icon('store')}<strong>AI 跨境运营平台</strong></a><nav class="admin-sidebar-nav" aria-label="业务模块">${groups.map(group=>group.id==='home'?link('overview'):`<details data-nav-group="${group.id}" ${expanded(group)?'open':''}><summary>${ui.icon(group.icon)}<span>${esc(group.label)}</span>${ui.icon('chevronDown')}</summary><div class="admin-nav-children">${group.modules.map(link).join('')}</div></details>`).join('')}</nav><div class="admin-sidebar-footer">${ui.button({label:'AI 助手',leadingIcon:'spark',action:'copilot-open',attrs:{id:'workspace-copilot-sidebar',class:'admin-nav-link'}})}${ui.button({label:'设置与连接',leadingIcon:'gear',attrs:{class:'admin-nav-link','data-tab':'connections'}})}</div></aside>`;
 }
 function topbar(items,tab,controls){return `<header class="workspace-topbar" aria-label="工作台顶部导航"><div class="workspace-primary">${ui.button({label:'查找模块',leadingIcon:'search',shortcut:'⌘ K',action:'module-finder',attrs:{class:'admin-search','aria-label':'查找业务模块'}})}<span class="admin-breadcrumb">${esc(ui.moduleDetails(tab).group)}</span></div><div class="workspace-global-controls">${controls}</div></header>`}
 function quietCopy(){for(const note of document.querySelectorAll('.main-scroll [data-ui-help],.copilot-panel [data-ui-help]')){const heading=note.closest('section,.card')?.querySelector('h2,h3');if(heading&&!heading.title)heading.title=note.textContent.trim();note.remove()}}

 document.addEventListener('click',event=>{const menu=document.querySelector('.workspace-toolbar-menu');if(menu?.open&&!event.target.closest('.workspace-toolbar-menu'))menu.open=false});
 document.addEventListener('keydown',event=>{const menu=document.querySelector('.workspace-toolbar-menu');if(event.key==='Escape'&&menu?.open&&event.target.closest('.workspace-toolbar-menu')){menu.open=false;menu.querySelector('summary').focus();event.stopImmediatePropagation()}});
 const draftRevisions=new Map(),draftReads=new Map();
 const draftKey=scope=>JSON.stringify(scope);
 async function readDraft(scope){const row=await api('commerce_form_draft_get',{scope});draftRevisions.set(draftKey(scope),row.revision);return row}
 async function primeDraft(scope){const key=draftKey(scope);if(draftRevisions.has(key))return;if(!draftReads.has(key))draftReads.set(key,readDraft(scope).finally(()=>draftReads.delete(key)));return draftReads.get(key)}
 async function saveDraft(scope,payload){await primeDraft(scope);const row=await api('commerce_form_draft_save',{scope,payload,expected_revision:draftRevisions.get(draftKey(scope))});draftRevisions.set(draftKey(scope),row.revision);return row}
 function draftControls(form,scope){primeDraft(scope).catch(()=>{});return `<div class="form-actions" role="group" aria-label="本机输入草稿" title="仅保存在本机；恢复后需重新测算">${ui.button({label:'保存输入草稿',action:'form-save',attrs:{'data-form':form}})}${ui.button({label:'恢复已保存草稿',action:'form-restore',attrs:{'data-form':form}})}</div>`}
 return {nextSteps,contextual,journey,scopeLabel,disclosure,capture,restore,sidebar,topbar,quietCopy,draftControls,readDraft,saveDraft};
};
