// Actual empty-product intake in the shared opaque UI; no models or paid calls.
import assert from 'node:assert/strict';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const out=path.resolve(process.env.CREATIVE_INTAKE_QA_DIR||'.local/coordination/creative-intake-20261114');
const state=path.resolve(process.env.COMMERCE_STATE||path.join(out,'preview-state'));
const origin='http://127.0.0.1:'+(process.env.COMMERCE_PORT||'38867');
const fixture=JSON.parse(await readFile(path.join(state,'readiness-fixture.json'),'utf8'));
let pw;try{pw=await import('playwright')}catch{for(const d of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',d,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(pw);await mkdir(out,{recursive:true});const browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const checks=[],errors=[];let page;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addCookies([{name:'commerce_session',value:(await readFile(path.join(state,'auth.token'),'utf8')).trim(),url:origin,httpOnly:true,sameSite:'Strict'}]);
 const api=async(tool,args={})=>{const r=await context.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}}),d=await r.json();assert.ok(r.ok(),JSON.stringify(d));return d};
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(origin+'/workspace?tab=workspace');const f=page.frameLocator('iframe').first();await f.locator('.pw-object-header').waitFor();
 await f.locator('[data-pw-action=catalog]').click();await f.locator('.catalog-product-title').first().click();await f.locator('[data-catalog-action=project]').first().click();
 const production=async()=>{await f.locator('[data-creative-tab=workflow]').click();await f.locator('[data-media-action=tab][data-tab=production]').click();await f.locator('.media-readiness').waitFor()};
 await production();assert.ok(await f.locator('[data-media-action=create]').isDisabled());
 for(const key of ['product_facts','product_image','reference_media','design_direction'])assert.equal(await f.locator('[data-preparation-key='+key+']').count(),1);
 const before=await api('commerce_creative_get',{project_id:fixture.project_id});
 await f.locator('[data-preparation-key=product_facts]').click();assert.equal(await f.locator('#creative-facts').evaluate(el=>el===el.ownerDocument.activeElement),true);
 const facts='合成规格：容量500毫升 | synthetic:spec';await f.locator('#creative-facts').fill(facts);await f.locator('#creative-audience').fill('合成目标人群');await f.locator('#creative-useScene').fill('合成厨房台面收纳');await f.locator('#creative-source').fill('https://example.com/synthetic-competitor-reference');
 await production();assert.ok(await f.locator('[data-media-action=create]').isDisabled());await f.locator('[data-preparation-key=product_facts]').click();assert.equal(await f.locator('#creative-facts').inputValue(),facts);
 assert.equal((await api('commerce_creative_get',{project_id:fixture.project_id})).revision,before.revision);
 await f.locator('[data-creative-action=save]').click();await f.locator('[data-creative-action=save]:not([disabled])').waitFor();
 checks.push('empty draft -> specific missing inputs -> exact field focus; unsaved facts survive navigation and are not promoted until saved');
 await production();await f.locator('[data-preparation-key=product_image]').click();assert.equal(await f.locator('#creative-kind').inputValue(),'product_image');
 await f.locator('#creative-file').setInputFiles(fixture.image_path);await f.locator('[data-creative-action=upload]').click();
 await f.locator('.data-table').getByText('商品原图',{exact:true}).waitFor();
 await production();await f.locator('[data-preparation-key=reference_media]').click();assert.equal(await f.locator('#creative-kind').inputValue(),'reference_image');
 await f.locator('#creative-file').setInputFiles(fixture.image_path);await f.locator('[data-creative-action=upload]').click();
 await f.locator('.data-table').getByText('参考图片',{exact:true}).waitFor();
 await production();await f.locator('[data-preparation-key=design_direction]').click();
 assert.equal(await f.locator('#media-analysis-layout').evaluate(el=>el===el.ownerDocument.activeElement),true);
 await f.locator('[data-media-reference]').first().check();
 for(const key of ['layout','elements','style','colors','typography','selling_points','shots','rhythm','adaptation','avoid'])await f.locator('[data-media-field="analysis.'+key+'"]').fill('合成参考拆解：主体、场景、特写和产品依据。');
 await f.locator('[data-media-action=direction-save]').click();await f.getByText('当前商品依据与设计方向可以建立制作清单。',{exact:true}).waitFor();
 assert.ok(await f.locator('[data-media-action=create]').isEnabled());checks.push('actions choose correct upload kind; real files uploaded/hashed; reference direction saved; current inputs enable request creation');
 for(const theme of ['light','dark'])for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await f.locator('body').evaluate((_,t)=>window.CommerceUI.applyTheme(t),theme);await f.locator('.media-readiness').evaluate(el=>el.scrollIntoView({block:'start'}));assert.ok(await f.locator('html').evaluate(el=>el.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,`creative-intake-${theme}-${width}.png`),animations:'disabled'})}
 await context.route('**/v1/invoke',async route=>{const body=route.request().postDataJSON();if(body?.tool==='commerce_media_overview')await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'synthetic_read_failure'})});else await route.continue()});
 await f.locator('#media-readiness-refresh').click();await f.getByText('本次操作未完成，请核对所填资料和当前版本后重试。',{exact:true}).waitFor();
 assert.ok(await f.locator('[data-media-action=create]').isDisabled(),'failed recheck must not leave cached readiness enabled');
 await context.unroute('**/v1/invoke');await f.locator('#media-readiness-refresh').click();await f.getByText('当前商品依据与设计方向可以建立制作清单。',{exact:true}).waitFor();assert.ok(await f.locator('[data-media-action=create]').isEnabled());
 checks.push('failed preparation reread disables cached readiness, retains project, and can recover without duplicate work');
 await f.locator('[data-media-action=create]').click();await f.locator('[data-media-field=request]').waitFor();
 const request=(await api('commerce_media_overview',{project_id:fixture.project_id})).requests[0];assert.equal(request.status,'awaiting_media');assert.equal(request.external_generation_submitted,false);
 const p=await api('commerce_creative_get',{project_id:fixture.project_id});assert.equal(p.brief.product.verified_facts.length,1);assert.equal(p.assets.filter(a=>a.kind==='product_image').length,1);assert.equal(p.assets.filter(a=>a.kind==='reference_image').length,1);assert.equal(p.assets.find(a=>a.kind==='product_image').source_ref,'user_provided_unverified');assert.equal(p.assets.find(a=>a.kind==='reference_image').source_ref,'https://example.com/synthetic-competitor-reference');
 assert.equal((await api('commerce_media_plugin_execution_list',{project_id:fixture.project_id})).executions.length,0);checks.push('request created from saved data only, with no plugin execution or generation; desktop/mobile light/dark render');
 assert.deepEqual(errors,[]);await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'passed',checks,errors,synthetic:true},null,2));console.log(JSON.stringify({status:'passed',checks}));
}catch(err){await page?.screenshot({path:path.join(out,'ui-failure.png')}).catch(()=>{});await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'failed',checks,errors,message:err.message},null,2));console.error(err.stack);process.exitCode=1}
finally{await browser.close()}
