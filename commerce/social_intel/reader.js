(() => {
  'use strict';
  const data=JSON.parse(document.querySelector('#data').textContent),ui=window.CommerceUI,e=ui.escape;
  const labels={commerce:'电商选品与市场趋势',ai:'AI 工具与自动化',news:'行业新闻与热点'};
  const status={observed_not_verified:'已观察 · 未独立核实',corroborated:'已有佐证',conflict:'存在冲突',unknown:'尚未确认'};
  const metric={likes:'点赞',views:'播放',comments:'评论',shares:'分享',saves:'收藏',sales:'销量'};
  let selected=data.records[0]?.record_id;
  const el=id=>document.getElementById(id);
  const selectionLabel=r=>r.ranking.selected?'TOP '+r.ranking.rank:(r.source.kind==='permalink'&&r.source.access==='observed'?'候选 · 待核实':'待补来源');
  const fmt=value=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(value))+'（上海）';
  function link(url,label){return url?`<a href="${e(url)}" target="_blank" rel="noreferrer noopener">${e(label)}</a>`:e(label)}
  function assets(ids){return data.assets.filter(a=>ids.includes(a.evidence_id)).map(a=>`<li>${link(encodeURI(a.path),'查看本机证据 '+a.evidence_id)}<br><span class="meta">${e(fmt(a.captured_at))} · ${e(a.locator)}</span><br><code>SHA-256 ${e(a.sha256)}</code></li>`).join('')}
  const selectedCount=data.records.filter(r=>r.ranking.selected).length;
  el('overview').textContent=`本轮 ${data.records.length} 条候选 / ${selectedCount} 条正式入选。${data.scope.limitations} 独立样张尚未接入生产工作台。`;
  el('controls').innerHTML=ui.field('搜索原文与中文',ui.input({id:'query',type:'search',placeholder:'例如：家居、AI、Black Friday'}))+ui.field('主题',ui.select({id:'category',options:[{value:'all',label:'全部主题'},...Object.entries(labels).map(([value,label])=>({value,label}))]}))+ui.field('显示',ui.select({id:'mode',options:[{value:'all',label:'全部候选'},{value:'top',label:'正式 TOP'},{value:'pending',label:'候选（未入 TOP）'}]}))+ui.field('外观',ui.select({id:'theme',value:'system',options:[{value:'system',label:'跟随系统'},{value:'light',label:'浅色'},{value:'dark',label:'深色'}]}));
  function render(){
    const q=el('query').value.toLowerCase(),category=el('category').value,mode=el('mode').value;
    const rows=data.records.filter(r=>(category==='all'||r.category===category)&&(mode==='all'||(mode==='top'?r.ranking.selected:!r.ranking.selected))&&[r.title_zh,r.summary_zh,r.original.text].join(' ').toLowerCase().includes(q));
    if(!rows.some(r=>r.record_id===selected))selected=rows[0]?.record_id;
    el('records').innerHTML=rows.map(r=>ui.button({label:r.title_zh,attrs:{'data-record':r.record_id,'aria-current':r.record_id===selected,'aria-label':r.title_zh+' · '+selectionLabel(r)}})).join('')||ui.empty('没有匹配记录。来源或证据不足时保留空缺。');
    const r=rows.find(r=>r.record_id===selected);
    if(!r){el('detail').innerHTML=ui.empty('本轮尚无满足当前条件的内容。');return}
    el('detail').innerHTML=`<div class="tags">${ui.badge(labels[r.category],'blue')}${ui.badge(status[r.verification],'warning')}${ui.badge(selectionLabel(r),'gray')}</div><h2>${e(r.title_zh)}</h2><p>${e(r.summary_zh)}</p><p class="meta">${e(r.source.platform)} · 发布时间：${e(r.published.display)}（${e(r.published.precision==='unknown'?'年份或时间不明':r.published.precision)}）<br>实际采集：${e(fmt(r.captured_at))}</p><h3>原文摘录</h3><blockquote>${e(r.original.text)}</blockquote><p class="note">${e(r.original.method)} · ${e(r.original.locator)}。未转写的音频与未读取的视频内容不在本条范围。</p><p>${e(r.translation.zh)}</p><p class="note">译文：${e(r.translation.method)} · ${e(r.translation.review_status==='pending'?'待校对':'已校对')}</p><h3>为什么值得跟进</h3><p>${e(r.ranking.reason)}</p><h3>建议下一步</h3><p>${e(r.next_action)}</p><h3>限制与待核实点</h3><ul>${r.limitations.map(s=>`<li>${e(s)}</li>`).join('')}</ul><div class="metric-list">${r.metrics.map(m=>`<span>${e(metric[m.name])} <strong>${e(m.display)}</strong><br><small>${m.approximate?'近似显示值':'界面显示值'}</small></span>`).join('')}</div><p class="note">互动量是界面快照，不代表销量、收益或增长趋势。</p><p>${link(r.source.url,r.source.kind==='permalink'?'打开原始内容':r.source.url?'打开来源入口（未取得单条链接）':'单条原始链接尚未取得')}</p><details><summary>采集证据（${r.evidence_ids.length}）</summary><ul class="evidence-list">${assets(r.evidence_ids)}</ul></details><details><summary>本条历史（实际观察以来）</summary><ul>${data.events.filter(v=>v.record_id===r.record_id).map(v=>`<li>${e(fmt(v.at))} · ${e(v.type)}<p>${e(v.result)}</p><code>${e(v.content_sha256)}</code></li>`).join('')}</ul><p class="note">只展示本轮实际记录，不能回溯尚未采集的历史。</p></details><details><summary>跨工具引用与版本</summary><p>记录 ID：<code>${e(r.record_id)}</code></p><p>内容 SHA-256：<code>${e(r.content_sha256)}</code></p><p>格式：commerce-social-intelligence-v1。JSON 是权威交换包，Markdown 是阅读视图，CSV 是索引。哈希不证明内容真实。</p></details>`;
  }
  el('process').innerHTML=`<h2>本轮采集过程</h2><p class="note">批次 ${e(data.batch_id)} · 每类目标 ${data.scope.top_per_category} 条 · 未达标不补造内容</p><ul>${data.attempts.map(a=>`<li><strong>${e(a.platform)} · ${e(a.query)}</strong><p>${e(a.reason)}</p><p class="meta">${e(fmt(a.started_at))} → ${e(fmt(a.ended_at))} · ${e(a.status)}</p><details><summary>过程证据</summary><ul>${assets(a.evidence_ids)}</ul></details></li>`).join('')}</ul>`;
  el('query').addEventListener('input',render);el('category').addEventListener('change',render);el('mode').addEventListener('change',render);el('theme').addEventListener('change',event=>ui.applyTheme(event.target.value));
  el('records').addEventListener('click',event=>{const b=event.target.closest('[data-record]');if(!b)return;selected=b.dataset.record;render();const d=el('detail');d.tabIndex=-1;d.focus({preventScroll:true});if(window.innerWidth<701)d.scrollIntoView({behavior:'smooth',block:'start'})});
  render();
})();
