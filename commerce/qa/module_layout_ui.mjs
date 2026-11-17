// Real local UI coverage. All business data belongs to an isolated test state.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile,readdir,mkdir,mkdtemp,writeFile,rm} from 'node:fs/promises';
import {homedir,tmpdir} from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath,pathToFileURL} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.resolve(process.env.QA_OUTPUT_DIR||path.join(root,'../.local/coordination/module-layout-20261116/browser'));
const auditOnly=process.env.QA_AUDIT_ONLY==='1';
const routes=['overview','store-ops','workspace','pilots','listing','research','insights','operations','workflow','orders','order-imports','products','restock','support','alerts','live','platforms','creative','intelligence','exposure','phones','tasks','organization','agent','skills','assistant-team','models','connections','memory'];
const selectedRoutes=process.env.QA_ROUTES?process.env.QA_ROUTES.split(','):routes;
const sizes=process.env.QA_WIDTHS?process.env.QA_WIDTHS.split(',').map(Number):[1440,1024,768,390,360];
const themes=process.env.QA_THEMES?process.env.QA_THEMES.split(','):['light','dark'];
await mkdir(out,{recursive:true});
let pw;for(const id of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',id,'node_modules/playwright/index.mjs')).href);break}catch{}}
assert.ok(pw,'Existing Playwright runtime is required');
const state=await mkdtemp(path.join(tmpdir(),'commerce-module-layout-'));
const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
const origin=`http://127.0.0.1:${port}`;
const child=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'qa/react_workbench_fixture.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port),COMMERCE_QA_PAGE_CONTEXT:'1',COMMERCE_QA_INTEL:'1',COMMERCE_QA_LISTING_SCHEMA:'1',COMMERCE_QA_LAYOUT_QUESTIONS:process.env.QA_AGENT_RECORD==='1'?'1':'0'},stdio:['ignore','ignore','pipe']});
const closed=new Promise(resolve=>child.once('close',resolve));let logs='';child.stderr.on('data',b=>logs=(logs+String(b)).slice(-2500));
let browser,page;const errors=[],external=[],blocked=[],faults=[],coverage=[],checks=[];
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function invoke(tool,args={}){const response=await fetch(origin+'/v1/invoke',{method:'POST',headers:{authorization:'Bearer synthetic-workbench-preview','content-type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'test'})});assert.equal(response.status,200,tool);return response.json()}
async function settle(route){
 await page.locator('.r-app[data-module="'+route+'"]').waitFor();
 const legacy=page.locator('.r-legacy-container:not([hidden]) iframe');
 if(await legacy.count())await page.frameLocator('.r-legacy-container:not([hidden]) iframe').locator('.app[data-view-ready="true"]').waitFor();
 if(route==='workspace')await page.frameLocator('iframe[title="完整商品内容编辑"]').locator('#pw-main[aria-busy="false"]').waitFor();
 await page.waitForTimeout(100);
}
async function dimensions(frame){return frame.evaluate(()=>{
 const visible=el=>el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
 const intentional=el=>{for(let p=el.parentElement;p&&p!==document.body;p=p.parentElement){const s=getComputedStyle(p);if(['auto','scroll','hidden','clip'].includes(s.overflowX)&&p.scrollWidth>p.clientWidth+1)return true}return false};
 const containers=[...document.querySelectorAll('.r-main,.main-scroll,.pw-main,.r-business-nav,.r-section-tabs,.r-page,.ui-dialog,.r-dialog')].filter(visible).map(el=>({selector:el.className,width:Math.round(el.clientWidth),scroll:Math.round(el.scrollWidth)}));
 const offscreen=[...document.querySelectorAll('h1,h2,h3,label,button,select,input,textarea,pre,table')].filter(visible).filter(el=>{const r=el.getBoundingClientRect();return (r.right>innerWidth+2||r.left < -2)&&!intentional(el)}).slice(0,12).map(el=>({tag:el.tagName,class:el.className,text:(el.getAttribute('aria-label')||el.textContent||'').trim().slice(0,65),left:Math.round(el.getBoundingClientRect().left),right:Math.round(el.getBoundingClientRect().right)}));
 const tables=[...document.querySelectorAll('.ui-table,.table-wrap,.r-table-wrap')].filter(visible).filter(w=>w.querySelector(':scope>table')).map(w=>{const t=w.querySelector(':scope>table');return {width:w.clientWidth,scroll:Math.max(w.scrollWidth,t.scrollWidth),mode:w.dataset.uiTableMode||'original',rows:t.tBodies[0]?.rows.length||0}});return {viewport:innerWidth,document:document.documentElement.scrollWidth,containers,offscreen,tables};
})}
async function measure(route,width,theme){
 const documents=[];
 for(const frame of page.frames()){
  if(frame!==page.mainFrame()&&!(await(await frame.frameElement()).isVisible()))continue;
  documents.push(await dimensions(frame));
 }
 const problems=documents.flatMap((doc,i)=>[...(doc.document>doc.viewport+1?[`document ${i}: ${doc.document}/${doc.viewport}`]:[]),...doc.containers.filter(c=>c.scroll>c.width+1).map(c=>`container ${i} ${c.selector}: ${c.scroll}/${c.width}`)]);
 if(process.env.QA_TABLES==='1')for(const [i,doc] of documents.entries())for(const t of doc.tables)if(t.scroll>t.width+1)problems.push(`table ${i}: ${t.scroll}/${t.width}`);
 const screenshot=`${route}-${width}-${theme}.png`;
 if(process.env.QA_SCREENSHOTS!=='0')await page.screenshot({path:path.join(out,screenshot),animations:'disabled'});
 const row={route,width,theme,documents,problems,screenshot};coverage.push(row);
 console.log(JSON.stringify({route,width,theme,problems,offscreen:documents.reduce((n,d)=>n+d.offscreen.length,0)}));
}
try{
 let ready=false;for(let i=0;i<140;i++){try{if((await fetch(origin+'/v1/health',{headers:{authorization:'Bearer synthetic-workbench-preview'}})).ok){ready=true;break}}catch{}await pause(100)}assert.ok(ready,logs);
 const {case_id:caseId}=JSON.parse(await readFile(path.join(state,'fixture.json'),'utf8'));
 await invoke('commerce_task_create',{idempotency_key:'module-layout-long-title',kind:'analysis',input:{title:'合成验收 · '+ '跨模块长标题与完整来源核对'.repeat(6)+' SYNTHETIC_'+ 'x'.repeat(180),demo:true,organization_case:caseId}});
 let agentRecord;
 if(process.env.QA_AGENT_RECORD==='1'){
  agentRecord=await invoke('commerce_agent_start',{question:'合成布局验收：读取本机状态并询问缺少的目标时间范围。',role:'conductor',topic:'runtime',parameters:{},idempotency_key:'layout-agent-record'});
  for(let i=0;i<100&&['queued','running'].includes(agentRecord.status);i++){await pause(80);agentRecord=await invoke('commerce_agent_get',{run_id:agentRecord.id})}
  assert.equal(agentRecord.status,'awaiting_input','synthetic protocol fixture produces a saved question');
 }
 const manifest=await readFile(path.join(root,'web/workbench.sources.json'),'utf8');
 browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1440,height:960}});
 await context.route('**/*',route=>{
  const request=route.request(),url=request.url();
  if(!url.startsWith(origin+'/')&&!/^(about|data|blob):/.test(url)){external.push(new URL(url).origin);return route.abort()}
  if(url.includes('/phone/'))return route.fulfill({contentType:'application/json',body:JSON.stringify({devices:[],control_seconds:60,notice:'合成布局验收，无真实设备。'})});
  if(url.endsWith('/v1/invoke')){const tool=request.postDataJSON().tool;if(tool==='commerce_intel_live_refresh'){faults.push('synthetic_upstream_unavailable');return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'synthetic_upstream_unavailable'})})}if(/commerce_(copilot_send|agent_start|live_sync|live_open_setup|platform_open_setup|model_open_setup|platform_read|listing_.*submit|media_.*generate|creative_start|task_execute|phone_.*control)/.test(tool)){blocked.push(tool);return route.abort()}}
  return route.continue();
 });
 page=await context.newPage();page.setDefaultTimeout(20000);page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+'/login?token=synthetic-workbench-preview');
 for(const width of sizes)for(const theme of themes)for(const route of selectedRoutes){
  await page.setViewportSize({width,height:960});
  const caseParam=['workspace','listing','workflow','operations'].includes(route)?'&case_id='+caseId:'';
  await page.goto(origin+`/workspace?host=harness&tab=${route}&demo=true${caseParam}`);
  await page.locator('#react-theme').selectOption(theme);await page.waitForFunction(()=>!document.querySelector('#react-theme').disabled);
  await settle(route);
  if(route==='agent'&&!agentRecord){const agent=page.frameLocator('.r-legacy-container:not([hidden]) iframe');await agent.locator('#agent-submit:not([disabled])').waitFor();assert.notEqual(await agent.locator('[data-agent-composer]').getAttribute('open'),null,'an empty execution history starts with the analysis form open')}
  if(route==='agent'&&agentRecord){const agent=page.frameLocator('.r-legacy-container:not([hidden]) iframe');await agent.locator('.agent-history [data-agent-action="select"]').first().waitFor();const list=await agent.locator('.agent-history').boundingBox(),columns=await agent.locator('.agent-columns').boundingBox();assert.ok(Math.abs(list.width-columns.width)<3,'unselected history fills the available width');assert.ok(list.height<=660,'history stays within its scroll region');const row=agent.locator('.agent-history [data-agent-action="select"]').first();assert.ok(await row.getAttribute('title'),'the full question remains available');assert.deepEqual(await row.evaluate(el=>{const s=getComputedStyle(el);return [s.display,s.textAlign,s.textOverflow]}),['block','left','ellipsis'])}
  await measure(route,width,theme);
  if(route==='agent'&&agentRecord){const agent=page.frameLocator('.r-legacy-container:not([hidden]) iframe');await agent.locator('.agent-history [data-agent-action="select"]').first().click();await agent.locator('.agent-answer').waitFor();assert.equal(await agent.locator('.agent-columns').getAttribute('data-selected'),'true');await measure('agent-selected',width,theme)}
 }
 if(process.env.QA_DETAILS!=='0'){
  await page.setViewportSize({width:390,height:960});
  for(const theme of themes){
   await page.goto(origin+'/workspace?host=harness&tab=tasks&demo=true');await settle('tasks');await page.locator('#react-theme').selectOption(theme);
   const opener=page.getByRole('button',{name:'查看回执',exact:true}).first();await opener.click();await page.getByRole('dialog',{name:'任务与执行回执'}).waitFor();await measure('tasks-receipt',390,theme);await page.getByRole('dialog').getByRole('button',{name:'继续原工作',exact:true}).focus();const tail=await page.getByRole('dialog').getByRole('button',{name:'继续原工作',exact:true}).boundingBox(),box=await page.getByRole('dialog').boundingBox();assert.ok(tail.y+tail.height<=box.y+box.height,'dialog tail actions remain reachable');await page.getByRole('dialog').press('Escape');await page.getByRole('dialog').waitFor({state:'hidden'});assert.equal(await opener.evaluate(el=>el===document.activeElement),true,'task dialog returns focus to exact opener');
   await page.goto(origin+'/workspace?host=harness&tab=skills&demo=true');await settle('skills');await page.frameLocator('.r-legacy-container:not([hidden]) iframe').locator('[data-skills-action="open"]').first().click();await page.frameLocator('.r-legacy-container:not([hidden]) iframe').locator('#skills-detail').waitFor();await measure('skill-detail',390,theme);
   await page.goto(origin+'/workspace?host=harness&tab=connections&demo=true');await settle('connections');const legacy=page.frameLocator('.r-legacy-container:not([hidden]) iframe');await legacy.locator('[data-action="client-info"][data-client="codex"]').click();await legacy.getByRole('dialog').waitFor();await measure('connection-detail',390,theme);await legacy.getByRole('dialog').press('Escape');
   if(!auditOnly){
    await page.goto(origin+'/workspace?host=harness&tab=organization&demo=true');await settle('organization');const org=page.frameLocator('.r-legacy-container:not([hidden]) iframe'),extra=org.locator('[data-org-controls]');assert.equal(await extra.getAttribute('open'),null);await org.locator('#org-currency').fill('USD');await extra.locator('summary').click();assert.ok(await org.getByRole('button',{name:'导出当前看板',exact:true}).isVisible());await extra.locator('summary').press('Escape');assert.equal(await extra.getAttribute('open'),null);assert.equal(await org.locator('#org-currency').inputValue(),'USD');assert.ok(await extra.locator('summary').evaluate(el=>el===document.activeElement));await measure('organization-controls',390,theme);
    await page.goto(origin+'/workspace?host=harness&tab=skills&demo=true');await settle('skills');const nav=page.locator('.r-module-navigation');assert.ok(await nav.getByRole('button',{name:'能力库更多页面',exact:true}).isVisible());await nav.getByRole('button',{name:'能力库更多页面',exact:true}).click();const overflowItem=page.getByRole('menuitem').first(),overflowLabel=(await overflowItem.innerText()).trim();assert.equal(await nav.locator('>.r-module-link').count()+await page.getByRole('menuitem').count(),5,'every module remains reachable');await overflowItem.click();await nav.locator('>[aria-current=page]').filter({hasText:overflowLabel}).waitFor();assert.equal((await nav.locator('>[aria-current=page]').innerText()).trim(),overflowLabel);await nav.getByRole('button',{name:'能力库更多页面',exact:true}).click();await measure('module-overflow-menu-open',390,theme);await page.getByRole('menuitem').first().press('Escape');assert.ok(await nav.getByRole('button',{name:'能力库更多页面',exact:true}).evaluate(el=>el===document.activeElement));await measure('module-overflow-menu',390,theme);
   }
  }
  checks.push('Long task receipts, skill details and connection dialogs render at 390; receipt tail actions are reachable and Escape restores focus');
  if(!auditOnly)checks.push('Low-frequency organization controls preserve unsaved currency and Escape focus; More navigation reaches hidden modules and retains the active page');
  for(const route of ['/model-setup','/platform-setup','/setup','/phones'])for(const theme of themes){
   await invoke('commerce_ui_set_preferences',{theme});await page.goto(origin+route);await page.locator(route==='/phones'?'.r-phone-shell':'h1').waitFor();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await measure(route.slice(1),390,theme);
  }
  checks.push('Four auxiliary configuration/device pages render narrowly without saving configuration or controlling devices');
 }
 if(agentRecord){
  await page.setViewportSize({width:390,height:960});await page.goto(origin+'/workspace?host=harness&tab=agent&demo=true');await settle('agent');const agent=page.frameLocator('.r-legacy-container:not([hidden]) iframe');
  await agent.locator('.agent-history [data-agent-action="select"]').first().waitFor();assert.equal(await agent.locator('[data-agent-composer]').getAttribute('open'),null,'saved history is shown before the new-analysis form');
  await agent.locator('[data-agent-composer]>summary').click();await agent.locator('#agent-question').fill('合成未发送草稿');await agent.locator('#agent-question').press('Escape');assert.equal(await agent.locator('[data-agent-composer]').getAttribute('open'),null);await agent.locator('[data-agent-composer]>summary').click();assert.equal(await agent.locator('#agent-question').inputValue(),'合成未发送草稿');
  await agent.locator('#agent-question').press('Escape');await agent.locator('.agent-history [data-agent-action="select"]').first().click();await agent.getByRole('button',{name:'补充回答',exact:true}).click();assert.notEqual(await agent.locator('[data-agent-composer]').getAttribute('open'),null);assert.equal(await agent.locator('#agent-question').inputValue(),'');await agent.locator('#agent-question').press('Escape');assert.equal(await agent.locator('[data-agent-composer]').getAttribute('open'),null);await agent.getByRole('button',{name:'补充回答',exact:true}).click();assert.notEqual(await agent.locator('[data-agent-composer]').getAttribute('open'),null,'an explicit reply overrides a previously collapsed view snapshot');await measure('agent-reply',390,'light');
  checks.push('Existing execution history is visible first; disclosure keeps unsent input, and replying opens the original question form without sending');
 }
 if(process.env.QA_TABLES==='1'&&!auditOnly){
  await page.setViewportSize({width:390,height:960});await page.goto(origin+'/workspace?host=harness&tab=connections&demo=true');await page.locator('#react-theme').selectOption('light');await page.waitForFunction(()=>!document.querySelector('#react-theme').disabled);await settle('connections');
  const frame=page.frameLocator('.r-legacy-container:not([hidden]) iframe');const cell=frame.locator('[data-ui-table-preview]').first();await cell.waitFor();const original=(await cell.innerText()).trim(),originalCell=await cell.elementHandle();
  assert.equal(await frame.getByRole('button',{name:'配置 Ozon 与飞书',exact:true}).count(),1,'Shared connection setup retains one reachable entry');
  await cell.focus();await cell.press('Enter');const detail=frame.locator('dialog.ui-table-detail');await detail.waitFor();assert.ok((await detail.innerText()).includes(original),'Full source text is readable');assert.equal(await detail.locator('input,select,textarea').count(),0,'Read-only detail never duplicates editable controls');
  const close=detail.getByRole('button',{name:'关闭完整信息',exact:true});await close.press('Tab');assert.ok(await close.evaluate(el=>el===document.activeElement));await close.press('Escape');await detail.waitFor({state:'detached'});assert.ok(await cell.evaluate(el=>el===document.activeElement),'Escape returns to the originating cell');
  await cell.click();await detail.waitFor();await measure('table-complete-info',390,'light');await page.setViewportSize({width:1440,height:960});await page.waitForTimeout(150);await detail.getByRole('button',{name:'关闭完整信息',exact:true}).click();assert.ok(await originalCell.evaluate(el=>el===document.activeElement),'Closing after a resize restores the original cell');await frame.getByRole('button',{name:'刷新连接状态',exact:true}).focus();
  assert.equal(await frame.locator('[data-ui-table-mode=compact]').count(),0,'Wide containers return to the ordinary table');assert.equal(await originalCell.getAttribute('tabindex'),null,'Temporary cell tab stops are removed on wide screens');await measure('table-resize-wide',1440,'light');
  checks.push('Adaptive records include every field and original action; full information works with click/Enter, traps focus, returns focus on Escape and returns to wide tables without replacing nodes');
 }
 assert.equal(await readFile(path.join(root,'web/workbench.sources.json'),'utf8'),manifest,'Shared artifact changed while checking');
 const issues=coverage.filter(row=>row.problems.length);
 const result={status:issues.length||errors.length?'issues_found':'passed',coverage,issues:issues.map(({route,width,theme,problems})=>({route,width,theme,problems})),checks,errors,external,blocked,faults,synthetic:true,synthetic_model_record:!!agentRecord,real_model_calls:0,store_actions:0,device_actions:0};
 await writeFile(path.join(out,'verification.json'),JSON.stringify(result,null,2)+'\n');await writeFile(path.join(out,'tested-manifest.json'),manifest);
 console.log(JSON.stringify({status:result.status,cases:coverage.length,issues:issues.length,errors,external,blocked}));
 if(!auditOnly){assert.deepEqual(issues,[]);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(blocked,[])}
}catch(error){if(page)await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});await writeFile(path.join(out,'failure.json'),JSON.stringify({error:String(error),coverage,errors,external,blocked,logs},null,2));throw error}
finally{await browser?.close();child.kill('SIGTERM');await closed;await rm(state,{recursive:true,force:true})}
