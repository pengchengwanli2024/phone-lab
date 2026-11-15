import {goToModule} from './ui_navigation.mjs';
// Plain Playwright integration runner against isolated real commerce HTTP state.
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,readFile,readdir,rm} from 'node:fs/promises';
import {tmpdir,homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
let playwright;
try{playwright=await import(process.env.PLAYWRIGHT_MODULE||'playwright')}
catch{for(const cache of await readdir(path.join(homedir(),'.npm/_npx'))){try{playwright=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',cache,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(playwright,'Install Playwright or set PLAYWRIGHT_MODULE');
const temp=await mkdtemp(path.join(tmpdir(),'commerce-workbench-'));
const state=path.join(temp,'state'),notes=path.join(temp,'notes');await mkdir(state);await mkdir(notes);
const secret='synthetic-workbench-only';await writeFile(path.join(state,'auth.token'),secret);
await writeFile(path.join(state,'config.json'),JSON.stringify({knowledge_root:notes}));
await writeFile(path.join(notes,'Inventory.md'),'# Inventory\nRestock when stock is low. <img src=x onerror=alert(1)>');
const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
const origin=`http://127.0.0.1:${port}`;
const server=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'server.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port)},stdio:'ignore'});

const out=path.join(root,'../.commerce-state/verification/local-launch');await mkdir(out,{recursive:true});
let browser,page;const checks=[],errors=[],requests=[],delay=ms=>new Promise(r=>setTimeout(r,ms));
async function idle(){await page.waitForFunction(()=>!document.querySelector('.ui-load-state'))}
async function open(){await page.locator('#workspace-module-search').click();await page.locator('#module-query').waitFor();assert.equal(await page.locator('#module-query').evaluate(e=>e===document.activeElement),true)}
async function find(query){await page.locator('#module-query').fill(query)}
try{
 for(let n=0;n<100;n++){try{if((await fetch(origin+'/v1/health',{headers:{Authorization:'Bearer '+secret}})).ok)break}catch{}await delay(100)}
 browser=await playwright.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1440,height:1050},acceptDownloads:true});page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 await page.goto(origin+'/login?token='+secret);await page.goto(origin+'/legacy');await page.locator('.kpi-value').first().waitFor();await idle();
 await page.locator('#workspace-help').click();await page.getByRole('dialog').waitFor();assert.match(await page.locator('.dialog').textContent(),/合成示例数据/);await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.id),'workspace-help');
 const task=await(await page.request.post(origin+'/v1/invoke',{data:{tool:'commerce_task_create',arguments:{kind:'analysis',idempotency_key:'launch-notice-fixture',input:{title:'合成待办 <img src=x onerror=alert(1)>'}},client:'test'}})).json();
 await page.reload();await page.locator('.kpi-value').first().waitFor();await idle();await page.locator('#workspace-notices').click();await page.locator('.task-notice-list').waitFor();assert.match(await page.locator('.task-notice-list').textContent(),/合成待办/);assert.equal(await page.locator('.dialog img').count(),0);await page.locator('[data-action=workspace-open][data-target=alerts]').click();await page.locator('.ops-workspace').waitFor();assert.equal(await page.locator('h1').textContent(),'提醒与经营');
 const after=await(await page.request.post(origin+'/v1/invoke',{data:{tool:'commerce_task_get',arguments:{task_id:task.id},client:'test'}})).json();assert.equal(after.status,'queued');
 checks.push('data help is scoped and restores focus; notice center reads escaped queued tasks and opens real reminders without completing work');
 await page.setViewportSize({width:390,height:700});await page.locator('#mobile-mine').click();await page.locator('#workspace-my-theme').selectOption('dark');await page.waitForFunction(()=>!document.querySelector('#workspace-my-theme').disabled);assert.equal(await page.locator('#ui-theme').inputValue(),'dark');assert.equal(await page.evaluate(()=>document.documentElement.dataset.resolvedTheme),'dark');await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.id),'mobile-mine');
 await page.locator('#mobile-modules').click();await find('库存');await page.locator('[data-module-target=products]').click();assert.equal(await page.locator('#mobile-modules').getAttribute('aria-current'),'page');
 await page.locator('#mobile-agent').click();await page.locator('#agent-question').waitFor();assert.equal(await page.locator('h1').textContent(),'AI运营');await page.locator('#workspace-help').click();assert.match(await page.locator('.dialog').textContent(),/按自己的来源/);await page.keyboard.press('Escape');
 await page.locator('#mobile-tasks').click();await page.locator('#runtime-center').waitFor();await page.locator('#mobile-mine').click();
 const rejectTheme=async route=>{if(route.request().postDataJSON().tool==='commerce_ui_set_preferences')return route.fulfill({status:503,json:{error:'synthetic_theme_save_unconfirmed'}});return route.continue()};await page.route('**/v1/invoke',rejectTheme);await page.locator('#workspace-my-theme').selectOption('light');await page.waitForFunction(()=>!document.querySelector('#workspace-my-theme').disabled);assert.equal(await page.locator('#workspace-my-theme').inputValue(),'dark');assert.equal(await page.evaluate(()=>document.documentElement.dataset.resolvedTheme),'dark');await page.unroute('**/v1/invoke',rejectTheme);
 await page.locator('[data-action=workspace-open][data-target=connections]').click();await page.locator('#knowledge-query').waitFor();assert.equal(await page.locator('#mobile-mine').getAttribute('aria-current'),'page');
 await page.setViewportSize({width:390,height:500});assert.ok(await page.locator('.mobile-nav').evaluate(e=>e.getBoundingClientRect().bottom<=innerHeight+1));await page.locator('#mobile-overview').click();assert.equal(await page.locator('#mobile-overview').getAttribute('aria-current'),'page');assert.equal(await page.locator('.overview-attention th').count(),4);
 checks.push('five narrow navigation items work; local theme persists and rolls back on unconfirmed save; short viewport keeps navigation visible; attention table preserves actions');
 await page.setViewportSize({width:1440,height:1050});
 const modules=await page.locator('.tabs [data-tab]').count();await open();assert.equal(await page.locator('[data-module-target]').count(),modules);
 await page.screenshot({path:path.join(out,'finder-light.png')});
 await find('ＣＯＳＴ');assert.equal(await page.locator('[data-module-target]').count(),1);assert.equal(await page.locator('[data-module-target]').getAttribute('data-module-target'),'operations');
 await page.locator('#module-query').press('ArrowDown');assert.equal(await page.evaluate(()=>document.activeElement.dataset.moduleTarget),'operations');await page.keyboard.press('Enter');await page.locator('#analysis-form').waitFor();assert.equal(await page.locator('.dialog').count(),0);assert.equal(await page.evaluate(()=>document.activeElement.id),'workspace-title');
 checks.push('all current modules searchable, grouped and described; full-width Latin normalization, ArrowDown and Enter reach correct module with heading focus');
 await page.locator('#analysis-price').fill('42');await page.keyboard.press('Control+k');await page.locator('#module-query').waitFor();await find('库存');assert.ok(await page.locator('[data-module-target=products]').count());await find('unmatched-keyword');assert.equal(await page.locator('[data-module-target]').count(),0);assert.match(await page.locator('#module-results').textContent(),/没有匹配/);await page.locator('#module-query').press('Enter');assert.equal(await page.locator('.dialog').count(),1);
 await find('<img src=x onerror=alert(1)>');assert.equal(await page.locator('#module-results img').count(),0);await find('知识');await page.locator('#module-query').press('Enter');await page.locator('#knowledge-query').waitFor();
 await page.keyboard.press('Meta+k');await find('成本');await page.locator('#module-query').press('Enter');assert.equal(await page.locator('#analysis-price').inputValue(),'42');
 checks.push('Ctrl/Meta K, Chinese queries, escaped query, no-match Enter and unsent form preservation across finder navigation');
 await page.locator('#analysis-price').focus();await page.keyboard.press('Control+k');await page.keyboard.press('Escape');assert.equal(await page.locator('#analysis-price').evaluate(e=>e===document.activeElement),true);
 await goToModule(page,'tasks');await page.locator('[data-action=new-task]').first().click();await page.locator('#task-title').fill('Unsent synthetic draft');await page.keyboard.press('Control+k');assert.equal(await page.locator('#task-title').inputValue(),'Unsent synthetic draft');assert.equal(await page.locator('#module-finder').count(),0);await page.keyboard.press('Escape');
 checks.push('Escape restores original field; module shortcut does not replace an open business dialog');
 await goToModule(page,'overview');
 for(const theme of ['light','dark','system']){
  await page.emulateMedia({colorScheme:theme==='system'?'dark':'light'});await page.selectOption('#ui-theme',theme);await page.waitForFunction(()=>!document.querySelector('#ui-theme').disabled);
  for(const width of [1920,1440,1024,768,390,320]){
   await page.setViewportSize({width,height:1050});await delay(80);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${theme}/${width} page overflow`);
   assert.ok(await page.locator('.kpi-value').evaluateAll(nodes=>nodes.every(e=>e.scrollWidth<=e.clientWidth+1&&e.getBoundingClientRect().right<=e.closest('.kpi').getBoundingClientRect().right-10)),`${theme}/${width} KPI clipping`);
   if(width===1440)await page.screenshot({path:path.join(out,'implemented-'+theme+'.png'),fullPage:true});
   if(width===390)await page.screenshot({path:path.join(out,'implemented-narrow-'+theme+'.png'),fullPage:true});
   await open();assert.equal(await page.locator('[data-module-target]').count(),modules);
   const geometry=await page.locator('.dialog').evaluate(e=>({left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,width:innerWidth,height:e.getBoundingClientRect().height,viewport:innerHeight}));assert.ok(geometry.left>=0&&geometry.right<=geometry.width+1&&geometry.height<=geometry.viewport,`${theme}/${width} dialog fit`);
   await page.locator('#module-query').press('ArrowUp');assert.equal(await page.evaluate(()=>document.activeElement.dataset.moduleTarget),'connections');await page.keyboard.press('Home');assert.equal(await page.evaluate(()=>document.activeElement.dataset.moduleTarget),'overview');await page.keyboard.press('End');assert.equal(await page.evaluate(()=>document.activeElement.dataset.moduleTarget),'connections');
   if(width===390)await page.screenshot({path:path.join(out,'finder-narrow-'+theme+'.png')});await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.id),'workspace-module-search');
  }
 }
 checks.push('finder and overview fit 320/390/768/1024/1440/1920 in light/dark/system; system follows dark preference; ArrowUp/Home/End and repeated Escape restore focus');
 await page.setViewportSize({width:1440,height:1050});await open();const close=page.locator('.dialog button').first(),last=page.locator('.dialog-actions button').last();await close.focus();await page.keyboard.press('Shift+Tab');assert.equal(await last.evaluate(e=>e===document.activeElement),true);await page.keyboard.press('Tab');assert.equal(await close.evaluate(e=>e===document.activeElement),true);await page.keyboard.press('Escape');
 assert.ok(requests.every(url=>url.startsWith(origin)), 'No external runtime resources');assert.deepEqual(errors,[]);
 const result={status:'passed',synthetic:true,module_count:modules,checks,page_errors:errors,external_runtime_resources:false,external_business_operations:false};await writeFile(path.join(out,'interaction-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){await writeFile(path.join(out,'interaction-failure-'+Date.now()+'.json'),JSON.stringify({status:'failed',synthetic:true,error:error.message,checks,page_errors:errors},null,2));await page?.screenshot({path:path.join(out,'interaction-failure.png')}).catch(()=>{});throw error}
finally{await browser?.close();server.kill('SIGTERM');await delay(300);await rm(temp,{recursive:true,force:true})}
