/* Global information workspace. All base controls come from Commerce UI. */
window.CommerceIntel = ({api,esc,toast,repaint,modal,closeModal,refreshTasks,isActive}) => {
  const ui=window.CommerceUI;
  const categories={earthquake:'地震',disaster:'灾害',trade:'贸易资讯',macro:'宏观政策',energy:'能源资讯',logistics:'交通物流'};
  const names={usgs:'USGS',gdacs:'GDACS',wto:'WTO news',fed:'美联储',ecb:'ECB',eia:'EIA',hmrc:'HMRC',transport:'DfT'};
  const defaults={query:'',source:'all',category:'all',country:'',hours:'all',scope:'latest',view:'all'};
  const state={filters:{...defaults},draft:{...defaults},result:null,sources:[],watches:[],jobs:[],collectionAlerts:[],jobError:'',jobLoading:false,wm:null,side:'detail',selected:null,articles:[],articleError:'',selectedId:null,changed:false,loading:false,itemLoading:false,refreshing:'',error:'',itemError:'',actionId:'',request:0,itemRequest:0,watchRequest:0,cursor:'',trail:[],pageSize:'20',expanded:false,mapVisible:true,box:{x:0,y:0,w:720,h:360},clusters:new Map(),cluster:null,scroll:0,resetScroll:false,watchModal:0,watchSaving:null};
  const fmt=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'来源未提供';
  const icon=name=>ui.icon(name);
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
  const summary=filters=>[filters.query,filters.source!=='all'?names[filters.source]:'',filters.category!=='all'?categories[filters.category]:'',filters.country,filters.hours!=='all'?`近${filters.hours==='24'?'24小时':'7天'}`:'',filters.scope==='archive'?'本机积累':'当前快照',filters.view==='bookmarked'?'收藏':filters.view==='unviewed'?'未查看':''].filter(Boolean).join(' · ');
  function failMessage(error){return ({intel_cursor_expired:'来源记录已更新，请从第一页重新检索。',intel_record_changed:'这条来源记录已有更新，请重新载入后再核查。',intel_watch_limit:'已达到 12 个关注主题，请先移除一个。',intel_item_not_found:'这条记录已不在本机留存范围内，请重新检索。'})[error.message]||error.message||'暂时无法完成，请重试';}

  async function loadWatches(){const revision=++state.watchRequest;try{const result=await api('commerce_intel_watch_list');if(revision===state.watchRequest){state.watches=result.watches;if(state.side==='topics')repaint()}}catch(error){if(state.side==='topics'){state.error='关注主题读取失败：'+failMessage(error);repaint()}}}
  async function search({reset=false,keepSelection=false,quiet=false}={}){
    if(reset){state.cursor='';state.trail=[];state.resetScroll=true;if(!keepSelection){state.selected=null;state.selectedId=null;state.itemRequest++}}
    const revision=++state.request;state.loading=true;state.error='';if(!quiet)repaint();
    try{
      const result=await api('commerce_intel_search',{...state.filters,limit:state.pageSize,cursor:state.cursor,include_map:state.mapVisible});
      if(revision!==state.request)return;
      state.result=result;state.sources=result.sources;
      const current=result.items.find(row=>row.id===state.selected?.id);
      state.changed=state.changed||(!!current&&current.record_sha256!==state.selected.record_sha256);
      return true;
    }catch(error){
      if(revision!==state.request)return;
      if(error.message==='intel_cursor_expired'&&state.cursor){toast('快照已更新，已回到第一页');return search({reset:true,keepSelection:true})}
      state.error='检索失败：'+failMessage(error);return false;
    }finally{if(revision===state.request){state.loading=false;repaint()}}
  }
  function formFilters(){
    const form=document.querySelector('#intel-search');if(!form)return {...state.draft};
    const values=new FormData(form),filters={...state.filters};
    for(const key of Object.keys(defaults))if(values.has(key))filters[key]=String(values.get(key)).trim();
    return filters;
  }
  function applyFilters(patch){Object.assign(state.filters,patch);state.draft={...state.filters};state.cluster=null;search({reset:true});}
  async function openItem(ident){
    const revision=++state.itemRequest;state.selectedId=ident;state.selected=null;state.articles=[];state.articleError='';state.side='detail';state.itemLoading=true;state.itemError='';state.changed=false;repaint();
    try{
      let item=await api('commerce_intel_item_get',{item_id:ident});if(revision!==state.itemRequest)return;
      const originalHash=item.record_sha256;
      item=await api('commerce_intel_item_update',{item_id:ident,action:'viewed',record_sha256:originalHash});
      if(revision!==state.itemRequest)return;
      state.selected=item;state.changed=item.record_sha256!==originalHash;loadArticles();
      search({quiet:true,keepSelection:true});loadWatches();
    }catch(error){if(revision===state.itemRequest)state.itemError='记录读取失败：'+failMessage(error)}
    finally{if(revision===state.itemRequest){state.itemLoading=false;repaint()}}
  }
  async function refresh(source='all'){
    if(state.refreshing)return;state.refreshing=source;state.error='';repaint();
    try{
      const result=await api('commerce_intel_refresh',{source});state.sources=result.sources;
      if(result.status==='cooldown')toast('仍在采集间隔内，保留当前快照');
      else if(result.status==='already_refreshing')toast('已有采集正在进行，稍后重新检索即可');
      else{const attempted=result.attempted||[];const good=result.sources.filter(s=>attempted.includes(s.id)&&s.status==='ok').length;toast(`${good}/${attempted.length} 个来源已更新，请核对采集或导入状态`)}
      await search({reset:true,keepSelection:true});loadWatches();
    }catch(error){state.error='采集回执未确认：'+failMessage(error)}
    finally{state.refreshing='';repaint()}
  }
  const crawlerIds={fed:'federal-reserve-press',ecb:'ecb-press',eia:'eia-energy',wto:'wto-trade',hmrc:'hmrc-news',transport:'uk-transport-news'};
  const jobErrors={collection_source_check_failed:'部分来源未通过多路核对，请查看来源状态后重试。',collection_import_failed:'采集已完成，但导入失败；可重试或导入最近快照。',worker_interrupted:'执行中断，需要明确重试。',collection_evidence_quota_reached:'本机采集存储已达到保护阈值，请整理私有运行资料后重试。',collection_runtime_unavailable:'本机爬虫运行环境不可用，请检查安装状态。',collection_worker_failed:'采集进程失败，已有快照已保留。'};
  const jobNames={queued:'排队中',running:'采集中',cancelling:'正在取消',cancelled:'已取消',succeeded:'已采集并导入',failed:'失败',interrupted:'已中断，等待明确重试'};
  function jobRows(){return `${state.collectionAlerts.filter(a=>a.status==='open').map(a=>ui.alert('采集失败或中断：'+esc(jobErrors[a.code]||'采集失败，请检查任务后重试。'),'danger')+button('确认已查看','job-alert-ack',{'data-alert':a.id})).join('')}${state.jobError?ui.alert(esc(state.jobError),'danger'):''}${state.jobs.slice(0,5).map(job=>`<section class="intel-source-state"><strong>${esc(job.source==='all'?'全部多路来源':names[Object.keys(crawlerIds).find(k=>crawlerIds[k]===job.source)]||job.source)} · ${esc(jobNames[job.status]||job.status)}</strong><p role="status">${job.progress.processed}/${job.progress.total} 个来源完成，${job.progress.successful} 个通过核对 · 第 ${job.attempt} 次尝试${job.status==='queued'&&job.not_before>Date.now()/1000?' · 限频等待至 '+fmt(job.not_before):''}</p>${job.error?`<p>${esc(jobErrors[job.error]||'采集失败，请检查来源后重试。')}</p>`:''}${['queued','running'].includes(job.status)?button('取消剩余采集','job-cancel',{'data-job':job.id}):['failed','cancelled','interrupted'].includes(job.status)?button('重试此任务','job-retry',{'data-job':job.id}):''}</section>`).join('')||'<p class="muted">尚无采集任务</p>'}`}
  async function loadJobs(){
    if(state.jobLoading)return;state.jobLoading=true;
    try{const result=await api('commerce_crawler_list');const changed=state.jobs.some(old=>['queued','running','cancelling'].includes(old.status)&&result.jobs.some(j=>j.id===old.id&&!['queued','running','cancelling'].includes(j.status)));state.jobs=result.jobs;state.collectionAlerts=result.alerts||[];state.jobError='';const panel=document.querySelector('#intel-collection-jobs');if(panel&&!panel.contains(document.activeElement))panel.innerHTML=jobRows();if(changed)await search({reset:true,keepSelection:true,quiet:true})}
    catch(error){state.jobError='任务状态读取失败：'+failMessage(error)}finally{state.jobLoading=false}
  }
  async function jobAction(action,target){
    target.disabled=true;
    try{if(action==='collect')await api('commerce_crawler_start',{source:crawlerIds[target.dataset.source]||'all',idempotency_key:crypto.randomUUID()});else if(action==='job-alert-ack')await api('commerce_crawler_alert_ack',{alert_id:target.dataset.alert});else await api(action==='job-cancel'?'commerce_crawler_cancel':'commerce_crawler_retry',{job_id:target.dataset.job});await loadJobs();repaint()}
    catch(error){state.jobError='采集操作未确认：'+failMessage(error);toast(state.jobError);target.disabled=false}
  }
  async function loadArticles(){const item=state.selected;if(!item)return;try{const value=await api('commerce_intel_article_list',{item_id:item.id});if(state.selected?.id===item.id){state.articles=value.articles;if(!document.querySelector('.dialog'))repaint()}}catch(error){state.articleError=failMessage(error)}}
  function articleSection(){
    const doc=state.articles[0],article=doc?.article,translation=article?.translation;
    const supported=['fed','ecb','eia','wto','hmrc','transport'].includes(state.selected?.source);
    return `<section class="intel-side-section"><h3>正文与中文</h3><p>原文、译文和采集证据分别保留。正文只覆盖发布方页面，不含附件；译文需人工校对。</p>${supported?button('抓取此版本正文','article-capture',{disabled:!!doc&&['queued','running'].includes(doc.status)}):'<p>此来源尚未配置正文适配。</p>'}${state.articleError?ui.alert(esc(state.articleError),'danger'):''}${doc?`<p role="status">正文：${esc(({ready:'已双路核对',queued:'排队中',running:'采集中',failed:'抓取失败',interrupted:'已中断，可重新抓取'})[doc.status]||doc.status)}${doc.error?' · 操作未完成，可重新抓取或重试翻译':''}</p>${doc.source_record_changed?ui.alert('来源记录已有更新，以下保留旧版本证据。','warning'):''}`:''}${article?`<details><summary>查看原文 · ${article.text.length} 字符</summary><p class="intel-article-text">${esc(article.text)}</p><small>采集：${fmt(article.captured_at)}<br>原文哈希：${esc(article.content_sha256)}<br>来源：${esc(article.source_url)}</small></details>${button(doc.translation_status==='running'?'翻译中…':translation?'译文待校对':'生成中文译文','article-translate',{'data-article':doc.id,disabled:doc.translation_status==='running'||!!translation||doc.source_record_changed})}${translation?`<details open><summary>中文译文 · 待校对</summary><p class="intel-article-text">${esc(translation.zh)}</p><p>${translation.warnings?.length?'存在数字或单位差异，请逐项核对。':'自动数字检查未发现差异，仍需人工校对。'}</p><small>译文哈希：${esc(translation.zh_sha256)}</small></details>`:''}`:''}</section>`;
  }
  async function articleAction(action,target){const item=state.selected;if(!item)return;target.disabled=true;try{if(action==='article-capture')await api('commerce_intel_article_start',{item_id:item.id,record_sha256:item.record_sha256,idempotency_key:crypto.randomUUID()});else await api('commerce_intel_article_translate',{article_id:target.dataset.article});await loadArticles()}catch(error){state.articleError=failMessage(error);toast('正文操作未确认：'+state.articleError);target.disabled=false}}
  function rememberScroll(){
    const old=document.querySelector('#intel-list-scroll');if(!state.resetScroll&&old)state.scroll=old.scrollTop;
    if(state.resetScroll){state.scroll=0;state.resetScroll=false}
    requestAnimationFrame(()=>{const list=document.querySelector('#intel-list-scroll');if(list)list.scrollTop=state.scroll;if(document.querySelector('#intel-map-svg'))setBox(state.box,{keepCluster:true})});
  }

  function activeChips(){
    const labels={query:'关键词',source:'来源',category:'类别',country:'国家',hours:'时间',scope:'范围',view:'状态'};
    return Object.entries(state.filters).filter(([key,value])=>value!==defaults[key]).map(([key,value])=>{
      const text=key==='source'?names[value]:key==='category'?categories[value]:key==='scope'?'本机积累':key==='view'?value==='bookmarked'?'已收藏':'未查看':key==='hours'?value==='24'?'近24小时':'近7天':value;
      return ui.button({label:`${labels[key]}：${text} ×`,variant:'quiet',attrs:{'data-intel-chip':key,class:'intel-chip','aria-label':`移除${labels[key]}筛选`}});
    }).join('');
  }
  function toolbar(){return `<form id="intel-search" class="card intel-search-panel"><div class="intel-search-line">${ui.field('检索公开信息',ui.input({id:'intel-query',name:'query',type:'search',maxlength:100,value:state.draft.query,placeholder:'例如：墨西哥洪水、地震、trade tariff','aria-label':'检索公开信息'}))}${ui.button({label:state.loading?'检索中…':'检索',variant:'primary',attrs:{type:'submit',disabled:state.loading}})}${button('筛选','filters',{'aria-expanded':state.expanded,'aria-controls':'intel-filter-fields'})}${button('重置','clear',{disabled:state.loading})}</div><div id="intel-filter-fields" class="intel-filter-fields" ${state.expanded?'':'hidden'}>${select('source','信息源',[['all','全部来源'],...Object.entries(names)])}${select('category','主题类别',[['all','全部类别'],...Object.entries(categories)])}${ui.field('来源明确提供的国家',ui.input({id:'intel-country',name:'country',maxlength:80,value:state.draft.country,placeholder:'国家原文 / ISO3，例如 MEX','data-intel-input':'country'}))}${select('hours','来源发布时间',[['all','快照内全部'],['24','近24小时'],['168','近7天']])}${select('scope','检索范围',[['latest','当前快照'],['archive','本机积累']])}</div><div class="intel-filter-chips">${activeChips()||'<span class="muted">当前检索全部公开源快照。国家缺失时保持未知。</span>'}</div></form>`}
  function sourceStrip(){return `<div class="intel-source-strip" aria-label="信息源状态">${state.sources.map(source=>button(`${names[source.id]} · ${sourceState(source)}`,'source-panel',{'data-source':source.id,class:'intel-source-pill '+(source.status==='failed'?'failed':'')})).join('')}<span class="muted">${state.result?.archive.archived??'—'} 条本机留存 · 采集计划见设备与任务</span></div>`}
  function stream(){
    const rows=state.result?.items||[],stats=state.result?.stats;
    return `<section class="card intel-stream"><div class="intel-stream-header"><h2>信息时间线</h2><span class="muted" aria-live="polite">${state.loading?'正在更新结果…':`${state.result?.total??0} 条匹配`}</span></div><div class="intel-view-options" aria-label="记录状态">${choice('全部','all',state.filters.view==='all')}${choice('未查看'+(stats?` ${stats.unviewed}`:''),'unviewed',state.filters.view==='unviewed')}${choice('收藏'+(stats?` ${stats.bookmarked}`:''),'bookmarked',state.filters.view==='bookmarked')}</div><div id="intel-list-scroll" class="intel-list-scroll" aria-busy="${state.loading}">${rows.length?`<ul class="intel-timeline">${rows.map(row=>`<li class="${state.selectedId===row.id?'selected':''} ${row.is_viewed?'viewed':'unviewed'}"><button type="button" id="intel-row-${row.id}" class="intel-row-open link-btn" data-intel-id="${row.id}" aria-pressed="${state.selectedId===row.id}"><span class="intel-row-meta"><b>${esc(names[row.source])}</b><span>${esc(categories[row.category])}</span>${!row.in_latest_snapshot?'<span>历史采集</span>':''}${row.is_bookmarked?'<span>已收藏</span>':''}</span><strong>${esc(row.title)}</strong><small>${esc(row.country||'国家未提供')} · ${fmt(row.published)}</small><span class="intel-row-status">${row.is_viewed?'已查看':'未查看'}<span>查看来源 ›</span></span></button></li>`).join('')}</ul>`:`<div class="intel-empty"><div>${icon('book')}</div><h3>${state.loading?'正在检索本机记录…':'这个范围还没有记录'}</h3><p>可调整筛选或刷新公开源。没有记录不表示风险为零。</p>${button('清空条件','clear')}${button('采集公开来源','refresh',{disabled:!!state.refreshing})}</div>`}</div><div class="intel-pagination">${button('上一页','previous',{disabled:!state.trail.length||state.loading})}<span>${state.result?.total?`${(state.result.offset||0)+1}–${(state.result.offset||0)+rows.length} / ${state.result.total}`:'0 条'}<br><small>第 ${state.trail.length+1} 页</small></span>${button('下一页','next',{disabled:!state.result?.next_cursor||state.loading})}</div><p class="intel-stream-note">按来源发布时间排序 · 已查看仅指打开过本机详情。</p></section>`;
  }
  function clusters(){
    const width=document.querySelector('#intel-map-svg')?.getBoundingClientRect().width||640;const pixel=state.box.w/Math.max(240,width),groups=new Map(),cell=42*pixel;
    for(const item of state.result?.markers||[]){const x=(item.location.lon+180)*2,y=(90-item.location.lat)*2;const key=Math.floor(x/cell)+'-'+Math.floor(y/cell);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item)}
    state.clusters=groups;
    return [...groups].map(([key,items])=>{
      const x=items.reduce((a,i)=>a+(i.location.lon+180)*2,0)/items.length,y=items.reduce((a,i)=>a+(90-i.location.lat)*2,0)/items.length;
      const selected=items.some(i=>i.id===state.selectedId),r=(items.length>1?10:selected?6:4)*pixel;
      const fill=items.length>1?'var(--ui-color-brand)':items[0].source==='usgs'?'var(--ui-color-signal-earthquake)':'var(--ui-color-signal-disaster)';
      return `<g role="button" tabindex="0" id="intel-map-${items.length===1?items[0].id:key}" ${items.length===1?`data-intel-id="${items[0].id}"`:`data-intel-cluster="${key}"`} aria-label="${esc(items.length===1?items[0].title:`邻近点位 ${items.length} 条记录`)}"><circle cx="${x}" cy="${y}" r="${22*pixel}" fill="transparent"/><circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${selected?'var(--ui-color-text)':'var(--ui-color-map-border)'}" stroke-width="${(selected?2:1.2)*pixel}"/>${items.length>1?`<text x="${x}" y="${y}" dy=".34em" text-anchor="middle" fill="var(--ui-color-on-brand)" font-size="${10*pixel}" font-weight="700">${items.length}</text>`:''}<title>${esc(items.length===1?items[0].title:'邻近点位，点击选择具体记录')}</title></g>`;
    }).join('');
  }
  function clusterPopup(){const rows=state.clusters.get(state.cluster)||[];return rows.length>1?`<div class="intel-cluster-popup"><div><strong>邻近点位 · ${rows.length} 条记录</strong>${button('关闭','cluster-close',{'aria-label':'关闭邻近点位列表'},'quiet')}</div>${rows.slice(0,20).map(row=>ui.button({label:row.title,variant:'quiet',attrs:{'data-intel-id':row.id}})).join('')}${rows.length>20?'<p class="muted">其余记录可放大地图后选择，或使用关键词检索。</p>':''}</div>`:''}
  function map(){
    return `<section class="card intel-map"><div class="intel-map-head"><h2>全球事件分布</h2><div class="intel-map-controls">${button('+','zoom-in',{'aria-label':'放大地图'})}${button('−','zoom-out',{'aria-label':'缩小地图'})}${button('复位','map-reset')}<span id="intel-map-zoom">${Math.round(720/state.box.w*100)}%</span></div></div><div class="intel-map-canvas"><svg id="intel-map-svg" viewBox="${state.box.x} ${state.box.y} ${state.box.w} ${state.box.h}" tabindex="0" aria-label="公开信息事件地图，可拖动平移，使用加减按钮缩放"><rect x="-720" y="-360" width="2160" height="1080" fill="var(--ui-color-map-ocean)"/>${[60,120,180,240,300].map(y=>`<path d="M0 ${y}H720" stroke="var(--ui-color-map-grid)"/>`).join('')}${[120,240,360,480,600].map(x=>`<path d="M${x} 0V360" stroke="var(--ui-color-map-grid)"/>`).join('')}<path d="__INTEL_WORLD_PATH__" fill="var(--ui-color-map-land)" stroke="var(--ui-color-map-border)" stroke-width=".35"/><g id="intel-map-markers">${clusters()}</g></svg><div id="intel-cluster-popup">${clusterPopup()}</div></div><div class="intel-map-legend"><span><i class="disaster"></i>GDACS</span><span><i class="quake"></i>USGS</span><span>数字为邻近点位数量</span></div><p class="muted">拖动平移 · +/− 缩放 · 点击点位查看详情<br>显示 ${state.result?.markers.length||0}/${state.result?.stats.geolocated||0} 条有坐标记录，最多250条。无坐标资讯仍列入时间线。</p><small class="muted">底图 Natural Earth · 点位不代表店铺或路线已受影响。</small></section>`;
  }
  function view(){
    rememberScroll();const stats=state.result?.stats;
    return `<div class="intel-root"><header class="intel-header"><div><span class="intel-eyebrow">GLOBAL INTELLIGENCE</span><h2>公开信号，形成可核查的线索</h2><p>检索、收藏与证据共用同一个后台。</p></div><div>${button('关注当前检索','watch-open',{id:'intel-watch-open'})}${button(state.refreshing?'采集中…':'刷新来源','refresh',{disabled:!!state.refreshing},'primary')}</div></header>${toolbar()}${sourceStrip()}${state.error?ui.alert(state.error,'danger')+button('重试检索','search'):''}<div class="intel-results-head"><div><strong>${state.result?.total??'—'}</strong> 条匹配<span>${stats?.unviewed??'—'} 未查看 · ${stats?.bookmarked??'—'} 已收藏</span></div><div>${button(state.mapVisible?'隐藏地图':'显示地图','map-toggle',{'aria-pressed':state.mapVisible})}<span class="muted">${state.filters.scope==='latest'?'当前快照':'本机积累'}</span></div></div><div class="intel-workspace ${state.mapVisible?'with-map':'list-only'}">${state.mapVisible?map():''}${stream()}</div><p class="intel-scope-note">本机积累只包含实际采集过的标题和元数据，并非全网历史全文检索。可按所选记录抓取正文并生成待校对中文；来源陈述尚未独立核实。</p></div>`;
  }

  function detail(){
    if(state.itemLoading)return '<div class="intel-detail-empty" role="status">正在载入来源记录…</div>';
    if(state.itemError&&!state.selected)return ui.alert(state.itemError,'danger')+button('重试读取','item-retry');
    const item=state.selected;
    if(!item)return `<div class="intel-detail-empty">${icon('doc')}<h3>选择一条信息</h3><p>点击时间线或地图点位，在这里查看原始来源、采集凭据和核查任务。</p><div>${ui.badge('来源可追溯','gray')}${ui.badge('影响待核查','gray')}</div></div><section class="intel-side-section"><h3>当前可用</h3><p>三类公开源 · 本机历史留存<br>收藏与未查看 · 关注检索条件<br>版本绑定的共享核查任务</p>${button('查看信息源','source-panel')}${button('管理关注主题','topics-panel')}</section>`;
    const busy=state.actionId===item.id;
    return `<article class="intel-record" aria-label="来源详情">${state.itemError?ui.alert(state.itemError,'danger'):''}${state.changed?ui.alert('来源记录有新内容，请重新载入后核查。')+button('载入最新内容','item-retry'):''}<div class="intel-record-tags">${ui.badge(names[item.source],'blue')}${ui.badge(categories[item.category],'gray')}${ui.badge(item.in_latest_snapshot?'当前快照':'历史采集','gray')}</div><h3>${esc(item.title)}</h3><div class="intel-record-tags">${ui.badge(item.is_viewed?'已查看':'未查看','gray')}${item.is_bookmarked?ui.badge('已收藏','blue'):''}</div><dl><dt>来源发布时间</dt><dd>${fmt(item.published)}</dd><dt>本机采集时间</dt><dd>${fmt(item.collected_at)}</dd><dt>来源国家</dt><dd>${esc(item.country||'来源未提供')}${item.country_code?' · '+esc(item.country_code):''}</dd><dt>原始预警</dt><dd>${esc(item.publisher_alert||'来源未提供')}</dd></dl><div class="intel-record-actions">${button(item.is_bookmarked?'取消收藏':'收藏记录','bookmark',{disabled:busy},item.is_bookmarked?'secondary':'primary')}${item.location?button('地图定位','locate'):''}${button('导出证据','export',{disabled:busy})}</div><p><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">查看原始来源 ↗</a></p><label class="intel-url-label">原始链接（可选择复制）${ui.input({id:'intel-source-link',value:item.url,readonly:true,'aria-label':'原始来源链接'})}</label>${button('复制链接','copy',{},'quiet')}<section class="intel-review"><h3>店铺与履约影响</h3><p>尚未关联销售国家、仓库或运输路线。请先核实来源，再创建核查任务。</p>${item.review_task?`<p>${ui.badge(item.review_task.status==='queued'?'核查已排队':'核查任务已取消','gray')}</p>${ui.button({label:'查看共享核查任务',attrs:{'data-tab':'tasks'}})}`:button('创建影响核查任务','review',{disabled:busy,'data-intel-task':item.id},'primary')}<small>创建任务不表示已执行店铺操作。</small></section><details class="intel-evidence"><summary>采集与内容凭据 · ${item.revision_count} 个留存版本</summary><dl><dt>首次留存</dt><dd>${fmt(item.first_seen)}</dd><dt>最近留存</dt><dd>${fmt(item.last_seen)}</dd></dl><p class="intel-hash">内容 SHA-256<br>${esc(item.record_sha256)}</p><p class="intel-hash">${item.collection_provenance?.length?'本机采集快照 SHA-256':'来源响应 SHA-256'}<br>${esc(item.source_payload_sha256)}</p><ul>${item.revisions.map(r=>`<li><time>${fmt(r.observed_at)}</time><span>${esc(r.title)}</span></li>`).join('')}</ul><p>哈希检查内容一致性，不证明真实性。这里只列最近5个留存版本。</p></details>${item.is_viewed?button('标为未查看','unviewed',{},'quiet'):''}${articleSection()}<p class="intel-fact-note">来源陈述尚未独立核实，已查看与收藏仅用于整理记录。</p></article>`;
  }
  function sources(){return `<div class="intel-sources-panel"><section class="intel-side-section"><h3>多路采集任务</h3><p>抓取固定公开来源，核对后导入本机。取消保留已完成的来源；重启后中断的任务需要明确重试。</p>${button('采集全部多路来源','collect')}<div id="intel-collection-jobs">${jobRows()}</div></section><p class="muted">分开记录最近尝试与最近成功。采集成功不代表事件刚发生。</p>${state.sources.map(source=>{const wait=Math.max(0,Math.ceil(90-(Date.now()/1000-(source.last_attempt||0))));return `<section class="intel-source-state" id="intel-source-${source.id}"><div><strong>${esc(source.name)}</strong>${ui.badge(sourceState(source),source.status==='ok'&&sourceState(source)==='已采集'?'blue':'gray')}</div><p>${esc(source.coverage)}</p><small>${source.provider==='local_verified_snapshot'?'原始采集':'最近成功'}：${fmt(source.last_success)}<br>${source.provider==='local_verified_snapshot'?'最近导入尝试':'最近尝试'}：${fmt(source.last_attempt)}<br>当前快照：${source.cached_items} 条</small>${source.error?ui.alert(({source_format_changed:'来源格式变化，旧快照已保留。',crawler_snapshot_missing:'本机尚无可导入的多路采集快照。',crawler_snapshot_invalid:'本机采集快照未通过完整性检查，旧数据已保留。',crawler_latest_attempt_failed_using_previous:'最近采集未通过核对，当前仍为上次成功数据。'}[source.error]||'来源暂不可用，旧快照已保留。'),'danger'):''}${crawlerIds[source.id]?button('采集并更新','collect',{'data-source':source.id}):''}${button(wait?`${wait} 秒后可更新`:source.provider==='local_verified_snapshot'?'导入最近快照':'刷新此来源','refresh-one',{'data-source':source.id,disabled:!!state.refreshing||wait>0})}</section>`}).join('')}<section class="intel-side-section"><h3>World Monitor</h3><p>仅公开工具表发现已预留。认证新闻、金融和航运数据尚未连接。</p>${state.wm?.discovery?`<p class="muted">本轮发现 ${state.wm.discovery.tool_count} 个官方工具；未调用认证数据。</p>`:''}${button('检查官方接口','discover')}</section><p class="muted">可手动更新；USGS、GDACS、WTO 的后台计划在“设备与任务”设置。每源至少间隔90秒。</p></div>`}
  function topics(){return `<div class="intel-topics"><p class="muted">保存检索条件并查看匹配数量，最多12项。当前未启用自动采集或消息推送。</p>${button('关注当前检索','watch-open')}${state.watches.length?state.watches.map(watch=>`<section class="intel-watch"><button type="button" data-intel-watch="${watch.id}"><strong>${esc(watch.name)}</strong><span>${watch.matches} 条匹配 · ${watch.unviewed} 未查看</span><small>${esc(summary(watch.filters))}</small></button>${button('移除','watch-remove',{'data-watch':watch.id,'aria-label':'移除关注主题 '+watch.name},'quiet')}</section>`).join(''):'<div class="empty small">还没有关注主题。先检索，再保存条件。</div>'}</div>`}
  function aside(){return `<aside class="assistant intel-aside"><div class="intel-side-tabs" aria-label="情报侧栏">${['detail','sources','topics'].map((key,index)=>button(['详情','信息源','关注主题'][index],'side',{'data-side':key,'aria-pressed':state.side===key,class:state.side===key?'active':''},'quiet')).join('')}</div><div class="intel-side-content">${state.side==='detail'?detail():state.side==='sources'?sources():topics()}</div></aside>`}

  function setBox(next,{keepCluster=false}={}){
    const w=Math.max(120,Math.min(720,next.w)),h=w/2;state.box={w,h,x:Math.max(0,Math.min(720-w,next.x)),y:Math.max(0,Math.min(360-h,next.y))};
    const map=document.querySelector('#intel-map-svg');if(map)map.setAttribute('viewBox',`${state.box.x} ${state.box.y} ${w} ${h}`);
    const markers=document.querySelector('#intel-map-markers');if(markers)markers.innerHTML=clusters();
    const zoom=document.querySelector('#intel-map-zoom');if(zoom)zoom.textContent=Math.round(720/w*100)+'%';
    if(!keepCluster)state.cluster=null;const popup=document.querySelector('#intel-cluster-popup');if(popup)popup.innerHTML=clusterPopup();
  }
  function zoom(factor){const old=state.box,w=old.w/factor;setBox({w,x:old.x+(old.w-w)/2,y:old.y+(old.h-w/2)/2})}
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
  document.addEventListener('change',event=>{const key=event.target.dataset.intelFilter;if(key)applyFilters(formFilters())});
  document.addEventListener('submit',event=>{if(event.target.id==='intel-search'){event.preventDefault();applyFilters(formFilters())}});
  let suppressMapClick=false,drag=null;
  document.addEventListener('click',async event=>{
    const target=event.target.closest('[data-intel-action],[data-intel-id],[data-intel-cluster],[data-intel-view],[data-intel-chip],[data-intel-watch]');if(!target)return;
    if(suppressMapClick&&event.isTrusted&&target.closest('#intel-map-svg')){suppressMapClick=false;return}
    if(target.dataset.intelId){state.cluster=null;openItem(target.dataset.intelId);return}
    if(target.dataset.intelCluster){state.cluster=target.dataset.intelCluster;const popup=document.querySelector('#intel-cluster-popup');if(popup)popup.innerHTML=clusterPopup();return}
    if(target.dataset.intelView){applyFilters({view:target.dataset.intelView,...(target.dataset.intelView==='bookmarked'?{scope:'archive'}:{})});return}
    if(target.dataset.intelChip){applyFilters({[target.dataset.intelChip]:defaults[target.dataset.intelChip]});return}
    if(target.dataset.intelWatch){const watch=state.watches.find(w=>w.id===target.dataset.intelWatch);if(watch)applyFilters(watch.filters);return}
    const action=target.dataset.intelAction;
    if(action==='filters'){state.expanded=!state.expanded;repaint()}
    else if(action==='clear')applyFilters({...defaults});
    else if(action==='search')search({keepSelection:true});
    else if(action==='refresh')refresh();
    else if(action==='refresh-one')refresh(target.dataset.source);
    else if(action==='side'){state.side=target.dataset.side;repaint();if(state.side==='topics')loadWatches();if(state.side==='sources')loadJobs()}
    else if(action==='article-capture'||action==='article-translate')articleAction(action,target);
    else if(action==='collect'||action==='job-cancel'||action==='job-retry'||action==='job-alert-ack')jobAction(action,target);
    else if(action==='source-panel'){state.side='sources';repaint();loadJobs();if(target.dataset.source)document.querySelector('#intel-source-'+target.dataset.source)?.scrollIntoView({block:'nearest'})}
    else if(action==='topics-panel'){state.side='topics';repaint();loadWatches()}
    else if(action==='next')navigate('next');
    else if(action==='previous')navigate('previous');
    else if(action==='map-toggle'){state.mapVisible=!state.mapVisible;search({keepSelection:true,quiet:true});repaint()}
    else if(action==='zoom-in')zoom(1.6);
    else if(action==='zoom-out')zoom(1/1.6);
    else if(action==='map-reset')setBox({x:0,y:0,w:720});
    else if(action==='locate'&&state.selected?.location){state.mapVisible=true;const p=state.selected.location;state.box={x:Math.max(0,Math.min(480,(p.lon+180)*2-120)),y:Math.max(0,Math.min(240,(90-p.lat)*2-60)),w:240,h:120};search({quiet:true,keepSelection:true});repaint()}
    else if(action==='cluster-close'){state.cluster=null;const popup=document.querySelector('#intel-cluster-popup');if(popup)popup.innerHTML=''}
    else if(action==='item-retry'&&state.selectedId)openItem(state.selectedId);
    else if(action==='bookmark'||action==='unviewed'||action==='review')itemAction(action);
    else if(action==='watch-open'){target.focus();watchOpen()}
    else if(action==='watch-save')watchSave();
    else if(action==='watch-remove'){target.disabled=true;try{await api('commerce_intel_watch_remove',{watch_id:target.dataset.watch});await loadWatches();repaint()}catch(error){toast('移除未确认：'+failMessage(error));target.disabled=false}}
    else if(action==='discover'){target.disabled=true;try{state.wm=await api('commerce_worldmonitor_status',{discover:true});toast('工具表检查完成；认证数据未启用');repaint()}catch(error){toast('接口检查失败：'+failMessage(error));target.disabled=false}}
    else if(action==='export')exportItem();
    else if(action==='copy'&&state.selected){try{await navigator.clipboard.writeText(state.selected.url);toast('来源链接已复制')}catch{const input=document.querySelector('#intel-source-link');input?.focus();input?.select();toast(document.execCommand('copy')?'来源链接已复制':'链接已选中，可使用系统复制')}}
  });
  document.addEventListener('pointerdown',event=>{const map=event.target.closest('#intel-map-svg');if(!map||state.box.w===720||event.button!==0)return;drag={id:event.pointerId,x:event.clientX,y:event.clientY,box:{...state.box},width:map.getBoundingClientRect().width,map,captured:false}});
  document.addEventListener('pointermove',event=>{if(!drag||event.pointerId!==drag.id)return;const dx=event.clientX-drag.x,dy=event.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4){suppressMapClick=true;if(!drag.captured){drag.map.setPointerCapture(event.pointerId);drag.captured=true}}const ratio=drag.box.w/drag.width;const box={...drag.box,x:Math.max(0,Math.min(720-drag.box.w,drag.box.x-dx*ratio)),y:Math.max(0,Math.min(360-drag.box.h,drag.box.y-dy*ratio))};state.box=box;drag.map.setAttribute('viewBox',`${box.x} ${box.y} ${box.w} ${box.h}`)});
  for(const name of ['pointerup','pointercancel'])document.addEventListener(name,event=>{if(drag?.id===event.pointerId){const moved=drag.captured;try{drag.map.releasePointerCapture(event.pointerId)}catch{}drag=null;if(moved)setBox(state.box);setTimeout(()=>{suppressMapClick=false},0)}});
  document.addEventListener('wheel',event=>{if(event.target.closest('#intel-map-svg')&&(event.ctrlKey||event.metaKey)){event.preventDefault();zoom(event.deltaY<0?1.15:1/1.15)}},{passive:false});
  document.addEventListener('keydown',event=>{
    if(event.key==='Enter'&&event.target.id==='intel-watch-name'){event.preventDefault();watchSave();return}
    if((event.key==='Enter'||event.key===' ')&&event.target.matches('g[data-intel-id],g[data-intel-cluster]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));return}
    if(event.target.id==='intel-map-svg'){
      const key=event.key;if(['+','=','-','Home','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(key))event.preventDefault();
      if(key==='+'||key==='=')zoom(1.6);else if(key==='-')zoom(1/1.6);else if(key==='Home')setBox({x:0,y:0,w:720});
      else if(key.startsWith('Arrow'))setBox({...state.box,x:state.box.x+(key==='ArrowLeft'?-1:key==='ArrowRight'?1:0)*state.box.w/12,y:state.box.y+(key==='ArrowUp'?-1:key==='ArrowDown'?1:0)*state.box.h/12});
    }
  });
  let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(isActive?.()&&document.querySelector('#intel-map-svg'))setBox(state.box)},100)});
  window.addEventListener('focus',()=>{if(isActive?.()&&!document.querySelector('.dialog')){search({quiet:true,keepSelection:true});loadWatches()}});
  setInterval(()=>{if(!isActive?.()||state.side!=='sources')return;for(const button of document.querySelectorAll('[data-intel-action="refresh-one"]')){const source=state.sources.find(s=>s.id===button.dataset.source);if(!source)continue;const wait=Math.max(0,Math.ceil(90-(Date.now()/1000-(source.last_attempt||0))));button.disabled=!!state.refreshing||wait>0;button.textContent=wait?wait+' 秒后可更新':source.provider==='local_verified_snapshot'?'导入最近快照':'刷新此来源'}},1000);
  setInterval(()=>{if(!isActive?.())return;if(state.side==='sources')loadJobs();if(state.articles.some(a=>['queued','running'].includes(a.status)||a.translation_status==='running'))loadArticles()},3000);
  async function enter(){loadJobs();search({keepSelection:true});loadWatches();try{state.wm=await api('commerce_worldmonitor_status');if(state.side==='sources')repaint()}catch{}}
  return {view,aside,enter};
};
