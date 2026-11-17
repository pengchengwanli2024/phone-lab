/* Order handoff is data only. The service rechecks every snapshot before saving. */
window.CommerceOrderSupportContext=()=>{
 const copy=value=>JSON.parse(JSON.stringify(value));
 const businessScope=context=>({platform:context.scope.platform,store_ref:context.scope.store_id,subject_ref:context.order.order_id});
 const scopeKey=context=>JSON.stringify(Object.values(businessScope(context)));
 const eligible=(source,context)=>{const doc=source.document||source,s=businessScope(context);return ['conversation','facts'].includes(doc.kind)&&doc.synthetic===context.scope.demo&&doc.scope?.platform===s.platform&&doc.scope?.store_ref===s.store_ref&&doc.scope?.subject_ref===s.subject_ref};
 function receive(prepared){
  const c=prepared?.context,s=c?.scope,o=c?.order;
  if(prepared?.external_execution_allowed!==false||c?.schema!=='commerce-order-support-context-v1'||typeof s?.demo!=='boolean'||!['ozon','tiktok','amazon','mercado','temu','local'].includes(s.platform)||typeof s.store_id!=='string'||!s.store_id.trim()||s.store_id==='all'||!/^([A-Z]{2})$/.test(s.market)||typeof o?.id!=='string'||!o.id.trim()||typeof o.order_id!=='string'||!o.order_id.trim()||![o.source_sha256,o.record_sha256,c.context_sha256].every(v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v)))throw Error('order_support_invalid_context');
  return copy(c);
 }
 function selected(sources,context){
  if(!sources.some(s=>s.document.kind==='conversation'))throw Error('order_support_conversation_required');
  if(!sources.some(s=>s.document.kind==='facts'))throw Error('order_support_facts_required');
  for(const source of sources){
   if(!eligible(source,context))throw Error('order_support_scope_mismatch');
   if(!source.fresh)throw Error('order_support_source_stale');
   if(source.document.kind==='facts'){
    const facts=Object.fromEntries(source.document.records.map(row=>[row.key,row.value]));
    if(facts.order_ref!==context.order.order_id)throw Error('order_support_order_mismatch');
    if(facts.market!==context.scope.market)throw Error('order_support_market_mismatch');
   }
  }
 }
 function request(context,sources,content,previous){
  selected(sources,context);
  if(content.fields.conversation_ref!==context.order.order_id)throw Error('order_support_order_mismatch');
  return {context:copy(context),source_refs:sources.map(s=>({id:s.id,version:s.version,sha256:s.sha256})),content,
   ...(previous?{parent_id:previous.id,expected_parent_sha256:previous.draft.draft_sha256}:{})};
 }
 return {receive,businessScope,scopeKey,eligible,selected,request};
};
