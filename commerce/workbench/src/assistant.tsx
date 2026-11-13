import { useEffect, useRef, useState } from 'react';
import '../../web/copilot-ui.js';
import '../../web/copilot-ui.css';
import { api, errorText } from './api';
import { productScope } from './copilot-scope';
import type { BusinessContext, Product, SharedCopilotController } from './types';
import { Button, Dialog, Empty, ErrorNotice } from './ui';

interface Props { context: BusinessContext; visible?: boolean; close: () => void; onWorkspace?: () => void; requestedThreadId?: string; onResearch?: (id: string) => void; onOpenCandidate?: (id: string) => void; }
interface Review { title: string; body: string; actions: string; }

/** The exact product Copilot factory, mounted once across module navigation. */
export function Assistant({ context, visible = true, close: _close, onWorkspace, requestedThreadId, onResearch, onOpenCandidate }: Props) {
  const host = useRef<HTMLDivElement>(null), controller = useRef<SharedCopilotController | null>(null);
  const current = useRef(context), active = useRef(false), workspace = useRef(onWorkspace), research = useRef(onResearch), candidate = useRef(onOpenCandidate), generation = useRef(0);
  const shown = useRef(visible), scopeReady = useRef(false);
  const [ready, setReady] = useState(false), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const [review, setReview] = useState<Review | null>(null), [announcement, setAnnouncement] = useState('');
  workspace.current = onWorkspace; research.current = onResearch; candidate.current = onOpenCandidate;
  shown.current = visible;
  const signature = JSON.stringify(context);
  active.current = visible && ready;

  useEffect(() => {
    let alive = true;
    const repaint = () => {
      if (!alive || !host.current || !controller.current) return;
      host.current.innerHTML = controller.current.view();
      controller.current.afterPaint();
    };
    controller.current = window.CommerceCopilot({
      api: (tool, args) => api(tool, args), inline: true, compact: true,
      getContext: () => current.current, isActive: () => active.current, repaint,
      modal: (title, body, actions = '') => setReview({ title, body, actions }), closeModal: () => setReview(null),
      toast: setAnnouncement, onWorkspace: () => workspace.current?.(), onResearch: id => research.current?.(id), onOpenCandidate: id => candidate.current?.(id),
      errorText: failure => errorText(failure instanceof Error ? failure : Error(failure.message || failure.code || 'request_failed')),
    });
    return () => { alive = false; controller.current?.dispose(); controller.current = null; };
  }, []);

  useEffect(() => {
    if (visible && scopeReady.current) controller.current?.open(undefined, { focus: false });
    else { controller.current?.close(); setReview(null); }
  }, [visible]);

  useEffect(() => {
    const version = ++generation.current;
    active.current = false; scopeReady.current = false; controller.current?.close(); setReady(false); setError(''); setReview(null);
    async function resolve() {
      try {
        const resolved = context.entity?.kind === 'case'
          ? productScope(context, await api<Product>('commerce_workspace_get', { case_id: context.entity.id }))
          : context;
        if (version !== generation.current) return;
        current.current = resolved; scopeReady.current = true; setReady(true);
        if (shown.current) { active.current = true; controller.current?.open(undefined, { focus: false }); if (requestedThreadId) await controller.current?.openThread(requestedThreadId); }
      } catch (failure) { if (version === generation.current) setError(errorText(failure)); }
    }
    void resolve();
    return () => { generation.current++; };
  }, [signature, retry, requestedThreadId]);

  return <aside className="r-assistant r-shared-assistant" aria-label="AI 业务对话" hidden={!visible} aria-busy={!ready && !error}>
    {!ready && (error ? <><ErrorNotice>{error}</ErrorNotice><Button onClick={() => setRetry(v => v + 1)}>重新读取范围</Button></> : <Empty>正在读取当前工作范围…</Empty>)}
    <div ref={host} className="r-shared-copilot" hidden={!ready} />
    <span className="sr-only" role="status">{announcement}</span>
    {review && <Dialog title={review.title} close={() => setReview(null)}>
      <div dangerouslySetInnerHTML={{ __html: review.body }} />
      <div className="r-actions" dangerouslySetInnerHTML={{ __html: review.actions }} />
    </Dialog>}
  </aside>;
}
