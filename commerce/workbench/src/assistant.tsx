import { useEffect, useRef, useState } from 'react';
import '../../web/copilot-evidence.js';
import '../../web/copilot-interactions.js';
import '../../web/copilot-events.js';
import '../../web/copilot-reading.js';
import '../../web/copilot-upload.js';
import '../../web/generative-ui.js';
import '../../web/copilot-capabilities.js';
import '../../web/copilot-capabilities.css';
import '../../web/copilot-ui.js';
import '../../web/copilot-ui.css';
import { api, errorText } from './api';
import { productScope } from './copilot-scope';
import type { BusinessContext, PageContext, Product, SharedCopilotController } from './types';
import { Button, Dialog, Empty, ErrorNotice } from './ui';

interface Props { pageReady?:boolean;context: BusinessContext; pageContext?: PageContext; visible?: boolean; close: () => void; onWorkspace?: () => void; requestedThreadId?: string; onResearch?: (id: string) => void; onOpenCandidate?: (id: string, researchTaskId?: string) => void; onModels?: () => void; }
interface Review { title: string; body: string; actions: string; }

/** The exact product Copilot factory, mounted once across module navigation. */
export function Assistant({ pageReady=true,context, pageContext, visible = true, close: _close, onWorkspace, requestedThreadId, onResearch, onOpenCandidate, onModels }: Props) {
  const host = useRef<HTMLDivElement>(null), controller = useRef<SharedCopilotController | null>(null);
  const current = useRef(context), active = useRef(false), workspace = useRef(onWorkspace), research = useRef(onResearch), candidate = useRef(onOpenCandidate), models = useRef(onModels), generation = useRef(0);
  const shown = useRef(visible), scopeReady = useRef(false);
  const returnFocus=useRef<string|null>(null);
  const [resolvedSignature,setResolvedSignature] = useState('');
  const [ready, setReady] = useState(false), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const [review, setReview] = useState<Review | null>(null), [announcement, setAnnouncement] = useState('');
  workspace.current = onWorkspace; research.current = onResearch; candidate.current = onOpenCandidate; models.current = onModels;
  const metadataReady=useRef(pageReady);metadataReady.current=pageReady;
  shown.current = visible;
  const signature = JSON.stringify(context), pageSignature=JSON.stringify(pageContext);
  const page=useRef(pageContext);page.current=pageContext;
  const scopeMatches=resolvedSignature===signature;
  active.current = visible && ready && scopeMatches && pageReady;

  useEffect(() => {
    let alive = true;
    const repaint = () => {
      if (!alive || !host.current || !controller.current) return;
      host.current.innerHTML = controller.current.view();
      controller.current.afterPaint();
    };
    controller.current = window.CommerceCopilot({
      api: (tool, args) => api(tool, args), inline: true, compact: true,
      getContext: () => current.current, getPageContext:()=>({...page.current,page:page.current?.page||current.current.module,demo:!!current.current.demo}), isActive: () => active.current, repaint,
      modal: (title, body, actions = '') => {returnFocus.current=null;setReview({ title, body, actions });}, closeModal: focusId => {returnFocus.current=focusId||null;setReview(null);},
      toast: setAnnouncement, onWorkspace: () => workspace.current?.(), onModels: () => models.current?.(), onResearch: id => research.current?.(id), onOpenCandidate: (id, taskId) => candidate.current?.(id, taskId),
      errorText: failure => errorText(failure instanceof Error ? failure : Error(failure.message || failure.code || 'request_failed')),
    });
    return () => { alive = false; controller.current?.dispose(); controller.current = null; };
  }, []);

  useEffect(() => {
    if (visible && pageReady && scopeMatches && scopeReady.current) controller.current?.open(undefined, { focus: false });
    else { controller.current?.close(); setReview(null); }
  }, [visible,pageReady]);

  useEffect(() => {
    const version = ++generation.current;
    active.current = false; scopeReady.current = false; controller.current?.close(); setReady(false); setError(''); setReview(null);
    async function resolve() {
      try {
        const resolved = context.entity?.kind === 'case'
          ? productScope(context, await api<Product>('commerce_workspace_get', { case_id: context.entity.id }))
          : context;
        if (version !== generation.current) return;
        current.current = resolved; setResolvedSignature(signature); scopeReady.current = true; setReady(true);
        if (shown.current && metadataReady.current) { active.current = true; controller.current?.open(undefined, { focus: false }); if (requestedThreadId) await controller.current?.openThread(requestedThreadId); }
      } catch (failure) { if (version === generation.current) setError(errorText(failure)); }
    }
    void resolve();
    return () => { generation.current++; };
  }, [signature, retry, requestedThreadId]);

  useEffect(()=>{controller.current?.contextChanged()},[pageSignature]);

  return <aside className="r-assistant r-shared-assistant" aria-label="AI 业务对话" hidden={!visible} aria-busy={(!ready || !scopeMatches || !pageReady) && !error}>
    {(!ready || !scopeMatches || !pageReady) && (error ? <><ErrorNotice>{error}</ErrorNotice><Button onClick={() => setRetry(v => v + 1)}>重新读取范围</Button></> : <Empty>正在读取当前工作范围…</Empty>)}
    <div ref={host} className="r-shared-copilot" hidden={!ready || !scopeMatches || !pageReady} />
    <span className="sr-only" role="status">{announcement}</span>
    {review && <Dialog title={review.title} close={() => setReview(null)} returnFocus={returnFocus}>
      <div dangerouslySetInnerHTML={{ __html: review.body }} />
      <div className="r-actions" dangerouslySetInnerHTML={{ __html: review.actions }} />
    </Dialog>}
  </aside>;
}
