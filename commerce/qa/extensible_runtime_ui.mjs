// Synthetic localhost acceptance through real pages and their shared backend.
import assert from 'node:assert/strict';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const evidence=path.resolve(process.env.CAPABILITY_QA_DIR||'.local/coordination/extensible-runtime-20261114');
const state=path.resolve(process.env.COMMERCE_STATE||path.join(evidence,'preview-state-v2'));
const origin='http://127.0.0.1:'+(process.env.COMMERCE_PORT||'38836');
const fixture=JSON.parse(await readFile(path.join(state,'extensible-fixture.json'),'utf8'));
let pw;try{pw=await import('playwright')}catch{for(const d of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',d,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(pw);await mkdir(evidence,{recursive:true});
const browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const errors=[],checks=[];let page;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1080},acceptDownloads:true});
 await context.addCookies([{name:'commerce_session',value:(await readFile(path.join(state,'auth.token'),'utf8')).trim(),url:origin,httpOnly:true,sameSite:'Strict'}]);
 const api=async(tool,args={})=>{const r=await context.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}});const data=await r.json();assert.ok(r.ok(),JSON.stringify(data));return data};
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+'/legacy?tab=skills');await page.locator('[data-skill-library=custom]').click();
 await page.locator('[data-extension-action=new]').waitFor();
 await page.locator('[data-extension-action=new]').click();
 await page.locator('[data-extension-field=name]').fill('合成验收 · 我的状态技能');
 await page.locator('[data-extension-action=save]').click();
 await page.locator('[data-extension-action=test]').click();
 await page.locator('[data-extension-action=enable]').first().waitFor({state:'visible'});
 await page.waitForFunction(()=>!document.querySelector('[data-extension-action=enable]')?.disabled);
 await page.locator('[data-extension-action=enable]').first().click();
 await page.waitForFunction(()=>!document.querySelector('[data-extension-action=run]')?.disabled);
 await page.locator('[data-extension-action=run]').click();
 await page.locator('[aria-label="扩展任务结果"]').getByText('运行详情 · 已完成',{exact:true}).waitFor({timeout:15000});
 checks.push('self-service skill saved, actually read-tested, enabled and run; selected state updates after enable');
 await page.locator('[data-extension-action=schedule-new]').click();
 await page.locator('[data-extension-field=trigger]').selectOption('manual');
 await page.locator('[data-extension-action=schedule-save]').click();
 await page.locator('[data-extension-action=schedule-enable]').first().click();
 await page.locator('[data-extension-action=schedule-run]').first().click();
 await page.locator('[aria-label="扩展任务结果"]').getByText('运行详情 · 已完成',{exact:true}).waitFor({timeout:15000});
 checks.push('saved manual schedule enabled and executed with its own stored input/scope/budget');
 await page.locator('[data-extension-action=tab][data-tab=plugin]').click();await page.locator('[data-extension-action=new]').click();
 await page.locator('[data-extension-field=name]').fill('合成验收 · HTTP插件');
 await page.locator('[data-extension-field="plugin.transport"]').selectOption('http');
 await page.locator('[data-extension-field="plugin.endpoint"]').fill(fixture.provider_url+'/read');
 await page.locator('[data-extension-field="plugin.tool"]').fill('synthetic_read');
 await page.locator('[data-extension-action=save]').click();await page.locator('[data-extension-action=test]').click();
 await page.locator('[aria-label="扩展任务结果"]').getByText('运行详情 · 已完成',{exact:true}).waitFor({timeout:15000});
 assert.match(await page.locator('[aria-label="扩展任务结果"]').textContent(),/received local plugin result/);
 checks.push('user-created HTTP plugin receives an actual local server result');
 await page.locator('[data-extension-action=tab][data-tab=agent]').click();await page.locator('[data-extension-action=new]').click();
 await page.locator('[data-extension-field=name]').fill('合成验收 · 本机Agent');
 await page.locator('[data-extension-field="agent.model_id"]').selectOption(fixture.model_id);
 await page.locator('[data-extension-action=save]').click();await page.locator('[data-extension-action=test]').click();
 await page.locator('[aria-label="扩展任务结果"]').getByText('运行详情 · 已完成',{exact:true}).waitFor({timeout:15000});
 await page.waitForFunction(()=>!document.querySelector('[data-extension-action=enable]')?.disabled);await page.locator('[data-extension-action=enable]').first().click();
 await page.waitForFunction(()=>!document.querySelector('[data-extension-action=run]')?.disabled);
 await page.locator('[data-extension-action=run]').click();await page.locator('.extension-approval').waitFor({timeout:15000});
 assert.match(await page.locator('.extension-approval').textContent(),/input_sha256/);await page.locator('[data-extension-action=approve]').click();
 await page.locator('[aria-label="扩展任务结果"]').getByText('运行详情 · 已完成',{exact:true}).waitFor({timeout:15000});
 assert.match(await page.locator('[aria-label="扩展任务结果"]').textContent(),/Actual local HTTP model receipt/);
 checks.push('Agent structure-only test is labelled; per-step approval leads to an actual configured local model receipt');
 for(const theme of ['light','dark'])for(const width of [1440,390]){await api('commerce_ui_set_preferences',{theme});await page.reload();await page.locator('[data-skill-library=custom]').click();await page.locator('.extension-workspace[aria-busy=false]').waitFor();await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`extensions ${theme}/${width}`);await page.screenshot({path:path.join(evidence,`extensions-${theme}-${width}.png`),animations:'disabled'})}
 // Private setup must save the same contract used by actual jobs.
 await page.goto(origin+'/capability-setup');await page.locator('#capability-label').waitFor();
 await page.locator('#capability-label').fill('合成验收 · UI添加图片服务');
 await page.locator('#capability-base_url').fill(fixture.provider_url);await page.locator('#capability-model').fill('synthetic-ui-image');
 await page.locator('#capability-protocol').fill(JSON.stringify({probe_path:'/health',submit_path:'/jobs',submit_body:{model:'{{model}}',prompt:'{{prompt}}',images:'{{images}}'},status_path:'status',outputs_path:'outputs',output_base64_path:'base64'}));
 await page.locator('[data-setup-field=enabled]').check();await page.locator('[data-setup-action=save]').click();
 await page.getByText('配置已保存。请检查当前版本；只有实际生成任务取得文件后才会显示产出。',{exact:true}).waitFor();
 const row=page.locator('tr').filter({hasText:'合成验收 · UI添加图片服务'});await row.locator('[data-setup-action=test]').click();await page.getByText('只读连接探测通过。',{exact:true}).waitFor();
 for(const width of [1440,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(evidence,`private-setup-${width}.png`),animations:'disabled'})}
 checks.push('authenticated private setup saves and probes a real local provider configuration without MCP credentials');
 await page.goto(origin+'/product-workspace');await page.locator('.pw-object-header').waitFor();await page.locator('[data-pw-action=catalog]').click();await page.locator('.catalog-product-title').first().click();await page.locator('[data-catalog-action=project]').first().click();await page.locator('[data-creative-tab=workflow]').click();await page.locator('[data-media-action=tab][data-tab=production]').click();
 await page.locator('[data-media-field=request]').selectOption(fixture.image_request);await page.locator('[data-provider-asset]').first().check();
 await page.locator('[data-provider-action=generate]').click();await page.locator('[data-provider-action=preview]').first().waitFor({timeout:20000});
 await page.locator('[data-provider-action=preview]').first().click();await page.waitForFunction(()=>document.querySelector('.creative-preview img')?.naturalWidth===96);
 const request=await api('commerce_media_request_get',{request_id:fixture.image_request});assert.equal(request.status,'awaiting_review');assert.equal(request.external_generation_submitted,true);assert.ok(request.provider_jobs.length);
 checks.push('product identity image -> frozen request -> actual local image generation -> verified PNG -> review state');
 await page.locator('[data-media-field=request]').selectOption(fixture.video_request);await page.locator('[data-provider-field=shot]').selectOption('0');await page.locator('[data-provider-asset]').first().check();
 await page.locator('[data-provider-action=generate]').click();await page.locator('[data-provider-action=use-shot]').first().waitFor({timeout:20000});await page.locator('[data-provider-action=use-shot]').first().click();
 assert.ok(await page.locator('[data-media-field="shot.0"]').inputValue());const video=await api('commerce_media_request_get',{request_id:fixture.video_request});assert.equal(video.status,'awaiting_media');
 checks.push('short video generated for one storyboard shot, selected into local edit, never misreported as complete 30-second output');
 for(const theme of ['light','dark'])for(const width of [1440,390]){await page.evaluate(t=>window.CommerceUI.applyTheme(t),theme);await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`media ${theme}/${width}`);await page.locator('.media-provider-flow').evaluate(el=>el.scrollIntoView({block:'start'}));await page.screenshot({path:path.join(evidence,`provider-${theme}-${width}.png`),animations:'disabled'})}
 // Actual React shell embeds the same capability source through its API bridge.
 await page.goto(origin+'/workspace?tab=skills');const frame=page.frameLocator('iframe').first();await frame.locator('[data-skill-library=custom]').click();await frame.locator('.extension-workspace').waitFor();assert.match(await frame.locator('.extension-workspace').textContent(),/合成验收/);checks.push('React parent and iframe bridge read the same durable extension registry');
 assert.deepEqual(errors,[]);await writeFile(path.join(evidence,'ui-result.json'),JSON.stringify({status:'passed',checks,errors,synthetic:true},null,2));console.log(JSON.stringify({status:'passed',checks}));
}catch(error){await page?.screenshot({path:path.join(evidence,'ui-failure.png')}).catch(()=>{});await writeFile(path.join(evidence,'ui-result.json'),JSON.stringify({status:'failed',message:error.message,checks,errors},null,2));console.error(error.stack);process.exitCode=1}
finally{await browser.close()}
