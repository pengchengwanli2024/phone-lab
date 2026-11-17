/* Readable, escaped projections of the shared assistant's retained evidence. */
window.CommerceAssistantEvidence=(()=>{
  const date=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'';
  function link(value){try{const u=new URL(value);if(!['http:','https:'].includes(u.protocol)||u.username||u.password||!u.hostname.includes('.')||/^(?:127\.|10\.|192\.168\.|169\.254\.)/.test(u.hostname)||u.hostname.endsWith('.local'))return '';return u.href}catch{return ''}}
  const error=code=>({web_provider_timeout:'检索超时，可重试',web_search_not_configured:'检索服务尚未配置',web_provider_unavailable:'检索来源暂不可用',web_http_403:'来源拒绝公开读取',web_http_404:'原文已不可访问',web_page_unavailable:'原文暂时无法读取',web_page_body_unavailable:'来源页面未提供可读取的正文',web_dns_unavailable:'来源网络解析失败',web_private_address_rejected:'该地址不属于可读取的公开来源'})[code]||'该来源暂未读取成功';
  function item(row,esc){
    const url=link(row.url),title=row.title||row.name||'公开来源',stamp=row.published_beijing||date(row.published_at??row.published);
    const publication=row.publication_status==='future_timestamp'?'来源时间晚于当前，待核对':row.publication_status==='outside_window'?'不在所选日期':stamp?'发布于 '+stamp:'发布时间待核对';
    const content=(row.content_status==='search_summary_only'?'搜索摘要':row.content_status==='page_text'?'正文已读取':row.content_status==='json_data'?'公开数据已读取':'')+(row.text_truncated?' · 内容已限量':'');
    return `<li class="copilot-source-item"><div>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>`:`<strong>${esc(title)}</strong>`}</div><small>${esc([row.publisher||row.source,publication,content].filter(Boolean).join(' · '))}</small>${row.status==='failed'?`<p role="status">${esc(error(row.error))}</p>`:row.summary||row.text?`<p>${esc((row.summary||row.text).slice(0,320))}${(row.summary||row.text).length>320?'…':''}</p>`:''}${row.source_sha256?`<details><summary>来源版本</summary><code>${esc(row.source_sha256)}</code></details>`:''}</li>`;
  }
  function render(observation,esc){
    const data=observation.data||{},refs=(observation.references||[observation.id]).join('、'),tag=`<small class="copilot-source-ref">${esc(refs)}</small>`;
    if(observation.tool==='commerce_web_search')return `<section class="copilot-public-sources"><header><strong>公开网络检索</strong>${tag}</header><p class="muted">${data.cached?'缓存读取 · ':'检索于 '}${esc(date(data.retrieved_at))} · ${esc(data.window?.date_beijing||'')} · 来源陈述待核实</p>${(data.groups||[]).map(group=>`<section><h4>${esc(group.label||'公开网络')} · ${group.items?.length||0} 条</h4>${group.status==='failed'?`<p role="status">${esc(error(group.error))}</p>`:!group.items?.length?'<p>本次检索未返回匹配结果。</p>':`<ul>${group.items.map(row=>item(row,esc)).join('')}</ul>`}${group.truncated?'<small>展示已限量，原检索范围保留。</small>':''}</section>`).join('')}</section>`;
    if(observation.tool==='commerce_web_read')return `<section class="copilot-public-sources"><header><strong>原文读取</strong>${tag}</header><ul>${(data.items||[]).map(row=>item(row,esc)).join('')}</ul></section>`;
    if(observation.tool==='commerce_intel_search')return `<section class="copilot-local-sources"><header><strong>本机资料 · ${esc(data.total??data.items?.length??0)} 条匹配</strong>${tag}</header>${data.items?.length?`<ul>${data.items.map(row=>item(row,esc)).join('')}</ul>`:'<p>仅检索已采集资料；无匹配不代表公开网络没有相关信息。</p>'}</section>`;
    if(observation.tool==='commerce_intel_item_get')return `<section class="copilot-public-sources"><header><strong>所选情报来源</strong>${tag}</header><ul>${item(data,esc)}</ul></section>`;
    if(observation.tool==='commerce_intel_live_get')return `<section class="copilot-local-sources"><header><strong>监测位置与行情快照</strong>${tag}</header>${Object.entries(data.sources||{}).map(([key,source])=>`<p><strong>${esc(({flights:'航空器',vessels:'船舶',markets:'行情'})[key]||key)}</strong> · 匹配 ${esc(source.matched??0)} 条 · 快照内有效 ${esc(source.fresh_count??0)} 条${source.availability==='expired'?' · 样本已过期':''}<br><small>${esc(source.provider||'')} · 观测 ${esc(source.observed_at_beijing||date(source.observed_at)||'未知')}${source.truncated?' · 明细已限量':''}</small></p>`).join('')}</section>`;
    if(observation.tool==='commerce_current_page')return `<section class="copilot-local-sources"><header><strong>提问时的页面范围</strong>${tag}</header><p>${esc([data.label,data.section_label,data.selection?.name].filter(Boolean).join(' · '))}</p></section>`;
    if(observation.tool==='commerce_live_status')return `<section class="copilot-local-sources"><header><strong>店铺数据状态</strong>${tag}</header><p>订单快照 ${esc(data.orders?.count??0)} 条${data.orders?.fresh?'':' · 待更新'}；库存快照 ${esc(data.stock?.count??0)} 条${data.stock?.fresh?'':' · 待更新'}。</p></section>`;
    return null;
  }
  function group(observations){const rows=[],seen=new Map();for(const observation of observations){const key=observation.sha256?observation.tool+':'+observation.sha256:observation.id;if(seen.has(key)){seen.get(key).references.push(observation.id);continue}const row={...observation,references:[observation.id]};rows.push(row);seen.set(key,row)}return rows}
  function progress(run){const trace=run.trace||[];for(let i=trace.length-1;i>=0;i--){if(trace[i].event==='read_tool')return '正在整理已读取资料…';if(trace[i].event==='tool_started')return ({commerce_web_search:'正在检索公开网络…',commerce_web_read:'正在读取来源原文…',commerce_intel_search:'正在检索本机资料…'})[trace[i].tool]||'正在读取任务所需资料…'}return '正在理解问题并选择处理方式…'}
  function prose(value,esc){
    const inline=value=>esc(value).replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
    let list=false;const rows=[];
    for(const line of String(value||'').split('\n')){
      const bullet=line.match(/^\s*[-*]\s+(.+)$/);
      if(bullet){if(!list){rows.push('<ul>');list=true}rows.push('<li>'+inline(bullet[1])+'</li>');continue}
      if(list){rows.push('</ul>');list=false}
      if(line.trim())rows.push(/^#{1,4}\s+/.test(line)?'<p><strong>'+inline(line.replace(/^#{1,4}\s+/,''))+'</strong></p>':'<p>'+inline(line)+'</p>');
    }
    if(list)rows.push('</ul>');return rows.join('');
  }
  function reportArchive(result,esc){return `<section class="copilot-saved-report"><div class="copilot-formatted">${prose(result.analysis||result.content||'',esc)}</div>${result.source_questions?.length?`<h4>原分析待补充</h4>${result.source_questions.map(q=>`<p>${esc(q)}</p>`).join('')}`:''}${result.source_links?.length?`<h4>原始来源</h4><ul>${result.source_links.map(row=>item(row,esc)).join('')}</ul>`:''}</section>`}
  function archive(result,esc){
    const local=result.model==='windowed_stock_cover'||result.model==='explicit_unit_contribution';
    if(local&&window.CommerceUI?.table){
      const value=(x,unit='')=>typeof x==='number'&&Number.isFinite(x)?String(x)+(unit?' '+unit:''):'未知';
      const restock=result.model==='windowed_stock_cover',currency=result.currency||'';
      const metrics=restock?[['销量速度',value(result.velocity,'件/天')],['库存覆盖',value(result.days_of_cover,'天')],['目标库存',value(result.target_units,'件')],['建议补货',value(result.suggested_qty,'件')]]:
        [['单件总成本',value(result.total_cost,currency)],['单件贡献',value(result.contribution,currency)],['贡献率',value(result.contribution_rate==null?null:result.contribution_rate*100,'%')]];
      const table=window.CommerceUI.table(['指标','本次测算'],metrics.map(([label,n])=>`<tr><td>${esc(label)}</td><td>${esc(n)}</td></tr>`));
      return `<section class="copilot-saved-report"><h3>${restock?'补货测算':'单件贡献测算'}</h3>${table}<p class="muted">${restock?'按所给销量窗口外推，未创建采购单、未修改库存；不保证未来需求。':'按所给币种和费用假设测算，不是真实利润或结算。'}</p>${result.missing?.length?'<p>测算资料仍有缺项，请返回原输入核对，不能把未知记为零。</p>':''}</section>`;
    }
    if(typeof result.analysis==='string'||typeof result.content==='string')return reportArchive(result,esc);
    return null;
  }
  function reviewStatus(run){
    if(run.status!=='awaiting_review'||!run.result?.proposals?.length)return null;
    const actions=run.actions||[],rows=run.result.proposals.map(p=>actions.find(a=>a.proposal_id===p.id));
    if(rows.some(row=>!row?.task_id))return null;
    const receipts=rows.map(row=>row.receipt||{});
    if(receipts.some(r=>r.outcome==='unknown'||!['succeeded','failed','pending'].includes(r.outcome)))return '任务结果待核对';
    if(receipts.some(r=>r.outcome==='failed'))return '本地任务失败';
    if(receipts.every(r=>r.outcome==='succeeded'&&r.status==='completed'&&r.result_sha256))return '本地任务已完成';
    return '本地任务处理中';
  }
  return {render,group,progress,archive,prose,reviewStatus};
})();
