import { AbstractAgent, type RunAgentInput, type BaseEvent, type Message } from '@ag-ui/client';
import { Observable } from 'rxjs';
import '../../web/copilot-events.js';
import { api, newKey } from './api';
import type { BusinessContext, Thread } from './types';

export function transcript(thread: Thread): Message[] {
  return thread.turns.flatMap(turn => {
    const result: Message[] = [{ id: 'q-' + turn.id, role: 'user', content: turn.question }];
    if (turn.run.result?.answer) result.push({ id: 'a-' + turn.run.id, role: 'assistant', content: turn.run.result.answer });
    return result;
  });
}

/** AG-UI lifecycle over the existing durable Python runner, with no second LLM. */
export class CommerceAgent extends AbstractAgent {
  backend: Thread | null = null;
  constructor(readonly context: BusinessContext, readonly invoke: typeof api = api, readonly pollMs = 400) { super({ agentId: 'commerce', description: '本机共享业务助手' }); }
  async restore(thread: Thread) { this.backend = thread; this.setMessages(transcript(thread)); }
  run(input: RunAgentInput): Observable<BaseEvent> {
    return this.observe(input);
  }
  /** Reattach to the exact durable run. This path never opens/sends a request. */
  resume(input: RunAgentInput, thread: Thread, runId: string): Observable<BaseEvent> {
    this.backend = thread;
    return this.observe(input, { thread, runId });
  }
  private observe(input: RunAgentInput, resume?: {thread: Thread; runId: string}): Observable<BaseEvent> {
    return new Observable(observer => {
      let detached = false, stop: (() => void) | undefined;
      const execute = async () => {
        if (!resume) {
          const message = [...input.messages].reverse().find(m => m.role === 'user');
          if (!message || typeof message.content !== 'string' || !message.content.trim()) throw Error('invalid_message');
          this.backend ??= await this.invoke<Thread>('commerce_copilot_open', { context: this.context, title: '运营协作', idempotency_key: 'react-thread:' + newKey() });
          this.backend = await this.invoke<Thread>('commerce_copilot_send', { thread_id: this.backend.id, message: message.content, context_sha256: this.backend.context_sha256, idempotency_key: 'react-turn:' + input.runId });
        }
        const original = resume?.thread || this.backend;
        const runId = resume?.runId || this.backend?.latest_run?.id;
        if (!runId || !original) throw Error('missing_run_receipt');
        if (detached) return;
        stop = globalThis.CommerceRunEvents.observe({api: this.invoke, thread: original, runId, pollMs: this.pollMs,
          eventThreadId: input.threadId, eventRunId: input.runId,
          onEvent: event => observer.next(event),
          onComplete: thread => {this.backend = thread; observer.complete();},
          onError: (error, thread) => {if(thread)this.backend = thread; observer.error(error);}
        });
      };
      void execute().catch(error => { if (!detached) { observer.error(error); } });
      return () => { detached = true; stop?.(); }; // A detached browser never cancels or replays the server run.
    });
  }
}
