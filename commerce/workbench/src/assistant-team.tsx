import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, errorText, newKey } from './api';
import type { BusinessContext, Thread } from './types';
import { Badge, Button, Dialog, Empty, ErrorNotice, Panel } from './ui';
import { AssistantTeamAutomation, TeamKeywordInput, TeamPackageContents, TeamRoutingEditor, teamModeLabel, teamModes, teamPresetPlaybooks, teamRoutingForMembers, teamRoutingValidation, teamKeywordValidation, type TeamDispatchMode, type TeamPackage, type TeamPreset, type TeamRouting } from './assistant-team-automation';
import './assistant-team.css';

interface TeamProfile {
  id: string; revision: number; name: string; role_id: string; instructions: string;
  model_ids: string[]; enabled: boolean; sha256: string; expertise?: string[];
}
interface TeamChannel {
  id: string; revision: number; name: string; instructions: string; context: BusinessContext;
  member_ids: string[]; sha256: string; routing?: TeamRouting; playbook_key?: string;
}
interface TeamMemberResult {
  profile_id: string; name: string; thread_id: string; run_id: string; status: string;
  run_status?: string; original_run_id?: string; research_task_id?: string;
  answer?: string; answer_sha256?: string | null; questions?: string[]; result_sha256?: string | null;
}
export interface TeamDiscussion {
  id: string; channel_id: string; question: string; status: string; members: TeamMemberResult[];
  updated?: number; mode?: TeamDispatchMode; max_rounds?: number;
  routing_decision?: { selected_member_ids: string[]; selected_member_names: string[]; reason: string; matched_keywords: string[]; lead_id: string };
  plan?: { index: number; round: number; profile_id: string; name: string; kind: 'contribution' | 'synthesis'; status: string; thread_id?: string; run_id?: string }[];
  final_answer?: string; stopped_reason?: string; budget?: { max_member_requests: number; used_member_requests: number };
}
interface DiscussionSummary { id: string; question: string; status: string; created?: string | number }
interface TeamCatalog {
  profiles: TeamProfile[]; channels: TeamChannel[];
  roles: { id: string; name: string }[];
  models: { id: string; label: string; selectable: boolean }[];
  discussions?: DiscussionSummary[]; presets?: TeamPreset[];
  limits: { profiles?: number; channels?: number; channel_members?: number; model_preferences?: number; package_bytes?: number };
}
interface PackagePreview { sha256: string; package: TeamPackage; counts: { profiles: number; channels: number; playbooks?: number; starter_notes?: number; skills?: number; connector_requirements?: number; triggers?: number }; warnings: string[]; source_format?: string; execution_started?: false }
type ProfileDraft = Pick<TeamProfile, 'name' | 'role_id' | 'instructions' | 'model_ids' | 'enabled' | 'expertise'>;
type ChannelDraft = Pick<TeamChannel, 'name' | 'instructions' | 'context' | 'member_ids' | 'routing' | 'playbook_key'>;
type Editor = { kind: 'profile'; original?: TeamProfile; draft: ProfileDraft } | { kind: 'channel'; original?: TeamChannel; draft: ChannelDraft };
const tool = (name: string) => 'commerce_assistant_team_' + name;
const modules = [
  ['overview', '运营台'], ['orders', '订单'], ['products', '库存'], ['operations', '成本与补货'],
  ['organization', '商品与岗位交接'], ['research', '研究资料'], ['creative', '创意工作室'],
  ['intelligence', '全球情报'], ['insights', '选品与评论'], ['support', '客服'], ['connections', '接入与知识'],
  ['alerts', '经营提醒'], ['pilots', '商品候选'], ['agent', '执行记录'], ['exposure', '经营关联'],
  ['tasks', '任务记录'], ['platforms', '平台数据'], ['live', 'Ozon 经营'], ['skills', '技能'],
];
const statusLabels: Record<string, string> = {
  queued: '排队中', pending: '待执行', running: '执行中', completed: '已完成', succeeded: '已完成',
  awaiting_input: '待补充', needs_input: '待补充', awaiting_review: '待审阅', needs_review: '待审阅',
  unknown: '结果未确认', failed: '失败', cancelled: '已取消', canceled: '已取消', partial: '部分完成',
  cancel_requested: '正在请求取消', cancelling: '正在取消', interrupted: '已中断', blocked: '受阻',
};
const teamErrors: Record<string, string> = {
  team_revision_conflict: '配置已被其他窗口更新。请刷新后核对；当前输入已保留。',
  team_profile_not_found: '找不到这位成员，请刷新成员列表。',
  team_channel_not_found: '找不到这个频道，请刷新频道列表。',
  team_profile_disabled: '所选成员尚未启用，请编辑成员并选择可用模型。',
  team_model_unavailable: '当前没有可用的首选或备用模型，请核对模型配置。',
  team_model_required: '请为启用的成员选择至少一个可用模型。',
  team_package_too_large: '文件内容超过 64 KiB，请精简后重新预览。',
  team_package_changed: '导入内容已变化，请重新预览后再确认。',
  team_package_invalid: '团队包格式不正确，请使用 JSON 或 Markdown 团队包。',
  team_discussion_not_found: '找不到这次讨论，请刷新讨论记录。',
  team_idempotency_conflict: '此请求已有不同内容，请先读取原记录。',
  team_limit_exceeded: '当前配置已达到数量上限，请核对成员、频道和模型数量。',
  team_revision_changed: '配置已被其他窗口更新。请刷新后核对；当前输入已保留。',
  team_limit_reached: '成员或频道已达到数量上限，请先核对已有配置。',
  team_not_found: '找不到原成员或频道，请刷新配置列表。',
  team_no_available_model: '当前没有可用的首选或备用模型，请核对成员模型配置。',
  team_member_outside_channel: '该成员已不在当前频道中，请刷新后重新选择。',
  team_invalid_text: '名称、指令或问题格式不正确。名称最多 80 字，指令最多 8000 字，共同问题最多 2000 字。',
  team_invalid_profile: '成员配置不正确，请核对名称、岗位、指令与启用状态。',
  team_invalid_keywords: '专长或规则关键词格式不正确。最多 16 个不同关键词，每个最多 40 字。',
  team_invalid_routing: '路由配置不正确。最多 12 条规则，每条需有关键词与频道成员；协作轮数为 1 至 3。',
  team_unknown_mention: '问题提及了频道中不存在的成员，请核对 @ 后的成员名称。',
  team_no_recipient: '此频道仅响应点名，请使用 @成员名称 后再发送。',
  team_ambiguous_mention: '所提及的成员名称不唯一，请使用成员标识或修改重名配置。',
  team_model_changed: '原讨论绑定的模型配置已变化，后续步骤暂停。请先核对原讨论。',
  team_channel_scope_changed: '频道业务范围已变化，原讨论的后续步骤已停止。请核对当前频道范围后另开讨论，原请求不会重发。',
  team_playbook_not_found: '所选工作剧本不属于此频道的预设，请重新核对。',
  team_discussion_changed: '讨论状态已变化，请读取最新状态后再继续。',
  team_discussion_requires_review: '此讨论状态不支持继续后续步骤，请先核对原请求。',
  team_discussion_reply_required: '原对话尚无已完成的补充回答，请先在原对话处理后再继续。',
  team_invalid_channel: '频道配置不正确，请核对名称、指令与业务模块。',
  team_invalid_members: '频道需选择 1 至 4 位不同成员。',
  team_invalid_model_preferences: '请按顺序选择最多 3 个不同的模型。',
  team_invalid_package: '团队包格式不正确，请使用 JSON 或 Markdown 团队包。',
  team_package_private_data: '团队包含有疑似凭据或本机路径，请移除后重新预览。',
  team_import_not_confirmed: '尚未取得导入完成回执，请刷新配置列表核对，勿直接重复导入。',
};
export function teamErrorText(error: unknown): string {
  const code = error instanceof Error ? error.message : '';
  return teamErrors[code] || (code.startsWith('team_') ? '团队操作未完成。请核对配置或读取当前记录；系统不会自动重发模型请求。' : errorText(error));
}
export function teamStatus(status: string): string { return statusLabels[status.toLowerCase()] || '未识别状态（' + status + '）'; }
export function teamDiscussionActive(status: string): boolean { return ['queued', 'running', 'pending', 'cancel_requested', 'cancelling'].includes(status.toLowerCase()); }
export function teamCanStartDiscussion(mode: TeamDispatchMode, members: ({ enabled: boolean; model_ids: string[] } | undefined)[]): boolean {
  const available = (member: typeof members[number]) => !!member?.enabled && !!member.model_ids.length;
  return members.length > 0 && (mode === 'auto' ? members.some(available) : members.every(available));
}
export function teamPackageBytes(content: string): number { return new TextEncoder().encode(content).byteLength; }
export function teamDownloadName(name: string): string {
  const safe = name.replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, '-').replace(/^\.+|\.+$/g, '').trim().slice(0, 80);
  return (safe || '智能体团队') + '.md';
}
export function teamOrderedModel(ids: string[], index: number, value: string, maximum = 3): string[] {
  if (!Number.isInteger(index) || index < 0 || index > ids.length || index >= maximum) return [...ids];
  const next = [...ids];
  if (!value) next.splice(index, 1);
  else if (index >= 0 && index < maximum && !ids.some((id, position) => id === value && position !== index)) next[index] = value;
  return next.filter(Boolean).slice(0, maximum);
}
function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  return <Badge tone={['failed', 'unknown', 'partial', 'awaiting_input', 'awaiting_review'].includes(normalized) ? 'warning' : normalized === 'completed' || normalized === 'succeeded' ? 'success' : 'gray'}>{teamStatus(status)}</Badge>;
}

