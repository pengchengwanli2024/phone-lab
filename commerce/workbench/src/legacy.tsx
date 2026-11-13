import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';
import type { BusinessContext, Theme } from './types';
import { Button } from './ui';
declare const __PRODUCT_HTML__: string;
export function Legacy({ tab, demo, theme, caseId, active = true, requestedTab, navigate, onCopilot, chatWidth, onChatWidth, assistantToggle = 0, onAssistantState, onResearch, researchTaskId = '', onResearchContext }: { tab: string; demo: boolean; theme: Theme; caseId: string; active?: boolean; requestedTab?: string; navigate: (tab: string, caseId?: string, researchTaskId?: string) => void; researchTaskId?: string; onResearchContext?: (caseId: string, taskId: string) => void; onCopilot?: (context: BusinessContext) => void; chatWidth?: number; onChatWidth?: (width: number) => void; assistantToggle?: number; onAssistantState?: (visible: boolean) => void; onResearch?: (id: string) => void }) {
  const researchRequest=useRef(researchTaskId),researchContextCallback=useRef(onResearchContext);researchRequest.current=researchTaskId;researchContextCallback.current=onResearchContext;
  const frame = useRef<HTMLIFrameElement>(null), nonce = useRef(crypto.randomUUID()), [ready, setReady] = useState(false);
  const [refreshStatus, setRefreshStatus] = useState('');
  const [refreshEpoch, setRefreshEpoch] = useState(0);
  const previousActive = useRef<boolean | null>(null);
  const awaitingRefresh = useRef(false);
  const copilotCallback = useRef(onCopilot); copilotCallback.current = onCopilot;
  const widthCallback=useRef(onChatWidth);widthCallback.current=onChatWidth;
  const assistantCallback=useRef(onAssistantState);assistantCallback.current=onAssistantState;
  const lastAssistantToggle=useRef(assistantToggle);
  const researchCallback=useRef(onResearch);researchCallback.current=onResearch;
  const product = tab === 'workspace';
  // Product selection must not rebuild an unrelated store/form document.
  const frameCaseId = product ? caseId : '';
  const legacyTab = tab === 'restock' ? 'operations' : tab;
  const mode = tab === 'restock' ? 'stock' : 'cost';
  const source = useMemo(() => {
    const bootstrap = JSON.stringify({ tab: legacyTab, mode, demo, case_id: frameCaseId, research_task_id: product ? researchRequest.current : undefined, bridge: true, embedded: !product, hosted: true, reactHost: true }).replaceAll('<', '\\u003c');
    let html = product ? __PRODUCT_HTML__.replace('__COMMERCE_NESTED_BOOTSTRAP__', () => bootstrap) : __LEGACY_HTML__.replace('<script>', () => `<script>window.__COMMERCE_LEGACY__=${bootstrap};`);
    if (product) html = html.replace('</head>', '<style>.pw-sidebar,.pw-topbar,.pw-platform-bottom-nav{display:none!important}.pw-frame{grid-template-columns:minmax(0,1fr)!important}.pw-body{grid-column:1/-1!important;height:100dvh!important}.pw-columns{height:100%!important}</style></head>');
    return html.replaceAll('__COMMERCE_NESTED_NONCE__', nonce.current);
  }, [product, frameCaseId, demo]);
  useEffect(() => {
    previousActive.current = null;
    awaitingRefresh.current = false;
    let active = true;
    const draftStorage = window.CommerceCopilotDraftStorage();
    const receive = async (event: MessageEvent) => {
      const m = event.data;
      if (event.source !== frame.current?.contentWindow || m?.nonce !== nonce.current) return;
      if(m.type==='commerce:copilot-draft'){
        if(typeof m.id!=='string'||m.id.length>80)return;
        const target=event.source as Window;
        try{const value=await draftStorage.request(m.op,m.key,m.value,m.expected);if(active&&target===frame.current?.contentWindow)target.postMessage({type:'commerce:copilot-draft-result',nonce:nonce.current,id:m.id,value},'*')}
        catch(error){if(active&&target===frame.current?.contentWindow)target.postMessage({type:'commerce:copilot-draft-result',nonce:nonce.current,id:m.id,error:error instanceof Error?error.message:'draft_storage_unavailable'},'*')}
        return;
      }
      if(product&&m.type==='commerce:workspace-research'&&typeof m.task_id==='string'&&/^[a-zA-Z0-9_-]{1,100}$/.test(m.task_id)){researchCallback.current?.(m.task_id);return;}
      if(product&&m.type==='commerce:workspace-assistant-state'){if(typeof m.visible==='boolean')assistantCallback.current?.(m.visible);return;}
      if(product&&m.type==='commerce:workspace-chat-width'){if(typeof m.width==='number'&&Number.isFinite(m.width)&&m.width>=320&&m.width<=960)widthCallback.current?.(m.width);return;}
      if (m.type === 'commerce:legacy-ready' || m.type === 'commerce:workspace-ready') { setReady(true); return; }
      if (m.type === 'commerce:workspace-refresh-result' && (!caseId || m.case_id === caseId) && ['refreshed','deferred','failed','superseded'].includes(m.status)) { awaitingRefresh.current = false; setRefreshStatus(m.status); setRefreshEpoch(v => v + 1); return; }
      if (m.type === 'commerce:workspace-backend') { navigate('workspace'); return; }
      if (m.type === 'commerce:workspace-open') { navigate('workspace'); return; }
      if (m.type === 'commerce:workspace-copilot') {
        const context = m.context;
        if (!context || typeof context.module !== 'string' || typeof context.demo !== 'boolean') return;
        const safe: BusinessContext = { module: context.module, demo: context.demo };
        for (const key of ['platform', 'market', 'store_id'] as const) if (typeof context[key] === 'string' && context[key].length <= 160) safe[key] = context[key];
        if (context.entity && typeof context.entity.kind === 'string' && typeof context.entity.id === 'string' && context.entity.kind.length <= 40 && context.entity.id.length <= 160) safe.entity = { kind: context.entity.kind, id: context.entity.id };
        copilotCallback.current?.(safe); return;
      }
      if (m.type === 'commerce:workspace-navigate' && typeof m.tab === 'string') { navigate(m.tab); return; }
      if (m.type === 'commerce:workspace-selected' && typeof m.case_id === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(m.case_id)) { if(m.research_task_id!=null&&(typeof m.research_task_id!=='string'||(m.research_task_id&&!/^[a-zA-Z0-9_-]{1,160}$/.test(m.research_task_id))))return; if (m.case_id !== caseId) navigate('workspace', m.case_id, m.research_task_id||''); else researchContextCallback.current?.(m.case_id,m.research_task_id||''); return; }
      if (m.type === 'commerce:workspace-dynamic-cost' && typeof m.case_id === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(m.case_id)) { navigate('operations', m.case_id); return; }
      if (m.type !== 'commerce:call' || typeof m.id !== 'string' || typeof m.tool !== 'string' || !/^commerce_(?:[a-z_]+|a2ui_[a-z_]+)$/.test(m.tool)) return;
      const target = event.source as Window;
      try { const result = await api(m.tool, m.arguments || {}); if (active && target === frame.current?.contentWindow) target.postMessage({ type: 'commerce:result', nonce: nonce.current, id: m.id, result }, '*'); }
      catch (e) { if (active) target.postMessage({ type: 'commerce:result', nonce: nonce.current, id: m.id, error: e instanceof Error ? e.message : 'request_failed' }, '*'); }
    };
    window.addEventListener('message', receive); return () => { active = false; draftStorage.dispose(); setReady(false); window.removeEventListener('message', receive); };
  }, [source]);
  useEffect(()=>{if(product&&ready)frame.current?.contentWindow?.postMessage({type:'commerce:workspace-research-context',nonce:nonce.current,case_id:caseId,research_task_id:researchTaskId},'*');},[product,ready,caseId,researchTaskId]);
  useEffect(()=>{if(product&&ready&&assistantToggle!==lastAssistantToggle.current){lastAssistantToggle.current=assistantToggle;frame.current?.contentWindow?.postMessage({type:'commerce:workspace-assistant-toggle',nonce:nonce.current},'*');}},[product,ready,assistantToggle]);
  useEffect(()=>{if(product&&ready&&typeof chatWidth==='number'&&Number.isFinite(chatWidth)&&chatWidth>=320&&chatWidth<=960)frame.current?.contentWindow?.postMessage({type:'commerce:workspace-layout',nonce:nonce.current,chat_width:chatWidth},'*');},[ready,product,chatWidth]);
  useEffect(() => { if (ready) frame.current?.contentWindow?.postMessage(product ? { type: 'commerce:theme', nonce: nonce.current, theme } : { type: 'commerce:legacy-navigate', nonce: nonce.current, tab: legacyTab, mode, theme }, '*'); }, [ready, legacyTab, mode, theme, product]);
  useEffect(() => {
    if (!product || !ready) return;
    if (active && previousActive.current === false) { awaitingRefresh.current = true; frame.current?.contentWindow?.postMessage({ type: 'commerce:workspace-refresh', nonce: nonce.current }, '*'); }
    previousActive.current = active;
  }, [active, product, ready]);
  useEffect(() => { if (product && active && ready && requestedTab && !awaitingRefresh.current) frame.current?.contentWindow?.postMessage({ type: 'commerce:workspace-tab', nonce: nonce.current, tab: requestedTab }, '*'); }, [product, active, ready, requestedTab, refreshEpoch]);
  return <div className="r-legacy-shell">{product && ['deferred','failed','superseded'].includes(refreshStatus) && <div className="r-refresh-notice" role="status"><span>{refreshStatus === 'deferred' ? '原商品有未保存编辑或正在处理，已延后刷新。请在成本阶段核对当前版本。' : '原商品尚未刷新，请核对当前版本后继续。'}</span><Button onClick={() => frame.current?.contentWindow?.postMessage({ type: 'commerce:workspace-tab', nonce: nonce.current, tab: 'cost' }, '*')}>查看原成本阶段</Button></div>}<iframe ref={frame} title={product ? '完整商品内容编辑' : '专业业务模块'} srcDoc={source} sandbox="allow-scripts allow-forms allow-downloads" className="r-legacy" referrerPolicy="no-referrer" /></div>;
}
