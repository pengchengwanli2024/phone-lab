/* Persistent dashboard controls. No localStorage dependency in opaque hosts. */
window.CommerceIntelDashboard=({api,esc,repaint,onChange,onFocus,isActive})=>{
  const ui=window.CommerceUI;
  const titles={trade:'贸易资讯',macro:'宏观政策',energy:'能源资讯',logistics:'交通物流'};
  const base=()=>({layers:['earthquake','flood','storm','fire','drought','volcano','tsunami','other','waterways','flights'],panels:Object.keys(titles).map(id=>({id,visible:true,collapsed:false,wide:false})),language:'zh',time:'all',region:'global',link_map:false});
  let optionsExpanded=false;
  let preferences=base(),revision=0,ready=false,busy=false,error='',pending=null,layers=[],regions={},references=[];
  const copy=value=>JSON.parse(JSON.stringify(value));
  const stable=v=>Array.isArray(v)?v.map(stable):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,stable(v[k])])):v;
  const same=(a,b)=>JSON.stringify(stable(a))===JSON.stringify(stable(b));
  function preset(id){const p=base();if(id==='logistics'){p.layers=['earthquake','flood','storm','waterways','ports','flights','vessels'];p.time='168';p.panels=p.panels.map(v=>({...v,visible:v.id!=='macro'}));}else if(id==='hazards'){p.layers=p.layers.filter(k=>!['waterways','flights','vessels'].includes(k));p.time='168';p.link_map=true;p.panels=p.panels.map(v=>({...v,visible:false}));}return p;}
  const button=(label,action,attrs={})=>ui.button({label,variant:'quiet',attrs:{'data-intel-dashboard':action,disabled:busy||!ready||!!pending,...attrs}});
  function receive(value){revision=value.revision;preferences=copy(value.preferences);if(value.layers)layers=value.layers;if(value.regions)regions=value.regions;if(value.references)references=value.references;ready=true;}
  function commit(value,before){receive(value);error='';pending=null;onChange?.(copy(preferences),before);}
  async function enter(){if(busy)return;try{receive(await api('commerce_intel_dashboard_get'));error='';}catch{ready=false;error='仪表盘偏好暂时无法读取，可重试；当前显示默认地图。';}repaint();}
  async function change(patch){
    if(busy||!ready||!!pending||pending)return false;
    const before=copy(preferences),next={...copy(preferences),...copy(patch)};
    if(same(next,preferences))return true;
    const expected=revision,focusId=document.activeElement?.id;busy=true;error='';repaint();
    try{commit(await api('commerce_intel_dashboard_update',{expected_revision:expected,preferences:next}),before);return true;}
    catch(failure){
      try{
        const observed=await api('commerce_intel_dashboard_get');
        if(same(observed.preferences,next)){commit(observed,before);return true;}
        receive(observed);onChange?.(copy(preferences),before);
        error=failure.message==='intel_dashboard_conflict'?'其它界面已修改布局，已载入最新选择，请重新操作。':'保存未完成，原选择已保留，可明确重试。';
        if(observed.revision===expected)pending={next,expected,before};
      }catch{pending={next,expected,before};error='保存结果尚未确认，请检查连接后核对；不会自动重发。';}
      return false;
    }finally{busy=false;repaint();if(focusId)requestAnimationFrame(()=>document.getElementById(focusId)?.focus({preventScroll:true}));}
  }
  async function retry(){
    if(!pending||busy)return;const intent=pending;busy=true;repaint();
    try{
      const observed=await api('commerce_intel_dashboard_get');
      if(same(observed.preferences,intent.next)){commit(observed,intent.before);return;}
      receive(observed);pending=null;
      if(observed.revision!==intent.expected){error='其它界面已修改布局，已载入最新选择，请重新操作。';onChange?.(copy(preferences),intent.before);return;}
      busy=false;await change(intent.next);
    }catch{error='仍无法核对保存状态，请检查连接后重试。';}finally{busy=false;repaint();}
  }
  function controls(result,sources,liveSource=()=>null){
    const count=result?.map_stats?.by_layer||{};
    const presetControl=ui.select({id:'intel-dashboard-preset','aria-label':'仪表盘预设',title:'组合图层、时间和面板；保留检索条件',value:['overview','logistics','hazards'].find(k=>same(preferences,preset(k)))||'custom',disabled:busy||!ready||!!pending,'data-intel-dashboard-select':'preset',options:[{value:'custom',label:'自定义布局'},{value:'overview',label:'综合观察'},{value:'logistics',label:'贸易与物流'},{value:'hazards',label:'自然事件'}]});
    return `<div class="intel-dashboard-controls"><div class="intel-time-controls" role="group" aria-label="统一时间范围">${[['all','全部'],['1','1小时'],['6','6小时'],['24','24小时'],['48','48小时'],['168','7天']].map(([key,label])=>button(label,'time',{'data-value':key,id:'intel-time-'+key,'aria-pressed':preferences.time===key})).join('')}</div>${button('图层与视图 · '+preferences.layers.length,'options',{'aria-expanded':optionsExpanded,'aria-controls':'intel-control-options',class:'intel-options-toggle',disabled:false})}<div id="intel-control-options" class="intel-control-options" data-expanded="${optionsExpanded}">${presetControl}
      ${ui.select({id:'intel-map-region','aria-label':'地图区域',value:preferences.region,disabled:busy||!ready||!!pending,'data-intel-dashboard-select':'region',options:Object.entries(regions).map(([value,r])=>({value,label:r.label}))})}
      <details id="intel-layer-picker" class="intel-picker" ${document.querySelector('#intel-layer-picker')?.open?'open':''}><summary>图层 ${preferences.layers.length}</summary><div class="intel-picker-body"><strong>事件图层</strong>${layers.map(layer=>{const sourceIds=layer.sources.split(' / '),states=sources.filter(s=>sourceIds.includes(s.id));const observation=liveSource(layer.id);const health=layer.kind==='live_observation'?(observation?.status==='requires_authorization'?'评估快照 · 待许可':observation?.status==='requires_config'?'需要配置密钥':observation?.status==='failed'?'来源读取失败':observation?.availability==='expired'||observation?.status==='stale'?'观测已过期':observation?.mode==='local_evaluation'?(observation?.evaluation_session?.active?'本地连续测试':'本地开发测试 · 手动读取'):observation?.last_success?'发布方位置快照':'尚无观测'):layer.kind==='static_geographic_reference'?'地理参考 · 非实时状态':!states.some(s=>s.last_success)?'尚无采集':states.some(s=>s.status==='failed')?'来源异常，保留快照':states.some(s=>s.freshness==='stale')?'快照陈旧':'来源已采集';return `<label><input type="checkbox" id="intel-layer-${layer.id}" data-intel-dashboard-layer="${layer.id}" ${preferences.layers.includes(layer.id)?'checked':''} ${busy||!ready||!!pending?'disabled':''}><span>${esc(layer.name)}<small>${layer.kind==='static_geographic_reference'?references.filter(r=>r.layer===layer.id).length+' 个参考点':(layer.kind==='live_observation'?(observation?.matched||0):(count[layer.id]||0))+' 条坐标'} · ${health}</small></span></label>`}).join('')}<p>图层仅控制地图；开启“视野联动”后同步筛选资讯与面板。</p></div></details>
      <label class="intel-link-control"><input id="intel-map-link" type="checkbox" data-intel-dashboard-select="link_map" ${preferences.link_map?'checked':''} ${busy||!ready||!!pending?'disabled':''}>视野联动</label>
      <details id="intel-panel-picker" class="intel-picker" ${document.querySelector('#intel-panel-picker')?.open?'open':''}><summary>面板配置</summary><div class="intel-picker-body">${preferences.panels.map(p=>`<label><input type="checkbox" id="intel-panel-visible-${p.id}" data-intel-dashboard-panel="${p.id}" ${p.visible?'checked':''} ${busy||!ready||!!pending?'disabled':''}>${titles[p.id]}</label>`).join('')}${button('恢复默认仪表盘','reset')}</div></details>
      ${ui.select({id:'intel-language','aria-label':'情报显示语言',value:preferences.language,disabled:busy||!ready||!!pending,'data-intel-dashboard-select':'language',options:[{value:'zh',label:'中文优先'},{value:'original',label:'来源原文'}]})}</div></div>${busy?'<p class="intel-layout-status" role="status">正在保存仪表盘选择…</p>':''}${error?`<div class="intel-layout-status" role="alert">${esc(error)} ${button(pending?'核对并重试':'重试读取',pending?'retry':'reload',{disabled:busy})}</div>`:''}`;
  }
  function panelButtons(id){const p=preferences.panels.find(x=>x.id===id),title=titles[id]||({map:'地图',latest:'资讯'})[id];return `<div class="intel-panel-controls">${p?ui.button({label:'',leadingIcon:'chevronDown',variant:'quiet',attrs:{id:'intel-collapse-'+id,'data-intel-dashboard':'collapse','data-panel':id,'aria-label':(p.collapsed?'展开':'收起')+title,'aria-expanded':!p.collapsed,disabled:busy||!ready||!!pending}}):''}${button('放大','focus',{'data-panel':id,id:'intel-focus-'+id,'aria-label':'放大'+title,disabled:false})}${p?`<details class="intel-panel-menu"><summary aria-label="${title}面板选项">${ui.icon('more')}</summary><div>${button('前移','move',{'data-panel':id,'data-delta':'-1',disabled:busy||!ready||!!pending||preferences.panels[0].id===id})}${button('后移','move',{'data-panel':id,'data-delta':'1',disabled:busy||!ready||!!pending||preferences.panels.at(-1).id===id})}${button(p.wide?'标准宽度':'加宽面板','wide',{'data-panel':id})}${button('隐藏面板','hide',{'data-panel':id})}</div></details>`:''}</div>`;}
  function title(row){return preferences.language==='zh'?(row.reading?.zh_title||row.display?.zh_title||row.title):row.title;}
  function caption(row){return preferences.language==='original'?'':row.reading?'机器译文 · 待校对':row.display?.zh_title?'来源字段整理':'';}
  document.addEventListener('click',event=>{
    if(isActive&&!isActive())return;const target=event.target.closest('[data-intel-dashboard]');if(!target||target.disabled)return;
    const action=target.dataset.intelDashboard,id=target.dataset.panel;
    if(action==='options'){optionsExpanded=!optionsExpanded;repaint();return;}
    if(action==='focus'){onFocus?.(id);return;}
    if(action==='reload'){enter();return;}if(action==='retry'){retry();return;}
    if(action==='time'){change({time:target.dataset.value});return;}
    if(action==='reset'){change(base());return;}
    const panels=copy(preferences.panels),p=panels.find(x=>x.id===id);if(!p)return;
    if(action==='collapse')p.collapsed=!p.collapsed;else if(action==='wide')p.wide=!p.wide;else if(action==='hide')p.visible=false;
    else if(action==='move'){const from=panels.indexOf(p),to=Math.max(0,Math.min(panels.length-1,from+Number(target.dataset.delta)));panels.splice(from,1);panels.splice(to,0,p);}else return;
    change({panels});
  });
  document.addEventListener('change',event=>{
    if(isActive&&!isActive())return;const t=event.target,key=t.dataset.intelDashboardSelect;
    if(key==='preset'){if(['overview','logistics','hazards'].includes(t.value))change(preset(t.value));}
    else if(key)change({[key]:key==='link_map'?t.checked:t.value});
    else if(t.dataset.intelDashboardLayer){const id=t.dataset.intelDashboardLayer;change({layers:t.checked?[...preferences.layers.filter(k=>k!==id),id]:preferences.layers.filter(k=>k!==id)});}
    else if(t.dataset.intelDashboardPanel)change({panels:preferences.panels.map(p=>p.id===t.dataset.intelDashboardPanel?{...p,visible:t.checked}:p)});
  });
  function clearDrop(){for(const el of document.querySelectorAll('.is-drop-target'))el.classList.remove('is-drop-target');}
  let pointerDrag=null;
  function cancelDrag(){const previous=pointerDrag;pointerDrag=null;clearDrop();if(previous)try{previous.handle.releasePointerCapture(previous.pointer)}catch{}}
  document.addEventListener('pointerdown',event=>{
    if(pointerDrag)cancelDrag();
    const handle=event.target.closest('[data-intel-panel-drag]');if(!handle||event.button!==0||busy||pending||!ready||isActive&&!isActive())return;
    pointerDrag={id:handle.dataset.intelPanelDrag,pointer:event.pointerId,x:event.clientX,y:event.clientY,handle,target:null,active:false};
  });
  document.addEventListener('pointermove',event=>{
    const d=pointerDrag;if(!d||event.pointerId!==d.pointer)return;
    if(event.buttons===0||d.handle.isConnected===false){cancelDrag();return;}
    if(!d.active&&Math.abs(event.clientX-d.x)+Math.abs(event.clientY-d.y)>6){d.active=true;try{d.handle.setPointerCapture(event.pointerId);}catch{}}
    if(!d.active)return;event.preventDefault();
    const panel=document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-intel-panel]');clearDrop();d.target=panel?.dataset.intelPanel;
    if(panel)panel.classList.add('is-drop-target');
  },{passive:false});
  document.addEventListener('pointerup',event=>{
    const d=pointerDrag;if(!d||event.pointerId!==d.pointer)return;pointerDrag=null;clearDrop();try{d.handle.releasePointerCapture(event.pointerId);}catch{}if(!d.active||!d.target||d.id===d.target)return;
    const panels=copy(preferences.panels),from=panels.findIndex(p=>p.id===d.id),to=panels.findIndex(p=>p.id===d.target);
    if(from<0||to<0)return;const [moving]=panels.splice(from,1);panels.splice(to,0,moving);change({panels});
  });
  document.addEventListener('pointercancel',cancelDrag);
  document.addEventListener('lostpointercapture',event=>{if(pointerDrag?.pointer===event.pointerId)cancelDrag()});
  window.addEventListener?.('blur',cancelDrag);
  document.addEventListener('keydown',event=>{
    if(pointerDrag&&event.key==='Escape'){event.preventDefault();cancelDrag();return;}
    const handle=event.target.closest?.('[data-intel-panel-drag]');if(!handle||!event.altKey||!['ArrowLeft','ArrowRight'].includes(event.key)||busy||pending||!ready)return;
    event.preventDefault();const panels=copy(preferences.panels),from=panels.findIndex(p=>p.id===handle.dataset.intelPanelDrag),to=Math.max(0,Math.min(panels.length-1,from+(event.key==='ArrowLeft'?-1:1)));
    if(from<0||from===to)return;const [moving]=panels.splice(from,1);panels.splice(to,0,moving);change({panels});
  });
  return {enter,change,retry,controls,panelButtons,title,caption,interacting:()=>!!pointerDrag,preferences:()=>copy(preferences),panels:()=>copy(preferences.panels),region:()=>copy(regions[preferences.region]||{x:0,y:0,w:720,h:360}),references:()=>copy(references.filter(r=>preferences.layers.includes(r.layer)))};
};
