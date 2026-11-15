// Real isolated HTTP, shared UI, actual media files and versioned receipts.
import assert from 'node:assert/strict';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const evidence=path.resolve(process.env.PRODUCT_MEDIA_QA_DIR||'.local/coordination/product-media-20261114');
const state=path.join(evidence,'preview-state'),origin='http://127.0.0.1:'+(process.env.COMMERCE_PORT||'38826');
await mkdir(evidence,{recursive:true});
let pw;try{pw=await import('playwright')}catch{for(const d of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',d,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(pw);
const browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const errors=[],checks=[];let page;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1080},acceptDownloads:true});
 await context.addCookies([{name:'commerce_session',value:(await readFile(path.join(state,'auth.token'),'utf8')).trim(),url:origin,httpOnly:true,sameSite:'Strict'}]);
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+'/product-workspace');await page.locator('.pw-object-header').waitFor();
 await page.locator('[data-pw-action=catalog]').click();await page.locator('.catalog-product').first().waitFor();
 await page.waitForFunction(()=>document.querySelector('.catalog-product img')?.naturalWidth>0);
 await page.locator('.catalog-product-title').first().click();await page.locator('.catalog-detail-header').waitFor();
 assert.match(await page.locator('.catalog-browser').textContent(),/货源与报价/);
 await page.locator('[data-catalog-import]').selectOption('reference_image');
 await page.locator('[data-catalog-action=creative]').click();await page.locator('.media-flow').waitFor();
 await page.locator('[data-creative-tab=brief]').click();await page.locator('#creative-name').fill('合成验收 · 产品图像视频');
 await page.locator('#creative-facts').fill('合成规格：容量500毫升 | synthetic:spec');
 await page.locator('[data-creative-action=save]').click();await page.locator('.creative-projects [aria-pressed=true]').waitFor();
 await page.locator('#creative-kind').selectOption('product_image');await page.locator('#creative-file').setInputFiles(path.join(state,'synthetic-upload.png'));
 await page.locator('[data-creative-action=upload]').click();await page.getByText('校验完成，素材已保存。',{exact:true}).waitFor();
 await page.locator('[data-creative-tab=workflow]').click();await page.locator('[data-media-reference]').first().check();
 for(const [k,v] of Object.entries({layout:'单一产品主体与清晰信息层级',elements:'产品、卖点、场景',style:'简洁真实',colors:'蓝白与产品本色',typography:'清晰字级',selling_points:'展示有依据的容量信息',shots:'使用场景、产品特写、操作演示',rhythm:'场景开头、细节、使用、收尾',adaptation:'围绕自己的500毫升容量安排信息',avoid:'不复制竞品标识或编造使用效果'}))await page.locator(`[data-media-field="analysis.${k}"]`).fill(v);
 await page.locator('[data-media-action=direction-save]').click();await page.locator('[data-media-action=create]').waitFor();
 await page.locator('[data-media-action=create]').click();await page.locator('[data-media-field="shot.0"]').waitFor();
 await page.locator('[data-media-field="shot.0"]').selectOption({label:'synthetic-upload.png'});
 await page.locator('[data-media-action=execute]').click();await page.locator('[data-media-action=preview]').waitFor({timeout:30000});
 await page.locator('[data-media-action=preview]').first().click();await page.waitForFunction(()=>document.querySelector('.creative-preview img')?.naturalWidth===1080);
 await page.locator('[data-media-field=reviewNote]').fill('合成验收：产品身份、卖点文字、版式与文件均已核对');await page.locator('[data-media-action=approve]').click();
 await page.getByText('已审阅通过',{exact:true}).waitFor();checks.push('catalog images/details/supply -> bound project -> reference direction -> actual PNG -> version review');
 await page.locator('[data-media-action=tab][data-tab=performance]').click();
 for(const [k,v] of Object.entries({period_start:'2026-11-01',period_end:'2026-11-08',source_ref:'synthetic:performance-report',impressions:'1000',clicks:'30',orders:'3',video_views:'1000',completed_views:'400'}))await page.locator(`[data-media-field="metric.${k}"]`).fill(v);
 await page.locator('[data-media-field="metric.request_id"]').selectOption({index:1});
 await page.locator('[data-media-action=metrics-save]').click();await page.getByText('synthetic:performance-report',{exact:true}).waitFor();
 await page.locator('[data-media-field=enabled]').check();await page.locator('[data-media-action=policy]').click();await page.getByText(/下次复查：/).waitFor();
 await page.locator('[data-media-action=review]').click();await page.locator('.media-review-report').first().waitFor();
 assert.match(await page.locator('.media-review-report').first().textContent(),/因果关系/);
 checks.push('actual metrics retain source/window/version; saved periodic policy and review recommendations');
 await page.locator('[data-media-action=tab][data-tab=production]').click();await page.locator('[data-media-field=kind]').selectOption('ugc_video');await page.locator('[data-media-action=create]').click();
 await page.locator('[data-media-field="shot.4"]').waitFor();assert.match(await page.locator('.media-flow').textContent(),/使用场景/);assert.match(await page.locator('.media-flow').textContent(),/产品特写/);
 for(let i=0;i<5;i++)await page.locator(`[data-media-field="shot.${i}"]`).selectOption({label:'synthetic-upload.png'});
 await page.locator('[data-media-action=execute]').click();await page.locator('[data-media-action=preview]').waitFor({timeout:90000});
 await page.locator('[data-media-action=preview]').first().click();await page.waitForFunction(()=>document.querySelector('.creative-preview video')?.readyState>=1,null,{timeout:30000});
 assert.ok(Math.abs(await page.locator('.creative-preview video').evaluate(v=>v.duration)-30)<.2);
 checks.push('UGC storyboard includes scenes, closeups and demonstration; actual five-shot 30-second draft plays');
 for(const theme of ['light','dark']){
  await page.locator('#pw-theme').selectOption(theme);await page.waitForFunction(t=>document.documentElement.dataset.theme===t,theme);
  for(const width of [1440,390]){
   await page.setViewportSize({width,height:1000});
   for(const tab of ['direction','production','performance']){
    await page.locator(`[data-media-action=tab][data-tab=${tab}]`).click();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${theme}/${width}/${tab}`);
    await page.screenshot({animations:'disabled',path:path.join(evidence,`media-${tab}-${theme}-${width}.png`)});
   }
  }
 }
 await page.setViewportSize({width:1440,height:1000});await page.locator('[data-pw-action=catalog]').click();await page.locator('.catalog-product-title').first().waitFor();await page.locator('.catalog-browser[aria-busy=false]').waitFor();await page.waitForFunction(()=>document.querySelector('.catalog-product img')?.naturalWidth>0);
 for(const theme of ['light','dark']){await page.locator('#pw-theme').selectOption(theme);await page.waitForFunction(t=>document.documentElement.dataset.theme===t,theme);for(const width of [1440,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({animations:'disabled',path:path.join(evidence,`catalog-${theme}-${width}.png`)})}}
 checks.push('1440/390 light/dark actual catalog and creative flow rendering without horizontal overflow');
 // Same product artifacts inside an opaque iframe and actual nonce API bridge.
 const html=await(await context.request.get(origin+'/product-workspace')).text();const host=await context.newPage();
 host.on('pageerror',e=>errors.push(e.message));await host.goto(origin+'/product-workspace');
 await host.exposeFunction('mediaInvoke',async(tool,args)=>{const r=await context.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}});const j=await r.json();if(!r.ok)throw Error(j.error);return j});
 await host.evaluate(html=>{document.body.innerHTML='<iframe sandbox="allow-scripts allow-downloads" title="opaque product" style="width:100%;height:900px"></iframe>';const f=document.querySelector('iframe'),nonce='synthetic-media-bridge';window.addEventListener('message',async ev=>{const m=ev.data;if(ev.source!==f.contentWindow||m.nonce!==nonce||m.type!=='commerce:call')return;try{const result=await window.mediaInvoke(m.tool,m.arguments);f.contentWindow.postMessage({type:'commerce:result',nonce,id:m.id,result},'*')}catch(error){f.contentWindow.postMessage({type:'commerce:result',nonce,id:m.id,error:error.message},'*')}});f.srcdoc=html.replace('{"embedded":false}','{"embedded":true,"bridge":true}').replaceAll('__COMMERCE_BRIDGE_NONCE__',nonce)},html);
 const frame=host.frameLocator('iframe');await frame.locator('.pw-object-header').waitFor();await frame.locator('[data-pw-action=catalog]').click();await frame.locator('.catalog-product-title').first().click();await frame.locator('[data-catalog-action=project]').first().click();await frame.locator('.media-flow').waitFor();
 assert.ok(await frame.locator('[data-media-action=tab]').count());checks.push('same catalog/project/creative artifacts operate through opaque iframe API bridge');
 await host.close();assert.deepEqual(errors,[]);
 await writeFile(path.join(evidence,'ui-result.json'),JSON.stringify({status:'passed',checks,errors,synthetic:true},null,2));console.log(JSON.stringify({status:'passed',checks}));
}catch(error){await page?.screenshot({path:path.join(evidence,'ui-failure.png')}).catch(()=>{});await writeFile(path.join(evidence,'ui-result.json'),JSON.stringify({status:'failed',message:error.message,checks,errors},null,2));console.error(error.message);process.exitCode=1}
finally{await browser.close()}
