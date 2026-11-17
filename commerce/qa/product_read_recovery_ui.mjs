// Actual shared HTTP + opaque iframe recovery. No models or marketplace calls.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile,readdir,mkdir,mkdtemp,writeFile,rm} from 'node:fs/promises';
import {homedir,tmpdir} from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),out=path.resolve(process.env.QA_OUTPUT_DIR||'.local/coordination/product-read-recovery-20261116/browser');await mkdir(out,{recursive:true});
const work=await mkdtemp(path.join(tmpdir(),'product-read-qa-')),listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
const origin='http://127.0.0.1:'+port;const env={...process.env,COMMERCE_STATE:work,COMMERCE_PORT:String(port)};
const child=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'qa/fixture_product_reads.py')],{env,stdio:['ignore','ignore','pipe']});let logs='';child.stderr.on('data',c=>logs=(logs+c).slice(-2000));const closed=new Promise(r=>child.once('close',r));
const checks=[],errors=[],external=[],writes=[];let browser,page;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
try{
 let ready=false;for(let i=0;i<100;i++){try{if((await fetch(origin+'/v1/health',{headers:{authorization:'Bearer synthetic-product-read-preview'}})).ok){ready=true;break}}catch{}await pause(100)}assert.ok(ready,logs);
 let pw;for(const id of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',id,'node_modules/playwright/index.mjs')).href);break}catch{}}assert.ok(pw);
 browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});const ctx=await browser.newContext({viewport:{width:1440,height:1080}});
 await ctx.route('**/*',async route=>{const req=route.request();if(new URL(req.url()).origin!==origin){external.push(new URL(req.url()).origin);return route.abort()}if(req.url().endsWith('/v1/invoke')){const tool=req.postDataJSON()?.tool;if(tool&&(/commerce_(?:copilot_send|agent_run|task_execute|listing_.*(?:submit|apply)|live_(?:sync|configure)|creative_(?:generate|execute))/.test(tool)||(tool==='commerce_workspace_save'&&req.postDataJSON().arguments?.form!=='view'))){writes.push(tool);return route.abort()}}return route.continue()});
 page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(18000);
 await ctx.addCookies([{name:'commerce_session',value:'synthetic-product-read-preview',url:origin,httpOnly:true,sameSite:'Strict'}]);
 const {case_id:cid}=JSON.parse(await readFile(path.join(work,'fixture.json'),'utf8'));
 // Exercise the actual Harness HTTP proxy, including its original 15s deadline.
 process.env.COMMERCE_STATE=work;process.env.COMMERCE_PORT=String(port);const routes=new Map();const {apply}=await import('../harness/index.js');await apply({inject(){},connection:{fetch:{register:spec=>routes.set(spec.path,spec)}}});
 const started=Date.now(),response=await routes.get('/api/commerce/invoke').fetch(new Request(origin+'/api/commerce/invoke',{method:'POST',body:JSON.stringify({tool:'commerce_workspace_list',arguments:{}})}));
 const elapsed=Date.now()-started;const result=await response.json();
 if(process.env.COMMERCE_QA_BASELINE_WORKSPACE){assert.equal(response.status,503);assert.equal(result.error,'commerce_service_unavailable');await writeFile(out+'/verification.json',JSON.stringify({status:'reproduced_before_fix',native_proxy_status:503,elapsed_ms:elapsed,source_latency_injected_ms:300,retries:0,synthetic:true},null,2));console.log('Captured original source scan exceeding real Harness proxy deadline');}
 else{
 assert.equal(response.status,200);assert.equal(result.items.length,55);assert.ok(elapsed<5000,'Bounded metadata work must fit the unchanged native deadline');checks.push('55 synthetic products return through the actual Harness proxy under unchanged deadline and 300ms/source-scan latency');
 await writeFile(path.join(work,'.fail-next-workspace-read'),'QA-only one-shot fault');await page.goto(origin+'/?tab=workspace');const frame=page.frameLocator('iframe[title="完整商品内容编辑"]');
 await frame.getByText(/共享后台暂不可用/).waitFor();let journal=JSON.parse(await readFile(path.join(work,'reads.json'),'utf8'));const before=journal.requests.filter(r=>r.tool==='commerce_workspace_list').length;assert.equal(journal.requests.filter(r=>r.tool==='commerce_catalog_list').length,0);checks.push('First read failure stays visible without starting a competing catalog or automatically retrying');
 await frame.getByRole('button',{name:'重新读取',exact:true}).click();await frame.locator('#pw-case option').nth(55).waitFor({state:'attached'});await frame.locator('.catalog-product').first().waitFor();journal=JSON.parse(await readFile(path.join(work,'reads.json'),'utf8'));assert.equal(journal.requests.filter(r=>r.tool==='commerce_workspace_list').length,before+1);assert.equal(journal.requests.filter(r=>r.tool==='commerce_catalog_list').length,1);checks.push('Explicit reread restores all 55 picker options and actual product cards through the opaque iframe');
 await page.goto(origin+'/?tab=workspace&case_id='+cid);const detail=page.frameLocator('iframe[title="完整商品内容编辑"]');await detail.locator('.pw-object-header').waitFor();const after=JSON.parse(await readFile(path.join(work,'reads.json'),'utf8'));assert.equal(after.requests.filter(r=>r.tool==='commerce_catalog_list').length,1);checks.push('A direct product deep link reads its exact details without preloading a hidden catalog');
 await detail.locator('[data-pw-tab="content"]').click();await detail.locator('#pw-content-title').fill('合成未保存商品标题');await detail.locator('[data-pw-action=more]').click();await detail.getByRole('button',{name:'刷新资料',exact:true}).click();assert.equal(await detail.locator('#pw-content-title').inputValue(),'合成未保存商品标题');checks.push('Explicit detail refresh keeps the current unsaved product title');
 for(const width of [1440,390]){await page.setViewportSize({width,height:1080});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:out+'/product-'+width+'.png'})}checks.push('Desktop and narrow layouts remain usable');
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(writes,[]);await writeFile(out+'/verification.json',JSON.stringify({status:'Passed',checks,errors,external,writes,native_proxy_elapsed_ms:elapsed,synthetic:true,source_latency_injected_ms:300,models:0,store_writes:0},null,2));console.log(JSON.stringify({status:'Passed',groups:checks.length}));
 }
}catch(error){await page?.screenshot({path:out+'/failure.png'}).catch(()=>{});await writeFile(out+'/failure.json',JSON.stringify({error:String(error),checks,errors,external,writes,logs},null,2));throw error}
finally{await browser?.close();child.kill('SIGTERM');await closed;await rm(work,{recursive:true,force:true})}
