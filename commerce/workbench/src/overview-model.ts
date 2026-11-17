import type { Product, Task } from './types';
import type { SalesSummary, InventorySummary } from './operating-charts';

/** No interpolation or synthetic comparison: each point is one platform day. */
export function salesSeries(sales: SalesSummary | null | undefined, metric: 'amount' | 'units') {
  return (sales?.records || []).map(row => ({ day: row.day, value: metric === 'units' ? row.ordered_units : Number(row.amount) }));
}
export function salesPageContext(sales:SalesSummary|null|undefined,metric:'amount'|'units',demo=false) {
  return {section:'sales-trend',replace_filters:true,source:demo?'local':sales?(sales.stale?'stale':'live'):'unavailable',entity:{kind:'chart',id:metric==='amount'?'sales-trend':'sales-ordered-units',name:metric==='amount'?'下单金额':'下单件数'},filters:!demo&&sales?{platform:'ozon',store_id:'ozon-live',market:'RU',date_from:sales.date_from,date_to:sales.date_to}:{platform:'all',store_id:'all',market:'all'},source_refs:sales?.source_sha256?{sales:sales.source_sha256}:{}};
}
export function inventoryPageContext(inventory:InventorySummary|null|undefined,demo=false) {
  return {section:'inventory-statistics',replace_filters:true,source:demo?'local':inventory?(inventory.stale?'stale':'live'):'unavailable',entity:{kind:'chart',id:'inventory-statistics'},filters:!demo&&inventory?{platform:'ozon',store_id:'ozon-live',market:'RU'}:{platform:'all',store_id:'all',market:'all'},source_refs:inventory?.source_sha256?{stock:inventory.source_sha256}:{}};
}
const stageNames: Record<string,string> = {S1:'调研资料',S3:'成本资料',S2:'贡献测算',S4:'素材交付',S5:'字段校对',S6:'平台规则'};
export function coreStages(product?: Product) {
  return ['S1','S3','S2','S4','S5','S6'].map(id=>{
    const stage=product?.stages.find(row=>row.id===id);
    return {id,name:stageNames[id],detail:stage?.name||stageNames[id],status:stage?.status||'unread',label:!stage?'待读取':stage.status==='PASS'?'检查通过':stage.status==='HOLD'?'待补齐':stage.status==='FAIL'?'检查不符':stage.status==='BLOCKED'?'受阻':'状态待核对'};
  });
}
export function taskKind(task: Task) { const kinds:Record<string,string>={analysis:'分析',research:'研究',draft:'内容草稿',report:'简报',workflow:'工作流'};return kinds[task.kind] || '共享任务'; }
