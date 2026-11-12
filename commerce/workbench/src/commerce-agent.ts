import { AbstractAgent, EventType, type RunAgentInput, type BaseEvent, type Message } from '@ag-ui/client';
import { Observable } from 'rxjs';
import { api, newKey } from './api';
import type { BusinessContext, Thread } from './types';

export function transcript(thread: Thread): Message[] {
  return thread.turns.flatMap(turn => {
    const result: Message[] = [{ id: 'q-' + turn.id, role: 'user', content: turn.question }];
    if (turn.run.result?.answer) result.push({ id: 'a-' + turn.id, role: 'assistant', content: turn.run.result.answer });
    return result;
  });
}

/** AG-UI lifecycle over the existing durable Python runner, with no second LLM. */
export class CommerceAgent extends AbstractAgent {
  backend: Thread | null = null;
  constructor(readonly context: BusinessContext) { super({ agentId: 'commerce', description: '本机共享业务助手' }); }
  async restore(thread: Thread) { this.backend = thread; this.setMessages(transcript(thread)); }
  run(input: RunAgentInput): Observable<BaseEvent> {
    return new Observable(observer => {
      let detached = false;
      const emit = (event: BaseEvent) => { if (!detached) observer.next(event); };
      const execute = async () => {
        const message = [...input.messages].reverse().find(m => m.role === 'user');
        if (!message || typeof message.content !== 'string' || !message.content.trim()) throw Error('invalid_message');
        this.backend ??= await api<Thread>('commerce_copilot_open', { context: this.context, title: '运营协作', idempotency_key: 'react-thread:' + newKey() });
        const original = this.backend;
        const value = await api<Thread>('commerce_copilot_send', { thread_id: original.id, message: message.content, context_sha256: original.context_sha256, idempotency_key: 'react-turn:' + input.runId });
        this.backend = value;
        const runId = value.latest_run?.id;
        if (!runId) throw Error('missing_run_receipt');
        emit({ type: EventType.RUN_STARTED, threadId: input.threadId, runId: input.runId });
        // These are real queue states, not simulated token streaming.
        const deadline = Date.now() + 10 * 60 * 1000;
        while (!detached && ['queued', 'running', 'cancel_requested'].includes(this.backend.latest_run?.status || '')) {
          if (Date.now() > deadline) throw Error('request_outcome_unknown');
          await new Promise(resolve => setTimeout(resolve, 1200));
          if (detached) return;
          this.backend = await api<Thread>('commerce_copilot_get', { thread_id: original.id });
          emit({ type: EventType.STATE_SNAPSHOT, snapshot: { backend_thread_id: original.id, status: this.backend.latest_run?.status } });
        }
        if (detached) return;
        const run = this.backend.latest_run;
        if (!run || run.id !== runId) throw Error('run_changed');
        if (!run.result?.answer && !['completed', 'review', 'needs_input', 'awaiting_input', 'awaiting_review'].includes(run.status)) throw Error(run.error || 'agent_run_' + run.status);
        const id = 'a-' + run.id;
        emit({ type: EventType.TEXT_MESSAGE_START, messageId: id, role: 'assistant' });
        emit({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: id, delta: run.result?.answer || '本轮需要补充资料，请查看原任务。' });
        emit({ type: EventType.TEXT_MESSAGE_END, messageId: id });
        emit({ type: EventType.RUN_FINISHED, threadId: input.threadId, runId: input.runId });
        observer.complete();
      };
      void execute().catch(error => { if (!detached) { observer.error(error); } });
      return () => { detached = true; }; // A detached browser never cancels or replays the server run.
    });
  }
}
