import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, newKey } from './api';
import { Badge, Button, Dialog, Empty, ErrorNotice, Panel } from './ui';
import './assistant-team-automation.css';

export type TeamDispatchMode = 'all' | 'auto' | 'collaborate';
export interface TeamRouting {
  mode: TeamDispatchMode; lead_id?: string; mentions_only?: boolean;
  rules: { keywords: string[]; member_ids: string[] }[]; max_rounds: number;
}
export const teamModes: { value: TeamDispatchMode; label: string }[] = [
  { value: 'all', label: '全员独立回答' }, { value: 'auto', label: '自动选择成员' }, { value: 'collaborate', label: '顺序协作并汇总' },
];
export const teamModeLabel = (mode?: string) => teamModes.find(item => item.value === mode)?.label || '全员独立回答';
export function teamKeywords(value: string): string[] {
  const seen = new Set<string>();
  return value.split(/[,，、\n]/).map(item => item.trim()).filter(item => { const key = item.toLocaleLowerCase(); if (!item || seen.has(key)) return false; seen.add(key); return true; });
}
export function teamKeywordValidation(values: string[]): string {
  return values.length > 16 ? '最多填写 16 个不同关键词，请精简后保存。' : values.some(value => Array.from(value).length > 40) ? '每个关键词最多 40 字，请精简后保存。' : values.some(value => /[\u0000-\u001f\u007f]/.test(value)) ? '关键词不能包含控制字符，请移除后保存。' : '';
}
export function teamRoutingValidation(value: TeamRouting): string {
  if (value.mentions_only !== undefined && typeof value.mentions_only !== 'boolean') return '仅响应点名设置须为启用或停用。';
  if (value.rules.length > 12) return '最多保存 12 条路由规则。';
  for (const rule of value.rules) { const invalid = teamKeywordValidation(rule.keywords); if (invalid) return invalid; if (!rule.keywords.length || !rule.member_ids.length) return '每条规则需要至少一个关键词与一位频道成员。'; }
  return '';
}
export function teamRoutingForMembers(routing: TeamRouting, memberIds: string[]): TeamRouting {
  return { ...routing, lead_id: memberIds.includes(routing.lead_id || '') ? routing.lead_id : undefined,
    rules: routing.rules.map(rule => ({ ...rule, keywords: [...rule.keywords], member_ids: rule.member_ids.filter(id => memberIds.includes(id)) })) };
}
export function TeamKeywordInput({ value, onChange, label, placeholder }: { value: string[]; onChange: (value: string[]) => void; label: string; placeholder?: string }) {
  const [text, setText] = useState(value.join('、')), emitted = useRef(JSON.stringify(value));
  const signature = JSON.stringify(value);
  useEffect(() => { if (signature !== emitted.current) { emitted.current = signature; setText(value.join('、')); } }, [signature]);
  return <label className="ui-field">{label}<input value={text} maxLength={1000} placeholder={placeholder || '用逗号或顿号分隔'} onChange={event => { const next = teamKeywords(event.target.value); emitted.current = JSON.stringify(next); setText(event.target.value); onChange(next); }} />{teamKeywordValidation(value) && <span className="team-field-error">{teamKeywordValidation(value)}</span>}</label>;
}
export function TeamRoutingEditor({ value, members, onChange }: { value: TeamRouting; members: { id: string; name: string }[]; onChange: (value: TeamRouting) => void }) {
  return <fieldset className="team-routing"><legend>频道响应方式</legend>
    <label className="ui-field">默认模式<select value={value.mode} onChange={event => onChange({ ...value, mode: event.target.value as TeamDispatchMode })}>{teamModes.map(mode => <option key={mode.value} value={mode.value}>{mode.label}</option>)}</select></label>
    {value.mode === 'auto' && <label className="team-check"><input type="checkbox" checked={value.mentions_only === true} onChange={event => onChange({ ...value, mentions_only: event.target.checked })} />自动模式仅响应点名</label>}
    <label className="ui-field">主责成员<select value={value.lead_id || ''} onChange={event => onChange({ ...value, lead_id: event.target.value || undefined })}><option value="">由频道成员顺序确定</option>{members.map(member => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>
    <label className="ui-field">协作轮数<select value={value.max_rounds} onChange={event => onChange({ ...value, max_rounds: Number(event.target.value) })}>{[1, 2, 3].map(round => <option key={round} value={round}>{round} 轮</option>)}</select></label>
    <p className="team-muted">{value.mode === 'auto' && value.mentions_only ? '自动模式需明确使用 @成员名称 或 @all 点名，未点名不会调用模型。' : '自动模式按明确提及、关键词规则、成员专长选择回答者。'}顺序协作在成员贡献后由主责成员汇总；遇到待补充、失败或未确认结果会暂停。</p>
    {value.rules.map((rule, index) => <div className="team-routing-rule" key={index}>
      <TeamKeywordInput label={'规则 ' + (index + 1) + ' · 关键词'} value={rule.keywords} onChange={keywords => onChange({ ...value, rules: value.rules.map((item, position) => position === index ? { ...item, keywords } : item) })} />
      <fieldset className="team-member-picker"><legend>匹配后参与的成员</legend>{members.map(member => <label className="team-check" key={member.id}><input type="checkbox" checked={rule.member_ids.includes(member.id)} onChange={event => onChange({ ...value, rules: value.rules.map((item, position) => position === index ? { ...item, member_ids: event.target.checked ? [...item.member_ids, member.id] : item.member_ids.filter(id => id !== member.id) } : item) })} />{member.name}</label>)}</fieldset>
      <Button onClick={() => onChange({ ...value, rules: value.rules.filter((_, position) => position !== index) })}>移除规则 {index + 1}</Button>
    </div>)}
    <Button disabled={value.rules.length >= 12 || !members.length} onClick={() => onChange({ ...value, rules: [...value.rules, { keywords: [], member_ids: [] }] })}>添加关键词规则</Button>
  </fieldset>;
}

export type TeamTriggerKind = 'manual' | 'once' | 'interval' | 'weekly' | 'webhook' | 'after_discussion';
export interface TeamTriggerEvent {
  id?: string; event_id?: string; created?: string | number; status: string; discussion_id?: string | null; error?: string | null;
}
export interface TeamTriggerInput {
  id?: string; name: string; kind: TeamTriggerKind; channel_id: string; channel_revision: number; question: string;
  dispatch_mode: TeamDispatchMode; max_rounds: number; playbook_key?: string;
  schedule: { at?: string; start_at?: string; interval_seconds?: number; weekday?: number; time?: string; timezone?: string; discussion_id?: string };
}
export interface TeamTrigger extends TeamTriggerInput {
  id: string; revision: number; enabled: boolean; error?: string | null; history?: TeamTriggerEvent[];
  next_at?: string | number | null; last_discussion_id?: string | null;
}
interface TriggerChannel { id: string; revision: number; name: string; routing?: TeamRouting; playbook_key?: string }
export const triggerKinds: { value: TeamTriggerKind; label: string }[] = [
  { value: 'manual', label: '手动' }, { value: 'once', label: '一次定时' }, { value: 'interval', label: '固定间隔' },
  { value: 'weekly', label: '每周' }, { value: 'webhook', label: '本机事件' }, { value: 'after_discussion', label: '讨论结束后' },
];
const triggerErrorMessages: Record<string, string> = {
  team_revision_changed: '记录已被其他窗口更新。请读取最新状态后核对，当前输入已保留。',
  team_revision_conflict: '记录已被其他窗口更新。请读取最新状态后核对，当前输入已保留。',
  team_trigger_revision_changed: '触发器修订已变化，请刷新并核对。',
  team_trigger_not_found: '找不到此触发器，请刷新列表。',
  team_trigger_invalid: '触发器配置不正确，请核对问题、频道和时间。',
  team_invalid_trigger: '触发器配置不正确，请核对问题、频道和时间。',
  team_trigger_disabled: '触发器尚未启用，请核对配置后明确启用。',
  team_trigger_invalid_time: '执行时间无效，请核对日期与时区。',
  team_trigger_invalid_schedule: '时间配置无效。定时时间需包含秒和时区偏移；间隔为 60 至 604800 整数秒。',
  team_trigger_invalid_definition: '触发器配置不完整，请核对名称、频道、问题和响应方式。',
  team_trigger_invalid_name: '名称不能为空，最多 80 字。',
  team_trigger_invalid_question: '问题不能为空，最多 2000 字。',
  team_trigger_invalid_kind: '触发方式不适用于此操作，请核对触发器类型。',
  team_trigger_invalid_playbook: '工作剧本标识不正确，请重新选择已导入的剧本。',
  team_trigger_playbook_not_found: '此频道中找不到所选工作剧本，请核对预设与频道归属。',
  team_trigger_profile_disabled: '频道包含未启用成员。自动触发需要全部成员已启用并配置模型。',
  team_trigger_model_unavailable: '频道成员的绑定模型当前不可用，请核对模型后重新保存并启用。',
  team_trigger_channel_not_found: '找不到所绑定的频道，请刷新列表并重新选择。',
  team_trigger_source_not_found: '找不到绑定的原讨论，请核对讨论编号。',
  team_trigger_source_unknown: '原讨论结果尚未确认，本次触发受阻；请先核对原讨论。',
  team_trigger_channel_busy: '频道已有未结束或待核对讨论，本次事件已跳过。',
  team_trigger_slot_missed: '已错过执行时段，本次事件已跳过，不会补发。',
  team_trigger_dispatch_rejected: '讨论请求未通过执行校验，请核对配置与原事件记录。',
  team_trigger_dispatch_unknown: '讨论派发结果尚未确认。请先核对原事件与讨论，不要新建重复请求。',
  team_trigger_recovered_unknown: '服务恢复后，此事件的原派发结果尚未确认；未自动重发。',
  team_trigger_invalid_payload: '事件内容不符合要求。请使用不含凭据的 JSON 对象，最多 8192 字节、4 层深度和 128 个数据项。',
  team_trigger_invalid_event_id: '事件编号不能为空，最多 160 字，且不能包含控制字符。',
  team_trigger_event_conflict: '该事件编号已有不同内容，请读取原记录；新事件应使用独立编号。',
  team_trigger_event_limit: '此触发器已达到事件数量上限，已停止新增事件。',
  team_trigger_limit_reached: '触发器已达到 100 个上限，请核对已有配置。',
  team_trigger_not_ready: '触发前置条件未就绪，请核对成员、模型、频道和原事件记录。',
  team_trigger_channel_changed: '频道修订已变化。触发器已暂停，请编辑并明确绑定当前修订。',
  team_trigger_source_changed: '原配置已变化。触发器已暂停，请核对后重新保存。',
  team_model_required: '频道成员尚未完成模型配置。请先配置成员，再启用触发器。',
};
export function teamTriggerError(value: unknown): string {
  const code = typeof value === 'string' ? value : value instanceof Error ? value.message : '';
  return triggerErrorMessages[code] || '此操作未取得确认。请读取原触发器与事件记录，核对后再继续；不会自动重发模型请求。';
}
export function teamTriggerStatus(status: string): string {
  return ({ dispatched: '已派发 · 待查看讨论', skipped: '已跳过', blocked: '受阻', failed: '失败', unknown: '结果未确认' } as Record<string, string>)[status] || '未识别状态（' + status + '）';
}
export function teamTriggerTime(value?: string | number | null): string {
  if (value == null || value === '') return '未安排';
  const date = new Date(typeof value === 'number' && value < 100000000000 ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? '时间待核对' : date.toISOString().replace('T', ' ').replace(/(?:\.000)?Z$/, ' UTC');
}
export function teamTriggerValidation(draft: TeamTriggerInput): string {
  if (!draft.name.trim() || !draft.channel_id || !draft.question.trim()) return '请填写名称、频道和问题。';
  if (draft.max_rounds < 1 || draft.max_rounds > 3 || !Number.isInteger(draft.max_rounds)) return '协作轮数须为 1 至 3。';
  const offsetISO = (value?: string) => !!value && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value) && Number(value.slice(0, 4)) >= 2000 && Number(value.slice(0, 4)) <= 2100 && !Number.isNaN(Date.parse(value));
  if (draft.kind === 'once' && !offsetISO(draft.schedule.at)) return '请填写带时区偏移的一次执行时间，例如 2027-01-01T09:00:00+08:00。';
  if (draft.kind === 'interval' && (!offsetISO(draft.schedule.start_at) || !Number.isInteger(draft.schedule.interval_seconds) || draft.schedule.interval_seconds! < 60 || draft.schedule.interval_seconds! > 604800)) return '间隔触发需要带时区偏移的开始时间，以及 60 至 604800 的整数秒间隔。';
  if (draft.kind === 'weekly') {
    if (!Number.isInteger(draft.schedule.weekday) || draft.schedule.weekday! < 0 || draft.schedule.weekday! > 6 || !/^([01]\d|2[0-3]):[0-5]\d$/.test(draft.schedule.time || '')) return '请选择每周日期并填写有效的 HH:MM 时间。';
    try { if (!draft.schedule.timezone) return '请填写 IANA 时区，例如 Asia/Shanghai。'; new Intl.DateTimeFormat('zh-CN', { timeZone: draft.schedule.timezone }).format(); } catch { return '请填写有效的 IANA 时区，例如 Asia/Shanghai。'; }
  }
  if (draft.kind === 'after_discussion' && !draft.schedule.discussion_id?.trim()) return '请填写原讨论编号。';
  return '';
}
export function teamTriggerRequest(draft: TeamTriggerInput): TeamTriggerInput {
  const schedule = draft.kind === 'once' ? { at: draft.schedule.at } : draft.kind === 'interval' ? { start_at: draft.schedule.start_at, interval_seconds: draft.schedule.interval_seconds } : draft.kind === 'weekly' ? { weekday: draft.schedule.weekday, time: draft.schedule.time, timezone: draft.schedule.timezone } : draft.kind === 'after_discussion' ? { discussion_id: draft.schedule.discussion_id?.trim() } : {};
  return { ...(draft.id ? { id: draft.id } : {}), name: draft.name.trim(), kind: draft.kind, channel_id: draft.channel_id, channel_revision: draft.channel_revision, question: draft.question.trim(), dispatch_mode: draft.dispatch_mode, max_rounds: draft.max_rounds, ...(draft.playbook_key ? { playbook_key: draft.playbook_key } : {}), schedule };
}
function freshTrigger(channels: TriggerChannel[]): TeamTriggerInput {
  const channel = channels[0];
  return { name: '', kind: 'manual', channel_id: channel?.id || '', channel_revision: channel?.revision || 1, question: '', dispatch_mode: channel?.routing?.mode || 'auto', max_rounds: channel?.routing?.max_rounds || 1, playbook_key: channel?.playbook_key, schedule: {} };
}
export function TeamTriggerHistory({ events, onDiscussion }: { events: TeamTriggerEvent[]; onDiscussion: (id: string) => void }) {
  return events.length ? <ol className="team-trigger-history">{events.map((event, index) => <li key={event.id || event.event_id || index}><Badge tone={event.status === 'dispatched' ? 'gray' : 'warning'}>{teamTriggerStatus(event.status)}</Badge><span className="team-muted">{event.created == null ? '' : teamTriggerTime(event.created)}</span>{event.error && <p className="team-field-error">{teamTriggerError(event.error)}</p>}{event.discussion_id && <Button onClick={() => onDiscussion(event.discussion_id!)}>读取原讨论</Button>}</li>)}</ol> : <Empty>尚无事件记录。事件派发不代表模型讨论已完成。</Empty>;
}

export function AssistantTeamAutomation({ channels, active, onDiscussion, playbooks = [] }: { channels: TriggerChannel[]; active: boolean; onDiscussion: (id: string) => void; playbooks?: { key: string; name: string; channel_id?: string }[] }) {
  const [items, setItems] = useState<TeamTrigger[]>([]), [selected, setSelected] = useState<TeamTrigger | null>(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(''), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [editor, setEditor] = useState<{ draft: TeamTriggerInput; original?: TeamTrigger } | null>(null), [editorError, setEditorError] = useState('');
  const [eventId, setEventId] = useState(''), [payload, setPayload] = useState('{}');
  const alive = useRef(false), version = useRef(0), selection = useRef(0), locked = useRef(false), keys = useRef(new Map<string, string>());
  const availablePlaybooks = playbooks.filter(item => !item.channel_id || item.channel_id === editor?.draft.channel_id);
  async function load() {
    const request = ++version.current; setLoading(true); setError('');
    try { const result = await api<{ triggers: TeamTrigger[] }>('commerce_assistant_team_trigger_list'); if (alive.current && request === version.current) { setItems(result.triggers); setSelected(current => current ? result.triggers.find(item => item.id === current.id) || null : null); } }
    catch (failure) { if (alive.current && request === version.current) setError(teamTriggerError(failure)); }
    finally { if (alive.current && request === version.current) setLoading(false); }
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; version.current++; selection.current++; }; }, []);
  useEffect(() => { if (active) void load(); else { version.current++; selection.current++; } }, [active]);
  async function read(id: string) {
    const request = ++selection.current;
    try { const result = await api<TeamTrigger>('commerce_assistant_team_trigger_get', { trigger_id: id }); if (alive.current && request === selection.current) { setSelected(result); setEventId(''); setPayload('{}'); setError(''); } }
    catch (failure) { if (alive.current && request === selection.current) setError(teamTriggerError(failure)); }
  }
  async function mutate(name: string, action: () => Promise<void>, showError = setError) {
    if (locked.current) return; locked.current = true; setBusy(name); showError(''); setNotice('');
    try { await action(); } catch (failure) { if (alive.current) showError(teamTriggerError(failure)); } finally { locked.current = false; if (alive.current) setBusy(''); }
  }
  function save(event: FormEvent) {
    event.preventDefault(); if (!editor) return;
    const invalid = teamTriggerValidation(editor.draft); if (invalid) { setEditorError(invalid); return; }
    const current = editor;
    void mutate('save', async () => { const result = await api<TeamTrigger>('commerce_assistant_team_trigger_save', { trigger: teamTriggerRequest(current.draft), ...(current.original ? { expected_revision: current.original.revision } : {}) }); if (!alive.current) return; setEditor(null); setSelected(result); setNotice('配置已保存为暂停状态。启用或执行需要单独点击，可能产生模型调用。'); await load(); }, setEditorError);
  }
  function enable(item: TeamTrigger) {
    void mutate('enable', async () => { const result = await api<TeamTrigger>('commerce_assistant_team_trigger_enable', { trigger_id: item.id, expected_revision: item.revision, enabled: !item.enabled }); if (!alive.current) return; setSelected(result); setNotice(result.enabled ? '触发器已启用，满足条件时可能发起模型讨论。请通过事件与原讨论核对结果。' : '触发器已暂停。已派发的原讨论仍需在讨论记录中查看或取消。'); await load(); });
  }
  function dispatch(item: TeamTrigger, webhook: boolean) {
    let parsed: unknown;
    if (webhook && new TextEncoder().encode(payload).byteLength > 8192) { setError('事件内容超过 8192 字节，请精简后再提交。'); return; }
    if (webhook) { if (!eventId.trim()) { setError('请填写用于去重的事件编号。'); return; } try { parsed = JSON.parse(payload); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) { setError('事件内容须为 JSON 对象。'); return; } } catch { setError('事件内容须为有效的 JSON 对象。'); return; } }
    const signature = JSON.stringify([item.id, item.revision, webhook ? eventId.trim() : 'run', webhook ? parsed : null]);
    let key = keys.current.get(signature); if (!key) { key = newKey(); keys.current.set(signature, key); }
    const args = { trigger_id: item.id, expected_revision: item.revision, ...(webhook ? { event_id: eventId.trim(), payload: parsed } : { idempotency_key: key }) };
    void mutate('dispatch', async () => {
      const event = await api<TeamTriggerEvent>('commerce_assistant_team_trigger_' + (webhook ? 'event' : 'run'), args);
      if (!alive.current) return;
      setSelected(current => current?.id === item.id ? { ...current, history: [event, ...(current.history || [])].slice(0, 20) } : current);
      if (event.status !== 'unknown') keys.current.delete(signature);
      setNotice(teamTriggerStatus(event.status) + '。请读取原讨论确认执行进度。');
      await load(); await read(item.id);
    });
  }
  return <div className="team-automation"><Panel title="触发器" action={<div className="r-actions"><Button disabled={!!busy || loading} onClick={() => void load()}>刷新触发器</Button><Button primary disabled={!!busy || !channels.length} onClick={() => { setEditorError(''); setEditor({ draft: freshTrigger(channels) }); }}>新建触发器</Button></div>}>
    <p className="team-muted">保存始终暂停。启用后，定时或事件条件可发起有界模型讨论；派发回执与讨论完成分别展示。</p><ErrorNotice>{error}</ErrorNotice>{notice && <p role="status" className="team-feedback">{notice}</p>}
    {loading && !items.length ? <Empty>正在读取触发器…</Empty> : items.length ? <div className="team-trigger-list">{items.map(item => <article key={item.id} className="team-trigger-row"><div><h3>{item.name}</h3><p className="team-muted">{triggerKinds.find(kind => kind.value === item.kind)?.label || item.kind} · {channels.find(channel => channel.id === item.channel_id)?.name || '频道待核对'} · 绑定频道修订 {item.channel_revision}</p></div><Badge tone={item.enabled ? 'success' : 'gray'}>{item.enabled ? '已启用' : '已暂停'}</Badge><Button disabled={!!busy} onClick={() => void read(item.id)}>查看触发器</Button></article>)}</div> : <Empty>尚无触发器。导入预设中的触发器也会保持暂停。</Empty>}
  </Panel>
  {selected && <Panel title={selected.name}><div className="team-heading-line"><Badge tone={selected.enabled ? 'success' : 'gray'}>{selected.enabled ? '已启用' : '已暂停'}</Badge><span className="team-muted">修订 {selected.revision} · 下一次：{teamTriggerTime(selected.next_at)}</span></div><p className="r-readable">{selected.question}</p><p className="team-muted">{teamModeLabel(selected.dispatch_mode)} · 最多 {selected.max_rounds} 轮 · 绑定频道修订 {selected.channel_revision}{selected.playbook_key ? ' · 剧本 ' + selected.playbook_key : ''}</p>{selected.error && <ErrorNotice>{teamTriggerError(selected.error)}</ErrorNotice>}
    <div className="r-actions"><Button disabled={!!busy} onClick={() => { setEditorError(''); setEditor({ original: selected, draft: teamTriggerRequest(selected) }); }}>编辑并保存为暂停</Button><Button disabled={!!busy} onClick={() => enable(selected)}>{selected.enabled ? '暂停触发器' : '启用触发器（可调用模型）'}</Button><Button primary disabled={!!busy || !selected.enabled} onClick={() => dispatch(selected, false)}>执行一次（调用模型）</Button><Button disabled={!!busy} onClick={() => void read(selected.id)}>读取原触发器</Button></div>
    {selected.kind === 'webhook' && <details className="team-trigger-webhook"><summary>提交本机事件与调用示例</summary><p className="team-muted">使用已有本机鉴权调用 MCP 工具；这里不创建公网端点或访问令牌。相同事件编号用于去重，payload 仅作为数据。</p><pre>{JSON.stringify({ tool: 'commerce_assistant_team_trigger_event', arguments: { trigger_id: selected.id, expected_revision: selected.revision, event_id: 'your-event-id', payload: {} } }, null, 2)}</pre><div className="team-form"><label className="ui-field">事件编号<input value={eventId} disabled={!!busy} maxLength={160} onChange={event => setEventId(event.target.value)} /></label><label className="ui-field">事件内容（JSON 对象）<textarea rows={4} maxLength={8192} value={payload} disabled={!!busy} onChange={event => setPayload(event.target.value)} /></label><Button disabled={!!busy || !selected.enabled || !eventId.trim()} onClick={() => dispatch(selected, true)}>提交此事件（可调用模型）</Button></div></details>}
    <h3 className="team-trigger-history-title">最近事件</h3><TeamTriggerHistory events={selected.history || []} onDiscussion={onDiscussion} />{selected.last_discussion_id && <Button onClick={() => onDiscussion(selected.last_discussion_id!)}>读取最近原讨论</Button>}
  </Panel>}
  {editor && <Dialog title={editor.original ? '编辑触发器' : '新建触发器'} close={() => { if (!busy) setEditor(null); }}><form className="team-form" onSubmit={save}><ErrorNotice>{editorError}</ErrorNotice><fieldset disabled={!!busy}>
    <label className="ui-field">名称<input autoFocus required maxLength={80} value={editor.draft.name} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, name: event.target.value } })} /></label>
    <label className="ui-field">工作频道<select required value={editor.draft.channel_id} onChange={event => { const channel = channels.find(item => item.id === event.target.value); setEditor({ ...editor, draft: { ...editor.draft, channel_id: event.target.value, channel_revision: channel?.revision || 1, playbook_key: channel?.playbook_key, dispatch_mode: channel?.routing?.mode || 'auto', max_rounds: channel?.routing?.max_rounds || 1 } }); }}><option value="">请选择频道</option>{channels.map(channel => <option key={channel.id} value={channel.id}>{channel.name} · 修订 {channel.revision}</option>)}</select></label>
    <p className="team-muted">当前绑定修订 {editor.draft.channel_revision}。<Button onClick={() => { const channel = channels.find(item => item.id === editor.draft.channel_id); if (channel) setEditor({ ...editor, draft: { ...editor.draft, channel_revision: channel.revision } }); }}>明确绑定频道当前修订</Button></p>
    <label className="ui-field">触发方式<select value={editor.draft.kind} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, kind: event.target.value as TeamTriggerKind, schedule: event.target.value === 'weekly' ? { weekday: 0, time: '09:00', timezone: 'Asia/Shanghai' } : event.target.value === 'interval' ? { interval_seconds: 3600, start_at: '' } : {} } })}>{triggerKinds.map(kind => <option key={kind.value} value={kind.value}>{kind.label}</option>)}</select></label>
    {editor.draft.kind === 'once' && <label className="ui-field">执行时间（带时区偏移 ISO）<input required value={editor.draft.schedule.at || ''} placeholder="2027-01-01T09:00:00+08:00" onChange={event => setEditor({ ...editor, draft: { ...editor.draft, schedule: { at: event.target.value } } })} /></label>}
    {editor.draft.kind === 'interval' && <><label className="ui-field">开始时间（带时区偏移 ISO）<input required value={editor.draft.schedule.start_at || ''} placeholder="2027-01-01T09:00:00+08:00" onChange={event => setEditor({ ...editor, draft: { ...editor.draft, schedule: { ...editor.draft.schedule, start_at: event.target.value } } })} /></label><label className="ui-field">间隔秒数<input type="number" min={60} max={604800} step={1} required value={editor.draft.schedule.interval_seconds ?? 3600} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, schedule: { ...editor.draft.schedule, interval_seconds: Number(event.target.value) } } })} /></label></>}
    {editor.draft.kind === 'weekly' && <><label className="ui-field">星期<select value={editor.draft.schedule.weekday ?? 0} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, schedule: { ...editor.draft.schedule, weekday: Number(event.target.value) } } })}>{['一', '二', '三', '四', '五', '六', '日'].map((day, index) => <option key={day} value={index}>星期{day}</option>)}</select></label><label className="ui-field">当地时间<input type="time" required value={editor.draft.schedule.time || ''} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, schedule: { ...editor.draft.schedule, time: event.target.value } } })} /></label><label className="ui-field">IANA 时区<input required value={editor.draft.schedule.timezone || ''} placeholder="Asia/Shanghai" onChange={event => setEditor({ ...editor, draft: { ...editor.draft, schedule: { ...editor.draft.schedule, timezone: event.target.value } } })} /></label></>}
    {editor.draft.kind === 'after_discussion' && <label className="ui-field">原讨论编号<input required value={editor.draft.schedule.discussion_id || ''} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, schedule: { discussion_id: event.target.value } } })} /></label>}
    <label className="ui-field">问题<textarea required maxLength={2000} rows={4} value={editor.draft.question} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, question: event.target.value } })} /></label>
    <label className="ui-field">响应方式<select value={editor.draft.dispatch_mode} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, dispatch_mode: event.target.value as TeamDispatchMode } })}>{teamModes.map(mode => <option key={mode.value} value={mode.value}>{mode.label}</option>)}</select></label>
    <label className="ui-field">最多协作轮数<select value={editor.draft.max_rounds} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, max_rounds: Number(event.target.value) } })}>{[1, 2, 3].map(round => <option key={round} value={round}>{round}</option>)}</select></label>
    <label className="ui-field">工作剧本<select value={editor.draft.playbook_key || ''} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, playbook_key: event.target.value || undefined } })}><option value="">使用频道默认剧本</option>{availablePlaybooks.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}{editor.draft.playbook_key && !availablePlaybooks.some(item => item.key === editor.draft.playbook_key) && <option value={editor.draft.playbook_key}>{editor.draft.playbook_key}（已保存）</option>}</select></label>
    <p className="team-muted">保存不会调用模型，所有新增和编辑均回到暂停状态。</p><div className="r-form-actions"><Button primary type="submit">保存为暂停</Button><Button onClick={() => setEditor(null)}>取消</Button></div>
  </fieldset></form></Dialog>}
  </div>;
}

