import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { webcrypto, createHash } from 'node:crypto';

const compiled = await build({ entryPoints: ['src/assistant-team.tsx'], bundle: true, write: false, format: 'cjs', platform: 'node', external: ['react', 'react-dom/server'], loader: { '.css': 'empty' } });
const module = { exports: {} };
const require = createRequire(import.meta.url);
const scope = vm.createContext({ module, exports: module.exports, require, TextEncoder, crypto: webcrypto, window: { CommerceUI: { icon: () => '' } } });
vm.runInContext(compiled.outputFiles[0].text, scope);
const { AssistantTeam, TeamDiscussionResults, teamOrderedModel, teamPackageBytes, teamDownloadName, teamStatus, teamDiscussionActive, teamErrorText, teamAnswerHash, teamSpeechWithinLimit, teamSpeechAudio, teamSpeechReason } = module.exports;
const plain = value => Array.from(value);

test('model order preserves primary and backups and rejects duplicate or noncontiguous selection', () => {
  const initial = ['primary', 'backup-one'];
  assert.deepEqual(plain(teamOrderedModel(initial, 2, 'backup-two')), ['primary', 'backup-one', 'backup-two']);
  assert.deepEqual(plain(teamOrderedModel(initial, 0, 'backup-one')), initial);
  assert.deepEqual(plain(teamOrderedModel(initial, 0, '')), ['backup-one']);
  assert.deepEqual(plain(teamOrderedModel(initial, 1, 'replacement')), ['primary', 'replacement']);
  assert.deepEqual(plain(teamOrderedModel(initial, 3, 'fourth')), initial);
  assert.deepEqual(plain(teamOrderedModel(initial, -1, '')), initial);
  assert.deepEqual(initial, ['primary', 'backup-one'], 'editing never mutates a saved catalog profile');
});

test('package limit uses UTF-8 bytes including Chinese and astral characters', () => {
  assert.equal(teamPackageBytes('a'.repeat(65536)), 65536);
  assert.equal(teamPackageBytes('中'.repeat(21845)), 65535);
  assert.ok(teamPackageBytes('中'.repeat(21846)) > 65536);
  assert.equal(teamPackageBytes('a中𠮷'), 8);
});