const speechReasons: Record<string, string> = {
  render_busy: '本机正在生成另一段朗读，请稍后再试。', render_cancelled: '朗读生成已取消。',
  unsupported_platform: '当前系统不支持本机朗读生成。', local_dependencies_missing: '本机朗读组件尚未就绪，请在本机完成配置后重试。',
  suitable_voice_unavailable: '本机尚无适合此回答语言的已安装语音。', render_timeout: '本机朗读生成超时，请稍后再试。',
  local_render_failed: '本机朗读生成失败，请检查本机语音配置。', audio_too_large: '生成音频超过现有大小上限，未返回音频。',
  invalid_audio: '生成音频未通过格式检查，请稍后再试。', voice_listing_too_large: '本机语音列表超出检查上限，未生成音频。',
  assistant_speech_invalid_arguments: '朗读绑定信息不完整，请重新读取原讨论。',
  assistant_speech_answer_unavailable: '原回答暂不可读取，请重新读取原讨论。',
  assistant_speech_run_not_found: '未找到这段回答的原请求，请回原对话核对。',
  assistant_speech_answer_not_completed: '原请求尚未完成，暂不能生成朗读。',
  assistant_speech_answer_too_large: '本机朗读目前最多支持 2000 字、8000 字节的完整回答。',
  assistant_speech_answer_changed: '原回答已变化，请读取最新讨论后再生成朗读。',
  assistant_speech_hash_unavailable: '当前客户端无法核对原文哈希，请重新读取讨论或使用安全浏览器入口。',
};
export function teamSpeechReason(reason: string): string { return speechReasons[reason] || '本机朗读未能生成，请核对原回答或本机语音配置。'; }
export function teamSpeechWithinLimit(answer: string): boolean { return Array.from(answer).length <= 2000 && teamPackageBytes(answer) <= 8000; }
export async function teamAnswerHash(answer: string, savedHash?: string | null): Promise<string> {
  if (savedHash && /^[a-f0-9]{64}$/.test(savedHash)) return savedHash;
  if (!globalThis.crypto?.subtle) throw new Error('assistant_speech_hash_unavailable');
  const bytes = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(answer));
  return Array.from(new Uint8Array(bytes), value => value.toString(16).padStart(2, '0')).join('');
}
export function teamSpeechAudio(value: { status: string; mime_type?: string; audio_data_url?: string; text_sha256?: string }, expectedHash: string): string | null {
  const url = value.audio_data_url;
  return value.status === 'ready' && value.mime_type === 'audio/wav' && value.text_sha256 === expectedHash && typeof url === 'string' && url.length <= 8388640 && /^data:audio\/wav;base64,[A-Za-z0-9+/]+={0,2}$/.test(url) ? url : null;
}
export function TeamAnswerSpeech({ member, active }: { member: TeamMemberResult; active: boolean }) {
  const [audio, setAudio] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const player = useRef<HTMLAudioElement>(null), mounted = useRef(false), generation = useRef(0), inFlight = useRef(false), activeRef = useRef(active);
  activeRef.current = active;
  const answer = member.answer || '';
  function pause() { if (player.current) { player.current.pause(); player.current.currentTime = 0; } }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; pause(); }; }, []);
  useEffect(() => { generation.current++; pause(); setAudio(''); setError(''); }, [member.thread_id, member.run_id, member.answer_sha256, answer]);
  useEffect(() => { if (!active) { generation.current++; pause(); } }, [active]);
  async function generate() {
    if (inFlight.current || !activeRef.current || !teamSpeechWithinLimit(answer)) return;
    inFlight.current = true; setBusy(true); setError('');
    const request = ++generation.current;
    try {
      const textHash = await teamAnswerHash(answer, member.answer_sha256);
      if (!mounted.current || !activeRef.current || request !== generation.current) return;
      const result = await api<{ status: string; reason?: string; mime_type?: string; audio_data_url?: string; text_sha256?: string }>('commerce_assistant_speech', { thread_id: member.thread_id, run_id: member.run_id, expected_text_sha256: textHash });
      if (!mounted.current || !activeRef.current || request !== generation.current) return;
      const url = teamSpeechAudio(result, textHash);
      if (url) { pause(); setAudio(url); } else setError(teamSpeechReason(result.reason || 'invalid_audio'));
    } catch (failure) { if (mounted.current && activeRef.current && request === generation.current) setError(teamSpeechReason(failure instanceof Error ? failure.message : '')); }
    finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }
  if (!teamSpeechWithinLimit(answer)) return <p className="team-muted">本机朗读目前最多支持 2000 字、8000 字节的完整回答；此回答超出上限。</p>;
  return <div className="team-answer-speech"><Button disabled={busy || !active} onClick={() => void generate()}>{busy ? '正在生成本机朗读…' : '生成朗读'}</Button><span className="team-muted">仅在本机生成，点击播放器才播放。</span><ErrorNotice>{error}</ErrorNotice>{audio && <audio ref={player} controls preload="none" src={audio} aria-label={member.name + '的回答朗读'} />}</div>;
}

