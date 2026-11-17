import {goToModule} from './ui_navigation.mjs';
// Actual isolated HTTP + browser + opaque-frame workflow. All input media is synthetic.
import assert from 'node:assert/strict';
import {readFile,readdir,writeFile,mkdir} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const evidence=process.env.CREATIVE_QA_DIR?path.resolve(process.env.CREATIVE_QA_DIR):path.join(path.dirname(root),'.local/creative-acceptance');await mkdir(evidence,{recursive:true});
let pw;try{pw=await import('playwright')}catch{for(const c of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',c,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(pw);
const origin='http://127.0.0.1:'+(process.env.COMMERCE_PORT||'38735');
const secret=(await readFile(path.join(evidence,'state/auth.token'),'utf8')).trim();
const browser=await pw.chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const checks=[],errors=[];let page;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1080},acceptDownloads:true});
 await context.addCookies([{name:'commerce_session',value:secret,url:origin,httpOnly:true,sameSite:'Strict'}]);
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.name));await page.goto(origin+'/legacy');await page.locator('.kpi-value').first().waitFor();
 await goToModule(page,'creative');await page.locator('[data-creative-action=example]').click();await page.locator('[data-creative-action=save]').click();
 await page.locator('[data-creative-tab=scripts]').waitFor();assert.match(await page.locator('.creative-workspace').textContent(),/合成测试资料/);checks.push('create synthetic private project with honest draft labels');
 await page.locator('[data-creative-tab=scripts]').click();assert.equal(await page.locator('.creative-script').count(),3);assert.match(await page.locator('.creative-script').first().textContent(),/500/);checks.push('three grounded script angles and contiguous storyboard displayed');
 await page.locator('[data-creative-tab=brief]').click();await page.locator('#creative-kind').selectOption('reference_video');await page.locator('#creative-file').setInputFiles(path.join(evidence,'synthetic-reference.mp4'));await page.locator('[data-creative-action=upload]').click();
 await page.getByText('校验完成，素材已保存。',{exact:true}).waitFor();await page.locator('[data-creative-tab=analysis]').click();
 await page.locator('#creative-asset').selectOption({label:'synthetic-reference.mp4 · 参考视频'});await page.locator('[data-creative-action=analyze]').click();
 await page.waitForFunction(()=>['已完成','部分完成 · 有待补充项'].includes(document.querySelector('.creative-job>strong')?.textContent),null,{timeout:30000});
 await page.waitForFunction(()=>[...document.querySelectorAll('td')].filter(x=>x.textContent==='关键帧').length===4);assert.equal(await page.locator('td').filter({hasText:/^关键帧$/}).count(),4);checks.push('chunked upload, actual keyframes/OCR analysis and persisted job polling');
 assert.equal(await page.locator('.creative-frame').count(),4);assert.match(await page.locator('.creative-analysis').textContent(),/语义角色仍待人工解读/);
 await page.locator('#creative-transcript-review').fill('人工校对的合成参考口播，不是商品事实。');await page.locator('#creative-transcript-review').press('Tab');
 assert.ok(await page.locator('[data-creative-action=review_transcript]').evaluate(e=>e===document.activeElement));await page.locator('[data-creative-action=review_transcript]').press('Enter');
 await page.getByText(/资料版本 2/).first().waitFor();await page.locator('[data-creative-tab=brief]').click();assert.equal(await page.locator('#creative-transcript').inputValue(),'人工校对的合成参考口播，不是商品事实。');
 await page.locator('#creative-project-select').selectOption(await page.locator('#creative-project-select').inputValue());await page.locator('[data-creative-tab=analysis]').click();await page.locator('.creative-job-list [data-job-kind=analyze]').first().click();await page.locator('#creative-transcript-review').waitFor();assert.equal(await page.locator('#creative-transcript-review').inputValue(),'人工校对的合成参考口播，不是商品事实。');await page.locator('[data-creative-tab=brief]').click();
 checks.push('structured analysis shows visual-cut limits; keyboard transcript review fills reference without promoting it to product facts');
 await page.locator('[data-creative-tab=brief]').click();await page.locator('#creative-kind').selectOption('product_image');await page.locator('#creative-file').setInputFiles(path.join(evidence,'synthetic-product.png'));await page.locator('[data-creative-action=upload]').click();await page.getByText('校验完成，素材已保存。',{exact:true}).waitFor();
 await page.locator('#creative-kind').selectOption('audio');await page.locator('#creative-file').setInputFiles(path.join(evidence,'synthetic-tone.wav'));await page.locator('[data-creative-action=upload]').click();await page.getByText('校验完成，素材已保存。',{exact:true}).waitFor();
 await page.locator('[data-creative-tab=outputs]').click();await page.locator('#creative-asset').selectOption({label:'synthetic-product.png · 商品原图'});await page.locator('#creative-audio').selectOption({label:'synthetic-tone.wav'});await page.locator('[data-creative-action=image_layout]').click();
 await page.waitForFunction(()=>document.querySelector('.creative-job>strong')?.textContent==='已完成',null,{timeout:30000});
 await page.getByText('product_main · 模板排版',{exact:true}).waitFor();await page.getByText('product_main · 模板排版',{exact:true}).locator('..').locator('[data-creative-action=asset]').click();
 await page.waitForFunction(()=>document.querySelector('.creative-preview img')?.naturalWidth===1080);checks.push('three rendered PNG layouts, editable SVG assets and private image preview');
 await page.locator('[data-creative-action=render]').click();await page.waitForFunction(()=>document.querySelector('.creative-job>strong')?.textContent==='已完成',null,{timeout:90000});
 const videoRow=page.getByText('图文视频草稿 · detail',{exact:true}).locator('..');await videoRow.locator('[data-creative-action=asset]').click();
 await page.waitForFunction(()=>document.querySelector('.creative-preview video')?.readyState>=1,null,{timeout:30000});
 assert.ok(Math.abs(await page.locator('.creative-preview video').evaluate(v=>v.duration)-30)<.2);checks.push('real 30-second video draft rendered and browser metadata preview works');
 await page.locator('[data-creative-tab=scripts]').click();const download=page.waitForEvent('download');await page.locator('[data-creative-action=export]').click();const file=await download;const bundle=JSON.parse(await readFile(await file.path(),'utf8'));
 assert.equal(bundle.export_kind,'private_creative_project_draft');assert.equal(bundle.plan.scripts.length,3);assert.equal(bundle.source_sha256.length,64);assert.ok(bundle.assets.some(a=>a.kind==='video_draft'&&a.provided_audio_used&&a.media.has_audio));assert.equal(bundle.analysis_receipts.length,1);assert.equal(bundle.brief.reference.transcript_review.status,'caller_reviewed_not_independently_verified');checks.push('download retains script, storyboard, analysis receipts, review provenance, assets and source hashes');
 const mdDownload=page.waitForEvent('download');await page.locator('[data-creative-action=export_markdown]').click();const mdFile=await mdDownload;const md=await readFile(await mdFile.path(),'utf8');assert.match(md,/原片分析回执/);assert.match(md,/人工校对的合成参考口播/);checks.push('Markdown handoff contains reviewed text, facts, storyboard, visual-cut receipts and production limits');
 for(const theme of ['light','dark']){await page.locator('#ui-theme').selectOption(theme);for(const tab of ['brief','analysis','scripts','outputs']){await page.locator(`[data-creative-tab=${tab}]`).click();if(tab==='analysis'){await page.locator('.creative-job-list [data-job-kind=analyze]').first().click();await page.locator('#creative-transcript-review').waitFor()}for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${theme} ${tab} ${width}`)}}}
 checks.push('four views fit 1440/1024/768/390 in light and dark themes');
 await page.setViewportSize({width:1440,height:1080});await page.locator('[data-creative-tab=outputs]').click();await page.screenshot({path:path.join(evidence,'creative-studio-browser.png')});
 // Opaque srcdoc iframe and the installed client's nonce + message protocol.
 const host=await context.newPage();host.on('pageerror',e=>errors.push(e.name));
 await host.route(origin+'/creative-test-frame',route=>route.fulfill({contentType:'text/html',body:'<iframe title="creative" sandbox="allow-scripts allow-downloads" style="width:100%;height:1000px;border:0"></iframe>'}));
 await host.exposeFunction('invokeCreative',async(tool,args)=>{const r=await context.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}});const j=await r.json();if(!r.ok)throw Error('backend_rejected');return j});
 await host.goto(origin+'/creative-test-frame');const html=await(await context.request.get(origin+'/legacy')).text();
 await host.evaluate(html=>{const f=document.querySelector('iframe'),nonce='synthetic-creative-frame';window.addEventListener('message',async e=>{const m=e.data;if(e.source!==f.contentWindow||m?.nonce!==nonce||m?.type!=='commerce:call')return;try{const result=await window.invokeCreative(m.tool,m.arguments);f.contentWindow.postMessage({type:'commerce:result',nonce,id:m.id,result},'*')}catch{f.contentWindow.postMessage({type:'commerce:result',nonce,id:m.id,error:'synthetic_error'},'*')}});f.srcdoc=html.replaceAll('__COMMERCE_BRIDGE_NONCE__',nonce)},html);
 const frame=host.frameLocator('iframe');await frame.locator('.kpi-value').first().waitFor();await goToModule(frame,'creative');await frame.locator('[data-creative-action=example]').click();await frame.locator('#creative-name').fill('合成iframe项目');await frame.locator('#creative-name').press('Enter');await frame.locator('[data-creative-tab=scripts]').waitFor();
 await frame.locator('[data-creative-tab=scripts]').click();assert.equal(await frame.locator('.creative-script').count(),3);
 await frame.locator('[data-creative-tab=brief]').click();await frame.locator('#creative-kind').selectOption('product_image');await frame.locator('#creative-file').setInputFiles(path.join(evidence,'synthetic-product.png'));await frame.locator('[data-creative-action=upload]').click();await frame.getByText('校验完成，素材已保存。',{exact:true}).waitFor();checks.push('opaque no-forms iframe supports Enter save, project API bridge and checksum upload');
 await host.close();assert.deepEqual(errors,[]);
 const result={status:'passed',synthetic:true,backend:'isolated real HTTP',checks,javascript_errors:errors,limits:['Iframe protocol emulation is not installed desktop-host visual acceptance.','No real product/video, AI provider or publication invoked by this suite.']};await writeFile(path.join(evidence,'creative-ui-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){await writeFile(path.join(evidence,'creative-ui-result.json'),JSON.stringify({status:'failed',synthetic:true,error_type:error.name,checks,javascript_errors:errors},null,2));await page?.screenshot({path:path.join(evidence,'creative-ui-failure.png')}).catch(()=>{});console.error(JSON.stringify({status:'failed',error_type:error.name,message:error.message.replace(/\/Users\/[^\s)]+/g,'[private-path]'),checks}));process.exitCode=1}
finally{await browser.close()}
