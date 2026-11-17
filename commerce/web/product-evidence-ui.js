(() => {
  'use strict';
  const SOURCE_KEYS=['kind','platform','label','url','model','variant','observed_at','valid_until','review_state','verification_note','rights_status','rights_evidence','notes','quote_ids','images','metrics','archived'];
  const PROPOSAL_KEYS=['customer_need','selection_reason','differentiation','risks','currency','trial_quantity','trial_budget','max_loss','min_contribution_rate','conditions'];
  const kinds={supplier:'货源',competitor:'竞品',market:'市场数据',document:'样品与文件'};
  const states={unreviewed:'待核对',checked:'已本地核对',conflict:'信息冲突',rejected:'不采信'};
  const rights={unknown:'权利待确认',reference_only:'仅作参考',authorized:'已记录商用授权',self_owned:'自有素材'};
  const decisions={hold:'待补证',reject:'暂不进入',trial:'可有限试销'};
  const metricLabels={price:'竞品价格',currency:'原币',sales_units:'有来源的销量',window_days:'数据窗口（天）',searches:'搜索量',rating:'评分',review_count:'评论数'};
  const stamp=()=>new Date().toISOString();
  const clone=v=>JSON.parse(JSON.stringify(v));
  const isUrl=v=>{try{const u=new URL(v);return u.protocol==='https:'&&!u.username&&!u.password;}catch{return false;}};
  window.CommerceProductEvidence=({api,repaint,onNavigate=()=>{},onDirty=()=>{},onImagePreview=()=>{},formatProjectLabel=p=>p.name||'创意项目',formatQuoteStatus=()=> '待核对'})=>{
    const ui=window.CommerceUI,esc=ui.escape;
    const s={caseId:'',epoch:0,data:null,error:'',notice:'',loading:false,busy:false,uploading:false,section:'all',edit:null,history:null,actor:'当前操作者',showArchived:false,images:new Map(),loadingImages:new Set()};
    const button=(label,action,attrs={},primary=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{'data-pe-action':action,...attrs}});
    const pick=(label,key,value,options,attrs={})=>ui.field(label,ui.select({id:'pe-'+key.replaceAll('.','-'),'data-pe-field':key,value,options:Object.entries(options).map(([value,label])=>({value,label})),...attrs}));
    const input=(label,key,value,type='text',attrs={})=>ui.field(label,ui.input({id:'pe-'+key.replaceAll('.','-'),'data-pe-field':key,value:value??'',type,...attrs}));
    const area=(label,key,value,attrs={})=>ui.field(label,`<textarea id="pe-${esc(key.replaceAll('.','-'))}" data-pe-field="${esc(key)}" class="ui-control pe-textarea" ${attrs.disabled?'disabled':''}>${esc(value??'')}</textarea>`);
    const link=(url,label,row=null,index=-1)=>isUrl(url)?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" ${row?`data-pe-action="origin-open" data-entry="${row.id}" data-source-sha="${row.sha256}" data-index="${index}"`:""}>${esc(label)}</a>`:`<span>${esc(label||'原始链接待补')}</span>`;
    const when=v=>{const d=new Date(v);return Number.isFinite(d.getTime())?d.toLocaleString():v||'未记录';};
    const money=(v,c)=>v==null?'待补':esc(v)+' '+esc(c||'币种待补');
    const statusLabel=code=>ui.status?.(code)?.label||({queued:'等待执行',running:'执行中',completed:'已完成',succeeded:'已完成',failed:'失败',cancelled:'已取消',interrupted:'已中断'}[code]||'状态待核对');
    const assetLabel=kind=>kind.startsWith('generated')?'AI生成 / 待审阅':({reference_image:'参考图片',reference_video:'参考视频',source_video:'原始视频',video:'视频',image:'图片',document:'文件',audio:'音频',subtitle:'字幕'}[kind]||'素材');
    const executionLabel=row=>({analysis:'业务分析',analyze:'原片分析'}[row.title]||row.title||'执行记录');
    const codeMessage=error=>{
      const code=error?.message||String(error);
      if(/changed|conflict/.test(code))return '资料已变化，请核对当前版本；本次输入已保留。';
      if(code==='evidence_trial_not_ready')return '试销依据或约束尚未满足，请先补齐缺项。';
      if(/reference/.test(code))return '引用不属于当前商品或当前版本，请重新选择依据。';
      if(/rights/.test(code))return '记录商用或自有素材时，需要填写授权依据。';
      if(/invalid_url/.test(code))return '请填写与所选平台匹配的公开HTTPS商品链接，去除账号或令牌参数。';
      if(code==='evidence_invalid_date')return '请填写含时区的有效日期，并核对截止时间。';
      if(code==='evidence_future_observation')return '采集时间晚于当前时间，请核对后重新保存。';
      if(/image/.test(code))return '原图未完成读取或上传，请核对文件、来源与当前版本。';
      if(/^evidence_|^invalid_/.test(code))return '本次资料未保存，请核对必填项、日期和数值；输入已保留。';
      return '保存结果尚未确认，请先核对保存结果；不会自动重复创建。';
    };
    const sourcing=window.CommerceSourcing?.({api,repaint,onDirty:()=>onDirty(dirty()),onDraft(payload){if(s.edit||s.busy)return false;const row=s.data.sources.find(r=>!r.archived&&r.platform===payload.platform&&r.url===payload.url);if(row){payload.quote_ids=clone(row.quote_ids);const urls=new Set(row.images.map(i=>i.url));payload.images=[...clone(row.images),...payload.images.filter(i=>!urls.has(i.url))].slice(0,12);}s.edit={kind:'source',entryId:row?.id||'',revision:row?.revision||0,payload,base:s.data.dossier_sha256,key:crypto.randomUUID(),dirty:true,submitted:null,original:row?Object.fromEntries(SOURCE_KEYS.map(k=>[k,clone(row[k])])):clone(payload)};s.section='all';s.notice='已带入渠道商品资料，请核对款式、原图与价格口径后保存来源。';onDirty(true);return true;}});
    const dirty=()=>!!s.edit?.dirty||!!s.edit?.submitted||s.uploading||s.busy||!!sourcing?.hasUnsavedChanges()||!!sourcing?.hasActiveMutation();
    function changed(paint=false){if(s.edit)s.edit.dirty=true;onDirty(dirty());if(paint)repaint();}
    function clearImages(){s.images.clear();s.loadingImages.clear();}
    async function enter(caseId,{force=false}={}){
      if(caseId!==s.caseId&&dirty()){s.error='当前商品有未保存输入，请先保存或明确放弃。';repaint();return false;}
      if(caseId===s.caseId&&s.data&&!force)return true;
      if(caseId!==s.caseId){clearImages();s.edit=null;s.history=null;s.data=null;s.caseId=caseId;s.error='';if(sourcing)void sourcing.enter(caseId,{load:false});}
      const epoch=++s.epoch;s.loading=true;repaint();
      try{const d=await api('commerce_product_evidence_get',{case_id:caseId});if(epoch!==s.epoch||caseId!==s.caseId)return false;s.data=d;s.error='';if(s.section==='channels')await sourcing?.enter(caseId,{force:true});return epoch===s.epoch;}
      catch(error){if(epoch===s.epoch)s.error=codeMessage(error);return false;}
      finally{if(epoch===s.epoch){s.loading=false;repaint();}}
    }
    function sourceById(id){return s.data?.sources.find(r=>r.id===id);}
    function sourceEditor(id){
      if(dirty()){s.error='请先保存或放弃当前编辑。';repaint();return;}
      const row=id?sourceById(id):null;
      const payload=row?Object.fromEntries(SOURCE_KEYS.map(k=>[k,clone(row[k])])):{kind:'supplier',platform:'1688',label:'',url:'',model:'',variant:'',observed_at:stamp(),valid_until:'',review_state:'unreviewed',verification_note:'',rights_status:'unknown',rights_evidence:'',notes:'',quote_ids:[],images:[],metrics:{},archived:false};
      s.edit={kind:'source',entryId:id||'',revision:row?.revision||0,payload,base:s.data.dossier_sha256,key:crypto.randomUUID(),dirty:false,submitted:null,original:clone(payload)};s.error='';s.notice='';s.section='all';repaint();
    }
    function proposalEditor(){
      if(dirty()){s.error='请先保存或放弃当前编辑。';repaint();return;}
      s.edit={kind:'proposal',payload:Object.fromEntries(PROPOSAL_KEYS.map(k=>[k,s.data.proposal[k]??(k==='currency'?'':null)])),revision:s.data.proposal.revision,base:s.data.dossier_sha256,key:crypto.randomUUID(),dirty:false,submitted:null};s.edit.original=clone(s.edit.payload);s.error='';s.notice='';repaint();
    }
    function reviewEditor(){
      if(dirty()){s.error='请先保存或放弃当前编辑。';repaint();return;}
      s.edit={kind:'review',payload:{decision:'hold',reason:'',checks:Object.fromEntries(Object.keys(s.data.criteria).map(k=>[k,{status:'pending',note:'资料待核对',evidence_refs:[]}]))},base:s.data.dossier_sha256,key:crypto.randomUUID(),dirty:false,submitted:null};s.error='';s.notice='';s.section='reviews';repaint();
    }

    function currentPayload(e){
      if(e.kind==='source'){const row=sourceById(e.entryId);return row?Object.fromEntries(SOURCE_KEYS.map(k=>[k,clone(row[k])])):null;}
      if(e.kind==='proposal')return Object.fromEntries(PROPOSAL_KEYS.map(k=>[k,clone(s.data.proposal[k])]));
      return null;
    }
    function displayValue(v){
      if(v==null||v==='')return '未填写';
      if(Array.isArray(v))return v.map(x=>typeof x==='object'?(x.label||x.url||x.media_id):x).join('；')||'无';
      if(typeof v==='object')return Object.entries(v).map(([k,x])=>(metricLabels[k]||k)+'：'+(x??'未知')).join('；');
      if(typeof v==='boolean')return v?'是':'否';
      return String(v);
    }
    function conflictView(e){
      if(!e||e.submitted||e.base===s.data.dossier_sha256)return '';
      const current=currentPayload(e),original=e.original||{};
      const labels={kind:'来源类型',platform:'平台',label:'名称',url:'原始链接',model:'型号',variant:'款式',observed_at:'采集时间',valid_until:'有效至',review_state:'核对状态',verification_note:'核对依据',rights_status:'素材权利',rights_evidence:'授权依据',notes:'原文与备注',quote_ids:'报价关联',images:'图片引用',metrics:'市场数据',archived:'归档',customer_need:'客户需求',selection_reason:'选择理由',differentiation:'差异化',risks:'风险',currency:'币种',trial_quantity:'数量',trial_budget:'总投入',max_loss:'最大损失',min_contribution_rate:'最低贡献率',conditions:'进入条件'};
      const keys=current?Object.keys(e.payload).filter(k=>JSON.stringify(original[k])!==JSON.stringify(current[k])||JSON.stringify(original[k])!==JSON.stringify(e.payload[k])):[];
      return `<section class="pe-notice pe-conflict"><h4>当前资料已变化，请核对差异</h4><p>${e.kind==='review'?'继续编辑会把六项判断重置为待补证，并移除已失效的引用；原意见保留。':'继续编辑会保留你的修改，使用后台未被你修改的新字段。双方都改过的字段以你的输入为准；图片与报价关联按增删合并，请核对后再保存。'}</p>${keys.length?ui.table(['字段','编辑起点','后台当前值','你的输入'],keys.map(k=>`<tr><th>${esc(labels[k]||k)}</th><td>${esc(displayValue(original[k]))}</td><td>${esc(displayValue(current[k]))}</td><td>${esc(displayValue(e.payload[k]))}</td></tr>`)):'<p>关联证据版本已更新，当前输入仍然保留。</p>'}${button('核对差异后继续编辑','rebase',{disabled:s.busy})}</section>`;
    }
    function mergeValue(original,draft,current){
      if(JSON.stringify(original)===JSON.stringify(draft))return clone(current);
      if(Array.isArray(original)&&Array.isArray(draft)&&Array.isArray(current)){
        const id=x=>typeof x==='object'?(x.media_id||x.url)+':'+x.role:String(x);
        const base=new Set(original.map(id)),wanted=new Map(draft.map(x=>[id(x),x]));
        const merged=current.filter(x=>!base.has(id(x))||wanted.has(id(x))).map(x=>wanted.get(id(x))||x);
        const seen=new Set(merged.map(id));for(const x of draft)if(!base.has(id(x))&&!seen.has(id(x))){merged.push(x);seen.add(id(x));}
        return clone(merged);
      }
      if(original&&draft&&current&&typeof original==='object'&&typeof draft==='object'&&typeof current==='object'&&!Array.isArray(original)&&!Array.isArray(draft)&&!Array.isArray(current)){
        const result={...current};for(const k of new Set([...Object.keys(original),...Object.keys(draft)])){if(!Object.hasOwn(draft,k)){if(Object.hasOwn(original,k))delete result[k];}else if(!Object.hasOwn(original,k))result[k]=clone(draft[k]);else result[k]=mergeValue(original[k],draft[k],current[k]??null);}return result;
      }
      return clone(draft);
    }
    function rebase(){
      const e=s.edit;if(!e||s.busy||e.submitted)return;
      const current=currentPayload(e);
      if(e.kind==='review'){
        const valid=new Set(s.data.available_evidence.map(x=>x.id));
        for(const row of Object.values(e.payload.checks)){row.status='pending';row.evidence_refs=row.evidence_refs.filter(x=>valid.has(x));}
      }else if(current){
        e.payload=mergeValue(e.original||{},e.payload,current);e.original=clone(current);
        e.revision=e.kind==='source'?sourceById(e.entryId).revision:s.data.proposal.revision;
      }else if(e.kind==='source'&&e.entryId){s.error='当前来源未读到，请重新核对来源范围；输入保留。';repaint();return;}
      e.base=s.data.dossier_sha256;e.key=crypto.randomUUID();e.dirty=true;s.error='';s.notice='已按核对结果继续编辑，请检查字段和引用后保存。';onDirty(dirty());repaint();
    }
    function editView(){
      const e=s.edit;if(!e)return '';
      const disabled=s.busy||!!e.submitted,p=e.payload;let body='';
      if(e.kind==='source'){
        const platforms=Object.fromEntries(s.data.platforms.map(p=>[p.id,p.label]));
        body=`<div class="pe-form-grid">${pick('来源类型','kind',p.kind,kinds,{disabled})}${pick('来源平台','platform',p.platform,platforms,{disabled})}${input('供应商或商品名称','label',p.label,'text',{disabled,maxlength:1000})}${input('原始商品链接','url',p.url,'url',{disabled})}${input('型号','model',p.model,'text',{disabled})}${input('款式与配件','variant',p.variant,'text',{disabled})}${input('采集时间（含时区）','observed_at',p.observed_at,'text',{disabled})}${input('资料有效至（可留空）','valid_until',p.valid_until,'text',{disabled})}${pick('资料核对','review_state',p.review_state,states,{disabled})}${pick('图片与资料权利','rights_status',p.rights_status,rights,{disabled})}</div>${area('核对依据与冲突','verification_note',p.verification_note,{disabled})}${area('授权依据或文件说明','rights_evidence',p.rights_evidence,{disabled})}${area('原文、规格、包装和备注','notes',p.notes,{disabled})}`;
        if(p.kind!=='supplier')body+=`<fieldset class="pe-fieldset"><legend>有来源的市场数据，缺项保持空白</legend><div class="pe-form-grid">${Object.entries(metricLabels).map(([k,label])=>input(label,'metrics.'+k,p.metrics[k],k==='currency'?'text':'number',{disabled,min:0,step:'any'})).join('')}</div></fieldset>`;
        if(p.kind==='supplier')body+=`<fieldset class="pe-fieldset"><legend>关联原报价记录</legend>${s.data.quotes.length?s.data.quotes.map(q=>`<label class="pe-check"><input type="checkbox" data-pe-quote="${esc(q.quote_id)}" ${p.quote_ids.includes(q.quote_id)?'checked':''} ${disabled?'disabled':''}>${esc(q.fields.supplier||q.quote_id)} · ${money(q.fields.purchase_cost,q.fields.currency)}</label>`).join(''):'<p>尚无原报价。保存来源后可进入“管理报价”补充。</p>'}</fieldset>`;
        body+=`${area('原始图片地址（每行一个，上传图片会保留）','image_links',p.images.filter(i=>!i.media_id).map(i=>i.url).join('\n'),{disabled})}${p.images.filter(i=>i.media_id).map((i,n)=>`<p>${esc(i.label||'已存原图')} ${button('移除本版本引用','image-remove',{'data-index':p.images.indexOf(i),disabled})}</p>`).join('')}<label class="pe-check"><input type="checkbox" data-pe-field="archived" ${p.archived?'checked':''} ${disabled?'disabled':''}>归档此来源，保留历史记录</label>`;
      }else if(e.kind==='proposal'){
        body=`${area('目标客户与需求','customer_need',p.customer_need,{disabled})}${area('为什么选择这个商品','selection_reason',p.selection_reason,{disabled})}${area('能兑现的差异化','differentiation',p.differentiation,{disabled})}${area('风险与放弃条件','risks',p.risks,{disabled})}<div class="pe-form-grid">${input('经营币种','currency',p.currency,'text',{disabled})}${input('首测数量','trial_quantity',p.trial_quantity,'number',{disabled,min:1})}${input('总投入上限','trial_budget',p.trial_budget,'number',{disabled,min:0,step:'any'})}${input('最大损失上限','max_loss',p.max_loss,'number',{disabled,min:0,step:'any'})}${input('最低贡献率（%）','min_contribution_rate',p.min_contribution_rate==null?'':p.min_contribution_rate*100,'number',{disabled,min:0,max:100,step:'any'})}</div>${area('进入条件与复查安排','conditions',p.conditions,{disabled})}`;
      }else{
        body=`${pick('本次结论','review.decision',p.decision,decisions,{disabled})}${area('总体理由与下一步','review.reason',p.reason,{disabled})}${Object.entries(s.data.criteria).map(([key,label])=>`<fieldset class="pe-fieldset"><legend>${esc(label)}</legend>${pick('判断','checks.'+key+'.status',p.checks[key].status,{pending:'待补证',pass:'本地核对通过',fail:'不满足'},{disabled})}${area('依据与理由','checks.'+key+'.note',p.checks[key].note,{disabled})}<details><summary>引用当前版本证据 · ${p.checks[key].evidence_refs.length}条</summary><div class="pe-evidence-options">${s.data.available_evidence.map(r=>`<label class="pe-check"><input type="checkbox" data-pe-check="${key}" data-ref="${esc(r.id)}" ${p.checks[key].evidence_refs.includes(r.id)?'checked':''} ${disabled?'disabled':''}>${esc(r.label)}</label>`).join('')||'<p>先补充来源资料。</p>'}</div></details></fieldset>`).join('')}<p class="pw-meta">评审只记录本地选品结论；采购、投放与发布仍走原授权和核查。</p>`;
      }
      return `<section class="pw-section pe-editor" aria-label="${esc(e.kind==='source'?'来源编辑':e.kind==='proposal'?'选品理由编辑':'选品评审编辑')}"><h3>${e.kind==='source'?(e.entryId?'维护原始来源':'新增原始来源'):e.kind==='proposal'?'维护选品理由与约束':'记录正式选品评审'}</h3>${conflictView(e)}${body}${input('记录人','actor',s.actor,'text',{disabled})}<div class="pw-form-actions">${e.submitted?button('核对保存结果','reconcile',{},true)+button('使用原请求安全重试','retry',{disabled:s.busy}):button('保存'+(e.kind==='source'?'来源':e.kind==='proposal'?'理由与约束':'评审'),e.kind+'-save',{disabled:s.busy},true)}${button('放弃未保存修改','discard',{disabled:s.busy})}</div></section>`;
    }

    function historyView(){
      const row=s.history;if(!row)return '';
      return `<section class="pw-section pe-history-view"><header class="pe-card-heading"><div><h3>${esc(row.label)} · 历史v${row.revision}</h3><p>${esc(row.actor)} · ${esc(when(row.saved_at))}</p></div>${button('关闭历史版本','history-close')}</header><p class="pw-meta">只读查看原始版本，不覆盖当前来源。</p><p>${link(row.url,'该版本原始链接',row)}</p><p>${esc([row.model,row.variant].filter(Boolean).join(' / '))}</p><p class="pe-note">${esc(row.notes)}</p><p>${esc(row.verification_note)}</p>${imagesView(row,true)}<small>SHA-256 ${esc(row.sha256)}</small></section>`;
    }
    function imagePreview(row,index,src){return `<button class="pe-image-preview" type="button" data-pe-action="image-preview" data-entry="${row.id}" data-source-sha="${row.sha256}" data-index="${index}" aria-label="放大原图：${esc(row.images[index].label||'来源图片')}"><img src="${esc(src)}" alt="${esc(row.images[index].label||'来源图片')}" loading="lazy"></button>`;}
    function imagesView(row,historical=false){
      if(!row.images.length)return '<p class="pe-missing">原始图片尚未取得。</p>';
      return `<div class="pe-images">${row.images.map((image,index)=>{
        const key=row.id+':'+row.sha256+':'+index,blob=s.images.get(key);
        return `<figure>${blob?imagePreview(row,index,blob):image.media_id?`<div class="pe-image-placeholder" data-pe-image="${esc(key)}" data-entry="${row.id}" data-source-sha="${row.sha256}" data-index="${index}">原图读取中…</div>`:`<div class="pe-image-placeholder">尚未留存图片<br>${historical?'':button('读取并留存原图','image-capture',{'data-entry':row.id,'data-index':index,disabled:s.busy||dirty()})}</div>`}<figcaption>${ui.badge(image.role==='generated'?'AI生成':image.role==='document'?'文件图片':'原始参考图',image.role==='generated'?'blue':'gray')}<span>${esc(image.label||'来源图片')}</span>${image.url?link(image.url,'图片原始地址',row,index):''}</figcaption></figure>`;
      }).join('')}</div>`;
    }
    function sourceCard(row){
      const quoteRows=s.data.quotes.filter(q=>row.quote_ids.includes(q.quote_id));
      return `<article class="pw-section pe-source-card" data-pe-source="${row.id}"><header class="pe-card-heading"><div><h3>${esc(row.label)}</h3><p>${esc(kinds[row.kind])} · ${esc(s.data.platforms.find(p=>p.id===row.platform)?.label||row.platform)} · v${row.revision}</p></div><div>${ui.badge(row.archived?'已归档':states[row.review_state],row.review_state==='conflict'?'danger':'gray')}${!row.fresh||!row.recent?ui.badge('日期待复核','warning'):''}</div></header><p>${link(row.url,'打开原始商品或资料',row)}</p><dl class="pe-facts"><div><dt>型号 / 款式</dt><dd>${esc([row.model,row.variant].filter(Boolean).join(' / ')||'待确认')}</dd></div><div><dt>采集时间</dt><dd>${esc(when(row.observed_at))}</dd></div><div><dt>素材权利</dt><dd>${esc(rights[row.rights_status])}</dd></div></dl>${row.notes?`<p class="pe-note">${esc(row.notes)}</p>`:''}${row.verification_note?`<p><strong>核对：</strong>${esc(row.verification_note)}</p>`:''}${row.rights_evidence?`<p><strong>授权依据：</strong>${esc(row.rights_evidence)}</p>`:''}${Object.keys(row.metrics).length?`<dl class="pe-facts">${Object.entries(row.metrics).map(([k,v])=>`<div><dt>${esc(metricLabels[k]||k)}</dt><dd>${v==null||v===''?'待补':esc(v)}</dd></div>`).join('')}</dl>`:''}${imagesView(row)}${quoteRows.length?`<div class="pe-quote-summary"><h4>原报价</h4>${quoteRows.map(q=>`<p>${money(q.fields.purchase_cost,q.fields.currency)} · 起订${esc(q.fields.moq??'待补')} · ${esc(formatQuoteStatus(q.status))} · v${q.revision}</p>`).join('')}</div>`:''}<div class="pw-form-actions">${button('维护来源','source-edit',{'data-entry':row.id,disabled:s.busy})}${row.kind==='supplier'?button('管理原报价','quotes'):''}<label class="pe-upload-label">上传原始图片<input type="file" data-pe-upload="${row.id}" aria-label="上传原始图片：${esc(row.label)}" accept="image/png,image/jpeg,image/webp" ${s.busy||dirty()?'disabled':''}></label></div><details><summary>来源历史 · ${row.history.length}个版本</summary><ol class="pe-history">${row.history.map(h=>`<li><strong>v${h.revision} · ${esc(h.actor)}</strong><p>${esc(when(h.at))} · ${esc(h.payload.label)} · ${esc(states[h.payload.review_state])}</p><p>${link(h.payload.url,'该版本原始链接',{id:row.id,sha256:h.sha256})} · 图片${h.payload.images.length}张</p>${button('查看此版本','source-version',{'data-entry':row.id,'data-revision':h.revision})}${h.payload.notes?`<p class="pe-note">${esc(h.payload.notes)}</p>`:''}<small>SHA-256 ${esc(h.sha256)}</small></li>`).join('')}</ol></details></article>`;
    }
    function proposalView(){
      const p=s.data.proposal;
      return `<section class="pw-section"><header class="pe-card-heading"><h3>选品理由与试销约束</h3>${button('维护理由与约束','proposal-edit',{disabled:s.busy})}</header><dl class="pe-facts">${[['目标客户与需求',p.customer_need],['选择理由',p.selection_reason],['差异化',p.differentiation],['风险与退出条件',p.risks],['币种',p.currency],['首测数量',p.trial_quantity],['总投入上限',p.trial_budget],['最大损失',p.max_loss],['最低贡献率',p.min_contribution_rate==null?null:(p.min_contribution_rate*100)+'%'],['进入条件',p.conditions]].map(([k,v])=>`<div><dt>${k}</dt><dd>${v==null||v===''?'待确定':esc(v)}</dd></div>`).join('')}</dl><details><summary>理由历史 · v${p.revision}</summary>${(p.history||[]).map(h=>`<p>v${h.revision} · ${esc(h.actor)} · ${esc(when(h.at))}</p><p class="pe-note">${esc(h.payload.selection_reason)}</p>`).join('')||'<p>尚未保存理由版本。</p>'}</details></section>`;
    }
    function reviewView(){
      return `<section class="pw-section"><header class="pe-card-heading"><h3>正式选品评审</h3>${button('记录本次评审','review-new',{disabled:s.busy},true)}</header><div class="pe-readiness">${s.data.readiness.gaps.length?`<p>有限试销仍缺以下依据：</p><ul>${s.data.readiness.gaps.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'<p>基础资料条件已满足，可由经营负责人逐项评审。</p>'}</div>${s.data.reviews.map(r=>`<article class="pe-review"><header>${ui.badge(decisions[r.decision],r.decision==='reject'?'danger':r.decision==='trial'?'blue':'warning')}${ui.badge(r.current?'依据版本当前':'依据已变化 · 需重评',r.current?'gray':'warning')}</header><p class="pe-note">${esc(r.reason)}</p><p class="pw-meta">${esc(r.actor)} · ${esc(when(r.at))}</p><details><summary>六项判断与引用</summary>${Object.entries(r.checks).map(([k,v])=>`<p><strong>${esc(s.data.criteria[k])}</strong> · ${esc({pending:'待补证',pass:'本地核对通过',fail:'不满足'}[v.status])}</p><p>${esc(v.note)}</p><ul>${v.evidence_refs.map(ref=>`<li>${esc(ref)}</li>`).join('')}</ul>`).join('')}<small>证据版本 ${esc(r.dossier_sha256)}</small></details></article>`).join('')||'<p class="pe-missing">尚未保存正式评审；有图片或任务回执不等于选品通过。</p>'}<p class="pw-meta">结论随当前证据版本核对，不授予任何采购、广告或平台发布权限。</p></section>`;
    }
    function originalViews(){
      const c=s.data.economics,values=s.data.cost_checkpoint.payload?.input||{};
      return `<section class="pw-section"><header class="pe-card-heading"><h3>原成本与报价</h3><div>${button('管理报价','quotes')}${button('进入成本测算','cost')}</div></header><p>当前测算：${c.status==='CALCULATED'?'已计算，仍需核对经营依据':'费用待补'}</p><dl class="pe-facts"><div><dt>采购参考</dt><dd>${money(values.purchase_cost,values.currency)}</dd></div><div><dt>售价</dt><dd>${money(values.price,values.currency)}</dd></div><div><dt>贡献</dt><dd>${money(c.contribution,c.currency)}</dd></div></dl>${c.missing?.length?`<p class="pw-meta">缺项：${c.missing.map(esc).join('、')}</p>`:''}</section><section class="pw-section"><header class="pe-card-heading"><h3>关联内容与 AI 素材</h3>${button('查看图片与视频','media')}</header>${s.data.projects.map(p=>`<h4>${esc(formatProjectLabel(p,s.data.projects))}</h4><p>${p.assets.length}个已登记素材</p><ul>${p.assets.map(a=>`<li>${esc(a.name)} · ${esc(assetLabel(a.kind))}</li>`).join('')}</ul>`).join('')||'<p>尚无关联创意项目。</p>'}</section>`;
    }
    function executionView(){
      return `<section class="pw-section"><header class="pe-card-heading"><h3>执行与维护记录</h3>${button('打开原任务记录','tasks')}</header>${(s.data.activity||[]).length?ui.table(['维护动作','记录人','时间'],s.data.activity.map(x=>`<tr><td>${esc(x.title)}</td><td>${esc(x.actor)}</td><td>${esc(when(x.at))}</td></tr>`)):''}<h4>原任务与媒体处理</h4>${s.data.executions.length?ui.table(['事项','来源','原状态','记录ID'],s.data.executions.map(x=>`<tr><td>${esc(executionLabel(x))}</td><td>${x.origin==='creative'?'媒体处理':'原任务'}</td><td>${esc(statusLabel(x.status))}</td><td><code title="${esc(x.id)}">#${esc(x.id.slice(-8))}</code></td></tr>`)):'<p>当前商品尚无关联执行记录。</p>'}<p class="pw-meta">来源保存与评审版本在各自历史中保留；任务是否成功不代替需求、成本或发布核验。</p></section>`;
    }
    function view(){
      if(!s.data)return `<section class="pw-section"><h2>商品证据档案</h2><p>${s.loading?'正在读取当前商品的证据…':'尚未读取当前商品。'}</p>${s.error?`<p role="alert">${esc(s.error)}</p>`:''}${button('重新读取','refresh')}</section>`;
      const filtered=s.data.sources.filter(r=>(s.showArchived||!r.archived)&&(s.section==='suppliers'?r.kind==='supplier':s.section==='competitors'?r.kind==='competitor':true));
      return `<div class="pe-workbench" data-pe-case="${esc(s.caseId)}"><section class="pw-section pe-heading"><header class="pe-card-heading"><div><h2>商品证据档案</h2><p>${esc(s.data.name)} · ${esc(s.data.case.scope.platform)} / ${esc(s.data.case.scope.market)}</p></div><div>${button('刷新证据','refresh',{disabled:s.busy||s.loading})}${button('导出当前档案','export',{disabled:s.busy})}</div></header><nav class="pe-sections" aria-label="证据档案分区">${Object.entries({all:'全部证据',suppliers:'货源',channels:'多渠道找货',competitors:'竞品',proposal:'理由与约束',reviews:'正式评审',executions:'执行记录'}).map(([key,label])=>button(label,'section',{'data-section':key,'aria-pressed':s.section===key})).join('')}</nav></section>${s.error?`<div class="pe-notice pe-error" role="alert">${esc(s.error)}</div>`:''}${s.notice?`<div class="pe-notice" role="status">${esc(s.notice)}</div>`:''}${historyView()}${editView()}${s.section==='channels'?(sourcing?.view()||'<p>渠道模块尚未加载，请刷新页面。</p>'):''}${['all','suppliers','competitors'].includes(s.section)?`<section class="pw-section"><header class="pe-card-heading"><h3>货源、竞品与原始资料</h3>${button('新增来源','source-new',{disabled:s.busy},true)}</header><label class="pe-check"><input type="checkbox" data-pe-show-archived ${s.showArchived?'checked':''}>显示已归档来源</label></section>${filtered.map(sourceCard).join('')||'<p class="pe-missing">该范围尚无来源记录。</p>'}`:''}${['all','proposal'].includes(s.section)?proposalView():''}${['all','reviews'].includes(s.section)?reviewView():''}${s.section==='all'?originalViews():''}${['all','executions'].includes(s.section)?executionView():''}</div>`;
    }
    function inputEvent(target){
      if(target.dataset.peSourcing!==undefined){void sourcing?.input(target);return;}
      if(target.dataset.peUpload){const row=sourceById(target.dataset.peUpload);if(row)void upload(row,target.files?.[0]);return;}
      if(target.dataset.peShowArchived!==undefined){s.showArchived=target.checked;repaint();return;}
      const e=s.edit;if(!e||e.submitted||s.busy)return;
      if(target.dataset.peQuote!==undefined){e.payload.quote_ids=target.checked?[...new Set([...e.payload.quote_ids,target.dataset.peQuote])]:e.payload.quote_ids.filter(x=>x!==target.dataset.peQuote);changed();return;}
      if(target.dataset.peCheck){const row=e.payload.checks[target.dataset.peCheck],ref=target.dataset.ref;row.evidence_refs=target.checked?[...new Set([...row.evidence_refs,ref])]:row.evidence_refs.filter(x=>x!==ref);changed();return;}
      const key=target.dataset.peField;if(!key)return;
      if(key==='actor'){s.actor=target.value;changed();return;}
      const value=target.type==='checkbox'?target.checked:target.value;
      if(key.startsWith('review.'))e.payload[key.split('.')[1]]=value;
      else if(key.startsWith('checks.')){const [,criterion,field]=key.split('.');e.payload.checks[criterion][field]=value;}
      else if(key.startsWith('metrics.')){const k=key.split('.')[1];e.payload.metrics[k]=k==='currency'?value.toUpperCase():value===''?null:Number(value);}
      else if(key==='image_links'){
        const previous=new Map(e.payload.images.filter(i=>!i.media_id).map(i=>[i.url,i])),kept=e.payload.images.filter(i=>i.media_id),existing=new Set(kept.map(i=>i.url));
        e.payload.images=[...kept,...[...new Set(value.split('\n').map(x=>x.trim()).filter(Boolean))].filter(u=>!existing.has(u)).map(u=>previous.has(u)?clone(previous.get(u)):({url:u,media_id:'',label:'页面原始图片（待核对）',role:'original'}))];
      }else if(['trial_quantity','trial_budget','max_loss','min_contribution_rate'].includes(key))e.payload[key]=value===''?null:Number(value)/(key==='min_contribution_rate'?100:1);
      else if(Object.hasOwn(e.payload,key))e.payload[key]=value;
      changed(key==='kind'||key==='platform');
    }
    async function performWrite(op,args){
      const caseId=s.caseId,e=s.edit;s.busy=true;s.error='';e.submitted={op,args:clone(args)};repaint();
      try{await api(op,args);if(caseId!==s.caseId)return;s.edit=null;onDirty(false);s.notice='已保存当前商品的新版本。';await enter(caseId,{force:true});}
      catch(error){if(caseId!==s.caseId)return;s.error=codeMessage(error);if(/^evidence_|^invalid_/.test(error.message||''))e.submitted=null;}
      finally{if(caseId===s.caseId){s.busy=false;onDirty(dirty());repaint();}}
    }
    async function save(kind){
      const e=s.edit;if(!e||e.kind!==kind||s.busy)return;
      let invalid;
      if(kind==='source'&&!e.payload.label.trim())invalid=['label','请填写供应商或商品名称。'];
      else if(kind==='source'&&['supplier','competitor'].includes(e.payload.kind)&&!e.payload.url.trim())invalid=['url','请填写原始商品链接。'];
      else if(kind==='review'&&!e.payload.reason.trim())invalid=['review-reason','请填写总体理由与下一步。'];
      else if(!s.actor.trim())invalid=['actor','请填写记录人。'];
      if(invalid){s.error=invalid[1];repaint();document.getElementById('pe-'+invalid[0])?.focus();return;}
      const args={case_id:s.caseId,payload:clone(e.payload),expected_dossier_sha256:e.base,idempotency_key:e.key,actor:s.actor};
      if(kind==='source'){args.entry_id=e.entryId;args.expected_revision=e.revision;}
      if(kind==='proposal')args.expected_revision=e.revision;
      if(kind==='review'&&e.payload.decision==='trial'&&!s.data.readiness.trial_prerequisites_met){s.error='试销条件尚未满足，请先补齐资料。';repaint();return;}
      await performWrite('commerce_product_evidence_'+(kind==='source'?'source_save':kind==='proposal'?'proposal_save':'review_save'),args);
    }
    async function reconcile(){
      const e=s.edit;if(!e?.submitted||s.busy)return;
      s.busy=true;repaint();const caseId=s.caseId;
      try{const r=await api('commerce_product_evidence_operation_get',{case_id:s.caseId,idempotency_key:e.key});if(caseId!==s.caseId)return;if(r.status==='saved'){s.edit=null;onDirty(false);s.notice='已核对原保存回执。';await enter(s.caseId,{force:true});}else{s.notice='尚未查到回执，可使用原请求安全重试。';}}
      catch(error){if(caseId===s.caseId)s.error=codeMessage(error);}
      finally{if(caseId===s.caseId){s.busy=false;onDirty(dirty());repaint();}}
    }
    async function readImage(row,index,epoch){
      const key=row.id+':'+row.sha256+':'+index,pendingKey=key+':'+epoch;if(s.images.has(key)||s.loadingImages.has(pendingKey))return;
      s.loadingImages.add(pendingKey);let offset=0,parts=[],mime='image/png';
      try{do{const r=await api('commerce_product_evidence_image',{case_id:s.caseId,entry_id:row.id,expected_entry_sha256:row.sha256,index,offset});if(epoch!==s.epoch)return;if(r.status!=='archived')return;mime=r.mime;parts.push(r.content_base64);offset=r.next_offset;}while(offset!==null);
        if(epoch!==s.epoch)return;const src='data:'+mime+';base64,'+parts.join('');s.images.set(key,src);
        const node=document.getElementById('pe-image-node-'+row.id+'-'+row.revision+'-'+index);if(node)node.innerHTML=imagePreview(row,index,src);
      }catch{const node=document.getElementById('pe-image-node-'+row.id+'-'+row.revision+'-'+index);if(node&&epoch===s.epoch)node.textContent='原图未读到，请刷新后重试。';}
      finally{s.loadingImages.delete(pendingKey);}
    }
    function afterRender(){
      const epoch=s.epoch;
      for(const node of document.querySelectorAll('[data-pe-image]')){
        const row=[...(s.data?.sources||[]),...(s.history?[s.history]:[])].find(r=>r.id===node.dataset.entry&&(!node.dataset.sourceSha||r.sha256===node.dataset.sourceSha)),index=Number(node.dataset.index);if(row)node.id='pe-image-node-'+node.dataset.entry+'-'+row.revision+'-'+index;
        if(row)void readImage(row,index,epoch);
      }
    }
    async function upload(row,file){
      if(!file||s.busy||dirty())return;
      if(file.size>5*1024*1024){s.error='单张原图请控制在5MB以内。';repaint();return;}
      const caseId=s.caseId;s.busy=true;s.uploading=true;onDirty(true);s.error='';s.notice='正在上传原图…';repaint();
      try{
        const bytes=new Uint8Array(await file.arrayBuffer()),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
        const start=await api('commerce_product_evidence_upload_begin',{case_id:caseId,entry_id:row.id,expected_entry_sha256:row.sha256,filename:file.name,size:bytes.length,sha256:sha,source_url:'',role:'original',actor:s.actor});
        for(let n=start.next_index;n<Math.ceil(bytes.length/start.chunk_bytes);n++){
          const part=bytes.subarray(n*start.chunk_bytes,(n+1)*start.chunk_bytes);let binary='';for(const b of part)binary+=String.fromCharCode(b);
          await api('commerce_product_evidence_upload_chunk',{case_id:caseId,upload_id:start.upload_id,index:n,content_base64:btoa(binary)});
        }
        await api('commerce_product_evidence_upload_finish',{case_id:caseId,upload_id:start.upload_id});
        if(caseId===s.caseId){s.notice='原图已保存，来源形成新版本。';await enter(caseId,{force:true});}
      }catch(error){if(caseId===s.caseId)s.error=codeMessage(error);}
      finally{if(caseId===s.caseId){s.busy=false;s.uploading=false;onDirty(dirty());repaint();}}
    }
    async function action(name,target={dataset:{}}){
      if(name.startsWith('sourcing-')){await sourcing?.action(name.slice(9),target);return;}
      if(name==='origin-open'){const caseId=s.caseId;try{const r=await api('commerce_product_evidence_origin_open',{case_id:caseId,entry_id:target.dataset.entry,expected_entry_sha256:target.dataset.sourceSha,index:Number(target.dataset.index)});if(caseId===s.caseId){s.notice=r.status==='requested'?'已请求本机浏览器打开原始地址，请在浏览器核对页面。':'本机浏览器未能打开，请复制原始链接后查看。';repaint();}}catch(error){if(caseId===s.caseId){s.error=codeMessage(error);repaint();}}return;}
      if(name==='refresh'){await enter(s.caseId,{force:true});return;}
      if(name==='section'){s.section=target.dataset.section;if(s.section==='channels')await sourcing?.enter(s.caseId,{force:true});repaint();return;}
      if(name==='history-close'){s.history=null;repaint();return;}
      if(name==='source-version'){const epoch=s.epoch;try{const r=await api('commerce_product_evidence_source_get',{case_id:s.caseId,entry_id:target.dataset.entry,revision:Number(target.dataset.revision)});if(epoch===s.epoch){s.history=r.entry;repaint();}}catch(error){if(epoch===s.epoch){s.error=codeMessage(error);repaint();}}return;}
      if(name==='image-preview'){const key=target.dataset.entry+':'+target.dataset.sourceSha+':'+Number(target.dataset.index),src=s.images.get(key),row=[...(s.data?.sources||[]),...(s.history?[s.history]:[])].find(r=>r.id===target.dataset.entry&&r.sha256===target.dataset.sourceSha);if(src&&row)onImagePreview(src,row.images[Number(target.dataset.index)]?.label||'来源原图');return;}
      if(name==='source-new'){sourceEditor('');return;}
      if(name==='source-edit'){sourceEditor(target.dataset.entry);return;}
      if(name==='proposal-edit'){proposalEditor();return;}
      if(name==='review-new'){reviewEditor();return;}
      if(name==='rebase'){rebase();return;}
      if(name==='discard'){s.edit=null;s.error='';onDirty(false);repaint();return;}
      if(name.endsWith('-save')){await save(name.split('-')[0]);return;}
      if(name==='reconcile'){await reconcile();return;}
      if(name==='retry'){const e=s.edit;if(e?.submitted)await performWrite(e.submitted.op,e.submitted.args);return;}
      if(name==='image-remove'&&s.edit?.kind==='source'&&!s.edit.submitted){s.edit.payload.images.splice(Number(target.dataset.index),1);changed(true);return;}
      if(name==='image-capture'){
        const row=sourceById(target.dataset.entry);if(!row||s.busy||dirty())return;const caseId=s.caseId;s.busy=true;s.error='';repaint();
        try{await api('commerce_product_evidence_image_capture',{case_id:s.caseId,entry_id:row.id,expected_entry_sha256:row.sha256,index:Number(target.dataset.index),actor:s.actor});if(caseId===s.caseId){s.notice='已留存原图，来源形成新版本。';await enter(s.caseId,{force:true});}}
        catch(error){if(caseId===s.caseId)s.error=codeMessage(error);}finally{if(caseId===s.caseId){s.busy=false;onDirty(dirty());repaint();}}return;
      }
      if(name==='export'){const blob=URL.createObjectURL(new Blob([JSON.stringify(s.data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=blob;a.download='product-evidence-'+s.caseId+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(blob),1000);return;}
      if(['quotes','cost','media','tasks'].includes(name))onNavigate(name);
    }
    return {enter,view,afterRender,action,input:inputEvent,hasUnsavedChanges:dirty,hasActiveMutation:()=>s.busy||!!sourcing?.hasActiveMutation(),discardChanges(){sourcing?.discard();s.edit=null;s.error='';onDirty(dirty());},dispose(){s.epoch++;sourcing?.dispose();clearImages();}};
  };
})();