const routingReasons: Record<string, string> = { all_members: '频道全员响应', explicit_mentions: '问题中明确提及成员', keyword_rules: '命中频道关键词规则', member_expertise: '命中成员专长', lead_fallback: '未命中明确规则，交由主责成员' };
export function teamRoutingReason(reason: string): string { return routingReasons[reason] || '响应选择原因待核对'; }
export function teamContributionKey(member: Pick<TeamMemberResult, 'profile_id' | 'thread_id' | 'run_id'>, index: number): string { return [member.profile_id, member.thread_id, member.run_id, index].join(':'); }
export function teamStoppedReason(reason: string): string {
  if (reason === 'team_channel_scope_changed') return '频道业务范围已变化，后续步骤已停止';
  reason = reason.replace(/^team_collaboration_/, '');
  return ({ awaiting_input: '原请求需要补充内容', needs_input: '原请求需要补充内容', awaiting_review: '原请求等待审阅', needs_review: '原请求等待审阅', failed: '原请求失败', unknown: '原请求结果未确认', cancelled: '原请求已取消', canceled: '原请求已取消', interrupted: '原请求已中断' } as Record<string, string>)[reason] || '后续步骤已暂停，请先核对原请求';
}
export function TeamDiscussionResults({ discussion, onConversation, active = true }: { discussion: TeamDiscussion; onConversation: (threadId: string) => void; active?: boolean }) {
  return <div className="team-discussion-results">
    <div className="team-heading-line"><h3>原问题</h3><StatusBadge status={discussion.status} /></div>
    <p className="r-readable team-question">{discussion.question}</p>
    {teamDiscussionActive(discussion.status) && <p className="team-muted" role="status">讨论在后台进行。离开此页后可从讨论记录恢复，读取状态不会重新提问。</p>}
    {discussion.status.toLowerCase() === 'unknown' && <p className="team-muted">部分执行结果尚未确认，未自动重试。请先查看各成员的原对话。</p>}
    {discussion.routing_decision && <div className="team-routing-decision"><h3>本次响应选择</h3><p>{discussion.routing_decision.selected_member_names.join('、') || '尚未选择响应者'} · {teamRoutingReason(discussion.routing_decision.reason)}</p>{!!discussion.routing_decision.matched_keywords.length && <p className="team-muted">命中关键词：{discussion.routing_decision.matched_keywords.join('、')}</p>}</div>}
    {discussion.plan?.length ? <><h3>{discussion.mode === 'collaborate' ? '顺序协作进度' : '成员请求进度'}</h3><ol className="team-plan">{discussion.plan.map(step => <li key={step.index}>{step.kind === 'synthesis' ? '最终汇总' : '第 ' + step.round + ' 轮贡献'} · {step.name}<StatusBadge status={step.status} />{step.thread_id && <Button onClick={() => onConversation(step.thread_id!)}>读取此步骤原对话</Button>}</li>)}</ol></> : null}
    {discussion.budget && <p className="team-muted">成员请求 {discussion.budget.used_member_requests} / {discussion.budget.max_member_requests}</p>}
    {discussion.stopped_reason && <p className="team-field-error">{teamStoppedReason(discussion.stopped_reason)}。{discussion.stopped_reason === 'team_channel_scope_changed' ? '请核对当前频道范围后另开讨论；原请求不会重发。' : '先在原对话处理，再明确核对并继续后续步骤；不会重发此步骤。'}</p>}
    <div className="team-member-results">{discussion.members.map((member, index) => <article key={teamContributionKey(member, index)} className="team-member-result">
      <div className="team-heading-line"><h3>{member.name}</h3><StatusBadge status={member.status} /></div>
      {member.answer ? <p className="r-readable">{member.answer}</p> : <p className="team-muted">{teamDiscussionActive(member.status) ? '正在等待原请求的回答…' : '原请求尚无可展示的回答。'}</p>}
      {!!member.questions?.length && <div className="team-followup"><h4>需要补充</h4><ul>{member.questions.map((question, i) => <li key={i}>{question}</li>)}</ul></div>}
      {(member.run_status || member.status) === 'completed' && member.answer && <TeamAnswerSpeech key={discussion.id + ':' + member.thread_id + ':' + member.run_id} member={member} active={active} />}
      {member.thread_id && <Button onClick={() => onConversation(member.thread_id)}>继续 {member.name} 的原对话</Button>}
    </article>)}</div>
    {discussion.mode === 'collaborate' && discussion.final_answer && <section className="team-final-answer"><h3>最终回答</h3><p className="r-readable">{discussion.final_answer}</p></section>}
  </div>;
}

