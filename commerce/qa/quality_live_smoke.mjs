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
// Explicit loopback smoke: read-only navigation, no settings, queue or platform actions.
assert.ok(process.argv.includes('--local-readonly'));
const state=path.resolve(process.env.COMMERCE_STATE||path.join(root,'../.commerce-state'));
const origin='http://127.0.0.1:'+Number(process.env.COMMERCE_PORT||38731);
const secret=(await readFile(path.join(state,'auth.token'),'utf8')).trim();
const browser=await playwright.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const errors=[];let report;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1050}});await context.addCookies([{name:'commerce_session',value:secret,url:origin,httpOnly:true,sameSite:'Strict'}]);
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.name));await page.goto(origin+'/legacy');await page.locator('.kpi-value').first().waitFor();
 const moduleCount=await page.locator('.tabs [data-tab]').count();assert.ok(moduleCount>=17);
 await page.locator('#workspace-help').click();assert.equal(await page.locator('#dialog-title').textContent(),'数据与使用说明');await page.keyboard.press('Escape');await page.locator('#workspace-notices').click();assert.equal(await page.locator('#dialog-title').textContent(),'本机提醒中心');await page.keyboard.press('Escape');
 assert.equal(await page.evaluate(()=>CommerceUI.status('failed').tone),'danger');
 const catalog=await context.request.post(origin+'/v1/invoke',{data:{tool:'commerce_platform_catalog',arguments:{},client:'test'}}),platformAvailable=catalog.ok();
 if(!platformAvailable){await goToModule(page,'platforms');await page.locator('[role=alert]').filter({hasText:'当前共享后台尚未启用该功能'}).waitFor()}

 await page.setViewportSize({width:390,height:1050});await page.selectOption('#ui-module','connections');await page.locator('.integration').first().waitFor();assert.equal(await page.locator('h1').textContent(),'连接与知识');
 await page.locator('#workspace-module-search').click();await page.locator('#module-query').fill('cost');await page.locator('#module-query').press('Enter');await page.locator('#analysis-form').waitFor();assert.equal(await page.evaluate(()=>document.activeElement.id),'workspace-title');
 assert.equal(await page.locator('.mobile-nav button').count(),5);await page.locator('#mobile-mine').click();await page.locator('#workspace-my-theme').waitFor();await page.keyboard.press('Escape');
 const setup=await context.newPage();setup.on('pageerror',e=>errors.push(e.name));await setup.goto(origin+'/setup');await setup.locator('#ozon-client').waitFor();assert.equal(await setup.locator('#ozon-client').getAttribute('type'),'password');assert.equal(await setup.locator('#ozon-key').getAttribute('type'),'password');
 assert.deepEqual(errors,[]);report={status:'passed',scope:'existing loopback service, read-only browser navigation',module_count:moduleCount,new_platform_backend_available:platformAvailable,checks:['current module bundle renders','shared failure state visible to running service','narrow module navigation','running shared module finder search and focus','existing running setup page still renders masked credential controls'],mutations:false,server_restarted:false,errors};
 await writeFile(path.join(root,'../.commerce-state/verification/workbench-quality/live-smoke.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close()}
