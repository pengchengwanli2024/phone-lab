import { createInvoke } from './transport.mjs';
let transport: ReturnType<typeof createInvoke> | undefined;
export function api<T>(tool: string, args: object = {}): Promise<T> {
  transport ??= createInvoke({ target: window, fetcher: window.fetch.bind(window) });
  return transport(tool, args) as Promise<T>;
}
const errors: Record<string, string> = {
  invalid_model_catalog: '模型列表未能读取，请刷新或检查连接。',
  agent_model_setup_required: '模型运行入口尚未配置，请在能力库的模型管理中完成配置。',
  agent_interrupted_no_automatic_resubmit: '回复已中断，未自动重发。核对原记录后可重新编辑问题。',
  market_research_revision_conflict: '研究任务已有新版本，请刷新核对后再继续。',
  market_research_not_found: '找不到这条研究任务，请核对任务入口。',
  agent_evidence_reference_required: '模型答复缺少来源引用，未采纳本轮结果；核对资料后可明确发送新问题。',
  authentication_required: '登录连接已过期，请从本机工作台入口重新打开。',
  unknown_tool: '当前后台尚未加载此功能，请更新服务后重试。',
  a2ui_revision_conflict: '其他窗口已更新这份测算。请读取最新版本；当前输入仍保留。',
  a2ui_dependency_missing: '动态表单所需的可选校验器未安装，已保留标准表单入口。',
  a2ui_disabled: '动态表单已关闭，请使用标准成本表单。',
  a2ui_case_mismatch: '此成本记录属于另一商品，请返回原商品继续。',
  a2ui_binding_required: '缺少当前商品与来源版本，请从商品工作区重新打开。',
  organization_case_not_found: '当前连接中找不到这个商品，请核对连接与对象范围。',
  workspace_currency_required: '请先在商品工作区明确成本币种，再进行同币种测算。',
  form_draft_conflict: '草稿已被其他窗口修改。请核对最新版本，当前输入仍保留。',
  workspace_source_changed: '商品依据已变化。请重新读取后核对，当前输入仍保留。',
  request_outcome_unknown: '本次请求未取得回执。请读取当前保存版本核对，勿直接重复提交。',
  idempotency_conflict: '此请求键已用于另一组输入，请读取原记录。',
  agent_not_configured: '尚未配置可用模型，请到 AI 运营检查本机模型路线。',
};
export function errorText(error: unknown) {
  const key = error instanceof Error ? error.message : 'request_failed';
  return errors[key] || (key.startsWith('invalid_') ? '输入格式或范围不正确，请核对相应字段。' : '操作未完成，请读取当前记录或检查连接。');
}
export const newKey = () => crypto.randomUUID();
