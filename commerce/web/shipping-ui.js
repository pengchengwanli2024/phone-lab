/* Shared local shipping workbench. No carrier booking or marketplace writes. */
window.CommerceShipping = ({api,ui,esc,repaint,isActive,getOrders=()=>[]}) => {
  const copy=x=>JSON.parse(JSON.stringify(x));
  const item=()=>({group_id:'',recipient_ref:'',sku:'',quantity:'',length_cm:'',width_cm:'',height_cm:'',weight_kg:'',rotation_allowed:true,no_stack:false});
  const carton=(kind='carton')=>({id:'',name:'',kind,model_id:'custom',reference:{status:'custom',source_name:'用户填写 · 待复测',source_urls:[]},inner_cm:['','',''],outer_cm:['','',''],tare_kg:'',max_weight_kg:'',packaging_cost:'',...(kind==='container'?{door_cm:['','']}:{})});
  const day=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const s={open:false,inputsOpen:true,revision:0,busy:false,error:'',catalog:{rate_books:[],plans:[],model_catalog:{models:[]}},form:{mode:'warehouse',origin:'',destination:'',ship_date:day(),packaging_currency:'CNY',rate_book_id:'',synthetic:false,items:[item()],cartons:[carton()]},result:null,variant:'space',group:0,box:0,step:null,layer:'all',camera:{yaw:40,pitch:30,zoom:1},selectedModel:'',rateContent:'',rateSource:'',rateSynthetic:false,preview:null,previewInput:null,rateBusy:false,files:{},selection:null,fileGeneration:0,download:{phase:'idle',message:''},downloadGeneration:0};
  const modelIds=['container-20gp','container-40gp','container-40hq'];
  const comparison={enabled:false,status:'idle',data:null,selected:'container-40gp',view:'',message:'',quoteDirty:false,saved:new Map()};
  let viewer=null,viewerElement=null,viewerBox=null,fileClient=null,catalogGeneration=0,comparisonGeneration=0,comparisonTimer=null;
  const active=()=>s.open&&isActive();
  const paint=()=>{if(active()){beforePaint();repaint();}};
  const btn=(label,action,primary=false,attrs={})=>ui.button({label,variant:primary?'primary':'secondary',attrs:{'data-shipping-action':action,...attrs}});
  const field=(label,key,value,attrs={})=>ui.field(label,ui.input({value,'data-shipping-field':key,...attrs}));
  const select=(label,key,value,options)=>ui.field(label,ui.select({value,options,'data-shipping-field':key}));
  const num=(v)=>Number(v).toLocaleString('zh-CN',{maximumFractionDigits:3});
  const localTime=value=>{const d=new Date(value);return value&&!Number.isNaN(d.getTime())?d.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'时间未记录'};
  const money=(v,c)=>v==null?'待报价':`${c} ${v}`;
  const filePending=file=>['reading','validating','previewing'].includes(file?.phase);
  const downloadPending=()=>['preparing','saving'].includes(s.download.phase);
  function syncControls(){
    for(const action of ['calculate','example','orders']){const b=document.querySelector('[data-shipping-action="'+action+'"]');if(b){b.disabled=s.busy;if(action==='calculate')b.textContent=s.busy?'正在比较…':'比较装箱与费用';}}
    const preview=document.querySelector('[data-shipping-action="preview-rates"]');if(preview)preview.disabled=!s.rateContent||s.busy||s.rateBusy;
    const confirm=document.querySelector('[data-shipping-action="import-rates"]');if(confirm)confirm.disabled=!s.preview||s.busy||s.rateBusy;
    for(const b of document.querySelectorAll('[data-shipping-action]')){if(['export','template'].includes(b.dataset.shippingAction))b.disabled=downloadPending();if(b.dataset.shippingAction==='pick-file')b.disabled=s.selection?.phase==='choosing'&&s.selection.kind===b.dataset.kind;}
  }
  function cancelFiles(){s.fileGeneration++;s.rateBusy=false;if(s.selection?.phase==='choosing')s.selection={...s.selection,phase:'cancelled',message:'已取消选择等待；如文件窗口仍打开，请关闭该窗口。'};for(const file of Object.values(s.files))if(filePending(file)){file.phase='cancelled';file.message='已取消读取或校验；原有数据未替换。';}}
  function stopComparison(){clearTimeout(comparisonTimer);comparisonTimer=null;comparisonGeneration++;if(comparison.status==='loading'||comparison.status==='waiting')comparison.status='suspended';}
  function beforePaint(){if(!active()){cancelFiles();stopComparison();}if(viewer){s.camera={...viewer.getState()};viewer.destroy();viewer=null;viewerElement=null;viewerBox=null;}}
  function displayColumn(){return comparison.view?comparison.data?.models.find(row=>row.model_id===comparison.view):null;}
  function displayResult(){return comparison.view?displayColumn()?.plan:s.result;}
  function displayVariant(){return comparison.view?displayColumn()?.selected_variant:s.variant;}
  function paintResults(){if(!active())return;beforePaint();const node=document.querySelector('#shipping-result');if(node){node.innerHTML=results();draw();}const detailButton=document.querySelector('[data-shipping-action="stage-detail"]');if(detailButton)detailButton.disabled=!displayResult();}
  function queueComparison(){
    stopComparison();comparison.enabled ||= s.form.cartons.some(row=>modelIds.includes(row.model_id||row.id));
    comparison.data=null;comparison.view='';comparison.message='';comparison.saved.clear();
    if(!comparison.enabled){comparison.status='idle';return;}
    comparison.status='waiting';comparisonTimer=setTimeout(()=>runComparison(),350);
  }
  function resumeComparison(){if(comparison.enabled&&comparison.status==='waiting'&&comparisonTimer===null)queueComparison();}
  async function runComparison(){
    clearTimeout(comparisonTimer);comparisonTimer=null;if(!active()||!comparison.enabled)return;
    if(Object.values(s.files).some(filePending)||s.selection?.phase==='choosing'){comparison.status='waiting';comparison.message='文件读取或校验完成后自动重算。';paintResults();return;}
    const generation=++comparisonGeneration,revision=s.revision;let input;
    try{input=payload(true);}catch(error){comparison.status='invalid';comparison.message=error.message;paintResults();return;}
    if(comparison.quoteDirty)input.rate_book_id='';
    comparison.status='loading';comparison.message='正在同步计算三种柜型…';paintResults();
    try{
      const result=await api('commerce_shipping_compare',{input});
      if(generation!==comparisonGeneration||revision!==s.revision||!active())return;
      comparison.data=result;comparison.status='ready';comparison.message=comparison.quoteDirty?'报价修改尚未确认，当前总费用待报价。':'';
      if(!s.result){const selected=result.models.find(row=>row.model_id===comparison.selected&&row.plan)||result.models.find(row=>row.plan);comparison.view=selected?.model_id||'';}
      s.group=0;s.box=0;s.step=null;s.layer='all';
    }catch(error){if(generation===comparisonGeneration&&revision===s.revision&&active()){comparison.status='failed';comparison.message=error.message;comparison.data=null;}}
    finally{if(generation===comparisonGeneration&&revision===s.revision&&active())paintResults();}
  }
  function invalidate(){beforePaint();cancelFiles();s.revision++;s.result=null;s.error='';s.busy=false;queueComparison();paintResults();syncControls();}
  async function refresh(){
    // Catalog requests are independent of edits to the shipping form.
    const generation=++catalogGeneration;
    try{const data=await api('commerce_shipping_state');if(s.open&&generation===catalogGeneration){s.catalog={rate_books:[],plans:[],model_catalog:{models:[]},...data};paint();}}
    catch(error){if(s.open&&generation===catalogGeneration)throw error;}
  }
  async function open(mode){s.open=true;if(mode&&mode!==s.form.mode){s.form.mode=mode;invalidate();}paint();try{await refresh();}catch(e){s.error=e.message;paint();}}
  function close(){beforePaint();cancelFiles();stopComparison();catalogGeneration++;s.open=false;s.revision++;s.busy=false;s.downloadGeneration++;if(downloadPending())s.download={phase:'unknown',message:'已离开装箱页面，保存结果尚未确认；请检查宿主保存窗口或浏览器下载列表。'};fileClient?.dispose();fileClient=null;repaint();}
  function controls(){return `<div class="shipping-fields">${select('发货模式','mode',s.form.mode,[{value:'warehouse',label:'批量入仓'},{value:'buyer',label:'买家订单'}])}${field('发货地 / 报价分区','origin',s.form.origin,{maxlength:100})}${field('目的地 / 报价分区','destination',s.form.destination,{maxlength:100})}${field('计划发货日期','ship_date',s.form.ship_date,{type:'date'})}${field('包材与报价币种','packaging_currency',s.form.packaging_currency,{maxlength:3})}${select('物流报价版本','rate_book_id',s.form.rate_book_id,[{value:'',label:'暂不报价，仅比较空间'},...s.catalog.rate_books.map(b=>({value:b.id,label:`${b.synthetic?'演示 · ':''}${b.source_ref} (${b.rate_count}条)`}))])}</div>`;}
  function inputRows(){
    const buyer=s.form.mode==='buyer';
    return ui.table([buyer?'订单号':'目的仓 / 批次标识',buyer?'收件人引用':'收件引用（选填）','SKU','数量','占位长 / 宽 / 高 cm','单件 kg','摆放限制','操作'],s.form.items.map((r,i)=>{
      const input=(k,type='text',attrs={})=>ui.input({value:r[k],type,'data-shipping-item':i,'data-key':k,'aria-label':`${i+1}行 ${k}`,...attrs});
      return `<tr><td>${input('group_id')}</td><td>${input('recipient_ref')}</td><td>${input('sku')}</td><td>${input('quantity','number',{min:1,step:1})}</td><td><div class="shipping-triple">${['length_cm','width_cm','height_cm'].map(k=>input(k,'number',{min:.001,step:'any'})).join('')}</div></td><td>${input('weight_kg','number',{min:0,step:'any'})}</td><td><label class="shipping-check">${ui.input({type:'checkbox',checked:r.rotation_allowed,'data-shipping-item':i,'data-key':'rotation_allowed'})}可旋转</label><label class="shipping-check">${ui.input({type:'checkbox',checked:r.no_stack,'data-shipping-item':i,'data-key':'no_stack'})}独占箱/柜</label></td><td>${btn('移除','remove-item',false,{'data-index':i,disabled:s.form.items.length===1})}</td></tr>`;
    }));
  }
  function referenceView(reference){
    if(!reference)return '';
    const status={reference:'规格参考 · 待复测',illustrative:'起始示例 · 非实测',customized_reference:'已修改参考 · 待复测',custom:'自定义 · 待复测'}[reference.status]||'来源待核对';
    const links=(reference.source_urls||[]).flatMap((url,index)=>{try{if(new URL(url).protocol!=='https:')return [];return [`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">来源${index+1}</a>`];}catch{return [];}}).join(' · ');
    return `<details class="shipping-reference"><summary>${esc(status)}</summary><p>${esc(reference.source_name)}${reference.checked_on?' · '+esc(reference.checked_on):''}</p>${reference.note?`<p>${esc(reference.note)}</p>`:''}${links}</details>`;
  }
  function modelControls(){const models=s.catalog.model_catalog?.models||[];return `<div class="shipping-model-controls">${ui.field('参考箱型/柜型或自定义',ui.select({id:'shipping-model',value:s.selectedModel,options:[{value:'',label:'选择后添加到可用模型'},...models.map(m=>({value:m.id,label:m.name})),{value:'custom-carton',label:'自定义纸箱'},{value:'custom-container',label:'自定义集装箱'}]}))}${btn('添加到可用模型','add-model',false,{disabled:!s.selectedModel||s.form.cartons.length>=12})}</div>${s.catalog.model_catalog?.notice?`<p class="muted">${esc(s.catalog.model_catalog.notice)}</p>`:''}`;}
  function cartonRows(){return ui.table(['类型 / 标识 / 名称','可用内径 长宽高 cm','运输外径 长宽高 cm','皮重与填充 kg','最大毛重 kg（含皮重）','柜门宽 / 高 cm','包装费 / 单元','操作'],s.form.cartons.map((r,i)=>{
    const labels={id:'标识',name:'名称',tare_kg:'皮重与填充 kg',max_weight_kg:'最大毛重 kg（含皮重）',packaging_cost:'包装费（空白表示未知）'};
    const input=(k,value,type='number',extra={})=>ui.input({value,type,'data-shipping-carton':i,'data-key':k,'aria-label':`${i+1}行 ${labels[k]||k}`,min:0,step:'any',...extra});
    const kind=ui.select({value:r.kind||'carton','data-shipping-carton':i,'data-key':'kind','aria-label':`${i+1}行 类型`,options:[{value:'carton',label:'纸箱'},{value:'container',label:'集装箱'}]});
    return `<tr><td>${kind}${input('id',r.id,'text')}${input('name',r.name,'text')}${referenceView(r.reference)}</td>${['inner_cm','outer_cm'].map(k=>`<td><div class="shipping-triple">${r[k].map((v,j)=>input(k+'.'+j,v,'number',{min:.001,'aria-label':`${i+1}行 ${k==='inner_cm'?'内径':'外径'}${['长','宽','高'][j]} cm`})).join('')}</div></td>`).join('')}<td>${input('tare_kg',r.tare_kg)}</td><td>${input('max_weight_kg',r.max_weight_kg,'number',{min:.001})}</td><td>${r.kind==='container'?`<div class="shipping-door">${(r.door_cm||['','']).map((v,j)=>input('door_cm.'+j,v,'number',{min:.001,'aria-label':`${i+1}行 柜门${j?'高':'宽'} cm`})).join('')}</div>`:'—'}</td><td>${input('packaging_cost',r.packaging_cost,'text',{placeholder:'未知，请填写',maxlength:32})}</td><td>${btn('移除','remove-carton',false,{'data-index':i,disabled:s.form.cartons.length===1})}</td></tr>`;
  }));}
  function fileStatus(kind){
    const file=s.files[kind],selection=s.selection?.kind===kind?s.selection:null;if(!file&&!selection)return '';
    const description=file?`<span><strong>${esc(file.filename||'CSV文件')}</strong>${file.bytes!=null?' · '+num(file.bytes)+' 字节':''} · ${esc(file.message)}</span>`:'';
    return `<div id="shipping-file-status-${kind}" class="shipping-file-status" role="status" aria-live="polite">${description}${selection?.message?`<span>${esc(selection.message)}</span>`:''}${filePending(file)||selection?.phase==='choosing'?btn('取消读取 / 校验','cancel-file',false,{'data-kind':kind}):''}</div>`;
  }
  function filePicker(kind,label){return btn(label,'pick-file',false,{'data-kind':kind,disabled:s.selection?.kind===kind&&s.selection.phase==='choosing'});}
  function csvTools(kind){const templateKind=kind==='cartons'?'models':kind;return `<details class="shipping-import-tools"><summary>${kind==='items'?'商品':'箱型/柜型'} CSV 与模板</summary><div class="shipping-actions">${btn('下载'+({rates:'报价',items:'商品',cartons:'箱型/柜型'})[kind]+'CSV模板','template',false,{'data-kind':templateKind,disabled:downloadPending()})}${filePicker(kind,'选择'+(kind==='items'?'商品':'箱型/柜型')+' CSV')}</div></details>${fileStatus(kind)}`;}
  function ratesView(){return `<details class="shipping-rates" ${s.ratesOpen?'open':''}><summary>物流报价表导入${s.catalog.rate_books.length?' · 已保存 '+s.catalog.rate_books.length+' 个版本':''}</summary><p class="muted">选择 UTF-8 CSV 后先校验预览，明确确认后保存。首续重或阶梯表需转换为模板格式并核对；未知费用不要填0。</p><div class="shipping-actions">${btn('下载报价CSV模板','template',false,{'data-kind':'rates',disabled:downloadPending()})}${filePicker('rates','选择报价 CSV')}</div>${fileStatus('rates')}<div class="shipping-fields">${field('报价来源 / 文件名','rateSource',s.rateSource,{maxlength:500})}<label class="shipping-check">${ui.input({type:'checkbox',checked:s.rateSynthetic,'data-shipping-field':'rateSynthetic'})}此报价表为合成演示</label></div><details><summary>辅助：粘贴或修改CSV内容</summary><label class="ui-field">报价CSV<textarea class="ui-control shipping-csv" data-shipping-field="rateContent" maxlength="500000" rows="6">${esc(s.rateContent)}</textarea></label></details>${btn(s.rateBusy?'正在校验…':'重新校验并预览报价','preview-rates',false,{disabled:!s.rateContent||s.busy||s.rateBusy})}${s.preview?`${ui.table(['渠道 / 路线','币种 / 计费','有效期','已含 / 未含费用'],s.preview.rates.map(r=>`<tr><td>${esc(r.name)}<small>${esc(r.origin)} → ${esc(r.destination)}</small></td><td>${esc(r.currency)} / ${r.basis==='weight'?'kg':'m³'}</td><td>${esc(r.valid_from)} 至 ${esc(r.valid_until)}</td><td>${esc(r.included_fees)}<small>未含：${esc(r.excluded_fees)}</small></td></tr>`))}${btn(s.rateBusy?'正在保存…':'确认保存此报价版本','import-rates',true,{disabled:s.busy||s.rateBusy})}`:''}</details>`;}
  function comparisonView(){
    if(!comparison.enabled)return `<section class="shipping-comparison"><div class="shipping-actions"><h2 tabindex="-1" id="shipping-comparison-title">2. 比较方案</h2>${btn('启用20GP / 40GP / 40HQ比较','enable-comparison')}</div></section>`;
    const rows=comparison.data?.models||[];
    return `<section class="shipping-comparison" aria-label="三种柜型比较" aria-busy="${comparison.status==='loading'}"><div class="shipping-actions"><h2 tabindex="-1" id="shipping-comparison-title">2. 比较方案</h2><span class="muted">修改商品、柜型或已确认报价后自动重算</span>${btn('重新计算柜型','compare-models',false,{disabled:comparison.status==='loading'})}</div>${comparison.message?`<p role="status">${esc(comparison.message)}</p>`:''}<div class="shipping-comparison-grid" role="group" aria-label="20GP、40GP、40HQ比较列">${modelIds.map(id=>{
      const row=rows.find(entry=>entry.model_id===id),p=row?.summary,code=id.slice(10).toUpperCase(),ready=row?.status==='ready'&&row.plan;
      const entries=p?[['所需柜数',p.box_count],['装入 / 未装入',`${p.placed_units} / ${p.unplaced_units}`],['空间利用率',p.volume_utilization_pct==null?'—':num(p.volume_utilization_pct)+'%'],['运输费用',money(p.shipping_cost,p.currency)],['包装 / 加固费',money(p.packaging_cost,p.currency)],['估算总费用',money(p.total_cost,p.currency)]]:[];
      return `<article class="shipping-comparison-column${comparison.view===id?' is-selected':''}"><h3>${code}</h3>${entries.length?`<dl>${entries.map(([label,value])=>`<div><dt>${label}</dt><dd>${esc(String(value??'—'))}</dd></div>`).join('')}</dl>`:`<p class="muted">${comparison.status==='loading'?'正在计算…':comparison.status==='waiting'?'等待参数稳定…':'请补齐商品信息'}</p>`}${row?.error?`<p class="shipping-comparison-error">${esc(row.error)}</p>`:''}${ready&&!p.complete?'<p>部分商品未装入，请查看原因。</p>':''}${btn('查看'+code+'装柜','view-model',false,{'data-model':id,'aria-pressed':comparison.view===id,disabled:!ready||comparison.status!=='ready'})}</article>`;
    }).join('')}</div><p class="muted">同一批商品分别直接装入各柜型，保持订单 / 入仓批次分组。利用率＝已装商品体积 ÷ 所用柜体总内积；缺少报价或费用时不估算总价。柜型参数在输入中修改，未添加的柜型使用待复测参考值。</p></section>`;
  }
  function results(){
    const prefix=comparisonView(),result=displayResult(),variant=displayVariant();
    if(!result)return prefix+ui.empty(s.busy?'正在比较混装候选…':comparison.enabled?'等待三柜型比较结果。':'填写商品与箱型后比较方案。');
    const variants=result.variants,current=variants[variant];
    if(comparison.view)return `${prefix}${result.synthetic?ui.alert('合成演示方案，请替换为实际尺寸与物流报价。'):''}<h2>${esc(comparison.view.slice(10).toUpperCase())} 装柜效果</h2>${!variants.cost?ui.alert(incompleteCost(variants.space)):''}${current?`<section id="shipping-plan-detail" class="shipping-plan-detail" tabindex="-1"><h2>3. 方案详情</h2>${detail(current,result)}</section>`:''}`;
    const summaries=['space','cost'].map(kind=>{
      const p=variants[kind];return `<tr><td>${kind==='space'?'外箱总体积最小':'报价范围内总费用最低'}</td><td>${p?p.box_count+' 箱/柜':'待报价'}</td><td>${p?num(p.total_outer_volume_cm3/1e6)+' m³':'—'}</td><td>${p?num(p.gross_weight_kg)+' kg':'—'}</td><td>${p?money(p.shipping_cost,p.currency):'待报价'}</td><td>${p?money(p.packaging_cost,p.currency):'—'}</td><td>${p?money(p.total_cost,p.currency):'待报价'}</td><td>${p?btn('查看','variant',false,{'data-variant':kind,'aria-pressed':s.variant===kind}):''}</td></tr>`;
    });
    return `${prefix}${result.synthetic?ui.alert('合成演示方案，请替换为实际尺寸与物流报价。'):''}${ui.table(['候选方案','箱/柜数','总体积','总毛重','运输费用','包装费用','估算总费用','操作'],summaries)}<p class="muted">${esc(result.notice)}</p>${!variants.cost?ui.alert(incompleteCost(variants.space)):''}${current?`<section id="shipping-plan-detail" class="shipping-plan-detail" tabindex="-1"><h2>3. 方案详情</h2>${detail(current,result)}</section>`:''}`;
  }
  function incompleteCost(plan){const unknown=[...new Set((plan?.groups||[]).flatMap(g=>g.boxes).filter(b=>b.packaging_cost==='').map(b=>b.carton_name))],reasons=[];if(unknown.length)reasons.push('包装费尚未提供：'+unknown.join('、')+'。空白表示未知，确认免费后才填0');if(!s.form.rate_book_id)reasons.push('尚未选择物流报价版本');if(!reasons.length)reasons.push('请核对报价路线、日期、币种以及重量和尺寸限制');return '当前没有完整可报价方案。'+reasons.join('。')+'；空间方案仍可查看。';}
  function detail(plan,result=s.result){
    if(!plan.groups.length)return ui.empty('此方案暂无装载单元。');s.group=Math.min(s.group,plan.groups.length-1);const group=plan.groups[s.group];s.box=Math.min(s.box,Math.max(0,group.boxes.length-1));const box=group.boxes[s.box];
    const quote=group.quote;
    return `${!plan.complete?ui.alert('仅部分商品装入；请处理未装入原因后重新计算。','danger'):''}${ui.table(['发货组','装入 / 未装入','候选数量','未装入原因'],plan.groups.map(g=>`<tr><td>${esc(g.group_id)}</td><td>${g.placed_units} / ${g.input_units-g.placed_units}</td><td>${result.comparisons.find(c=>c.group_id===g.group_id)?.candidate_count||0}</td><td>${g.unplaced.map(u=>`${esc(u.sku)} × ${u.quantity}：${esc(u.reasons.join('、'))}`).join('<br>')||'—'}</td></tr>`))}<div class="shipping-fields">${ui.field('查看发货组',ui.select({id:'shipping-group',value:s.group,options:plan.groups.map((g,i)=>({value:i,label:g.group_id}))}))}${ui.field('查看装载单元',ui.select({id:'shipping-box',value:s.box,options:group.boxes.map((b,i)=>({value:i,label:`第${i+1}${b.kind==='container'?'柜':'箱'} · ${b.carton_name} · ${b.items.length}件`}))}))}</div>${box?`<section class="shipping-visual"><div class="shipping-actions"><strong>${esc(box.carton_name)} · 内径 ${box.inner_cm.map(num).join(' × ')} cm</strong>${btn('旋转视角','turn')}${btn('放大','zoom-in')}${btn('缩小','zoom-out')}${btn('重置视角','reset-view')}${ui.field('显示层',ui.select({id:'shipping-layer',value:s.layer,options:[{value:'all',label:'全部层'},...[...new Set(box.items.map(x=>x.position_cm[2]))].sort((a,b)=>a-b).map(z=>({value:String(z),label:'底部高度 '+num(z)+' cm'}))]}))}</div><p class="muted shipping-viewer-help">拖动可自由旋转，滚轮或双指缩放；聚焦图形后可用方向键旋转、加减键缩放、Home 重置。</p><svg id="shipping-scene" role="img" aria-label="商品三维装箱示意"></svg><output id="shipping-camera" class="shipping-camera" aria-label="当前三维视角"></output><label class="ui-field">装入顺序 <span id="shipping-step-label"></span><input id="shipping-step" type="range" min="0" max="${box.items.length}" value="${s.step??box.items.length}"></label><div class="shipping-sku-legend">${[...new Set(box.items.map(x=>x.sku))].map(sku=>`<span><i class="shipping-swatch" style="--shipping-sku-color:${skuColor(sku)}"></i>${esc(sku)}</span>`).join('')}</div><p>装载单元毛重 ${num(box.gross_weight_kg)} kg · 外径 ${box.outer_cm.map(num).join(' × ')} cm · 内部体积利用率 ${num(box.volume_utilization_pct)}%</p>${ui.table(['SKU','该箱/柜数量'],[...new Set(box.items.map(x=>x.sku))].map(sku=>`<tr><td>${esc(sku)}</td><td>${box.items.filter(x=>x.sku===sku).length}</td></tr>`))}</section>`:ui.empty('此发货组暂无可装入的箱/柜。')}${quote?`<details class="shipping-quote-details"><summary>${esc(quote.rate_name)} · 当前组报价明细</summary>${ui.table(['箱/柜号','毛重 kg','体积重 kg','计费量','运输含燃油','包材'],quote.box_breakdown.map(b=>`<tr><td>${b.box_index}</td><td>${esc(b.gross_weight_kg)}</td><td>${esc(b.volumetric_weight_kg)}</td><td>${esc(b.chargeable)} ${esc(b.chargeable_unit)}</td><td>${money(b.shipping_cost,quote.currency)}</td><td>${money(b.packaging_cost,quote.currency)}</td></tr>`))}<p>每票费 ${money(quote.shipment_fee,quote.currency)} · 其它已知费用 ${money(quote.other_fee,quote.currency)}</p><p>已含：${esc(quote.included_fees)}；未含：${esc(quote.excluded_fees)}</p></details>`:''}<div class="shipping-actions">${btn('导出装箱 CSV','export',false,{'data-format':'csv',disabled:downloadPending()})}${btn('导出可打印装箱单','export',false,{'data-format':'html',disabled:downloadPending()})}${btn('导出完整方案 JSON','export',false,{'data-format':'json',disabled:downloadPending()})}</div><details><summary>输入与报价版本</summary><p class="shipping-hash">方案 ${esc(result.id)}<br>方案时间 ${esc(result.created_at||'时间未记录')}<br>输入 ${esc(result.input_sha256)}<br>报价 ${esc(result.rate_book_sha256||'尚未选择')}</p></details>`;
  }
  function view(){beforePaint();return `<div id="shipping-root" class="shipping-workbench"><div class="shipping-actions">${btn('返回原页面','close')}${btn('填入混装演示','example',false,{disabled:s.busy})}${btn('带入当前订单行','orders',false,{disabled:s.busy})}</div><nav class="shipping-stages" aria-label="装箱流程">${btn('1. 输入','stage-input')}${btn('2. 比较','stage-comparison')}${btn('3. 方案详情','stage-detail',false,{disabled:!displayResult()})}</nav>${s.error?ui.alert(s.error,'danger'):''}${downloadStatus()}<details id="shipping-input" class="shipping-input" data-ui-managed-state ${s.inputsOpen?'open':''}><summary id="shipping-input-title">1. 输入 · ${s.form.items.length} 行商品 · ${s.form.cartons.length} 种箱型/柜型${s.selection?.phase==='unknown'||Object.values(s.files).some(file=>['failed','changed','reading','validating','previewing'].includes(file.phase))?' · 文件待核对':''}</summary><section class="card"><h2>发货范围</h2>${controls()}<p class="muted">买家订单分别装箱，入仓按目的仓与批次分组。同一标识内可混合SKU，所有组使用同一路线。</p></section><section class="card"><h2>商品与数量</h2><p class="muted">填写含包装与缓冲的占位尺寸；独占选项会单独占用一个箱/柜。实际承重与稳定性需复核。</p>${inputRows()}<div class="shipping-actions">${btn('添加商品','add-item',false,{disabled:s.form.items.length>=100})}${csvTools('items')}</div></section><section class="card"><h2>可用箱型/柜型</h2>${modelControls()}${cartonRows()}<p class="muted">包装费留空表示未知；最大毛重包含皮重。柜门宽高只检查朝向准入，实际装载路径与承重需复核。</p><div class="shipping-actions">${btn('添加自定义纸箱','add-carton',false,{disabled:s.form.cartons.length>=12})}${csvTools('cartons')}</div></section>${ratesView()}<details class="shipping-advanced"><summary>高级与演示选项</summary><label class="shipping-check">${ui.input({type:'checkbox',checked:s.form.synthetic,'data-shipping-field':'synthetic'})}商品与箱型为合成演示</label><p class="muted">最多100行商品、500件、12种箱型/柜型、20个发货组。</p></details><div class="shipping-actions shipping-calculate">${btn(s.busy?'正在比较…':'比较装箱与费用','calculate',true,{disabled:s.busy})}</div></details><div id="shipping-result" aria-live="polite">${results()}</div><details class="shipping-history"><summary>已保存的装箱草稿</summary>${ui.table(['时间 / 模式','件数','操作'],s.catalog.plans.map(p=>`<tr><td>${esc(localTime(p.created_at))} / ${p.mode==='buyer'?'买家订单':'入仓'}${p.synthetic?' · 演示':''}</td><td>${p.input_units}</td><td>${btn('打开原方案','history',false,{'data-id':p.id})}</td></tr>`))}</details></div>`;}
  function stage(name){s.inputsOpen=name==='input';const input=document.querySelector('#shipping-input');if(input)input.open=s.inputsOpen;const target=document.querySelector(name==='input'?'#shipping-input-title':name==='comparison'?'#shipping-comparison-title':'#shipping-plan-detail');target?.focus?.({preventScroll:true});target?.scrollIntoView?.({block:'start',behavior:'auto'});}
  function skuColor(sku){let hash=0;for(const char of String(sku))hash=(Math.imul(hash,31)+char.codePointAt(0))>>>0;return ['var(--ui-color-action-primary)','var(--ui-color-success)','var(--ui-color-warning)','var(--ui-color-text)'][hash%4];}
  function cameraReadout(state){s.camera={...state};const readout=document.querySelector('#shipping-camera');if(readout)readout.textContent=`水平 ${Math.round(state.yaw)}° · 俯仰 ${Math.round(state.pitch)}° · 缩放 ${Math.round(state.zoom*100)}% · 显示 ${state.visibleCount} / ${state.totalCount} 件`;}
  function draw(){
    const result=displayResult();if(!active()||!result){beforePaint();return;}
    const plan=result.variants[displayVariant()],box=plan?.groups[s.group]?.boxes[s.box],svg=document.querySelector('#shipping-scene');if(!svg||!box){beforePaint();return;}
    const count=Math.min(s.step??box.items.length,box.items.length);s.step=count;
    const slider=document.querySelector('#shipping-step');if(slider)slider.value=count;const label=document.querySelector('#shipping-step-label');if(label)label.textContent=`${count} / ${box.items.length} 件`;
    if(!window.CommerceShippingViewer){svg.textContent='三维查看器尚未载入，请刷新后重试。';return;}
    if(viewerElement!==svg){beforePaint();viewerElement=svg;viewerBox=box;viewer=window.CommerceShippingViewer.create({element:svg,box,count,layer:s.layer,palette:skuColor,initialState:s.camera,onChange:cameraReadout});}
    else if(viewerBox!==box){viewerBox=box;viewer.setBox(box,{count,layer:s.layer,palette:skuColor});}
    else viewer.setFilter({count,layer:s.layer});
  }
  function afterPaint(){if(!active()){beforePaint();cancelFiles();return;}draw();if(comparison.status==='suspended')queueComparison();}
  function downloadStatus(){return s.download.phase==='idle'?'':`<div class="shipping-download-status" role="status" aria-live="polite">${esc(s.download.message)}</div>`;}
  function files(){if(!window.CommerceShippingFiles)throw Error('文件工具尚未载入，请刷新后重试。');return window.CommerceShippingFiles;}
  function errorMessage(error){const code=String(error?.code||error?.message||'');if(code.includes('shipping_native_download_unavailable'))return '当前客户端无法打开原生保存窗口，请更新客户端后重试；文件尚未保存。';if(code.includes('request_outcome_unknown'))return '保存结果尚未确认，请检查宿主保存窗口或浏览器下载列表后再重试。';return error?.message||'文件操作失败，请重新选择文件后重试。';}
  async function download(load,isCurrent=()=>true){
    if(downloadPending())return;
    const generation=++s.downloadGeneration;s.download={phase:'preparing',message:'正在准备下载文件…'};paint();
    try{
      const file=await load();if(generation!==s.downloadGeneration)return;
      if(!active()||!isCurrent()){s.download={phase:'cancelled',message:'页面、参数或方案已变化，已取消此次导出。'};paint();return;}
      s.download={phase:'saving',message:'文件已准备，正在等待保存结果…'};paint();
      if(!fileClient)fileClient=files().createClient({target:window,nonce:'__COMMERCE_BRIDGE_NONCE__'});
      const result=await fileClient.request('download',{file});if(generation!==s.downloadGeneration)return;
      const filename=result.filename||file.filename;
      if(result.status==='saved')s.download={phase:'saved',message:'已保存：'+filename};
      else if(result.status==='requested')s.download={phase:'requested',message:'已请求浏览器下载：'+filename+'。请在下载列表确认。'};
      else if(result.status==='cancelled')s.download={phase:'cancelled',message:'已取消保存：'+filename};
      else s.download={phase:'unknown',message:'保存结果尚未确认，请检查下载位置。'};
    }catch(error){if(generation===s.downloadGeneration)s.download={phase:String(error?.code||error?.message||'').includes('request_outcome_unknown')?'unknown':'failed',message:errorMessage(error)};}
    finally{if(generation===s.downloadGeneration)paint();}
  }
  const rateSnapshot=()=>({content:s.rateContent,source_ref:s.rateSource,synthetic:s.rateSynthetic});
  const sameRates=snapshot=>snapshot&&snapshot.content===s.rateContent&&snapshot.source_ref===s.rateSource&&snapshot.synthetic===s.rateSynthetic;
  async function previewRates(generation=s.fileGeneration,revision=s.revision){
    if(s.rateBusy)return;const snapshot=rateSnapshot();s.preview=null;s.previewInput=null;s.rateBusy=true;s.ratesOpen=true;
    s.files.rates={...s.files.rates,filename:s.files.rates?.filename||s.rateSource||'手动CSV内容',phase:'previewing',message:'已读取，正在校验报价…'};paint();
    try{
      const result=await api('commerce_shipping_rates_preview',snapshot);
      if(generation!==s.fileGeneration||revision!==s.revision||!sameRates(snapshot))return;
      s.preview=result;s.previewInput=snapshot;s.files.rates={...s.files.rates,phase:'ready',message:'已读取并校验，请核对预览后确认保存。'};
    }catch(error){if(generation===s.fileGeneration&&revision===s.revision){s.preview=null;s.previewInput=null;s.files.rates={...s.files.rates,phase:'failed',message:errorMessage(error)};}}
    finally{if(generation===s.fileGeneration&&revision===s.revision){s.rateBusy=false;queueComparison();paint();}}
  }
  function beginImport(kind){
    invalidate();s.selection=null;if(kind==='rates'){comparison.quoteDirty=true;s.preview=null;s.previewInput=null;s.ratesOpen=true;}
    return {generation:s.fileGeneration,revision:s.revision};
  }
  async function applyCsv(loaded,kind,generation,revision){
    const current=()=>generation===s.fileGeneration&&revision===s.revision&&active();if(!current())return;
    s.files[kind]={filename:loaded.filename,bytes:loaded.bytes,phase:'validating',message:'已读取，正在校验…'};
    try{
      if(kind==='rates'){s.rateContent=loaded.content;s.rateSource=loaded.filename;await previewRates(generation,revision);return;}
      paint();const result=await api('commerce_shipping_input_preview',{kind,content:loaded.content});if(!current())return;
      s.form[kind]=result.rows;s.files[kind]={...s.files[kind],phase:'ready',message:`已读取并导入 ${result.row_count??result.rows.length} 行。`};queueComparison();paint();
    }catch(error){if(current()){s.files[kind]={...s.files[kind],phase:'failed',message:errorMessage(error)};paint();}}
  }
  async function readFile(file,kind){
    if(!['items','cartons','rates'].includes(kind)||!file)return;
    const {generation,revision}=beginImport(kind);s.files[kind]={filename:file.name,bytes:file.size,phase:'reading',message:'正在读取 CSV…'};paint();
    try{const loaded=await files().readCsv(file,{kind});await applyCsv(loaded,kind,generation,revision);}
    catch(error){if(generation===s.fileGeneration&&revision===s.revision&&active()){s.files[kind]={...s.files[kind],phase:'failed',message:errorMessage(error)};paint();}}
    finally{if(active())resumeComparison();}
  }
  async function pickFile(kind){
    if(!['items','cartons','rates'].includes(kind)||!active())return;
    cancelFiles();const generation=s.fileGeneration,revision=s.revision;
    const current=()=>generation===s.fileGeneration&&revision===s.revision&&active();
    s.selection={kind,phase:'choosing',message:'正在选择 CSV…'};
    try{
      if(!fileClient)fileClient=files().createClient({target:window,nonce:'__COMMERCE_BRIDGE_NONCE__'});
      // Start the host chooser in the click turn, before any repaint or await.
      const pending=fileClient.request('pick-csv',{kind});paint();const selected=await pending;if(!current()){if(active())paint();return;}
      if(selected?.status==='cancelled'){s.selection={kind,phase:'cancelled',message:'已取消选择，保留已有文件和数据。'};paint();return;}
      if(selected?.status!=='selected'||typeof selected.content!=='string'||typeof selected.filename!=='string')throw Error('文件选择结果无效，请重新选择 CSV。');
      const next=beginImport(kind);await applyCsv(selected,kind,next.generation,next.revision);
    }catch(error){if(current()){const code=String(error?.code||error?.message||''),unknown=/shipping_file_selection_unknown|request_outcome_unknown/.test(code);s.selection={kind,phase:unknown?'unknown':'failed',message:unknown?'选择结果尚未确认，请关闭文件选择框后再试。':errorMessage(error)};paint();}}
    finally{if(active())resumeComparison();}
  }
  function customize(row){if(row.reference&&row.reference.status!=='custom')row.reference={...row.reference,status:'customized_reference'};}
  function addModel(){
    if(!s.selectedModel)throw Error('请先选择箱型/柜型。');
    let row;
    if(s.selectedModel==='custom-carton'||s.selectedModel==='custom-container'){row=carton(s.selectedModel==='custom-container'?'container':'carton');row.id=s.selectedModel;row.name=row.kind==='container'?'自定义集装箱':'自定义纸箱';}
    else{const model=s.catalog.model_catalog?.models?.find(m=>m.id===s.selectedModel);if(!model)throw Error('所选模型已变化，请刷新后重新选择。');row=copy(model);}
    const empty=s.form.cartons.length===1&&!s.form.cartons[0].id&&!s.form.cartons[0].name&&s.form.cartons[0].inner_cm.every(v=>v==='');
    if(!empty&&s.form.cartons.length>=12)throw Error('最多12种箱型/柜型。');
    const base=row.id;let suffix=2;while(s.form.cartons.some(r=>r.id===row.id))row.id=base+'-'+suffix++;
    invalidate();if(empty)s.form.cartons=[row];else s.form.cartons.push(row);queueComparison();paint();
  }
  function numeric(v,key){if(v===''||v==null||!Number.isFinite(Number(v)))throw Error('请补齐有效数值：'+key);return Number(v);}
  function payload(forComparison=false){const f=copy(s.form);if(comparison.quoteDirty)f.rate_book_id='';if(forComparison)f.cartons=f.cartons.filter(row=>modelIds.includes(row.model_id||row.id));f.items=f.items.map(r=>({...r,...Object.fromEntries(['quantity','length_cm','width_cm','height_cm','weight_kg'].map(k=>[k,numeric(r[k],k)]))}));f.cartons=f.cartons.map(r=>({...r,inner_cm:r.inner_cm.map(v=>numeric(v,'可用内径')),outer_cm:r.outer_cm.map(v=>numeric(v,'运输外径')),tare_kg:numeric(r.tare_kg,'皮重与填充'),max_weight_kg:numeric(r.max_weight_kg,'最大毛重'),...(r.door_cm?{door_cm:r.door_cm.map(v=>numeric(v,'柜门宽高'))}:{})}));return f;}
  async function calculate(){const focusStartedHere=document.activeElement?.dataset?.shippingAction==='calculate',input=payload();cancelFiles();stopComparison();const revision=++s.revision;s.busy=true;s.result=null;s.error='';paint();try{const result=await api('commerce_shipping_plan_create',{input});if(revision===s.revision){s.result=result;s.inputsOpen=false;s.catalog.plans=[{id:result.id,created_at:result.created_at,mode:result.mode,input_units:result.input_units,synthetic:result.synthetic},...s.catalog.plans.filter(p=>p.id!==result.id)].slice(0,20);s.variant='space';comparison.view='';s.group=0;s.box=0;s.step=null;s.layer='all';}}catch(e){if(revision===s.revision)s.error=e.message;}finally{if(revision===s.revision){s.busy=false;queueComparison();paint();if(s.result&&focusStartedHere&&(!document.activeElement||document.activeElement===document.body||document.activeElement.dataset?.shippingAction==='calculate'))stage('comparison');}}}
  async function action(b){const a=b.dataset.shippingAction;
    if(a.startsWith('stage-')){stage(a.slice(6));return;}
    if(a==='close'){close();return;}if(a==='turn'){viewer?.rotateBy(90,0);return;}if(a==='zoom-in'){viewer?.zoomIn();return;}if(a==='zoom-out'){viewer?.zoomOut();return;}if(a==='reset-view'){viewer?.reset();return;}if(a==='calculate'){if(!s.busy)await calculate();return;}
    if(a==='add-model'){addModel();return;}
    if(a==='enable-comparison'){
      const missing=modelIds.filter(id=>!s.form.cartons.some(row=>(row.model_id||row.id)===id));
      const additions=missing.map(id=>s.catalog.model_catalog.models.find(row=>row.id===id));
      if(additions.some(row=>!row))throw Error('柜型规格目录尚未读取，请稍后重试。');
      const rows=s.form.cartons.filter(row=>row.id||row.name);if(rows.length+additions.length>12)throw Error('最多12种箱型/柜型，请先移除不用的模型。');
      comparison.enabled=true;invalidate();s.form.cartons=[...rows,...copy(additions)];queueComparison();paint();return;
    }
    if(a==='compare-models'){comparison.enabled=true;queueComparison();await runComparison();return;}
    if(a==='view-model'){
      const row=comparison.data?.models.find(entry=>entry.model_id===b.dataset.model);
      if(comparison.status!=='ready'||!row?.plan)return;
      s.inputsOpen=false;const input=document.querySelector('#shipping-input');if(input)input.open=false;comparison.selected=row.model_id;comparison.view=row.model_id;s.group=0;s.box=0;s.step=null;s.layer='all';paintResults();
      const scene=document.querySelector('#shipping-scene');scene?.focus({preventScroll:true});scene?.scrollIntoView?.({block:'nearest',behavior:'auto'});return;
    }
    if(a==='pick-file'){await pickFile(b.dataset.kind);return;}
    if(a==='cancel-file'){if(filePending(s.files[b.dataset.kind])||s.selection?.kind===b.dataset.kind&&s.selection.phase==='choosing'){cancelFiles();resumeComparison();paint();}return;}
    if(a==='variant'){comparison.view='';s.variant=b.dataset.variant;s.group=0;s.box=0;s.step=null;s.layer='all';paint();stage('detail');return;}
    if(a==='example'){invalidate();s.form={...s.form,synthetic:true,origin:'CN',destination:'RU',packaging_currency:'CNY',items:[{...item(),group_id:'DEMO-1',recipient_ref:'DEMO-RECIPIENT',sku:'DEMO-A',quantity:12,length_cm:20,width_cm:10,height_cm:10,weight_kg:.4},{...item(),group_id:'DEMO-1',recipient_ref:'DEMO-RECIPIENT',sku:'DEMO-B',quantity:8,length_cm:10,width_cm:10,height_cm:10,weight_kg:.2}],cartons:[{id:'DEMO-L',name:'演示大箱',inner_cm:[60,40,40],outer_cm:[62,42,42],tare_kg:1.2,max_weight_kg:20,packaging_cost:'8'},{id:'DEMO-M',name:'演示中箱',inner_cm:[40,30,40],outer_cm:[42,32,42],tare_kg:.9,max_weight_kg:20,packaging_cost:'6'},{id:'DEMO-S',name:'演示小箱',inner_cm:[40,30,20],outer_cm:[42,32,22],tare_kg:.7,max_weight_kg:20,packaging_cost:'5'}]};paint();return;}
    if(a==='orders'){const rows=getOrders();if(!rows.length)throw Error('当前列表没有可带入的订单。');if(rows.some(o=>o.data_source==='ozon_api'&&!Array.isArray(o.items)))throw Error('当前Ozon列表是订单汇总，缺少可核对的逐SKU明细；请使用商品CSV按订单逐行导入。');const expanded=rows.flatMap(o=>Array.isArray(o.items)?o.items.map(line=>({...o,...line,order_id:o.order_id||o.id})):o);if(expanded.length>100)throw Error('当前超过100行商品，请先筛选订单或通过CSV分批导入，未自动截断。');invalidate();s.form.mode='buyer';s.form.items=expanded.map(o=>({...item(),group_id:[o.platform,o.store_id,o.order_id||o.id].filter(Boolean).join('/'),sku:o.sku||'',quantity:o.quantity??''}));s.form.synthetic=rows.some(o=>o.demo||String(o.id).startsWith('DEMO'));s.error='已带入订单与逐SKU明细；请核对数量，并补齐收件人引用、包装尺寸和重量。';paint();return;}
    if(a==='add-item'||a==='add-carton'||a==='remove-item'||a==='remove-carton'){invalidate();const key=a.endsWith('item')?'items':'cartons',rows=s.form[key];if(a.startsWith('add')){if(rows.length>=(key==='items'?100:12))throw Error('已达到行数上限');rows.push(key==='items'?item():carton());}else if(rows.length>1)rows.splice(Number(b.dataset.index),1);paint();return;}
    if(a==='template'){await download(()=>api('commerce_shipping_template',{kind:b.dataset.kind}));return;}
    if(a==='preview-rates'){await previewRates();return;}
    if(a==='import-rates'){
      if(s.rateBusy)return;if(!s.preview||!sameRates(s.previewInput))throw Error('请先重新校验并预览当前报价。');
      const revision=s.revision,generation=s.fileGeneration,snapshot={...s.previewInput},sha=s.preview.sha256;s.rateBusy=true;paint();
      try{const result=await api('commerce_shipping_rates_import',{...snapshot,expected_sha256:sha});if(revision!==s.revision||generation!==s.fileGeneration||!sameRates(snapshot))return;comparison.quoteDirty=false;invalidate();s.form.rate_book_id=result.id;s.preview=null;s.previewInput=null;s.files.rates={...s.files.rates,phase:'saved',message:'已确认保存为报价版本。'};await refresh();}
      catch(error){if(revision===s.revision&&generation===s.fileGeneration){s.error=errorMessage(error);}}
      finally{if(revision===s.revision&&generation===s.fileGeneration){s.rateBusy=false;paint();}}return;
    }
    if(a==='export'){
      const result=displayResult();if(!result)throw Error('请先重新计算当前参数。');
      const revision=s.revision,variant=displayVariant(),view=comparison.view,generation=comparisonGeneration;
      const current=()=>active()&&revision===s.revision&&displayResult()?.sha256===result.sha256&&displayVariant()===variant&&comparison.view===view&&(!view||generation===comparisonGeneration);
      await download(async()=>{
        let saved=result;
        if(result.persisted===false){
          saved=comparison.saved.get(result.sha256);
          if(!saved){saved=await api('commerce_shipping_plan_create',{input:copy(result.input)});if(revision===s.revision&&generation===comparisonGeneration)comparison.saved.set(result.sha256,saved);if(!current())throw Error('参数或所选柜型已变化，已取消此次导出。');s.catalog.plans=[{id:saved.id,created_at:saved.created_at,mode:saved.mode,input_units:saved.input_units,synthetic:saved.synthetic},...s.catalog.plans.filter(p=>p.id!==saved.id)].slice(0,20);}
        }
        return api('commerce_shipping_export',{plan_id:saved.id,variant,format:b.dataset.format,expected_sha256:saved.sha256});
      },current);return;
    }
    if(a==='history'){cancelFiles();stopComparison();const revision=++s.revision;s.busy=false;s.result=null;comparison.view='';paint();const result=await api('commerce_shipping_plan_get',{plan_id:b.dataset.id});if(revision!==s.revision)return;s.result=result;s.inputsOpen=false;s.form=copy(result.input);comparison.quoteDirty=false;queueComparison();s.variant='space';s.group=0;s.box=0;s.step=null;s.layer='all';s.error='';paint();stage('detail');}
  }
  document.addEventListener('click',event=>{const opener=event.target.closest('[data-shipping-open]');if(opener&&isActive()){open(opener.dataset.shippingOpen||undefined);return;}const b=event.target.closest('[data-shipping-action]');if(!b||!active()||b.disabled)return;action(b).catch(e=>{s.error=e.message;s.busy=false;paint();});});
  document.addEventListener('input',event=>{
    const e=event.target;if(!active()||!e.closest('#shipping-root'))return;
    if(e.id==='shipping-step'){s.step=Number(e.value);draw();return;}
    if(e.dataset.shippingField){
      const key=e.dataset.shippingField;
      if(['rateSource','rateSynthetic','rateContent'].includes(key)){s[key]=e.type==='checkbox'?e.checked:e.value;comparison.quoteDirty=true;s.preview=null;s.previewInput=null;invalidate();if(s.files.rates)s.files.rates={...s.files.rates,phase:'changed',message:'内容或来源已修改，请重新校验。'};}
      else{s.form[key]=e.type==='checkbox'?e.checked:e.value;if(key==='rate_book_id')comparison.quoteDirty=false;invalidate();}return;
    }
    if(e.dataset.shippingItem!==undefined){s.form.items[Number(e.dataset.shippingItem)][e.dataset.key]=e.type==='checkbox'?e.checked:e.value;invalidate();return;}
    if(e.dataset.shippingCarton!==undefined){
      const row=s.form.cartons[Number(e.dataset.shippingCarton)],[key,index]=e.dataset.key.split('.');
      if(index!==undefined){if(!row[key])row[key]=['',''];row[key][Number(index)]=e.value;}else row[key]=e.value;
      if(key==='kind'){if(row.kind==='container'&&!row.door_cm)row.door_cm=['',''];if(row.kind!=='container')delete row.door_cm;}
      if(['kind','inner_cm','outer_cm','tare_kg','max_weight_kg','door_cm'].includes(key))customize(row);invalidate();
    }
  });
  document.addEventListener('change',async event=>{
    const e=event.target;if(!active()||!e.closest('#shipping-root'))return;
    try{
      if(e.id==='shipping-group'){s.group=Number(e.value);s.box=0;s.step=null;s.layer='all';paint();}
      else if(e.id==='shipping-box'){s.box=Number(e.value);s.step=null;s.layer='all';paint();}
      else if(e.id==='shipping-layer'){s.layer=e.value;draw();}
      else if(e.id==='shipping-model'){s.selectedModel=e.value;paint();}
      else if(e.dataset.shippingFile)await readFile(e.files?.[0],e.dataset.shippingFile);
      else if(e.dataset.shippingField||e.dataset.shippingItem!==undefined||e.dataset.shippingCarton!==undefined){
        if(e.dataset.shippingField==='mode'||['rateSource','rateSynthetic','rateContent'].includes(e.dataset.shippingField)||e.dataset.shippingCarton!==undefined&&e.dataset.key==='kind')paint();
      }
    }catch(error){s.error=errorMessage(error);paint();}
  });
  document.addEventListener('toggle',event=>{if(event.target.matches?.('.shipping-rates'))s.ratesOpen=event.target.open;else if(event.target.id==='shipping-input')s.inputsOpen=event.target.open;},true);
  window.addEventListener('pagehide',()=>{beforePaint();cancelFiles();fileClient?.dispose();fileClient=null;});
  return {open,close,isOpen:()=>s.open,view,beforePaint,afterPaint};
};
