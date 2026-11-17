/* Ozon own-store query snapshots. All upstream reads require the explicit button. */
window.CommerceOzonSearchTerms=({api,repaint,isActive=()=>true})=>{
 const ui=window.CommerceUI,e=ui.escape,id=crypto.randomUUID(),SOURCE='own_store_product_queries_not_global_hotterms';
 const s={hidden:true,disposed:false,busy:false,refreshBusy:false,composing:false,status:null,data:null,error:'',notice:'',draft:'',query:'',limit:20,generation:0,request:0,timer:null};
 const active=()=>!s.hidden&&!s.disposed&&isActive();
 const paint=()=>{if(active()&&!s.composing)repaint()};
 const object=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
 const hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
 const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 const value=v=>v==null?'未知':typeof v==='object'?JSON.stringify(v):String(v);
 const period=v=>object(v)&&typeof v.date_from==='string'&&typeof v.date_to==='string';
 const samePeriod=(a,b)=>period(a)&&period(b)&&a.date_from===b.date_from&&a.date_to===b.date_to;
 const current=(generation,request)=>active()&&generation===s.generation&&request===s.request;
 const labels={queued:'已排队 · 尚未完成',running:'正在读取 · 尚未完成',succeeded:'原读取任务已完成',failed:'读取失败',unknown:'结果未知 · 待核对'};
 function validJob(job,connection){return job==null||object(job)&&typeof job.id==='string'&&!!labels[job.status]&&job.connection_sha256===connection&&job.store_identity?.connection_sha256===connection&&job.source===SOURCE&&job.external_execution_allowed===false&&job.queue_is_not_completion===true}
 function validStatus(v){return object(v)&&v.source===SOURCE&&hash(v.connection_sha256)&&v.store_identity?.connection_sha256===v.connection_sha256&&v.store_identity?.platform==='ozon'&&typeof v.configured==='boolean'&&['ready','stock_pending'].includes(v.scope_status)&&period(v.period)&&v.not_global_hot_terms===true&&v.external_execution_allowed===false&&validJob(v.refresh,v.connection_sha256)&&(v.snapshot==null||object(v.snapshot)&&hash(v.snapshot.sha256)&&typeof v.snapshot.id==='string'&&period(v.snapshot.period)&&typeof v.snapshot.fresh_period==='boolean'&&typeof v.snapshot.scope_current==='boolean')}
 function validData(v,status){
  if(!object(v)||v.source!==SOURCE||v.connection_sha256!==status.connection_sha256||v.store_identity?.connection_sha256!==status.connection_sha256||v.not_global_hot_terms!==true||v.external_execution_allowed!==false||!Array.isArray(v.items)||v.items.length>s.limit||!Array.isArray(v.products)||!v.products.every(object)||v.scope_sha256!==status.scope_sha256||v.scope_status!==status.scope_status)return false;
  if(v.availability==='not_collected')return !status.snapshot&&v.snapshot_sha256===null&&v.total===null&&v.items.length===0;
  if(!['snapshot','stale_snapshot'].includes(v.availability)||!status.snapshot||v.snapshot_sha256!==status.snapshot.sha256||v.snapshot_id!==status.snapshot.id||!samePeriod(v.period,status.snapshot.period)||v.scope_current!==status.snapshot.scope_current||(v.availability==='snapshot')!==status.snapshot.fresh_period||!Number.isInteger(v.total)||v.total<v.items.length||v.returned!==v.items.length)return false;
  const metrics=['unique_search_users','unique_view_users','position','view_conversion','gmv','order_count','query_index'];
  return v.items.every(row=>object(row)&&typeof row.query==='string'&&row.query.length>0&&metrics.every(k=>row[k]==null||typeof row[k]==='number'&&Number.isFinite(row[k])&&row[k]>=0)&&(row.currency==null||typeof row.currency==='string'));
 }
 const errorMessage=code=>({ozon_auth_or_permission:'Ozon 读取权限不足，请核对当前店铺 Seller API 角色；未用空值覆盖原快照。',ozon_rate_limited:'Ozon 已限流，请核对原读取回执。',ozon_query_configure_store_first:'请先配置当前 Ozon 店铺。',ozon_query_fresh_stock_required:'当前库存快照缺失或已陈旧，请先更新本店库存。',ozon_query_inventory_limit:'本次库存商品范围超出有界读取限制，请先核对本店商品范围。',ozon_query_platform_sku_required:'当前库存缺少平台 SKU，不能按店铺商品读取搜索词。',ozon_query_read_active:'已有搜索词读取正在处理，请先核对原任务。',ozon_query_connection_changed:'读取期间店铺已切换，未采用上一店铺结果。',ozon_query_scope_changed:'读取期间商品范围已变化，请核对原任务。',ozon_query_transport_unknown:'读取结果未知，请核对原任务，不自动重试。',ozon_query_interrupted_unknown:'原读取中断且结果未知，请先对账，不自动重试。'})[code]||'搜索词记录暂不可读，请刷新状态后核对；未启动模型或其它经营操作。';
 function cancelTimer(){if(s.timer!==null){clearTimeout(s.timer);s.timer=null}}
 function arm(){if(active()&&s.timer===null){const generation=s.generation;s.timer=setTimeout(async()=>{s.timer=null;if(active()&&generation===s.generation)await poll()},5000)}}
 function changed(status){s.request++;s.status=status;s.data=null;s.busy=false;s.refreshBusy=false;s.error='当前店铺或快照版本已变化，已清除原结果；请刷新记录后核对。';s.notice='';paint()}
 async function load(){
  if(!active())return;
  cancelTimer();const generation=s.generation,request=++s.request;s.busy=true;s.error='';s.notice='';s.data=null;paint();
  try{
   const before=await api('commerce_ozon_search_terms_status',{});if(!current(generation,request))return;if(!validStatus(before))throw Error('invalid_receipt');
   const rows=await api('commerce_ozon_search_terms_search',{query:s.query,limit:s.limit});if(!current(generation,request))return;
   const after=await api('commerce_ozon_search_terms_status',{});if(!current(generation,request))return;if(!validStatus(after))throw Error('invalid_receipt');
   if(before.connection_sha256!==after.connection_sha256||!validData(rows,after)){changed(after);return}
   s.status=after;s.data=rows;
  }catch(error){if(current(generation,request)){s.error=errorMessage(error?.message);s.data=null}}
  finally{if(generation===s.generation&&request===s.request)s.busy=false;paint();arm()}
 }
 async function refresh(){
  if(!active()||s.busy||s.refreshBusy||!s.status)return;
  const generation=s.generation,request=++s.request,expected=s.status.connection_sha256;cancelTimer();s.refreshBusy=true;s.error='';s.notice='';paint();let reload=false;
  try{
   const before=await api('commerce_ozon_search_terms_status',{});if(!current(generation,request))return;if(!validStatus(before))throw Error('invalid_receipt');
   if(before.connection_sha256!==expected){changed(before);return}
   if(!before.configured||before.scope_status!=='ready'){s.status=before;throw Error(before.scope_error||'ozon_query_fresh_stock_required')}
   const job=await api('commerce_ozon_search_terms_refresh',{expected_connection_sha256:expected});if(!current(generation,request))return;
   const after=await api('commerce_ozon_search_terms_status',{});if(!current(generation,request))return;if(!validStatus(after))throw Error('invalid_receipt');
   if(after.connection_sha256!==expected||!job||!validJob(job,expected)||after.refresh?.id!==job.id){changed(after);return}
   s.status=after;if(s.data&&!validData(s.data,after))s.data=null;s.notice='已返回原读取任务回执；同店同日去重，排队不代表完成。未知结果不自动重试。';reload=after.refresh.status==='succeeded';
  }catch(error){if(current(generation,request))s.error=errorMessage(error?.message)}
  finally{if(generation===s.generation&&request===s.request)s.refreshBusy=false;paint();arm()}
  if(reload&&current(generation,request))await load();
 }
 async function poll(){
  if(!active())return;
  if(s.busy||s.refreshBusy){arm();return}
  const generation=s.generation,request=s.request;
  try{
   const next=await api('commerce_ozon_search_terms_status',{});if(!current(generation,request))return;if(!validStatus(next))throw Error('invalid_receipt');
   if(s.status&&next.connection_sha256!==s.status.connection_sha256){changed(next);return}
   const different=!same(next,s.status);s.status=next;
   if((next.snapshot?.sha256||null)!==(s.data?.snapshot_sha256||null)||s.data&&next.scope_sha256!==s.data.scope_sha256||s.data&&next.snapshot&&next.snapshot.scope_current!==s.data.scope_current){await load();return}
   if(different)paint();
  }catch(error){if(current(generation,request)){s.error=errorMessage(error?.message);paint()}}
  finally{arm()}
 }
 async function enter(){if(s.disposed)return;s.hidden=false;s.generation++;s.request++;s.status=null;s.data=null;s.error='';s.notice='';s.refreshBusy=false;await load()}
 function search(){if(!active()||s.busy||s.refreshBusy)return;if(Array.from(s.draft).length>100){s.error='搜索词长度不能超过 100 字。';paint();return}s.query=s.draft;return load()}
 function inPanel(node){return !!node?.closest?.(`[data-ozon-search-terms="${id}"]`)}
 const click=async event=>{if(!active())return;const node=event.target?.closest?.('[data-ozon-query-search],[data-ozon-query-refresh],[data-ozon-query-reload]');if(!inPanel(node))return;if(node.dataset.ozonQuerySearch)await search();else if(node.dataset.ozonQueryRefresh)await refresh();else if(node.dataset.ozonQueryReload&&!s.busy&&!s.refreshBusy)await load()};
 const input=event=>{if(!active())return;const node=event.target?.closest?.('[data-ozon-query-input]');if(inPanel(node)&&node.dataset.ozonQueryInput)s.draft=String(node.value??'')};
 const keydown=async event=>{if(!active()||event.key!=='Enter'||event.isComposing||event.keyCode===229||s.composing)return;const node=event.target?.closest?.('[data-ozon-query-input]');if(inPanel(node)&&node.dataset.ozonQueryInput){event.preventDefault();s.draft=String(node.value??'');await search()}};
 const change=async event=>{if(!active())return;const node=event.target?.closest?.('[data-ozon-query-limit]');if(!inPanel(node)||!node.dataset.ozonQueryLimit)return;const n=Number(node.value);if(!Number.isInteger(n)||n<1||n>100){s.error='显示数量须为 1 至 100。';paint();return}s.limit=n;if(!s.busy&&!s.refreshBusy)await load()};
 const compositionstart=event=>{const node=event.target?.closest?.('[data-ozon-query-input]');if(active()&&inPanel(node)&&node.dataset.ozonQueryInput)s.composing=true};
 const compositionend=event=>{const node=event.target?.closest?.('[data-ozon-query-input]');if(active()&&inPanel(node)&&node.dataset.ozonQueryInput){s.draft=String(node.value??'');s.composing=false;paint()}};
 const listeners={click,input,keydown,change,compositionstart,compositionend};for(const [name,fn]of Object.entries(listeners))document.addEventListener(name,fn);
 function periodView(v,label){return period(v)?`<p>${e(label)}：<code>${e(v.date_from)}</code> → <code>${e(v.date_to)}</code></p>`:''}
 function jobView(job){if(!job)return '<p class="muted">当前店铺尚无搜索词读取任务回执。</p>';return `<section class="ui-card"><h4>原读取任务</h4>${ui.badge(labels[job.status]||'状态待核对',job.status==='failed'?'danger':'gray')}<p>${e(job.id)} · 创建于 ${e(value(job.created_at))}${job.finished_at?' · 结束于 '+e(job.finished_at):''}</p>${periodView(job.period,'该任务请求统计窗口（原值）')}${job.status==='unknown'?ui.alert('结果未知，请先核对原任务；不自动重试。'):job.status==='failed'?ui.alert(errorMessage(job.error),'danger'):''}${job.http_status?`<p>平台 HTTP 状态：${e(job.http_status)}</p>`:''}</section>`}
 function rowsView(){
  const d=s.data;if(!d)return '';
  if(d.availability==='not_collected')return ui.empty('尚未采集本店搜索词，暂无完整快照；缺数据不代表商品需求为零。');
  const products=new Map(d.products.map(p=>[String(p.sku),p]));
  const rows=d.items.map(row=>{const p=products.get(String(row.sku));return `<tr><th scope="row">${e(row.query)}<details><summary>平台原始字段</summary><pre>${e(JSON.stringify(row,null,2))}</pre></details></th><td>${e(value(p?.name))}<br>SKU ${e(value(row.sku))}<br>${e(value(p?.offer_id))}</td><td>${e(value(row.unique_search_users))}</td><td>${e(value(row.unique_view_users))}</td><td>${e(value(row.position))}</td><td>${e(value(row.view_conversion))}</td><td>${e(value(row.gmv))} / ${e(row.currency==null?'币种未知':row.currency===''?'币种原码为空':row.currency+'（原始码）')}</td><td>${e(value(row.order_count))}</td></tr>`});
  return `${d.availability==='stale_snapshot'||!d.scope_current||s.status?.snapshot?.fresh_period===false?ui.alert('这是陈旧或商品范围已变化的留存快照，仅供核对；不是当前完整商品范围。'):''}${periodView(d.period,'快照请求统计窗口（原始时区）')}${Object.entries(d.analytics_period||{}).map(([key,v])=>periodView(v,key+' 平台返回统计窗口（原值）')).join('')}<p class="muted">观测时间（原始值）：${e(value(d.observed_at))} · 版本 ${e(d.snapshot_sha256)}。显示 ${d.items.length} / ${e(d.total)} 行，最多显示 100 行，可缩小检索范围；无匹配不代表需求为零。</p>${ui.table(['原始搜索词','关联本店商品 / 平台 SKU','独立搜索用户（本行）','独立浏览用户（本行）','位置（原值）','浏览转化（原值）','GMV / 平台币种原码','订单数（原字段）'],rows,'完整快照中无匹配记录；这不代表商品需求为零。')}`;
 }
 function view(){
  if(s.disposed)return '';
  const status=s.status,disabled=s.busy||s.refreshBusy,refreshDisabled=disabled||!status?.configured||status.scope_status!=='ready';
  return `<section data-ozon-search-terms="${id}"><h3>Ozon 本店商品相关搜索词</h3><p class="muted">仅限当前店铺商品的搜索统计，不代表全平台热搜。中文与俄语按原词检索，不自动翻译、推断排名或启动模型。</p><p>当前店铺：${e(status?.store_identity?.label||'尚未读取店铺状态')} ${status?`· ${e(status.connection_sha256.slice(0,12))}`:''}</p><div class="form-actions">${ui.field('中文 / 俄语原词、商品或 SKU',ui.input({type:'search',value:s.draft,maxlength:100,'data-ozon-query-input':id,'aria-label':'检索本店原始搜索词'}))}${ui.field('最多显示',ui.select({value:String(s.limit),options:[20,50,100].map(n=>({value:String(n),label:String(n)})),disabled,'data-ozon-query-limit':id}))}${ui.button({label:'检索留存记录',attrs:{'data-ozon-query-search':id,disabled}})}${ui.button({label:'刷新记录',attrs:{'data-ozon-query-reload':id,disabled}})}${ui.button({label:'读取本店搜索词',variant:'primary',attrs:{'data-ozon-query-refresh':id,disabled:refreshDisabled}})}</div>${s.busy||s.refreshBusy?'<p role="status">正在核对当前店铺原回执…</p>':''}${s.error?ui.alert(s.error,'danger'):''}${s.notice?ui.alert(s.notice):''}${status&&!status.configured?ui.alert('尚未配置 Ozon 店铺，请先完成私有接入。'):status?.scope_status!=='ready'&&status?ui.alert(errorMessage(status.scope_error)):''}${status?periodView(status.period,'当前可请求窗口（原始时区）'):''}<p class="muted">仅明确点击“读取本店搜索词”才请求一次有界平台读取；同店同日返回原任务，排队不代表完成。独立用户不可跨行相加；GMV 不推算订单。未返回的指标为未知，0 保留原值；币种只展示平台原码，不推断或换算币种。</p>${status?jobView(status.refresh):''}${rowsView()}</section>`;
 }
 function hide(){s.hidden=true;s.generation++;s.request++;s.busy=false;s.refreshBusy=false;s.composing=false;s.status=null;s.data=null;cancelTimer()}
 function dispose(){if(s.disposed)return;s.disposed=true;hide();for(const [name,fn]of Object.entries(listeners))document.removeEventListener(name,fn)}
 return {enter,view,hide,dispose};
};
