import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import vm from 'node:vm';

const source = await readFile('../web/copilot-ui.js', 'utf8');
const context = { module: 'research', demo: false };
function setup(initial = 'running', apiOverride = null) {
  const events = new Map(), timers = new Set(), calls = [], opened = [];
  const listen = { addEventListener(name, handler) { if (!events.has(name)) events.set(name, []); events.get(name).push(handler); }, removeEventListener() {} };
  const esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  const ui = { escape: esc, icon: () => '', badge: esc, alert: esc, button: ({ label, attrs = {} }) => '<button ' + Object.entries(attrs).filter(([, value]) => value !== false && value != null).map(([key, value]) => key + '="' + esc(value) + '"').join(' ') + '>' + esc(label) + '</button>', field: (label, value) => label + value, input: () => '', select: () => '' };
  const document = { ...listen, querySelector: () => null, getElementById: () => null, activeElement: null };
  const window = { ...listen, CommerceUI: ui, innerWidth: 1440, dispatchEvent() {} };
  const job = { schema: 'commerce-market-research-v1', task_id: 'task-a', run_id: 'run-a', thread_id: 'thread-a', revision: 3, status: initial, phase: 'collecting', query: '俄罗斯厨房收纳', market: 'RU', source_count: 1, candidate_count: 0, error: null, questions: [], candidates: [], sources: [], report: null };
  const run = { id: 'run-a', status: 'completed', result_sha256: 'fixed-result', result: { answer: '研究已受理', questions: [] }, research_job: job };
  const thread = { id: 'thread-a', context, context_sha256: 'fixed-context', turns: [{ id: 'turn-a', question: '调研俄罗斯厨房收纳', run }], latest_run: run, research_job: job };
  vm.runInNewContext(source, { window, document, crypto: { randomUUID }, setInterval(fn) { timers.add(fn); return fn; }, clearInterval(fn) { timers.delete(fn); }, CustomEvent: class {}, localStorage: { getItem: () => null, setItem() {} } });
  const controller = window.CommerceCopilot({ api: async (name, args) => {
    calls.push([name, args]);
    if (apiOverride) { const result = await apiOverride(name, args); if (result !== undefined) return result; }
    if (name === 'commerce_model_list') return { models: [] };
    if (name === 'commerce_copilot_list') return { threads: [thread] };
    if (name === 'commerce_copilot_get') return thread;
    if (name === 'commerce_market_research_cancel') { job.status = 'cancelled'; return job; }
    if (name === 'commerce_market_research_resume') return job;
    throw Error('unexpected API: ' + name);
  }, getContext: () => context, isActive: () => true, inline: true, compact: true, repaint() {}, toast() {}, scopeLabel: () => '研究 · RU', onResearch: id => opened.push(['task', id]), onOpenCandidate: (id, taskId) => opened.push(['case', id, taskId]) });
  const emit = (name, event) => { for (const handler of events.get(name) || []) handler(event); };
  const click = (action, data = {}) => { const target = { dataset: { copilotAction: action, ...data }, closest(selector) { return selector === '[data-copilot-action]' ? target : null; } }; emit('click', { target, preventDefault() {} }); };
  controller.open(undefined, { focus: false });
  return { controller, calls, timers, job, run, thread, opened, emit, click };
}
const flush = () => new Promise(setImmediate);
async function ready(s) { await flush(); await s.controller.openThread('thread-a'); }

test('completed model run keeps polling the original active research without sending again', async () => {
  const s = setup(); await ready(s); const before = s.calls.length;
  for (const poll of s.timers) poll(); await flush();
  assert.ok(s.calls.slice(before).some(([name]) => name === 'commerce_copilot_get'));
  assert.ok(!s.calls.some(([name]) => /send|start|resume/.test(name)));
  assert.ok(s.controller.view().includes('采集公开资料'));
  assert.equal(s.run.result_sha256, 'fixed-result');
  s.emit('input', { target: { id: 'copilot-message', value: '采集中保留下一条' } });
  s.emit('keydown', { key: 'Enter', ctrlKey: true, target: { id: 'copilot-message' }, preventDefault() {} }); await flush();
  assert.ok(!s.calls.some(([name]) => name === 'commerce_copilot_send'));
  assert.ok(s.controller.view().includes('采集中保留下一条')); s.controller.dispose();
});
test('cancel acts on the same task and refreshes its status', async () => {
  const s = setup(); await ready(s); s.click('research-cancel', { task: 'task-a' }); await flush();
  const call = s.calls.find(([name]) => name === 'commerce_market_research_cancel');
  assert.deepEqual(JSON.parse(JSON.stringify(call[1])), { task_id: 'task-a' });
  assert.ok(s.controller.view().includes('已停止')); s.controller.dispose();
});
test('unknown resume retains its idempotency key and revision after an unconfirmed response', async () => {
  const s = setup('unknown', async name => { if (name === 'commerce_market_research_resume') throw Error('request_outcome_unknown'); }); await ready(s);
  s.click('research-resume', { task: 'task-a' }); await flush(); s.click('research-resume', { task: 'task-a' }); await flush();
  const calls = s.calls.filter(([name]) => name === 'commerce_market_research_resume');
  assert.equal(calls.length, 2); assert.equal(calls[0][1].idempotency_key, calls[1][1].idempotency_key); assert.equal(calls[0][1].expected_revision, 3);
  assert.ok(s.controller.view().includes('不会自动重试')); s.controller.dispose();
});
test('saved candidate navigation is bound to the server result and names are escaped', async () => {
  const s = setup('partial'); s.job.candidates = [{ case_id: 'case-a', name: '<img src=x onerror=alert(1)>', source_url: 'javascript:alert(1)', workspace_url: 'javascript:alert(1)', source_ids: ['S1'] }]; s.job.candidate_count = 1; await ready(s);
  const html = s.controller.view(); assert.ok(!html.includes('<img')); assert.ok(!html.includes('javascript:')); assert.ok(html.includes('部分完成'));
  s.click('research-candidate', { task: 'task-a', case: 'unlisted-case' }); await flush(); assert.equal(s.opened.length, 0);
  s.click('research-candidate', { task: 'task-a', case: 'case-a' }); await flush(); assert.deepEqual(s.opened, [['case', 'case-a', 'task-a']]);
  const before = s.calls.length; for (const poll of s.timers) poll(); await flush(); assert.equal(s.calls.length, before); s.controller.dispose();
});
test('one research task appears once across follow-up turns', async () => {
  const s = setup('completed'); const older = { ...s.run, id: 'run-old' }; s.thread.turns.unshift({ id: 'turn-old', question: '旧要求', run: older }); await ready(s);
  assert.equal(s.controller.view().split('data-research-task=').length - 1, 1); s.controller.dispose();
});

