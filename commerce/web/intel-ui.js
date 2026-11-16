/* Global information workspace. All base controls come from Commerce UI. */
window.CommerceIntel = ({api,esc,toast,repaint,modal,closeModal,refreshTasks,isActive,onExposure}) => {
  const ui=window.CommerceUI;
  const categories={earthquake:'地震',disaster:'灾害',trade:'贸易资讯',macro:'宏观政策',energy:'能源资讯',logistics:'交通物流'};
  const names={usgs:'USGS',gdacs:'GDACS',wto:'WTO news',fed:'美联储',ecb:'ECB',eia:'EIA',hmrc:'HMRC',transport:'DfT'};
  const defaults={query:'',source:'all',category:'all',country:'',hours:'all',scope:'latest',view:'all'};
  const panelCategories=['trade','macro','energy','logistics'];
  const state={section:window.__COMMERCE_LEGACY__?.intel_section==='social'||location.hash==='#social'?'social':'global',filters:{...defaults},draft:{...defaults},result:null,sources:[],watches:[],jobs:[],capacity:null,endurance:null,collectionAlerts:[],jobError:'',jobLoading:false,wm:null,side:'list',selected:null,articles:[],articleReviews:[],articleError:'',selectedId:null,changed:false,loading:false,itemLoading:false,refreshing:'',error:'',itemError:'',actionId:'',request:0,itemRequest:0,watchRequest:0,cursor:'',trail:[],pageSize:'20',expanded:false,mapVisible:true,box:{x:0,y:0,w:720,h:360},clusters:new Map(),cluster:null,scroll:0,resetScroll:false,watchModal:0,watchSaving:null,collectionJob:null,collectionRequest:null,readingJob:null,readingRequest:null,readingBusy:false,readingError:'',listScroll:0,returnId:null};
  Object.assign(state,{articlePlan:null,articleBatch:null,articleBatchError:'',articleBatchBusy:false,articleBatchPolling:false});
  state.panels={};state.focusPanel=null;state.reference=null;
  const globalActive=()=> (!isActive||isActive())&&state.section==='global';
  const dashboard=window.CommerceIntelDashboard({api,esc,repaint,isActive:globalActive,onFocus:focusPanel,onChange:(next,before)=>{
    if(next.region!==before.region){state.box=dashboard.region();geo?.box(state.box)}
    if(next.time!==before.time){state.filters.hours=next.time;state.draft.hours=next.time;}
    if(next.time!==before.time||next.region!==before.region||next.link_map!==before.link_map||JSON.stringify(next.layers)!==JSON.stringify(before.layers))search({reset:true,keepSelection:true});else repaint();
  }});
  const titleText=row=>dashboard.title(row);
  const titleCaption=row=>dashboard.caption(row);
  const countryText=row=>dashboard.preferences().language==='zh'?(row.display?.country_zh||row.country||'国家未提供'):(row.country||'国家未提供');
  const live=window.CommerceIntelLive?.({api,esc,repaint,isActive:()=>globalActive()&&state.mapVisible&&state.side==='list',bounds,preferences:dashboard.preferences,isBlocked:()=>dashboard.interacting?.()||suppressMapClick||!!drag,onFocus:()=>focusPanel('live'),isFocused:()=>state.focusPanel==='live',onSelect:()=>{state.cluster=null;state.reference=null;},onLocate:row=>{
    if(state.focusPanel==='live')state.focusPanel='map';
    geo?.focus(row);const p=row.location;state.box={x:Math.max(0,Math.min(480,(p.lon+180)*2-120)),y:Math.max(0,Math.min(240,(90-p.lat)*2-60)),w:240,h:120};state.cluster=null;state.reference=null;refreshMapLink();
  }});
  const geo=window.CommerceGeoMap?.({isActive:()=>globalActive()&&state.mapVisible&&state.side==='list',onPick:row=>{
    if(['flight','vessel'].includes(row.kind)){live?.select(row);return;}
    if(row.kind==='reference'){state.cluster=null;state.reference=row;repaint();return;}
    openItem(row.id);
  },onView:(range,view)=>{
    const w=Math.min(720,360/2**(view.zoom-1)*2),h=w/2;state.box={x:Math.max(0,Math.min(720-w,(view.lng+180)*2-w/2)),y:Math.max(0,Math.min(360-h,(90-view.lat)*2-h/2)),w,h};
    const key=JSON.stringify(range);if(key!==state.geoRange){state.geoRange=key;refreshMapLink();}
  }});
  function geoRows(){return [...(state.result?.markers||[]).map(row=>({...row,kind:'event',title:titleText(row)})),...dashboard.references().map(row=>({...row,kind:'reference'})),...(live?.points()||[])];}
  function liveMarkers(){const width=document.querySelector('#intel-map-svg')?.getBoundingClientRect().width||640;return live?.mapMarkers(state.box,state.box.w/Math.max(240,width))||'';}
  function bounds(){if(geo?.active())return geo.bounds();const b=state.box;return {west:b.x/2-180,east:(b.x+b.w)/2-180,north:90-b.y/2,south:90-(b.y+b.h)/2};}
  let linkTimer;
  function refreshMapLink(){clearTimeout(linkTimer);linkTimer=setTimeout(()=>{live?.read();if(dashboard.preferences().link_map)search({reset:true,keepSelection:true});},180);}
  function focusPanel(id){if(!['map','latest','live',...panelCategories].includes(id))return;state.panelScroll=document.querySelector('.main-scroll')?.scrollTop||0;state.focusPanel=id;repaint();requestAnimationFrame(()=>{const page=document.querySelector('.main-scroll');if(page)page.scrollTop=0;document.querySelector('#intel-panel-focus-title')?.focus({preventScroll:true})});}
  function closeFocus(){const id=state.focusPanel;state.focusPanel=null;repaint();requestAnimationFrame(()=>{const page=document.querySelector('.main-scroll');if(page)page.scrollTop=state.panelScroll||0;document.querySelector('#intel-focus-'+id)?.focus({preventScroll:true})});}
  const social=window.CommerceSocial({api,esc,toast,repaint,isActive:()=> (!isActive||isActive())&&state.section==='social'});
  const fmt=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'来源未提供';
  const icon=name=>ui.icon(name);
  const assistantAction=(label='AI 助手',attrs={})=>ui.button({label,leadingIcon:'spark',variant:'secondary',action:'copilot-open',attrs});
  const context=()=>state.side==='detail'&&state.selected&&!state.changed?{kind:'intel',id:state.selected.id}:null;
  const button=(label,action,attrs={},variant='secondary')=>ui.button({label,variant,attrs:{'data-intel-action':action,...attrs}});
  const choice=(label,value,active,kind='view')=>ui.button({label,variant:'quiet',attrs:{['data-intel-'+kind]:value,'aria-pressed':active,class:active?'intel-choice active':'intel-choice'}});
  const options=entries=>entries.map(([value,label])=>({value,label}));
  const select=(name,label,entries)=>ui.field(label,ui.select({id:'intel-'+name,name,value:state.draft[name],options:options(entries),'data-intel-filter':name}));
  function sourceState(source){
    const imported=source.provider==='local_verified_snapshot';
    if(source.status==='failed')return imported?'导入异常':'采集失败';
    if(!source.last_success)return imported?'尚无快照':'尚未采集';
    return Date.now()/1000-source.last_success>21600?'快照陈旧':imported?'已导入':'已采集';
  }
  const summary=filters=>[filters.query,filters.source!=='all'?names[filters.source]:'',filters.category!=='all'?categories[filters.category]:'',filters.country,filters.hours!=='all'?`近${filters.hours==='168'?'7天':filters.hours+'小时'}`:'',filters.scope==='archive'?'本机积累':'当前快照',filters.view==='bookmarked'?'收藏':filters.view==='unviewed'?'未查看':''].filter(Boolean).join(' · ');
  function failMessage(error){return ({article_body_unavailable:'来源页面尚未找到适配正文。',article_text_too_large:'正文超过6万字符完整留存上限。',article_capture_failed:'来源请求未完成，请核对回执后明确重试。',article_batch_plan_changed:'预览范围已有变化，请重新预览。',article_batch_changed:'批次进度已有变化，请先刷新。',article_batch_busy:'已有正文批次正在处理。',intel_cursor_expired:'来源记录已更新，请从第一页重新检索。',intel_record_changed:'这条来源记录已有更新，请重新载入后再核查。',intel_watch_limit:'已达到 12 个关注主题，请先移除一个。',intel_item_not_found:'这条记录已不在本机留存范围内，请重新检索。',translation_busy_try_later:'已有翻译正在处理，请稍后重试。',intel_reading_binding_mismatch:'译文与来源版本不一致，已停止展示，请重新核对。',translation_provider_failed:'翻译服务未完成请求，请检查模型连接后明确重试。',translation_failed:'翻译未完成，请明确重试。',translation_interrupted_no_automatic_retry:'翻译已中断，请明确重试。'})[error.message]||error.message||'暂时无法完成，请重试';}
  const activeJob=job=>job&&['queued','running','cancelling'].includes(job.status);
  function panel(side){state.side=side;repaint();requestAnimationFrame(()=>document.querySelector('#intel-reader-title')?.focus({preventScroll:true}));}
  function back(){state.itemRequest++;state.itemLoading=false;state.side='list';repaint();requestAnimationFrame(()=>{const page=document.querySelector('.main-scroll');if(page)page.scrollTop=state.listScroll;const target=(state.returnFocus&&document.getElementById(state.returnFocus))||document.querySelector('#intel-row-'+state.returnId)||document.querySelector('.intel-row-open')||document.querySelector('#intel-query');target?.focus({preventScroll:true})});}

  async function loadWatches(){const revision=++state.watchRequest;try{const result=await api('commerce_intel_watch_list');if(revision===state.watchRequest){state.watches=result.watches;if(state.side==='topics')repaint()}}catch(error){if(state.side==='topics'){state.error='关注主题读取失败：'+failMessage(error);repaint()}}}
  async function search({reset=false,keepSelection=false,quiet=false}={}){
    // A focus refresh must not consume the first explicit paging/filter action.
    if(quiet&&state.loading)return;
    if(reset){state.cursor='';state.trail=[];state.resetScroll=true;if(!keepSelection){state.selected=null;state.selectedId=null;state.itemRequest++}}
    const revision=++state.request;state.loading=!quiet;state.error='';if(!quiet)repaint();
    try{
      const prefs=dashboard.preferences();
      const args={...state.filters,limit:state.pageSize,cursor:state.cursor,include_map:state.mapVisible,include_panels:state.mapVisible,map_layers:prefs.layers,bounds:bounds(),link_map:prefs.link_map,...(state.result?.marker_capacity?{map_limit:5000}:{})};
      let result=await api('commerce_intel_search',args);if(revision!==state.request)return;
      if(state.mapVisible&&!args.map_limit&&result.marker_capacity)result=await api('commerce_intel_search',{...args,map_limit:5000});
      if(revision!==state.request)return;
      state.result=result;state.sources=result.sources;
      if(result.panels)state.panels=result.panels;else if(state.mapVisible)loadPanels(revision);
      const current=result.items.find(row=>row.id===state.selected?.id);
      state.changed=state.changed||(!!current&&current.record_sha256!==state.selected.record_sha256);
      return true;
    }catch(error){
      if(revision!==state.request)return;
      if(error.message==='intel_cursor_expired'&&state.cursor){toast('快照已更新，已回到第一页');return search({reset:true,keepSelection:true})}
      state.error='检索失败：'+failMessage(error);return false;
    }finally{if(revision===state.request){state.loading=false;repaint()}}
  }
  async function loadPanels(revision){
    const filters={...state.filters};state.panels={};
    await Promise.all(panelCategories.map(async category=>{
      if(filters.category!=='all'&&filters.category!==category){state.panels[category]={items:[],total:0};return;}
      try{
        const result=await api('commerce_intel_search',{...filters,category,limit:'20',cursor:'',include_map:false});
        if(revision!==state.request||!state.mapVisible)return;
        state.panels[category]=result;
      }catch(error){if(revision===state.request)state.panels[category]={error:failMessage(error)};}
    }));
    if(revision===state.request&&state.mapVisible&&state.side==='list'){
      const panels=document.querySelector('#intel-topic-panels');
      if(panels)panels.innerHTML=topicPanelContents();else repaint();
    }
  }
  function formFilters(){
    const form=document.querySelector('#intel-search');if(!form)return {...state.draft};
    const values=new FormData(form),filters={...state.filters};
    for(const key of Object.keys(defaults))if(values.has(key))filters[key]=String(values.get(key)).trim();
    return filters;
  }
  function applyFilters(patch){Object.assign(state.filters,patch);state.draft={...state.filters};state.cluster=null;state.side='list';search({reset:true});}
  async function openItem(ident,returnFocus='intel-row-'+ident){
    if(state.side==='list')state.listScroll=document.querySelector('.main-scroll')?.scrollTop||0;
    state.returnId=ident;
    state.returnFocus=returnFocus;
    const revision=++state.itemRequest;state.selectedId=ident;state.selected=null;state.articles=[];state.articleReviews=[];state.articleError='';state.side='detail';state.itemLoading=true;state.itemError='';state.changed=false;repaint();
    requestAnimationFrame(()=>{const page=document.querySelector('.main-scroll');if(page)page.scrollTop=0;document.querySelector('#intel-reader-title')?.focus({preventScroll:true})});
    try{
      let item=await api('commerce_intel_item_get',{item_id:ident});if(revision!==state.itemRequest)return;
      const originalHash=item.record_sha256;
      const reading=item.reading;
      item=await api('commerce_intel_item_update',{item_id:ident,action:'viewed',record_sha256:originalHash});
      if(reading&&item.record_sha256===originalHash)item.reading=reading;
      if(revision!==state.itemRequest)return;
      state.selected=item;state.changed=item.record_sha256!==originalHash;loadArticles();
      search({quiet:true,keepSelection:true});loadWatches();
    }catch(error){if(revision===state.itemRequest)state.itemError='记录读取失败：'+failMessage(error)}
    finally{if(revision===state.itemRequest){state.itemLoading=false;repaint()}}
  }
  async function refresh(source='all'){
    if(state.refreshing||activeJob(state.collectionJob))return;state.refreshing=source;state.jobError='';repaint();
    if(state.collectionRequest?.source!==source)state.collectionRequest={source,idempotency_key:crypto.randomUUID()};
    try{
      state.collectionJob=await api('commerce_crawler_start',{source:crawlerIds[source]||'all',idempotency_key:state.collectionRequest.idempotency_key});
      state.collectionRequest=null;
      toast('采集请求已接收，可查看进度。');
      await loadJobs();
    }catch(error){state.jobError='采集请求未确认：'+failMessage(error)+'。再次点击将查询或复用同一请求。'}
    finally{state.refreshing='';repaint()}
  }
  function collectionStatus(){const job=state.collectionJob;return `${state.jobError?ui.alert(esc(state.jobError),'danger'):''}${job?`<div class="intel-job-feedback" role="status" aria-live="polite"><strong>${esc(jobNames[job.status]||job.status)}</strong><span>${job.progress?.processed||0}/${job.progress?.total||8} 个来源处理 · ${job.progress?.successful||0} 个成功${job.status==='failed'||job.status==='interrupted'?'；旧快照保留，可明确重试。':''}</span>${activeJob(job)?button('查看进度','source-panel'):['failed','interrupted','cancelled'].includes(job.status)?button('重试采集','job-retry',{'data-job':job.id}):''}</div>`:''}`;}
  async function importSnapshot(source){
    if(state.refreshing)return;state.refreshing=source;state.error='';repaint();
    try{
      const result=await api('commerce_intel_refresh',{source});state.sources=result.sources;
      const imported=result.sources.find(s=>s.id===source);
      if(result.status==='cooldown')toast('仍在导入间隔内，已有快照保留。');
      else if(result.status==='already_refreshing')toast('已有导入正在进行，稍后可重新查询。');
      else if(imported?.status==='ok')toast('已导入已有快照；原采集时间：'+fmt(imported.last_success));
      else toast('导入未完成，旧快照保留。请在信息源中检查原因。');
      await search({reset:true,keepSelection:true,quiet:true});
    }catch(error){state.error='快照导入未确认：'+failMessage(error)}
    finally{state.refreshing='';repaint()}
  }
  const crawlerIds={usgs:'usgs',gdacs:'gdacs',fed:'federal-reserve-press',ecb:'ecb-press',eia:'eia-energy',wto:'wto-trade',hmrc:'hmrc-news',transport:'uk-transport-news'};
  const jobErrors={collection_storage_warning:'采集证据容量接近或达到保护线，请归档历史成功任务。',collection_archive_failed:'归档未通过校验，原始文件保留，请检查后重试。',collection_source_check_failed:'部分来源未通过多路核对，请查看来源状态后重试。',collection_import_failed:'采集已完成，但导入失败；可重试或导入最近快照。',worker_interrupted:'执行中断，需要明确重试。',collection_evidence_quota_reached:'本机采集存储已达到保护阈值，请整理私有运行资料后重试。',collection_runtime_unavailable:'本机爬虫运行环境不可用，请检查安装状态。',collection_worker_failed:'采集进程失败，已有快照已保留。'};
  const jobNames={queued:'排队中',running:'采集中',cancelling:'正在取消',cancelled:'已取消',succeeded:'已采集并导入',failed:'失败',interrupted:'已中断，等待明确重试'};
  function jobRows(){return `${state.endurance?`<p role="status">24小时验收：${state.endurance.formal_acceptance?'已达到验收条件':state.endurance.status==='in_progress'?`运行中 · ${(state.endurance.elapsed_seconds/3600).toFixed(1)}小时`:'尚未通过或未启动'}${state.endurance.earliest_finish_at?'<br>最早完成：'+fmt(state.endurance.earliest_finish_at):''}</p>`:''}${state.capacity?`<p role="status">采集证据：${(state.capacity.used_bytes/1000000).toFixed(1)} / ${(state.capacity.limit_bytes/1000000).toFixed(0)} MB · ${state.capacity.status==='ok'?'容量正常':state.capacity.status==='warning'?'接近保护线':'达到保护线或需检查'}</p>${button('归档历史成功任务','job-archive')}`:''}${state.collectionAlerts.filter(a=>a.status==='open').map(a=>ui.alert('采集失败或中断：'+esc(jobErrors[a.code]||'采集失败，请检查任务后重试。'),'danger')+button('确认已查看','job-alert-ack',{'data-alert':a.id})).join('')}${state.jobError?ui.alert(esc(state.jobError),'danger'):''}${state.jobs.slice(0,5).map(job=>`<section class="intel-source-state"><strong>${esc(job.source==='all'?'全部来源':names[Object.keys(crawlerIds).find(k=>crawlerIds[k]===job.source)]||job.source)} · ${esc(jobNames[job.status]||job.status)}</strong><p role="status">${job.progress.processed}/${job.progress.total} 个来源完成，${job.progress.successful} 个通过核对 · 第 ${job.attempt} 次尝试${job.status==='queued'&&job.not_before>Date.now()/1000?' · 限频等待至 '+fmt(job.not_before):''}</p>${job.error?`<p>${esc(jobErrors[job.error]||'采集失败，请检查来源后重试。')}</p>`:''}${['queued','running'].includes(job.status)?button('取消剩余采集','job-cancel',{'data-job':job.id}):['failed','cancelled','interrupted'].includes(job.status)?button('重试此任务','job-retry',{'data-job':job.id}):''}</section>`).join('')||'<p class="muted">尚无采集任务</p>'}`}
  async function loadJobs(){
    if(state.jobLoading)return;state.jobLoading=true;
    try{
      const result=await api('commerce_crawler_list');
      const changed=state.jobs.some(old=>activeJob(old)&&result.jobs.some(j=>j.id===old.id&&!activeJob(j)));
      state.jobs=result.jobs;state.capacity=result.capacity;state.endurance=result.endurance;state.collectionAlerts=result.alerts||[];
      let completed=false;
      if(state.collectionJob){
        const expected=state.collectionJob.id;
        const job=await api('commerce_crawler_get',{job_id:expected});
        if(state.collectionJob?.id!==expected)return;
        state.collectionJob=job;
        const receipt=state.collectionJob.id+':'+state.collectionJob.status;
        if(!activeJob(state.collectionJob)&&state.collectionReported!==receipt){state.collectionReported=receipt;completed=true;}
      }
      if(changed||completed){await search({reset:true,keepSelection:true,quiet:true});loadWatches();}
      else if(state.collectionJob||state.side==='sources')repaint();
    }catch(error){state.jobError='任务状态读取失败：'+failMessage(error);repaint()}finally{state.jobLoading=false}
  }
  async function jobAction(action,target){
    target.disabled=true;
    try{if(action==='collect'){await refresh(target.dataset.source||'all');return}else if(action==='job-archive'){const result=await api('commerce_crawler_archive');toast(`已归档 ${result.archived} 个历史成功任务；失败证据保留`)}else if(action==='job-alert-ack')await api('commerce_crawler_alert_ack',{alert_id:target.dataset.alert});else{const job=await api(action==='job-cancel'?'commerce_crawler_cancel':'commerce_crawler_retry',{job_id:target.dataset.job});if(state.collectionJob?.id===target.dataset.job)state.collectionJob=job;}await loadJobs();repaint()}
    catch(error){state.jobError='采集操作未确认：'+failMessage(error);toast(state.jobError);target.disabled=false}
  }
  async function loadArticles(){const item=state.selected,revision=state.itemRequest;if(!item)return;try{const value=await api('commerce_intel_article_list',{item_id:item.id});const records=value.articles[0]?(await api('commerce_intel_article_reviews',{article_id:value.articles[0].id})).records:[];if(state.selected?.id===item.id&&revision===state.itemRequest){state.articles=value.articles;state.articleReviews=records;if(!document.querySelector('.dialog'))repaint()}}catch(error){if(state.selected?.id===item.id&&revision===state.itemRequest){state.articleError=failMessage(error);repaint()}}}
  function readingStatus(){const job=state.readingJob;return `${state.readingError?ui.alert(esc(state.readingError),'danger'):''}${job?`<p class="intel-reading-status" role="status" aria-live="polite">中文标题：${esc(({queued:'排队中',running:'翻译中',completed:'已生成 · 机器译文待校对',failed:'翻译失败，可明确重试'})[job.status]||job.status)}</p>`:''}`;}
  async function startReading(){
    if(state.readingBusy||['queued','running'].includes(state.readingJob?.status))return;
    const rows=state.side==='detail'&&state.selected?[state.selected]:[...(state.mapVisible?dashboard.panels().filter(p=>p.visible&&!p.collapsed).flatMap(p=>state.panels[p.id]?.items||[]):[]),...(state.result?.items||[])];
    const records=[...new Map(rows.filter(r=>!r.reading).map(r=>[r.id,{item_id:r.id,record_sha256:r.record_sha256}])).values()].slice(0,20);
    if(!records.length){toast('当前记录已有中文标题，原文仍可对照阅读。');return;}
    const signature=JSON.stringify(records);
    if(state.readingRequest?.signature!==signature)state.readingRequest={signature,key:crypto.randomUUID()};
    state.readingBusy=true;state.readingError='';repaint();
    try{state.readingJob=await api('commerce_intel_reading_start',{input:{records},idempotency_key:state.readingRequest.key});state.readingRequest=null;await loadReading();}
    catch(error){state.readingError='中文标题请求未确认：'+failMessage(error)}
    finally{state.readingBusy=false;repaint()}
  }
  async function loadReading(){
    const ident=state.readingJob?.id;if(!ident)return;
    try{
      const job=await api('commerce_intel_reading_get',{job_id:ident});if(ident!==state.readingJob?.id)return;
      state.readingJob=job;
      if(job.status==='failed')state.readingError=failMessage({message:job.error||'translation_failed'});
      if(job.status==='completed'){
        await search({keepSelection:true,quiet:true});
        const selected=state.selected,revision=state.itemRequest;
        if(selected){const updated=await api('commerce_intel_item_get',{item_id:selected.id});if(revision===state.itemRequest&&state.selected?.id===updated.id)state.selected=updated;}
      }
      repaint();
    }catch(error){state.readingError='中文标题状态读取失败：'+failMessage(error);repaint()}
  }
  const batchActive=job=>['queued','running','cancel_requested'].includes(job?.status);
  const batchLabels={queued:'已排队',running:'采集中',cancel_requested:'等待当前单条结束',cancelled:'已取消剩余采集',interrupted:'已中断，需明确恢复',partial:'部分完成',completed:'采集已结束'};
  function articleBatchStatus(){
    const job=state.articleBatch;
    return `${state.articleBatchError?ui.alert(esc(state.articleBatchError),'warning'):''}${job?`<section class="intel-batch-status" aria-label="正文采集进度"><div><strong>正文补齐 · ${esc(batchLabels[job.status]||job.status)}</strong><span role="status">已留存 ${job.counts.captured} · 当前可用 ${job.counts.current_ready} · 失败 ${job.counts.failed} · 剩余 ${job.counts.pending}</span><div>${batchActive(job)?button('停止剩余采集','article-batch-cancel',{disabled:state.articleBatchBusy||job.status==='cancel_requested'}):['cancelled','interrupted','partial'].includes(job.status)?button(job.counts.failed?'重试失败并继续':'继续剩余采集','article-batch-resume',{disabled:state.articleBatchBusy}):''}${button('历史批次','article-batch-history',{},'quiet')}</div></div><details><summary>逐条采集回执 · ${job.records.length} 条</summary><ul>${job.records.map(r=>`<li><button type="button" class="link-btn" data-intel-id="${esc(r.item_id)}">${esc(names[r.source]||r.source)} · ${esc(r.title)}</button><span>${esc(({pending:'待采集',ready:'已留存',failed:'失败',superseded:'来源已变化'})[r.status]||r.status)}${r.source_record_changed?' · 当前来源已有更新':''}${r.error?' · '+esc(failMessage({message:r.error})):''}</span>${r.status==='failed'&&!batchActive(job)?button('重试此条','article-batch-retry-one',{'data-item':r.item_id,disabled:state.articleBatchBusy}):''}</li>`).join('')}</ul></details></section>`:''}`;
  }
  async function readArticleBatch(){
    if(state.articleBatchPolling||document.activeElement?.matches?.('input,textarea,select'))return;
    state.articleBatchPolling=true;const previous=state.articleBatch;
    try{
      const value=previous?await api('commerce_intel_article_batch_get',{batch_id:previous.id}):(await api('commerce_intel_article_batch_list')).batches[0];
      if(value){state.articleBatch=value;state.articleBatchError='';if(batchActive(previous)&&!batchActive(value)){await search({reset:true,quiet:true,keepSelection:true});loadWatches();if(state.selected)loadArticles();}if(!document.querySelector('.dialog'))repaint();}
    }catch(error){state.articleBatchError='正文进度读取未确认：'+failMessage(error);if(!document.querySelector('.dialog'))repaint();}
    finally{state.articleBatchPolling=false;}
  }
  async function articleBatchAction(action,target){
    if(state.articleBatchBusy)return;
    state.articleBatchBusy=true;state.articleBatchError='';target.disabled=true;
    try{
      if(action==='article-plan'){
        const plan=await api('commerce_intel_article_plan',{filters:{...state.filters},limit:20});state.articlePlan={...plan,idempotency_key:crypto.randomUUID()};
        modal('补齐当前范围正文',`<p>本次匹配 ${plan.coverage.matched} 条，已有当前正文 ${plan.coverage.current_ready} 条，支持但缺正文 ${plan.coverage.missing_supported} 条。</p><p>本次按来源均衡选择 ${plan.records.length} 条；未适配来源 ${plan.coverage.unsupported} 条，路径未适配 ${plan.coverage.invalid_url} 条。仅抓取发布方正文，不自动翻译。</p><ul class="intel-batch-plan">${plan.records.map(r=>`<li>${esc(names[r.source]||r.source)} · ${esc(r.title)}</li>`).join('')}</ul><p id="intel-batch-error" role="alert"></p>`,button('开始本次采集','article-batch-start',{disabled:!plan.records.length},'primary'));
      }else if(action==='article-batch-history'){
        const value=await api('commerce_intel_article_batch_list');
        modal('正文采集批次',value.batches.length?`<ul class="intel-batch-plan">${value.batches.map(job=>`<li>${button(`${names[job.filters?.source]||'全部来源'} · ${batchLabels[job.status]||job.status} · ${job.counts.current_ready}/${job.records.length} · ${fmt(job.created_at)} · ${job.id.slice(0,8)}`,'article-batch-select',{'data-batch':job.id})}</li>`).join('')}</ul>`:'<p>还没有正文采集批次。</p>','');
      }else if(action==='article-batch-select'){
        state.articleBatch=await api('commerce_intel_article_batch_get',{batch_id:target.dataset.batch});closeModal();
      }else if(action==='article-batch-start'){
        const plan=state.articlePlan;if(!plan)return;
        state.articleBatch=await api('commerce_intel_article_batch_start',{filters:plan.filters,limit:plan.limit,expected_plan_sha256:plan.sha256,idempotency_key:plan.idempotency_key});closeModal();
      }else if(state.articleBatch){
        const job=state.articleBatch;
        state.articleBatch=await api(action==='article-batch-cancel'?'commerce_intel_article_batch_cancel':'commerce_intel_article_batch_resume',{batch_id:job.id,...(action!=='article-batch-cancel'?{expected_revision:job.revision,retry_failed:true,...(target.dataset.item?{retry_item_ids:[target.dataset.item]}:{})}:{})});
      }
    }catch(error){state.articleBatchError='正文操作未确认：'+failMessage(error);const node=document.querySelector('#intel-batch-error');if(node)node.textContent=state.articleBatchError;else toast(state.articleBatchError);}
    finally{state.articleBatchBusy=false;target.disabled=false;if(!document.querySelector('.dialog'))repaint();}
  }
  function articleSection(){
    const doc=state.articles[0],article=doc?.article,translation=article?.translation;
    const supported=['fed','ecb','eia','wto','hmrc','transport'].includes(state.selected?.source);
    return `<section class="intel-side-section"><h3>正文与中文</h3><p data-ui-help>原文、译文和采集证据分别保留。正文只覆盖发布方页面，不含附件；译文需人工校对。</p>${supported?button('抓取此版本正文','article-capture',{disabled:!!doc&&['queued','running'].includes(doc.status)}):'<p>此来源尚未配置正文适配。</p>'}${state.articleError?ui.alert(esc(state.articleError),'danger'):''}${doc?`<p role="status">正文：${esc(({ready:'已双路核对',queued:'排队中',running:'采集中',failed:'抓取失败',interrupted:'已中断，可重新抓取'})[doc.status]||doc.status)}${doc.error?' · 操作未完成，可重新抓取或重试翻译':''}</p>${doc.source_record_changed?ui.alert('来源记录已有更新，以下保留旧版本证据。','warning'):''}`:''}${article?`<details><summary>查看原文 · ${article.text.length} 字符</summary><p class="intel-article-text">${esc(article.text)}</p><small>采集：${fmt(article.captured_at)}<br>原文哈希：${esc(article.content_sha256)}<br>来源：${esc(article.source_url)}</small></details>${button(doc.translation_status==='running'?'翻译中…':translation?'译文待校对':'生成中文译文','article-translate',{'data-article':doc.id,disabled:doc.translation_status==='running'||!!translation||doc.source_record_changed})}${translation?`<details open><summary>中文译文 · 待校对</summary><p class="intel-article-text">${esc(translation.zh)}</p><p>${translation.warnings?.length?'原始检查曾提示数字或单位差异，最新复查见下方追加记录。':'自动数字检查未发现差异，仍需人工校对。'}</p><small>译文哈希：${esc(translation.zh_sha256)}</small></details>${reviewSection(doc)}`:''}`:''}</section>`;
  }
  function reviewSection(doc){
    const records=state.articleReviews,latest=records.at(-1),revision=[...records].reverse().find(r=>r.kind==='revision');
    return `<section class="intel-side-section"><h3>修订与复核记录</h3><p data-ui-help>原始机器译文保留。修订另存版本，重新检查不会自动批准；复核声明仅记录本机明确操作。</p>${button('重新检查数字','article-recheck',{'data-article':doc.id})}${button('编辑中文修订','article-edit',{'data-article':doc.id})}${button('记录复核声明','article-review-open',{'data-article':doc.id})}${latest?`<p role="status">最近记录：${esc(latest.status==='approved'?'声明已核对':latest.status==='needs_changes'?'声明需修改':'待人工复核')} · ${latest.warnings.length}项自动差异</p>`:''}${revision?`<details><summary>当前中文修订</summary><p class="intel-article-text">${esc(revision.zh)}</p></details>`:''}<details><summary>${records.length}条追加记录</summary>${records.slice(-10).map(r=>`<p>${esc(r.kind)} · ${fmt(r.created_at)} · ${esc(r.note||'无备注')}<br><small>${esc(r.zh_sha256)}</small></p>`).join('')}</details></section>`;
  }
  let reviewDraft=null;
  function reviewOpen(action,target){
    const doc=state.articles.find(a=>a.id===target.dataset.article);if(!doc?.article?.translation)return;
    const revision=[...state.articleReviews].reverse().find(r=>r.kind==='revision');reviewDraft={article_id:doc.id,base_sha256:revision?.zh_sha256||doc.article.translation.zh_sha256,operation:action==='article-edit'?'revision':'review',idempotency_key:crypto.randomUUID()};
    const text=revision?.zh||doc.article.translation.zh;
    const body=action==='article-edit'?ui.field('中文修订',`<textarea id="intel-review-text" rows="12" maxlength="60000">${esc(text)}</textarea>`):ui.field('复核结果',ui.select({id:'intel-review-decision',value:'needs_changes',options:[{value:'needs_changes',label:'需要修改'},{value:'approved',label:'已逐项核对'}]}))+`<label><input type="checkbox" id="intel-review-confirm">我已对照原文和当前中文版本进行复核</label>`;
    modal(action==='article-edit'?'保存中文修订':'记录明确复核声明',body+ui.field('修订或复核说明',ui.input({id:'intel-review-note',maxlength:2000}))+`<p id="intel-review-error" role="alert"></p>`,button('保存追加记录','article-review-save',{},'primary'));
    document.querySelector(action==='article-edit'?'#intel-review-text':'#intel-review-decision')?.focus();
  }
  async function reviewSave(target){
    if(!reviewDraft)return;target.disabled=true;
    const args={...reviewDraft,note:document.querySelector('#intel-review-note').value};
    if(args.operation==='revision')args.zh=document.querySelector('#intel-review-text').value;
    else Object.assign(args,{decision:document.querySelector('#intel-review-decision').value,confirmed:document.querySelector('#intel-review-confirm').checked});
    try{await api('commerce_intel_article_record',args);closeModal();reviewDraft=null;await loadArticles();toast('追加记录已保存，原始译文保留')}catch(error){document.querySelector('#intel-review-error').textContent=failMessage(error);target.disabled=false}
  }
  async function reviewRecheck(target){const doc=state.articles.find(a=>a.id===target.dataset.article);if(!doc)return;target.disabled=true;const revision=[...state.articleReviews].reverse().find(r=>r.kind==='revision');try{await api('commerce_intel_article_record',{article_id:doc.id,operation:'recheck',idempotency_key:crypto.randomUUID(),base_sha256:revision?.zh_sha256||doc.article.translation.zh_sha256});await loadArticles()}catch(error){toast(failMessage(error));target.disabled=false}}
  async function articleAction(action,target){const item=state.selected;if(!item)return;target.disabled=true;try{if(action==='article-capture')await api('commerce_intel_article_start',{item_id:item.id,record_sha256:item.record_sha256,idempotency_key:crypto.randomUUID()});else await api('commerce_intel_article_translate',{article_id:target.dataset.article});await loadArticles()}catch(error){state.articleError=failMessage(error);toast('正文操作未确认：'+state.articleError);target.disabled=false}}
  function rememberScroll(){
    const old=document.querySelector('#intel-list-scroll');if(!state.resetScroll&&old)state.scroll=old.scrollTop;
    if(state.resetScroll){state.scroll=0;state.resetScroll=false}
    requestAnimationFrame(()=>{const list=document.querySelector('#intel-list-scroll');if(list)list.scrollTop=state.scroll;if(document.querySelector('#intel-map-svg'))setBox(state.box,{keepCluster:true})});
  }

  function activeChips(){
    const labels={query:'关键词',source:'来源',category:'类别',country:'国家',hours:'时间',scope:'范围',view:'状态'};
    return Object.entries(state.filters).filter(([key,value])=>value!==defaults[key]).map(([key,value])=>{
      const text=key==='source'?names[value]:key==='category'?categories[value]:key==='scope'?'本机积累':key==='view'?value==='bookmarked'?'已收藏':'未查看':key==='hours'?value==='168'?'近7天':'近'+value+'小时':value;
      return ui.button({label:`${labels[key]}：${text} ×`,variant:'quiet',attrs:{'data-intel-chip':key,class:'intel-chip','aria-label':`移除${labels[key]}筛选`}});
    }).join('');
  }
  const matchLabels={metadata:'标题与字段',translated_title:'中文标题',article:'原文正文',translation:'中文译文',revision:'中文修订'};
  function searchEvidence(row,expanded=false){
    const result=state.result?.items.find(item=>item.id===row.id&&item.record_sha256===row.record_sha256);
    const evidence=(row.search_match||result?.search_match)?.evidence?.filter(ref=>matchLabels[ref.kind]&&ref.record_sha256===row.record_sha256)||[];
    if(!evidence.length)return '';
    if(expanded)return `<details class="intel-search-evidence"><summary>本次检索依据 · ${evidence.length} 处</summary><p class="muted">片段来自本次检索版本；译文与来源陈述尚未独立核实。</p>${evidence.map(ref=>`<div><b>${esc(matchLabels[ref.kind])}</b><p>${esc(ref.snippet)}</p><small>内容版本：${esc(ref.text_sha256)}${ref.article_id?`<br>正文记录：${esc(ref.article_id)}`:''}${ref.revision_id?`<br>修订记录：${esc(ref.revision_id)}`:''}</small></div>`).join('')}</details>`;
    const ref=[...evidence].reverse().find(value=>value.kind!=='metadata');
    return ref?`<span class="intel-search-match"><span>${esc(matchLabels[ref.kind])}命中${['translation','translated_title'].includes(ref.kind)?' · 待核对':''}</span><span>${esc(ref.snippet)}</span></span>`:'';
  }
  function toolbar(){return `<form id="intel-search" class="intel-search-panel"><div class="intel-search-line">${ui.field('',ui.input({id:'intel-query',name:'query',type:'search',maxlength:100,value:state.draft.query,placeholder:'搜索标题、正文与中文译文','aria-label':'检索公开信息'}))}${ui.button({label:state.loading?'检索中…':'检索',variant:'primary',attrs:{type:'submit',disabled:state.loading}})}${button('筛选','filters',{'aria-expanded':state.expanded,'aria-controls':'intel-filter-fields'})}</div><div id="intel-filter-fields" class="intel-filter-fields" ${state.expanded?'':'hidden'}>${select('source','信息源',[['all','全部来源'],...Object.entries(names)])}${select('category','主题类别',[['all','全部类别'],...Object.entries(categories)])}${ui.field('来源国家字段',ui.input({id:'intel-country',name:'country',maxlength:80,value:state.draft.country,placeholder:'国家原文 / ISO3，例如 MEX','data-intel-input':'country'}))}${select('hours','来源发布时间',[['all','快照内全部'],['1','近1小时'],['6','近6小时'],['24','近24小时'],['48','近48小时'],['168','近7天']])}${select('scope','检索范围',[['latest','当前快照'],['archive','本机积累']])}</div>${activeChips()?`<div class="intel-filter-chips">${activeChips()}${button('重置','clear',{disabled:state.loading},'quiet')}</div>`:''}</form>`}
  function sourceStrip(){const failed=state.sources.filter(s=>s.status==='failed').length;return `<div class="intel-source-summary" aria-label="信息源状态">${button(`${state.sources.length} 个信息源${failed?' · '+failed+' 个异常':''}`,'source-panel',{},'quiet')}<span>${dashboard.preferences().link_map?'当前视野 · ':''}${state.filters.scope==='archive'?'本机积累':'当前快照'} · ${state.result?.total??'—'} 条${dashboard.preferences().link_map?'有坐标事件':''}${state.loading?' · 更新中':''}</span></div>`}
  function stream(){
    const rows=state.result?.items||[],stats=state.result?.stats;
    return `<section class="card intel-stream"><div class="intel-stream-header"><h2>资讯列表</h2>${dashboard.panelButtons('latest')}<span class="muted" aria-live="polite">${state.loading?'正在更新结果…':`${state.result?.total??0} 条匹配`}</span></div>
      <div class="intel-view-options" aria-label="记录状态">${choice('全部','all',state.filters.view==='all')}${choice('未查看'+(stats?` ${stats.unviewed}`:''),'unviewed',state.filters.view==='unviewed')}${choice('收藏'+(stats?` ${stats.bookmarked}`:''),'bookmarked',state.filters.view==='bookmarked')}</div>
      <div id="intel-list-scroll" class="intel-list-scroll" aria-busy="${state.loading}">${rows.length?`<ul class="intel-timeline">${rows.map(row=>`<li class="${state.selectedId===row.id?'selected':''} ${row.is_viewed?'viewed':'unviewed'}"><button type="button" id="intel-row-${row.id}" class="intel-row-open link-btn" data-intel-id="${row.id}" aria-pressed="${state.selectedId===row.id}"><span class="intel-row-meta"><b>${esc(names[row.source])}</b><span>${esc(categories[row.category])}</span>${!row.in_latest_snapshot?'<span>历史采集</span>':''}${row.is_bookmarked?'<span>已收藏</span>':''}</span><strong>${esc(titleText(row))}</strong>${titleText(row)!==row.title?`<span class="intel-original-title">${esc(row.title)}</span><span class="intel-translation-label">${esc(titleCaption(row))}</span>`:''}${searchEvidence(row)}<small>${esc(countryText(row))} · ${fmt(row.published)}</small><span class="intel-row-status">${row.is_viewed?'已查看':'未查看'}<span>阅读详情 ›</span></span></button></li>`).join('')}</ul>`:`<div class="intel-empty"><h3>${state.loading?'正在检索本机记录…':'这个范围还没有记录'}</h3><p>可调整筛选，或采集最新来源。</p>${button('清空条件','clear')}${button('采集最新来源','refresh',{disabled:!!state.refreshing||!!activeJob(state.collectionJob)})}</div>`}</div>
      <div class="intel-pagination">${button('上一页','previous',{disabled:!state.trail.length||state.loading})}<span>${state.result?.total?`${(state.result.offset||0)+1}–${(state.result.offset||0)+rows.length} / ${state.result.total}`:'0 条'} · 第 ${state.trail.length+1} 页</span>${button('下一页','next',{disabled:!state.result?.next_cursor||state.loading})}</div></section>`;
  }
  function clusters(){
    const width=document.querySelector('#intel-map-svg')?.getBoundingClientRect().width||640;const pixel=state.box.w/Math.max(240,width),groups=new Map(),cell=42*pixel;
    for(const item of state.result?.markers||[]){const x=(item.location.lon+180)*2,y=(90-item.location.lat)*2;const key=Math.floor(x/cell)+'-'+Math.floor(y/cell);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item)}
    state.clusters=groups;
    return [...groups].map(([key,items])=>{
      const x=items.reduce((a,i)=>a+(i.location.lon+180)*2,0)/items.length,y=items.reduce((a,i)=>a+(90-i.location.lat)*2,0)/items.length;
      const selected=items.some(i=>i.id===state.selectedId),r=(items.length>1?10:selected?6:4)*pixel;
      const fill=items.length>1?'var(--ui-color-brand)':items[0].source==='usgs'?'var(--ui-color-signal-earthquake)':'var(--ui-color-signal-disaster)';
      return `<g role="button" tabindex="0" id="intel-map-${items.length===1?items[0].id:key}" ${items.length===1?`data-intel-id="${items[0].id}"`:`data-intel-cluster="${key}"`} aria-label="${esc(items.length===1?titleText(items[0]):`邻近点位 ${items.length} 条记录`)}"><circle cx="${x}" cy="${y}" r="${22*pixel}" fill="transparent"/><circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${selected?'var(--ui-color-text)':'var(--ui-color-map-border)'}" stroke-width="${(selected?2:1.2)*pixel}"/>${items.length>1?`<text x="${x}" y="${y}" dy=".34em" text-anchor="middle" fill="var(--ui-color-on-brand)" font-size="${10*pixel}" font-weight="700">${items.length}</text>`:''}<title>${esc(items.length===1?titleText(items[0]):'邻近点位，点击选择具体记录')}</title></g>`;
    }).join('');
  }
  function clusterPopup(){if(live?.hasSelection())return live.popup();if(state.reference){const ref=state.reference;return `<div class="intel-cluster-popup"><div><strong>${esc(ref.title)}</strong>${button('关闭','cluster-close',{'aria-label':'关闭地理参考'},'quiet')}</div><p>近似地理位置参考。没有实时船舶、拥堵或关闭观测，当前运行状态未知。</p><a href="${esc(ref.source_url)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">查看参考来源 ↗</a></div>`;}const rows=state.clusters.get(state.cluster)||[];return rows.length>1?`<div class="intel-cluster-popup"><div><strong>邻近点位 · ${rows.length} 条记录</strong>${button('关闭','cluster-close',{'aria-label':'关闭邻近点位列表'},'quiet')}</div>${rows.slice(0,20).map(row=>ui.button({label:titleText(row),variant:'quiet',attrs:{'data-intel-id':row.id}})).join('')}${rows.length>20?'<p class="muted">其余记录可放大地图后选择，或使用关键词检索。</p>':''}</div>`:''}
  function observationLegend(key){
    const s=live?.source(key),name=key==='flights'?'▲ 航空器':'船舶';
    if(s?.status==='requires_config')return name+' · 待配置';
    if(!dashboard.preferences().layers.includes(key))return name+' · 图层未开启';
    if(s?.availability==='expired')return name+' · 样本已过期';
    if(s?.status==='failed')return name+' · 来源读取失败';
    if(s?.availability==='outside_filter')return name+' · 视野内无匹配';
    if(!s?.matched)return name+' · 尚无有效位置';
    return name+(s.mode==='local_evaluation'?'开发测试':'')+' '+s.items.length+(s.truncated?'/'+s.matched+' · 上限600':' 条');
  }
  function map(){
    return `<section class="card intel-map"><div class="intel-map-head"><h2>全球事件分布</h2>${dashboard.panelButtons('map')}<div class="intel-map-controls">${button('+','zoom-in',{'aria-label':'放大地图'})}${button('−','zoom-out',{'aria-label':'缩小地图'})}${button('复位','map-reset')}<span id="intel-map-zoom">${geo?.active()?geo.zoomPercent():Math.round(720/state.box.w*100)}%</span></div></div><div class="intel-map-canvas"><svg id="intel-map-svg" viewBox="${state.box.x} ${state.box.y} ${state.box.w} ${state.box.h}" tabindex="0" aria-label="公开信息事件地图，可拖动平移，使用加减按钮缩放"><rect x="-720" y="-360" width="2160" height="1080" fill="var(--ui-color-map-ocean)"/>${[60,120,180,240,300].map(y=>`<path d="M0 ${y}H720" stroke="var(--ui-color-map-grid)"/>`).join('')}${[120,240,360,480,600].map(x=>`<path d="M${x} 0V360" stroke="var(--ui-color-map-grid)"/>`).join('')}<path d="__INTEL_WORLD_PATH__" fill="var(--ui-color-map-land)" stroke="var(--ui-color-map-border)" stroke-width=".35"/><g id="intel-map-markers">${clusters()}${referenceMarkers()}${liveMarkers()}</g></svg><div id="intel-cluster-popup">${clusterPopup()}</div></div><div class="intel-map-legend"><span><i class="disaster"></i>GDACS 灾害</span><span><i class="quake"></i>USGS 地震</span><span>◇ 地理参考</span><span>${esc(observationLegend('flights'))}</span><span>${esc(observationLegend('vessels'))}</span><span>${state.result?.markers.length||0}/${state.result?.map_stats?.matched??state.result?.stats.geolocated??0} 条事件坐标 · 上限${state.result?.marker_limit||250}</span></div><small class="muted">底图 Natural Earth · 数字为邻近记录数量 · 点位不代表经营影响</small></section>`;
  }
  function topicPanels(){return `<div id="intel-topic-panels" class="intel-topic-panels">${topicPanelContents()}</div>`;}
  function topicPanel(category){
    const result=state.panels[category],config=dashboard.panels().find(p=>p.id===category),collapsed=config?.collapsed&&state.focusPanel!==category;
    const sourceIds=new Set((result?.items||[]).map(r=>r.source)),sources=state.sources.filter(s=>sourceIds.has(s.id));
    const stamps=sources.map(s=>s.last_success).filter(Boolean),failed=sources.some(s=>s.status==='failed'),stale=sources.some(s=>s.freshness==='stale');
    const status=failed?'来源异常 · 保留快照':stale?'快照陈旧':stamps.length?'采集于 '+fmt(Math.min(...stamps)):'尚无来源快照';
    return `<section class="card intel-topic-panel ${collapsed?'is-collapsed':''} ${config?.wide?'is-wide':''}" data-intel-panel="${category}" aria-label="${categories[category]}面板"><header><h2 draggable="false" tabindex="0" id="intel-panel-drag-${category}" data-intel-panel-drag="${category}" title="拖动标题或使用Alt+左右方向键调整顺序">${categories[category]}</h2><span>${result?.total===undefined?'—':result.total+' 条'}</span>${dashboard.panelButtons(category)}</header>${collapsed?'':`${result?.error?`<p role="alert">读取失败：${esc(result.error)}</p>${button('重试','search')}`:!result?'<p class="muted">读取快照…</p>':!result.items.length?'<p class="muted">当前筛选范围暂无记录</p>':`<ul>${result.items.slice(0,3).map(row=>`<li><button type="button" id="intel-panel-row-${row.id}" data-intel-id="${row.id}"><span>${esc(names[row.source])} · ${fmt(row.published)}</span><strong>${esc(titleText(row))}</strong>${titleCaption(row)?`<small>${esc(titleCaption(row))}</small>`:''}</button></li>`).join('')}</ul>`}<footer><small>${esc(status)}</small>${button('查看全部','category',{'data-category':category,'aria-label':'查看全部'+categories[category]},'quiet')}</footer>`}</section>`;
  }
  function topicPanelContents(){return dashboard.panels().filter(p=>p.visible).map(p=>topicPanel(p.id)).join('')||'<p class="muted">主题面板已隐藏，可从“面板配置”恢复。</p>';}
  function referenceMarkers(){
    const width=document.querySelector('#intel-map-svg')?.getBoundingClientRect().width||640,pixel=state.box.w/Math.max(240,width);
    return dashboard.references().map(ref=>{const x=(ref.location.lon+180)*2,y=(90-ref.location.lat)*2,r=5*pixel;return `<g role="button" tabindex="0" id="intel-${ref.id}" data-intel-reference="${ref.id}" aria-label="${esc(ref.title)}，地理参考，运行状态未知"><circle cx="${x}" cy="${y}" r="${18*pixel}" fill="transparent"/><path d="M${x} ${y-r}l${r} ${r}l${-r} ${r}l${-r} ${-r}Z" fill="var(--ui-color-map-ocean)" stroke="var(--ui-color-muted)" stroke-width="${1.5*pixel}"/><title>${esc(ref.title)} · 地理参考</title></g>`}).join('');
  }
  function sourceHealth(){return `<div class="intel-source-health" aria-label="来源采集状态">${state.sources.map(source=>button(`${names[source.id]||source.name} · ${sourceState(source)}`,'source-panel',{'data-source':source.id,class:'intel-health-source','aria-label':`${names[source.id]||source.name}：${sourceState(source)}，查看采集状态`},'quiet')).join('')}</div>`;}
  function auxiliaryActions(){const open=state.auxOpen??((document.documentElement?.clientWidth||1000)>600);return `<details id="intel-aux-menu" class="intel-aux-menu" ${open?'open':''}><summary aria-label="更多情报操作">${icon('more')}</summary><div>${button('关注检索','watch-open',{id:'intel-watch-open'},'quiet')}${button('关注主题','topics-panel',{},'quiet')}${button('正文批次','article-batch-history',{},'quiet')}${ui.button({label:'社交观察',variant:'quiet',attrs:{'data-intel-section':'social'}})}</div></details>`;}
  function globalView(){
    rememberScroll();
    if(state.side!=='list')return `<section class="intel-root intel-reader" aria-labelledby="intel-reader-title"><header class="intel-reader-header">${button(state.focusPanel?'返回面板':state.mapVisible?'返回仪表盘':'返回列表','reader-back')}<h2 id="intel-reader-title" tabindex="-1">${({detail:'来源详情',sources:'信息源与采集',topics:'关注主题'})[state.side]}</h2></header>${state.side==='detail'?detail():state.side==='sources'?sources():topics()}</section>`;
    if(state.focusPanel){const id=state.focusPanel;return `<section class="intel-root intel-focused-view"><header class="intel-reader-header">${button(state.mapVisible?'返回仪表盘':'返回列表','focus-back')}<h2 id="intel-panel-focus-title" tabindex="-1">${({map:'全球事件分布',latest:'资讯列表',live:'实时监测',...categories})[id]}</h2>${assistantAction()}</header>${id==='map'?dashboard.controls(state.result,state.sources,live?.source)+map():id==='latest'?stream():id==='live'?live.panel():topicPanel(id)}</section>`;}
    const translateBusy=state.readingBusy||['queued','running'].includes(state.readingJob?.status);
    return `<div class="intel-root ${state.mapVisible?'intel-dashboard':'intel-list-view'}"><header class="intel-header"><div><div class="intel-display-switch" role="group" aria-label="情报布局">${button('仪表盘','dashboard-view',{'aria-pressed':state.mapVisible},state.mapVisible?'primary':'quiet')}${button('资讯列表','list-view',{'aria-pressed':!state.mapVisible},state.mapVisible?'quiet':'primary')}</div>${assistantAction()}${auxiliaryActions()}</div><div>${button('补齐正文','article-plan',{disabled:state.articleBatchBusy||batchActive(state.articleBatch)})}${button(translateBusy?'中文标题处理中…':'补全中文标题','reading-start',{disabled:translateBusy||!state.result?.items.length})}${button(state.refreshing?'正在提交…':activeJob(state.collectionJob)?'采集中…':'采集最新来源','refresh',{disabled:!!state.refreshing||!!activeJob(state.collectionJob)},'primary')}</div></header>
      ${toolbar()}${state.mapVisible?dashboard.controls(state.result,state.sources,live?.source):''}${collectionStatus()}${readingStatus()}${!state.mapVisible||batchActive(state.articleBatch)?articleBatchStatus():''}${state.error?ui.alert(state.error,'danger')+button('重试检索','search'):''}
      <div class="intel-results-head">${sourceStrip()}</div>
      ${state.mapVisible?live?.ribbon()||'':''}
      <div class="intel-workspace ${state.mapVisible?'with-map':'list-only'}">${state.mapVisible?map():''}${state.mapVisible&&live?live.panel():stream()}</div>
      ${state.mapVisible?`<div class="intel-news-grid">${stream()}${topicPanels()}</div>`+sourceHealth()+(!batchActive(state.articleBatch)?articleBatchStatus():''):''}
      <p class="intel-scope-note" data-ui-help>本机留存 ${state.result?.archive.archived??'—'} 条。${state.result?.search_coverage?`本次范围 ${state.result.search_coverage.records_with_body}/${state.result.search_coverage.eligible_records} 条已有正文。`:''}检索已采集的标题、正文与现有中文；缺少正文的记录只查标题与字段。来源陈述尚未独立核实。</p></div>`;
  }

  function detail(){
    if(state.itemLoading)return '<div class="intel-detail-empty" role="status">正在载入来源记录…</div>';
    if(state.itemError&&!state.selected)return ui.alert(esc(state.itemError),'danger')+button('重试读取','item-retry');
    const item=state.selected;if(!item)return '<p>未选中记录，请返回列表。</p>';
    const busy=state.actionId===item.id,reading=item.reading;
    const titleBusy=state.readingBusy||['queued','running'].includes(state.readingJob?.status);
    return `<article class="intel-record" aria-label="来源详情">
      ${state.itemError?ui.alert(esc(state.itemError),'danger'):''}${state.changed?ui.alert('来源记录有新内容，请重新载入后核查。')+button('载入最新内容','item-retry'):''}
      <div class="intel-record-tags">${ui.badge(names[item.source],'blue')}${ui.badge(categories[item.category],'gray')}${ui.badge(item.in_latest_snapshot?'当前快照':'历史采集','gray')}</div>
      <h3>${esc(titleText(item))}</h3>
      ${titleCaption(item)?`<p class="intel-translation-label">${esc(titleCaption(item))}</p>`:''}${titleText(item)!==item.title?`<details><summary>原文标题</summary><p>${esc(item.title)}</p></details>`:''}
      <p class="intel-record-meta">${fmt(item.published)} · ${esc(countryText(item))}</p>
      <div class="intel-record-actions">${assistantAction('与 AI 讨论',{disabled:state.changed})}${button(item.is_bookmarked?'取消收藏':'收藏记录','bookmark',{disabled:busy})}${!reading?button(titleBusy?'中文标题处理中…':'生成中文标题','reading-start',{disabled:titleBusy}):''}${button('查看经营关联','exposure',{disabled:state.changed||!onExposure})}</div>
      ${searchEvidence(item,true)}${readingStatus()}${articleSection()}
      <section class="intel-side-section"><h3>经营关联与核查</h3><p>选择已有商品工作项与明确的国家、仓库或路线范围，查看关联线索。实际影响仍需核查。</p>
        ${item.review_task?`<p>核查任务：${esc(({queued:'已排队',running:'处理中',completed:'已返回结果',cancelled:'已取消',awaiting_input:'等待补充',failed:'失败',interrupted:'已中断'})[item.review_task.status]||item.review_task.status)}</p>${ui.button({label:'查看共享核查任务',attrs:{'data-tab':'tasks'}})}`:button('创建影响核查任务','review',{disabled:busy||state.changed,'data-intel-task':item.id})}
      </section>
      <details class="intel-evidence"><summary>原始来源与采集证据 · ${item.revision_count} 个留存版本</summary>
        <dl><dt>来源发布时间</dt><dd>${fmt(item.published)}</dd><dt>本机采集时间</dt><dd>${fmt(item.collected_at)}</dd><dt>来源国家</dt><dd>${esc(item.country||'来源未提供')}${item.country_code?' · '+esc(item.country_code):''}</dd><dt>原始预警</dt><dd>${esc(item.publisher_alert||'来源未提供')}</dd></dl>
        <p><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">打开原始来源 ↗</a></p>
        <label class="intel-url-label">原始链接${ui.input({id:'intel-source-link',value:item.url,readonly:true,'aria-label':'原始来源链接'})}</label>
        <div class="intel-record-actions">${button('复制链接','copy')}${button('导出证据','export')}${item.location?button('地图定位','locate'):''}</div>
        <p class="intel-hash">内容 SHA-256<br>${esc(item.record_sha256)}</p><p class="intel-hash">来源响应 SHA-256<br>${esc(item.source_payload_sha256)}</p>
        <ul>${item.revisions.map(r=>`<li><time>${fmt(r.observed_at)}</time><span>${esc(r.title)}</span></li>`).join('')}</ul><p>哈希检查内容一致性，不证明真实性。这里只列最近5个留存版本。</p>
      </details>
      ${item.is_viewed?button('标为未查看','unviewed',{},'quiet'):''}<p class="intel-fact-note">来源陈述尚未独立核实，已查看与收藏仅用于整理记录。</p>
    </article>`;
  }
  function sources(){return `<div class="intel-sources-panel"><section class="intel-side-section"><h3>多路采集任务</h3><p data-ui-help>六个feed经多路核对，USGS/GDACS保留原生单路采集；完成后导入本机。取消保留已完成的来源；重启后中断的任务需要明确重试。</p>${button('采集全部来源','collect')}<div id="intel-collection-jobs">${jobRows()}</div></section><p class="muted" data-ui-help>分开记录最近尝试与最近成功。采集成功不代表事件刚发生。</p>${state.sources.map(source=>{const wait=Math.max(0,Math.ceil(90-(Date.now()/1000-(source.last_attempt||0))));return `<section class="intel-source-state" id="intel-source-${source.id}"><div><strong>${esc(source.name)}</strong>${ui.badge(sourceState(source),source.status==='ok'&&sourceState(source)==='已采集'?'blue':'gray')}</div><p>${esc(source.coverage)}</p><small>${source.provider==='local_verified_snapshot'?'原始采集':'最近成功'}：${fmt(source.last_success)}<br>${source.provider==='local_verified_snapshot'?'最近导入尝试':'最近尝试'}：${fmt(source.last_attempt)}<br>当前快照：${source.cached_items} 条</small>${source.error?ui.alert(({source_format_changed:'来源格式变化，旧快照已保留。',crawler_snapshot_missing:'本机尚无可导入的多路采集快照。',crawler_snapshot_invalid:'本机采集快照未通过完整性检查，旧数据已保留。',crawler_latest_attempt_failed_using_previous:'最近采集未通过核对，当前仍为上次成功数据。'}[source.error]||'来源暂不可用，旧快照已保留。'),'danger'):''}${crawlerIds[source.id]?button('采集并更新','collect',{'data-source':source.id}):''}${source.provider==='local_verified_snapshot'?button(wait?`${wait} 秒后可导入`:'导入已有快照','refresh-one',{'data-source':source.id,disabled:!!state.refreshing||wait>0}):''}</section>`}).join('')}<section class="intel-side-section"><h3>World Monitor</h3><p data-ui-help>仅公开工具表发现已预留。认证新闻、金融和航运数据尚未连接。</p>${state.wm?.discovery?`<p class="muted">本轮发现 ${state.wm.discovery.tool_count} 个官方工具；未调用认证数据。</p>`:''}${button('检查官方接口','discover')}</section><p class="muted" data-ui-help>可手动更新；8个固定来源的后台计划在“设备与任务”设置。每源至少间隔90秒。</p></div>`}
  function topics(){return `<div class="intel-topics"><p class="muted" data-ui-help>保存检索条件并查看匹配数量，最多12项。当前未启用自动采集或消息推送。</p>${button('关注当前检索','watch-open')}${state.watches.length?state.watches.map(watch=>`<section class="intel-watch"><button type="button" data-intel-watch="${watch.id}"><strong>${esc(watch.name)}</strong><span>${watch.matches} 条匹配 · ${watch.unviewed} 未查看</span><small>${esc(summary(watch.filters))}</small></button>${button('移除','watch-remove',{'data-watch':watch.id,'aria-label':'移除关注主题 '+watch.name},'quiet')}</section>`).join(''):'<div class="empty small">还没有关注主题。先检索，再保存条件。</div>'}</div>`}
  function globalAside(){return '';}

  function setBox(next,{keepCluster=false}={}){
    const w=Math.max(120,Math.min(720,next.w)),h=w/2;state.box={w,h,x:Math.max(0,Math.min(720-w,next.x)),y:Math.max(0,Math.min(360-h,next.y))};
    const map=document.querySelector('#intel-map-svg');if(map)map.setAttribute('viewBox',`${state.box.x} ${state.box.y} ${w} ${h}`);
    const markers=document.querySelector('#intel-map-markers');if(markers)markers.innerHTML=clusters()+referenceMarkers()+liveMarkers();
    const zoom=document.querySelector('#intel-map-zoom');if(zoom)zoom.textContent=Math.round(720/w*100)+'%';
    if(!keepCluster){state.cluster=null;state.reference=null;}const popup=document.querySelector('#intel-cluster-popup');if(popup)popup.innerHTML=clusterPopup();
  }
  function zoom(factor){if(geo?.active()){geo.zoomBy(factor);return;}const old=state.box,w=old.w/factor;setBox({w,x:old.x+(old.w-w)/2,y:old.y+(old.h-w/2)/2});refreshMapLink()}
  function watchOpen(){
    const pending=formFilters();
    if(JSON.stringify(pending)!==JSON.stringify(state.filters))applyFilters(pending);
    const revision=++state.watchModal;state.watchFilters={...pending};
    modal('关注当前检索',`${ui.field('主题名称',ui.input({id:'intel-watch-name',maxlength:60,value:(pending.query||pending.country||'全球公开信息').slice(0,60)}))}<p class="muted">${esc(summary(pending))}</p><p>保存的是检索条件，当前不会启用自动采集或通知。</p><p id="intel-watch-error" role="alert"></p>`,button('保存关注','watch-save',{id:'intel-watch-save'},'primary'));
    document.querySelector('#intel-watch-name')?.focus();return revision;
  }
  async function watchSave(){
    const revision=state.watchModal;if(state.watchSaving===revision)return;state.watchSaving=revision;
    const control=document.querySelector('#intel-watch-save');if(control)control.disabled=true;
    try{await api('commerce_intel_watch_save',{name:document.querySelector('#intel-watch-name')?.value||'',...state.watchFilters});if(revision===state.watchModal)closeModal();await loadWatches();toast('关注主题已保存');}
    catch(error){if(revision===state.watchModal){const output=document.querySelector('#intel-watch-error');if(output)output.textContent='保存未确认：'+failMessage(error)}}
    finally{if(state.watchSaving===revision)state.watchSaving=null;if(revision===state.watchModal){const current=document.querySelector('#intel-watch-save');if(current)current.disabled=false}repaint()}
  }
  async function itemAction(action){
    const item=state.selected;if(!item||state.actionId)return;state.actionId=item.id;state.itemError='';repaint();
    try{
      if(action==='review'){
        const task=await api('commerce_intel_review_create',{item_id:item.id,record_sha256:item.record_sha256});
        if(state.selected?.id===item.id)state.selected=await api('commerce_intel_item_get',{item_id:item.id});
        await refreshTasks?.();toast(task.status==='queued'?'已创建或复用共享核查任务 '+task.id.slice(0,8):'同版本已有任务，当前状态为已取消');
      }else{
        const updated=await api('commerce_intel_item_update',{item_id:item.id,action:action==='bookmark'?(item.is_bookmarked?'unbookmark':'bookmark'):'unviewed'});
        if(state.selected?.id===item.id)state.selected=updated;
        await search({quiet:true,keepSelection:true});loadWatches();
      }
    }catch(error){state.itemError='操作回执未确认：'+failMessage(error)}
    finally{state.actionId='';repaint()}
  }
  async function navigate(direction){
    if(state.loading)return;const before={cursor:state.cursor,trail:[...state.trail]};
    if(direction==='next'&&state.result?.next_cursor){state.trail.push(state.cursor);state.cursor=state.result.next_cursor}
    else if(direction==='previous'&&state.trail.length)state.cursor=state.trail.pop();else return;
    state.resetScroll=true;const ok=await search({keepSelection:true});
    if(ok===false){state.cursor=before.cursor;state.trail=before.trail;repaint()}
  }
  function exportItem(){
    const item=state.selected;if(!item)return;const excluded=['is_viewed','is_bookmarked','saved_at','review_task'];
    const payload={schema:'commerce-intel-evidence-v1',exported_at:new Date().toISOString(),verification:'publisher_report_not_independently_verified',store_impact:'not_assessed',record:Object.fromEntries(Object.entries(item).filter(([key])=>!excluded.includes(key)))};
    const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download='intel-'+item.id+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
  }
  document.addEventListener('input',event=>{if(event.target.id==='intel-query')state.draft.query=event.target.value;else if(event.target.id==='intel-country')state.draft.country=event.target.value});
  document.addEventListener('change',event=>{const key=event.target.dataset.intelFilter;if(key==='hours')dashboard.change({time:event.target.value});else if(key)applyFilters(formFilters())});
  document.addEventListener('submit',event=>{if(event.target.id==='intel-search'){event.preventDefault();applyFilters(formFilters())}});
  let suppressMapClick=false,drag=null;
  document.addEventListener('click',async event=>{
    const target=event.target.closest('[data-intel-action],[data-intel-id],[data-intel-cluster],[data-intel-view],[data-intel-chip],[data-intel-watch],[data-intel-reference]');if(!target)return;
    if(suppressMapClick&&event.isTrusted&&target.closest('#intel-map-svg')){suppressMapClick=false;return}
    if(target.dataset.intelReference){live?.dismiss();state.reference=dashboard.references().find(r=>r.id===target.dataset.intelReference);state.cluster=null;const popup=document.querySelector('#intel-cluster-popup');if(popup)popup.innerHTML=clusterPopup();return;}
    if(target.dataset.intelId){state.cluster=null;state.reference=null;openItem(target.dataset.intelId,target.id||undefined);return}
    if(target.dataset.intelCluster){live?.dismiss();state.cluster=target.dataset.intelCluster;state.reference=null;const popup=document.querySelector('#intel-cluster-popup');if(popup)popup.innerHTML=clusterPopup();return}
    if(target.dataset.intelView){applyFilters({view:target.dataset.intelView,...(target.dataset.intelView==='bookmarked'?{scope:'archive'}:{})});return}
    if(target.dataset.intelChip){if(target.dataset.intelChip==='hours')dashboard.change({time:'all'});else applyFilters({[target.dataset.intelChip]:defaults[target.dataset.intelChip]});return}
    if(target.dataset.intelWatch){const watch=state.watches.find(w=>w.id===target.dataset.intelWatch);if(watch)applyFilters(watch.filters);return}
    const action=target.dataset.intelAction;
    if(action==='article-plan'||action?.startsWith('article-batch-'))articleBatchAction(action,target);
    else if(action==='reader-back')back();
    else if(action==='focus-back')closeFocus();
    else if(action==='reading-start')startReading();
    else if(action==='exposure'&&state.selected&&onExposure){try{await onExposure({item_id:state.selected.id,record_sha256:state.selected.record_sha256})}catch(error){state.itemError='经营关联未能打开：'+failMessage(error);repaint()}}
    else if(action==='filters'){state.expanded=!state.expanded;repaint()}
    else if(action==='clear'){applyFilters({...defaults});dashboard.change({time:'all'});}
    else if(action==='search')search({keepSelection:true});
    else if(action==='refresh')refresh();
    else if(action==='refresh-one')importSnapshot(target.dataset.source);
    else if(action==='side'){state.side=target.dataset.side;repaint();if(state.side==='topics')loadWatches();if(state.side==='sources')loadJobs()}
    else if(action==='article-recheck')reviewRecheck(target);
    else if(action==='article-edit'||action==='article-review-open')reviewOpen(action,target);
    else if(action==='article-review-save')reviewSave(target);
    else if(action==='article-capture'||action==='article-translate')articleAction(action,target);
    else if(action==='collect'||action==='job-cancel'||action==='job-retry'||action==='job-alert-ack'||action==='job-archive')jobAction(action,target);
    else if(action==='source-panel'){if(state.side==='list')state.listScroll=document.querySelector('.main-scroll')?.scrollTop||0;panel('sources');loadJobs();if(target.dataset.source)document.querySelector('#intel-source-'+target.dataset.source)?.scrollIntoView({block:'nearest'})}
    else if(action==='topics-panel'){if(state.side==='list')state.listScroll=document.querySelector('.main-scroll')?.scrollTop||0;panel('topics');loadWatches()}
    else if(action==='next')navigate('next');
    else if(action==='previous')navigate('previous');
    else if(action==='category'&&categories[target.dataset.category]){state.focusPanel=null;state.mapVisible=false;applyFilters({category:target.dataset.category});}
    else if(['map-toggle','dashboard-view','list-view'].includes(action)){state.mapVisible=action==='map-toggle'?!state.mapVisible:action==='dashboard-view';search({keepSelection:true});repaint()}
    else if(action==='zoom-in')zoom(1.6);
    else if(action==='zoom-out')zoom(1/1.6);
    else if(action==='map-reset'){geo?.reset();setBox({x:0,y:0,w:720});refreshMapLink();}
    else if(action==='locate'&&state.selected?.location){state.side='list';state.mapVisible=true;state.focusPanel='map';geo?.focus(state.selected);const p=state.selected.location;state.box={x:Math.max(0,Math.min(480,(p.lon+180)*2-120)),y:Math.max(0,Math.min(240,(90-p.lat)*2-60)),w:240,h:120};search({keepSelection:true});repaint();requestAnimationFrame(()=>document.querySelector('#intel-map-svg')?.focus())}
    else if(action==='cluster-close'){state.cluster=null;state.reference=null;const popup=document.querySelector('#intel-cluster-popup');if(popup)popup.innerHTML=''}
    else if(action==='item-retry'&&state.selectedId)openItem(state.selectedId);
    else if(action==='bookmark'||action==='unviewed'||action==='review')itemAction(action);
    else if(action==='watch-open'){target.focus();watchOpen()}
    else if(action==='watch-save')watchSave();
    else if(action==='watch-remove'){target.disabled=true;try{await api('commerce_intel_watch_remove',{watch_id:target.dataset.watch});await loadWatches();repaint()}catch(error){toast('移除未确认：'+failMessage(error));target.disabled=false}}
    else if(action==='discover'){target.disabled=true;try{state.wm=await api('commerce_worldmonitor_status',{discover:true});toast('工具表检查完成；认证数据未启用');repaint()}catch(error){toast('接口检查失败：'+failMessage(error));target.disabled=false}}
    else if(action==='export')exportItem();
    else if(action==='copy'&&state.selected){try{await navigator.clipboard.writeText(state.selected.url);toast('来源链接已复制')}catch{const input=document.querySelector('#intel-source-link');input?.focus();input?.select();toast(document.execCommand('copy')?'来源链接已复制':'链接已选中，可使用系统复制')}}
  });
  function finishMapDrag(){
    const previous=drag;drag=null;if(!previous)return;
    // Clear the lock before release: lostpointercapture can fire synchronously.
    if(previous.captured)try{previous.map.releasePointerCapture(previous.id)}catch{}
    if(previous.moved){setBox(state.box);refreshMapLink();}
    setTimeout(()=>{if(!drag)suppressMapClick=false},0);
  }
  document.addEventListener('pointerdown',event=>{
    if(drag)finishMapDrag();suppressMapClick=false;
    const map=event.target.closest('#intel-map-svg');if(!map||state.box.w===720||event.button!==0)return;
    const width=map.getBoundingClientRect().width;if(!Number.isFinite(width)||width<=0)return;
    drag={id:event.pointerId,x:event.clientX,y:event.clientY,box:{...state.box},width,map,captured:false,captureAttempted:false,moved:false};
  });
  document.addEventListener('pointermove',event=>{
    if(!drag||event.pointerId!==drag.id)return;
    if(event.buttons===0||drag.map.isConnected===false){finishMapDrag();return;}
    const dx=event.clientX-drag.x,dy=event.clientY-drag.y;
    if(Math.abs(dx)+Math.abs(dy)>4){
      drag.moved=true;suppressMapClick=true;
      if(!drag.captureAttempted){drag.captureAttempted=true;try{drag.map.setPointerCapture(event.pointerId);drag.captured=true}catch{}}
    }
    if(!drag.moved)return;
    const ratio=drag.box.w/drag.width,box={...drag.box,x:Math.max(0,Math.min(720-drag.box.w,drag.box.x-dx*ratio)),y:Math.max(0,Math.min(360-drag.box.h,drag.box.y-dy*ratio))};
    state.box=box;drag.map.setAttribute('viewBox',`${box.x} ${box.y} ${box.w} ${box.h}`);
  });
  for(const name of ['pointerup','pointercancel','lostpointercapture'])document.addEventListener(name,event=>{if(drag?.id===event.pointerId)finishMapDrag()});
  window.addEventListener('blur',finishMapDrag);
  document.addEventListener('wheel',event=>{if(event.target.closest('#intel-map-svg')&&(event.ctrlKey||event.metaKey)){event.preventDefault();zoom(event.deltaY<0?1.15:1/1.15)}},{passive:false});
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&drag){event.preventDefault();finishMapDrag();return;}
    if(event.key==='Escape'&&globalActive()&&state.side==='list'&&live?.hasSelection()&&!document.querySelector('.dialog')){event.preventDefault();live.clear();return;}
    if(event.key==='Escape'&&globalActive()&&state.side==='list'&&(state.reference||state.cluster)&&!document.querySelector('.dialog')){event.preventDefault();const origin=state.reference?'intel-'+state.reference.id:'intel-map-'+state.cluster;state.reference=null;state.cluster=null;const popup=document.querySelector('#intel-cluster-popup');if(popup)popup.innerHTML='';(document.getElementById(origin)||document.querySelector('#intel-map-svg'))?.focus({preventScroll:true});return;}
    if(event.key==='Escape'&&globalActive()&&state.focusPanel&&state.side==='list'&&!document.querySelector('.dialog')){event.preventDefault();closeFocus();return;}
    if(event.key==='Escape'&&globalActive()&&state.side!=='list'&&!document.querySelector('.dialog')){event.preventDefault();back();return;}
    if(event.key==='Enter'&&event.target.id==='intel-watch-name'){event.preventDefault();watchSave();return}
    if((event.key==='Enter'||event.key===' ')&&event.target.matches('g[data-intel-id],g[data-intel-cluster],g[data-intel-reference]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));return}
    if(event.target.id==='intel-map-svg'){
      const key=event.key;if(['+','=','-','Home','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(key))event.preventDefault();
      if(key==='+'||key==='=')zoom(1.6);else if(key==='-')zoom(1/1.6);else if(key==='Home')setBox({x:0,y:0,w:720});
      else if(key.startsWith('Arrow'))setBox({...state.box,x:state.box.x+(key==='ArrowLeft'?-1:key==='ArrowRight'?1:0)*state.box.w/12,y:state.box.y+(key==='ArrowUp'?-1:key==='ArrowDown'?1:0)*state.box.h/12});
      if(['Home','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(key))refreshMapLink();
    }
  });
  document.addEventListener('toggle',event=>{if(event.target.id==='intel-aux-menu')state.auxOpen=event.target.open},true);
  let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{const aux=document.querySelector('#intel-aux-menu');if(aux){const compact=(document.documentElement?.clientWidth||1000)<=600;if(compact!==state.auxCompact){state.auxCompact=compact;state.auxOpen=!compact;aux.open=!compact;}}if(globalActive()&&document.querySelector('#intel-map-svg'))setBox(state.box)},100)});
  window.addEventListener('focus',()=>{if(globalActive()&&!document.querySelector('.dialog')){search({quiet:true,keepSelection:true});loadWatches()}});
  setInterval(()=>{if(!globalActive()||state.side!=='sources')return;for(const button of document.querySelectorAll('[data-intel-action="refresh-one"]')){const source=state.sources.find(s=>s.id===button.dataset.source);if(!source)continue;const wait=Math.max(0,Math.ceil(90-(Date.now()/1000-(source.last_attempt||0))));button.disabled=!!state.refreshing||wait>0;button.textContent=wait?wait+' 秒后可导入':'导入已有快照'}},1000);
  setInterval(async()=>{if(!globalActive()||drag||document.hidden||document.querySelector('.dialog'))return;if(batchActive(state.articleBatch))await readArticleBatch();if(state.side==='sources'||activeJob(state.collectionJob))await loadJobs();if(['queued','running'].includes(state.readingJob?.status))await loadReading();if(state.side==='detail'&&state.articles.some(a=>['queued','running'].includes(a.status)||a.translation_status==='running'))await loadArticles()},3000);
  function sectionTabs(){return `<div class="intel-section-tabs" aria-label="信息阅读视图">${['global','social'].map((key,i)=>ui.button({label:['全球公开信息','社交观察'][i],variant:state.section===key?'primary':'secondary',attrs:{'data-intel-section':key,'aria-pressed':state.section===key}})).join('')}</div>`}
  function view(){return state.section==='social'?sectionTabs()+social.view():globalView()}
  function aside(){return state.section==='social'?social.aside():globalAside()}
  document.addEventListener('click',event=>{const b=event.target.closest('[data-intel-section]');if(!b||!['global','social'].includes(b.dataset.intelSection))return;state.section=b.dataset.intelSection;repaint();enter()});
  async function enter(){if(state.section==='social')return social.enter();readArticleBatch();loadJobs();await dashboard.enter();const prefs=dashboard.preferences();state.filters.hours=prefs.time;state.draft.hours=prefs.time;if(!state.result){state.box=dashboard.region();if(prefs.region!=='global')geo?.box(state.box);}live?.enter();search({keepSelection:true});loadWatches();try{state.wm=await api('commerce_worldmonitor_status');if(state.side==='sources')repaint()}catch{}}
  if(location.hash==='#social'){
    const jump=()=>{const tab=document.querySelector('[data-tab="intelligence"]');if(!tab)return false;tab.click();return true};
    const observer=new MutationObserver(()=>{if(document.querySelector('[data-tab="intelligence"]')){observer.disconnect();jump()}});
    observer.observe(document.querySelector('#app')||document.body,{childList:true,subtree:true});
  }
  return {view,aside,enter,context,beforePaint:()=>geo?.beforePaint(),afterPaint:()=>geo?.mount(document.querySelector('.intel-map-canvas'),geoRows(),live?.selection()?.id||state.selectedId||state.reference?.id)};
};
