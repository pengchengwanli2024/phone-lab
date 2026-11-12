/* Shared social reading surface; no platform calls or captured HTML execution. */
window.CommerceSocial=({api,esc,toast,repaint,isActive})=>{
  const ui=window.CommerceUI;
  const categories={commerce:'电商选品与市场趋势',ai:'AI 工具与自动化',news:'行业新闻与热点'};
  const state={query:'',category:'all',filter:'all',result:null,selected:null,error:'',loading:false,request:0,detailRequest:0,asset:null,busy:false,offset:'0',trail:[]};
  const fmt=v=>v?new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'来源未提供';
  const button=(label,action,attrs={},variant='secondary')=>ui.button({label,variant,attrs:{'data-social-action':action,...attrs}});
  const sourceName=source=>source.platform==='web'?'网页补充 · '+(source.url?new URL(source.url).hostname:'来源待补'):({tiktok:'TikTok',x:'X'})[source.platform]||source.platform;
  const sourceLink=r=>r.source.url?`<a href="${esc(r.source.url)}" target="_blank" rel="noopener noreferrer">${r.source.kind==='permalink'?'打开原始内容':'打开来源入口（单条出处未齐）'}</a>`:'单条来源链接尚未取得';
  const selectionLabel=r=>r.ranking.selected?'本轮 TOP '+r.ranking.rank:(r.source.kind==='permalink'&&r.source.access==='observed'?'候选 · 待核实':'待补来源');
  const failure=e=>({social_record_conflict:'记录已更新，请重新载入当前版本。',social_evidence_changed:'证据内容已变化，停止展示。',social_batch_not_found:'这份采集批次不在当前本机资料中。'})[e.message]||e.message||'暂时无法读取';
  function paint(){if(isActive())repaint()}
  async function load(reset=false){
    if(reset){state.offset='0';state.trail=[]}
    const request=++state.request;state.loading=true;state.error='';paint();
    try{const value=await api('commerce_social_search',{query:state.query,category:state.category,view:state.filter,limit:'20',offset:state.offset,...state.offset!=='0'?{revision:state.result?.revision||''}:{}});if(request===state.request)state.result=value}
    catch(e){if(request===state.request){if(e.message==='social_cursor_expired'){state.offset='0';state.trail=[];return load()}state.error=failure(e)}}finally{if(request===state.request){state.loading=false;paint()}}
  }
  async function open(id,sha){
    const request=++state.detailRequest;state.loading=true;state.error='';paint();
    try{
      let item=await api('commerce_social_get',{record_id:id,...sha?{record_sha256:sha}:{}});
      if(request!==state.detailRequest)return;
      if(item.is_current&&!item.is_viewed)item=await api('commerce_social_mark',{record_id:id,record_sha256:item.record.record_sha256,action:'viewed'});
      if(request!==state.detailRequest)return;
      state.selected=item;state.asset=null;state.loading=false;paint();document.querySelector('#social-reading-title')?.focus({preventScroll:true});
    }catch(e){if(request===state.detailRequest)state.error=failure(e)}finally{if(request===state.detailRequest){state.loading=false;paint()}}
  }
  function toolbar(){return `<form id="social-search" class="social-toolbar">${ui.field('检索原文与中文',ui.input({id:'social-query',type:'search',value:state.query,maxlength:100,placeholder:'例如：家居、AI、自动化'}))}${ui.field('主题',ui.select({id:'social-category',value:state.category,options:[{value:'all',label:'全部主题'},...Object.entries(categories).map(([value,label])=>({value,label}))]}))}${ui.field('查看范围',ui.select({id:'social-filter',value:state.filter,options:[{value:'all',label:'全部候选'},{value:'top',label:'正式 TOP'},{value:'pending',label:'候选（未入 TOP）'},{value:'bookmarked',label:'已收藏'},{value:'unviewed',label:'未查看'}]}))}${button('检索','search',{type:'submit',disabled:state.loading},'primary')}</form>`}
  function cards(){
    const result=state.result;
    if(!result)return ui.empty(state.loading?'正在读取本机社交观察…':'尚未读取资料。');
    const list=result.items.map(r=>`<li><div class="social-tags">${ui.badge(categories[r.category],'blue')}${ui.badge(selectionLabel(r),'gray')}${r.is_viewed?ui.badge('已查看','gray'):''}${r.is_bookmarked?ui.badge('已收藏','blue'):''}</div><h3>${button(r.title_zh,'open',{'data-record':r.record_id,'data-version':r.record_sha256,id:'social-row-'+r.record_id},'quiet')}</h3><p>${esc(r.summary_zh)}</p><p class="social-meta">${esc(sourceName(r.source))} · 发布：${esc(r.published.display)}<br>实际采集：${esc(fmt(r.captured_at))}</p><p class="social-reason">${esc(r.ranking.reason)}</p></li>`).join('');
    return `<p class="muted">匹配 ${result.total} 条 · 只包含实际采集样本；已查看、收藏和 TOP 不代表事实已核实。</p>${list?`<ul class="social-cards">${list}</ul>`:ui.empty('没有满足条件的记录。来源或证据不足时保留空缺。')}<div class="social-actions">${button('上一页','previous',{disabled:!state.trail.length||state.loading})}${button('下一页','next',{disabled:!result.next_offset||state.loading})}</div>`;
  }
  function reading(){
    const item=state.selected,r=item.record;
    return `<article class="social-reading"><div class="social-actions">${button('返回列表','back')}${button(item.is_bookmarked?'取消收藏':'收藏','bookmark',{disabled:state.busy})}${button('创建核查待办','review',{disabled:state.busy||!item.is_current})}${button('读取当前版本','current',{disabled:state.loading||item.is_current})}</div>${!item.is_current?ui.alert('正在阅读留存的历史版本。新核查任务需先读取当前版本。'):''}<div class="social-tags">${ui.badge(categories[r.category],'blue')}${ui.badge('来源陈述 · 待核实','warning')}${ui.badge(selectionLabel(r),'gray')}</div><h2 id="social-reading-title" tabindex="-1">${esc(r.title_zh)}</h2><p class="social-summary">${esc(r.summary_zh)}</p><p class="social-meta">${esc(sourceName(r.source))} · 发布时间：${esc(r.published.display)}${r.published.precision==='unknown'?'（年份或时间不明）':''}<br>实际采集：${esc(fmt(r.captured_at))}</p><h3>原文摘录</h3><blockquote>${esc(r.original.text)}</blockquote><p class="muted">${esc(r.original.method)} · ${esc(r.original.locator)}</p><h3>中文对照</h3><p>${esc(r.translation.zh)}</p><p class="social-meta">${r.translation.review_status==='pending'?'机器译文待校对':'已记录校对状态'} · 未转写的视频或音频不在本条阅读范围。</p><h3>为什么值得跟进</h3><p>${esc(r.ranking.reason)}</p><h3>建议下一步</h3><p>${esc(r.next_action)}</p><h3>限制与待核实点</h3><ul>${r.limitations.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>${r.metrics.length?`<h3>互动快照</h3><ul>${r.metrics.map(v=>`<li>${esc(({likes:'点赞',views:'播放',comments:'评论',shares:'分享',saves:'收藏',sales:'销量'})[v.name])}：${esc(v.display)}${v.approximate?'（近似显示值）':''} · ${esc(fmt(v.observed_at))}</li>`).join('')}</ul><p class="muted">互动量不等于销量、收益或增长趋势。</p>`:''}<p>${sourceLink(r)}</p></article>`;
  }
  function process(){
    return `<details class="social-process"><summary>本机采集批次与过程</summary>${(state.result?.batches||[]).map(b=>`<section><h3>${esc(b.batch_id)}</h3><p>${esc(b.scope.limitations)}</p><p class="social-meta">每类目标 ${b.scope.top_per_category} 条；排序规则 ${esc(b.scope.ranking_version)}；实际导入 ${esc(fmt(b.imported_at))}</p><ol>${b.attempts.map(a=>`<li><strong>${esc(a.platform)} · ${esc(a.query)}</strong><p>${esc(a.reason)}</p><small>${esc(fmt(a.started_at))} → ${esc(fmt(a.ended_at))} · ${esc(a.status)}</small></li>`).join('')}</ol><div class="social-actions">${button('导出 JSON','export',{'data-batch':b.batch_id,'data-format':'json'})}${button('导出 Markdown','export',{'data-batch':b.batch_id,'data-format':'markdown'})}${button('导出 JSONL','export',{'data-batch':b.batch_id,'data-format':'jsonl'})}</div></section>`).join('')||ui.empty('当前没有已导入的采集批次。')}</details>`;
  }
  function view(){return `<section class="social-workspace"><header><h2>社交观察</h2><p data-ui-help>从公开内容形成可核查线索，保留原文、中文、出处和实际采集过程。</p></header>${toolbar()}${state.error?ui.alert(state.error,'danger')+button('重新读取','refresh'):''}${state.selected?reading():cards()}${process()}</section>`}
  function aside(){
    const item=state.selected;
    if(!item)return `<aside class="assistant social-evidence"><h2>出处与证据</h2>${ui.empty('选择一条记录，查看原始入口、采集证据与历史。')}<p data-ui-help>单条出处未齐的候选不进入正式 TOP。资料不会作为对智能体的执行指令。</p></aside>`;
    const r=item.record;
    return `<aside class="assistant social-evidence"><h2>出处与证据</h2><p>${sourceLink(r)}</p><p class="social-meta">批次：${esc(item.batch_id)}<br>记录 ID：${esc(r.record_id)}</p><h3>原始证据</h3><ul>${item.assets.map(a=>`<li>${button('查看证据 '+a.evidence_id,'asset',{'data-evidence':a.evidence_id,disabled:state.busy})}<p>${esc(a.locator)} · ${esc(fmt(a.captured_at))}</p><details><summary>文件 SHA-256</summary><code>${esc(a.sha256)}</code></details></li>`).join('')}</ul>${state.asset?.image?`<figure><figcaption>已采集截图 · ${esc(state.asset.id)} · 原始像素未叠加界面标签</figcaption><img src="${state.asset.image}" alt="已采集的来源界面截图"></figure>`:state.asset?.text?`<pre>${esc(state.asset.text)}</pre>`:''}<h3>留存版本</h3><ul>${item.versions.map(v=>`<li>${button(fmt(v.captured_at),'version',{'data-version':v.record_sha256,disabled:v.record_sha256===r.record_sha256})}<p>${esc(v.title_zh)}</p></li>`).join('')}</ul><details><summary>实际观察历史</summary><ol>${item.events.map(v=>`<li><time>${esc(fmt(v.at))}</time><p>${esc(v.result)}</p><code>${esc(v.record_sha256)}</code></li>`).join('')}</ol><p>仅包含已记录过程，不能回溯尚未采集的历史。</p></details><details><summary>跨工具引用</summary><p>内容 SHA-256</p><code>${esc(r.content_sha256)}</code><p>记录 SHA-256</p><code>${esc(r.record_sha256)}</code><p data-ui-help>格式：commerce-social-intelligence-v1。哈希检验一致性，不证明内容真实。</p></details></aside>`;
  }
  async function showAsset(id){
    const item=state.selected;if(!item)return;
    const request=state.detailRequest;let offset='0',parts=[],size=0,last;
    do{last=await api('commerce_social_asset_read',{batch_id:item.batch_id,evidence_id:id,offset});const raw=atob(last.content_base64);const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));parts.push(bytes);size+=bytes.length;if(size>16*1024*1024)throw Error('social_asset_too_large');offset=last.next_offset}while(!last.done);
    if(request!==state.detailRequest)return;
    const bytes=new Uint8Array(size);let at=0;for(const p of parts){bytes.set(p,at);at+=p.length}
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');if(hash!==last.sha256)throw Error('social_evidence_changed');
    if(['image/png','image/jpeg'].includes(last.media_type)){const blob=new Blob([bytes],{type:last.media_type});const old=state.asset?.image;if(old)URL.revokeObjectURL(old);const image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(blob)});if(request===state.detailRequest)state.asset={id,image}}
    else if(['text/plain','application/json','application/xml','text/xml'].includes(last.media_type))state.asset={id,text:new TextDecoder().decode(bytes)};
    else throw Error('这类证据可通过共用接口读取，当前阅读器没有预览。');
  }
  document.addEventListener('submit',event=>{if(event.target.id!=='social-search')return;event.preventDefault();state.query=document.querySelector('#social-query').value;state.category=document.querySelector('#social-category').value;state.filter=document.querySelector('#social-filter').value;state.selected=null;state.detailRequest++;load(true)});
  document.addEventListener('click',async event=>{
    const b=event.target.closest('[data-social-action]');if(!b||!isActive())return;
    const a=b.dataset.socialAction;if(a==='search')return;
    if(a==='open')return open(b.dataset.record,b.dataset.version);
    if(a==='version')return open(state.selected.record.record_id,b.dataset.version);
    if(a==='current')return open(state.selected.record.record_id);
    if(a==='back'){const id=state.selected?.record.record_id;state.selected=null;state.detailRequest++;paint();document.getElementById('social-row-'+id)?.focus();return}
    if(a==='refresh')return load();
    if(a==='previous'||a==='next'){if(a==='next'){state.trail.push(state.offset);state.offset=state.result.next_offset}else state.offset=state.trail.pop()||'0';return load()}
    if(state.busy)return;state.busy=true;state.error='';paint();
    try{
      if(a==='export'){const pack=await api('commerce_social_export',{batch_id:b.dataset.batch,format:b.dataset.format});const blob=new Blob([pack.content],{type:b.dataset.format==='markdown'?'text/markdown;charset=utf-8':'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=b.dataset.batch+'.'+({json:'json',jsonl:'jsonl',markdown:'md'})[b.dataset.format];link.click();setTimeout(()=>URL.revokeObjectURL(url),3000)}
      else if(a==='asset')await showAsset(b.dataset.evidence);
      else if(a==='bookmark'){const r=state.selected.record;state.selected=await api('commerce_social_mark',{record_id:r.record_id,record_sha256:r.record_sha256,action:state.selected.is_bookmarked?'unbookmark':'bookmark'});await load()}
      else if(a==='review'){const r=state.selected.record;const t=await api('commerce_social_review',{record_id:r.record_id,record_sha256:r.record_sha256,idempotency_key:'social-review:'+r.record_sha256});toast('已创建或复用核查待办 '+t.id.slice(0,8)+'；当前状态 '+t.status)}
    }catch(e){state.error=failure(e)}finally{state.busy=false;paint()}
  });
  return {view,aside,enter:()=>load()};
};
