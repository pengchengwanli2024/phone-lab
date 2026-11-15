// Actual UI/HTTP handoff, with isolated synthetic bytes and no paid generation.
import assert from 'node:assert/strict';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const out=path.resolve(process.env.PLUGIN_EXECUTION_QA_DIR||'.local/coordination/plugin-execution-20261114');
const state=path.resolve(process.env.COMMERCE_STATE||path.join(out,'preview-state'));
const origin='http://127.0.0.1:'+(process.env.COMMERCE_PORT||'38856');
const fixture=JSON.parse(await readFile(path.join(state,'extensible-fixture.json'),'utf8'));
let pw;try{pw=await import('playwright')}catch{for(const d of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',d,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(pw);await mkdir(out,{recursive:true});
const browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const checks=[],errors=[];let page;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 await context.addCookies([{name:'commerce_session',value:(await readFile(path.join(state,'auth.token'),'utf8')).trim(),url:origin,httpOnly:true,sameSite:'Strict'}]);
 const api=async(tool,args={})=>{const r=await context.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}});const d=await r.json();assert.ok(r.ok(),JSON.stringify(d));return d};
 for(const provider of ['lovart','heygen']){const r=await context.request.post(origin+'/v1/media/plugins/configure',{data:{provider,expected_revision:0,account_label:'Synthetic '+provider,link_id:provider==='lovart'?'link_synthetic_selected':'',connection_status:provider==='lovart'?'available_to_host':'needs_reauthentication',observed_at:Date.now()/1000,model:provider==='lovart'?'synthetic-image':'heygen-video-1',model_parameters:{}}});assert.ok(r.ok(),await r.text())}
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+'/product-workspace');await page.locator('.pw-object-header').waitFor();
 await page.locator('[data-pw-action=catalog]').click();await page.locator('.catalog-product-title').first().click();await page.locator('[data-catalog-action=project]').first().click();
 await page.locator('[data-creative-tab=workflow]').click();await page.locator('[data-media-action=tab][data-tab=production]').click();
 await page.locator('[data-media-field=request]').selectOption(fixture.image_request);
 await page.locator('[data-plugin-media-action=prepare]').click();await page.locator('[data-plugin-execution-action=start]').click();
 await page.getByText('等待你确认',{exact:true}).waitFor();
 const plan=(await api('commerce_media_plugin_plan_list',{request_id:fixture.image_request})).plans[0];
 let execution=(await api('commerce_media_plugin_execution_list',{request_id:fixture.image_request})).executions[0];
 const p=await api('commerce_creative_get',{project_id:fixture.project_id});
 await api('commerce_media_plugin_plan_prepare',{request_id:fixture.image_request,expected_revision:p.revision,provider:'lovart',expected_connection_revision:1,asset_ids:[fixture.asset_id],idempotency_key:'newer-unused-plan'});
 const probe=await context.newPage();await probe.goto(origin+'/workspace?tab=tasks');await probe.getByRole('button',{name:'继续插件任务',exact:true}).first().click();
 const probeFrame=probe.frameLocator('iframe').last();await probeFrame.getByText('等待你确认',{exact:true}).waitFor();
 assert.equal(await probeFrame.locator('[data-plugin-execution]').getAttribute('data-plugin-execution'),plan.id);
 await probeFrame.locator('[data-plugin-media-action=prepare]').click();await probeFrame.locator('[data-plugin-execution-action=start]').waitFor();
 assert.notEqual(await probeFrame.locator('[data-plugin-execution]').getAttribute('data-plugin-execution'),plan.id);
 await probe.close();checks.push('exact older plan resumes even with newer plan; preparing another plan switches selection without altering original execution');
 assert.equal(execution.external_generation_submitted,false);assert.equal(execution.status,'awaiting_approval');
 assert.match(await page.locator('.plugin-execution-approval').textContent(),/Synthetic lovart/);
 await page.locator('[data-plugin-execution-action=source]').focus();assert.equal(await page.evaluate(()=>document.activeElement.dataset.pluginExecutionAction),'source');
 for(const theme of ['light','dark'])for(const width of [1440,390]){await page.evaluate(t=>window.CommerceUI.applyTheme(t),theme);await page.setViewportSize({width,height:1000});await page.locator('.plugin-execution').evaluate(el=>el.scrollIntoView({block:'start'}));assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,`execution-approval-${theme}-${width}.png`),animations:'disabled'})}
 checks.push('product plan -> exact account/source/hash approval; no external call; keyboard and 1440/390 light/dark');
 await page.locator('[data-plugin-execution-action=approve]').click();await page.getByText('等待插件会话接续',{exact:true}).waitFor();
 const claim=await api('commerce_media_plugin_execution_claim',{execution_id:execution.id,host_id:'codex',idempotency_key:'ui-host-claim'}),auth={execution_id:execution.id,claim_token:claim.claim_token};
 await api('commerce_media_plugin_execution_record_transfer',{...auth,asset_id:fixture.asset_id,remote_reference:{type:'url',url:'https://assets.lovart.ai/synthetic-upload.png'},idempotency_key:'ui-upload'});
 const packet=await api('commerce_media_plugin_execution_begin',auth);assert.equal(packet.submission_grant,'once_only');assert.equal(packet.tool_call.arguments.link_id,'link_synthetic_selected');
 await api('commerce_media_plugin_execution_receipt',{...auth,receipt:{status:'pending',task_ids:['synthetic-ui-task'],project_id:'synthetic-ui-project'},idempotency_key:'ui-pending'});
 await page.locator('[data-plugin-execution-action=refresh]').click();await page.getByText('生成服务处理中',{exact:true}).waitFor();
 assert.ok(await page.locator('[data-provider-action=generate]').isDisabled());
 const receipt={status:'completed',task_ids:['synthetic-ui-task'],project_id:'synthetic-ui-project',outputs:[{url:'https://synthetic-results.lovart.ai/result.png?synthetic-signature='+'b'.repeat(400)}]};
 execution=await api('commerce_media_plugin_execution_receipt',{...auth,receipt,idempotency_key:'ui-completed'});assert.equal(execution.actual_bytes_verified,false);
 await page.locator('[data-plugin-execution-action=refresh]').click();await page.getByText('正在回收并校验实际文件',{exact:true}).waitFor();
 checks.push('approved host claim -> one-time submission packet -> pending/completed receipts; completion does not pretend actual bytes verified');
 await writeFile(path.join(state,'allow-plugin-download'),'synthetic only');
 await page.getByText('实际文件已回收 · 待审阅',{exact:true}).waitFor({timeout:15000});
 execution=await api('commerce_media_plugin_execution_get',{execution_id:execution.id});assert.ok(execution.actual_bytes_verified);assert.equal(execution.assets.length,1);
 const result=await api('commerce_task_result',{task_id:execution.task_id});assert.equal(result.execution.operation,'media_plugin');assert.equal(result.task.status,'completed');
 assert.equal((await api('commerce_media_request_get',{request_id:fixture.image_request})).assets[0].id,execution.assets[0].id);
 assert.ok(await page.locator('[data-plugin-media-action=prepare]').isDisabled());
 await page.locator('[data-plugin-execution-action=preview]').click();
 await page.screenshot({path:path.join(out,'execution-result.png'),animations:'disabled'});
 assert.equal((await api('commerce_media_plugin_execution_receipt',{...auth,receipt,idempotency_key:'ui-completed-replay'})).status,'awaiting_review');
 checks.push('real PNG download/decode/register -> same request review and shared task; completion replay preserves adopted files');
 await page.setViewportSize({width:1440,height:1000});
 await page.goto(origin+'/workspace?tab=tasks');await page.getByRole('heading',{name:'任务',exact:true}).waitFor();
 await page.getByRole('button',{name:'查看回执',exact:true}).first().click();await page.getByText('插件执行与实际素材回执',{exact:true}).waitFor();
 assert.doesNotMatch(await page.getByRole('dialog').textContent(),/执行尝试：/);
 await page.getByRole('button',{name:'继续原工作',exact:true}).click();
 const f=page.frameLocator('iframe').last();await f.getByText('实际文件已回收 · 待审阅',{exact:true}).waitFor({timeout:15000});
 assert.equal(await f.locator('[data-media-field=request]').inputValue(),fixture.image_request);
 assert.equal(await f.locator('[data-plugin-execution]').getAttribute('data-plugin-execution'),plan.id);
 assert.equal(await page.locator('iframe').last().getAttribute('sandbox'),'allow-scripts allow-forms allow-downloads');
 await page.screenshot({path:path.join(out,'execution-task-return.png'),animations:'disabled'});
 checks.push('React task receipt -> original product request inside actual opaque iframe');
 await f.locator('[data-media-field=request]').selectOption(fixture.video_request);await f.locator('[data-plugin-media-action=prepare]').click();
 await f.getByText(/人物、口播和分镜需要先确认/).waitFor();assert.ok(await f.locator('[data-plugin-execution-action=start]').isDisabled());
 checks.push('HeyGen reauthentication/person/script/storyboard blockers stay closed');
 assert.deepEqual(errors,[]);await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'passed',checks,errors,synthetic:true},null,2));console.log(JSON.stringify({status:'passed',checks}));
}catch(err){await page?.screenshot({path:path.join(out,'ui-failure.png')}).catch(()=>{});await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'failed',checks,errors,message:err.message},null,2));console.error(err.stack);process.exitCode=1}
finally{await browser.close()}
