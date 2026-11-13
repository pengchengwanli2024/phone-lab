import { useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import type { ModelOption } from './model-catalog';
import { modelEngine, modelReadiness } from './model-catalog';
import { Badge, Button, Empty, ErrorNotice } from './ui';

export function Models({ active }: { active: boolean }) {
  const [models, setModels] = useState<ModelOption[]>([]), [loading, setLoading] = useState(true);
  const [query, setQuery] = useState(''), [error, setError] = useState(''), [message, setMessage] = useState(''), [opening, setOpening] = useState(false);
  const generation = useRef(0);
  async function load() {
    const version = ++generation.current; setLoading(true); setError('');
    try {
      const result = await api<{ models: ModelOption[] }>('commerce_model_list');
      if (!Array.isArray(result.models)) throw Error('invalid_model_catalog');
      if (version === generation.current) setModels(result.models);
    } catch (failure) { if (version === generation.current) { setModels([]); setError(errorText(failure)); } }
    finally { if (version === generation.current) setLoading(false); }
  }
  useEffect(() => { if (active) void load(); return () => { generation.current++; }; }, [active]);
  async function configure() {
    if (opening) return; setOpening(true); setError(''); setMessage('');
    try {
      const result = await api<{ opened: boolean }>('commerce_model_open_setup');
      if (result.opened) setMessage('已打开本机配置页，保存后刷新此列表。');
      else setError('尚未确认配置页已打开，请重试。');
    } catch (failure) { setError(errorText(failure)); }
    finally { setOpening(false); }
  }
  const term = query.trim().toLocaleLowerCase();
  const visible = models.filter(model => [model.label, model.model, modelEngine(model)].some(value => value?.toLocaleLowerCase().includes(term)));
  return <div className="r-page r-models">
    <div className="r-page-heading"><h1>模型管理</h1><div className="r-actions"><Button onClick={() => void load()} disabled={loading}>刷新列表</Button><Button primary onClick={() => void configure()} disabled={opening}>{opening ? '正在打开…' : '配置模型'}</Button></div></div>
    <ErrorNotice>{error}</ErrorNotice>{message && <p className="r-feedback" role="status">{message}</p>}
    <label className="ui-field r-model-search">查找模型<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="名称、模型 ID 或服务类型" /></label>
    {loading ? <Empty>正在读取模型…</Empty> : error && !models.length ? null : visible.length ? <section className="r-model-list" aria-label="已配置模型">{visible.map(model => {
      const state = modelReadiness(model);
      return <article className="r-model-row" key={model.id}>
        <div className="r-model-info"><h2>{model.label}</h2><p><span>{modelEngine(model)}</span><span>{model.model || '模型待核对'}</span></p>
          {model.engine !== 'builtin' && <details className="r-model-details"><summary>连接详情</summary><dl><div><dt>服务地址</dt><dd>{model.base_url || '待配置'}</dd></div><div><dt>配置版本</dt><dd>{model.revision}</dd></div><div><dt>凭据</dt><dd>{model.key_configured === true ? '已配置' : model.key_configured === false ? '未配置' : '待核对'}</dd></div></dl></details>}
        </div><Badge tone={state.tone}>{state.label}</Badge>
      </article>;
    })}</section> : <Empty>{term ? '没有匹配的模型。' : '尚无可读取的模型，添加配置后刷新。'}</Empty>}
    <p className="r-footnote">配置、测试和启停在本机配置页完成；对话中的模型选择按会话保留。</p>
  </div>;
}
