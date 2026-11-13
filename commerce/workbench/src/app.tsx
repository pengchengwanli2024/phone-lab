import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { createRoot } from 'react-dom/client';
import { api, errorText } from './api';
import { Overview } from './overview';
import { CostPage } from './cost-page';
import { Tasks } from './tasks';
import { Candidates } from './candidates';
import { Models } from './models';
import { Assistant } from './assistant';
import { Legacy } from './legacy';
import { SurfaceProvider } from './surface-provider';
import { Button, Dialog, Empty, ErrorNotice, Icon } from './ui';
import type { BusinessContext, Theme, Thread } from './types';
import { navigation, labels, destinationFor, businessModule } from './navigation';
import { initialDataMode, ThemeControl, WorkspaceSettings, UserPanel } from './workspace-controls';
import '../../web/research-context.js';
import './style.css';

const migrated = ['overview', 'workspace', 'operations', 'tasks', 'pilots', 'models'];
const params = new URL(location.href).searchParams;
const initial = params.get('tab') || 'overview';
function Workspace() {
  const hosted = window.parent !== window || ['dsh','harness','hermes','codex'].includes(params.get('host') || '');
  const [visited,setVisited] = useState(() => new Set([initial]));
  const [compact,setCompact] = useState(() => innerWidth < 1024);
  const [mobileView,setMobileView] = useState<'chat'|'page'>('page'), [keyboardOpen,setKeyboardOpen] = useState(false);
  const [chatWidth,setChatWidth] = useState(480), [chatMax,setChatMax] = useState(640);
  const workArea = useRef<HTMLDivElement>(null), navRef = useRef<HTMLElement>(null), drag = useRef({x:0,width:480});
  const [assistantContext,setAssistantContext]=useState<BusinessContext|null>(null);
  const [productTab,setProductTab] = useState<string | undefined>();
  const [tab, setTab] = useState(labels[initial.replace('old:', '')] ? initial : 'overview');
  const [caseId, setCaseId] = useState(params.get('case_id') || ''), [demo, setDemo] = useState(() => initialDataMode(params));
  const [costCaseId,setCostCaseId] = useState(params.get('tab')==='operations' ? params.get('case_id')||'' : '');
  const [productCaseId,setProductCaseId] = useState(params.get('case_id') || '');
  const [productResearchTask, setProductResearchTask] = useState(initial === 'workspace' ? params.get('research_task_id') || '' : '');
  const productSelection = useRef(productCaseId); productSelection.current=productCaseId;
  const [theme, setTheme] = useState<Theme>('system'), [themeBusy, setThemeBusy] = useState(false), [error, setError] = useState('');
  const [settings, setSettings] = useState(false), [user, setUser] = useState(false);
  const [researchTaskId, setResearchTaskId] = useState(params.get('research_task_id') || ''), [requestedThreadId, setRequestedThreadId] = useState('');
  const threadRequest = useRef(0);
  const [productAssistant, setProductAssistant] = useState(innerWidth >= 1024), [assistantToggle, setAssistantToggle] = useState(0);
  const [assistant, setAssistant] = useState(true), [finder, setFinder] = useState(false), [query, setQuery] = useState('');
  const [legacyTab, setLegacyTab] = useState(!migrated.includes(tab) ? tab.replace('old:', '') : 'platforms');
  const [legacyStarted, setLegacyStarted] = useState(!migrated.includes(tab));
  const headingRef = useRef<HTMLDivElement>(null), themeRevision = useRef(0);
  const activeTab = tab.replace('old:', ''), legacy = !migrated.includes(tab);
  function navigate(next: string, id?: string, taskId?: string) {
    if (!labels[next.replace('old:', '')]) return;
    const selectedResearch=next==='workspace'?(taskId===undefined&&id===undefined?productResearchTask:taskId||''):'';
    setAssistantContext(null);
    threadRequest.current++; setRequestedThreadId(''); setResearchTaskId('');
    if (next === 'workspace') {setProductTab(undefined);if(id===undefined)id=productSelection.current;}
    if(next==='workspace'){setProductCaseId(id||'');setProductResearchTask(selectedResearch);}else if(next==='operations'&&id)setProductCaseId(id);
    if (next==='operations') {if(id===undefined)id='';setCostCaseId(id);}
    setVisited(previous => new Set([...previous,next])); setTab(next); setMobileView('page'); if (id !== undefined) setCaseId(id);
    if (!migrated.includes(next)) { setLegacyTab(next.replace('old:', '')); setLegacyStarted(true); }
    // Opaque iframe documents may not change their URL. The host owns its route.
    if (window.parent === window) { const url = new URL(location.href); url.searchParams.set('tab', next); url.searchParams.delete('research_task_id'); if(next==='workspace'&&selectedResearch)url.searchParams.set('research_task_id',selectedResearch); if (id !== undefined) { if (id) url.searchParams.set('case_id', id); else url.searchParams.delete('case_id'); } history.pushState({}, '', url); }
    requestAnimationFrame(() => headingRef.current?.focus());
  }
  function openResearch(id: string) {
    navigate('pilots'); setResearchTaskId(id);
    if (window.parent === window) { const url = new URL(location.href); url.searchParams.set('research_task_id', id); history.replaceState({}, '', url); }
  }
  function closeResearch() {
    setResearchTaskId('');
    if (window.parent === window) { const url = new URL(location.href); url.searchParams.delete('research_task_id'); history.replaceState({}, '', url); }
  }
  async function openResearchThread(id: string) {
    const version = ++threadRequest.current;
    try {
      const thread = await api<Thread>('commerce_copilot_get', { thread_id: id });
      if (version !== threadRequest.current) return;
      setAssistantContext(thread.context); setRequestedThreadId(thread.id); setAssistant(true); setMobileView('chat');
    } catch (failure) { if (version === threadRequest.current) setError(errorText(failure)); }
  }
  useEffect(() => {
    const hostNavigate = (event: MessageEvent) => { if (event.source === parent && event.data?.nonce === '__COMMERCE_BRIDGE_NONCE__' && event.data?.type === 'commerce:host-navigate' && labels[event.data.tab]) {if(event.data.tab==='pilots'&&typeof event.data.research_task_id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(event.data.research_task_id))openResearch(event.data.research_task_id);else navigate(event.data.tab);} };
    const back = () => { const p = new URL(location.href).searchParams; const next = p.get('tab') || 'overview'; setAssistantContext(null); setRequestedThreadId(''); threadRequest.current++; setResearchTaskId(p.get('research_task_id')||''); setProductResearchTask(next==='workspace'?p.get('research_task_id')||'':''); if (labels[next.replace('old:', '')]) { setTab(next); setVisited(previous => new Set([...previous,next])); setCaseId(p.get('case_id') || ''); if(next==='operations')setCostCaseId(p.get('case_id')||''); if(next==='workspace'||(next==='operations'&&p.get('case_id')))setProductCaseId(p.get('case_id')||''); if (!migrated.includes(next)) { setLegacyTab(next.replace('old:', '')); setLegacyStarted(true); } } };
    const keyboard = (event: KeyboardEvent) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setFinder(true); } };
    window.addEventListener('popstate', back); window.addEventListener('keydown', keyboard); window.addEventListener('message', hostNavigate);
    const revision = themeRevision.current;
    void api<{ theme: Theme }>('commerce_ui_get_preferences').then(result => { if (revision === themeRevision.current) { setTheme(result.theme); window.CommerceUI.applyTheme(result.theme); } }).catch(() => {});
    return () => { window.removeEventListener('popstate', back); window.removeEventListener('keydown', keyboard); window.removeEventListener('message', hostNavigate); };
  }, []);
  function resizeChat(value: number, save = true) {
    const width = workArea.current?.clientWidth || innerWidth;
    const max = Math.max(320,Math.min(width >= 1800 ? 960 : 640,Math.round((width-24)*.5),width-514));
    const next = Math.round(Math.max(320,Math.min(max,value)));
    setChatMax(max); setChatWidth(next);
    if (save) try { localStorage.setItem('commerce-product-chat-width-v2',String(next)); } catch {}
  }
  useEffect(() => {
    const element=workArea.current; if(!element)return;
    const update=()=>{setCompact(element.clientWidth<1024);let preferred=Math.round((element.clientWidth-24)*.38);try{preferred=Number(localStorage.getItem('commerce-product-chat-width-v2'))||preferred;}catch{} resizeChat(preferred,false);};
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
  async function changeTheme(value: Theme) {
    if (themeBusy) return; const previous = theme; themeRevision.current++; setThemeBusy(true); setTheme(value); window.CommerceUI.applyTheme(value);
    try { await api('commerce_ui_set_preferences', { theme: value }); setError(''); } catch (e) { setTheme(previous); window.CommerceUI.applyTheme(previous); setError(errorText(e)); } finally { setThemeBusy(false); }
  }
  function changeMode(next: boolean) { try { localStorage.setItem('commerce-workspace-example-data', String(next)); } catch {} setDemo(next); if (window.parent === window) { const url = new URL(location.href); if (next) url.searchParams.set('demo', 'true'); else url.searchParams.delete('demo'); history.replaceState({}, '', url); } }
  const pageContext = useMemo<BusinessContext>(() => ({ module: businessModule(activeTab), demo, ...(activeTab==='restock'?{calculator:'restock_plan'}:{}), ...(['workspace', 'operations'].includes(activeTab) && (activeTab==='workspace'?productCaseId:costCaseId) ? { entity: { kind: 'case', id: activeTab==='workspace'?productCaseId:costCaseId } } : {}) }), [activeTab, demo, costCaseId, productCaseId]);
  const context=assistantContext||pageContext;
  function openBusinessCopilot(next:BusinessContext){if(next.module!==businessModule(activeTab)||!!next.demo!==demo)return;setAssistantContext(next);setAssistant(true);setMobileView('chat');}
  const destination=destinationFor(activeTab) || navigation[0];
  const navLink = (id: string,label: string,icon: string) => <button key={id} aria-label={label} className={`r-nav-link ${destination.id===id?'selected':''}`} aria-current={destination.id===id?'page':undefined} onClick={()=>navigate(id)}><Icon name={icon}/><span className="r-nav-label">{label}</span></button>;
  function toggleAssistant(){if(activeTab==='workspace'){setAssistantToggle(value=>value+1);return;}if(compact){setAssistant(true);setMobileView(value=>value==='chat'?'page':'chat');}else setAssistant(value=>!value);}
  const found = Object.entries(labels).filter(([id, label]) => (id + label).toLowerCase().includes(query.trim().toLowerCase()));
  return <div className={`app r-app ${hosted?'r-hosted':''}`} data-keyboard-open={keyboardOpen}>
    <a href={compact&&mobileView==='chat'&&activeTab!=='workspace'?'#copilot-log':'#main-workspace'} className="r-skip">跳至工作区</a>
    <aside className="r-sidebar" aria-label="平台导航"><button className="r-brand" aria-label="Phone-Lab 运营台" onClick={()=>navigate('overview')}><span><Icon name="store"/></span><div><strong>Phone-Lab</strong><small>AI 跨境运营平台</small></div></button><nav aria-label="业务模块">{navigation.map(item=>navLink(item.id,item.label,item.icon))}</nav><footer><Button icon="panelLeft" onClick={toggleAssistant}>智能助手</Button><Button icon="gear" onClick={()=>navigate('skills')}>能力与连接</Button></footer></aside>
    <header className="r-topbar">
      <Button className="r-assistant-toggle" icon="panelLeft" aria-label="切换智能助手" title="展开或收起智能助手" aria-pressed={activeTab==='workspace'?productAssistant:compact?mobileView==='chat':assistant} onClick={toggleAssistant}/>
      <nav ref={navRef} className="r-business-nav" aria-label="工作台业务导航" onKeyDown={event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const buttons=[...event.currentTarget.querySelectorAll<HTMLButtonElement>('button')],index=buttons.indexOf(event.target as HTMLButtonElement);if(index<0)return;event.preventDefault();buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length]?.focus();}}>{navigation.map(item=><button key={item.id} aria-label={item.label} title={item.label} aria-current={destination.id===item.id?'page':undefined} onClick={()=>navigate(item.id)}><Icon name={item.icon}/><span>{item.label}</span></button>)}</nav>
      <div className="r-top-controls"><Button className="r-search" icon="search" aria-label="查找工作与模块" title="查找工作与模块（⌘ K）" onClick={()=>{setQuery('');setFinder(true);}}/><ThemeControl id="react-theme" theme={theme} busy={themeBusy} change={value=>void changeTheme(value)}/><Button className="r-top-icon" icon="gear" aria-label="设置" title="设置" onClick={()=>setSettings(true)}/><Button className="r-top-icon r-user-toggle" icon="person" aria-label="用户" title="用户" onClick={()=>setUser(true)}/></div>
    </header>
    <div ref={workArea} className={`r-work-area ${assistant&&activeTab!=='workspace'?'with-assistant':''} ${compact?'is-compact':''}`} data-mobile-view={mobileView} style={{'--r-chat-width':`${chatWidth}px`} as CSSProperties}>
      {activeTab!=='workspace'&&compact&&<div className="r-mode-switcher" role="group" aria-label="工作视图"><Button aria-pressed={mobileView==='chat'} onClick={()=>{setAssistant(true);setMobileView('chat');}}>AI 对话</Button><Button aria-pressed={mobileView==='page'} onClick={()=>setMobileView('page')}>{destination.label}</Button></div>}
      <Assistant context={context} visible={assistant&&activeTab!=='workspace'&&(!compact||mobileView==='chat')} close={()=>{setAssistant(false);setMobileView('page');}} onWorkspace={()=>navigate('workspace',productCaseId||undefined)} requestedThreadId={requestedThreadId} onResearch={openResearch} onModels={()=>navigate('models')} onOpenCandidate={(id,taskId)=>navigate('workspace',id,taskId)}/>
      {assistant&&activeTab!=='workspace'&&<div className="r-chat-splitter" role="separator" tabIndex={compact?-1:0} aria-label="调整对话区宽度" aria-orientation="vertical" aria-valuemin={320} aria-valuemax={chatMax} aria-valuenow={chatWidth} aria-controls="commerce-copilot main-workspace" onPointerDown={event=>{if(event.button!==0)return;event.preventDefault();drag.current={x:event.clientX,width:chatWidth};event.currentTarget.setPointerCapture(event.pointerId);}} onPointerMove={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId))resizeChat(drag.current.width+event.clientX-drag.current.x);}} onPointerUp={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);}} onKeyDown={event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();resizeChat(event.key==='Home'?320:event.key==='End'?chatMax:chatWidth+(event.key==='ArrowRight'?16:-16));}}/>}
      <main className="r-main" id="main-workspace" tabIndex={-1} ref={headingRef}>
        {destination.items.length>1&&activeTab!=='workspace'&&<nav className="r-section-tabs" aria-label={`${destination.label}页面`}>{destination.items.map(id=><Button key={id} aria-current={activeTab===id?'page':undefined} onClick={()=>navigate(id,id==='operations'?'':undefined)}>{labels[id]||id}</Button>)}</nav>}
        <ErrorNotice>{error}</ErrorNotice>
        <div hidden={tab!=='overview'}><Overview demo={demo} navigate={navigate}/></div>
        {visited.has('operations')&&<div hidden={tab!=='operations'}><CostPage key={costCaseId||'general'} caseId={costCaseId} onReturn={()=>{navigate('workspace',costCaseId||undefined);setProductTab('cost');}}/>{!costCaseId&&<div className="r-page r-secondary-entry"><Button onClick={()=>navigate('restock')}>补货计划</Button></div>}</div>}
        <div hidden={tab!=='workspace'} className="r-approved-product">{visited.has('workspace')&&<Legacy tab="workspace" chatWidth={chatWidth} onChatWidth={value=>resizeChat(value)} assistantToggle={assistantToggle} onResearch={openResearch} onAssistantState={setProductAssistant} requestedTab={productTab} active={tab==='workspace'} demo={demo} theme={theme} caseId={productCaseId} researchTaskId={productResearchTask} onResearchContext={(id,taskId)=>{if(id!==productSelection.current)return;setProductResearchTask(taskId);if(window.parent===window&&activeTab==='workspace'){const url=new URL(location.href);if(taskId)url.searchParams.set('research_task_id',taskId);else url.searchParams.delete('research_task_id');history.replaceState({},'',url);}}} navigate={navigate}/>}</div>
        <div hidden={tab!=='tasks'}><Tasks navigate={navigate} onResearch={openResearch}/></div>
        {visited.has('pilots')&&<div hidden={tab!=='pilots'}><Candidates active={tab==='pilots'} requestedTask={researchTaskId} closeTask={closeResearch} openTask={openResearch} openThread={id=>void openResearchThread(id)} navigate={navigate}/></div>}
        {visited.has('models')&&<div hidden={tab!=='models'}><Models active={tab==='models'}/></div>}
        {legacyStarted&&<div hidden={!legacy} className="r-legacy-container"><Legacy tab={legacyTab} onCopilot={openBusinessCopilot} demo={demo} theme={theme} caseId={caseId} navigate={navigate}/></div>}
      </main>
    </div>
    {settings && <WorkspaceSettings theme={theme} themeBusy={themeBusy} changeTheme={value=>void changeTheme(value)} demo={demo} changeDemo={changeMode} close={()=>setSettings(false)} error={error}/>}
    {user && <UserPanel close={()=>setUser(false)} settings={()=>{setUser(false);setSettings(true);}} connections={()=>{setUser(false);navigate('connections');}}/>}
    {finder && <Dialog title="查找模块" close={() => setFinder(false)}><label className="ui-field">模块名称或关键词<input type="search" autoFocus value={query} onChange={e => setQuery(e.target.value)} placeholder="例如：商品、成本、库存、任务" /></label><p className="r-footnote" role="status">{found.length} 个匹配入口</p><div className="r-finder-list">{found.length ? found.map(([id, label]) => <Button key={id} onClick={() => { setFinder(false); navigate(id); }}>{label}<span>{navigation.find(item=>item.items.includes(id))?.label||'业务页面'}</span></Button>) : <Empty>没有匹配模块。</Empty>}</div></Dialog>}</div>;
}
createRoot(document.getElementById('root')!).render(<SurfaceProvider><Workspace /></SurfaceProvider>);
