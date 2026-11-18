import {readCreativeIntent,writeCreativeIntent,type CreativeIntent} from './creative-intent';
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { createRoot } from 'react-dom/client';
import { api, errorText } from './api';
import { Overview } from './overview';
import { CostPage } from './cost-page';
import { Tasks } from './tasks';
import { ListingPage } from './listing-page';
import type {ListingTarget} from './listing-observation';
import { StoreWorkbench } from './store-workbench';
import { Candidates } from './candidates';
import { Models } from './models';
import { Assistant } from './assistant';
import { useAssistantPage } from './assistant-page';
import { readAssistantPinned, useModuleAssistant, writeAssistantPinned } from './module-assistant';
import { Legacy } from './legacy';
import { PhoneFleetPage, PhoneFleetPanel } from './phone-fleet';
import { OrderImports } from './order-imports';
import type {OrderSupportRequest,PreparedOrderSupport} from './order-support';
import { WorkflowCanvas } from './workflow-canvas';
import { LayeredMemory } from './layered-memory';
import { AssistantToolDiscovery } from './assistant-tool-discovery';
import { AssistantTeam } from './assistant-team';
import { OperatingControl } from './operating-control';
import { PipelineBoard } from './pipeline-board';
import { DecisionChecks } from './decision-checks';
import { SurfaceProvider } from './surface-provider';
import { Button, Dialog, Empty, ErrorNotice, Icon } from './ui';
import type { BusinessContext, PageContext, Theme, Thread } from './types';
import { navigation, labels, destinationFor, businessModule, initialDestination, conversationDestination } from './navigation';
import {WorkspaceNavigation,CompactPageNavigation} from './workspace-navigation';
import { initialDataMode, ThemeControl, WorkspaceSettings } from './workspace-controls';
import '../../web/research-context.js';
import './style.css';
import '../../ui/workspace.css';
import './workspace-shell.css';

