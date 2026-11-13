export interface ModelOption {
  id: string; label: string; engine: string; model?: string; provider?: string;
  revision: string; enabled: boolean; selectable: boolean; test_status: string;
  tested_revision?: string | null; base_url?: string; key_configured?: boolean;
}
export function modelReadiness(model: ModelOption) {
  if (model.engine === 'builtin') return model.selectable
    ? { label: '按请求检查', tone: 'gray' }
    : { label: '配置待修复', tone: 'warning' };
  if (model.test_status === 'unknown') return { label: '测试结果待核对', tone: 'warning' };
  if (model.test_status === 'failed') return { label: '测试未通过', tone: 'warning' };
  if (model.test_status === 'passed' && model.tested_revision === model.revision)
    return model.selectable && model.enabled
      ? { label: '已启用', tone: 'success' }
      : { label: '测试通过 · 未启用', tone: 'gray' };
  return { label: model.tested_revision ? '需重新测试' : '待测试', tone: 'warning' };
}
export function modelEngine(model: ModelOption) {
  const engines: Record<string, string> = { llama_cpp: 'llama.cpp', vllm: 'vLLM', custom: '自定义兼容服务' };
  if (model.engine !== 'builtin') return engines[model.engine] || model.engine;
  return ({ codex: 'Codex', codex_cli: 'Codex', hermes: 'Hermes' } as Record<string, string>)[model.provider || ''] || '项目默认';
}
