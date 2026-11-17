import type {CreativeIntent} from './creative-intent';
import { useEffect, useMemo, useRef, useState } from 'react';
import type {OrderSupportRequest,PreparedOrderSupport} from './order-support';
import { api } from './api';
import type { BusinessContext, PageContext, Theme } from './types';
import { Button } from './ui';
import { embeddedDocument } from './embedded-document';
declare const __PRODUCT_HTML__: string;
export function Legacy({ tab, demo, theme, caseId, active = true, requestedTab, requestedTabEpoch=0,navigate, onCopilot, onPageContext,onEditState,onSelectedProduct,onCost,onCreative,onCreativeOpened,creativeIntent,chatWidth, onChatWidth, assistantToggle = 0, onAssistantState, onResearch, researchTaskId = '', onResearchContext,orderSupportRequest,onOrderSupport,onOrderSupportResult }: { orderSupportRequest?:OrderSupportRequest|null;onOrderSupport?:(prepared:PreparedOrderSupport)=>Promise<void>;onOrderSupportResult?:(id:string,error?:string)=>void; onCost?:(caseId:string,delivery?:boolean)=>void;creativeIntent?:CreativeIntent|null;onCreative?:(intent:Omit<CreativeIntent,'id'>)=>void;onCreativeOpened?:(id:string,projectId:string)=>void;tab: string; demo: boolean; theme: Theme; caseId: string; active?: boolean; requestedTab?: string;requestedTabEpoch?:number; navigate: (tab: string, caseId?: string, researchTaskId?: string) => void; researchTaskId?: string; onResearchContext?: (caseId: string, taskId: string) => void; onCopilot?: (context: BusinessContext) => void; onPageContext?: (page: PageContext, scope: BusinessContext) => void;onEditState?:(caseId:string,dirty:boolean,section:string)=>void;onSelectedProduct?:(caseId:string,taskId:string)=>void; chatWidth?: number; onChatWidth?: (width: number) => void; assistantToggle?: number; onAssistantState?: (visible: boolean) => void; onResearch?: (id: string) => void }) {
  const orderCallback=useRef(onOrderSupport),orderResult=useRef(onOrderSupportResult);orderCallback.current=onOrderSupport;orderResult.current=onOrderSupportResult;
  const researchRequest=useRef(researchTaskId),researchContextCallback=useRef(onResearchContext);researchRequest.current=researchTaskId;researchContextCallback.current=onResearchContext;
  const costCallback=useRef(onCost);costCallback.current=onCost;
  const creativeCallback=useRef(onCreative),creativeOpened=useRef(onCreativeOpened),creativeRequest=useRef(creativeIntent);creativeCallback.current=onCreative;creativeOpened.current=onCreativeOpened;creativeRequest.current=creativeIntent;
  const frame = useRef<HTMLIFrameElement>(null), nonce = useRef(crypto.randomUUID()), [ready, setReady] = useState(false);
  const [refreshStatus, setRefreshStatus] = useState('');
  const [refreshEpoch, setRefreshEpoch] = useState(0);
  const previousActive = useRef<boolean | null>(null);
  const activeView=useRef(active);activeView.current=active;
  const awaitingRefresh = useRef(false);
  const copilotCallback = useRef(onCopilot); copilotCallback.current = onCopilot;
  const selectedCallback=useRef(onSelectedProduct);selectedCallback.current=onSelectedProduct;
  const editCallback=useRef(onEditState);editCallback.current=onEditState;
  const editSection=useRef('cost');
  const lastPage=useRef<{page:PageContext;scope:BusinessContext}|null>(null);
  const pageCallback=useRef(onPageContext);pageCallback.current=onPageContext;
  const widthCallback=useRef(onChatWidth);widthCallback.current=onChatWidth;
  const assistantCallback=useRef(onAssistantState);assistantCallback.current=onAssistantState;
  const lastAssistantToggle=useRef(assistantToggle);
  const researchCallback=useRef(onResearch);researchCallback.current=onResearch;
  const product = tab === 'workspace';
  const packed = product ? __PRODUCT_HTML__ : __LEGACY_HTML__;
  const [documentState,setDocumentState]=useState<{packed:string;html:string}|null>(null);
  const [documentError,setDocumentError]=useState(''),[documentRetry,setDocumentRetry]=useState(0);
  const documentHtml=documentState?.packed===packed?documentState.html:'';
  useEffect(()=>{
    let current=true;setDocumentState(null);setDocumentError('');
    void embeddedDocument(packed).then(html=>{if(current)setDocumentState({packed,html});}).catch(error=>{
      if(current)setDocumentError(error instanceof Error&&error.message==='embedded_document_unsupported'?'当前浏览器无法载入离线业务模块，请使用支持 gzip 解压的浏览器。':'业务模块未能载入，请重新载入。');
    });
    return()=>{current=false;};
  },[packed,documentRetry]);
  // Product selection must not rebuild an unrelated store/form document.
  const frameCaseId = product ? caseId : '';
  const legacyTab = tab === 'restock' ? 'operations' : tab;
  const mode = tab === 'restock' ? 'stock' : 'cost';
  const source = useMemo(() => {
    if(!documentHtml)return '';
    nonce.current=crypto.randomUUID();
    const bootstrap = JSON.stringify({ tab: legacyTab, mode, demo, intel_section: !product && legacyTab === 'intelligence' && location.hash === '#social' ? 'social' : undefined, case_id: frameCaseId, research_task_id: product ? researchRequest.current : undefined, bridge: true, embedded: true, hosted: true, reactHost: true }).replaceAll('<', '\\u003c');
    let html = product ? documentHtml.replace('__COMMERCE_NESTED_BOOTSTRAP__', () => bootstrap) : documentHtml.replace('<script>', () => `<script>window.__COMMERCE_LEGACY__=${bootstrap};`);
    return html.replaceAll('__COMMERCE_NESTED_NONCE__', nonce.current);
  }, [documentHtml, product, frameCaseId, demo]);
  useEffect(() => {
    if(!source)return;
    lastPage.current=null;
    previousActive.current = null;
    awaitingRefresh.current = false;
    let active = true,catalogCreativeRequest='';
    const draftStorage = window.CommerceCopilotDraftStorage();
    const shippingFiles = window.CommerceShippingFiles.createClient({target:window,nonce:'__COMMERCE_BRIDGE_NONCE__'});
    const receive = async (event: MessageEvent) => {
      const m = event.data;
      if (event.source !== frame.current?.contentWindow || m?.nonce !== nonce.current) return;
      if(product&&activeView.current&&m.type==='commerce:workspace-catalog-creative-pending'&&typeof m.id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(m.id)){catalogCreativeRequest=m.id;return;}
      if(product&&activeView.current&&m.type==='commerce:workspace-catalog-creative'&&m.catalog_request_id===catalogCreativeRequest&&catalogCreativeRequest&&typeof m.case_id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(m.case_id)&&typeof m.project_id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(m.project_id)&&typeof m.source_sha256==='string'&&/^[a-f0-9]{64}$/.test(m.source_sha256)){
        const currentNonce=nonce.current,target=frame.current?.contentWindow;
        try{const project=await api<{brief:{product_binding?:{case_id:string;source_sha256:string}}}>('commerce_creative_get',{project_id:m.project_id});if(!active||!activeView.current||nonce.current!==currentNonce||target!==frame.current?.contentWindow||m.catalog_request_id!==catalogCreativeRequest)return;const binding=project.brief.product_binding;if(!binding||binding.case_id!==m.case_id||binding.source_sha256!==m.source_sha256)throw Error('creative_product_scope_mismatch');creativeCallback.current?.({case_id:m.case_id,source_sha256:m.source_sha256,project_id:m.project_id});}
        catch{if(active&&activeView.current&&nonce.current===currentNonce&&m.catalog_request_id===catalogCreativeRequest)target?.postMessage({type:'commerce:workspace-creative-error',nonce:currentNonce},'*');}return;
      }
      if(product&&activeView.current&&m.type==='commerce:workspace-creative'&&m.case_id===caseId&&typeof m.source_sha256==='string'&&/^[a-f0-9]{64}$/.test(m.source_sha256)&&(!m.project_id||typeof m.project_id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(m.project_id))){creativeCallback.current?.({case_id:m.case_id,source_sha256:m.source_sha256,...(m.project_id?{project_id:m.project_id}:{})});return;}
      if(!product&&activeView.current&&m.type==='commerce:creative-open-result'&&m.id===creativeRequest.current?.id&&m.case_id===creativeRequest.current?.case_id&&typeof m.project_id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(m.project_id)){creativeOpened.current?.(m.id,m.project_id);return;}
      if(product&&m.type==='commerce:workspace-edit-state'&&m.case_id===caseId&&typeof m.dirty==='boolean'){const section=['overview','evidence','research','cost','media','content','plan','review'].includes(m.section)?m.section:'overview';editSection.current=section;editCallback.current?.(m.case_id,m.dirty,section);return;}
      if(m.type==='commerce:order-support-result'&&typeof m.id==='string'&&['accepted','failed'].includes(m.status)){orderResult.current?.(m.id,m.status==='failed'?(typeof m.error==='string'?m.error:'order_support_context_failed'):undefined);return;}
      if(m.type==='commerce:workspace-order-support'&&activeView.current){try{await orderCallback.current?.(m.prepared);}catch{}return;}
      if(m.type==='commerce:shipping-file'){
        await window.CommerceShippingFiles.handleRequest(event,{source:frame.current?.contentWindow||null,nonce:nonce.current,perform:(op,args)=>{if(!activeView.current)throw Error('shipping_file_view_hidden');return shippingFiles.request(op,args);},alive:()=>active&&event.source===frame.current?.contentWindow});
        return;
      }
      // A hidden frame can finish initialization after the user has left it.
      // Its reads/draft replies remain valid, but it cannot replace the active route.
      if(!activeView.current&&['commerce:workspace-backend','commerce:workspace-open','commerce:workspace-navigate','commerce:workspace-selected','commerce:workspace-dynamic-cost','commerce:workspace-research','commerce:workspace-copilot'].includes(m.type))return;
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
      if(m.type==='commerce:page-context') {
        const page=window.CommercePageContext.clean(m.page_context),context=m.context;
        if(!page||!context||typeof context.module!=='string'||typeof context.demo!=='boolean')return;
        const safe:BusinessContext={module:context.module,demo:context.demo};
        for(const key of ['platform','market','store_id']as const)if(typeof context[key]==='string'&&context[key].length<=160)safe[key]=context[key];
        if(context.entity&&typeof context.entity.kind==='string'&&typeof context.entity.id==='string'&&context.entity.kind.length<=40&&context.entity.id.length<=160)safe.entity={kind:context.entity.kind,id:context.entity.id};
        lastPage.current={page,scope:safe};if(activeView.current)pageCallback.current?.(page,safe);return;
      }
      if (m.type === 'commerce:workspace-copilot') {
        const context = m.context;
        if (!context || typeof context.module !== 'string' || typeof context.demo !== 'boolean') return;
        const safe: BusinessContext = { module: context.module, demo: context.demo };
        for (const key of ['platform', 'market', 'store_id'] as const) if (typeof context[key] === 'string' && context[key].length <= 160) safe[key] = context[key];
        if (context.entity && typeof context.entity.kind === 'string' && typeof context.entity.id === 'string' && context.entity.kind.length <= 40 && context.entity.id.length <= 160) safe.entity = { kind: context.entity.kind, id: context.entity.id };
        copilotCallback.current?.(safe); return;
      }
      if (m.type === 'commerce:workspace-navigate' && typeof m.tab === 'string') { navigate(m.tab, typeof m.case_id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(m.case_id)?m.case_id:undefined); return; }
      if (m.type === 'commerce:workspace-selected' && typeof m.case_id === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(m.case_id)) { if(m.research_task_id!=null&&(typeof m.research_task_id!=='string'||(m.research_task_id&&!/^[a-zA-Z0-9_-]{1,160}$/.test(m.research_task_id))))return; if (m.case_id !== caseId) {if(product&&selectedCallback.current)selectedCallback.current(m.case_id,m.research_task_id||'');else navigate('workspace', m.case_id, m.research_task_id||'');} else researchContextCallback.current?.(m.case_id,m.research_task_id||''); return; }
      if (m.type === 'commerce:workspace-dynamic-cost' && typeof m.case_id === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(m.case_id) && (!product||m.case_id===caseId)) { if(costCallback.current)costCallback.current(m.case_id,m.return_delivery===true);else navigate('operations', m.case_id); return; }
      if (m.type !== 'commerce:call' || typeof m.id !== 'string' || typeof m.tool !== 'string' || !/^commerce_(?:[a-z_]+|a2ui_[a-z_]+)$/.test(m.tool)) return;
      const target = event.source as Window;
      try { const result = await api(m.tool, m.arguments || {}); if (active && target === frame.current?.contentWindow) target.postMessage({ type: 'commerce:result', nonce: nonce.current, id: m.id, result }, '*'); }
      catch (e) { if (active) target.postMessage({ type: 'commerce:result', nonce: nonce.current, id: m.id, error: e instanceof Error ? e.message : 'request_failed' }, '*'); }
    };
    window.addEventListener('message', receive); return () => { active = false; draftStorage.dispose(); shippingFiles.dispose(); setReady(false); window.removeEventListener('message', receive); };
  }, [source]);
  useEffect(()=>{if(active&&ready){if(lastPage.current)pageCallback.current?.(lastPage.current.page,lastPage.current.scope);const tick=requestAnimationFrame(()=>frame.current?.contentWindow?.postMessage({type:product?'commerce:workspace-resume':'commerce:legacy-resume',nonce:nonce.current},'*'));return()=>cancelAnimationFrame(tick);}},[product,active,ready,legacyTab]);
  useEffect(()=>{if(!product&&ready&&orderSupportRequest)frame.current?.contentWindow?.postMessage({type:'commerce:order-support-context',nonce:nonce.current,...orderSupportRequest},'*');},[product,ready,orderSupportRequest]);
  useEffect(()=>{if(product&&ready)frame.current?.contentWindow?.postMessage({type:'commerce:workspace-research-context',nonce:nonce.current,case_id:caseId,research_task_id:researchTaskId},'*');},[product,ready,caseId,researchTaskId]);
  useEffect(()=>{if(product&&ready&&assistantToggle!==lastAssistantToggle.current){lastAssistantToggle.current=assistantToggle;frame.current?.contentWindow?.postMessage({type:'commerce:workspace-assistant-toggle',nonce:nonce.current},'*');}},[product,ready,assistantToggle]);
  useEffect(()=>{if(product&&ready&&typeof chatWidth==='number'&&Number.isFinite(chatWidth)&&chatWidth>=320&&chatWidth<=960)frame.current?.contentWindow?.postMessage({type:'commerce:workspace-layout',nonce:nonce.current,chat_width:chatWidth},'*');},[ready,product,chatWidth]);
  useEffect(() => { if (ready) frame.current?.contentWindow?.postMessage(product ? { type: 'commerce:theme', nonce: nonce.current, theme } : { type: 'commerce:legacy-navigate', nonce: nonce.current, tab: legacyTab, mode, theme }, '*'); }, [ready, legacyTab, mode, theme, product]);
  useEffect(()=>{if(!product&&active&&ready&&legacyTab==='creative')frame.current?.contentWindow?.postMessage(creativeIntent?{type:'commerce:legacy-creative-open',nonce:nonce.current,request:creativeIntent}:{type:'commerce:legacy-creative-clear-origin',nonce:nonce.current},'*');},[product,active,ready,legacyTab,creativeIntent?.id]);
  useEffect(() => { if (!product && active && ready && legacyTab === 'creative' && /^pluginexec_[a-f0-9]{20}$/.test(caseId)) frame.current?.contentWindow?.postMessage({ type: 'commerce:legacy-plugin-execution', nonce: nonce.current, execution_id: caseId }, '*'); }, [product, active, ready, legacyTab, caseId]);
  useEffect(()=>{if(!product&&ready&&legacyTab==='organization'&&/^[a-zA-Z0-9_-]{1,160}$/.test(caseId))frame.current?.contentWindow?.postMessage({type:'commerce:legacy-case-open',nonce:nonce.current,case_id:caseId},'*');},[product,ready,legacyTab,caseId]);
  useEffect(()=>{if(!product&&ready&&legacyTab==='skills'&&/^[a-zA-Z0-9_-]{1,160}$/.test(caseId))frame.current?.contentWindow?.postMessage({type:'commerce:legacy-extension-open',nonce:nonce.current,run_id:caseId},'*');},[product,ready,legacyTab,caseId]);
  useEffect(() => { if (!product && ready && legacyTab === 'agent' && /^[a-f0-9]{32}$/.test(caseId)) frame.current?.contentWindow?.postMessage({ type: 'commerce:legacy-agent-open', nonce: nonce.current, run_id: caseId }, '*'); }, [product, ready, legacyTab, caseId]);
  useEffect(() => {
    if (!product || !ready) return;
    if (active && previousActive.current === false) { awaitingRefresh.current = true; frame.current?.contentWindow?.postMessage({ type: 'commerce:workspace-refresh', nonce: nonce.current }, '*'); }
    previousActive.current = active;
  }, [active, product, ready]);
  useEffect(() => { if (product && active && ready && requestedTab && !awaitingRefresh.current) frame.current?.contentWindow?.postMessage({ type: 'commerce:workspace-tab', nonce: nonce.current, tab: requestedTab }, '*'); }, [product, active, ready, requestedTab, requestedTabEpoch,refreshEpoch]);
  return <div className="r-legacy-shell">{product && ['deferred','failed','superseded'].includes(refreshStatus) && <div className="r-refresh-notice" role="status"><span>{refreshStatus === 'deferred' ? '原商品有未保存编辑或正在处理，已延后刷新。请先处理当前输入。' : '原商品尚未刷新，请核对当前版本后继续。'}</span><Button onClick={() => frame.current?.contentWindow?.postMessage({ type: 'commerce:workspace-tab', nonce: nonce.current, tab: editSection.current }, '*')}>返回当前编辑</Button></div>}{documentError?<div className="r-empty" role="alert"><p>{documentError}</p><Button onClick={()=>setDocumentRetry(value=>value+1)}>重新载入模块</Button></div>:source?<iframe ref={frame} title={product ? '完整商品内容编辑' : '专业业务模块'} srcDoc={source} sandbox="allow-scripts allow-forms allow-downloads" className="r-legacy" referrerPolicy="no-referrer" />:<div className="r-empty" role="status">正在载入业务模块…</div>}</div>;
}
