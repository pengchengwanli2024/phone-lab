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

const out=path.join(root,'../.commerce-state/verification/workbench-quality');await mkdir(out,{recursive:true});
const checks=[],errors=[],delay=ms=>new Promise(r=>setTimeout(r,ms));let browser,page;
async function api(tool,args={}){const r=await fetch(origin+'/v1/invoke',{method:'POST',headers:{Authorization:'Bearer '+secret,'content-type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'test'})});assert.equal(r.ok,true,tool);return r.json()}
async function nav(tab){await goToModule(page,tab)}
async function idle(){await page.waitForFunction(()=>!document.querySelector('.ui-load-state'))}
try{
 for(let n=0;n<100;n++){try{const r=await fetch(origin+'/v1/health',{headers:{Authorization:'Bearer '+secret}});if(r.ok)break}catch{}await delay(100)}
 browser=await playwright.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1440,height:1050},acceptDownloads:true});page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+'/login?token='+secret);await page.goto(origin+'/legacy');await page.locator('.kpi-value').first().waitFor();
 const modules=await page.locator('.tabs [data-tab]').evaluateAll(nodes=>nodes.map(n=>({id:n.dataset.tab,label:n.textContent})));
 for(const m of modules){await nav(m.id);await page.waitForFunction(label=>document.querySelector('h1')?.textContent===label,m.id==='overview'?'经营总览':m.label);if(['platforms','agent','exposure','live','creative','skills','organization'].includes(m.id))assert.equal(await page.locator('.assistant').count(),0)}
 checks.push(`${modules.length} desktop modules reachable; specialized modules have no unrelated simulated assistant`);
 await page.setViewportSize({width:390,height:1050});
 for(const m of modules){await nav(m.id);assert.equal(await page.locator('#ui-module').inputValue(),m.id);await page.waitForFunction(label=>document.querySelector('h1')?.textContent===label,m.id==='overview'?'经营总览':m.label)}
 await nav('overview');await page.locator('#ui-module').focus();await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.dataset.action),'workspace-open');
  checks.push(`${modules.length} narrow modules; module selector and primary next action support keyboard focus traversal`);
 for(const width of [320,390,768,1024,1440,1920]){await page.setViewportSize({width,height:1050});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.ok(await page.locator('.kpi-value').evaluateAll(nodes=>nodes.every(e=>e.scrollWidth<=e.clientWidth+1&&e.getBoundingClientRect().right<=e.closest('.kpi').getBoundingClientRect().right-10)))}
 await page.emulateMedia({reducedMotion:'reduce'});assert.ok(await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches));
 checks.push('KPI numbers fit card bounds at 320/390/768/1024/1440/1920; reduced motion honored');
 if(modules.some(m=>m.id==='platforms')){
  const missing=async route=>{if(['commerce_platform_catalog','commerce_platform_list'].includes(route.request().postDataJSON().tool))return route.fulfill({status:400,json:{error:'unknown_tool'}});return route.continue()};
  await page.route('**/v1/invoke',missing);await nav('platforms');await page.locator('[role=alert]').filter({hasText:'当前共享后台尚未启用该功能'}).waitFor();await page.unroute('**/v1/invoke',missing);await nav('overview');
  checks.push('new module on older service has a readable not-enabled state instead of raw unknown_tool');
 }
 await page.setViewportSize({width:1440,height:1050});
 let fail=true;
 const scopeRoute=async route=>{const p=route.request().postDataJSON();if(p.tool==='commerce_dashboard'&&p.arguments.demo===false){await delay(500);if(fail)return route.fulfill({status:503,json:{error:'synthetic_scope_unavailable'}})}return route.continue()};
 await page.route('**/v1/invoke',scopeRoute);await page.selectOption('#store','ozon-demo');await idle();assert.match(await page.locator('.kpi-value').first().textContent(),/39,200/);
 await page.locator('#demo').uncheck();await page.locator('.ui-load-state').waitFor();assert.equal(await page.locator('.kpi-value').count(),0);assert.equal(await page.locator('#store').inputValue(),'all');
 await page.locator('[role=alert]').filter({hasText:'synthetic_scope_unavailable'}).waitFor();assert.equal(await page.locator('.kpi-value').count(),0);assert.equal(await page.locator('.assistant').count(),0);
 fail=false;await page.locator('[data-action=reload]').click();await idle();assert.equal(await page.locator('.kpi-value').first().textContent(),'—');assert.equal(await page.locator('[role=alert]').count(),0);
 await page.unroute('**/v1/invoke',scopeRoute);checks.push('scope change clears incompatible store and old numbers immediately; visible loading/error/retry recovers truthful live empty state');
 // Deliver an older live response after a newer demo response.
 let release,started;const held=new Promise(r=>release=r),seen=new Promise(r=>started=r);
 const late=async route=>{const p=route.request().postDataJSON();if(p.tool==='commerce_dashboard'&&p.arguments.demo===false){const response=await route.fetch();started();await held;return route.fulfill({response})}return route.continue()};
 await page.locator('#demo').check();await idle();await page.route('**/v1/invoke',late);await page.locator('#demo').uncheck();await seen;await page.locator('#demo').check();await idle();assert.match(await page.locator('.kpi-value').first().textContent(),/128,640/);release();await delay(200);assert.match(await page.locator('.kpi-value').first().textContent(),/128,640/);await page.unroute('**/v1/invoke',late);
 checks.push('late previous scope response cannot replace current data');
 await nav('tasks');await page.locator('[data-action=new-task]').first().click();await page.locator('[data-action=submit-task]').click();assert.equal(await page.locator('#task-title').getAttribute('aria-invalid'),'true');assert.equal(await page.locator('#task-title').evaluate(e=>e===document.activeElement),true);
 await page.locator('#task-title').fill('Synthetic keyboard task');await page.locator('#task-title').press('Enter');await page.waitForFunction(()=>!document.querySelector('.dialog'));await page.getByText('Synthetic keyboard task',{exact:true}).first().waitFor();
 assert.equal((await api('commerce_task_list')).tasks.filter(t=>t.input?.title==='Synthetic keyboard task').length,1);
 await page.locator('[data-action=new-task]').first().focus();await page.locator('[data-action=new-task]').first().click();
 const first=page.locator('.dialog button').first(),last=page.locator('.dialog button').last();await first.focus();await page.keyboard.press('Shift+Tab');assert.equal(await last.evaluate(e=>e===document.activeElement),true);await page.keyboard.press('Tab');assert.equal(await first.evaluate(e=>e===document.activeElement),true);await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement?.dataset.action),'new-task');
 checks.push('task validation, keyboard submit, dialog Tab cycle, Escape and trigger focus restore');
 const statuses=['queued','running','completed','failed','interrupted','cancelled','future_status'];
 const statusRoute=async route=>{if(route.request().postDataJSON().tool!=='commerce_task_list')return route.continue();const r=await route.fetch(),j=await r.json(),base=j.tasks[0];return route.fulfill({response:r,json:{...j,tasks:statuses.map((status,i)=>({...base,id:'synthetic-status-'+i,status,input:{title:'Synthetic status '+status}}))}})};
 await page.route('**/v1/invoke',statusRoute);await page.locator('[data-action=runtime-refresh]').click();await idle();
 const tones=['blue','blue','success','danger','warning','gray','gray'];
 for(let i=0;i<statuses.length;i++){const row=page.locator('.task-row').filter({hasText:'Synthetic status '+statuses[i]});assert.equal(await row.locator('.ui-badge').getAttribute('data-ui-tone'),tones[i]);if(statuses[i]==='future_status'){assert.match(await row.textContent(),/状态未知/);assert.equal(await row.locator('[data-action=cancel-task],[data-action=execute-task],[data-action=task-retry]').count(),0)}}
 await page.unroute('**/v1/invoke',statusRoute);checks.push('actual task rows use separate success/failure/interrupted/unknown status semantics; unknown state has no implied actions');
 await nav('tasks');let creates=0;
 const delayedCreate=async route=>{if(route.request().postDataJSON().tool==='commerce_task_create'){creates++;await delay(400)}return route.continue()};await page.route('**/v1/invoke',delayedCreate);
 await page.locator('[data-action=new-task]').first().click();await page.locator('#task-title').fill('Synthetic repeated submission');await page.locator('[data-action=submit-task]').evaluate(e=>{e.click();e.click()});await page.waitForFunction(()=>!document.querySelector('.dialog'));await idle();assert.equal(creates,1);await page.unroute('**/v1/invoke',delayedCreate);
 await nav('insights');await page.locator('.business-root').waitFor();assert.equal(await page.locator('#business-mode').inputValue(),'real');await nav('support');await page.locator('.business-root').waitFor();assert.match(await page.locator('.business-root').textContent(),/尚未授权|未连接/);assert.equal(await page.locator('[data-action=support-draft]').count(),0);
 checks.push('repeated shared-task submission creates one task; review/support now use explicit source-backed real-input panels rather than legacy example tasks');
 assert.deepEqual(errors,[]);const report={status:'passed',synthetic:true,external_operations:false,checks,errors};await writeFile(path.join(out,'interactions.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}catch(error){await writeFile(path.join(out,'interactions-failure-'+Date.now()+'.json'),JSON.stringify({status:'failed',synthetic:true,error:error.message,checks,errors},null,2));await page?.screenshot({path:path.join(out,'interaction-failure.png')}).catch(()=>{});throw error}
finally{await browser?.close();server.kill('SIGTERM');await delay(300);await rm(temp,{recursive:true,force:true})}