test('export names cannot carry directory separators, control characters or empty dot names', () => {
  for (const name of ['../../team', 'C:\\private\\team', 'a\u0000b\nc', '...', '团队频道']) {
    const filename = teamDownloadName(name);
    assert.match(filename, /\.md$/);
    assert.doesNotMatch(filename, /[\\/:*?"<>|\u0000-\u001f\u007f]/);
    assert.ok(filename.length <= 83);
  }
  assert.equal(teamDownloadName('...'), '智能体团队.md');
});

test('polling only follows original active requests while all terminal outcomes remain distinct', () => {
  for (const status of ['queued', 'running', 'cancel_requested']) assert.equal(teamDiscussionActive(status), true);
  for (const status of ['completed', 'awaiting_input', 'awaiting_review', 'unknown', 'failed', 'cancelled', 'interrupted', 'partial', 'unrecognized']) assert.equal(teamDiscussionActive(status), false);
  assert.equal(teamStatus('UNKNOWN'), '结果未确认');
  assert.equal(teamStatus('awaiting_input'), '待补充');
  assert.equal(teamStatus('cancel_requested'), '正在请求取消');
  assert.equal(teamStatus('cancelled'), '已取消');
  assert.match(teamStatus('new-server-status'), /未识别状态/);
});

test('team failures expose understandable Chinese without echoing raw failure data', () => {
  const failure = message => { scope.failureMessage = message; return vm.runInContext('new Error(failureMessage)', scope); };
  assert.match(teamErrorText(failure('team_no_available_model')), /没有可用/);
  assert.match(teamErrorText(failure('team_revision_changed')), /配置已被其他窗口更新/);
  assert.match(teamErrorText(failure('team_package_private_data')), /疑似凭据或本机路径/);
  assert.match(teamErrorText(failure('team_new_error_with_private_information')), /团队操作未完成/);
  assert.doesNotMatch(teamErrorText(failure('team_new_error_with_private_information')), /private_information/);
});

const render = discussion => renderToStaticMarkup(React.createElement(TeamDiscussionResults, { discussion, onConversation() {} }));
test('unknown, failed, awaiting-input and cancelled members retain separate visible outcomes', () => {
  const html = render({ id: 'discussion', channel_id: 'channel', question: '原问题', status: 'unknown', members: [
    { profile_id: 'a', name: '研究员', thread_id: 'original-a', run_id: 'run-a', status: 'unknown', answer: '' },
    { profile_id: 'b', name: '审阅员', thread_id: 'original-b', run_id: 'run-b', status: 'awaiting_input', questions: ['请提供目标市场。'], answer: '需要更多依据。' },
    { profile_id: 'c', name: '成员三', thread_id: 'original-c', run_id: 'run-c', status: 'failed', answer: '' },
    { profile_id: 'd', name: '成员四', thread_id: 'original-d', run_id: 'run-d', status: 'cancelled', answer: '' },
  ] });
  for (const label of ['结果未确认', '待补充', '失败', '已取消', '请提供目标市场。', '继续 研究员 的原对话', '继续 审阅员 的原对话']) assert.ok(html.includes(label), label);
  assert.match(html, /未自动重试/);
  assert.doesNotMatch(html, /已完成|重新提问/);
});

test('model answers, imported-style member names and questions are rendered as escaped text', () => {
  const unsafe = '<img src=x onerror="alert(1)"><script>attack()</script>';
  const html = render({ id: 'discussion', channel_id: 'channel', question: unsafe, status: 'completed', members: [
    { profile_id: 'a', name: unsafe, thread_id: 'thread', run_id: 'run', status: 'completed', answer: unsafe, questions: [unsafe] },
  ] });
  assert.match(html, /&lt;img/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<img|<script/);
});

test('initial team screen shows a read state rather than invented members or an execution receipt', () => {
  const html = renderToStaticMarkup(React.createElement(AssistantTeam, { onConversation() {} }));
  assert.match(html, /智能体团队/);
  assert.match(html, /正在读取团队配置/);
  assert.doesNotMatch(html, /已完成|导入成功|已启动/);
});

test('speech binds the exact original UTF-8 answer, including whitespace, or uses the server answer hash', async () => {
  const answer = '  原回答\n𠮷\t ';
  assert.equal(await teamAnswerHash(answer), createHash('sha256').update(answer).digest('hex'));
  assert.equal(await teamAnswerHash('unchanged binding', 'a'.repeat(64)), 'a'.repeat(64));
  assert.notEqual(await teamAnswerHash(answer), await teamAnswerHash(answer.trim()));
  assert.equal(teamSpeechWithinLimit('𠮷'.repeat(2000)), true, 'Unicode characters match the Python character limit');
  assert.equal(teamSpeechWithinLimit('a'.repeat(2001)), false);
  assert.equal(teamSpeechWithinLimit('𠮷'.repeat(2001)), false);
});

test('speech only exposes hash-bound ready WAV data URLs and never accepts remote media', () => {
  const hash = 'a'.repeat(64), url = 'data:audio/wav;base64,UklGRg==';
  const valid = { status: 'ready', mime_type: 'audio/wav', audio_data_url: url, text_sha256: hash };
  assert.equal(teamSpeechAudio(valid, hash), url);
  assert.equal(teamSpeechAudio({ ...valid, audio_data_url: 'https://example.invalid/audio.wav' }, hash), null);
  assert.equal(teamSpeechAudio({ ...valid, mime_type: 'text/html' }, hash), null);
  assert.equal(teamSpeechAudio({ ...valid, text_sha256: 'b'.repeat(64) }, hash), null);
  assert.equal(teamSpeechAudio({ ...valid, status: 'failed' }, hash), null);
  assert.match(teamSpeechReason('local_dependencies_missing'), /本机朗读组件/);
  assert.doesNotMatch(teamSpeechReason('sensitive unknown detail'), /sensitive/);
});

test('speech appears only for completed original requests, without autoplay or synthesized receipts', () => {
  const member = { profile_id: 'a', name: '成员', thread_id: 'thread', run_id: 'run', status: 'unknown', answer: '已有文本' };
  assert.doesNotMatch(render({ id: 'd', question: '问题', status: 'unknown', members: [member] }), /生成朗读/);
  const html = render({ id: 'd', question: '问题', status: 'partial', members: [{ ...member, status: 'partial', run_status: 'completed' }] });
  assert.match(html, /部分完成/);
  assert.match(html, /生成朗读/);
  assert.doesNotMatch(html, /<audio|autoplay|已生成朗读/);
  const oversized = render({ id: 'd', question: '问题', status: 'completed', members: [{ ...member, status: 'completed', answer: '长'.repeat(2001) }] });
  assert.match(oversized, /2000 字、8000 字节/);
  assert.doesNotMatch(oversized, />生成朗读<\/button>/);
});
