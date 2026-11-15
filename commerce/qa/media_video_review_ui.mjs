// Operator content review through actual opaque UI and HTTP; no paid service.
import assert from 'node:assert/strict';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const out=path.resolve(process.env.VIDEO_REVIEW_QA_DIR||'.local/coordination/video-review-20261114');
const state=path.resolve(process.env.COMMERCE_STATE||path.join(out,'preview-state'));
const origin='http://127.0.0.1:'+(process.env.COMMERCE_PORT||'38862');
const fixture=JSON.parse(await readFile(path.join(state,'extensible-fixture.json'),'utf8'));
let pw;try{pw=await import('playwright')}catch{for(const d of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',d,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(pw);await mkdir(out,{recursive:true});const browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const checks=[],errors=[];let page;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addCookies([{name:'commerce_session',value:(await readFile(path.join(state,'auth.token'),'utf8')).trim(),url:origin,httpOnly:true,sameSite:'Strict'}]);
 const api=async(tool,args={})=>{const r=await context.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}}),d=await r.json();assert.ok(r.ok(),JSON.stringify(d));return d};
 const bind=async(revision,status)=>{const r=await context.request.post(origin+'/v1/media/plugins/configure',{data:{provider:'heygen',expected_revision:revision,link_id:'',account_label:'Synthetic HeyGen',connection_status:status,observed_at:Date.now()/1000,model:'heygen-video-1',model_parameters:{}}});assert.ok(r.ok(),await r.text())};
 await bind(0,'needs_reauthentication');page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+'/workspace?tab=workspace');const f=page.frameLocator('iframe').first();await f.locator('.pw-object-header').waitFor();
 await f.locator('[data-pw-action=catalog]').click();await f.locator('.catalog-product-title').first().click();await f.locator('[data-catalog-action=project]').first().click();
 await f.locator('[data-creative-tab=workflow]').click();await f.locator('[data-media-action=tab][data-tab=production]').click();await f.locator('[data-media-field=request]').selectOption(fixture.video_request);
 await f.locator('[data-plugin-media-action=prepare]').click();await f.locator('[data-video-review-field=presenter_mode]').waitFor();
 assert.ok(await f.locator('[data-video-review-action=save]').isDisabled());assert.ok(await f.locator('[data-plugin-execution-action=start]').isDisabled());
 await f.locator('[data-video-review-field=presenter_mode]').selectOption('fictional_adult');await f.locator('[data-video-review-field=presenter_description]').fill('虚构成年家居用品讲解员，自然居家服装。');
 await f.locator('[data-video-review-field=use_scene]').fill('合成厨房台面的日常收纳场景');await f.locator('[data-video-review-field=script_text]').fill('合成测试台词：查看产品规格和细节，按实际用途使用。');
 await f.locator('[data-video-review-confirm]').check();assert.ok(await f.locator('[data-video-review-action=save]').isEnabled());
 for(const theme of ['light','dark'])for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await f.locator('body').evaluate((_,t)=>window.CommerceUI.applyTheme(t),theme);await f.locator('[data-video-review-plan]').evaluate(el=>el.scrollIntoView({block:'start'}));assert.ok(await f.locator('html').evaluate(el=>el.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,`video-review-${theme}-${width}.png`),animations:'disabled'})}
 const original=(await api('commerce_media_plugin_plan_list',{request_id:fixture.video_request})).plans[0];
 await f.locator('[data-video-review-action=save]').click();await f.locator('[data-video-review-action=edit]').waitFor();
 let reviewed=(await api('commerce_media_plugin_plan_list',{request_id:fixture.video_request})).plans[0];assert.notEqual(reviewed.id,original.id);assert.deepEqual(reviewed.blockers,['needs_reauthentication']);assert.ok(reviewed.video_review.operator_reviewed);
 assert.ok(await f.locator('[data-plugin-execution-action=start]').isDisabled());checks.push('editable persona/scene/script/all shots and explicit content confirmation create immutable version; reauthentication is preserved');
 await bind(1,'available_to_host');await f.locator('[data-provider-action=refresh]').click();await f.getByText('依据已变化，请重新准备',{exact:true}).waitFor();
 assert.ok(await f.locator('[data-video-review-action=edit]').isDisabled());
 await f.locator('[data-plugin-media-action=prepare]').click();await f.locator('[data-video-review-field=presenter_mode]').waitFor();
 await f.locator('[data-video-review-field=presenter_mode]').selectOption('faceless');await f.locator('[data-video-review-field=use_scene]').fill('合成台面产品与结构细节展示');await f.locator('[data-video-review-field=speech_mode]').selectOption('none');
 assert.ok(await f.locator('[data-video-review-field=script_text]').isHidden());await f.locator('[data-video-review-confirm]').check();
 await f.locator('[data-video-review-action=save]').click();await f.locator('[data-video-review-action=edit]').waitFor();
 reviewed=(await api('commerce_media_plugin_plan_list',{request_id:fixture.video_request})).plans[0];assert.deepEqual(reviewed.blockers,[]);assert.equal(reviewed.video_review.content.script_text,'');
 await f.locator('[data-plugin-execution-action=start]').click();await f.getByText('等待你确认',{exact:true}).waitFor();
 let x=(await api('commerce_media_plugin_execution_list',{request_id:fixture.video_request})).executions[0];assert.equal(x.status,'awaiting_approval');assert.equal(x.external_generation_submitted,false);
 await f.locator('[data-plugin-execution-action=approve]').click();await f.getByText('等待插件会话接续',{exact:true}).waitFor();checks.push('new account revision invalidates old plan; explicit silent/faceless version requires separate generation approval');
 await f.locator('[data-video-review-action=edit]').click();await f.locator('[data-video-review-field=speech_mode]').selectOption('voiceover');
 const editor=f.locator('[data-video-review-field=script_text]');await editor.fill('尚未保存的编辑台词，仅用于焦点验收。');await editor.focus();await editor.evaluate(el=>el.setSelectionRange(3,6));
 await page.waitForTimeout(2600);
 assert.deepEqual(await editor.evaluate(el=>({focused:el===el.ownerDocument.activeElement,start:el.selectionStart,end:el.selectionEnd})),{focused:true,start:3,end:6});
 assert.equal(await editor.inputValue(),'尚未保存的编辑台词，仅用于焦点验收。');checks.push('pending execution polling preserves editor focus, caret, and unsaved text without changing approved plan');
 const claim=await api('commerce_media_plugin_execution_claim',{execution_id:x.id,host_id:'harness',idempotency_key:'video-review-host'}),auth={execution_id:x.id,claim_token:claim.claim_token};
 await api('commerce_media_plugin_execution_record_transfer',{...auth,asset_id:fixture.asset_id,remote_reference:{type:'asset_id',asset_id:'synthetic-uploaded-video-reference'},idempotency_key:'video-upload'});
 const grant=await api('commerce_media_plugin_execution_begin',auth);assert.equal(grant.tool_call.name,'heygen.reference_to_video');assert.equal(grant.tool_call.arguments.duration,30);assert.match(grant.tool_call.arguments.prompt,/不生成口播/);
 x=await api('commerce_media_plugin_execution_receipt',{...auth,receipt:{status:'completed',task_ids:['synthetic-reviewed-video'],outputs:[{url:'https://synthetic-video.heygen.example/result.mp4'}]},idempotency_key:'video-output'});assert.equal(x.status,'retrieving');assert.equal(x.actual_bytes_verified,false);
 await writeFile(path.join(state,'allow-video-download'),'synthetic only');await f.getByText('实际文件已回收 · 待审阅',{exact:true}).waitFor({timeout:15000});
 x=await api('commerce_media_plugin_execution_get',{execution_id:x.id});assert.ok(x.actual_bytes_verified);assert.equal(x.assets[0].kind,'generated_video');assert.equal(x.assets[0].media.duration_seconds,30);
 await f.locator('[data-plugin-execution-action=preview]').click();await f.locator('video').waitFor();await f.locator('video').evaluate(v=>v.readyState>=1?undefined:new Promise((resolve,reject)=>{v.addEventListener('loadedmetadata',resolve,{once:true});setTimeout(()=>reject(Error('video metadata not loaded')),4000)}));assert.equal(await f.locator('video').evaluate(v=>v.duration),30);
 await page.screenshot({path:path.join(out,'video-review-result.png'),animations:'disabled'});checks.push('reviewed video plan -> one-time host packet -> actual 30s MP4 decode/register -> same request review and preview');
 assert.deepEqual(errors,[]);await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'passed',checks,errors,synthetic:true},null,2));console.log(JSON.stringify({status:'passed',checks}));
}catch(err){await page?.screenshot({path:path.join(out,'ui-failure.png')}).catch(()=>{});await writeFile(path.join(out,'ui-result.json'),JSON.stringify({status:'failed',checks,errors,message:err.message},null,2));console.error(err.stack);process.exitCode=1}
finally{await browser.close()}
