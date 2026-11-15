import {goToModule} from './ui_navigation.mjs';
// Input-source recovery, mode isolation and pre-model gating through actual HTTP.
import assert from 'node:assert/strict';
import {readFile,readdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const evidence=path.resolve(process.env.SKILLS_QA_DIR||'.local/sealeap-inputs73'),origin='http://127.0.0.1:'+(process.env.COMMERCE_PORT||'38738');
let pw;try{pw=await import('playwright')}catch{for(const c of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',c,'node_modules/playwright/index.mjs')).href);break}catch{}}}assert.ok(pw);
const token=(await readFile(path.join(process.env.SKILLS_QA_STATE||path.join(evidence,'state'),'auth.token'),'utf8')).trim(),checks=[],errors=[];
const browser=await pw.chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});let page;
try{
 const ctx=await browser.newContext({viewport:{width:1440,height:1080}});await ctx.addCookies([{name:'commerce_session',value:token,url:origin,httpOnly:true,sameSite:'Strict'}]);
 const api=async(tool,args={})=>{const r=await ctx.request.post(origin+'/v1/invoke',{data:{tool,arguments:args,client:'test'}});assert.ok(r.ok(),tool);return r.json()};
 page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.name));await page.goto(origin+'/legacy');await page.locator('.kpi-value').first().waitFor();await goToModule(page,'skills');await page.locator('.skills-summary strong').first().waitFor();
 const entry=await api('commerce_skills_get',{skill_id:'sealeap-athena-amazon-keyword-traffic'});await page.locator('#skills-query').fill(entry.id);await page.locator('#skills-query').press('Enter');await page.locator('[data-skills-action=open]').first().click();await page.locator('[data-skills-action=method_toggle]').click();assert.equal(await page.locator('[data-skills-action=method_toggle]').getAttribute('aria-expanded'),'true');assert.match(await page.locator('.skills-workspace').textContent(),/未选择时不会请求模型/);
 const data=entry.draft_input_template;data.scope.marketplace='synthetic-US';data.facts=[{id:'F1',text:'合成商品为PP蓝色收纳盒；未提供搜索或排名报告。',source_ref:'synthetic_ui_fixture',label:'synthetic'}];await page.getByRole('button',{name:'高级 JSON',exact:true}).click();await page.locator('#skills-input').fill(JSON.stringify(data));await page.locator('[data-skills-action=prepare]').click();await page.locator('[data-skills-action=generate]').click();await page.locator('[aria-label=技能草稿结果]').waitFor();assert.match(await page.locator('[aria-label=技能草稿结果]').textContent(),/mode_id/);assert.match(await page.locator('[aria-label=技能草稿结果]').textContent(),/本次未请求模型/);checks.push('unselected business mode is an explicit local model gate even with supplied facts');
 for(const mode of entry.subcapabilities.slice(0,2)){
  await page.locator('#skills-mode').selectOption(mode.name);assert.equal(await page.locator('[aria-label=技能草稿结果]').count(),0);
  const expected=entry.source_method.mode_methods[mode.name].inputs[0].text;
  const input=page.locator('[aria-label=原文方法表] tbody tr').filter({has:page.locator('td').filter({hasText:/^MI1$/})});assert.equal(await input.count(),1);assert.equal(await input.locator('td').nth(1).textContent(),expected);assert.match(await input.locator('td').nth(2).textContent(),/workflow\.md/);
 }checks.push('switching modes clears old drafts and displays only the selected mode input with exact source locator');
 await page.locator('[data-skills-action=method_toggle]').click();assert.equal(await page.locator('[aria-label=原文方法表]').count(),0);await page.locator('[data-skills-action=method_toggle]').focus();await page.locator('[data-skills-action=method_toggle]').press('Enter');await page.locator('[aria-label=原文方法表]').waitFor();checks.push('explicit shared button expands/collapses the source method index through keyboard activation');
 for(const theme of ['light','dark','system']){await page.locator('#ui-theme').selectOption(theme);for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${theme} ${width}`)}}checks.push('expanded selected-mode source table fits three themes and four widths');
 assert.deepEqual(errors,[]);const result={status:'passed',actual_http:true,synthetic:true,checks,javascript_errors:errors};await writeFile(path.join(evidence,'input-ui-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){await writeFile(path.join(evidence,'input-ui-result.json'),JSON.stringify({status:'failed',checks,error_type:e.name}));await page?.screenshot({path:path.join(evidence,'input-ui-failure-private.png')}).catch(()=>{});console.error(JSON.stringify({status:'failed',checks,message:e.message.replace(/\/Users\/[^\s)]+/g,'[private-path]')}));process.exitCode=1}finally{await browser.close()}
