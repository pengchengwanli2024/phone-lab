/* Field editors preserve the evidence contract; references remain explicit. */
window.CommerceBusinessForms=({ui})=>{
 const esc=ui.escape,clone=value=>JSON.parse(JSON.stringify(value));
 const labels={sku:'商品 SKU',title:'标题',description:'描述',category_id:'类目编号',price:'售价',currency:'币种',quantity:'数量',image_refs:'图片引用',order_ref:'订单引用',package_ref:'包裹引用',carrier:'承运商',tracking_number:'运单号',amount:'退款金额',reason:'原因',unit_cost:'采购单价',supplier_ref:'供应商引用',campaign_ref:'广告计划引用',budget:'预算',market:'市场',start_at:'开始时间',end_at:'结束时间',conversation_ref:'会话引用',reply:'回复正文',policy_ref:'规则依据'};
 const input=(id,label,value,large=false,readonly=false)=>ui.field(label,large?`<textarea id="${id}" class="ui-control" ${readonly?'readonly':''}>${esc(value)}</textarea>`:ui.input({id,value:value??'',readonly}));
 const recordFields=kind=>kind==='reviews'?['id','text','rating']:kind==='conversation'?['id','role','text']:['key','value'];
 function importEditor(doc){
  const scope=doc.scope||{};
  return `<div class="business-field-editor">${input('business-label','资料名称',doc.label)}${input('business-platform','平台',scope.platform)}${input('business-store','店铺引用（脱敏）',scope.store_ref)}${input('business-subject','业务对象引用',scope.subject_ref)}${input('business-origin','来源引用',doc.origin_ref)}${input('business-observed','实际采集时间（含时区）',doc.observed_at)}${input('business-valid','资料有效至（含时区）',doc.valid_until)}</div><p class="muted" data-ui-help>保留原始陈述，未知评分留空。引用和有效期由操作者核对。</p>${doc.records.map((r,index)=>`<fieldset class="business-field-record"><legend>记录 ${index+1}</legend>${recordFields(doc.kind).map(key=>{const value=r[key],id='business-record-'+index+'-'+key;return key==='rating'?ui.field('评分（未知可留空）',ui.select({id,value:value??'',options:[{value:'',label:'未知'},...[1,2,3,4,5].map(n=>({value:n,label:String(n)}))]})):key==='role'?ui.field('消息角色',ui.select({id,value,options:[{value:'buyer',label:'买家'},{value:'seller',label:'卖家'}]})):input(id,({id:'记录编号',text:'原文内容',key:'事实字段名',value:'事实值'})[key],value===null?'':typeof value==='object'?JSON.stringify(value):value,key==='text'||key==='value',typeof value==='object'&&value!==null)}).join('')}</fieldset>`).join('')}`;
 }
 function importValue(doc,read=id=>document.getElementById(id)?.value){
  const value=clone(doc),metadata={label:'business-label',origin_ref:'business-origin',observed_at:'business-observed',valid_until:'business-valid'};
  for(const [key,id]of Object.entries(metadata)){const next=read(id);if(next!==undefined)value[key]=next}
  for(const [key,id]of Object.entries({platform:'business-platform',store_ref:'business-store',subject_ref:'business-subject'})){const next=read(id);if(next!==undefined)value.scope[key]=key==='store_ref'&&next===''?null:next}
  value.records=value.records.map((row,index)=>{for(const key of recordFields(value.kind)){if(row[key]!==null&&typeof row[key]==='object')continue;const next=read('business-record-'+index+'-'+key);if(next!==undefined){if(key==='rating')row[key]=next===''?null:Number(next);else if(key==='value'&&row.key==='quantity'&&next!==''){if(!/^\d+$/.test(next)||!Number.isSafeInteger(Number(next)))throw Error('business_invalid_quantity');row[key]=Number(next)}else if(key==='value'&&row[key]===null&&next==='')row[key]=null;else if(key==='value'&&typeof row[key]==='boolean'){if(!['true','false'].includes(next))throw Error('business_invalid_boolean');row[key]=next==='true'}else if(key==='value'&&typeof row[key]==='number'&&next.trim()!==''&&Number.isFinite(Number(next)))row[key]=Number(next);else row[key]=next}}return row});return value;
 }
 function choices(sources){return sources.flatMap(source=>source.document.kind==='facts'?source.document.records.map(row=>({source_id:source.id,key:row.key,label:`${source.document.label} · v${source.version} · ${labels[row.key]||row.key}`})):[])}
 function draftEditor(template,content,sources){
  const refs=choices(sources);
  return `<div class="business-field-editor">${Object.entries(template.required_fields).map(([key,type])=>{const value=content.fields[key],complex=value!==null&&typeof value==='object',citation=content.citations[key],selected=refs.findIndex(r=>r.source_id===citation?.source_id&&r.key===citation?.key);return `<section>${input('business-value-'+key,labels[key]||key,complex?JSON.stringify(value):value,type==='reply'||key==='description',complex)}${ui.field((labels[key]||key)+' · 依据',ui.select({id:'business-citation-'+key,value:selected<0?'':String(selected),options:[{value:'',label:'待补充依据'},...refs.map((r,index)=>({value:String(index),label:r.label}))]}))}${complex?'<p class="muted">结构化图片等复杂值可使用高级JSON编辑。</p>':''}</section>`}).join('')}</div>`;
 }
 function draftValue(template,content,sources,read=id=>document.getElementById(id)?.value){
  const result=clone(content),refs=choices(sources);
  for(const [key,type]of Object.entries(template.required_fields)){
   const next=read('business-value-'+key),original=result.fields[key];
   if(next!==undefined&&!(original!==null&&typeof original==='object')){
    if(next==='')delete result.fields[key];
    else if(type==='quantity'||type==='positive_quantity'){if(!/^\d+$/.test(next)||!Number.isSafeInteger(Number(next)))throw Error('business_invalid_quantity');result.fields[key]=Number(next)}
    else result.fields[key]=next;
   }
   const selected=read('business-citation-'+key);
   if(selected!==undefined){const ref=/^\d+$/.test(selected)?refs[Number(selected)]:null;if(ref)result.citations[key]={source_id:ref.source_id,key:ref.key};else delete result.citations[key]}
  }
  return result;
 }
 return {importEditor,importValue,draftEditor,draftValue};
};
