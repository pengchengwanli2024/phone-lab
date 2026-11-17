import { useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import { Badge, Button, Empty, ErrorNotice, Panel } from './ui';

type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export interface RegisteredMcpExtension {
  id: string; name: string; kind: string; version: number; enabled: boolean; test_status: string;
  definition_sha256?: string;
  definition: { kind: string; spec: { transport: string; [key: string]: JsonValue }; [key: string]: JsonValue };
}
export interface DiscoveredTool {
  name: string; description: string; inputSchema: JsonValue; extension_schema_supported: boolean;
  annotations?: Record<string, string | boolean>;
}
export interface ToolDiscoveryResult {
  extension_id: string; version: number; definition_sha256: string; catalog_sha256: string;
  protocol_version?: string; tools: DiscoveredTool[]; test_status: string; extension_enabled: boolean;
}
const discoveryErrors: Record<string, string> = {
  tool_discovery_definition_changed: '扩展定义或连接配置已变化，请重新选择当前登记版本后再发现。',
  tool_discovery_registration_unavailable: '当前登记项不可读取，请回能力库核对插件。',
  tool_discovery_registered_mcp_required: '请选择已登记的 MCP-HTTP 插件。',
  tool_discovery_busy: '工具目录发现正在处理其他请求，请稍后再试。',
  tool_discovery_timeout: '工具目录发现超时，尚未确认目录。',
  tool_discovery_probe_failed: '未能读取工具目录，请核对已登记插件的连接设置。',
  tool_discovery_tools_unavailable: '服务未声明工具目录能力。',
  tool_discovery_page_limit: '目录分页超出现有检查上限，未采纳不完整目录。',
  tool_discovery_catalog_limit: '工具目录超过现有数量或大小上限，未采纳不完整目录。',
  tool_discovery_hash_unavailable: '后台未提供可核对的原定义哈希，请重新读取或更新本机后台后重试。',
  tool_discovery_unsafe_number: '该定义含数值，当前客户端无法精确核对原 JSON 数值编码；请重新读取后台提供的定义哈希。',
  tool_discovery_redacted_definition: '当前返回定义经过脱敏，不能代替原定义哈希；请重新读取后台提供的定义哈希。',
};
export function toolDiscoveryError(error: unknown): string {
  const code = error instanceof Error ? error.message : '';
  return discoveryErrors[code] || (code.startsWith('tool_discovery_') ? '工具目录未能通过检查，请核对已登记插件。发现不会测试、启用或调用工具。' : errorText(error));
}
export function registeredMcpExtensions(items: RegisteredMcpExtension[]): RegisteredMcpExtension[] {
  return items.filter(item => item.kind === 'plugin' && item.definition?.kind === 'plugin' && item.definition?.spec?.transport === 'mcp_http');
}
function compareCodepoints(a: string, b: string): number {
  const left = Array.from(a, char => char.codePointAt(0)!), right = Array.from(b, char => char.codePointAt(0)!);
  for (let i = 0; i < Math.min(left.length, right.length); i++) if (left[i] !== right[i]) return left[i] - right[i];
  return left.length - right.length;
}
/** Match Python's sorted, UTF-8 JSON for values whose original numeric encoding was not lost by JSON.parse. */
export function exactDefinitionJson(value: JsonValue, depth = 0): string {
  if (depth > 24) throw new Error('tool_discovery_hash_unavailable');
  if (typeof value === 'number') throw new Error('tool_discovery_unsafe_number');
  if (typeof value === 'string') {
    if (value.includes('[redacted]') || value === '[bounded]') throw new Error('tool_discovery_redacted_definition');
    if (Array.from(value).some(char => { const code = char.codePointAt(0)!; return code >= 0xd800 && code <= 0xdfff; })) throw new Error('tool_discovery_hash_unavailable');
    return JSON.stringify(value);
  }
  if (value === null || typeof value === 'boolean') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(item => exactDefinitionJson(item, depth + 1)).join(',') + ']';
  if (typeof value !== 'object') throw new Error('tool_discovery_hash_unavailable');
  return '{' + Object.keys(value).sort(compareCodepoints).map(key => exactDefinitionJson(key, depth + 1) + ':' + exactDefinitionJson(value[key], depth + 1)).join(',') + '}';
}
export async function extensionDefinitionHash(extension: RegisteredMcpExtension): Promise<string> {
  if (extension.definition_sha256 && /^[a-f0-9]{64}$/.test(extension.definition_sha256)) return extension.definition_sha256;
  if (!globalThis.crypto?.subtle) throw new Error('tool_discovery_hash_unavailable');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(exactDefinitionJson(extension.definition)));
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
}
export function ToolDiscoveryCatalog({ result }: { result: ToolDiscoveryResult }) {
  return <div className="team-tool-catalog"><div className="team-heading-line"><h3>已读取的工具目录 · {result.tools.length}</h3><Badge>登记版本 {result.version}</Badge></div>
    <p className="team-muted">已完成 MCP 握手与目录读取。发现不等于测试或启用，服务端 annotations 不授予操作权限。</p>
    <dl className="team-catalog-hashes"><div><dt>原定义 SHA256</dt><dd>{result.definition_sha256}</dd></div><div><dt>目录 SHA256</dt><dd>{result.catalog_sha256}</dd></div>{result.protocol_version && <div><dt>协议版本</dt><dd>{result.protocol_version}</dd></div>}</dl>
    {result.tools.length ? result.tools.map(item => <article className="team-discovered-tool" key={item.name}><div className="team-heading-line"><h3>{item.name}</h3><Badge tone={item.extension_schema_supported ? 'gray' : 'warning'}>{item.extension_schema_supported ? '结构在现有扩展 Schema 子集内' : '复杂 Schema · 当前扩展不支持'}</Badge></div>
      <p className="r-readable">{item.description || '服务未提供描述。'}</p>
      <details><summary>输入 Schema（仅供审阅）</summary><pre className="r-readable">{JSON.stringify(item.inputSchema, null, 2)}</pre></details>
      {item.annotations && Object.keys(item.annotations).length > 0 && <details><summary>服务端 annotations（不代表授权）</summary><pre className="r-readable">{JSON.stringify(item.annotations, null, 2)}</pre></details>}
      <p className="team-muted">{item.extension_schema_supported ? '仍需在能力库登记准确工具并按现有流程测试；此处未确认工具可用。' : '仅展示元数据。需先调整为现有扩展支持的结构，不能直接登记为可用工具。'}</p>
    </article>) : <Empty>服务已返回目录，本次没有工具条目。</Empty>}
  </div>;
}

