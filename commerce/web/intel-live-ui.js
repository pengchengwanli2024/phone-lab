/* Shared public observations; transport timestamps stay separate from news filters. */
window.CommerceIntelLive=({api,esc,repaint,isActive,bounds,preferences,onLocate,onSelect,onFocus,isFocused,isBlocked})=>{
  const ui=window.CommerceUI,copy=v=>JSON.parse(JSON.stringify(v));
  let snapshot=null,error='',busy=false,tab='markets',selection=null,group=null,query='',groups=new Map(),reading=false,lastRead=0,readRevision=0;
  const label={ready:'已更新',idle:'尚未读取',failed:'读取失败 · 保留旧观测',stale:'观测已陈旧',requires_config:'待配置 API Key',requires_authorization:'待确认数据许可',evaluation:'本地开发测试'};
  const button=(text,action,attrs={})=>ui.button({label:text,variant:'quiet',attrs:{'data-intel-live':action,...attrs}});
  const source=k=>snapshot?.sources?.[k];
  const paint=()=>{if(!isBlocked?.()&&!document.activeElement?.matches?.('input,textarea,select'))repaint();};
  const time=v=>v?new Date(v*1000).toLocaleString('zh-CN',{hour12:false}):'尚无观测';
  const number=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:2}):'—';
  const change=q=>typeof q.change_percent==='number'?`${q.change_percent>=0?'+':''}${q.change_percent.toFixed(2)}%`:'—';
  const changeClass=q=>typeof q.change_percent!=='number'?'':q.change_percent>=0?'is-up':'is-down';
  const price=q=>typeof q.price==='number'?q.price.toLocaleString('zh-CN',{maximumFractionDigits:q.symbol==='CNY=X'?4:2}):'—';
  const emptyLabel=s=>({expired:'位置样本已过期，请按来源限频重新读取。',outside_filter:'已有 '+s.fresh_count+' 条有效位置，当前视野或检索条件未匹配。',never_received:'尚未收到有效位置样本。',empty:'来源本次未返回有效位置。'})[s.availability]||'当前视野没有可展示的有效观测。';
  const providerError=s=>({upstream_http_429:'来源限频，请到下次可读时间再试。',ais_stream_disconnected:'AIS 连接已建立，但位置流在收到有效数据前断开。',ais_proxy_dependency_missing:'当前 WebSocket 代理缺少所需依赖。',ais_connection_failed:'无法连接 AIS 位置流，请稍后重试。',ais_subscription_rejected:'AIS 服务拒绝订阅，请在供应商账户中检查密钥和连接限制。',ais_no_positions:'订阅窗口内未收到有效船舶位置。',ais_client_unavailable:'船舶连接客户端暂不可用。'})[s.error]||'来源读取失败，稍后可重试。';
  const rowName=r=>r.kind==='flight'?(r.callsign||r.icao24):r.name||r.mmsi;
  function focus(id){requestAnimationFrame(()=>document.getElementById(id)?.focus({preventScroll:true}));}
  async function read(){
    const revision=++readRevision;reading=true;
    try{const value=await api('commerce_intel_live_get',{bounds:bounds(),query});if(revision!==readRevision)return;snapshot=value;error='';lastRead=Date.now();
      const current=Object.values(value.sources||{}).flatMap(s=>s.items||[]),byId=new Map(current.map(r=>[r.id,r]));
      if(selection)selection=byId.get(selection.id)||null;
      if(group){group=group.map(r=>byId.get(r.id)).filter(Boolean);if(!group.length)group=null;}
    }
    catch{if(revision===readRevision)error='实时监测快照暂时无法读取，可重试。';}
    finally{if(revision===readRevision){reading=false;paint();}}
  }
  async function refresh(key='all',evaluation=false,session){
    if(busy)return;busy=true;error='';paint();
    try{await api('commerce_intel_live_refresh',{source:key,...(evaluation?{evaluation:true}:{}),...(session?{evaluation_session:session,...(session==='start'?{minutes:60}:{})}:{})});await read();}
    catch{error='刷新请求未确认。请先重新读取状态，再明确重试。';}
    finally{busy=false;paint();}
  }
  async function enter(){await read();await refresh();}
  function spark(q){const values=(q.series||[]).filter(v=>typeof v==='number'&&Number.isFinite(v));if(values.length<2)return '';
    const low=Math.min(...values),range=Math.max(...values)-low||1;
    return `<svg class="intel-price-spark" viewBox="0 0 100 28" role="img" aria-label="最近一个月日线收盘走势"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${values.map((v,i)=>`${i*100/(values.length-1)},${26-(v-low)/range*24}`).join(' ')}"/></svg>`;
  }
  function ribbon(){const quotes=source('markets')?.items||[];return `<div class="intel-market-ribbon" aria-label="全球行情速览">${quotes.length?quotes.slice(0,7).map(q=>`<button type="button" data-intel-live="quote" data-key="${esc(q.id)}"><span>${esc(q.name)}</span><strong>${price(q)}</strong><small class="${changeClass(q)}">${change(q)}</small></button>`).join(''):'<span class="muted">全球行情 · '+(source('markets')?.refresh_status==='running'?'读取公开行情中…':label[source('markets')?.status]||'尚未读取')+'</span>'}<small class="intel-quote-caveat">行情可能延迟<br>含最近交易时段</small></div>`;}
  function details(row){if(!row)return '';return `<div class="intel-observation-detail"><header><strong>${esc(rowName(row))}</strong>${button('关闭','clear',{'aria-label':'关闭位置详情'})}</header><dl>${Object.entries({'标识':row.icao24||row.mmsi,'注册国家':row.country,[row.kind==='flight'?'气压高度':'高度']:row.altitude_m==null?null:number(row.altitude_m)+' 米',[row.kind==='flight'?'地速':'速度']:row.speed_kmh==null?null:number(row.speed_kmh)+' 公里/小时',[row.kind==='flight'?'航迹角':'航向']:row.heading==null?'未提供':number(row.heading)+'°','观测时间':time(row.observed_at),'坐标':row.location.lat.toFixed(5)+', '+row.location.lon.toFixed(5)}).filter(([,v])=>v!=null).map(([k,v])=>`<dt>${k}</dt><dd>${esc(v)}</dd>`).join('')}</dl><a href="${esc(row.source_url)}" target="_blank" rel="noopener noreferrer">${esc(row.source)} ↗</a><small>接收站观测，不推断航线、目的地或异常。</small></div>`;}
  function popup(){if(selection?.kind)return `<div class="intel-cluster-popup intel-live-popup">${details(selection)}</div>`;if(group)return `<div class="intel-cluster-popup"><header><strong>邻近航空器/船舶 · ${group.length} 条</strong>${button('关闭','clear')}</header>${group.slice(0,30).map(r=>button(rowName(r)+' · '+time(r.observed_at),'select',{'data-key':r.id})).join('')}${group.length>30?'<small>显示前30条，放大地图查看其它点位。</small>':''}</div>`;return '';}
  function quoteDetail(q){return `<div class="intel-quote-detail"><header><strong>${esc(q.name)} · ${esc(q.symbol)}</strong>${button('返回行情','clear')}</header><p><b>${price(q)}</b> ${esc(q.currency)} <span class="${changeClass(q)}">${change(q)}</span></p>${spark(q)}<small>${esc(q.change_basis)} · 观测 ${time(q.observed_at)}</small><p class="muted">发布方行情可能延迟；非交易时段保留最近价格。</p><a href="${esc(q.source_url)}" target="_blank" rel="noopener noreferrer">${esc(q.source)} ↗</a></div>`;}
  function rows(){const s=source(tab);if(!s)return '<p class="muted">正在读取共享监测快照…</p>';
    if(tab==='vessels'&&s.status==='requires_config')return `<div class="intel-live-empty"><h3>连接船舶位置流</h3><p>AISStream 需要免费账户的 API Key。配置后即可读取位置、速度和航向。</p><a href="https://aisstream.io/" target="_blank" rel="noopener noreferrer">打开 AISStream ↗</a><details><summary>本机配置方式</summary><p>将 AISStream 账户生成的密钥填入私有运行目录 intel-live.json 的 AISSTREAM_API_KEY。模型供应商密钥不能用于船舶位置流。密钥仅在服务端读取，切勿提交到源码。</p></details><small>沿海接收站覆盖，并非全球卫星 AIS。</small></div>`;
    if(tab==='markets'){
      const selected=s.items.find(q=>q.id===selection?.id);if(selected)return quoteDetail(selected);
      return `<table class="intel-quotes-table"><thead><tr><th>市场</th><th>最新值</th><th>涨跌</th></tr></thead><tbody>${s.items.map(q=>`<tr><td><button type="button" data-intel-live="quote" data-key="${esc(q.id)}">${esc(q.name)}<small>${esc(q.symbol)} · ${esc(q.currency)}</small></button></td><td>${price(q)}</td><td class="${changeClass(q)}">${change(q)}</td></tr>`).join('')}</tbody></table>${s.unavailable?.length?`<p role="status">${s.unavailable.length} 项行情暂不可用，未显示为0。</p>`:''}<small class="intel-provider-note">股票/期货较前交易日；加密资产为24小时。选择市场查看时间与走势。</small>`;
    }
    const list=s.items.filter(r=>!query||[r.callsign,r.icao24,r.name,r.mmsi,r.country].join(' ').toLowerCase().includes(query.toLowerCase()));
    return `${s.mode==='local_evaluation'?`<div class="intel-provider-note" role="status">本地开发测试 · ${s.evaluation_session?.active?'连续测试至 '+time(s.evaluation_session.until)+'，保持此页可见时按限频读取。':s.evaluation_session?.ended?'连续测试已到期结束，可按需重新开始。':'可手动读取，或开始有时限的连续测试。'} ${button(s.evaluation_session?.active?'停止连续测试':'连续测试60分钟',s.evaluation_session?.active?'session-stop':'session-start',{disabled:busy})}</div>`:''}${s.status==='requires_authorization'?'<div class="intel-provider-note" role="status">当前仅为实测评估快照，自动刷新已暂停。运营使用需要 OpenSky 书面许可。<a href="https://opensky-network.org/about/terms-of-use" target="_blank" rel="noopener noreferrer">查看许可要求 ↗</a></div>':''}${selection?.kind?details(selection):''}<form id="intel-live-search">${ui.input({id:'intel-live-query',type:'search','aria-label':'检索航空器或船舶',maxlength:64,value:query,placeholder:'呼号、标识或名称'})}${ui.button({label:'查找',variant:'secondary',attrs:{type:'submit'}})}</form><small class="intel-provider-note">当前地图视野 ${s.matched} 条${s.truncated?' · 显示上限600':''} · ${s.mode==='local_evaluation'?(s.evaluation_session?.active?'连续测试 · ':'手动读取 · ')+'最短'+s.interval_seconds/60+'分钟':s.interval_seconds/60+'分钟刷新'}${list.length>60?' · 列表显示最新60条，可检索或缩小视野':''}</small><div class="intel-position-list">${list.slice(0,60).map(r=>`<button type="button" id="intel-live-row-${r.id}" data-intel-live="locate" data-key="${r.id}"><strong>${esc(rowName(r))}</strong><span>${number(r.speed_kmh)} km/h · ${r.kind==='flight'?number(r.altitude_m)+' m':esc(r.mmsi)}</span><small>${time(r.observed_at)}</small></button>`).join('')||`<p class="muted" role="status">${esc(emptyLabel(s))}</p>`}</div><small class="intel-provider-note">${esc(snapshot.coverage)}${s.partial?' · 本次连接中断，保留已收到的位置样本。':''}</small>`;
  }
  function panel(){const s=source(tab),running=s?.refresh_status==='running',wait=Math.max(0,Math.ceil((s?.next_refresh||0)-Date.now()/1000)),refreshLabel=wait?Math.ceil(wait/60)+'分钟后可读':s?.mode==='local_evaluation'?'读取测试样本':'刷新';return `<section class="card intel-live-panel" aria-label="实时监测面板"><header><h2>实时监测</h2><span class="intel-live-status">${running?'正在更新…':s?.availability==='expired'?'位置样本已过期':label[s?.status]||'准备读取'}</span>${!isFocused?.()?button('放大','focus',{id:'intel-focus-live','aria-label':'放大实时监测'}):''}${button(refreshLabel,'refresh',{title:wait?'下次允许读取：'+time(s.next_refresh):'读取最新来源快照',disabled:busy||running||wait>0||['requires_config','requires_authorization'].includes(s?.status)})}</header><div class="intel-live-tabs" role="group" aria-label="监测数据类型">${[['markets','全球行情'],['flights','航空器'],['vessels','船舶']].map(([k,n])=>button(n,'tab',{'data-key':k,'aria-pressed':tab===k})).join('')}</div>${error?`<p role="alert">${esc(error)} ${button('重新读取','read')}</p>`:''}${s?.error&&s.status!=='requires_config'?`<p class="intel-live-error" role="alert">${esc(providerError(s))}${s.last_success?' 最近成功 '+time(s.last_success):' 尚无成功观测。'}</p>`:''}<div class="intel-live-content">${rows()}</div><footer>${esc(s?.provider||'公开来源')} · ${s?.last_success?'读取于 '+time(s.last_success):label[s?.status]||'等待返回'}</footer></section>`;}
  function items(){const layers=preferences().layers;return ['flights','vessels'].flatMap(k=>layers.includes(k)?source(k)?.items||[]:[]);}
  function mapMarkers(box,pixel){groups=new Map();for(const row of items()){
    const x=(row.location.lon+180)*2,y=(90-row.location.lat)*2,key=row.kind+':'+Math.floor(x/(28*pixel))+':'+Math.floor(y/(28*pixel));
    if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);
  }
    return [...groups].map(([key,rows])=>{const x=rows.reduce((n,r)=>n+(r.location.lon+180)*2,0)/rows.length,y=rows.reduce((n,r)=>n+(90-r.location.lat)*2,0)/rows.length,color=rows[0].kind==='flight'?'var(--ui-color-brand)':'var(--ui-color-success)';
      return `<g role="button" tabindex="0" data-intel-live="map" data-key="${key}" aria-label="${rows.length>1?rows.length+' 条'+(rows[0].kind==='flight'?'航空器':'船舶')+'观测':esc(rowName(rows[0]))}"><circle cx="${x}" cy="${y}" r="${14*pixel}" fill="transparent"/>${rows.length>1?`<circle cx="${x}" cy="${y}" r="${8*pixel}" fill="${color}"/><text x="${x}" y="${y}" dy=".34em" text-anchor="middle" font-size="${8*pixel}" fill="var(--ui-color-on-brand)">${rows.length}</text>`:`<path d="M0 -7L4 5L0 3L-4 5Z" transform="translate(${x} ${y}) rotate(${rows[0].heading||0}) scale(${pixel})" fill="${color}" stroke="var(--ui-color-surface)" stroke-width=".7"/>`}</g>`;
    }).join('');
  }
  function clear(){const id=selection?.id;selection=null;group=null;repaint();if(id)requestAnimationFrame(()=>{(document.getElementById('intel-live-row-'+id)||document.getElementById('intel-map-svg'))?.focus({preventScroll:true});});}
  document.addEventListener('click',event=>{
    if(!isActive()||isBlocked?.())return;const t=event.target.closest('[data-intel-live]');if(!t||t.disabled)return;
    const action=t.dataset.intelLive,key=t.dataset.key;
    if(action==='refresh'){refresh(tab,source(tab)?.mode==='local_evaluation');return;}if(action==='read'){read();return;}
    if(action==='focus'){onFocus?.();return;}
    if(action==='session-start'||action==='session-stop'){refresh('flights',false,action==='session-start'?'start':'stop');return;}
    if(action==='clear'){clear();return;}
    if(action==='tab'){tab=key;selection=null;group=null;query='';repaint();read();return;}
    if(action==='quote'){tab='markets';selection=source('markets')?.items.find(q=>q.id===key);repaint();return;}
    if(action==='map'){onSelect?.();const found=groups.get(key)||[];if(found.length===1){selection=found[0];group=null;tab=selection.kind==='flight'?'flights':'vessels';}else{group=copy(found);selection=null;}repaint();return;}
    const row=[...items(),...(group||[])].find(r=>r.id===key)||Object.values(snapshot?.sources||{}).flatMap(s=>s.items).find(r=>r.id===key);
    if(row){onSelect?.();selection=row;group=null;if(action==='locate')onLocate(row);repaint();}
  });
  document.addEventListener('submit',event=>{if(event.target.id!=='intel-live-search')return;event.preventDefault();query=(document.getElementById('intel-live-query')?.value.trim()||'').slice(0,64);read().then(()=>{repaint();focus('intel-live-query');});});
  document.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('g[data-intel-live]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
  setInterval(async()=>{if(!isActive()||isBlocked?.()||document.hidden||reading||busy||document.querySelector('.dialog')||document.activeElement?.matches?.('input,textarea,select')||document.querySelector('.intel-picker[open]'))return;
    const running=Object.values(snapshot?.sources||{}).some(s=>s.refresh_status==='running');
    if(Date.now()-lastRead>(running?1800:15000))await read();
    if(!error&&Object.values(snapshot?.sources||{}).some(s=>(s.mode!=='local_evaluation'||s.evaluation_session?.active)&&!['requires_config','requires_authorization'].includes(s.status)&&s.refresh_status!=='running'&&Date.now()/1000>=s.next_refresh))await refresh();
  },2000);
  return {enter,read,refresh,ribbon,panel,mapMarkers,popup,clear,dismiss:()=>{selection=null;group=null;},hasSelection:()=>!!selection?.kind||!!group,source,selection:()=>selection};
};
