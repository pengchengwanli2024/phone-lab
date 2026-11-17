(() => {
  'use strict';
  window.CommerceSourcing=({api,repaint,onDirty=()=>{},onDraft=()=>false})=>{
    const ui=window.CommerceUI,e=ui.escape;
    const s={caseId:'',epoch:0,fileSequence:0,channels:[],history:[],platform:'yiwugo',query:'',url:'',content:'',format:'json',result:null,busy:false,error:'',keys:new Map()};
    const b=(label,action,attrs={})=>ui.button({label,attrs:{'data-pe-action':'sourcing-'+action,...attrs}});
    const dirty=()=>!!(s.url||s.content||s.result?.draft);
    const clearInputs=()=>{s.fileSequence++;s.url='';s.content='';s.result=null;s.error='';onDirty(false);};
    const channel=()=>s.channels.find(x=>x.id===s.platform);
    const field=(label,key,value)=>ui.field(label,ui.input({id:'sourcing-'+key,'data-pe-sourcing':key,value,disabled:s.busy}));
    const status=v=>({preview_ready:'已取得预览，待核对保存',preview_partial:'已取得部分页面资料，款式/报价待核',needs_export:'读取受限或缺少商品结构',export_required:'需正常导出资料',leads:'已取得公开线索',no_public_leads:'未取得公开线索',search_failed:'检索未完成'}[v]||'尚未实测');
    async function enter(caseId,{force=false,load=true}={}){
      if(s.busy)return false;
      if(caseId!==s.caseId){s.epoch++;s.fileSequence++;Object.assign(s,{caseId,url:'',content:'',result:null,history:[],channels:[],error:''});s.keys.clear();}
      if(!load)return;
      if(s.channels.length&&!force)return;
      const epoch=++s.epoch;
      try{const [c,h]=await Promise.all([api('commerce_product_evidence_sourcing_channels',{case_id:caseId}),api('commerce_product_evidence_sourcing_history',{case_id:caseId})]);if(epoch!==s.epoch)return;s.channels=c.items;s.history=h.items;}
      catch{if(epoch===s.epoch)s.error='渠道读取失败，请刷新；当前输入已保留。';}
      finally{if(epoch===s.epoch)repaint();}
    }
    function view(){
      const c=channel();
      return `<section class="pw-section"><header class="pe-card-heading"><div><h3>多渠道找货</h3><p>批发渠道与零售渠道分别核对；先取得原始资料，再维护报价和成本。</p></div>${b('刷新渠道与回执','refresh',{disabled:s.busy})}</header>${s.error?`<p role="alert" class="pe-notice pe-error">${e(s.error)}</p>`:''}<div class="pe-form-grid">${ui.field('进货渠道',ui.select({id:'sourcing-platform','data-pe-sourcing':'platform',value:s.platform,disabled:s.busy,options:s.channels.map(r=>({value:r.id,label:r.label+' · '+r.kind}))}))}${field('找货关键词','query',s.query)}</div>${b('检索该渠道公开线索','search',{disabled:s.busy||!c?.search_supported})}<p class="pw-meta">${e(c?.status_note||'正在读取渠道目录…')}。正式平台 API：${c?.authorized_api_connected?'已连接':'尚未连接'}。</p><div class="pe-form-grid">${field('准确商品原始链接（HTTPS）','url',s.url)}${ui.field('正常导出资料格式',ui.select({id:'sourcing-format','data-pe-sourcing':'format',value:s.format,disabled:s.busy,options:[{value:'json',label:'单商品 JSON'},{value:'html',label:'含商品元数据的 HTML'}]}))}</div><div class="form-actions">${b('读取公开商品信息','preview-public',{disabled:s.busy||!c?.public_preview_supported})}${b('清空找货输入','discard',{disabled:s.busy})}</div><details><summary>网页受限时导入商品资料</summary><p>在平台正常取得后导入；不会使用账号 Cookie、绕过登录或验证。JSON 可包含 title、model、variant、description、images、offers（price、currency、variant、moq）。</p><label class="ui-field">选择 JSON / HTML 文件<input type="file" data-pe-sourcing="file" accept=".json,.html,.htm,application/json,text/html" ${s.busy?'disabled':''}></label>${ui.field('原始商品资料',`<textarea id="sourcing-content" data-pe-sourcing="content" class="ui-control pe-textarea" maxlength="200000" ${s.busy?'disabled':''}>${e(s.content)}</textarea>`)}${b('解析导出资料并预览','preview-import',{disabled:s.busy})}</details>${s.busy?'<p role="status">正在处理当前渠道，结果返回前请保留此商品。</p>':''}${resultView()}<details><summary>渠道覆盖与实际状态 · ${s.channels.length} 个</summary>${ui.table(['渠道','获取方式','当前商品来源','最近实测'],s.channels.map(r=>`<tr><td>${e(r.label)}<br><small>${e(r.kind)}</small></td><td>${r.public_preview_supported?'公开线索 / 商品元数据 / 资料导入':'正常导出资料 / 待接授权接口'}</td><td>${r.source_count}</td><td>${e(status(r.last_attempt?.status))}</td></tr>`))}</details><details><summary>同商品找货回执 · ${s.history.length} 条</summary>${s.history.map(r=>`<article class="pe-review"><strong>${e(s.channels.find(c=>c.id===r.platform)?.label||r.platform)} · ${e(status(r.status))}</strong><p>${e(r.product?.title||r.query||r.request_url)}</p><small>${e(r.observed_at)}</small>${r.draft||r.items?.length?b('查看这次获取结果','restore',{'data-receipt':r.id}):''}</article>`).join('')||'<p>尚无检索、读取或资料导入回执。</p>'}</details></section>`;
    }
    function resultView(){
      const r=s.result;if(!r)return '';
      return `<section class="pe-review"><h4>${e(status(r.status))}</h4><p>${e(r.reason)}</p>${r.error?`<p class="pw-meta">原回执：${e(r.error)}</p>`:''}${(r.items||[]).map((x,i)=>`<article><strong>${e(x.title)}</strong><p class="pe-note">${e(x.snippet)}</p><p class="pe-note">${e(x.url)}</p>${b('选用此商品链接','choose',{'data-index':i,disabled:s.busy})}</article>`).join('')}${r.product?`<h4>${e(r.product.title)}</h4><p>型号：${e(r.product.model||'待补')} · 款式：${e(r.product.variant||'待锁定')} · 原图链接 ${r.product.images.length} 张</p><p class="pe-note">${e(r.product.description)}</p>${ui.table(['原文选项','标价','起订量','口径'],r.product.offers.map(o=>`<tr><td>${e(o.variant||'尚未锁定')}</td><td>${e(o.price??[o.low_price,o.high_price].filter(v=>v!==null).join('–'))} ${e(o.currency||'币种待核')}</td><td>${e(o.moq||'待核')}</td><td>${o.kind==='price_range_not_variant_quote'?'价格区间，不作为选定款报价':'公开/导出标价，非正式报价'}</td></tr>`))}<details><summary>查看原始图片地址</summary>${r.product.images.map(u=>`<p class="pe-note">${e(u)}</p>`).join('')}</details>${b('带入来源编辑，核对后保存','take',{disabled:s.busy})}<p class="pw-meta">原图留存沿用来源卡片；此处不自动创建报价、不把图片公开展示视为商用许可。</p>`:''}</section>`;
    }
    async function request(action,extra){
      if(s.busy)return;
      const caseId=s.caseId,epoch=s.epoch,args={case_id:caseId,platform:s.platform,...extra};const signature=JSON.stringify([action,args]);
      let key=s.keys.get(signature);if(!key){key=crypto.randomUUID();s.keys.set(signature,key);}
      s.fileSequence++;s.busy=true;s.error='';onDirty(true);repaint();
      try{
        const r=await api('commerce_product_evidence_sourcing_'+action,{...args,idempotency_key:key});
        if(epoch!==s.epoch||caseId!==s.caseId)return;
        s.result=r;
        // A failed follow-up read cannot make the received operation unknown.
        // Retain its original key until both the response and history settle.
        try{
          const h=await api('commerce_product_evidence_sourcing_history',{case_id:caseId});
          if(epoch===s.epoch&&caseId===s.caseId){s.history=h.items;s.keys.delete(signature);}
        }catch{if(epoch===s.epoch&&caseId===s.caseId)s.error='已取得本次结果；回执列表读取失败。输入与结果已保留，可刷新回执或以原请求重试。';}
      }
      catch{if(epoch===s.epoch)s.error='尚未确认处理结果。输入已保留；可先刷新回执，或以原请求重试。';}
      finally{if(epoch===s.epoch){s.busy=false;onDirty(dirty());repaint();}}
    }
    async function action(name,target){
      if(name==='refresh'){await enter(s.caseId,{force:true});return;}
      if(s.busy)return;
      if(name==='discard'){clearInputs();repaint();return;}
      if(name==='search'&&!s.query.trim()){s.error='请填写找货关键词。';repaint();return;}
      if(name.startsWith('preview-')&&(!s.url.trim()||(name==='preview-import'&&!s.content.trim()))){s.error='请填写准确商品链接；导入时还需提供单商品资料。';repaint();return;}
      if(name==='search'){await request('search',{query:s.query});return;}
      if(name.startsWith('preview-')){await request('preview',{url:s.url,mode:name==='preview-import'?'import':'public',format:s.format,content:name==='preview-import'?s.content:''});return;}
      if(name==='choose'){const r=s.result?.items?.[Number(target.dataset.index)];if(r){s.fileSequence++;s.url=r.url;onDirty(true);repaint();}return;}
      if(name==='restore'){const r=s.history.find(x=>x.id===target.dataset.receipt);if(r){s.fileSequence++;s.result=r;s.platform=r.platform;s.url=r.request_url;onDirty(true);repaint();}return;}
      if(name==='take'&&s.result?.draft){if(onDraft(JSON.parse(JSON.stringify(s.result.draft)))){s.fileSequence++;s.url='';s.content='';s.result=null;repaint();}return;}
    }
    async function input(target){
      const key=target.dataset.peSourcing;
      if(s.busy)return;
      if(key==='file'){
        const file=target.files?.[0],epoch=s.epoch,caseId=s.caseId,sequence=++s.fileSequence;
        const current=()=>epoch===s.epoch&&caseId===s.caseId&&sequence===s.fileSequence;
        if(!file)return;
        if(file.size>200000){s.error='资料文件请控制在200KB以内。';repaint();return;}
        try{const content=await file.text();if(!current())return;s.content=content;s.format=/\.html?$/i.test(file.name)?'html':'json';onDirty(true);repaint();}catch{if(current()){s.error='未能读取资料文件。';repaint();}}return;
      }
      if(!['query','platform','url','format','content'].includes(key))return;
      if(key==='platform'&&dirty()){s.error='请先带入保存或清空当前商品资料，再切换渠道。';repaint();return;}
      if(['platform','format','content'].includes(key))s.fileSequence++;
      s[key]=target.value;if(key==='platform')s.result=null;onDirty(dirty());if(['platform','format'].includes(key))repaint();
    }
    return {enter,view,action,input,hasUnsavedChanges:dirty,hasActiveMutation:()=>s.busy,discard:clearInputs,dispose(){s.epoch++;s.fileSequence++;}};
  };
})();
