import { errorText } from './api';
const messages: Record<string,string> = {
  import_invalid_mapping: '字段映射有重复或不存在的CSV列，请核对列名。',
  import_idempotency_conflict: '此导入请求已有不同内容，请读取原批次。',
  import_source_changed: '导入预览版本不一致，请重新读取当前批次。',
  import_csv_filename_required: '请选择CSV文件，并保留.csv扩展名。',
  import_row_limit: 'CSV最多支持2000行，请检查表头和行数。',
  import_scope_mismatch: '导入批次与当前店铺范围不一致。',
  import_mode_mismatch: '合成与本机资料范围不一致，请核对当前数据模式。',
  workflow_cycle: '步骤依赖形成循环，请移除冲突连线。',
  workflow_invalid_edge: '依赖指向不存在的步骤，请核对画布。',
  memory_revision_conflict: '记忆已有新修订，请刷新核对；当前输入已保留。',
  memory_source_changed: '引用来源已变化或过期，请重新选择当前版本。',
  memory_quote_not_found: '引文不在所选记录原文中，请保留准确原文。',
  memory_scope_mismatch: '来源或事实属于不同对象范围，不能合并。',
  memory_fact_not_confirmed: '摘要只能使用当前有效且已确认的事实。',
};
export function adoptionErrorText(error:unknown) {
  return error instanceof Error&&messages[error.message] ? messages[error.message] : errorText(error);
}
