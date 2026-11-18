// Isolated real-HTTP regression for shared Web interactions and inline delivery.
import assert from 'node:assert/strict';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import {readFile,writeFile,mkdtemp,mkdir,readdir,access,rm} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {tmpdir,homedir} from 'node:os';
import net from 'node:net';
import http from 'node:http';
import path from 'node:path';

const root=path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))));
const out=path.resolve(process.env.QA_OUTPUT_DIR||path.join(root,'.commerce-state/verification/modern-web'));await mkdir(out,{recursive:true});
let playwright;
try{playwright=await import(process.env.PLAYWRIGHT_MODULE||'playwright');}catch{for(const entry of await readdir(path.join(homedir(),'.npm/_npx')).catch(()=>[])){try{playwright=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',entry,'node_modules/playwright/index.mjs')).href);break;}catch{}}}
assert.ok(playwright,'Use the existing Playwright installation or PLAYWRIGHT_MODULE.');
const {chromium}=playwright;
const work=await mkdtemp(path.join(tmpdir(),'phone-lab-mwg-'));
const listener=net.createServer();
await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
const port=listener.address().port;
await new Promise(resolve=>listener.close(resolve));
const origin=`http://127.0.0.1:${port}`;
const child=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'commerce/qa/react_workbench_fixture.py')],{cwd:root,env:{...process.env,COMMERCE_STATE:work,COMMERCE_PORT:String(port)},stdio:['ignore','ignore','pipe']});
const stopped=new Promise(resolve=>child.once('close',resolve));
let stderr='';child.stderr.on('data',chunk=>stderr+=chunk.toString());
const result={scope:'Isolated synthetic fixture; existing generated artifacts; Chromium only',errors:[],external:[],checks:[]};
const fingerprint=async()=>Object.fromEntries(await Promise.all(['commerce/web/workbench.bundle.js','commerce/web/workbench.sources.json','commerce/web/product-workspace.bundle.js','commerce/ui/build.py'].map(async name=>[name,createHash('sha256').update(await readFile(path.join(root,name))).digest('hex')])));
result.startHashes=await fingerprint();
let browser,page;
try{
 for(let i=0;i<100;i++){
  if(child.exitCode!==null)throw Error('Fixture exited: '+stderr);
  try{if((await fetch(origin+'/v1/health',{headers:{authorization:'Bearer synthetic-workbench-preview'}})).ok)break;}catch{}
  await new Promise(resolve=>setTimeout(resolve,100));
 }
 let executablePath=process.env.CHROME_PATH;
 if(!executablePath){try{await access('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');executablePath='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';}catch{}}
 browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{}),args:['--use-mock-keychain','--password-store=basic']});
 const context=await browser.newContext({viewport:{width:1440,height:960}});
 await context.route('**/*',route=>{const url=route.request().url();if(url.startsWith(origin+'/')||/^(data|blob|about):/.test(url))return route.continue();result.external.push(new URL(url).origin);return route.abort();});
 await context.addInitScript(()=>{
  window.__auditLongTasks=[];
  new PerformanceObserver(list=>window.__auditLongTasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true});
 });
 page=await context.newPage();page.on('pageerror',e=>result.errors.push(e.message));
 await page.goto(origin+'/login?token=synthetic-workbench-preview');
 const response=await page.goto(origin+'/workspace?tab=overview&demo=true');
 await page.locator('.r-app').waitFor();
 await page.locator('.r-dashboard').waitFor();
 result.load=await page.evaluate(()=>({title:document.title,htmlBytes:new TextEncoder().encode(document.documentElement.outerHTML).length,resources:performance.getEntriesByType('resource').length,longTasks:window.__auditLongTasks,navigation:performance.getEntriesByType('navigation').map(e=>({encodedBodySize:e.encodedBodySize,domContentLoaded:e.domContentLoadedEventEnd,load:e.loadEventEnd}))}));
 result.load.headers=await response.allHeaders();
 await page.screenshot({path:path.join(out,'overview-1440-light.png'),fullPage:false});
 // A real streaming response withholds unused document bytes until the shell
 // has painted. This guards the offline inline protocol as well as ordering.
 const rawHtml=await (await fetch(origin+'/workspace',{headers:{authorization:'Bearer synthetic-workbench-preview'}})).text();
 const tailAt=rawHtml.indexOf('<!-- COMMERCE_EMBEDDED_DOCUMENTS_START -->');assert.ok(tailAt>0);
 let releaseTail;const gate=http.createServer((request,response)=>{
  if(request.url==='/workspace'){
   response.writeHead(200,{'content-type':'text/html; charset=utf-8','cache-control':'no-store'});
   response.write(rawHtml.slice(0,tailAt));releaseTail=()=>response.end(rawHtml.slice(tailAt));return;
  }
  const upstream=http.request(origin+request.url,{method:request.method,headers:{...request.headers,host:`127.0.0.1:${port}`,origin,authorization:'Bearer synthetic-workbench-preview'}},reply=>{response.writeHead(reply.statusCode,reply.headers);reply.pipe(response)});
  upstream.on('error',()=>{response.writeHead(502);response.end()});request.pipe(upstream);
 });
 await new Promise(resolve=>gate.listen(0,'127.0.0.1',resolve));const gateOrigin='http://127.0.0.1:'+gate.address().port;
 const earlyContext=await browser.newContext({viewport:{width:1440,height:900}});
 await earlyContext.route('**/*',route=>{const url=route.request().url();if(url.startsWith(gateOrigin+'/')||/^(data|blob|about):/.test(url))return route.continue();result.external.push(url);return route.abort()});
 try{
  const earlyPage=await earlyContext.newPage();earlyPage.on('pageerror',e=>result.errors.push(e.message));
  await earlyPage.goto(gateOrigin+'/workspace',{waitUntil:'commit'});await earlyPage.locator('.r-dashboard').waitFor();
  await earlyPage.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await earlyPage.screenshot({path:path.join(out,'progressive-before-tail.png')});
  assert.equal(await earlyPage.locator('#commerce-embedded-legacy').count(),0,'The application can render before deferred inline data arrives');
  assert.equal(await earlyPage.evaluate(()=>document.readyState),'loading');
  releaseTail();await earlyPage.waitForLoadState('domcontentloaded');
  await earlyPage.locator('.r-search').click();await earlyPage.getByRole('dialog').getByRole('searchbox').fill('connections');
  await earlyPage.getByRole('dialog').locator('[data-finder-route="connections"]').click();
  await earlyPage.frameLocator('iframe[title="专业业务模块"]').locator('.connections-root').waitFor();
  result.checks.push({kind:'progressiveInline',paintBeforeData:true,legacyDecodedAfterData:true});
 }finally{releaseTail?.();await earlyContext.close();gate.closeAllConnections();await new Promise(resolve=>gate.close(resolve));}
 const alertPage=await context.newPage();
 await alertPage.goto(origin+'/workspace?tab=alerts&demo=false');
 const alertFrame=alertPage.frameLocator('iframe[title="专业业务模块"]');
 await alertFrame.locator('.app[data-workspace-tab="alerts"][data-view-ready="true"]').waitFor();
 const orderLink=alertFrame.getByRole('button',{name:'查看关联订单',exact:true}).first();
 assert.equal(await orderLink.count(),1,'A specific order alert must expose its related order');
 const orderRequests=[];alertPage.on('request',r=>{if(r.url().endsWith('/v1/invoke'))orderRequests.push(r.postDataJSON().tool)});
 for(const width of [1440,390]){
  await alertPage.setViewportSize({width,height:width===1440?900:844});
  await alertPage.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  await orderLink.click();const originalOrder=alertFrame.getByRole('dialog');
  await originalOrder.getByRole('heading',{name:'订单详情 · SYN-1',exact:true}).waitFor();
  assert.match(await originalOrder.innerText(),/平台只读快照/);
  assert.ok(await originalOrder.getByRole('button',{name:'核对经营快照',exact:true}).isVisible());
  await alertPage.screenshot({path:path.join(out,'alert-order-'+width+'.png')});
  await alertPage.keyboard.press('Escape');await originalOrder.waitFor({state:'hidden'});
 }
 const wrongSource=async route=>{const call=route.request().postDataJSON();if(call?.tool!=='commerce_orders_list')return route.continue();const response=await route.fetch(),data=await response.json();for(const order of data.orders)order.source_sha256='0'.repeat(64);return route.fulfill({response,json:data})};
 await alertPage.route('**/v1/invoke',wrongSource);await orderLink.click();
 await alertFrame.locator('.live-alerts').getByText('读取未完成：提醒来源已变化或订单范围不匹配，请刷新提醒后重新核对。',{exact:true}).waitFor();
 assert.equal(await alertFrame.getByRole('dialog').count(),0,'A changed snapshot cannot open another order');
 await alertPage.unroute('**/v1/invoke',wrongSource);await orderLink.click();
 await alertFrame.getByRole('dialog').getByRole('heading',{name:'订单详情 · SYN-1',exact:true}).waitFor();
 assert.equal(orderRequests.some(t=>/commerce_(live_sync|copilot_send|task_create|.*submit)/.test(t)),false,'Related-order navigation stays read-only');
 result.checks.push({kind:'alertOrderContext',widths:[1440,390],changedSourceRejected:true,recovered:true,mutations:0});
 await alertPage.close();
 for(const width of [1440,768,390,320]){
  await page.setViewportSize({width,height:960});
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const metrics=await page.evaluate(()=>({scrollWidth:document.documentElement.scrollWidth,innerWidth,mainWidth:document.querySelector('#main-workspace').getBoundingClientRect().width,workWidth:document.querySelector('.r-work-area').getBoundingClientRect().width,assistantExpanded:document.querySelector('#workspace-assistant-toggle').getAttribute('aria-expanded'),unnamedInputs:[...document.querySelectorAll('input,textarea,select')].filter(e=>e.getClientRects().length&&!e.closest('[hidden]')&&!e.labels?.length&&!e.getAttribute('aria-label')&&!e.getAttribute('aria-labelledby')).map(e=>({tag:e.tagName,id:e.id,placeholder:e.getAttribute('placeholder')}))}));
  assert.equal(metrics.assistantExpanded,'false','The assistant starts collapsed');
  assert.equal(await page.locator('.r-shared-assistant:visible').count(),0);
  assert.ok(metrics.mainWidth>=metrics.workWidth-2,'Collapsed assistant leaves the complete work-area width available at '+width);
  result.checks.push({kind:'viewport',width,...metrics});
  if(width===390){
   await page.locator('#workspace-assistant-toggle').click();await page.locator('.r-shared-assistant[aria-busy="false"] #copilot-message').waitFor();
   assert.equal(await page.locator('.r-work-area').getAttribute('data-mobile-view'),'chat');
   assert.equal(await page.locator('#main-workspace').isVisible(),false);
   await page.locator('#workspace-assistant-toggle').click();await page.locator('#main-workspace').waitFor();
   await page.waitForFunction(()=>document.activeElement?.id==='workspace-assistant-toggle');
   assert.equal(await page.locator('#workspace-assistant-toggle').getAttribute('aria-expanded'),'false');
   assert.equal(await page.locator('.r-mode-switcher').count(),0);
   result.checks.push({kind:'mobileAssistant',opensExplicitly:true,returnsToPage:true,returnsFocus:true});
  }
 }
 await page.setViewportSize({width:390,height:844});
 await page.emulateMedia({colorScheme:'dark',reducedMotion:'reduce'});
 await page.screenshot({path:path.join(out,'overview-390-dark.png'),fullPage:false});
 await page.setViewportSize({width:1440,height:960});
 const find=async route=>{await page.locator('.r-search').click();const dialog=page.getByRole('dialog');const before=await dialog.boundingBox();await dialog.getByRole('searchbox').fill(route);const target=dialog.locator('[data-finder-route="'+route+'"]');await target.waitFor();const after=await dialog.boundingBox();for(const key of ['x','y','width','height'])assert.ok(Math.abs(before[key]-after[key])<=1,'Finder geometry stays fixed while filtering: '+key);await target.click();await dialog.waitFor({state:'hidden'});await page.locator('.r-app[data-module="'+route+'"]').waitFor();};
 await find('operations');
 await page.locator('.r-cost-page input[name="price"]').waitFor();
 result.checks.push({kind:'routeTitle',overview:result.load.title,cost:await page.title(),visibleHeadings:await page.locator('.r-cost-page h1').allTextContents()});
 const field=page.locator('.r-cost-page input[name="price"]');
 await page.emulateMedia({forcedColors:'active'});
 const fieldStyle=()=>field.evaluate(e=>{const s=getComputedStyle(e);return{outline:s.outline,boxShadow:s.boxShadow,border:s.border,forcedColors:matchMedia('(forced-colors: active)').matches}});
 await field.evaluate(e=>e.blur());const unfocused=await fieldStyle();await field.focus();
 result.checks.push({kind:'forcedColorsInputFocus',unfocused,focused:await fieldStyle()});
 await page.emulateMedia({forcedColors:'none'});
 // A real drag starts inside the dialog and ends on its backdrop.
 await page.locator('.r-search').click();
 const dialog=page.getByRole('dialog');await dialog.getByRole('searchbox').fill('未完成的关键词');
 const rect=await dialog.boundingBox();
 await page.mouse.move(rect.x+rect.width/2,rect.y+40);await page.mouse.down();await page.mouse.move(8,8,{steps:8});await page.mouse.up();
 result.checks.push({kind:'dialogDragOut',openAfterInsidePressOutsideRelease:await page.getByRole('dialog').count()});
 if(await page.getByRole('dialog').count())await page.keyboard.press('Escape');
 // Test the original restock module in a blank document with synthetic API responses.
 const imePage=await context.newPage();await imePage.goto(origin+'/workspace?tab=overview&demo=true');
 await imePage.evaluate(()=>{document.body.innerHTML='<div id="audit-live"></div>';window.__auditSaves=[];});
 await imePage.addScriptTag({content:await readFile(path.join(root,'commerce/web/live-plan-ui.js'),'utf8')});
 result.checks.push({kind:'imeRestock',...await imePage.evaluate(async()=>{
  const data={candidates:[{key:'synthetic',product_id:'synthetic',type:'fbs',scope:'synthetic',available:10,observed_at:'2026-11-17T00:00:00Z',source_sha256:'a'.repeat(64),fresh:true}],plans:[]};
  const api=async(tool,args)=>{if(tool==='commerce_live_readiness')return{complete:0,total:0,checks:[],deliveries:[],notice:'synthetic'};if(tool==='commerce_live_restock_list')return data;if(tool==='commerce_live_restock_save'){window.__auditSaves.push(args);return{};}throw Error(tool)};
  let module;const repaint=()=>document.querySelector('#audit-live').innerHTML=module.render();
  module=window.CommerceLivePlans({api,repaint,toast:()=>{}});await module.load();module.select('synthetic');
  const input=document.querySelector('#live-plan-source_ref');input.value='未上屏的拼音';input.dispatchEvent(new Event('input',{bubbles:true}));
  input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
  const key=new KeyboardEvent('keydown',{key:'Enter',keyCode:229,isComposing:true,bubbles:true,cancelable:true});input.dispatchEvent(key);
  await new Promise(resolve=>setTimeout(resolve,10));
  return{isComposing:key.isComposing,keyCode:key.keyCode,prevented:key.defaultPrevented,saveCalls:window.__auditSaves.length};
 })});
 await imePage.close();
 await find('memory');await page.locator('.r-page:visible').first().waitFor();
 result.checks.push({kind:'memoryInputs',inputs:await page.locator('main input').evaluateAll(es=>es.filter(e=>e.getClientRects().length).map(e=>({type:e.type,placeholder:e.placeholder,label:e.labels?.[0]?.textContent||e.getAttribute('aria-label')})))});
 await page.getByRole('button',{name:'设置',exact:true}).click();
 const settings=page.getByRole('dialog');
 await settings.locator('summary').focus();
 const before=await settings.evaluate(e=>({active:document.activeElement.outerHTML,controls:[...e.querySelectorAll('button,input,select,summary')].map(c=>({tag:c.tagName,text:c.textContent,id:c.id,rects:c.getClientRects().length,visible:c.checkVisibility(),tabIndex:c.tabIndex,disabled:c.disabled}))}));
 const trace=[];for(let i=0;i<3;i++){await page.keyboard.press('Tab');trace.push(await page.evaluate(()=>({tag:document.activeElement.tagName,id:document.activeElement.id,text:document.activeElement.textContent?.slice(0,70),inside:!!document.activeElement?.closest('dialog')})));}
 result.checks.push({kind:'dialogTabWrap',before,trace});
 await page.keyboard.press('Escape');
 result.checks.push({kind:'dialogEscape',closed:await page.getByRole('dialog').count()===0});
 await find('connections');
 const legacy=page.frameLocator('iframe[title="专业业务模块"]');await legacy.locator('.connections-root').waitFor();
 result.checks.push({kind:'connectionHelp',remainingHelp:await legacy.locator('[data-ui-help]').count(),headings:await legacy.locator('h2[title]').evaluateAll(es=>es.map(e=>({text:e.textContent,title:e.title,tabIndex:e.tabIndex}))),secondInstructionVisible:(await legacy.locator('body').innerText()).includes('保存连接不会代替授权范围核对')});
 // Reproduce the outer host's opaque iframe and nonce protocol, without a native app.
 const host=await context.newPage();
 await host.route(origin+'/audit-host',route=>route.fulfill({contentType:'text/html',body:'<button id="before">Host before</button><iframe title="Audit workspace" sandbox="allow-scripts allow-forms allow-downloads" style="width:1400px;height:850px"></iframe><button id="after">Host after</button>'}));
 await host.exposeFunction('auditInvoke',async(tool,args)=>{const r=await context.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}});if(!r.ok())throw Error('Synthetic invoke failed');return r.json();});
 await host.goto(origin+'/audit-host');
 const html=await(await context.request.get(origin+'/workspace')).text();
 await host.evaluate(html=>{const iframe=document.querySelector('iframe'),nonce='synthetic-modern-web-audit';window.addEventListener('message',async e=>{const m=e.data;if(e.source!==iframe.contentWindow||m?.nonce!==nonce||m?.type!=='commerce:call')return;try{const value=await window.auditInvoke(m.tool,m.arguments);iframe.contentWindow.postMessage({type:'commerce:result',nonce,id:m.id,result:value},'*');}catch{iframe.contentWindow.postMessage({type:'commerce:result',nonce,id:m.id,error:'synthetic_error'},'*');}});iframe.srcdoc=html.replaceAll('__COMMERCE_BRIDGE_NONCE__',nonce);},html);
 const frame=host.frameLocator('iframe');await frame.locator('.r-app').waitFor();await frame.getByRole('button',{name:'设置',exact:true}).click();
 const frameDialog=frame.getByRole('dialog');await frameDialog.locator('summary').focus();await host.keyboard.press('Tab');
 const forward={hostActive:await host.evaluate(()=>({tag:document.activeElement.tagName,id:document.activeElement.id})),frameActive:await frameDialog.evaluate(()=>({tag:document.activeElement.tagName,inside:!!document.activeElement.closest('dialog')}))};
 await frameDialog.getByRole('button',{name:'关闭弹窗'}).focus();await host.keyboard.press('Shift+Tab');
 const backward=await frameDialog.evaluate(()=>({tag:document.activeElement.tagName,text:document.activeElement.textContent,visible:document.activeElement.checkVisibility()}));
 await frameDialog.evaluate(()=>{HTMLElement.prototype.checkVisibility=undefined;});
 await frameDialog.locator('summary').focus();await host.keyboard.press('Tab');
 const fallback=await frameDialog.evaluate(()=>({inside:!!document.activeElement.closest('dialog'),text:document.activeElement.textContent}));
 result.checks.push({kind:'visibilityFallback',...fallback});
 result.checks.push({kind:'opaqueIframeDialogFocus',forward,backward});await host.close();
 const libraryPage=await context.newPage();await libraryPage.goto(origin+'/workspace?tab=memory&demo=true');
 const layeredSearch=libraryPage.getByRole('searchbox',{name:'关键词',exact:true});await layeredSearch.fill('synthetic');let layeredCalls=0;
 const layeredObserver=request=>{if(request.url().endsWith('/v1/invoke')&&request.postDataJSON()?.tool==='commerce_memory_search')layeredCalls++};libraryPage.on('request',layeredObserver);
 for(const values of [{isComposing:true,keyCode:13},{isComposing:false,keyCode:229}])await layeredSearch.evaluate((e,values)=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true,...values})),values);
 await libraryPage.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));assert.equal(layeredCalls,0);
 const layeredSent=libraryPage.waitForRequest(r=>r.url().endsWith('/v1/invoke')&&r.postDataJSON()?.tool==='commerce_memory_search');await layeredSearch.press('Enter');await layeredSent;assert.equal(layeredCalls,1);
 libraryPage.off('request',layeredObserver);result.checks.push({kind:'layeredMemoryIME',compositionCalls:0,ordinaryEnter:1});
 await libraryPage.getByRole('button',{name:'参考知识',exact:true}).click();
 await libraryPage.waitForFunction(()=>[...document.querySelectorAll('button')].some(e=>e.textContent==='刷新目录'&&!e.disabled));
 const knowledge=libraryPage.getByRole('searchbox',{name:'查找笔记',exact:true});
 let searches=0;const observe=request=>{if(request.url().endsWith('/v1/invoke')&&request.postDataJSON()?.tool==='commerce_knowledge_search')searches++;};libraryPage.on('request',observe);
 await knowledge.pressSequentially('synthetic');
 const typed=await knowledge.inputValue();
 const sent=libraryPage.waitForRequest(request=>request.url().endsWith('/v1/invoke')&&request.postDataJSON()?.tool==='commerce_knowledge_search',{timeout:4000}).catch(()=>null);
 await knowledge.press('Enter');const request=await sent;const ordinaryEnter=searches;
 await libraryPage.getByRole('button',{name:'搜索正文',exact:true}).waitFor();
 await knowledge.pressSequentially('-ime');const beforeIME=await knowledge.inputValue();
 await knowledge.evaluate(e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',keyCode:13,isComposing:true,bubbles:true,cancelable:true})));
 await libraryPage.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 result.checks.push({kind:'knowledgeIME',typed,beforeIME,whileComposing:searches-ordinaryEnter,ordinaryEnter,request:!!request});libraryPage.off('request',observe);
 const legacyTasks=await context.newPage();await legacyTasks.goto(origin+'/legacy?tab=tasks');
 await legacyTasks.locator('.app[data-workspace-tab="tasks"][data-view-ready="true"]').waitFor();
 await legacyTasks.locator('[data-action="new-task"]').first().click();const taskTitle=legacyTasks.locator('#task-title');await taskTitle.fill('合成输入法任务');
 let taskCreates=0;legacyTasks.on('request',r=>{if(r.url().endsWith('/v1/invoke')&&r.postDataJSON()?.tool==='commerce_task_create')taskCreates++});
 for(const values of [{isComposing:true,keyCode:13},{isComposing:false,keyCode:229}])await taskTitle.evaluate((e,values)=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true,...values})),values);
 await legacyTasks.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));assert.equal(taskCreates,0);assert.equal(await taskTitle.inputValue(),'合成输入法任务');
 await taskTitle.press('Enter');await legacyTasks.getByRole('dialog').waitFor({state:'hidden'});assert.equal(taskCreates,1);
 result.checks.push({kind:'legacyTaskIME',compositionCalls:0,ordinaryEnter:1});await legacyTasks.close();
 const {case_id:caseId}=JSON.parse(await readFile(path.join(work,'fixture.json'),'utf8'));
 await page.goto(origin+'/workspace?tab=workspace&case_id='+caseId+'&demo=true');
 const product=page.frameLocator('iframe[title="完整商品内容编辑"]');await product.locator('#pw-main[aria-busy="false"]').waitFor();
 assert.equal(await page.locator('#workspace-assistant-toggle').getAttribute('aria-expanded'),'false');
 await page.locator('#workspace-assistant-toggle').click();
 await page.locator('.r-shared-assistant[aria-busy="false"] #copilot-message').fill('synthetic-unsent-draft');
 assert.ok((await page.locator('.r-shared-assistant .copilot-context-label').textContent()).includes(caseId),'An explicitly opened assistant keeps the original product identity');
 const assistantBox=await page.locator('.r-shared-assistant').boundingBox(),businessBox=await page.locator('#main-workspace').boundingBox();
 assert.ok(assistantBox.x>=businessBox.x+businessBox.width-1,'An explicitly opened desktop assistant occupies the right side');
 result.checks.push({kind:'assistantPlacement',defaultCollapsed:true,rightSide:true});
 await product.locator('[data-pw-tab="cost"]').click();
 const originalFrame=await page.locator('iframe[title="完整商品内容编辑"]').getAttribute('srcdoc');
 await product.getByRole('button',{name:'编辑成本',exact:true}).click();
 const purchase=page.locator('.r-cost-page input[name="purchase_cost"]');await purchase.fill('34');
 await find('connections');await page.frameLocator('iframe[title="专业业务模块"]').locator('.connections-root').waitFor();await find('workspace');
 const preserved=(await page.locator('iframe[title="完整商品内容编辑"]').getAttribute('srcdoc'))===originalFrame;
 assert.equal(preserved,true,'Module navigation must preserve the decoded product frame');
 await page.locator('.r-shared-assistant[aria-busy="false"] #copilot-message').waitFor();assert.equal(await page.locator('#copilot-message').inputValue(),'synthetic-unsent-draft');
 await product.locator('[data-pw-tab="cost"]').click();await product.getByRole('button',{name:'编辑成本',exact:true}).click();
 assert.equal(await purchase.inputValue(),'34','The original bound cost form keeps unsaved input');
 result.checks.push({kind:'compressedProductDraft',preserved});
 await page.locator('#workspace-assistant-toggle').click();
 assert.equal(await page.locator('.r-shared-assistant:visible').count(),0);
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:900});
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  for(const [route]of [['orders','订单'],['products','库存'],['restock','补货计划'],['platforms','平台数据'],['live','Ozon 经营'],['connections','连接与授权'],['creative','创意工作室']]){
   await find(route);const child=page.frameLocator('iframe[title="专业业务模块"]');await child.locator('.app[data-workspace-tab="'+(route==='restock'?'operations':route)+'"][data-view-ready="true"]').waitFor();await child.getByRole('heading',{level:1}).first().waitFor();
   const fits=await child.locator('html').evaluate(e=>e.scrollWidth<=e.clientWidth+1)&&await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);
   assert.equal(fits,true,route+' must fit viewport '+width);result.checks.push({kind:'legacyRouteFit',route,width,fits,heading:await child.getByRole('heading',{level:1}).first().innerText()});
  }
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.external,[]);
 result.browser=await browser.version();result.completed=true;
}catch(e){result.fatal=e.stack;if(page){result.failureState=await page.evaluate(()=>({module:document.querySelector('.r-app')?.dataset.module,dialogs:[...document.querySelectorAll('dialog[open]')].map(e=>e.textContent?.slice(0,300))})).catch(()=>null);await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});}}
finally{
 if(browser)await browser.close();child.kill('SIGTERM');await stopped;await rm(work,{recursive:true,force:true});
 result.endHashes=await fingerprint();result.sourceStable=JSON.stringify(result.startHashes)===JSON.stringify(result.endHashes);
 await writeFile(path.join(out,'browser-results.json'),JSON.stringify(result,null,2)+'\n');
 const get=kind=>result.checks.find(check=>check.kind===kind);
 const requirements=[['Collapsed assistants leave the complete business width',result.checks.filter(c=>c.kind==='viewport').length===4&&result.checks.filter(c=>c.kind==='viewport').every(c=>c.assistantExpanded==='false'&&c.mainWidth>=c.workWidth-2)],['Explicit desktop assistant opens on the right',get('assistantPlacement')?.defaultCollapsed===true&&get('assistantPlacement')?.rightSide===true],['Mobile AI toggle returns to the business page and trigger',get('mobileAssistant')?.returnsToPage===true&&get('mobileAssistant')?.returnsFocus===true],['Additional memory/task shortcuts preserve IME confirmation',get('layeredMemoryIME')?.ordinaryEnter===1&&get('legacyTaskIME')?.ordinaryEnter===1],['Application paints before unused inline documents',get('progressiveInline')?.paintBeforeData===true&&get('progressiveInline')?.legacyDecodedAfterData===true],['Related order rejects a changed source and recovers',get('alertOrderContext')?.changedSourceRejected===true&&get('alertOrderContext')?.recovered===true],['IME composition does not save',get('imeRestock')?.saveCalls===0],['Folded details keep Tab inside iframe',get('opaqueIframeDialogFocus')?.forward.hostActive.tag==='IFRAME'],['Dragging from dialog does not close',get('dialogDragOut')?.openAfterInsidePressOutsideRelease===1],['Connection instructions remain accessible',get('connectionHelp')?.secondInstructionVisible===true],['Initial document below 5 MB',result.load?.navigation?.[0]?.encodedBodySize<5000000],['Route title follows current module',get('routeTitle')?.cost==='成本与定价 · Phone-Lab'],['Knowledge search ignores IME but submits ordinary Enter',get('knowledgeIME')?.whileComposing===0&&get('knowledgeIME')?.ordinaryEnter===1&&get('knowledgeIME')?.typed==='synthetic'],['Visibility fallback keeps iframe focus',get('visibilityFallback')?.inside===true],['Artifact stays stable during regression',result.sourceStable]];
 result.requirements=requirements.map(([name,passed])=>({name,passed}));
 await writeFile(path.join(out,'browser-results.json'),JSON.stringify(result,null,2)+'\n');
 if(requirements.some(([,passed])=>!passed)){process.exitCode=1;console.error('Regression failures: '+requirements.filter(([,passed])=>!passed).map(([name])=>name).join('; '));}
 if(result.fatal){await writeFile(path.join(out,'fixture-stderr.txt'),stderr);console.error(result.fatal);process.exitCode=1;}
 else console.log(JSON.stringify(result,null,2));
}