const migrated = ['pipeline','decisions','listing','store-ops','overview', 'workspace', 'operations', 'tasks', 'pilots', 'models', 'order-imports', 'workflow', 'memory', 'phones', 'assistant-team','operating-control','tools'];
const params = new URL(location.href).searchParams;
const initial = initialDestination(params, location.hash);
function readListingTarget(p:URLSearchParams):ListingTarget|null {return p.get('tab')==='listing'&&p.get('case_id')&&p.has('listing_platform')?{case_id:p.get('case_id')!,platform:p.get('listing_platform')!,store_ref:p.get('listing_store')||'',market:p.get('listing_market')||''}:null;}
function readListingAction(p:URLSearchParams):{target:ListingTarget;id:string}|null {const target=readListingTarget(p),id=p.get('image_action_id')||'';return target&&p.has('image_action_id')?{target,id:id||'invalid'}:null;}
function Workspace() {
  const hosted = window.parent !== window || ['dsh','harness','hermes','codex'].includes(params.get('host') || '');
  const [visited,setVisited] = useState(() => new Set([initial]));
  const [compact,setCompact] = useState(() => innerWidth < 1024);
  const [mobileView,setMobileView] = useState<'chat'|'page'>('page'), [keyboardOpen,setKeyboardOpen] = useState(false);
  const [chatWidth,setChatWidth] = useState(360), [chatMax,setChatMax] = useState(640);
  const workArea = useRef<HTMLDivElement>(null), navRef = useRef<HTMLElement>(null), drag = useRef({x:0,width:360});
  const [assistantContext,setAssistantContext]=useState<BusinessContext|null>(null);
  const [framePage,setFramePage]=useState<PageContext|null>(null);
  const [frameScope,setFrameScope]=useState<BusinessContext|null>(null);
  const [productTab,setProductTab] = useState<{tab:string;epoch:number}|undefined>();
  const productTabEpoch=useRef(0);
  function requestProductTab(tab:string){setProductTab({tab,epoch:++productTabEpoch.current});}
  const [tab, setTab] = useState(labels[initial.replace('old:', '')] ? initial : 'overview');
  const [caseId, setCaseId] = useState(params.get('case_id') || ''), [demo, setDemo] = useState(() => initialDataMode(params));
  const [costCaseId,setCostCaseId] = useState(params.get('tab')==='operations' ? params.get('case_id')||'' : '');
  const [costSurfaceId,setCostSurfaceId] = useState(params.get('surface') || '');
  const [storeScope,setStoreScope]=useState(params.get('store_scope')||'all');
  const [orderRequest,setOrderRequest]=useState<OrderSupportRequest|null>(null);
  const pendingOrder=useRef<{id:string;resolve:()=>void;reject:(error:Error)=>void;timer:ReturnType<typeof setTimeout>}|null>(null);
  const [listingTarget,setListingTarget]=useState<ListingTarget|null>(()=>readListingTarget(params));
  const listingTargets=useRef(new Map<string,ListingTarget>(listingTarget?[[listingTarget.case_id,listingTarget]]:[]));
  const [listingAction,setListingAction]=useState(()=>readListingAction(params));
  const [listingCaseId,setListingCaseId] = useState(initial === 'listing' ? params.get('case_id') || '' : '');
  const [productCaseId,setProductCaseId] = useState(params.get('case_id') || '');
  const [productResearchTask, setProductResearchTask] = useState(initial === 'workspace' ? params.get('research_task_id') || '' : '');
  const productEdits=useRef<{caseId:string;dirty:boolean;section:string;pending?:boolean}|null>(null);
  const [pendingProductTransition,setPendingProductTransition]=useState<{run:()=>void;section:string;editor?:'product'|'cost';blocked?:boolean}|null>(null);
  const [creativeIntent,setCreativeIntent]=useState<CreativeIntent|null>(()=>initial==='creative'?readCreativeIntent(params):null);
  const creativeSelection=useRef(creativeIntent);creativeSelection.current=creativeIntent;
  useLayoutEffect(()=>{if(window.parent===window&&tab==='creative'&&creativeIntent){const url=new URL(location.href);writeCreativeIntent(url,creativeIntent);history.replaceState({},'',url);acceptedURL.current=location.href;}},[tab,creativeIntent?.id]);
  const costEdits=useRef<{caseId:string;dirty:boolean}|null>(null);
  const costReturn=useRef<{caseId:string;delivery:boolean}|null>(params.get('cost_return')==='delivery'&&params.get('case_id')?{caseId:params.get('case_id')!,delivery:true}:null);
  const acceptedURL=useRef(location.href);
  const productSelection = useRef(productCaseId); productSelection.current=productCaseId;
  const [theme, setTheme] = useState<Theme>('system'), [themeBusy, setThemeBusy] = useState(false), [error, setError] = useState('');
  const [settings, setSettings] = useState(false);
  const [researchTaskId, setResearchTaskId] = useState(params.get('research_task_id') || ''), [requestedThreadId, setRequestedThreadId] = useState('');
  const threadRequest = useRef(0);
  const [pinned, setPinned] = useState(() => readAssistantPinned());
  const [assistant, setAssistant, setOrdinaryAssistant] = useModuleAssistant(tab.replace('old:', ''), pinned);
  function changePinned(value: boolean) { writeAssistantPinned(value); setPinned(value); setOrdinaryAssistant(value); }
  const [finder, setFinder] = useState(false), [query, setQuery] = useState('');
  const [workflowCase, setWorkflowCase] = useState(params.get('case_id') || '');
  const [legacyTab, setLegacyTab] = useState(!migrated.includes(tab) ? tab.replace('old:', '') : 'platforms');
  const [legacyStarted, setLegacyStarted] = useState(!migrated.includes(tab));
  const headingRef = useRef<HTMLDivElement>(null), themeRevision = useRef(0);
  const activeTab = tab.replace('old:', ''), legacy = !migrated.includes(tab);
  useEffect(()=>{document.title=`${labels[activeTab]||'工作台'} · Phone-Lab`;},[activeTab]);
  const currentRoute=useRef({tab,caseId,demo});currentRoute.current={tab,caseId,demo};
  function holdProductTransition(nextCase:string,run:()=>void,modeChange=false){const edits=productEdits.current;if(edits?.dirty&&edits.caseId===productSelection.current&&(modeChange||nextCase!==productSelection.current)){setPendingProductTransition({run,section:edits.section,blocked:edits.pending===true});return false;}return true;}
  function receiveProductEditState(id:string,dirty:boolean,section:string,pending=false){
    if(id!==productSelection.current)return;
    productEdits.current={caseId:id,dirty,section,pending};
    if(pending)setPendingProductTransition(current=>current&&current.editor!=='cost'?{...current,blocked:true}:current);
  }
  function discardProductTransition(){
    const transition=pendingProductTransition;if(!transition)return;
    // The dialog may have opened during validation, before the write began.
    if(transition.editor!=='cost'&&productEdits.current?.pending){setPendingProductTransition({...transition,blocked:true});return;}
    setPendingProductTransition(null);
    if(transition.editor==='cost')costEdits.current=null;else productEdits.current=null;
    transition.run();
  }
  function holdCostTransition(next:string,id:string|undefined,run:()=>void){const edits=costEdits.current;if(next==='operations'&&edits?.dirty&&edits.caseId!==(id||'')){setPendingProductTransition({run,section:'cost',editor:'cost'});return false;}return true;}
  function openProduct(id:string|undefined,section?:string,taskId?:string){const selected=id===undefined?productSelection.current:id;if(!holdProductTransition(selected,()=>openProduct(id,section,taskId)))return;if(activeTab!=='workspace'||selected!==productSelection.current||taskId!==undefined&&taskId!==productResearchTask)navigate('workspace',selected,taskId);if(section)requestProductTab(section);setMobileView('page');}
  function openProductCost(id:string,delivery=false){if(!holdCostTransition('operations',id,()=>openProductCost(id,delivery)))return;navigate('operations',id);costReturn.current={caseId:id,delivery};if(window.parent===window){const url=new URL(location.href);if(delivery)url.searchParams.set('cost_return','delivery');else url.searchParams.delete('cost_return');history.replaceState({},'',url);acceptedURL.current=location.href;}}
  function openCreative(value:Omit<CreativeIntent,'id'>){navigate('creative');const intent={...value,id:crypto.randomUUID()};setCreativeIntent(intent);if(window.parent===window){const url=new URL(location.href);writeCreativeIntent(url,intent);history.replaceState({},'',url);acceptedURL.current=location.href;}}
  function creativeOpened(id:string,projectId:string){const prior=creativeSelection.current;if(!prior||prior.id!==id)return;const value={...prior,project_id:projectId};setCreativeIntent(value);if(window.parent===window&&currentRoute.current.tab==='creative'){const url=new URL(location.href);writeCreativeIntent(url,value);history.replaceState({},'',url);acceptedURL.current=location.href;}}
  function navigate(next: string, id?: string, taskId?: string) {
    if (!labels[next.replace('old:', '')]) return;
    const nextProduct=next==='workspace'?(id===undefined?productSelection.current:id):productSelection.current;
    if(!holdCostTransition(next,id,()=>navigate(next,id,taskId)))return;
    if(!holdProductTransition(nextProduct,()=>navigate(next,id,taskId)))return;
    const preserveFrame=next===tab&&(next==='workspace'?(id===undefined||id===productSelection.current):legacy&&!id);
    cancelOrderSupport();setError('');setCreativeIntent(null);
    const selectedResearch=next==='workspace'?(taskId===undefined&&id===undefined?productResearchTask:taskId||''):'';
    setAssistantContext(null);if(!preserveFrame){setFramePage(null);setFrameScope(null);}setListingAction(null);
    threadRequest.current++; setRequestedThreadId(''); setResearchTaskId('');
    if (next === 'workspace') {setProductTab(undefined);if(id===undefined)id=productSelection.current;}
    if(next==='workspace'){setProductCaseId(id||'');setProductResearchTask(selectedResearch);}
    if (next==='operations') {if(id===undefined)id='';setCostCaseId(id);if(id)setCostSurfaceId('');}
    if(next==='listing'){setListingTarget(null);if(id===undefined)id=productSelection.current;setListingCaseId(id||'');}
    if (next==='workflow') {if(id===undefined)id=productSelection.current||workflowCase;setWorkflowCase(id||'');}
    if(id===undefined)id='';
    setVisited(previous => new Set([...previous,next])); setTab(next); setMobileView('page'); if (id !== undefined) setCaseId(id);
    if (!migrated.includes(next)) { setLegacyTab(next.replace('old:', '')); setLegacyStarted(true); }
    // Opaque iframe documents may not change their URL. The host owns its route.
    if (window.parent === window) { const url = new URL(location.href);writeCreativeIntent(url,null);url.searchParams.delete('cost_return'); url.searchParams.set('tab', next); if(next==='operations'&&!id&&costSurfaceId)url.searchParams.set('surface',costSurfaceId);else url.searchParams.delete('surface'); for(const key of ['listing_platform','listing_store','listing_market','image_action_id'])url.searchParams.delete(key); url.searchParams.delete('research_task_id'); if(next==='workspace'&&selectedResearch)url.searchParams.set('research_task_id',selectedResearch); if (id !== undefined) { if (id) url.searchParams.set('case_id', id); else url.searchParams.delete('case_id'); } history.pushState({}, '', url);acceptedURL.current=location.href; }
    requestAnimationFrame(() => headingRef.current?.focus());
  }
  function chooseStoreScope(value:string){setStoreScope(value);setAssistantContext(null);if(window.parent===window){const url=new URL(location.href);if(value==='all')url.searchParams.delete('store_scope');else url.searchParams.set('store_scope',value);history.replaceState({},'',url);acceptedURL.current=location.href;}}
  function cancelOrderSupport(){const pending=pendingOrder.current;if(!pending)return;pendingOrder.current=null;clearTimeout(pending.timer);setOrderRequest(null);pending.reject(Error('order_support_context_cancelled'));}
  function openOrderSupport(prepared:PreparedOrderSupport):Promise<void>{
    if(prepared?.context?.schema!=='commerce-order-support-context-v1'||prepared.context.scope.demo!==demo||prepared.external_execution_allowed!==false)return Promise.reject(Error('order_support_scope_mismatch'));
    cancelOrderSupport();setError('');const id=crypto.randomUUID();setLegacyStarted(true);
    return new Promise((resolve,reject)=>{const timer=setTimeout(()=>finishOrderSupport(id,'order_support_context_timeout'),20000);pendingOrder.current={id,resolve,reject,timer};setOrderRequest({id,prepared});});
  }
  function finishOrderSupport(id:string,code?:string){const pending=pendingOrder.current;if(!pending||pending.id!==id)return;pendingOrder.current=null;clearTimeout(pending.timer);setOrderRequest(null);if(code){const reason=['order_support_editor_open','order_support_context_timeout','order_support_scope_mismatch'].includes(code)?code:'order_support_context_failed';if(tab!=='order-imports')setError(errorText(Error(reason)));pending.reject(Error(reason));return;}setError('');navigate('support');pending.resolve();}
  function rememberListingRoute(target:ListingTarget,actionId?:string){listingTargets.current.set(target.case_id,target);if(window.parent===window){const url=new URL(location.href);if(url.searchParams.get('tab')!=='listing')return;const previous=readListingTarget(url.searchParams);if(actionId!==undefined){if(actionId)url.searchParams.set('image_action_id',actionId);else url.searchParams.delete('image_action_id');}else if(!previous||Object.keys(target).some(key=>target[key as keyof ListingTarget]!==previous[key as keyof ListingTarget]))url.searchParams.delete('image_action_id');url.searchParams.set('case_id',target.case_id);url.searchParams.set('listing_platform',target.platform);url.searchParams.set('listing_store',target.store_ref);url.searchParams.set('listing_market',target.market);history.replaceState({},'',url);acceptedURL.current=location.href;}}
  function selectListingAction(target:ListingTarget,id:string){setListingAction({target,id});rememberListingRoute(target,id);}
  function openListing(target:ListingTarget,actionId=''){navigate('listing',target.case_id);setListingTarget(target);setListingAction(actionId?{target,id:actionId}:null);rememberListingRoute(target,actionId);}
  function openResearch(id: string) {
    navigate('pilots'); setResearchTaskId(id);
    if (window.parent === window) { const url = new URL(location.href); url.searchParams.set('research_task_id', id); history.replaceState({}, '', url);acceptedURL.current=location.href; }
  }
  function openCostSurface(surfaceId: string, boundCase?: string) {
    if(!holdCostTransition('operations',boundCase,()=>openCostSurface(surfaceId,boundCase)))return;
    costReturn.current=null;
    if (boundCase) { navigate('operations',boundCase); return; }
    navigate('operations'); setCostSurfaceId(surfaceId);
    if(window.parent===window){const url=new URL(location.href);url.searchParams.set('surface',surfaceId);history.replaceState({},'',url);acceptedURL.current=location.href;}
  }
  function closeResearch() {
    setResearchTaskId('');
    if (window.parent === window) { const url = new URL(location.href); url.searchParams.delete('research_task_id'); history.replaceState({}, '', url);acceptedURL.current=location.href; }
  }
  async function openResearchThread(id: string, returnToModule = false, keepOriginalScope = false) {
    const version = ++threadRequest.current;
    try {
      const thread = await api<Thread>('commerce_copilot_get', { thread_id: id });
      if (version !== threadRequest.current) return;
      const apply=()=>{if(returnToModule && labels[thread.context.module]){navigate(conversationDestination(thread.context,thread.latest_run?.parameters?.page_context),thread.context.entity?.kind==='case'?thread.context.entity.id:undefined);if(thread.latest_run?.parameters?.page_context?.page==='store-ops')chooseStoreScope(thread.context.store_scope||'all');}setAssistantContext(keepOriginalScope ? thread.context : null);setRequestedThreadId(thread.id);setAssistant(true);setMobileView('chat');};
      const destination=returnToModule?conversationDestination(thread.context,thread.latest_run?.parameters?.page_context):activeTab;const entity=thread.context.entity?.kind==='case'?thread.context.entity.id:undefined;if(returnToModule&&!holdCostTransition(destination,entity,apply))return;const nextCase=destination==='workspace'&&entity?entity:productSelection.current;if(!holdProductTransition(nextCase,apply))return;apply();
    } catch (failure) { if (version === threadRequest.current) setError(errorText(failure)); }
  }
  useEffect(() => {
    const hostNavigate = (event: MessageEvent) => { if (event.source === parent && event.data?.nonce === '__COMMERCE_BRIDGE_NONCE__' && event.data?.type === 'commerce:host-navigate' && labels[event.data.tab]) {if(event.data.tab==='pilots'&&typeof event.data.research_task_id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(event.data.research_task_id))openResearch(event.data.research_task_id);else navigate(event.data.tab);} };
    const back = () => {const requestedURL=location.href,p=new URL(requestedURL).searchParams,next=initialDestination(p,location.hash);const sameFrame=next===currentRoute.current.tab&&(next==='workspace'?(p.get('case_id')||'')===productSelection.current:!migrated.includes(next)&&(p.get('case_id')||'')===currentRoute.current.caseId);const apply=()=>{cancelOrderSupport();setCreativeIntent(next==='creative'?readCreativeIntent(p):null);costReturn.current=next==='operations'&&p.get('cost_return')==='delivery'?{caseId:p.get('case_id')||'',delivery:true}:null;if(window.parent===window){const normalized=new URL(location.href);if(currentRoute.current.demo)normalized.searchParams.set('demo','true');else normalized.searchParams.delete('demo');history.replaceState({},'',normalized);}setStoreScope(p.get('store_scope')||'all');setAssistantContext(null); if(!sameFrame){setFramePage(null);setFrameScope(null);} setRequestedThreadId(''); threadRequest.current++; setResearchTaskId(p.get('research_task_id')||''); setProductResearchTask(next==='workspace'?p.get('research_task_id')||'':''); setListingTarget(readListingTarget(p));setListingAction(readListingAction(p));if(next==='listing')setListingCaseId(p.get('case_id')||''); if(next==='workflow')setWorkflowCase(p.get('case_id')||''); if (labels[next.replace('old:', '')]) { setTab(next); setVisited(previous => new Set([...previous,next])); setCaseId(p.get('case_id') || ''); if(next==='operations'){setCostCaseId(p.get('case_id')||'');setCostSurfaceId(p.get('surface')||'');} if(next==='workspace')setProductCaseId(p.get('case_id')||''); if (!migrated.includes(next)) { setLegacyTab(next.replace('old:', '')); setLegacyStarted(true); } }acceptedURL.current=location.href;};const nextCase=next==='workspace'?p.get('case_id')||'':productSelection.current;if(!holdCostTransition(next,p.get('case_id')||'',()=>{history.pushState({},'',requestedURL);apply();})){history.pushState({},'',acceptedURL.current);return;}if(!holdProductTransition(nextCase,()=>{history.pushState({},'',requestedURL);apply();})){history.pushState({},'',acceptedURL.current);return;}apply();};
    const keyboard = (event: KeyboardEvent) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setFinder(true); } };
    window.addEventListener('popstate', back); window.addEventListener('keydown', keyboard); window.addEventListener('message', hostNavigate);
    const revision = themeRevision.current;
    void api<{ theme: Theme }>('commerce_ui_get_preferences').then(result => { if (revision === themeRevision.current) { setTheme(result.theme); window.CommerceUI.applyTheme(result.theme); } }).catch(() => {});
    return () => { window.removeEventListener('popstate', back); window.removeEventListener('keydown', keyboard); window.removeEventListener('message', hostNavigate); };
  }, []);
  function resizeChat(value: number, save = true) {
    const width = workArea.current?.clientWidth || innerWidth;
    const {max,width:next} = window.CommerceUI.chatLayout(width,value);
    setChatMax(max); setChatWidth(next);
    if (save) try { localStorage.setItem('commerce-product-chat-width-v2',String(next)); } catch {}
  }
  useEffect(() => {
    const element=workArea.current; if(!element)return;
    const update=()=>{setCompact(element.clientWidth<1024);let saved:string|null=null;try{saved=localStorage.getItem('commerce-product-chat-width-v2');}catch{} resizeChat(window.CommerceUI.chatLayout(element.clientWidth,saved).width,false);};
    const observer=new ResizeObserver(update);observer.observe(element);update();
    window.addEventListener('storage',update);
    return ()=>{observer.disconnect();window.removeEventListener('storage',update);};
  },[]);
  useEffect(() => {
    const viewport=window.visualViewport;if(!viewport)return;
    const update=()=>setKeyboardOpen(innerWidth<=767 && viewport.scale===1 && document.documentElement.clientHeight-viewport.height>150);
    viewport.addEventListener('resize',update);update();
    return ()=>viewport.removeEventListener('resize',update);
  },[]);
  useEffect(() => {
    const nav=navRef.current, selected=nav?.querySelector<HTMLElement>('[aria-current="page"]');
    if(nav&&selected){const left=selected.offsetLeft-nav.offsetLeft;if(left<nav.scrollLeft)nav.scrollLeft=left;else if(left+selected.offsetWidth>nav.scrollLeft+nav.clientWidth)nav.scrollLeft=left+selected.offsetWidth-nav.clientWidth;}
  },[tab,compact,keyboardOpen,chatWidth]);
  useEffect(()=>{
    const nav=headingRef.current?.querySelector<HTMLElement>('.r-section-tabs'),selected=nav?.querySelector<HTMLElement>('[aria-current="page"]');
    if(!nav||!selected)return;const a=nav.getBoundingClientRect(),b=selected.getBoundingClientRect();
    if(b.left<a.left)nav.scrollLeft+=b.left-a.left;else if(b.right>a.right)nav.scrollLeft+=b.right-a.right;
  },[activeTab]);
  async function changeTheme(value: Theme) {
    if (themeBusy) return; const previous = theme; themeRevision.current++; setThemeBusy(true); setTheme(value); window.CommerceUI.applyTheme(value);
    try { await api('commerce_ui_set_preferences', { theme: value }); setError(''); } catch (e) { setTheme(previous); window.CommerceUI.applyTheme(previous); setError(errorText(e)); } finally { setThemeBusy(false); }
  }
  function changeMode(next: boolean) {if(next===demo)return;if(!holdProductTransition(productSelection.current,()=>changeMode(next),true))return;cancelOrderSupport();setStoreScope('all');threadRequest.current++; setAssistantContext(null); setFramePage(null); setFrameScope(null); setRequestedThreadId(''); setResearchTaskId(''); if (activeTab === 'agent') setCaseId(''); try { localStorage.setItem('commerce-workspace-example-data', String(next)); } catch {} setDemo(next); if (window.parent === window) { const url = new URL(location.href); url.searchParams.delete('store_scope');if (next) url.searchParams.set('demo', 'true'); else url.searchParams.delete('demo'); history.replaceState({}, '', url);acceptedURL.current=location.href; } }
  const pageContext = useMemo<BusinessContext>(() => ({ module: businessModule(activeTab), demo:activeTab==='intelligence'?false:demo,...(activeTab==='store-ops'&&storeScope!=='all'?{store_scope:storeScope}:{}), ...(activeTab==='restock'?{calculator:'restock_plan'}:{}), ...(['workspace', 'operations','listing'].includes(activeTab) && (activeTab==='listing'?listingCaseId:activeTab==='workspace'?productCaseId:costCaseId) ? { entity: { kind: 'case', id: activeTab==='listing'?listingCaseId:activeTab==='workspace'?productCaseId:costCaseId } } : {}) }), [activeTab, demo, costCaseId, productCaseId, listingCaseId,storeScope]);
  const assistantPage=useAssistantPage(activeTab,pageContext,headingRef,framePage);
  const currentPage=(legacy||activeTab==='workspace')&&framePage?.page===activeTab?framePage:assistantPage.page===activeTab?assistantPage:{page:activeTab,demo:!!pageContext.demo};
  const context:BusinessContext=assistantContext||{...(frameScope||pageContext),demo:!!currentPage.demo,...Object.fromEntries(Object.entries(currentPage.filters||{}).filter(([key])=>['platform','market','store_id'].includes(key)&&currentPage.filters?.[key])),...(currentPage.entity&&currentPage.entity.kind!=='chart'?{entity:{kind:currentPage.entity.kind,id:currentPage.entity.id}}:{})};
  function receiveFrameContext(page:PageContext,scope:BusinessContext){if(scope.module!==businessModule(activeTab)||(page.page!==activeTab&&!(activeTab==='restock'&&page.page==='operations')))return;if(activeTab==='workspace'&&(scope.entity?.kind==='case'?scope.entity.id!==productSelection.current:!!productSelection.current))return;setFramePage({...page,page:activeTab});setFrameScope(scope);}
  function openBusinessCopilot(next:BusinessContext){if(next.module!==businessModule(activeTab)||!!next.demo!==!!currentPage.demo||((legacy||activeTab==='workspace')&&framePage?.page!==activeTab))return;setAssistantContext(null);setFrameScope(next);setAssistant(true);setMobileView('chat');}
  const destination=destinationFor(activeTab) || navigation[0];
  const navLink = (id: string,label: string,icon: string) => <button key={id} aria-label={label} className={`r-nav-link ${destination.id===id?'selected':''}`} aria-current={destination.id===id?'page':undefined} onClick={()=>navigate(id)}><Icon name={icon}/><span className="r-nav-label">{label}</span></button>;
  function closeAssistant(){setAssistant(false);setMobileView('page');requestAnimationFrame(()=>document.getElementById('workspace-assistant-toggle')?.focus({preventScroll:true}));}
  function toggleAssistant(){if(compact){if(assistant&&mobileView==='chat')closeAssistant();else{setAssistant(true);setMobileView('chat');}}else setAssistant(value=>!value);}
  function selectWorkPage(next:string){
    // Returning through navigation resumes an unsaved calculator. An explicit
    // product action can still request another binding through the dirty guard.
    if(next==='operations'&&costEdits.current?.dirty){navigate(next,costEdits.current.caseId);return;}
    const selected=activeTab==='workspace'?productCaseId:activeTab==='operations'?costCaseId:activeTab==='listing'?listingCaseId:activeTab==='workflow'?workflowCase:'';
    if(next==='operations'&&selected){openProductCost(selected);return;}
    if(next==='workspace'&&selected){openProduct(selected,undefined,selected===productCaseId?productResearchTask:'');return;}
    if(next==='listing'&&selected){const target=listingTargets.current.get(selected);if(target)openListing(target);else navigate(next,selected);return;}
    if(next==='workflow'&&selected){navigate(next,selected);return;}
    navigate(next,next==='operations'?'':undefined);
  }
  const found = Object.entries(labels).filter(([id, label]) => (id + label).toLowerCase().includes(query.trim().toLowerCase()));
  return <div className={`app r-app ${hosted?'r-hosted':''}`} data-module={activeTab} data-keyboard-open={keyboardOpen}>
    <a href={compact&&mobileView==='chat'?'#copilot-log':'#main-workspace'} className="r-skip">跳至工作区</a>
    <aside className="r-sidebar" aria-label="平台导航"><button className="r-brand" title="返回运营台" onClick={()=>navigate('overview')}><span><Icon name="store"/></span><div><strong>Phone-Lab</strong><small>AI 跨境运营平台</small></div></button><nav aria-label="业务模块">{navigation.map(item=>navLink(item.id,item.label,item.icon))}</nav><WorkspaceNavigation route={activeTab} select={selectWorkPage}/></aside>
    <header className="r-topbar">
      <div className="r-topbar-location" aria-label="当前位置">{destination.label!==labels[activeTab]&&<><span>{destination.label}</span><i aria-hidden="true">/</i></>}<strong>{labels[activeTab]}</strong></div>
      <nav ref={navRef} className="r-business-nav" aria-label="工作台业务导航" onKeyDown={event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const buttons=[...event.currentTarget.querySelectorAll<HTMLButtonElement>('button')],index=buttons.indexOf(event.target as HTMLButtonElement);if(index<0)return;event.preventDefault();buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length]?.focus();}}>{navigation.map(item=><button key={item.id} aria-label={item.label} title={item.label} aria-current={destination.id===item.id?'page':undefined} onClick={()=>navigate(item.id)}><Icon name={item.icon}/><span>{item.label}</span></button>)}</nav>
      <div className="r-top-controls"><Button className="r-search" icon="search" aria-label={compact?'查找模块':undefined} aria-keyshortcuts="Meta+K Control+K" title="查找工作与模块（⌘ K）" onClick={()=>{setQuery('');setFinder(true);}}><span>查找模块</span><kbd aria-hidden="true">⌘ K</kbd></Button><Button className="r-data-scope" onClick={()=>setSettings(true)}>{demo?'示例数据':'当前资料'}</Button><Button className="r-top-icon r-phone-toggle" icon="phone" aria-label="多手机画面与控制" title="多手机画面与控制" aria-pressed={activeTab==='phones'} onClick={()=>navigate('phones')}/><ThemeControl id="react-theme" theme={theme} busy={themeBusy} change={value=>void changeTheme(value)}/><Button className="r-top-icon" icon="gear" aria-label="设置" title="设置" onClick={()=>setSettings(true)}/><Button id="workspace-assistant-toggle" className="r-assistant-toggle" icon="chat" aria-label="切换智能助手" title="展开或收起智能助手" aria-controls="commerce-copilot" aria-expanded={assistant&&(!compact||mobileView==='chat')} aria-pressed={assistant&&(!compact||mobileView==='chat')} onClick={toggleAssistant}><span className="r-assistant-label">智能助手</span></Button></div>
    </header>
    <div ref={workArea} className={`r-work-area ${assistant?'with-assistant':''} ${compact?'is-compact':''}`} data-mobile-view={mobileView} style={{'--r-chat-width':`${chatWidth}px`} as CSSProperties}>
      <Assistant pageReady={(legacy||activeTab==='workspace')?framePage?.page===activeTab:activeTab==='store-ops'&&storeScope!=='all'?currentPage.filters?.scope===storeScope&&!!currentPage.source_refs?.store_scope:true} context={context} pageContext={currentPage} visible={assistant&&(!compact||mobileView==='chat')} close={closeAssistant} onWorkspace={()=>openProduct(productCaseId||undefined,activeTab==='workspace'?'cost':undefined)} requestedThreadId={requestedThreadId} onResearch={openResearch} onModels={()=>navigate('models')} onOpenCandidate={(id,taskId)=>navigate('workspace',id,taskId)}/>
      {assistant&&<div className="r-chat-splitter" role="separator" tabIndex={compact?-1:0} aria-label="调整对话区宽度" aria-orientation="vertical" aria-valuemin={320} aria-valuemax={chatMax} aria-valuenow={chatWidth} aria-controls="commerce-copilot main-workspace" onPointerDown={event=>{if(event.button!==0)return;event.preventDefault();drag.current={x:event.clientX,width:chatWidth};event.currentTarget.setPointerCapture(event.pointerId);}} onPointerMove={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId))resizeChat(drag.current.width+drag.current.x-event.clientX);}} onPointerUp={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);}} onKeyDown={event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();resizeChat(event.key==='Home'?320:event.key==='End'?chatMax:chatWidth+(event.key==='ArrowLeft'?16:-16));}}/>}
      <main className="r-main" id="main-workspace" tabIndex={-1} ref={headingRef}>
        <CompactPageNavigation route={activeTab} select={selectWorkPage}/>
        <ErrorNotice>{error}</ErrorNotice>
        <div hidden={tab!=='overview'}><Overview demo={demo} active={tab==='overview'} navigate={navigate} onThread={id=>void openResearchThread(id)} onResearch={openResearch} onListing={target=>openListing(target)} onProduct={(id,section)=>openProduct(id,section)}/></div>
        {visited.has('operations')&&<div hidden={tab!=='operations'}>{costCaseId&&<div className="r-bound-workbar"><span>当前商品 · 成本与定价</span><Button onClick={()=>navigate('operations','')}>通用测算</Button></div>}<CostPage onEditState={(id,dirty)=>{costEdits.current={caseId:id,dirty};}} key={costCaseId||'general'} caseId={costCaseId} requestedSurface={costCaseId?'':costSurfaceId} onReturn={()=>openProduct(costCaseId||undefined,costReturn.current?.caseId===costCaseId&&costReturn.current.delivery?'delivery':'cost')}/>{!costCaseId&&<div className="r-page r-secondary-entry"><Button onClick={()=>navigate('restock')}>补货计划</Button></div>}</div>}
        <div hidden={tab!=='workspace'} className="r-approved-product">{visited.has('workspace')&&<Legacy tab="workspace" onCost={openProductCost} onCreative={openCreative} onSelectedProduct={(id,task)=>{productEdits.current=null;setPendingProductTransition(null);navigate('workspace',id,task);}} onEditState={receiveProductEditState} onPageContext={receiveFrameContext} onCopilot={openBusinessCopilot} onResearch={openResearch} requestedTab={productTab?.tab} requestedTabEpoch={productTab?.epoch||0} active={tab==='workspace'} demo={demo} theme={theme} caseId={productCaseId} researchTaskId={productResearchTask} onResearchContext={(id,taskId)=>{if(id!==productSelection.current)return;setProductResearchTask(taskId);if(window.parent===window&&activeTab==='workspace'){const url=new URL(location.href);if(taskId)url.searchParams.set('research_task_id',taskId);else url.searchParams.delete('research_task_id');history.replaceState({},'',url);acceptedURL.current=location.href;}}} navigate={navigate}/>}</div>
        {visited.has('listing')&&<div hidden={tab!=='listing'}><ListingPage demo={demo} active={tab==='listing'} caseId={listingCaseId} onCase={setListingCaseId} onTargetLoaded={rememberListingRoute} requestedTarget={listingTarget} requestedAction={listingAction} onSelectAction={selectListingAction} onPlatform={()=>navigate('platforms')} onProduct={(id,tab)=>openProduct(id,tab)}/></div>}
        {visited.has('store-ops')&&<div hidden={tab!=='store-ops'}><StoreWorkbench key={String(demo)} storeScope={storeScope} onStoreScope={chooseStoreScope} demo={demo} active={tab==='store-ops'} navigate={navigate} onListing={openListing} onThread={id=>void openResearchThread(id)} onResearch={openResearch}/></div>}
        {visited.has('tools')&&<div hidden={tab!=='tools'} className="r-page"><div className="r-page-heading"><h1>插件与工具发现</h1><Button onClick={()=>navigate('skills')}>自建插件与能力</Button></div><AssistantToolDiscovery active={tab==='tools'}/></div>}
        <div hidden={tab!=='tasks'}><Tasks active={tab==='tasks'} requestedTask={activeTab==='tasks'?caseId:''} navigate={navigate} onResearch={openResearch} onCost={openCostSurface} onConversation={id=>void openResearchThread(id,true)}/></div>
        {visited.has('pipeline')&&<div hidden={tab!=='pipeline'}><PipelineBoard demo={demo} active={tab==='pipeline'} navigate={navigate} onProduct={(id,section)=>openProduct(id,section)} onListing={target=>openListing(target)}/></div>}
        {visited.has('decisions')&&<div hidden={tab!=='decisions'}><DecisionChecks/></div>}
        {visited.has('pilots')&&<div hidden={tab!=='pilots'}><Candidates active={tab==='pilots'} requestedTask={researchTaskId} closeTask={closeResearch} openTask={openResearch} openThread={id=>void openResearchThread(id)} navigate={navigate}/></div>}
        {visited.has('models')&&<div hidden={tab!=='models'}><Models active={tab==='models'}/></div>}
        {visited.has('order-imports')&&<div hidden={tab!=='order-imports'}><OrderImports demo={demo} navigate={navigate} onSupport={openOrderSupport}/></div>}
        {visited.has('workflow')&&<div hidden={tab!=='workflow'}><WorkflowCanvas caseId={workflowCase} navigate={navigate}/></div>}
        {visited.has('memory')&&<div hidden={tab!=='memory'}><LayeredMemory demo={demo} navigate={navigate}/></div>}
        {visited.has('assistant-team')&&<div hidden={tab!=='assistant-team'}><AssistantTeam requestedDiscussion={activeTab==='assistant-team'?caseId:''} active={tab==='assistant-team'} onConversation={id=>void openResearchThread(id,false,true)}/></div>}
        {visited.has('operating-control')&&<div hidden={tab!=='operating-control'}><OperatingControl synthetic={demo} active={tab==='operating-control'} onNavigate={(route,id)=>navigate(route,id)}/></div>}
        {visited.has('phones')&&<div hidden={tab!=='phones'} className="r-phone-embedding"><PhoneFleetPanel page embedded active={tab==='phones'} close={()=>navigate('skills')}/></div>}
        {legacyStarted&&<div hidden={!legacy} className="r-legacy-container"><Legacy creativeIntent={creativeIntent} onCreativeOpened={creativeOpened} tab={legacyTab} active={legacy} orderSupportRequest={orderRequest} onOrderSupport={openOrderSupport} onOrderSupportResult={finishOrderSupport} onPageContext={receiveFrameContext} onCopilot={openBusinessCopilot} demo={demo} theme={theme} caseId={caseId} navigate={navigate}/></div>}
      </main>
    </div>
    {settings && <WorkspaceSettings pinned={pinned} changePinned={changePinned} theme={theme} themeBusy={themeBusy} changeTheme={value=>void changeTheme(value)} demo={demo} changeDemo={changeMode} close={()=>setSettings(false)} error={error} connections={()=>{setSettings(false);navigate('connections');}}/>}
    {pendingProductTransition&&<Dialog title={pendingProductTransition.blocked?'研究保存尚未确认':pendingProductTransition.editor==='cost'?'保留成本工作台的未保存输入':'保留当前商品的未保存输入'} close={()=>setPendingProductTransition(null)}><p>{pendingProductTransition.blocked?'原研究保存仍在处理或结果尚未确认。请返回原编辑器，核对同一请求后再切换。':pendingProductTransition.editor==='cost'?'成本工作台还有未保存的编辑。先返回保存，或明确放弃后切换。':'当前商品还有未保存的编辑。先返回保存，或明确放弃这些修改后继续。'}</p><div className="r-actions"><Button onClick={()=>{const {section,editor}=pendingProductTransition;setPendingProductTransition(null);setSettings(false);if(editor==='cost')navigate('operations',costEdits.current?.caseId??costCaseId);else openProduct(productSelection.current,section);}}>返回当前编辑</Button>{!pendingProductTransition.blocked&&<Button onClick={discardProductTransition}>放弃修改并继续</Button>}</div></Dialog>}
    {finder && <Dialog title="查找模块" close={() => setFinder(false)}><div className="r-command-search"><div role="search" onKeyDown={event=>{if(event.key!=='Enter')return;event.stopPropagation();if(event.nativeEvent.isComposing||event.nativeEvent.keyCode===229)return;if(found.length===1){event.preventDefault();setFinder(false);selectWorkPage(found[0][0]);}}}><label className="ui-field">模块名称或关键词<input type="search" autoFocus value={query} onChange={event => setQuery(event.target.value)} placeholder="例如：商品、成本、库存、任务" /></label></div><p className="r-footnote" role="status">{found.length} 个匹配入口</p><div className="r-finder-list">{found.length ? found.map(([id, label]) => <Button key={id} data-finder-route={id} onClick={() => { setFinder(false); selectWorkPage(id); }}><span>{label}</span><span>{navigation.find(item=>item.items.includes(id))?.label||'业务页面'}</span></Button>) : <Empty>没有匹配模块。</Empty>}</div></div></Dialog>}</div>;
}
function Root() {
  if (window.location.pathname.replace(/\/+$/, '') === '/phones') return <PhoneFleetPage />;
  return <Workspace />;
}

createRoot(document.getElementById('root')!).render(<SurfaceProvider><Root /></SurfaceProvider>);