test('clarification watches cross-client continuation using reads and preserves one reply control', async () => {
  const s = setup('awaiting_input'); s.job.questions = ['选择哪个品类？']; s.run.result.questions = ['选择哪个品类？']; await ready(s);
  const html = s.controller.view(); assert.equal(html.split('选择哪个品类？').length - 1, 1); assert.equal(html.split('data-copilot-action="reply"').length - 1, 1);
  const before = s.calls.length; for (const poll of s.timers) poll(); await flush();
  assert.ok(s.calls.slice(before).some(([name]) => name === 'commerce_copilot_get'));
  assert.ok(!s.calls.some(([name]) => /send|start|resume/.test(name))); s.controller.dispose();
});
test('research summary remains visible when the model answer is the same summary', async () => {
  const s = setup('partial'); s.job.report = { summary: s.run.result.answer }; await ready(s);
  assert.equal(s.controller.view().split(s.run.result.answer).length - 1, 1); s.controller.dispose();
});

test('unconfirmed send preserves the selected model hash and request key on explicit retry', async () => {
  const s = setup('partial', async name => { if (name === 'commerce_copilot_send') throw Error('request_outcome_unknown'); });
  s.thread.model_selection = { sha256: 'a'.repeat(64) }; await ready(s);
  s.emit('input', { target: { id: 'copilot-message', value: '继续核对原候选' } });
  s.click('send'); await flush(); s.thread.model_selection = { sha256: 'b'.repeat(64) };
  s.click('send'); await flush();
  const calls = s.calls.filter(([name]) => name === 'commerce_copilot_send'); assert.equal(calls.length, 2);
  assert.equal(calls[0][1].expected_model_sha256, 'a'.repeat(64)); assert.equal(calls[1][1].expected_model_sha256, calls[0][1].expected_model_sha256);
  assert.equal(calls[0][1].idempotency_key, calls[1][1].idempotency_key); assert.ok(s.controller.view().includes('继续核对原候选')); s.controller.dispose();
});
test('changed model rejection reloads without resending or losing the draft', async () => {
  const s = setup('partial', async name => { if (name === 'commerce_copilot_send') { s.thread.model_selection = { sha256: 'b'.repeat(64) }; const error = Error('copilot_model_changed'); error.code = 'copilot_model_changed'; throw error; } });
  s.thread.model_selection = { sha256: 'a'.repeat(64) }; await ready(s);
  s.emit('input', { target: { id: 'copilot-message', value: '保留补充要求' } });
  s.click('send'); await flush(); await flush();
  assert.equal(s.calls.filter(([name]) => name === 'commerce_copilot_send').length, 1); assert.ok(s.controller.view().includes('模型配置已变化')); assert.ok(s.controller.view().includes('保留补充要求'));
  const first = s.calls.find(([name]) => name === 'commerce_copilot_send')[1]; s.click('send'); await flush();
  const second = s.calls.filter(([name]) => name === 'commerce_copilot_send')[1][1];
  assert.equal(second.expected_model_sha256, 'b'.repeat(64)); assert.notEqual(second.idempotency_key, first.idempotency_key); s.controller.dispose();
});

test('partial research has a terminal Chinese status without generic cancel or retry capabilities', async () => {
  const context = vm.createContext({}); vm.runInContext(await readFile('../ui/status.js', 'utf8'), context);
  const status = context.CommerceStatus.describe('partial', { cancel: true, retry: true });
  assert.equal(status.label, '部分完成'); assert.equal(status.terminal, true); assert.equal(status.canCancel, false); assert.equal(status.canRetry, false);
  assert.equal(context.CommerceStatus.describe('awaiting_input').label, '等待补充信息');
});