export function AssistantToolDiscovery({ active = true }: { active?: boolean }) {
  const [extensions, setExtensions] = useState<RegisteredMcpExtension[]>([]), [selectedId, setSelectedId] = useState('');
  const [selected, setSelected] = useState<RegisteredMcpExtension | null>(null), [definitionHash, setDefinitionHash] = useState('');
  const [result, setResult] = useState<ToolDiscoveryResult | null>(null), [error, setError] = useState('');
  const [loading, setLoading] = useState(false), [reading, setReading] = useState(false), [discovering, setDiscovering] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const mounted = useRef(false), activeRef = useRef(active), listVersion = useRef(0), selectionVersion = useRef(0), busy = useRef(false);
  activeRef.current = active;
  async function load() {
    const request = ++listVersion.current; setLoading(true); setError('');
    try {
      const response = await api<{ items: RegisteredMcpExtension[] }>('commerce_extension_list', { kind: 'plugin' });
      if (!mounted.current || !activeRef.current || request !== listVersion.current) return;
      setLoaded(true); setExtensions(registeredMcpExtensions(response.items)); setSelectedId(''); setSelected(null); setDefinitionHash(''); setResult(null); selectionVersion.current++;
    } catch (failure) { if (mounted.current && activeRef.current && request === listVersion.current) setError(toolDiscoveryError(failure)); }
    finally { if (mounted.current && request === listVersion.current) setLoading(false); }
  }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; listVersion.current++; selectionVersion.current++; }; }, []);
  useEffect(() => { if (active && !loaded) void load(); else if (active && selectedId && !selected) void choose(selectedId); if (!active) { listVersion.current++; selectionVersion.current++; setReading(false); setLoading(false); } }, [active]);
  async function choose(id: string) {
    const request = ++selectionVersion.current; setSelectedId(id); setSelected(null); setDefinitionHash(''); setResult(null); setError('');
    if (!id) return;
    setReading(true);
    try {
      const entry = await api<RegisteredMcpExtension>('commerce_extension_get', { extension_id: id });
      if (!registeredMcpExtensions([entry]).length || entry.id !== id) throw new Error('tool_discovery_registered_mcp_required');
      const hash = await extensionDefinitionHash(entry);
      if (!mounted.current || !activeRef.current || request !== selectionVersion.current) return;
      setSelected(entry); setDefinitionHash(hash);
    } catch (failure) { if (mounted.current && activeRef.current && request === selectionVersion.current) setError(toolDiscoveryError(failure)); }
    finally { if (mounted.current && request === selectionVersion.current) setReading(false); }
  }
  async function discover() {
    if (busy.current || !selected || !definitionHash || !activeRef.current) return;
    busy.current = true; setDiscovering(true); setError(''); setResult(null);
    const request = selectionVersion.current, entry = selected, hash = definitionHash;
    try {
      const response = await api<ToolDiscoveryResult>('commerce_extension_tools_discover', { extension_id: entry.id, expected_definition_sha256: hash });
      if (!mounted.current || !activeRef.current || request !== selectionVersion.current) return;
      if (response.extension_id !== entry.id || response.version !== entry.version || response.definition_sha256 !== hash) throw new Error('tool_discovery_definition_changed');
      setResult(response);
    } catch (failure) { if (mounted.current && activeRef.current && request === selectionVersion.current) setError(toolDiscoveryError(failure)); }
    finally { busy.current = false; if (mounted.current) setDiscovering(false); }
  }
  return <Panel title="发现已登记 MCP 工具" action={<Button disabled={loading || reading || discovering || !active} onClick={() => void load()}>重新读取登记项</Button>}>
    <ErrorNotice>{error}</ErrorNotice>
    <p className="team-muted">只读取已登记 MCP-HTTP 插件的工具目录。到能力库的“技能 → 插件”编辑并测试准确的注册工具；目录描述与 Schema 均为未授信的外部资料。</p>
    {loading ? <Empty>正在读取已登记插件…</Empty> : !loaded ? <Empty>插件登记表尚未读到，请重新读取。</Empty> : !extensions.length ? <Empty>尚无可读取目录的已登记 MCP-HTTP 插件。请先到能力库的插件编辑器完成登记。</Empty> : <div className="team-form"><label className="ui-field">已登记 MCP-HTTP 插件<select value={selectedId} disabled={discovering || !active} onChange={event => void choose(event.target.value)}><option value="">请选择扩展，不会自动连接</option>{extensions.map(item => <option key={item.id} value={item.id}>{item.name} · v{item.version}</option>)}</select></label>
      {reading && <p className="team-muted" role="status">正在核对原登记版本与定义哈希…</p>}
      {selected && <><p className="team-muted">登记版本 {selected.version} · {selected.enabled ? '原登记项已启用' : '原登记项未启用'} · 此操作不会改变启用或测试状态。</p><p className="team-hash">定义 SHA256：{definitionHash}</p></>}
      <Button primary disabled={!selected || !definitionHash || reading || discovering || !active} onClick={() => void discover()}>{discovering ? '正在读取工具目录…' : '发现此扩展的工具目录'}</Button>
    </div>}
    {result && <ToolDiscoveryCatalog result={result} />}
  </Panel>;
}
