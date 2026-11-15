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
await mkdir(path.join(root,'../.commerce-state/verification/workbench-quality'),{recursive:true});
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
let browser,page;const errors=[],checks=[];
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function waitFor(fn){await page.waitForFunction(fn,null,{timeout:15000})}
async function calculate(){await page.locator('#analysis-form button[type=submit]').click()}
try{
  let ready=false;for(let n=0;n<100;n++){try{const r=await fetch(origin+'/v1/invoke',{method:'POST',headers:{Authorization:'Bearer '+secret,'content-type':'application/json'},body:JSON.stringify({tool:'commerce_status',arguments:{},client:'test'})});if(r.ok){ready=true;break}}catch{}await delay(80)}assert.ok(ready);
  browser=await playwright.chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1080},acceptDownloads:true});page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/login?token='+secret);await page.goto(origin+'/legacy');await page.locator('.kpi-value').first().waitFor();await goToModule(page,'alerts');await waitFor(()=>document.querySelector('.ops-workspace')?.textContent.includes('没有导入数据时'));
  assert.match(await page.locator('.ops-workspace').textContent(),/平台同步未连接/);assert.match(await page.locator('.ops-workspace').textContent(),/运行中，每 60 秒/);
  checks.push('honest empty state and local clock separated from unconnected shop and phone notifications');
  await page.locator('[data-ops-action=demo]').click();await waitFor(()=>document.querySelector('.ops-workspace')?.textContent.includes('整箱建议 36 件'));
  assert.equal(await page.locator('.ops-alert-head').count(),4);
  await page.locator('[data-ops-action=ack]').first().click();await waitFor(()=>document.querySelector('.ops-workspace')?.textContent.includes('已阅 · 未确认处理'));await page.locator('[data-ops-action=refresh]').click();
  const firstDownload=page.waitForEvent('download');await page.locator('[data-ops-action=export]').click();const demoExport=JSON.parse(await readFile(await(await firstDownload).path(),'utf8'));assert.equal(demoExport.observations.length,2);assert.ok(demoExport.audit.some(x=>x.action==='acknowledged'));
  checks.push('demo order/pack/deadline/stock alerts, acknowledgement persists, evidence export');
  await page.locator('#ops-scope').selectOption('manual');await waitFor(()=>document.querySelector('.ops-workspace')?.textContent.includes('没有导入数据时'));
  const fill=async(k,v)=>page.locator('#ops-'+k).fill(v);
  for(const [k,v]of Object.entries({store_id:'Synthetic store',warehouse:'Synthetic warehouse',sku:'SYN-SKU',source_ref:'synthetic.csv row 1 <img onerror=alert(1)>',order_id:'SYN-ORDER',quantity:'2',observed_at:new Date().toISOString()}))await fill(k,v);
  await page.locator('#ops-status').selectOption('awaiting_packaging');await page.locator('#ops-record-form button[type=submit]').click();await waitFor(()=>document.querySelector('.ops-alert-head')?.textContent.includes('履约方式')||[...document.querySelectorAll('.ops-alert-head')].some(x=>x.textContent.includes('履约方式')));
  assert.equal(await page.locator('.ops-alert-head').count(),2);assert.equal(await page.locator('.ops-workspace img').count(),0);
  await page.locator('#ops-record-form button[type=submit]').click();await page.locator('.toast').filter({hasText:'没有重复提醒'}).waitFor();assert.equal(await page.locator('.ops-alert-head').count(),2);
  checks.push('manual record form, unknown fulfillment holds packaging, safe escaped source and idempotent resubmit');
  await page.locator('#ops-status').selectOption('cancelled');await fill('observed_at',new Date().toISOString());await page.locator('#ops-record-form button[type=submit]').click();await waitFor(()=>[...document.querySelectorAll('.ops-alert-head')].every(x=>x.textContent.includes('已由后续记录关闭')));
  checks.push('later cancellation closes pending order reminders');
  await page.locator('[data-ops-kind=stock]').click();
  for(const [k,v]of Object.entries({available:'10',sold_units:'60',window_days:'30',lead_time_days:'14',safety_days:'7',pack_size:'6',inbound_units:'0',observed_at:new Date().toISOString()}))await fill(k,v);
  await page.locator('#ops-record-form button[type=submit]').click();await waitFor(()=>document.querySelector('.ops-workspace')?.textContent.includes('整箱建议 36 件'));
  await fill('inbound_units','12');await fill('inbound_due_at',new Date(Date.now()+2*86400000).toISOString());await fill('observed_at',new Date().toISOString());await page.locator('#ops-record-form button[type=submit]').click();await waitFor(()=>document.querySelector('.ops-workspace')?.textContent.includes('整箱建议 24 件'));
  checks.push('stock form calculates 36 units; eligible timed inbound changes plan to 24 units');
  await goToModule(page,'operations');await page.locator('[data-analysis-example=cost]').click();await goToModule(page,'alerts');await page.locator('[data-ops-tab=campaign]').click();await page.locator('[data-ops-action=campaign-example]').click();await page.locator('#ops-campaign-form button[type=submit]').click();await waitFor(()=>document.querySelector('#ops-campaign-output')?.textContent.includes('19.8'));
  const table=await page.locator('#ops-campaign-output').textContent();assert.match(table,/33/);assert.match(table,/尚待核实/);assert.match(table,/低于目标/);
  await page.locator('[data-ops-scenario=inventory_state]').selectOption('tight');assert.equal(await page.locator('#ops-campaign-output table').count(),0);await page.locator('#ops-campaign-form button[type=submit]').click();await waitFor(()=>document.querySelector('#ops-campaign-output')?.textContent.includes('优先补货'));
  const campaignDownload=page.waitForEvent('download');await page.locator('[data-ops-action=campaign-export]').click();const bundle=JSON.parse(await readFile(await(await campaignDownload).path(),'utf8'));assert.equal(bundle.plans[0].contribution,33);assert.equal(bundle.plans[1].contribution,19.8);assert.equal(bundle.evidence.input_sha256.length,64);
  checks.push('price/discount/ads/affiliate scenarios, no double ad charge, tight-stock advice and input evidence');
  await page.locator('#ops-plan-0-affiliate_rate').fill('101');await page.locator('#ops-campaign-form button[type=submit]').click();await page.locator('#ops-campaign-output [role=alert]').waitFor();await page.locator('#ops-plan-0-affiliate_rate').fill('0');
  let held=false;const delayed=async route=>{const body=route.request().postDataJSON();if(body.tool==='commerce_campaign_compare'&&!held){held=true;const response=await route.fetch();await delay(500);await route.fulfill({response})}else await route.continue()};await page.route('**/v1/invoke',delayed);await page.locator('#ops-campaign-form button[type=submit]').click();await page.locator('#ops-plan-0-price').fill('120');await delay(700);assert.equal(await page.locator('#ops-campaign-output table').count(),0);assert.doesNotMatch(await page.locator('#ops-campaign-output').textContent(),/正在比较/);await page.unroute('**/v1/invoke',delayed);
  checks.push('invalid affiliate rate visible; edited plan withdraws delayed calculation');
  for(const section of ['alerts','campaign']){await page.locator(`[data-ops-tab=${section}]`).click();for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow ${section} ${width}`)}}
  checks.push('alerts and campaign views fit 1440/1024/768/390');
  await page.setViewportSize({width:1440,height:1080});await page.locator('[data-ops-tab=alerts]').click();await page.screenshot({path:path.join(root,'../.commerce-state/verification/workbench-quality/operations-alerts.png')});
  assert.deepEqual(errors,[]);const result={status:'passed',synthetic:true,backend:'isolated real HTTP service',external_notifications_sent:false,checks,errors};await writeFile(path.join(root,'qa/operations-ui-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){await writeFile(path.join(root,'qa/operations-ui-result.json'),JSON.stringify({status:'failed',synthetic:true,error:error.message,checks,errors},null,2));if(page)await page.screenshot({path:path.join(root,'../.commerce-state/verification/workbench-quality/operations-diagnostic.png')}).catch(()=>{});throw error}
finally{await browser?.close();server.kill('SIGTERM');await delay(200);await rm(temp,{recursive:true,force:true})}
