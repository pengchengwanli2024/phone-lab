/* Execute actual bridge handlers without a browser, service, or customer data. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { transform } from 'esbuild';
const root=new URL('../../',import.meta.url);
const [appSource,legacySource,childSource,importSource,kit,forms,helper,business]=await Promise.all(['workbench/src/app.tsx','workbench/src/legacy.tsx','web/app.js','workbench/src/order-imports.tsx','ui/kit.js','web/businessforms-ui.js','web/order-support-context.js','web/business-ui.js'].map(path=>readFile(new URL(path,root),'utf8')));
const between=(source,start,end)=>{const from=source.indexOf(start),to=source.indexOf(end,from);assert.ok(from>=0&&to>from,`source seam ${start}`);return source.slice(from,to);};
const js=async(source)=>(await transform(source,{loader:'ts',target:'es2022'})).code;
const parentCode=await js(between(appSource,'  function cancelOrderSupport()','  function rememberListingRoute')+'\nglobalThis.open=openOrderSupport;globalThis.finish=finishOrderSupport;globalThis.cancel=cancelOrderSupport;');
const receiveCode=await js(between(legacySource,'    const receive = async','    window.addEventListener(\'message\', receive)')+'\nglobalThis.receive=receive;');
const sendingEffect=legacySource.split('\n').find(line=>line.includes("postMessage({type:'commerce:order-support-context'"));assert.ok(sendingEffect);
const childListener=childSource.split('\n').find(line=>line.includes("m.type!=='commerce:order-support-context'"));assert.ok(childListener);
const supportCode=await js(importSource.split('\n').find(line=>line.includes('async function support(row:'))+'\nglobalThis.support=support;');
const modeEffect=await js(importSource.split('\n').find(line=>line.includes('useEffect(')&&line.includes('void load()')&&line.includes('[demo]')));
const detailAction=childSource.split('\n').find(line=>line.includes("else if(action==='order-support')"));assert.ok(detailAction);
const detailCode=await js("async function run(){const action='order-support';"+detailAction.replace("else if(action==='order-support')","if(action==='order-support')")+"}globalThis.run=run;");
const prepared=()=>({context:{schema:'commerce-order-support-context-v1',scope:{demo:true,platform:'ozon',store_id:'synthetic-store',market:'RU'},order:{id:'SYN-1:1',order_id:'SYN-1',line_id:'1',source_sha256:'a'.repeat(64),record_sha256:'b'.repeat(64),import_batch_id:'import-synthetic',batch_sha256:'d'.repeat(64)},source:{data_source:'operator_csv_import_unverified',observed_at:null},context_sha256:'c'.repeat(64)},sources:[],external_execution_allowed:false});
function parentHarness(){
 const navigations=[],requests=[],errors=[],timers=new Map(),pendingOrder={current:null};let sequence=0;
 const context=vm.createContext({demo:true,tab:'order-imports',errorText:e=>e.message,pendingOrder,crypto:{randomUUID:()=>`request-${++sequence}`},setOrderRequest:r=>requests.push(r),setLegacyStarted(){},setError:e=>errors.push(e),navigate:tab=>navigations.push(tab),setTimeout:fn=>{const id=++sequence;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id)});
 vm.runInContext(parentCode,context);
 return {context,navigations,requests,errors,timers,pendingOrder,open:c=>context.open(c),finish:(...args)=>context.finish(...args),cancel:()=>context.cancel()};
}
function legacyHarness(parent,{visible=false}={}){
 const frameWindow={postMessage(){}},posted=[],calls=[],frame={current:{contentWindow:frameWindow}},nonce={current:'synthetic-nonce'},orderResult={current:(id,error)=>parent.finish(id,error)},orderCallback={current:c=>parent.open(c)},activeView={current:visible};
 const context=vm.createContext({frame,nonce,orderResult,orderCallback,activeView,active:true,product:false,caseId:'',api:async(tool,args)=>{calls.push([tool,args]);return {sources:[],drafts:[]};},navigate:tab=>parent.navigations.push(tab)});
 frameWindow.postMessage=value=>posted.push(value);vm.runInContext(receiveCode,context);
 return {context,frameWindow,frame,nonce,posted,calls,receive:data=>context.receive({source:frameWindow,data}),foreign:(data,source={})=>context.receive({source,data})};
}
async function childHarness({demo=true,visible=false}={}){
 const messages=[],handlers={},calls=[],parent={},scope={platform:'ozon',store_ref:'synthetic-store',subject_ref:'SYN-1'},source={id:'synthetic-conversation',kind:'conversation',scope,synthetic:true,label:'Synthetic conversation',record_count:1,fresh:true,version:1,sha256:'1'.repeat(64),observed_at:'2026-11-17T00:00:00Z'};let dialog=false;
 const document={documentElement:{dataset:{}},addEventListener:(type,fn)=>(handlers[type]||=[]).push(fn),querySelector:()=>dialog?{}:null,querySelectorAll:()=>[],getElementById:()=>null};
 const window={dispatchEvent(){},matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener:(type,fn)=>(handlers[type]||=[]).push(fn)};
 parent.postMessage=value=>messages.push(value);
 const context=vm.createContext({window,document,parent,reactHost:true,bridgeNonce:'synthetic-nonce',state:{demo},crypto:{randomUUID:()=> 'synthetic-key'},CustomEvent:class{},setTimeout(){}});
 for(const source of [kit,forms,helper,business])vm.runInContext(source,context);
 const controller=window.CommerceBusiness({api:async(name,args)=>{calls.push([name,args]);return {sources:[source],drafts:[]};},esc:window.CommerceUI.escape,repaint(){},toast(){},modal(){dialog=true;},closeModal(){dialog=false;},isActive:()=>visible});
 context.business=controller;vm.runInContext(childListener,context);
 const emit=async(data,eventSource=parent)=>{for(const fn of handlers.message||[])await fn({source:eventSource,data});};
 const choose=async()=>{for(const fn of handlers.change||[])await fn({target:{checked:true,dataset:{businessSource:source.id},matches:()=>true}});};
 return {controller,calls,messages,emit,parent,choose,setDialog:value=>dialog=value};
}
const message=(id,body=prepared())=>({type:'commerce:order-support-context',nonce:'synthetic-nonce',id,prepared:body});

test('parent stages the snapshot and navigates only after its own accepted receipt',async()=>{
 const p=parentHarness(),body=prepared(),pending=p.open(body);let settled=false;pending.then(()=>{settled=true;});
 assert.deepEqual(p.navigations,[]);assert.equal(p.requests.at(-1).prepared,body);
 p.finish('other-request');await Promise.resolve();assert.equal(settled,false);assert.deepEqual(p.navigations,[]);
 p.finish(p.pendingOrder.current.id);await pending;assert.deepEqual(p.navigations,['support']);assert.equal(p.pendingOrder.current,null);assert.equal(p.timers.size,0);
});

test('mode mismatches, editor refusal, stale receipts and cancellation keep the original route',async()=>{
 const p=parentHarness();const wrong=prepared();wrong.context.scope.demo=false;
 await assert.rejects(p.open(wrong),/模式不一致|order_support_scope_mismatch/);assert.equal(p.pendingOrder.current,null);
 const rejected=p.open(prepared()),first=p.pendingOrder.current.id;const rejection=assert.rejects(rejected,/先保存或关闭|order_support_editor_open/);
 p.finish(first,'order_support_editor_open');await rejection;assert.deepEqual(p.navigations,[]);
 const cancelled=p.open(prepared()),stale=p.pendingOrder.current.id;const cancellation=assert.rejects(cancelled,/已取消|order_support_context_cancelled/);p.cancel();await cancellation;
 p.finish(stale);assert.deepEqual(p.navigations,[]);
});

test('Legacy checks source and nonce but accepts the pending receipt from its hidden iframe',async()=>{
 const p=parentHarness(),l=legacyHarness(p),pending=p.open(prepared()),id=p.pendingOrder.current.id;
 const receipt={type:'commerce:order-support-result',nonce:'synthetic-nonce',id,status:'accepted'};
 await l.foreign(receipt);await l.receive({...receipt,nonce:'wrong'});assert.deepEqual(p.navigations,[]);
 await l.receive({type:'commerce:workspace-navigate',nonce:'synthetic-nonce',tab:'support'});assert.deepEqual(p.navigations,[]);
 await l.receive(receipt);await pending;assert.deepEqual(p.navigations,['support']);
});

test('an initialized hidden frame receives the staged context and can finish necessary local reads',async()=>{
 const p=parentHarness(),l=legacyHarness(p),request={id:'staged-id',prepared:prepared()};
 const context=vm.createContext({product:false,ready:true,orderSupportRequest:request,frame:l.frame,nonce:l.nonce,useEffect:fn=>fn()});
 vm.runInContext(await js(sendingEffect),context);assert.equal(l.posted.length,1);assert.equal(l.posted[0].id,'staged-id');
 await l.receive({type:'commerce:call',nonce:'synthetic-nonce',id:'local-read',tool:'commerce_business_list',arguments:{synthetic:true}});
 assert.equal(l.calls[0][0],'commerce_business_list');assert.equal(l.posted.at(-1).type,'commerce:result');assert.equal(l.posted.at(-1).id,'local-read');
});

test('child authenticates source and mode, keeps repeated-context selection, and refuses an unfinished editor',async()=>{
 const c=await childHarness();await c.emit(message('foreign'),{});await c.emit({...message('nonce'),nonce:'wrong'});assert.equal(c.calls.length,0);assert.equal(c.messages.length,0);
 const wrong=prepared();wrong.context.scope.demo=false;await c.emit(message('mode',wrong));assert.equal(c.messages.at(-1).status,'failed');assert.equal(c.calls.length,0);
 await c.emit(message('first'));assert.equal(c.messages.at(-1).status,'accepted');assert.equal(c.calls[0][0],'commerce_business_list');
 await c.choose();assert.match(c.controller.view('support'),/已选 1 条/);
 await c.emit(message('same'));assert.equal(c.messages.at(-1).status,'accepted');assert.match(c.controller.view('support'),/已选 1 条/);
 c.setDialog(true);await c.emit(message('editing'));assert.equal(c.messages.at(-1).status,'failed');assert.equal(c.messages.at(-1).error,'order_support_editor_open');assert.match(c.controller.view('support'),/已选 1 条/);
});

test('the full hidden child path reaches navigation only through its authenticated accepted receipt',async()=>{
 const p=parentHarness(),l=legacyHarness(p),c=await childHarness(),pending=p.open(prepared());
 await c.emit(message(p.pendingOrder.current.id));assert.deepEqual(p.navigations,[]);
 await l.receive(c.messages.at(-1));await pending;assert.deepEqual(p.navigations,['support']);
});

test('switching CSV mode during a staged support handoff releases the disabled form',async()=>{
 let rejectHandoff,handedOff=false;const handoff=new Promise((_resolve,reject)=>{rejectHandoff=reject;});handoff.catch(()=>{});const generation={current:0};let modeCleanup;
 const context=vm.createContext({batch:{id:'import-synthetic',scope:{platform:'ozon',store_ref:'synthetic-store',market:'RU'}},demo:true,busy:false,generation,fileEpoch:{current:0},setReadingFile(){},api:async()=>prepared(),onSupport:()=>{handedOff=true;return handoff;},setBusy:v=>{context.busy=v;},setError(){},errorText:e=>e.message,setBatch(){},setOrders(){},setChecked(){},setPage(){},load:()=>{generation.current++;},useEffect:fn=>{modeCleanup=fn();}});
 vm.runInContext(importSource.split('\n').find(line=>line.includes('function invalidateFileRead()')),context);
 vm.runInContext(supportCode,context);const support=context.support({id:'SYN-1:1',source_sha256:'a'.repeat(64)});await new Promise(setImmediate);assert.equal(handedOff,true);assert.equal(context.busy,true);
 vm.runInContext(modeEffect,context);modeCleanup();context.demo=false;vm.runInContext(modeEffect,context);
 rejectHandoff(Error('cancelled by mode switch'));await support;
 assert.equal(context.busy,false,'the new mode must release busy after invalidating the old request');
});

for(const changed of ['closed-or-replaced-dialog','changed-route'])test('late order-detail prepare cannot replace '+changed,async()=>{
 let resolvePrepare;const pending=new Promise(resolve=>{resolvePrepare=resolve;});const messages=[],closed=[];
 const button={dataset:{id:'SYN-1:1'},disabled:false,isConnected:true};let currentDialog={identity:'original-order-details'};
 const context=vm.createContext({b:button,state:{demo:true,tab:'orders',orders:[{id:'SYN-1:1',platform:'ozon',store_id:'synthetic-store',market:'RU',source_sha256:'a'.repeat(64)}]},navigationGeneration:7,api:()=>pending,reactHost:true,bridgeNonce:'synthetic-nonce',parent:{postMessage:m=>messages.push(m)},close:()=>closed.push(currentDialog),document:{querySelector:()=>currentDialog},business:{enterOrderSupport(){throw Error('must not replace editor');}},navigate(){throw Error('must not navigate');}});
 vm.runInContext(detailCode,context);const request=context.run();
 currentDialog={identity:'new-unsaved-editor',reply:'Keep this exact synthetic input'};
 if(changed==='closed-or-replaced-dialog')button.isConnected=false;
 else{context.navigationGeneration++;context.state.tab='support';}
 resolvePrepare(prepared());await request;
 assert.deepEqual(closed,[],'a late result must leave the current editor untouched');
 assert.deepEqual(messages,[],'a discarded source must not stage a handoff');
});

const pageMetadataSource=await readFile(new URL('ui/page-context.js',root),'utf8');
const resumeEffect=legacySource.split('\n').find(line=>line.includes('useEffect')&&line.includes('postMessage({type:')&&line.includes("'commerce:legacy-resume'"));assert.ok(resumeEffect);
const childResume=childSource.split('\n').find(line=>line.includes("event.data.type!=='commerce:legacy-resume'"));assert.ok(childResume);
const assistantSource=await readFile(new URL('workbench/src/assistant.tsx',root),'utf8');
const assistantCode=(await transform(assistantSource.split('\n').filter(line=>!line.startsWith('import ')).join('\n').replace('export function Assistant','function Assistant')+'\nglobalThis.Assistant=Assistant;',{loader:'tsx',target:'es2022',jsxFactory:'jsx'})).code;
const metadataWindow={};vm.runInNewContext(pageMetadataSource,{window:metadataWindow});
const actualPage=()=>({page:'support',section:'sources',demo:true,source:'local',entity:{kind:'order',id:'SYN-1:1'},filters:{platform:'ozon',market:'RU',store_ref:'synthetic-store'},source_refs:{record:'b'.repeat(64)}});
const actualScope=()=>({module:'support',demo:true,platform:'ozon',market:'RU',entity:{kind:'order',id:'SYN-1:1'}});

function animationQueue(){
 const pending=new Map();let serial=0;
 return {request:callback=>{const id=++serial;pending.set(id,callback);return id;},cancel:id=>pending.delete(id),flush:()=>{const frame=[...pending];pending.clear();for(const [,callback]of frame)callback(0);},get size(){return pending.size;}};
}

test('hidden page metadata is authenticated and cached without changing the active page, then replayed on resume',async()=>{
 const p=parentHarness(),l=legacyHarness(p),callbacks=[],lastPage={current:null},pageCallback={current:(page,scope)=>callbacks.push({page,scope})};
 Object.assign(l.context,{window:metadataWindow,lastPage,pageCallback});
 const metadata={type:'commerce:page-context',nonce:'synthetic-nonce',page_context:actualPage(),context:actualScope()};
 await l.foreign(metadata);await l.receive({...metadata,nonce:'foreign'});assert.equal(lastPage.current,null);
 await l.receive(metadata);assert.equal(callbacks.length,0);assert.equal(lastPage.current.page.demo,true);assert.equal(lastPage.current.scope.demo,true);
 const raf=animationQueue();const ctx=vm.createContext({product:false,active:false,ready:true,legacyTab:'support',lastPage,pageCallback,frame:l.frame,nonce:l.nonce,requestAnimationFrame:raf.request,cancelAnimationFrame:raf.cancel,useEffect:fn=>fn()});
 vm.runInContext(await js(resumeEffect),ctx);assert.equal(callbacks.length,0);assert.equal(l.posted.length,0);
 ctx.active=true;vm.runInContext(await js(resumeEffect),ctx);
 assert.equal(callbacks.length,1);assert.equal(callbacks[0].page.demo,true);assert.equal(callbacks[0].scope.entity.id,'SYN-1:1');assert.equal(l.posted.length,0,'resume waits until the next animation frame');raf.flush();assert.equal(l.posted.at(-1).type,'commerce:legacy-resume');
});

// The real dialog close button precedes editable fields in document order.
function dialogQuery({textarea=null,input=null,button=null}){
 return selector=>selector.includes(',')?button:selector.includes('textarea')?textarea:selector.includes('input')?input:selector.includes('button')?button:null;
}

test('authenticated resume re-emits unchanged business metadata and restores focus without replacing reply or caret',async()=>{
 const handlers={},sent=[],focused=[],field={value:'Keep this exact synthetic reply\n第二行',selectionStart:7,selectionEnd:12,focus:options=>focused.push({target:'reply',...options})},parent={postMessage:m=>sent.push(m)};
 const query=dialogQuery({textarea:field,input:{focus:()=>focused.push({target:'input'})},button:{focus:()=>focused.push({target:'close'})}});
 const context=vm.createContext({window:{addEventListener:(type,fn)=>handlers[type]=fn},reactHost:true,parent,bridgeNonce:'synthetic-nonce',pageLocation:{snapshot:actualPage},copilotContext:actualScope,document:{querySelector:query}});
 vm.runInContext(childResume,context);const resume={type:'commerce:legacy-resume',nonce:'synthetic-nonce'};
 handlers.message({source:{},data:resume});handlers.message({source:parent,data:{...resume,nonce:'wrong'}});assert.equal(sent.length,0);assert.equal(focused.length,0);
 handlers.message({source:parent,data:resume});handlers.message({source:parent,data:resume});
 assert.equal(sent.length,2,'unchanged metadata must be re-emitted after a hidden return');assert.equal(sent[0].page_context.demo,true);assert.equal(sent[0].context.demo,true);
 assert.equal(focused.length,2);assert.ok(focused.every(value=>value.target==='reply'));assert.equal(focused[0].preventScroll,true);assert.equal(field.value,'Keep this exact synthetic reply\n第二行');assert.equal(field.selectionStart,7);assert.equal(field.selectionEnd,12);
});

function assistantHarness(){
 const slots=[],effects=[],calls={open:0,openModes:[],close:0,requests:[]};let cursor=0,options;
 const hooks={useRef:initial=>{const i=cursor++;return slots[i]||=( {current:initial} );},useState:initial=>{const i=cursor++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return [slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value;}];},useEffect:(fn,deps)=>{const i=cursor++,old=slots[i];if(!old||deps.some((v,n)=>!Object.is(v,old.deps[n])))effects.push(()=>{old?.cleanup?.();slots[i]={deps,cleanup:fn()};});}};
 const context=vm.createContext({...hooks,jsx:(type,props,...children)=>({type,props:props||{},children}),window:{CommerceCopilot:input=>{options=input;return {open(){calls.open++;calls.openModes.push(options.getContext().demo);},close(){calls.close++;},dispose(){},contextChanged(){},openThread(){},view:()=>'',afterPaint(){}};}},api:async(...args)=>{calls.requests.push(args);return {};},errorText:e=>e.message,productScope:()=>{throw Error('no product read');},Button:'button',Dialog:'dialog',Empty:'empty',ErrorNotice:'error'});
 vm.runInContext(assistantCode,context);
 return {calls,get options(){return options;},render:props=>{cursor=0;return context.Assistant({visible:true,close(){},...props});},flush:()=>effects.splice(0).forEach(fn=>fn())};
}

test('assistant waits for confirmed metadata and never opens or exposes the fallback mode for sending',async()=>{
 const a=assistantHarness(),fallback={module:'support',demo:false};
 let view=a.render({pageReady:false,context:fallback,pageContext:{page:'support',demo:false}});a.flush();
 assert.equal(a.calls.open,0);assert.equal(a.options.isActive(),false);assert.equal(view.props['aria-busy'],true);
 a.render({pageReady:false,context:fallback,pageContext:{page:'support',demo:false}});a.flush();assert.equal(a.options.isActive(),false);
 a.render({pageReady:true,context:actualScope(),pageContext:actualPage()});a.flush();
 assert.equal(a.options.getContext().demo,true);assert.equal(a.options.getPageContext().demo,true);assert.equal(a.options.getPageContext().source_refs.record,'b'.repeat(64));assert.equal(a.options.isActive(),true);assert.ok(a.calls.open>=1);assert.ok(a.calls.openModes.every(mode=>mode===true),'no pre-metadata fallback context may be opened');assert.deepEqual(a.calls.requests,[]);
 a.render({pageReady:false,context:actualScope(),pageContext:actualPage()});a.flush();assert.equal(a.options.isActive(),false);
});

test('legacy currentPage uses the actual child mode instead of the global fallback',async()=>{
 const selection=appSource.split('\n').find(line=>line.includes('const currentPage='));assert.ok(selection);
 const context=vm.createContext({legacy:true,activeTab:'support',framePage:actualPage(),assistantPage:{page:'support',demo:false},pageContext:{module:'support',demo:false}});
 vm.runInContext(await js(selection+'\nglobalThis.selected=currentPage;'),context);assert.equal(context.selected.demo,true);assert.equal(context.selected.entity.id,'SYN-1:1');assert.equal(context.selected.source_refs.record,'b'.repeat(64));
});

test('the explicit support assistant request accepts the confirmed child mode even when global mode differs',async()=>{
 const entry=appSource.split('\n').find(line=>line.includes('function openBusinessCopilot('));assert.ok(entry);const scopes=[],opened=[];
 const context=vm.createContext({activeTab:'support',legacy:true,framePage:actualPage(),currentPage:actualPage(),pageContext:{module:'support',demo:false},businessModule:tab=>tab,setAssistantContext(){},setFrameScope:scope=>scopes.push(scope),setAssistant:visible=>opened.push(visible),setMobileView(){}});
 vm.runInContext(await js(entry+'\nglobalThis.open=openBusinessCopilot;'),context);context.open(actualScope());
 assert.equal(scopes.length,1,'the confirmed child scope should be accepted');assert.equal(scopes[0].demo,true);assert.deepEqual(opened,[true]);
});

test('returning to the same support page leaves its unfinished editor and navigation generation intact',async()=>{
 const navigateLine=childSource.split('\n').find(line=>line.includes('async function navigate(tab,initial=false)'));assert.ok(navigateLine);
 const context=vm.createContext({labels:{support:'客服'},state:{tab:'support'},navigationGeneration:9,business:{cancelEditor(){throw Error('must preserve editor');}},paint(){throw Error('must preserve original DOM');}});
 vm.runInContext(navigateLine+'\nglobalThis.resume=navigate;',context);await context.resume('support');assert.equal(context.navigationGeneration,9);
});


test('browser frame order restores the editor after heading focus and cancels abandoned resume work',async()=>{
 const raf=animationQueue(),tasks=[],trace=[],handlers={},sent=[];let focused='source-page',cleanup;
 const field={value:'Keep this original synthetic reply\n第二行',selectionStart:5,selectionEnd:14,focus:()=>{focused='reply-editor';trace.push('editor-focus');}};
 const parent={postMessage:message=>sent.push(message)},nonce={current:'synthetic-nonce'};
 const child=vm.createContext({window:{addEventListener:(type,fn)=>handlers[type]=fn},reactHost:true,parent,bridgeNonce:nonce.current,pageLocation:{snapshot:actualPage},copilotContext:actualScope,document:{querySelector:dialogQuery({textarea:field,input:{focus:()=>{focused='other-input';trace.push('input-focus');}},button:{focus:()=>{focused='close-button';trace.push('close-focus');}}})}});
 vm.runInContext(childResume,child);
 const frame={current:{contentWindow:{postMessage:data=>{trace.push('post-resume');tasks.push(()=>handlers.message({source:parent,data}));}}}};
 const drainTasks=()=>{while(tasks.length)tasks.shift()();};
 const headingLine=appSource.split('\n').find(line=>line.includes('requestAnimationFrame(() => headingRef.current?.focus())'));assert.ok(headingLine);
 const heading=vm.createContext({requestAnimationFrame:raf.request,headingRef:{current:{focus:()=>{focused='main-heading';trace.push('heading-focus');}}}});
 // navigate queues the heading first; React then runs the Legacy activation effect.
 vm.runInContext(headingLine,heading);
 const resume=vm.createContext({product:false,active:true,ready:true,legacyTab:'support',lastPage:{current:null},pageCallback:{current(){}},frame,nonce,requestAnimationFrame:raf.request,cancelAnimationFrame:raf.cancel,useEffect:fn=>{cleanup=fn();}});
 vm.runInContext(await js(resumeEffect),resume);
 drainTasks(); // An immediate postMessage would restore focus too early, before the heading rAF.
 assert.equal(focused,'source-page');assert.equal(raf.size,2);
 raf.flush();assert.equal(focused,'main-heading');drainTasks();
 assert.equal(focused,'reply-editor');assert.deepEqual(trace,['heading-focus','post-resume','editor-focus']);
 assert.equal(field.value,'Keep this original synthetic reply\n第二行');assert.equal(field.selectionStart,5);assert.equal(field.selectionEnd,14);assert.equal(sent.at(-1).type,'commerce:page-context');
 // Leaving before another activation frame must not let its queued reply steal focus.
 vm.runInContext(await js(resumeEffect),resume);assert.equal(raf.size,1);assert.equal(typeof cleanup,'function');cleanup();assert.equal(raf.size,0);
 focused='another-page';raf.flush();drainTasks();assert.equal(focused,'another-page');assert.equal(sent.length,1);
});


test('dialog focus selects textarea before earlier close buttons and falls back to input then button',()=>{
 for(const expected of ['textarea','input','button']){
  const handlers={},focused=[],sent=[],parent={postMessage:m=>sent.push(m)};
  const button={focus:options=>focused.push({target:'button',...options})};
  const input=expected==='button'?null:{value:'Synthetic input unchanged',focus:options=>focused.push({target:'input',...options})};
  const textarea=expected==='textarea'?{value:'Synthetic reply unchanged',selectionStart:3,selectionEnd:8,focus:options=>focused.push({target:'textarea',...options})}:null;
  const query=dialogQuery({textarea,input,button});
  assert.equal(query('.dialog textarea,.dialog input,.dialog button'),button,'a compound selector follows document order, not selector priority');
  const context=vm.createContext({window:{addEventListener:(type,fn)=>handlers[type]=fn},reactHost:true,parent,bridgeNonce:'synthetic-nonce',pageLocation:{snapshot:actualPage},copilotContext:actualScope,document:{querySelector:query}});
  vm.runInContext(childResume,context);handlers.message({source:parent,data:{type:'commerce:legacy-resume',nonce:'synthetic-nonce'}});
  assert.equal(focused.length,1);assert.equal(focused[0].target,expected);assert.equal(focused[0].preventScroll,true);
  if(textarea){assert.equal(textarea.value,'Synthetic reply unchanged');assert.equal(textarea.selectionStart,3);assert.equal(textarea.selectionEnd,8);}
  if(input)assert.equal(input.value,'Synthetic input unchanged');assert.equal(sent.length,1);
 }
});
