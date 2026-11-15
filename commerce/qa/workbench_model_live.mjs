import {goToModule} from './ui_navigation.mjs';
// One synthetic UI-to-model smoke against the already-authorized local service.
import {readFile,readdir,writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
let playwright;try{playwright=await import(process.env.PLAYWRIGHT_MODULE||'playwright')}catch{for(const cache of await readdir(path.join(homedir(),'.npm/_npx'))){try{playwright=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',cache,'node_modules/playwright/index.mjs')).href);break}catch{}}}
const state=process.env.COMMERCE_STATE||path.join(path.dirname(root),'.commerce-state');
const secret=(await readFile(path.join(state,'auth.token'),'utf8')).trim();
const port=process.env.COMMERCE_PORT||'38731',origin=`http://127.0.0.1:${port}`;
const browser=await playwright.chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
  const context=await browser.newContext({viewport:{width:1440,height:1080},acceptDownloads:true});
  await context.addCookies([{name:'commerce_session',value:secret,url:origin,httpOnly:true,sameSite:'Strict'}]);
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(origin+'/legacy');await page.locator('.kpi-value').first().waitFor();
  await goToModule(page,'research');await page.locator('[data-collection-meta=language]').fill('en');
  const original='Price 12.99 USD. Weight 2 kg. Not waterproof.';
  await page.locator('[data-collection-field=subject][data-part=original]').fill(original);
  await page.locator('[data-action=collection-translate]').click();
  await page.waitForFunction(()=>document.querySelector('[data-collection-field=subject][data-part=zh]')?.value.includes('12.99'),null,{timeout:120000});
  assert.equal(await page.locator('[data-collection-field=subject][data-part=original]').inputValue(),original);
  assert.equal(await page.locator('[data-collection-field=subject][data-part=reviewed]').isChecked(),false);
  const zh=await page.locator('[data-collection-field=subject][data-part=zh]').inputValue();assert.match(zh,/2\s*kg/);assert.match(zh,/不防水/);
  const download=page.waitForEvent('download');await page.locator('[data-action=collection-export]').click();const file=await download;const bundle=JSON.parse(await readFile(await file.path(),'utf8'));
  const provenance=bundle.record.fields.subject.translation;
  assert.equal(provenance.original_sha256.length,64);assert.equal(provenance.model_output_sha256.length,64);assert.equal(provenance.model_output,zh);assert.ok(provenance.job_id);assert.ok(provenance.model);assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(root,'qa/workbench-translation.png')});
  const result={status:'passed',synthetic:true,service:'existing shared local backend',model:provenance.model,provider:provenance.provider,job_id:provenance.job_id,original,zh,checks:['actual UI starts persisted translation job','current configured model returns Chinese','original unchanged','numbers, currency, unit and negation preserved','translation pending review','export includes initial model output and matching source/output hashes','no browser runtime exceptions'],limits:['One synthetic UI sample, not a quality benchmark','No external marketplace actions','Local-model comparison not performed']};
  await writeFile(path.join(root,'qa/workbench-model-live.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){await writeFile(path.join(root,'qa/workbench-model-live.json'),JSON.stringify({status:'failed',synthetic:true,error:error.message},null,2));throw error}
finally{await browser.close()}
