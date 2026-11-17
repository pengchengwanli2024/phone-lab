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
