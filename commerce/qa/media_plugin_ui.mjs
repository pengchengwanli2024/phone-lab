// Synthetic plugin-account plans through actual shared HTTP and browser UI.
import assert from 'node:assert/strict';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const out=path.resolve(process.env.PLUGIN_MEDIA_QA_DIR||'.local/coordination/plugin-binding-20261114');
const state=path.resolve(process.env.COMMERCE_STATE||path.join(out,'preview-state'));
const origin='http://127.0.0.1:'+(process.env.COMMERCE_PORT||'38846');
const fixture=JSON.parse(await readFile(path.join(state,'extensible-fixture.json'),'utf8'));
let pw;try{pw=await import('playwright')}catch{for(const d of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',d,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(pw);await mkdir(out,{recursive:true});
const browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const checks=[],errors=[];let page;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 await context.addCookies([{name:'commerce_session',value:(await readFile(path.join(state,'auth.token'),'utf8')).trim(),url:origin,httpOnly:true,sameSite:'Strict'}]);
 const api=async(tool,args={})=>{const r=await context.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}});const data=await r.json();assert.ok(r.ok(),JSON.stringify(data));return data};
 const binding=async(provider,revision,link_id)=>{const r=await context.request.post(origin+'/v1/media/plugins/configure',{data:{provider,expected_revision:revision,account_label:'Synthetic '+provider,link_id,connection_status:provider==='lovart'?'available_to_host':'needs_reauthentication',observed_at:Date.now()/1000,model:provider==='lovart'?'synthetic-image':'heygen-video-1',model_parameters:{}}});assert.ok(r.ok(),await r.text());return r.json()};
 const anonymous=await browser.newContext();const denied=await anonymous.request.post(origin+'/v1/media/plugins/configure',{data:{}});assert.equal(denied.status(),401);await anonymous.close();
 await binding('lovart',0,'link_synthetic_selected');await binding('heygen',0,'');
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+'/product-workspace');await page.locator('.pw-object-header').waitFor();
 await page.locator('[data-pw-action=catalog]').click();await page.locator('.catalog-product-title').first().click();await page.locator('[data-catalog-action=project]').first().click();
 await page.locator('[data-creative-tab=workflow]').click();await page.locator('[data-media-action=tab][data-tab=production]').click();
 await page.locator('[data-media-field=request]').selectOption(fixture.image_request);
 await page.locator('[data-plugin-media-action=prepare]').click();await page.locator('.plugin-media-plan').waitFor();
 assert.match(await page.locator('.plugin-media-plan').textContent(),/实际生成状态见下方执行回执/);
 const plans=await api('commerce_media_plugin_plan_list',{request_id:fixture.image_request}),plan=plans.plans[0];
 assert.equal(plan.tool_call.arguments.link_id,'link_synthetic_selected');assert.equal(plan.external_generation_submitted,false);
 const downloadEvent=page.waitForEvent('download');await page.locator('[data-plugin-media-action=download]').click();const download=await downloadEvent;const exportPath=path.join(out,'synthetic-plugin-plan.json');await download.saveAs(exportPath);
 assert.equal(JSON.parse(await readFile(exportPath,'utf8')).plan_sha256,plan.plan_sha256);
 assert.equal((await api('commerce_media_provider_jobs',{request_id:fixture.image_request})).jobs.length,0);
 checks.push('private account binding -> versioned product plan -> exact selected account -> real JSON download without remote generation');
 await binding('lovart',1,'link_synthetic_changed');await page.locator('[data-provider-action=refresh]').click();await page.getByText('依据已变化，请重新准备',{exact:true}).waitFor();
 checks.push('account change visibly invalidates a cached plan');
 for(const theme of ['light','dark'])for(const width of [1440,390]){await page.evaluate(t=>window.CommerceUI.applyTheme(t),theme);await page.setViewportSize({width,height:1000});await page.locator('.plugin-media-plan').evaluate(el=>el.scrollIntoView({block:'center'}));assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,`plugin-plan-${theme}-${width}.png`),animations:'disabled'})}
 await page.locator('[data-media-field=request]').selectOption(fixture.video_request);await page.locator('[data-plugin-media-action=prepare]').click();await page.locator('.plugin-media-plan').waitFor();
 assert.match(await page.locator('.plugin-media-plan').textContent(),/重新授权/);assert.match(await page.locator('.plugin-media-plan').textContent(),/人物、口播和分镜/);
 checks.push('HeyGen reauthentication and content approval remain explicit blockers');
 await page.goto(origin+'/capability-setup');await page.getByText('优先使用的宿主插件',{exact:true}).waitFor();assert.match(await page.locator('body').textContent(),/后台未直连/);
 checks.push('private setup distinguishes host-plugin authorization from direct API keys');
 await page.goto(origin+'/workspace?tab=workspace');const f=page.frameLocator('iframe').first();await f.locator('.pw-object-header').waitFor();await f.locator('[data-pw-action=catalog]').click();await f.locator('.catalog-product-title').first().click();await f.locator('[data-catalog-action=project]').first().click();await f.locator('[data-creative-tab=workflow]').click();await f.locator('[data-media-action=tab][data-tab=production]').click();await f.locator('[data-plugin-media-action=prepare]').waitFor();
 assert.equal(await page.locator('iframe').first().getAttribute('sandbox'),'allow-scripts allow-forms allow-downloads');checks.push('same plugin plan component runs in the actual opaque React product frame');
 assert.deepEqual(errors,[]);await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'passed',checks,errors,synthetic:true},null,2));console.log(JSON.stringify({status:'passed',checks}));
}catch(err){await page?.screenshot({path:path.join(out,'ui-failure.png')}).catch(()=>{});await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'failed',checks,errors,message:err.message},null,2));console.error(err.stack);process.exitCode=1}
finally{await browser.close()}
