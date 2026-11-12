/* Read-only navigation suggestions. Unknown evidence stays unknown. */
window.CommerceNextActions=(()=>{
 'use strict';
 const titles={overview:'总览',orders:'核对订单来源',products:'核对商品库存',operations:'补齐成本并测算',agent:'向运营角色提问',organization:'核对工作项资料',live:'核对Ozon来源',alerts:'查看经营提醒',research:'核对调研来源',creative:'准备创意草稿',intelligence:'查看公开情报',pilots:'打开商品试点',insights:'查看评论资料',support:'查看客服草稿',tasks:'查看共享任务',connections:'查阅业务知识',platforms:'核对平台接入',skills:'查看能力依据',exposure:'核对经营关联'};
 const routes={operations:['organization','alerts','agent','tasks'],orders:['live','operations','tasks','agent'],products:['live','operations','tasks','agent'],insights:['research','pilots','agent','tasks'],support:['orders','connections','agent','tasks'],research:['organization','intelligence','creative','tasks']};
 const record=value=>value&&typeof value==='object'&&!Array.isArray(value)?value:{};
 const action=(id,target,title,detail,tone='info')=>({id,target,title,detail,tone});
 function resourceState(available,fresh){
  if(available===true)return fresh===true?'fresh':fresh===false?'stale':'unknown';
  return available===false?'absent':'unknown';
 }
 function connectionAction(input){
  const l=record(input);
  if(l.configured===false)return action('connect-live','live','连接真实来源','先在私有向导配置连接，再核对读取范围。','warning');
  if(l.configured!==true)return null;
  if(l.scopeConfirmed===false)return action('review-scope','live','核对订单读取范围','连接已配置；范围尚未确认，请核对时间窗口和履约口径。','warning');
  const resources=[resourceState(l.ordersAvailable,l.ordersFresh),resourceState(l.stockAvailable,l.stockFresh)];
  if(resources.includes('stale'))return action('refresh-live','live','核对陈旧快照','已有来源已过有效期；核对范围后明确请求新的读取。','warning');
  if(typeof l.scopeConfirmed!=='boolean'||resources.includes('unknown'))return action('inspect-live','live','核对来源状态','部分范围或时间依据未知，请查看当前连接回执。');
  return null;
 }
 function overview(input){
  const rows=[],live=input.demo===false?connectionAction(input.live):null;
  if(live)rows.push(live);
  const statuses=Array.isArray(input.taskStatuses)?input.taskStatuses:[];
  if(statuses.some(s=>s==='failed'||s==='interrupted'))rows.push(action('inspect-failures','tasks','查看失败或中断任务','保留原回执，核对原因后再明确重试。','warning'));
  if(statuses.some(s=>s==='queued'||s==='running'))rows.push(action('inspect-tasks','tasks','查看共享待办','排队与运行不代表产物已交付或业务已完成。'));
  rows.push(action('open-pilot','pilots',titles.pilots,'从现有来源与资料缺项开始；不会创建库存或采购。'));
  return rows;
 }
 function plan(value){
  const input=record(value);
  if(input.loading===true||input.error===true||input.scopeCurrent===false)return [];
  const targets=Object.hasOwn(routes,input.tab)?routes[input.tab]:['pilots','organization','agent','tasks'];
  const rows=input.tab==='overview'?overview(input):targets.map(target=>action('open-'+target,target,titles[target],'核对当前资料与本地回执，按缺项继续；外部操作须另行确认。'));
  const available=new Set((Array.isArray(input.modules)?input.modules:Object.keys(titles)).filter(target=>Object.hasOwn(titles,target))),seen=new Set();
  return rows.filter(row=>{if(row.target===input.tab||!available.has(row.target)||seen.has(row.target))return false;seen.add(row.target);return true}).slice(0,4);
 }
 return Object.freeze({plan});
})();
