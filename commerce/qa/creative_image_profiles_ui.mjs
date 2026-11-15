// Isolated HTTP and shared opaque iframe; creates plans only, never generations.
import assert from 'node:assert/strict';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const out=path.resolve(process.env.IMAGE_PROFILES_QA_DIR||'.local/qa/image-profiles');
const state=path.resolve(process.env.COMMERCE_STATE||path.join(out,'preview-state'));
const origin='http://127.0.0.1:'+(process.env.COMMERCE_PORT||'38871');
const fixture=JSON.parse(await readFile(path.join(state,'product-media-fixture.json'),'utf8'));
let pw;try{pw=await import('playwright')}catch{for(const d of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',d,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(pw);await mkdir(out,{recursive:true});
const browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const checks=[],errors=[];let page;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addCookies([{name:'commerce_session',value:(await readFile(path.join(state,'auth.token'),'utf8')).trim(),url:origin,httpOnly:true,sameSite:'Strict'}]);
 const api=async(tool,args={})=>{const r=await context.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}}),d=await r.json();assert.ok(r.ok(),JSON.stringify(d));return d};
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 const open=async()=>{
  await page.goto(origin+'/workspace?tab=workspace');const f=page.frameLocator('iframe').first();
  await f.locator('.pw-object-header').waitFor();await f.locator('[data-pw-action=catalog]').click();await f.locator('.catalog-product-title').first().click();await f.locator('[data-catalog-action=project]').first().click();await f.locator('[data-creative-tab=workflow]').click();return f;
 };
 let f=await open();await f.locator('[data-media-reference]').first().check();
 for(const k of ['layout','elements','style','colors','typography','selling_points','shots','rhythm','adaptation','avoid'])await f.locator(`[data-media-field="analysis.${k}"]`).fill('合成验收：独立图片，产品可见事实、场景及细节。');
 await f.locator('[data-media-action=direction-save]').click();await f.locator('[data-media-field=imageProfile]').waitFor();
 assert.equal(await f.locator('[data-media-field=imageProfile]').inputValue(),'ozon_ru');
 assert.equal(await f.locator('[data-media-field=imageRatio]').inputValue(),'3:4');
 assert.equal(await f.locator('[data-media-field=imageCount]').inputValue(),'6');
 await f.locator('[data-media-field=imageLabel]').fill('合成验收 · 刷头独立特写');
 await f.locator('[data-media-field=imageFocus]').fill('只展示原图可见的刷头结构。');
 assert.equal(await f.locator('[data-media-field=imageFocus]').getAttribute('maxlength'),'1000');
 await f.locator('#media-readiness-refresh').click();
 await f.locator('[data-media-action=create]:not([disabled])').waitFor();
 assert.equal(await f.locator('[data-media-field=imageFocus]').inputValue(),'只展示原图可见的刷头结构。');
 await f.locator('[data-media-action=create]').click();await f.locator('[data-media-field=request]').waitFor();
 let overview=await api('commerce_media_overview',{project_id:fixture.project_id}),r=overview.requests[0];
 assert.equal(r.spec.image_options.label,'合成验收 · 刷头独立特写');assert.equal(r.spec.image_options.set_size,6);assert.equal(r.spec.image_delivery.aspect_ratio,'3:4');assert.equal(r.spec.width,1536);assert.equal(r.external_generation_submitted,false);
 checks.push('Ozon RU defaults 6 independent images / 3:4; unsaved focus survives reread; server freezes exact options and no generation');
 f=await open();await f.locator('[data-media-action=tab][data-tab=production]').click();
 await f.getByText(/合成验收 · 刷头独立特写 · Ozon/).waitFor();
 await f.locator('[data-media-field=imageProfile]').selectOption('tiktok_us');
 assert.equal(await f.locator('[data-media-field=imageRatio]').inputValue(),'1:1');
 assert.equal(await f.locator('[data-media-field=imageRatio] option').count(),1);
 assert.equal(await f.locator('[data-media-field=imageCount]').getAttribute('max'),'9');
 await f.locator('[data-media-field=imageCount]').fill('10');await f.locator('[data-media-action=create]').click();
 await f.getByText('计划张数超过所选平台的参考上限，请调整。',{exact:true}).waitFor();
 assert.equal((await api('commerce_media_overview',{project_id:fixture.project_id})).requests.length,1);
 await f.locator('[data-media-field=imageCount]').fill('9');await f.locator('[data-media-field=imageLabel]').fill('合成验收 · TikTok方图');
 await f.locator('[data-media-action=create]').click();await f.getByText(/合成验收 · TikTok方图 · TikTok Shop/).waitFor();
 overview=await api('commerce_media_overview',{project_id:fixture.project_id});r=overview.requests[0];
 assert.equal(r.spec.image_delivery.aspect_ratio,'1:1');assert.equal(r.spec.image_options.set_size,9);assert.equal(r.spec.width,2048);
 checks.push('reload shows saved delivery; TikTok US only square, rejects 10 without a write, accepts 9; no cross-platform assumptions');
 await f.locator('[data-media-field=imageProfile]').selectOption('woocommerce');
 await f.getByText(/主图、目录缩略图和图库受主题/).waitFor();
 for(const theme of ['light','dark'])for(const width of [1440,390]){
  await page.setViewportSize({width,height:1000});await f.locator('body').evaluate((_,t)=>window.CommerceUI.applyTheme(t),theme);
  await f.locator('[data-media-field=imageProfile]').evaluate(el=>el.scrollIntoView({block:'start'}));
  assert.ok(await f.locator('html').evaluate(el=>el.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(out,`image-settings-${theme}-${width}.png`),animations:'disabled'});
 }
 await f.locator('[data-media-field=kind]').selectOption('ugc_video');assert.equal(await f.locator('[data-media-field=imageProfile]').count(),0);
 await f.locator('[data-media-action=create]').click();await f.locator('[data-media-field="shot.4"]').waitFor();
 r=(await api('commerce_media_overview',{project_id:fixture.project_id})).requests[0];assert.equal(r.spec.duration_ms,30000);assert.equal(r.spec.image_options,undefined);
 assert.equal((await api('commerce_media_plugin_execution_list',{project_id:fixture.project_id})).executions.length,0);
 checks.push('theme-dependent profile remains unverified; 1440/390 light/dark no overflow; existing UGC contract and zero plugin execution');
 assert.deepEqual(errors,[]);await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'passed',checks,errors,synthetic:true},null,2));console.log(JSON.stringify({status:'passed',checks}));
}catch(error){await page?.screenshot({path:path.join(out,'ui-failure.png')}).catch(()=>{});await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'failed',checks,errors,message:error.message},null,2));console.error(error.stack);process.exitCode=1}
finally{await browser.close()}