export function AssistantTeam({ onConversation, active = true, requestedDiscussion = '' }: { requestedDiscussion?:string; onConversation: (threadId: string) => void; active?: boolean }) {
  const [catalog, setCatalog] = useState<TeamCatalog | null>(null);
  const [directoryQuery,setDirectoryQuery]=useState('');
  const matchesDirectory=(...parts:unknown[])=>parts.join(' ').toLocaleLowerCase().includes(directoryQuery.trim().toLocaleLowerCase());
  const [tab, setTab] = useState<'profiles' | 'channels' | 'discussions' | 'presets' | 'triggers'>('profiles');
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(''), [editor, setEditor] = useState<Editor | null>(null), [editorError, setEditorError] = useState('');
  const [channelId, setChannelId] = useState(''), [question, setQuestion] = useState('');
  const [discussion, setDiscussion] = useState<TeamDiscussion | null>(null), [discussionError, setDiscussionError] = useState('');
  const [discussionLoading, setDiscussionLoading] = useState(false);
  const [dispatchMode, setDispatchMode] = useState<TeamDispatchMode | ''>(''), [rounds, setRounds] = useState<number | ''>('');
  const [importOpen, setImportOpen] = useState(false), [content, setContent] = useState(''), [preview, setPreview] = useState<PackagePreview | null>(null);
  const [importError, setImportError] = useState('');
  const alive = useRef(false), catalogVersion = useRef(0), discussionVersion = useRef(0), importVersion = useRef(0);
  const discussionTargetVersion = useRef(0);
  const requestKeys = useRef(new Map<string, string>());
  const operationLock = useRef(false);
  const channel = catalog?.channels.find(item => item.id === channelId);
  const members = channel?.member_ids.map(id => catalog?.profiles.find(profile => profile.id === id));
  const memberLimit = Math.min(4, catalog?.limits.channel_members || 4), modelLimit = Math.min(3, catalog?.limits.model_preferences || 3);
  const packageLimit = Math.min(65536, catalog?.limits.package_bytes || 65536);

  function requestKey(operation: string, args: object) {
    const signature = JSON.stringify([operation, args]);
    let key = requestKeys.current.get(signature);
    if (!key) { key = newKey(); if (requestKeys.current.size >= 30) requestKeys.current.delete(requestKeys.current.keys().next().value!); requestKeys.current.set(signature, key); }
    return { key, signature };
  }
  async function loadCatalog() {
    const version = ++catalogVersion.current;
    setLoading(true); setError('');
    try {
      const result = await api<TeamCatalog>(tool('catalog'));
      if (!alive.current || version !== catalogVersion.current) return;
      setCatalog(result);
      setChannelId(current => result.channels.some(item => item.id === current) ? current : result.channels[0]?.id || '');
    } catch (failure) { if (alive.current && version === catalogVersion.current) setError(teamErrorText(failure)); }
    finally { if (alive.current && version === catalogVersion.current) setLoading(false); }
  }
  useEffect(() => {
    alive.current = true; void loadCatalog();
    return () => { alive.current = false; catalogVersion.current++; discussionVersion.current++; discussionTargetVersion.current++; importVersion.current++; };
  }, []);

  async function readDiscussion(id: string) {
    const version = ++discussionVersion.current, targetVersion = discussionTargetVersion.current;
    setDiscussionLoading(true);
    try {
      const result = await api<TeamDiscussion>(tool('discussion_get'), { discussion_id: id });
      if (alive.current && version === discussionVersion.current && targetVersion === discussionTargetVersion.current) {
        setDiscussion(result); setDiscussionError('');
        setCatalog(current => current?.discussions?.some(item => item.id === result.id && item.status !== result.status)
          ? { ...current, discussions: current.discussions.map(item => item.id === result.id ? { ...item, status: result.status } : item) }
          : current);
      }
    } catch (failure) { if (alive.current && version === discussionVersion.current && targetVersion === discussionTargetVersion.current) setDiscussionError(teamErrorText(failure) + ' 原问题不会自动重发。'); }
    finally { if (alive.current && version === discussionVersion.current && targetVersion === discussionTargetVersion.current) setDiscussionLoading(false); }
  }
  useEffect(() => {
    if (!active || tab !== 'discussions' || !discussion || !teamDiscussionActive(discussion.status)) return;
    const id = discussion.id;
    let stopped = false, timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (stopped || !alive.current) return;
      await readDiscussion(id);
      if (!stopped && alive.current) timer = setTimeout(() => void poll(), 2500);
    }
    timer = setTimeout(() => void poll(), 2000);
    return () => { stopped = true; clearTimeout(timer); discussionVersion.current++; };
  }, [active, tab, discussion?.id, discussion?.status]);
  useEffect(() => { if (active && tab === 'discussions' && discussion) void readDiscussion(discussion.id); }, [active, tab]);

  async function operation(name: string, action: () => Promise<void>, showError: (message: string) => void = setError) {
    if (operationLock.current) return;
    operationLock.current = true; setBusy(name); showError(''); setNotice('');
    try { await action(); }
    catch (failure) { if (alive.current) showError(teamErrorText(failure)); }
    finally { operationLock.current = false; if (alive.current) setBusy(''); }
  }
  function editProfile(profile?: TeamProfile) {
    setEditorError(''); setEditor({ kind: 'profile', original: profile, draft: profile ? { name: profile.name, role_id: profile.role_id, instructions: profile.instructions, model_ids: [...profile.model_ids], enabled: profile.enabled, expertise: [...(profile.expertise || [])] } : { name: '', role_id: catalog?.roles[0]?.id || '', instructions: '', model_ids: [], enabled: false, expertise: [] } });
  }
  function editChannel(item?: TeamChannel) {
    setEditorError(''); setEditor({ kind: 'channel', original: item, draft: item ? { name: item.name, instructions: item.instructions, context: { ...item.context }, member_ids: [...item.member_ids], routing: item.routing ? { ...item.routing, rules: item.routing.rules.map(rule => ({ keywords: [...rule.keywords], member_ids: [...rule.member_ids] })) } : { mode: 'all', rules: [], max_rounds: 1 }, playbook_key: item.playbook_key } : { name: '', instructions: '', context: { module: 'overview', demo: true }, member_ids: [], routing: { mode: 'all', rules: [], max_rounds: 1 } } });
  }
  function saveEditor(event: FormEvent) {
    event.preventDefault(); if (!editor) return;
    const current = editor;
    const invalid = current.kind === 'profile' ? teamKeywordValidation(current.draft.expertise || []) : teamRoutingValidation(current.draft.routing || { mode: 'all', rules: [], max_rounds: 1 });
    if (invalid) { setEditorError(invalid); return; }
    if (current.kind === 'profile' && current.draft.enabled && !current.draft.model_ids.length) { setEditorError('请为启用的成员选择至少一个可用模型。'); return; }
    void operation('save', async () => {
      if (current.kind === 'profile') await api<TeamProfile>(tool('profile_save'), { profile: { ...current.draft, name: current.draft.name.trim(), ...(current.original ? { id: current.original.id } : {}) }, ...(current.original ? { expected_revision: current.original.revision } : {}) });
      else await api<TeamChannel>(tool('channel_save'), { channel: { ...current.draft, name: current.draft.name.trim(), ...(current.original ? { id: current.original.id } : {}) }, ...(current.original ? { expected_revision: current.original.revision } : {}) });
      if (!alive.current) return;
      setEditor(null); setNotice(current.kind === 'profile' ? '成员配置已保存。保存配置不会启动模型。' : '频道已保存。频道范围仅在新对话和新讨论中生效。'); await loadCatalog();
    }, setEditorError);
  }
  function openThread(profileId: string, selectedChannel?: string) {
    const args = { profile_id: profileId, ...(selectedChannel ? { channel_id: selectedChannel } : {}) };
    const request = requestKey('thread_open', args);
    void operation('thread:' + profileId, async () => {
      const result = await api<{ thread: Thread; route: { selected_model_id: string; reason: string } }>(tool('thread_open'), { ...args, idempotency_key: request.key });
      if (!alive.current) return;
      requestKeys.current.delete(request.signature); onConversation(result.thread.id);
    });
  }
  function startDiscussion(event: FormEvent) {
    event.preventDefault(); if (operationLock.current || !channel || !question.trim() || !teamCanStartDiscussion(dispatchMode || channel.routing?.mode || 'all', members || [])) return;
    const args = { channel_id: channel.id, expected_revision: channel.revision, question: question.trim(), mode: dispatchMode || channel.routing?.mode || 'all', max_rounds: rounds || channel.routing?.max_rounds || 1, ...(channel.playbook_key ? { playbook_key: channel.playbook_key } : {}) };
    const request = requestKey('discussion_start', args), targetVersion = ++discussionTargetVersion.current;
    discussionVersion.current++; setDiscussion(null); setDiscussionLoading(false);
    void operation('start', async () => {
      const result = await api<TeamDiscussion>(tool('discussion_start'), { ...args, idempotency_key: request.key });
      if (!alive.current || targetVersion !== discussionTargetVersion.current) return;
      setDiscussion(result); requestKeys.current.delete(request.signature); setQuestion(''); await loadCatalog();
    }, setDiscussionError);
  }
  function cancelDiscussion() {
    if (operationLock.current || !discussion) return;
    const id = discussion.id, targetVersion = discussionTargetVersion.current;
    discussionVersion.current++;
    void operation('cancel', async () => {
      const result = await api<TeamDiscussion>(tool('discussion_cancel'), { discussion_id: id });
      if (alive.current && targetVersion === discussionTargetVersion.current) { discussionVersion.current++; setDiscussion(result); await loadCatalog(); }
    }, setDiscussionError);
  }
  function changeContent(value: string) {
    importVersion.current++; setContent(value); setPreview(null); setImportError(teamPackageBytes(value) > packageLimit ? '文件内容超过 64 KiB，请精简后重新预览。' : '');
  }
  async function readFile(file?: File) {
    const version = ++importVersion.current; setPreview(null); setImportError(''); setContent('');
    if (!file) return;
    if (!/\.(json|md|markdown)$/i.test(file.name)) { setImportError('请选择 JSON 或 Markdown 文件。'); return; }
    if (file.size > packageLimit) { setImportError('文件内容超过 64 KiB，请精简后重新预览。'); return; }
    try { const value = await file.text(); if (alive.current && version === importVersion.current) changeContent(value); }
    catch { if (alive.current && version === importVersion.current) setImportError('文件未能读取，请重新选择或粘贴内容。'); }
  }
  function previewPackage() {
    if (!content.trim() || teamPackageBytes(content) > packageLimit) return;
    const value = content, version = importVersion.current;
    void operation('preview', async () => {
      const result = await api<PackagePreview>(tool('package_preview'), { content: value });
      if (alive.current && version === importVersion.current) setPreview(result);
    }, setImportError);
  }
  function importPackage() {
    if (!preview || teamPackageBytes(content) > packageLimit) return;
    const args = { content, expected_sha256: preview.sha256 }, version = importVersion.current, request = requestKey('package_import', args);
    void operation('import', async () => {
      const result = await api<{ status: string; profiles: TeamProfile[]; channels: TeamChannel[] }>(tool('package_import'), { ...args, idempotency_key: request.key });
      if (!alive.current || version !== importVersion.current) return;
      if (result.status !== 'imported') throw new Error('team_import_not_confirmed');
      requestKeys.current.delete(request.signature); setImportOpen(false); changeContent(''); setNotice('已导入 ' + result.profiles.length + ' 位禁用成员与 ' + result.channels.length + ' 个频道。请逐位选择模型并启用后使用。'); await loadCatalog();
    }, setImportError);
  }
  function exportChannel(item: TeamChannel) {
    void operation('export:' + item.id, async () => {
      const result = await api<{ content: string; sha256: string; package: TeamPackage }>(tool('package_export'), { channel_id: item.id, name: item.name, version: 2 });
      if (!alive.current) return;
      const url = URL.createObjectURL(new Blob([result.content], { type: 'text/markdown;charset=utf-8' }));
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = teamDownloadName(item.name); document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('已生成团队 Markdown 下载。配置不包含运行记录、模型连接或账号。');
    });
  }
  function exportPreset(item: TeamPreset) {
    void operation('export-preset:' + item.id, async () => {
      const result = await api<{ content: string }>(tool('package_export'), { preset_id: item.id, name: item.name, version: 2 });
      if (!alive.current) return;
      const url = URL.createObjectURL(new Blob([result.content], { type: 'text/markdown;charset=utf-8' }));
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = teamDownloadName(item.name); document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('已生成完整团队预设下载，包含指令、剧本和参考说明；不包含运行记录、模型连接或账号。');
    });
  }
  function openDiscussion(id: string) { discussionTargetVersion.current++; setDiscussion(null); setDiscussionError(''); setTab('discussions'); void readDiscussion(id); }
  function advanceDiscussion() {
    if (operationLock.current || !discussion) return;
    const current = discussion, targetVersion = discussionTargetVersion.current; discussionVersion.current++;
    void operation('advance', async () => {
      const result = await api<TeamDiscussion>(tool('discussion_advance'), { discussion_id: current.id, ...(current.updated == null ? {} : { expected_updated: current.updated }) });
      if (alive.current && targetVersion === discussionTargetVersion.current) { setDiscussion(result); await loadCatalog(); }
    }, setDiscussionError);
  }
  useEffect(()=>{if(active&&requestedDiscussion&&/^discussion_[a-zA-Z0-9_-]+$/.test(requestedDiscussion))openDiscussion(requestedDiscussion);},[active,requestedDiscussion]);
  const effectiveMode = dispatchMode || channel?.routing?.mode || 'all';
  const unavailableMembers = !teamCanStartDiscussion(effectiveMode, members || []);
  const modelName = (id: string) => catalog?.models.find(item => item.id === id)?.label || '已保存模型（待核对）';
  const closeImport = () => { if (busy) return; importVersion.current++; setImportOpen(false); setImportError(''); setPreview(null); };
  return <div className="r-page assistant-team">
    <div className="r-page-heading"><div><h1>智能体团队</h1></div><div className="r-actions"><Button disabled={!!busy} onClick={() => { setImportOpen(true); setImportError(''); }}>导入团队</Button><Button disabled={!!busy || loading} onClick={() => void loadCatalog()}>刷新</Button></div></div>
    <ErrorNotice>{error}</ErrorNotice>{notice && <p className="team-feedback" role="status">{notice}</p>}
    <div className="r-tabs" aria-label="团队视图"><Button aria-pressed={tab === 'profiles'} onClick={() => setTab('profiles')}>成员</Button><Button aria-pressed={tab === 'channels'} onClick={() => setTab('channels')}>频道</Button><Button aria-pressed={tab === 'discussions'} onClick={() => setTab('discussions')}>讨论记录</Button><Button aria-pressed={tab === 'presets'} onClick={() => setTab('presets')}>团队预设</Button><Button aria-pressed={tab === 'triggers'} onClick={() => setTab('triggers')}>触发器</Button></div>
    {['profiles','channels','presets'].includes(tab)&&<label className="ui-field team-directory-search">查找配置<input type="search" placeholder="名称、标识或岗位" value={directoryQuery} onChange={event=>setDirectoryQuery(event.target.value)}/></label>}
    {catalog && tab === 'triggers' && <AssistantTeamAutomation channels={catalog.channels} active={active} onDiscussion={openDiscussion} playbooks={catalog.channels.flatMap(item => teamPresetPlaybooks(catalog.presets || [], item.id).map(playbook => ({ ...playbook, channel_id: item.id })))} />}
    {catalog && tab === 'presets' && <div className="team-presets">{catalog.presets?.length ? catalog.presets.filter(preset=>matchesDirectory(preset.name,preset.id)).map(preset => <Panel key={preset.id} title={preset.name} action={<Button disabled={!!busy} onClick={() => exportPreset(preset)}>导出完整预设</Button>}><p className="team-muted">标识 {preset.id.slice(-8)} · 触发器需单独启用</p><TeamPackageContents value={preset.package} /></Panel>) : <Empty>尚无团队预设。导入 JSON 或含 YAML 前置信息的 Markdown 后可在此读取完整配置。</Empty>}</div>}

    {loading && !catalog && <Empty>正在读取团队配置…</Empty>}
    {!loading && !catalog && <Empty>团队配置未读到，请检查连接后刷新。</Empty>}
    {catalog && tab === 'profiles' && <Panel title={'团队成员 · ' + catalog.profiles.length} action={<Button primary disabled={!!busy || catalog.profiles.length >= (catalog.limits.profiles || 24)} onClick={() => editProfile()}>新建成员</Button>}>
      {catalog.profiles.length ? <div className="team-profile-grid">{catalog.profiles.filter(profile=>matchesDirectory(profile.name,profile.id,profile.role_id)).slice().sort((a,b)=>Number(b.enabled)-Number(a.enabled)||b.revision-a.revision).map(profile => <article className="team-profile" key={profile.id}>
        <div className="team-heading-line"><h3>{profile.name}</h3><Badge>{profile.enabled ? '已启用' : '未启用'}</Badge></div>
        <p className="team-muted">{catalog.roles.find(role => role.id === profile.role_id)?.name || '岗位待核对'} · 修订 {profile.revision} · {profile.id.slice(-8)}</p>
        <details><summary>角色指令</summary><p className="team-profile-description">{profile.instructions || '尚未设置角色指令。'}</p></details>
        {!!profile.expertise?.length && <p className="team-muted">专长：{profile.expertise.join('、')}</p>}
        <ol className="team-model-order">{profile.model_ids.map((id, index) => <li key={id}>{index === 0 ? '首选' : '备用 ' + index}：{modelName(id)}</li>)}</ol>
        {!profile.model_ids.length && <p className="team-muted">尚未选择模型</p>}
        <div className="r-actions"><Button disabled={!!busy} onClick={() => editProfile(profile)}>编辑成员</Button><Button primary disabled={!!busy || !profile.enabled || !profile.model_ids.length} onClick={() => openThread(profile.id)}>开始对话</Button></div>
      </article>)}</div> : <Empty>还没有成员。新建角色配置或导入团队后，为成员选择模型并启用。</Empty>}
    </Panel>}
    {catalog && tab === 'channels' && <Panel title={'工作频道 · ' + catalog.channels.length} action={<Button primary disabled={!!busy || catalog.channels.length >= (catalog.limits.channels || 20)} onClick={() => editChannel()}>新建频道</Button>}>
      {catalog.channels.length ? <div className="team-channel-list">{catalog.channels.filter(item=>matchesDirectory(item.name,item.id,item.context.module)).map(item => <article className="team-channel" key={item.id}>
        <div className="team-heading-line"><h3>{item.name}</h3><span className="team-muted">{modules.find(entry => entry[0] === item.context.module)?.[1] || item.context.module} · {item.context.demo ? '演示范围' : '本机业务范围'}</span></div>
        <p className="team-muted">修订 {item.revision} · {item.id.slice(-8)}</p><details><summary>频道指令</summary><p className="r-readable">{item.instructions || '未设置频道共享指令。'}</p></details>
        <p className="team-muted">{teamModeLabel(item.routing?.mode)}{item.routing?.mode === 'collaborate' ? ' · 最多 ' + item.routing.max_rounds + ' 轮' : ''}{item.playbook_key ? ' · 剧本 ' + item.playbook_key : ''}</p>
        <p className="team-muted">{item.member_ids.map(id => catalog.profiles.find(profile => profile.id === id)?.name || '成员已不可用').join('、') || '尚未加入成员'}</p>
        <div className="r-actions"><Button disabled={!!busy} onClick={() => editChannel(item)}>编辑频道</Button><Button disabled={!!busy} onClick={() => { setChannelId(item.id); setDispatchMode(''); setRounds(''); setTab('discussions'); }}>发起讨论</Button><Button disabled={!!busy} onClick={() => exportChannel(item)}>导出团队</Button></div>
        {!!item.member_ids.length && <details className="team-channel-conversations"><summary>在此频道与单个成员对话</summary><div className="r-actions">{item.member_ids.map(id => { const profile = catalog.profiles.find(member => member.id === id); return profile && <Button key={id} disabled={!!busy || !profile.enabled || !profile.model_ids.length} onClick={() => openThread(id, item.id)}>与 {profile.name} 对话</Button>; })}</div></details>}
      </article>)}</div> : <Empty>还没有频道。创建频道后选择最多 {memberLimit} 位成员，并明确共享工作范围。</Empty>}
    </Panel>}
    {catalog && tab === 'discussions' && <div className="team-discussions-layout"><div>
      <Panel title="向频道成员提问"><form className="team-form" onSubmit={startDiscussion}>
        <fieldset disabled={!!busy}><label className="ui-field">工作频道<select value={channelId} onChange={event => { setChannelId(event.target.value); setDispatchMode(''); setRounds(''); }}><option value="">请选择频道</option>{catalog.channels.map(item => <option key={item.id} value={item.id}>{item.name} · r{item.revision} · {item.id.slice(-8)}</option>)}</select></label>
          {channel && <p className="team-muted">{members?.map(member => member?.name || '成员不可用').join('、') || '频道尚无成员'} · {channel.context.demo ? '演示范围' : '本机业务范围'}</p>}
          <label className="ui-field">本次响应方式<select value={dispatchMode} onChange={event => setDispatchMode(event.target.value as TeamDispatchMode | '')}><option value="">使用频道默认：{teamModeLabel(channel?.routing?.mode)}</option>{teamModes.map(mode => <option key={mode.value} value={mode.value}>{mode.label}</option>)}</select></label>
          {(dispatchMode || channel?.routing?.mode) === 'collaborate' && <label className="ui-field">本次协作轮数<select value={rounds} onChange={event => setRounds(event.target.value ? Number(event.target.value) : '')}><option value="">频道默认 · {channel?.routing?.max_rounds || 1} 轮</option>{[1, 2, 3].map(round => <option key={round} value={round}>{round} 轮</option>)}</select></label>}
          <label className="ui-field">共同问题<textarea rows={4} value={question} required maxLength={2000} onChange={event => setQuestion(event.target.value)} placeholder="说明希望各成员回答的问题" /></label>
          {unavailableMembers && <p className="team-field-error">{effectiveMode === 'auto' ? '至少需要一位已启用且已选择模型的成员。' : '请先为频道内所有成员选择模型并启用。'}</p>}{effectiveMode === 'auto' && !unavailableMembers && members?.some(member => !member?.enabled || !member.model_ids.length) && <p className="team-muted">部分成员尚未就绪。自动选择会核对实际响应者；明确提及未启用成员时会返回阻塞原因。</p>}
          <p className="team-muted">{effectiveMode === 'collaborate' ? '顺序协作最多 ' + (Number(rounds || channel?.routing?.max_rounds || 1) * (members?.length || 0) + 1) + ' 个成员请求（含汇总）。' : effectiveMode === 'auto' ? channel?.routing?.mentions_only ? '此频道自动模式仅响应点名，请使用 @成员名称 或 @all；未点名不会调用模型。' : '按提及、规则或专长选择实际响应成员，提交前会核对所选成员模型。' : '频道内 ' + (members?.length || 0) + ' 位成员分别独立回答。'}各原请求保留原对话，运行中不自动重试模型。</p>
          <Button primary type="submit" disabled={!channel || !question.trim() || !members?.length || !!unavailableMembers}>发起{teamModeLabel(dispatchMode || channel?.routing?.mode)}</Button>
        </fieldset>
      </form></Panel>
      <ErrorNotice>{discussionError}</ErrorNotice>
      {discussionLoading && !discussion && <Empty>正在读取原讨论…</Empty>}
      {discussion && <Panel title="讨论进度" action={<div className="r-actions"><Button disabled={!!busy} onClick={() => void readDiscussion(discussion.id)}>读取最新状态</Button>{discussion.mode === 'collaborate' && ['awaiting_input', 'awaiting_review'].includes(discussion.status) && <Button disabled={!!busy} onClick={advanceDiscussion}>核对原回答并继续后续步骤</Button>}{teamDiscussionActive(discussion.status) && <Button disabled={!!busy} onClick={cancelDiscussion}>取消未完成请求</Button>}</div>}><TeamDiscussionResults discussion={discussion} onConversation={onConversation} active={active && tab === 'discussions'} /></Panel>}
    </div><Panel title="最近讨论"><div className="team-history">{catalog.discussions?.length ? catalog.discussions.map(item => <Button className="team-history-item" key={item.id} disabled={!!busy} onClick={() => openDiscussion(item.id)}><span>{item.question}</span><StatusBadge status={item.status} /></Button>) : <Empty>尚无讨论记录。</Empty>}</div></Panel></div>}
    {editor && <Dialog title={(editor.original ? '编辑' : '新建') + (editor.kind === 'profile' ? '成员' : '频道')} close={() => { if (!busy) setEditor(null); }}><form className="team-form" onSubmit={saveEditor}><ErrorNotice>{editorError}</ErrorNotice><fieldset disabled={!!busy}>
      <label className="ui-field">{editor.kind === 'profile' ? '成员名称' : '频道名称'}<input value={editor.draft.name} autoFocus required maxLength={80} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, name: event.target.value } } as Editor)} /></label>
      {editor.kind === 'profile' ? <>
        <label className="ui-field">岗位<select value={editor.draft.role_id} required onChange={event => setEditor({ ...editor, draft: { ...editor.draft, role_id: event.target.value } })}>{catalog?.roles.map(role => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label>
        <label className="ui-field">角色指令<textarea rows={6} value={editor.draft.instructions} maxLength={8000} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, instructions: event.target.value } })} /></label>
        <TeamKeywordInput label="专长关键词（可选）" value={editor.draft.expertise || []} onChange={expertise => setEditor({ ...editor, draft: { ...editor.draft, expertise } })} />
        <fieldset className="team-model-fields"><legend>模型顺序</legend>{Array.from({ length: Math.min(modelLimit, editor.draft.model_ids.length + 1) }, (_, index) => <label className="ui-field" key={index}>{index === 0 ? '首选模型' : '备用模型 ' + index}<select value={editor.draft.model_ids[index] || ''} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, model_ids: teamOrderedModel(editor.draft.model_ids, index, event.target.value, modelLimit) } })}><option value="">{index === 0 ? '请选择模型' : '不使用此备用模型'}</option>{catalog?.models.map(model => <option value={model.id} key={model.id} disabled={!model.selectable || editor.draft.model_ids.some((id, position) => id === model.id && position !== index)}>{model.label}{model.selectable ? '' : '（当前不可用）'}</option>)}{editor.draft.model_ids[index] && !catalog?.models.some(model => model.id === editor.draft.model_ids[index]) && <option value={editor.draft.model_ids[index]}>原模型当前未登记，请重新选择</option>}</select></label>)}
          <p className="team-muted">新会话启动前按顺序选择可用模型；运行中不会切换或自动重试。</p></fieldset>
        <label className="team-check"><input type="checkbox" checked={editor.draft.enabled} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, enabled: event.target.checked } })} />启用此成员</label>
      </> : <>
        <label className="ui-field">频道共享指令<textarea rows={5} value={editor.draft.instructions} maxLength={8000} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, instructions: event.target.value } })} /></label>
        <label className="ui-field">业务模块<select value={editor.draft.context.module} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, context: { module: event.target.value, demo: editor.draft.context.demo === true } } })}>{modules.map(([id, label]) => <option key={id} value={id}>{label}</option>)}{!modules.some(([id]) => id === editor.draft.context.module) && <option value={editor.draft.context.module}>{editor.draft.context.module}</option>}</select></label>
        <label className="team-check"><input type="checkbox" checked={editor.draft.context.demo === true} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, context: { module: editor.draft.context.module, demo: event.target.checked } } })} />使用演示范围</label>
        {(editor.draft.context.store_id || editor.draft.context.entity) && <p className="team-muted">原频道已保存具体范围：{editor.draft.context.store_id ? '店铺 ' + editor.draft.context.store_id : ''}{editor.draft.context.entity ? ' · ' + editor.draft.context.entity.kind + ' ' + editor.draft.context.entity.id : ''}。切换模块或演示范围时将清除具体对象绑定。</p>}
        <p className="team-muted">新频道只保存模块与数据模式，不自动选择店铺或商品。</p>
        <fieldset className="team-member-picker"><legend>频道成员 · {editor.draft.member_ids.length}/{memberLimit}</legend>{catalog?.profiles.length ? catalog.profiles.map(profile => <label className="team-check" key={profile.id}><input type="checkbox" checked={editor.draft.member_ids.includes(profile.id)} disabled={!editor.draft.member_ids.includes(profile.id) && editor.draft.member_ids.length >= memberLimit} onChange={event => { const ids = event.target.checked ? [...editor.draft.member_ids, profile.id] : editor.draft.member_ids.filter(id => id !== profile.id); setEditor({ ...editor, draft: { ...editor.draft, member_ids: ids, routing: teamRoutingForMembers(editor.draft.routing || { mode: 'all', rules: [], max_rounds: 1 }, ids) } }); }} />{profile.name}<span className="team-muted">{profile.enabled ? '' : '未启用'}</span></label>) : <p className="team-muted">请先新建成员。</p>}</fieldset>
        <TeamRoutingEditor value={editor.draft.routing || { mode: 'all', rules: [], max_rounds: 1 }} members={(catalog?.profiles || []).filter(profile => editor.draft.member_ids.includes(profile.id))} onChange={routing => setEditor({ ...editor, draft: { ...editor.draft, routing } })} />
        <label className="ui-field">工作剧本（可选）<select value={editor.draft.playbook_key || ''} onChange={event => setEditor({ ...editor, draft: { ...editor.draft, playbook_key: event.target.value || undefined } })}><option value="">不使用剧本</option>{(editor.original ? teamPresetPlaybooks(catalog?.presets || [], editor.original.id) : []).map(item => <option key={item.key} value={item.key}>{item.name}</option>)}{editor.draft.playbook_key && !(editor.original ? teamPresetPlaybooks(catalog?.presets || [], editor.original.id) : []).some(item => item.key === editor.draft.playbook_key) && <option value={editor.draft.playbook_key}>{editor.draft.playbook_key}（已保存）</option>}</select></label>
      </>}
      <div className="r-form-actions"><Button type="submit" primary disabled={!editor.draft.name.trim() || (editor.kind === 'profile' ? !editor.draft.role_id : !editor.draft.member_ids.length)}>保存配置</Button><Button onClick={() => setEditor(null)}>取消</Button></div>
    </fieldset></form></Dialog>}
    {importOpen && <Dialog title="导入团队配置" close={closeImport}><ErrorNotice>{importError}</ErrorNotice><div className="team-form"><label className="ui-field">本地 JSON 或 Markdown 文件<input type="file" accept=".json,.md,.markdown,application/json,text/markdown" disabled={!!busy} onChange={event => void readFile(event.target.files?.[0])} /></label>
      <label className="ui-field">或粘贴团队包内容<textarea rows={8} value={content} maxLength={65536} disabled={busy === 'import'} onChange={event => changeContent(event.target.value)} /></label>
      <p className="team-muted">{teamPackageBytes(content).toLocaleString('zh-CN')} / {packageLimit.toLocaleString('zh-CN')} 字节。支持 JSON 与含 YAML 前置信息的 Markdown。导入成员禁用且模型为空，触发器暂停；不会授权接入或启动任务。</p>
      {preview && <section className="team-package-preview"><h3>{preview.package.name}</h3><p>{preview.counts.profiles} 位成员 · {preview.counts.channels} 个频道 · {preview.package.playbooks?.length || 0} 个剧本 · {preview.package.starter_notes?.length || 0} 条起始笔记 · {preview.package.skills?.length || 0} 项技能说明 · {preview.package.connector_requirements?.length || 0} 项接入需求 · {preview.package.triggers?.length || 0} 个触发器</p>{preview.source_format && <p className="team-muted">来源格式：{preview.source_format}</p>}{preview.warnings.map((warning, index) => <p className="team-field-error" key={index}>{warning}</p>)}<TeamPackageContents value={preview.package} /></section>}
      <div className="r-form-actions"><Button disabled={!!busy || !content.trim() || teamPackageBytes(content) > packageLimit} onClick={previewPackage}>预览团队包</Button><Button primary disabled={!!busy || !preview || teamPackageBytes(content) > packageLimit} onClick={importPackage}>确认导入禁用配置</Button></div>
    </div></Dialog>}
  </div>;
}