export interface TeamPackage {
  schema: 'phone-lab-team-v1' | 'phone-lab-team-v2'; name: string; instructions?: string; chief_key?: string | null;
  profiles: { key: string; name: string; role_id: string; instructions: string; expertise?: string[]; playbook_keys?: string[]; skill_keys?: string[]; connector_keys?: string[] }[];
  channels: { key?: string; name: string; instructions: string; members: string[]; routing?: { mode: TeamDispatchMode; rules: { keywords: string[]; member_keys: string[] }[]; max_rounds: number }; responder?: { kind: string; member_key?: string }; lead_key?: string | null; playbook_key?: string | null }[];
  playbooks?: { key: string; name: string; instructions: string; triggers: string[] }[];
  starter_notes?: { profile_key: string; name: string; content: string }[];
  skills?: { key: string; name: string; description: string; instructions: string }[];
  connector_requirements?: { key: string; label: string; reason: string; optional: boolean; status: 'unconfigured' }[];
  triggers?: ({ key: string; name: string; channel_key: string; kind: TeamTriggerKind; question: string; dispatch_mode: TeamDispatchMode; max_rounds: number; playbook_key?: string; schedule: TeamTriggerInput['schedule']; enabled: false } | { key: string; name: string; channel_key: null; kind: 'deferred'; reason: string; source_spec?: unknown })[];
}
export interface TeamPreset {
  id: string; name: string; package: TeamPackage; profile_map: Record<string, string>; channel_map: Record<string, string>; created: string | number;
}
export function teamPresetPlaybooks(presets: TeamPreset[], channelId?: string): { key: string; name: string }[] {
  const found = new Map<string, { key: string; name: string }>();
  for (const preset of presets) {
    if (channelId && !Object.values(preset.channel_map).includes(channelId)) continue;
    for (const item of preset.package.playbooks || []) if (!found.has(item.key)) found.set(item.key, { key: item.key, name: preset.name + ' · ' + item.name });
  }
  return [...found.values()];
}
export function TeamPackageContents({ value }: { value: TeamPackage }) {
  const profileName = (key?: string | null) => value.profiles.find(profile => profile.key === key)?.name || key || '未设置';
  return <div className="team-preset">
    {value.instructions && <section className="team-preset-section"><h4>团队指令</h4><p className="r-readable team-preset-long" tabIndex={0} aria-label="完整团队指令">{value.instructions}</p></section>}
    {value.chief_key && <p className="team-muted">主责成员：{profileName(value.chief_key)}</p>}
    <details><summary>完整成员与频道配置 · {value.profiles.length} 位成员 / {value.channels.length} 个频道</summary>
      {value.profiles.map(profile => <div key={profile.key}><h4>{profile.name} · {profile.role_id}</h4><p className="r-readable team-preset-long" tabIndex={0} aria-label={profile.name + '完整角色指令'}>{profile.instructions || '未设置角色指令。'}</p>{!!profile.expertise?.length && <p className="team-muted">专长：{profile.expertise.join('、')}</p>}{!!profile.playbook_keys?.length && <p className="team-muted">剧本：{profile.playbook_keys.join('、')}</p>}{!!profile.skill_keys?.length && <p className="team-muted">技能说明：{profile.skill_keys.join('、')}</p>}{!!profile.connector_keys?.length && <p className="team-muted">接入需求：{profile.connector_keys.join('、')}</p>}</div>)}
      {value.channels.map((channel, index) => <div key={channel.key || index}><h4>频道：{channel.name}</h4><p className="r-readable team-preset-long" tabIndex={0} aria-label={channel.name + '完整共享指令'}>{channel.instructions || '未设置共享指令。'}</p><p className="team-muted">成员：{channel.members.map(key => profileName(key)).join('、')}</p>{channel.playbook_key !== undefined && <p className="team-muted">默认工作剧本：{channel.playbook_key ? (value.playbooks?.find(item => item.key === channel.playbook_key)?.name || channel.playbook_key) + '（' + channel.playbook_key + '）' : '未选择'}</p>}{channel.routing && <><p className="team-muted">{teamModeLabel(channel.routing.mode)} · 最多 {channel.routing.max_rounds} 轮 · 主责 {profileName(channel.lead_key)}</p>{channel.routing.rules.map((rule, position) => <p className="team-muted" key={position}>规则：{rule.keywords.join('、')} → {rule.member_keys.map(key => profileName(key)).join('、')}</p>)}</>}{channel.responder && <p className="team-muted">响应规则：{({ everyone: '全员', mentions: '提及成员', lead: '主责成员' } as Record<string, string>)[channel.responder.kind] || channel.responder.kind}{channel.responder.member_key ? ' · ' + profileName(channel.responder.member_key) : ''}</p>}</div>)}
    </details>
    <details><summary>工作剧本 · {value.playbooks?.length || 0}</summary>{value.playbooks?.length ? value.playbooks.map(item => <div key={item.key}><h4>{item.name}</h4><p className="r-readable team-preset-long" tabIndex={0} aria-label={item.name + '完整剧本'}>{item.instructions}</p>{!!item.triggers.length && <p className="team-muted">参考触发条件：{item.triggers.join('、')}</p>}</div>) : <p className="team-muted">未提供工作剧本。</p>}</details>
    <details><summary>起始笔记 · {value.starter_notes?.length || 0}</summary>{value.starter_notes?.length ? value.starter_notes.map((item, index) => <div key={index}><h4>{item.name} · {profileName(item.profile_key)}</h4><p className="r-readable team-preset-long" tabIndex={0} aria-label={item.name + '完整起始笔记'}>{item.content}</p></div>) : <p className="team-muted">未提供起始笔记。</p>}</details>
    <details><summary>技能说明 · {value.skills?.length || 0}（仅文字）</summary><p className="team-muted">这些说明是导入的参考文字，不会安装技能、注册工具或授予执行权限。</p>{value.skills?.map(item => <div key={item.key}><h4>{item.name}</h4><p>{item.description}</p><p className="r-readable team-preset-long" tabIndex={0} aria-label={item.name + '完整技能说明'}>{item.instructions}</p></div>)}</details>
    <details><summary>接入需求 · {value.connector_requirements?.length || 0}（未配置）</summary><p className="team-muted">导入不会继承账号、授权或工具连接。</p>{value.connector_requirements?.map(item => <div key={item.key}><h4>{item.label} · {item.optional ? '可选' : '必需'}</h4><Badge>未配置</Badge><p>{item.reason}</p></div>)}</details>
    <details><summary>预设触发器 · {value.triggers?.length || 0}（暂停或延后）</summary>{value.triggers?.map(item => <div key={item.key}><h4>{item.name}</h4><Badge>{item.kind === 'deferred' ? '延后 · 不可执行' : '已暂停'}</Badge>{item.kind === 'deferred' ? <><p>{item.reason}</p>{item.source_spec != null && <details><summary>原始参考配置（仅文字）</summary><pre>{typeof item.source_spec === 'string' ? item.source_spec : JSON.stringify(item.source_spec, null, 2)}</pre></details>}</> : <><p className="r-readable">{item.question}</p><p className="team-muted">{triggerKinds.find(kind => kind.value === item.kind)?.label || item.kind} · {teamModeLabel(item.dispatch_mode)} · 最多 {item.max_rounds} 轮</p><p className="team-muted">导入后保持暂停；需核对成员模型与频道修订，再在触发器中单独启用。</p><pre>{JSON.stringify(item.schedule, null, 2)}</pre></>}</div>)}</details>
  </div>;
}
