// Real isolated HTTP/UI and local media; no provider or daily-state calls.
import assert from 'node:assert/strict';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const state=path.resolve(process.env.COMMERCE_STATE),out=path.dirname(state);
const origin='http://127.0.0.1:'+(process.env.COMMERCE_PORT||'38876');
const fixture=JSON.parse(await readFile(path.join(state,'product-media-fixture.json'),'utf8'));
let pw;try{pw=await import('playwright')}catch{for(const d of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',d,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(pw);await mkdir(out,{recursive:true});
const browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const checks=[],errors=[],debug=[];const runId=Date.now();let page;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 await context.addCookies([{name:'commerce_session',value:(await readFile(path.join(state,'auth.token'),'utf8')).trim(),url:origin,httpOnly:true,sameSite:'Strict'}]);
 const api=async(tool,args={})=>{const r=await context.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}}),d=await r.json();assert.ok(r.ok(),JSON.stringify(d));return d};
 let p=await api('commerce_creative_get',{project_id:fixture.project_id});
 p=await api('commerce_media_direction_save',{project_id:p.id,expected_revision:p.revision,reference_asset_ids:[fixture.reference_id],analysis:Object.fromEntries(['layout','elements','style','colors','typography','selling_points','shots','rhythm','adaptation','avoid'].map(k=>[k,'合成设计验收，非商品事实']))});
 const original=await api('commerce_media_request_create',{project_id:p.id,expected_revision:p.revision,kind:'showcase_video',idempotency_key:'preflight-ui-original-'+runId});
 const r=await api('commerce_media_request_edit',{request_id:original.id,expected_request_sha256:original.request_sha256,idempotency_key:'preflight-ui-edit-'+runId,editing:{aspect_ratio:'9:16',keep_source_audio:false,shots:Array.from({length:5},(_,i)=>({source_index:i,source_start_ms:0,duration_ms:500,caption:'合成验收 '+(i+1)}))}});
 const before=await api('commerce_creative_get',{project_id:p.id});
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('response',async response=>{try{const request=response.request();if(request.postDataJSON()?.tool==='commerce_media_request_preflight')debug.push({status:response.status(),body:await response.json()})}catch{}});
 await page.goto(origin+'/product-workspace');await page.locator('.pw-object-header').waitFor();
 await page.locator('[data-pw-action=catalog]').click();await page.locator('.catalog-product-title').first().click();
 await page.locator('[data-catalog-action=project]').first().click();
 await page.locator('[data-creative-tab=workflow]').click();await page.locator('[data-media-action=tab][data-tab=production]').click();
 await page.locator('[data-media-field=request]').selectOption(r.id);
 for(let i=0;i<5;i++)await page.locator(`[data-media-field="shot.${i}"]`).selectOption(fixture.asset_id);
 await page.locator('[data-media-action=preflight]').click();
 const preflight=page.locator('[aria-label="视频制作预检"]');await preflight.waitFor();
 assert.match(await preflight.textContent(),/图文视频草稿/);assert.match(await preflight.textContent(),/成片没有音轨/);
 assert.deepEqual(await api('commerce_creative_get',{project_id:p.id}),before);checks.push('read-only preflight through real UI/HTTP creates no job or asset');
 await page.locator('[data-media-field="shot.0"]').selectOption('');assert.equal(await preflight.count(),0);
 await page.locator('[data-media-field="shot.0"]').selectOption(fixture.asset_id);checks.push('changing selected input withdraws the prior report');
 for(const [width,height,theme]of [[1440,1000,'light'],[390,844,'dark']]){
  await page.setViewportSize({width,height});await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
  assert.equal(await page.evaluate(()=>innerWidth),width);await preflight.scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  await page.screenshot({path:path.join(out,`preflight-${width}-${theme}.png`),animations:'disabled'});
 }
 checks.push('actual 1440px/light and 390px/dark rendering without horizontal overflow');
 await page.setViewportSize({width:1440,height:1000});await page.locator('[data-media-action=execute]').click();
 await page.locator('[aria-label="成片技术检查"]').waitFor({timeout:30000});
 assert.match(await page.locator('[aria-label="成片技术检查"]').textContent(),/完整解码：通过/);
 const produced=await api('commerce_media_request_get',{request_id:r.id});assert.equal(produced.status,'awaiting_review');assert.equal(produced.quality_report.technical_status,'passed');
 const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'下载检查报告',exact:true}).click();
 const download=await downloadPromise;assert.ok((await readFile(await download.path(),'utf8')).includes('commerce-video-quality-v1'));
 await page.screenshot({path:path.join(out,'delivery-quality.png'),animations:'disabled'});
 checks.push('actual local MP4, full decode, pending human review and downloadable quality report');
 await page.goto(origin+'/workspace?tab=creative');const frame=page.frameLocator('iframe').first();
 await frame.locator('#creative-project-select').selectOption(p.id);
 await frame.locator('[data-creative-tab=workflow]').click();await frame.locator('[data-media-action=tab][data-tab=production]').click();
 await frame.locator('[data-media-field=request]').selectOption(r.id);
 await frame.locator('[aria-label="成片技术检查"]').waitFor();
 assert.match(await frame.locator('[aria-label="成片技术检查"]').textContent(),/完整解码：通过/);
 await page.screenshot({path:path.join(out,'iframe-delivery-quality.png'),animations:'disabled'});
 checks.push('shared workspace iframe loads the same exact result checks through its separate build path');
 assert.deepEqual(errors,[]);await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'passed',checks,errors,synthetic:true},null,2));console.log(JSON.stringify({status:'passed',checks}));
}catch(err){await writeFile(path.join(out,'ui-debug.json'),JSON.stringify({debug,text:await page?.locator('.media-flow').textContent().catch(()=>''),errors},null,2));await page?.screenshot({path:path.join(out,'ui-failure.png')}).catch(()=>{});await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'failed',checks,errors,message:err.message},null,2));console.error(err.stack);process.exitCode=1}
finally{await browser.close()}
