// Isolated real-DOM checks over the shared UI and Python journal, no real accounts.
import assert from 'node:assert/strict';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const out=process.env.QA_OUTPUT_DIR;
if(!out)throw Error('Private QA_OUTPUT_DIR required');await mkdir(out,{recursive:true});
let playwright;try{playwright=await import('playwright')}catch{for(const entry of await readdir(path.join(homedir(),'.npm/_npx')).catch(()=>[])){try{playwright=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',entry,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(playwright,'Existing Playwright required');
const origin=process.env.QA_ORIGIN||'http://127.0.0.1:61852',checks=[],errors=[],external=[];
const browser=await playwright.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
const api=async(tool,args={})=>{const r=await context.request.post(origin+'/v1/invoke',{headers:{authorization:'Bearer synthetic-generative-preview'},data:{tool,arguments:args,client:'test'}});const value=await r.json();assert.equal(r.ok(),true,tool+': '+JSON.stringify(value));return value;};
const ask=async text=>{await page.locator('#copilot-message').fill(text);await page.locator('#copilot-message').dispatchEvent('input');await page.locator('[data-copilot-action="send"]').click();};
try{
 await context.route('**/*',route=>{const url=route.request().url();if(url.startsWith(origin)||url.startsWith('data:'))return route.continue();external.push(url);return route.abort();});
 page.on('pageerror',error=>errors.push(error.message));
 await page.goto(origin+'/login?token=synthetic-generative-preview');errors.length=0;await page.goto(origin+'/generative-test');
 assert.deepEqual(errors,[],'Fixture initialization errors');
 const prepared=await api('commerce_copilot_open',{context:await page.evaluate(()=>window.qaContext),title:'合成生成式界面验收',idempotency_key:'qa:'+crypto.randomUUID()});
 await page.evaluate(id=>window.cp.openThread(id),prepared.id);
 await page.locator('#copilot-message').waitFor();await ask('合成验收：请比较供应10件，并审阅交付与成本。');
 await page.locator('.copilot-provisional').waitFor({timeout:15000});
 const thread=prepared,first=await api('commerce_copilot_get',{thread_id:thread.id}),runId=first.latest_run.id;
 assert.ok(first.latest_run.stream.answer);assert.ok(['queued','running'].includes(first.latest_run.status));checks.push('真实原请求在完成前展示生成预览');
 await page.locator('#copilot-message').fill('未发送草稿：保留卖点');await page.locator('#copilot-message').dispatchEvent('input');
 await page.waitForTimeout(600);assert.equal(await page.locator('#copilot-message').inputValue(),'未发送草稿：保留卖点');checks.push('增量刷新保留未发送草稿');
 await page.reload();await page.evaluate(id=>window.cp.openThread(id),thread.id);
 await page.locator('[data-component-kind="QuoteComparison"]').waitFor({timeout:15000});
 await page.waitForFunction(()=>!document.querySelector('.copilot-provisional'),null,{timeout:15000});
 const recovered=await api('commerce_copilot_get',{thread_id:thread.id});assert.equal(recovered.total_turns,1);assert.equal(recovered.latest_run.id,runId);assert.equal(recovered.latest_run.status,'completed');checks.push('刷新恢复同一请求，未重发模型或增加对话轮次');
 assert.equal(await page.locator('[data-component-kind="QuoteComparison"]').count(),1);assert.equal(await page.locator('[data-component-kind="DeliveryReview"]').count(),1);assert.equal(await page.locator('[data-component-kind="CostSummary"]').count(),1);
 assert.match(await page.locator('[data-component-kind="QuoteComparison"]').innerText(),/20（多10件）/);
 await page.locator('#copilot-log').evaluate(el=>{el.scrollTop=el.scrollHeight});
 await page.screenshot({path:path.join(out,'business-cards-light.png'),fullPage:true});
 await page.evaluate(()=>CommerceUI.applyTheme('dark'));await page.screenshot({path:path.join(out,'business-cards-dark.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,'business-cards-390.png'),fullPage:true});checks.push('三类业务卡片在1440浅深与390视口实际渲染，无页面横向溢出');
 await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>CommerceUI.applyTheme('light'));await ask('合成验收：请核对上架产品信息和产品图片。');
 await page.locator('[data-component-kind="ListingReview"]').waitFor({timeout:15000});await page.waitForFunction(()=>!document.querySelector('.copilot-provisional'),null,{timeout:15000});
 const card=page.locator('[data-component-kind="ListingReview"]').last();await card.locator('[data-generative-image]').first().click();await card.locator('img').waitFor();assert.ok(await card.locator('img').evaluate(img=>img.complete&&img.naturalWidth>0));checks.push('上架卡片展示产品字段，并通过原版本绑定接口读取真实合成图片字节');
 await page.evaluate(()=>window.cp.contextChanged());await card.locator('img').waitFor();assert.ok(await card.locator('img').evaluate(img=>img.complete&&img.naturalWidth>0));checks.push('同一保存版本的已读图片在页面重绘后保持');
 await page.locator('#copilot-log').evaluate(el=>{el.scrollTop=el.scrollHeight});await page.screenshot({path:path.join(out,'listing-image.png'),fullPage:true});
 const target=card.locator('[data-copilot-action="generative-workspace"]');await target.click();assert.match(await page.locator('#opened').innerText(),/已导航到准确商品/);checks.push('卡片导航使用原观察对象身份');
 await ask('合成验收：供应10件，模拟中断。');await page.locator('.copilot-provisional').waitFor({timeout:15000});await page.waitForFunction(()=>document.querySelector('#copilot-log')?.textContent.includes('结果尚未确认'),null,{timeout:15000});assert.equal(await page.locator('.copilot-provisional').count(),0);checks.push('中断撤下未校验预览，保留UNKNOWN且不自动重试');
 await ask('合成验收：供应10件，验证预览限量。');await page.getByText('预览已限量，完成后读取完整结果',{exact:true}).waitFor({timeout:15000});await page.waitForFunction(()=>!document.querySelector('.copilot-provisional'),null,{timeout:15000});checks.push('预览达到上限时明确提示，原请求仍完成并提供完整结果');
 assert.equal((await api('commerce_copilot_get',{thread_id:thread.id})).total_turns,4);assert.equal((await api('commerce_task_list')).tasks.length,0);assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
 await writeFile(path.join(out,'verification.json'),JSON.stringify({status:'Passed',synthetic:true,checks,page_errors:errors,external_requests:external,model_charges:0,store_writes:0,real_desktop_native:false},null,2));console.log(JSON.stringify({status:'Passed',checks:checks.length}));
}catch(error){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(path.join(out,'failure.json'),JSON.stringify({error:String(error),checks,page_errors:errors,external_requests:external},null,2));throw error}
finally{await context.close();await browser.close();}
