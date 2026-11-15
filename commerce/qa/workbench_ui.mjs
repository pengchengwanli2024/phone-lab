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
  const context=await browser.newContext({viewport:{width:1920,height:1080},acceptDownloads:true});page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/login?token='+secret);await page.goto(origin+'/legacy');await page.locator('.kpi-value').first().waitFor();
  await goToModule(page,'operations');await calculate();
  await waitFor(()=>document.querySelector('#analysis-output').textContent.includes('请补全：币种'));
  assert.equal(await page.locator('[data-metric=contribution]').count(),0);
  checks.push('blank cost inputs return HOLD instead of zero');
  await page.locator('[data-analysis-example=cost]').click();await calculate();
  await waitFor(()=>document.querySelector('[data-metric=contribution]')?.textContent.includes('38'));
  assert.match(await page.locator('[data-metric=contribution-rate]').textContent(),/38%/);
  const downloadPromise=page.waitForEvent('download');await page.locator('[data-action=analysis-export]').click();const downloaded=await downloadPromise;
  const evidence=JSON.parse(await readFile(await downloaded.path(),'utf8'));assert.equal(evidence.evidence.input.commission_rate,.1);assert.equal(evidence.contribution,38);assert.equal(evidence.evidence.input_sha256.length,64);
  checks.push('percentage conversion, live calculation, provenance JSON download');
  await page.locator('#analysis-purchase_cost').fill('0');assert.equal(await page.locator('[data-metric=contribution]').count(),0);await calculate();
  await waitFor(()=>document.querySelector('[data-metric=contribution]')?.textContent.includes('68'));
  await page.locator('#analysis-commission_rate').fill('101');await calculate();assert.equal(await page.locator('[aria-invalid=true]').count(),1);assert.equal(await page.locator('[data-metric=contribution]').count(),0);
  await page.locator('#analysis-commission_rate').fill('10');await page.locator('#analysis-purchase_cost').fill('');await calculate();await waitFor(()=>document.querySelector('#analysis-output').textContent.includes('采购成本'));
  checks.push('explicit zero, invalid rate, missing value, edit withdraws stale result');
  await page.locator('[data-analysis-example=cost]').click();
  let held=false;const routeHandler=async route=>{const body=route.request().postDataJSON();if(body.tool==='commerce_unit_economics'&&!held){held=true;const response=await route.fetch();await delay(500);await route.fulfill({response})}else await route.continue()};
  await page.route('**/v1/invoke',routeHandler);await calculate();await page.locator('#analysis-price').fill('200');await delay(650);assert.equal(await page.locator('[data-metric=contribution]').count(),0);await page.unroute('**/v1/invoke',routeHandler);
  await goToModule(page,'orders');await goToModule(page,'operations');assert.equal(await page.locator('#analysis-price').inputValue(),'200');
  checks.push('late response cannot restore result after input edit; navigation preserves input');
  await page.locator('[data-analysis-mode=stock]').click();await page.locator('[data-analysis-example=stock]').click();await calculate();
  await waitFor(()=>document.querySelector('[data-metric=suggested-qty]')?.textContent==='36 件');assert.equal(await page.locator('[data-metric=days-cover]').textContent(),'5 天');
  await page.locator('#analysis-sold_units').fill('0');await calculate();await waitFor(()=>document.querySelector('#analysis-output').textContent.includes('观察期内没有销量'));assert.equal(await page.locator('[data-metric=suggested-qty]').count(),0);
  checks.push('actual-window restock and pack rounding; no-demand HOLD');
  await goToModule(page,'connections');await page.locator('#knowledge-query').fill('补货');await page.locator('#knowledge-query').press('Enter');
  await page.locator('.knowledge-hits button').waitFor();assert.match(await page.locator('.knowledge-hits').textContent(),/Inventory.md/);assert.equal(await page.locator('.knowledge-hits img').count(),0);
  await page.locator('.knowledge-hits button').click();await page.locator('.dialog pre').waitFor();assert.match(await page.locator('.dialog').textContent(),/SHA-256/);await page.keyboard.press('Escape');
  await page.locator('#knowledge-query').fill('zzzz-no-match');assert.equal(await page.locator('.knowledge-hits').count(),0);await page.locator('#knowledge-query').press('Enter');await waitFor(()=>document.querySelector('#knowledge-output').textContent.includes('没有找到'));
  checks.push('Chinese finds English note, escaped excerpt, original and SHA-256, no-match state');
  const errorRoute=async route=>{if(route.request().postDataJSON().tool==='commerce_knowledge_search')await route.fulfill({status:503,json:{error:'synthetic_temporarily_unavailable'}});else await route.continue()};
  await page.route('**/v1/invoke',errorRoute);await page.locator('#knowledge-query').fill('库存');await page.locator('#knowledge-query').press('Enter');await page.locator('#knowledge-output [role=alert]').waitFor();await page.unroute('**/v1/invoke',errorRoute);
  checks.push('search service error has recoverable visible state');
  await goToModule(page,'research');await page.locator('[data-collection-meta=market]').waitFor();
  for(const platform of ['ozon','tiktok','amazon','mercado','temu']){await page.locator('#collection-platform').selectOption(platform);await page.waitForFunction(p=>document.querySelector('#collection-platform')?.value===p&&!!document.querySelector(`[data-collection-field="${p==='amazon'?'asin':p==='mercado'?'item_id':p==='temu'?'goods_id':'product_id'}"]`),platform)}
  await page.locator('#collection-platform').selectOption('research');await page.locator('[data-collection-field=subject][data-part=original]').waitFor();
  await page.locator('[data-action=collection-check]').click();await waitFor(()=>document.querySelector('#collection-feedback').textContent.includes('待处理'));
  await page.locator('[data-action=collection-final]').click();assert.match(await page.locator('#collection-feedback').textContent(),/待处理/);
  checks.push('five platform templates; missing evidence/translation blocks formal export');
  const fill=async(key,value)=>page.locator(`[data-collection-meta=${key}]`).fill(value);
  await fill('market','US');await fill('language','en');await fill('source_url','https://example.com/research');await fill('captured_at','2026-11-01T00:00:00Z');await fill('raw_excerpt','Synthetic research. Price 12.99 USD. Not waterproof.');
  const values=[['subject','Synthetic research.','合成调研。'],['findings','Price 12.99 USD.','价格 12.99 USD。'],['limitations','Not waterproof.','不防水。']];
  for(const [key,original,zh]of values){await page.locator(`[data-collection-field=${key}][data-part=original]`).fill(original);await page.locator(`[data-collection-field=${key}][data-part=zh]`).fill(zh);await page.locator(`[data-collection-field=${key}][data-part=locator]`).fill('Synthetic source paragraph');await page.locator(`[data-collection-field=${key}][data-part=reviewed]`).check()}
  await page.locator('[data-action=collection-check]').click();await waitFor(()=>document.querySelector('#collection-feedback').textContent.includes('检查通过'));
  const researchDownload=page.waitForEvent('download');await page.locator('[data-action=collection-final]').click();const researchFile=await researchDownload;const bundle=JSON.parse(await readFile(await researchFile.path(),'utf8'));assert.equal(bundle.status,'REVIEWED_RESEARCH');assert.equal(bundle.record.fields.findings.zh,'价格 12.99 USD。');assert.equal(bundle.raw_excerpt_sha256.length,64);
  checks.push('bilingual reviewed research export includes exact original, source and hash manifest');
  await page.locator('[data-collection-field=findings][data-part=zh]').fill('价格 1299 USD。');assert.equal(await page.locator('[data-collection-field=findings][data-part=reviewed]').isChecked(),false);await page.locator('[data-action=collection-check]').click();await waitFor(()=>document.querySelector('#collection-feedback').textContent.includes('数字或百分数'));
  checks.push('translation edits invalidate review; numeric drift visibly blocks completion');
  // Reproduce already-open Harness windows with the original no-forms sandbox.
  const legacy=await context.newPage();legacy.on('pageerror',e=>errors.push(e.message));
  await legacy.route(origin+'/legacy',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><iframe title="legacy" sandbox="allow-scripts allow-downloads" style="width:100%;height:950px"></iframe>'}));
  await legacy.exposeFunction('invokeLegacy',async(tool,args)=>{const response=await fetch(origin+'/v1/invoke',{method:'POST',headers:{Authorization:'Bearer '+secret,'content-type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'test'})});const body=await response.json();if(!response.ok)throw Error(body.error);return body});
  await legacy.goto(origin+'/legacy');const html=await(await page.request.get(origin+'/legacy')).text();
  await legacy.evaluate(html=>{const frame=document.querySelector('iframe'),nonce='synthetic-legacy';window.addEventListener('message',async event=>{const m=event.data;if(event.source!==frame.contentWindow||m?.type!=='commerce:call'||m.nonce!==nonce)return;try{const result=await window.invokeLegacy(m.tool,m.arguments);frame.contentWindow.postMessage({type:'commerce:result',nonce,id:m.id,result},'*')}catch(error){frame.contentWindow.postMessage({type:'commerce:result',nonce,id:m.id,error:error.message},'*')}});frame.srcdoc=html.replaceAll('__COMMERCE_BRIDGE_NONCE__',nonce)},html);
  const old=legacy.frameLocator('iframe');await old.locator('.kpi-value').first().waitFor();await goToModule(old,'operations');await old.locator('[data-analysis-example=cost]').click();await old.locator('#analysis-form button[type=submit]').click();await old.locator('[data-metric=contribution]').waitFor();assert.match(await old.locator('[data-metric=contribution]').textContent(),/38/);
  await goToModule(old,'connections');await old.locator('#knowledge-query').fill('补货');await old.locator('#knowledge-query').press('Enter');await old.locator('.knowledge-hits button').waitFor();await legacy.close();
  checks.push('existing no-forms sandbox supports calculator click and search Enter through bridge');
  for(const tab of ['operations','connections','research']){await page.setViewportSize({width:1440,height:1000});await goToModule(page,tab);for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${tab} overflow ${width}`)}}
  checks.push('new views fit 1440/1024/768/390 without page overflow');
  await page.setViewportSize({width:1920,height:1080});await goToModule(page,'operations');await page.locator('[data-analysis-mode=cost]').click();await page.locator('[data-analysis-example=cost]').click();await calculate();await page.locator('[data-metric=contribution]').waitFor();await page.screenshot({path:path.join(root,'../.commerce-state/verification/workbench-quality/workbench-cost.png')});
  assert.deepEqual(errors,[]);const result={status:'passed',synthetic:true,backend:'isolated actual HTTP service',translation_provider:'tested separately; not invoked by this browser suite',checks,errors};await writeFile(path.join(root,'qa/workbench-ui-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){await writeFile(path.join(root,'qa/workbench-ui-result.json'),JSON.stringify({status:'failed',synthetic:true,error:error.message,checks,errors},null,2));if(page)await page.screenshot({path:path.join(root,'../.commerce-state/verification/workbench-quality/workbench-diagnostic.png')}).catch(()=>{});throw error}
finally{await browser?.close();server.kill('SIGTERM');await delay(200);await rm(temp,{recursive:true,force:true})}
