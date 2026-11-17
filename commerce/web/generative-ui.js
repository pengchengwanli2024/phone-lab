/* Typed business views shared by browser/iframe; data is always escaped. */
(function(){
  // Transient display state only. Business images and version checks stay in
  // the original backend; repaint never loses a preview of the same version.
  const images=new Map();let imageBytes=0;
  const imageKey=a=>JSON.stringify([a.case_id,a.platform,a.store_ref,a.market,a.expected_binding_sha256,a.index]);
  function rememberImage(args,url){
    const key=imageKey(args);if(images.has(key)){imageBytes-=images.get(key).length;images.delete(key)}
    images.set(key,url);imageBytes+=url.length;
    while(images.size>12||imageBytes>16*1024*1024){const first=images.keys().next().value;imageBytes-=images.get(first).length;images.delete(first)}
  }
  const kinds=new Set(['Evidence','QuoteComparison','DeliveryReview','ListingReview','SkillReadiness','CostSummary','FieldDiff','Questions','ProposalReview','Receipt']);
  const labels={HOLD:'待补资料',BLOCKED:'受阻',PASS:'检查通过',FAIL:'检查不符',READY_FOR_SELECTION:'可审阅选择',EXPIRED:'已过期',needs_inputs:'待补资料',needs_mode:'待选模式',blocked:'受阻',source_unavailable:'来源不可用',draft_inputs_ready:'草稿输入齐备',local_check_available:'可请求本机检查',stale:'来源已变化',ready_for_local_review:'待本地审阅',local_review_recorded:'已记录本地审阅',review_expired_or_superseded:'审阅已过期或被替代',rejected:'已退回'};
  function render(surface,options={}){
    const ui=options.ui||window.CommerceUI;
    if(!ui||surface?.schema!=='commerce-generative-surface-v1'||surface.catalog_version!==1||!Array.isArray(surface.components)||surface.components.length>12)return null;
    const esc=ui.escape,value=v=>v==null||v===''?'待补充':typeof v==='object'?JSON.stringify(v):String(v),covered={answer:false,questions:new Set(),proposals:new Set()},seen=new Set();
    const pairs=(rows,prefix='')=>`<dl>${rows.map(([key,label,v])=>`<div data-field-id="${esc(prefix+key)}"><dt>${esc(label)}</dt><dd>${esc(value(v))}</dd></div>`).join('')}</dl>`;
    const list=items=>items?.length?`<ul>${items.slice(0,30).map(v=>`<li>${esc(value(v))}</li>`).join('')}</ul>${items.length>30?'<p class="muted">展示前30项，完整内容请核对原记录。</p>':''}`:'<p class="muted">暂无记录</p>';
    let html='';
    for(const c of surface.components){
      if(!c||!kinds.has(c.component)||typeof c.id!=='string'||!/^[a-zA-Z0-9_-]{1,100}$/.test(c.id)||seen.has(c.id)||!c.data||typeof c.data!=='object')return null;
      seen.add(c.id);const d=c.data,b=c.binding||{};let body='';
      if(c.component==='Evidence')body=options.evidence?.(c.observation)||ui.evidence({title:c.label,quote:value(d),sha256:b.observation_sha256,verification:'not_independently_verified'});
      else if(c.component==='QuoteComparison'){
        const rows=d.items||d.quotes?.items||[];
        body=rows.length?`<div class="ui-table-wrap" role="region" tabindex="0" aria-label="供应报价对照">${ui.table(['报价 / 版本','币种','单价','起订量','下单件数','商品小计','状态'],rows.slice(0,20).map(q=>{
          const f=q.fields||q,id='supply_quote:'+q.quote_id+':';
          return `<tr><th scope="row">${esc(value(q.supplier||q.quote_id))} · ${esc(value(q.revision))}</th><td>${esc(value(f.currency))}</td><td data-field-id="${esc(id+'unit_price')}">${esc(value(q.unit_price??f.purchase_cost))}</td><td>${esc(value(f.moq))}</td><td data-field-id="${esc(id+'order_units')}">${esc(q.order_units==null?'待明确数量':String(q.order_units)+(q.extra_units>0?'（多'+q.extra_units+'件）':''))}</td><td>${esc(value(q.goods_subtotal))}</td><td>${esc(labels[q.status]||q.status||'未知')}</td></tr>`;
        }))}</div>`:'<p>当前商品没有已记录报价。</p>';
        body+=d.quantity?`<p>比较需求：${esc(d.quantity)} 件，按起订量与整包数量向上取整。小计仅含报价商品；运费、税费及平台费用另行核对。</p>`:'<p class="muted">未提供明确采购数量，未推算订单件数或总价。</p>';
        if(rows.length>20||d.quotes?.truncated)body+='<p class="muted">报价已限量，完整列表请在对应商品工作区核对。</p>';
      }else if(c.component==='DeliveryReview'){
        const v=d.delivery_review||d;
        const checks={facts:'产品事实',translation:'目标语言与翻译',media_rights:'素材使用权',platform_rules:'平台规则与资质依据',images:'产品图片',content:'上架内容',draft:'内容草稿',cost:'成本测算',source:'产品来源'};
        body=pairs([['status','交付状态',labels[v.status]||'待核对'],['professional_gate','负责人核查门禁',labels[v.professional_gate]||'待核对'],['package_sha256','交付包版本',v.package_sha256]],'delivery:')+list([...(v.automatic_missing||[]),...(v.pending_checks||[])].map(k=>checks[k]||'待核对检查项'))+`<small class="muted">检查结果与经营负责人签收分别记录；不代表独立认证或已上架。</small>`;
      }else if(c.component==='ListingReview'){
        const p=d.product||{},target=d.target||{};
        body=pairs([['sku','SKU',p.sku],['title','商品标题',p.title],['price','售价',p.price==null||p.price===''?null:value(p.price)+' '+value(p.currency)],['quantity','计划数量',p.quantity],['category_id','目标类目',p.category_id],['image_count','产品图片',p.image_count==null?null:p.image_count+' 张']], 'listing:')+`<p class="copilot-prose">${esc(p.description||'产品描述待补充')}</p>`;
        if(p.description_truncated)body+='<p class="muted">长描述已限量，完整内容请在原方案核对。</p>';
        if(p.attributes?.length)body+=pairs(p.attributes.map((a,i)=>[String(i),a.name,a.value]),'listing:attribute:');
        if(p.publication)body+=pairs([['depth','包装深度',p.publication.depth],['width','包装宽度',p.publication.width],['height','包装高度',p.publication.height],['dimension_unit','尺寸单位',p.publication.dimension_unit],['weight','含包装重量',p.publication.weight],['weight_unit','重量单位',p.publication.weight_unit],['vat','适用税率',p.publication.vat]],'listing:publication:');
        body+=list((d.checks||[]).filter(x=>x.status!=='prepared').map(x=>x.label||x.id));
        const image=d.image_binding;
        if(image&&!surface.provisional){
          for(let index=0;index<Math.min(20,image.count);index++){
            const args={...image.target,expected_binding_sha256:image.expected_binding_sha256,index},url=images.get(imageKey(args));
            body+=`<div class="copilot-product-image"><button type="button" class="ui-button" data-generative-image="${esc(JSON.stringify(args))}">${url?'重新读取':'读取产品'}图片 ${index+1}</button><div role="status">${url?`<img src="${esc(url)}" alt="当前保存方案产品图片 ${index+1}" style="max-width:100%;max-height:280px">`:''}</div></div>`;
          }
        }else body+=`<p class="muted">${surface.provisional?'生成预览，尚未开放操作。':'图片内容请在准确保存方案的完整审阅页核对。'}</p>`;
        body+=`<small class="muted">${esc([target.platform,target.store_ref,target.market].filter(Boolean).join(' / '))} · 修订 ${esc(value(d.revision))}${d.stale?' · 来源已变化':''}。本卡片不批准或发布商品。</small>`;
      }else if(c.component==='SkillReadiness'){
        const fields={facts_with_source:'带来源的产品事实','scope.marketplace':'目标平台','scope.market':'目标市场',input:'技能输入',mode_id:'执行模式',references:'参考资料'};
        body=pairs([['state','当前条件',labels[d.state]||d.state],['source_intact','来源完整性',d.source_intact===true?'匹配':'待核对'],['account_entitlement','账号权限','未验证'],['offline_check','本机检查',d.offline_check?.can_request?'可明确请求检查':'条件未齐备'],['model_runtime','模型运行条件',d.model_draft?.runtime_status==='not_checked'?'未核对':'以原技能检查为准'],['authorization','外部执行授权',d.external_execution?.authorized===true?'以宿主逐项校验为准':'未授权']], 'skill:')+list([...(d.missing_fields||[]).map(k=>fields[k]||k),...(d.issues||[])]);
        if(d.external_prerequisites?.length)body+='<h4>外部前置条件</h4>'+list(d.external_prerequisites);
        body+='<p class="muted">输入齐备与可执行分开核对；未请求模型、外部工具或付费任务。</p>';
      }else if(c.component==='CostSummary'){
        const v=d.calculation||d;
        const names=d.cost_field_labels||{},rate=typeof v.contribution_rate==='number'?String(Math.round(v.contribution_rate*10000)/100)+'%':null;
        body=pairs([['status','测算状态',v.status==='CALCULATED'?'已测算，待核对':v.status==='HOLD'?'资料不足':'待核对'],['price',names.price||'单件售价',v.price],['total_cost','单件总成本',v.total_cost],['contribution','单件贡献',v.contribution],['contribution_rate','贡献率',rate],['currency',names.currency||'测算币种',v.currency]],'unit_economics:');
        if(v.cost_breakdown)body+=pairs(Object.entries(v.cost_breakdown).map(([key,amount])=>['cost_breakdown.'+key,({commission:'平台佣金',payment:'支付费用',return:'退货预留',ad:'广告费用'})[key]||names[key]||'费用分项',amount]),'unit_economics:');
        if(v.missing?.length)body+=list(v.missing.map(k=>names[k]||'待补参数'));
        if(v.stale)body+='<p>来源已变化，请在成本工作区重新测算。</p>';
        body+='<p class="muted">金额使用所列币种，缺失参数未补猜；该测算不代表结算或会计结果。</p>';
      }else if(c.component==='FieldDiff'){
        const before=d.data?.input||{};body=ui.fieldDiff({beforeLabel:'已读取值',afterLabel:'页面输入（未核实）',rows:Object.entries(d.ui_input||{}).slice(0,32).map(([key,after])=>({key,label:key,before:before[key],after}))})+list(d.ui_errors||[]);
      }else if(c.component==='Questions'){
        body=list(d.items);if(!surface.provisional){(d.items||[]).forEach(q=>covered.questions.add(q));body+=options.reply?.()||'';}
      }else if(c.component==='ProposalReview'){
        if(surface.provisional)body='<p>建议生成中，待最终校验后逐项审阅。</p>';
        else{body=(d.items||[]).map(p=>options.proposal?.(p)||`<p>${esc(p.reason||p.operation)}</p>`).join('');if(options.proposal)(d.items||[]).forEach(p=>covered.proposals.add(p.id));}
      }else if(c.component==='Receipt')body=(d.items||[]).length?(d.items||[]).map(a=>options.receipt?.(a)||ui.receipt(a.receipt)).join(''):'<p>尚无已提交的本地任务回执。</p>';
      if(!surface.provisional&&options.workspace&&(d.case_id||d.target?.case_id))body+=options.workspace(c);
      html+=`<section class="copilot-card copilot-generative-card" data-component-id="${esc(c.id)}" data-component-kind="${esc(c.component)}"><h3>${esc(c.label)}</h3>${body}<small class="muted">引用 ${esc(b.reference||'')} · ${surface.provisional?'生成预览，未完成校验':'本轮读取快照'}</small></section>`;
    }
    return {html,covered,captions:[]};
  }
  async function image(event,api){
    const button=event.target.closest?.('[data-generative-image]');if(!button||button.disabled)return false;
    const box=button.parentElement,feedback=box.querySelector('[role="status"]');button.disabled=true;feedback.textContent='正在读取准确版本图片…';
    try{
      const args=JSON.parse(button.dataset.generativeImage),data=await api('commerce_owner_review_image',args);
      if(!/^image\/(png|jpeg|webp)$/.test(data.mime)||typeof data.content_base64!=='string'||!/^[A-Za-z0-9+/=]+$/.test(data.content_base64)||data.content_base64.length>12000000)throw Error('invalid_image');
      const picture=button.ownerDocument.createElement('img');picture.src='data:'+data.mime+';base64,'+data.content_base64;rememberImage(args,picture.src);picture.alt='当前保存方案产品图片 '+(args.index+1);picture.style.maxWidth='100%';picture.style.maxHeight='280px';feedback.replaceChildren(picture);button.textContent='重新读取图片 '+(args.index+1);
    }catch{feedback.textContent='图片未读到，可能版本已变化；请刷新原方案后重试。';}
    finally{button.disabled=false;}
    return true;
  }
  window.CommerceGenerativeUI={render,image,components:[...kinds]};
})();
