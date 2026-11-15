// Actual shared UI and durable follow-up API, entirely synthetic and isolated.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath, pathToFileURL } from 'node:url';

assert.ok(process.env.COMMERCE_PYTHON && process.env.PLAYWRIGHT_MODULE && process.env.QA_OUTPUT_DIR);
const { chromium }=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))), output=process.env.QA_OUTPUT_DIR;
await mkdir(output,{recursive:true});
const work=await mkdtemp(path.join(tmpdir(),'commerce-followups-')),state=path.join(work,'state');await mkdir(state);
const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
const origin='http://127.0.0.1:'+port, secret='synthetic-followup-only';
const child=spawn(process.env.COMMERCE_PYTHON,[path.join(root,'qa/fixture_followups.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port)},stdio:['ignore','ignore','pipe']});
let log='';child.stderr.on('data',chunk=>{log=(log+chunk).slice(-4000);});const ended=new Promise(resolve=>child.once('close',resolve));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const invoke=async(tool,args={})=>{
 const response=await fetch(origin+'/v1/invoke',{method:'POST',headers:{authorization:'Bearer '+secret,'content-type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'test'})});
 assert.equal(response.status,200,tool);return response.json();
};
let browser,page;const calls=[],errors=[],checks=[];
try{
 let ready=false;for(let index=0;index<100;index++){if(child.exitCode!==null)break;try{await invoke('commerce_followup_targets');ready=true;break;}catch{}await pause(100);}
 assert.ok(ready,'fixture startup: '+log);
 const beforeTasks=(await invoke('commerce_task_list')).tasks.length,beforeRuns=(await invoke('commerce_agent_list')).runs.length;
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai',extraHTTPHeaders:{authorization:'Bearer '+secret}});
 await context.route('**/*',route=>route.request().url().startsWith(origin)||route.request().url().startsWith('about:')?route.continue():route.abort());
 page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{if(request.url().endsWith('/v1/invoke')){try{calls.push(request.postDataJSON().tool);}catch{}}});
 await page.goto(origin+'/workspace?tab=overview');await page.locator('.r-notice').first().waitFor();
 const dialog=page.getByRole('dialog',{name:'复查计划'});
 if(process.env.QA_FOLLOWUP_RACE_ONLY!=='1'){
 await page.getByRole('button',{name:'复查计划',exact:true}).click();
 await dialog.getByLabel('复查内容').selectOption('public_source:usgs');
 await dialog.getByRole('button',{name:'预约一次复查',exact:true}).click();
 await dialog.getByText('等待复查',{exact:true}).first().waitFor();
 let rows=(await invoke('commerce_followup_list')).items;assert.equal(rows.length,1);const original=rows[0];
 checks.push('explicit booking persists one version-bound appointment');

 await dialog.getByRole('button',{name:'改期',exact:true}).click();
 const future=await page.evaluate(()=>{const value=new Date(Date.now()+3600000),two=n=>String(n).padStart(2,'0');return `${value.getFullYear()}-${two(value.getMonth()+1)}-${two(value.getDate())}T${two(value.getHours())}:${two(value.getMinutes())}`;});
 await dialog.getByLabel('复查时间').fill(future);await dialog.getByRole('button',{name:'保存新时间',exact:true}).click();
 await dialog.getByRole('button',{name:'取消本次复查',exact:true}).waitFor();
 let updated=await invoke('commerce_followup_get',{followup_id:original.id});assert.ok(new Date(updated.due_at)>new Date(original.due_at));
 await dialog.getByRole('button',{name:'取消本次复查',exact:true}).click();
 await dialog.getByText('已取消复查',{exact:true}).first().waitFor();
 assert.equal((await invoke('commerce_followup_get',{followup_id:original.id})).state,'cancelled');
 checks.push('reschedule and cancellation update the original appointment without touching original work');

 await dialog.getByRole('button',{name:'预约一次复查',exact:true}).click();
 await dialog.getByText('等待复查',{exact:true}).first().waitFor();
 const advance=await context.request.post(origin+'/qa/followup-advance',{data:{}});assert.equal(advance.status(),200);assert.equal((await advance.json()).checks,1);
 await page.keyboard.press('Escape');await page.getByRole('button',{name:'刷新',exact:true}).first().click();
 const card=page.locator('.r-notice').filter({hasText:'复查：'});await card.waitFor();await card.click();
 await dialog.getByText(/尚未发现变化/).waitFor();
 assert.ok(calls.includes('commerce_attention_get'));assert.ok(calls.includes('commerce_followup_get'));
 checks.push('one due receipt appears through the shared attention entry and is revalidated on opening');

 for(const [width,appearance]of [[1440,'light'],[390,'light'],[1440,'dark'],[390,'dark']]){
  await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:appearance});
  assert.equal(await dialog.evaluate(node=>node.scrollWidth>node.clientWidth+1),false,`${width}/${appearance} dialog overflow`);
  await page.screenshot({path:path.join(output,`followups-${width}-${appearance}.png`),fullPage:true});
 }
 checks.push('1440px and 390px light/dark form and receipt layouts');
 await dialog.getByRole('button',{name:'标记已查看',exact:true}).click();
 await dialog.getByText('已查看回执',{exact:true}).first().waitFor();
 await page.keyboard.press('Escape');
 await page.waitForFunction(()=>!Array.from(document.querySelectorAll('.r-notice')).some(node=>node.textContent.includes('复查：')));
 checks.push('acknowledgment clears only the follow-up attention receipt and Escape closes the dialog');
 }

 // Exercise out-of-order history reads and a scope change after detail display.
 await page.setViewportSize({width:1440,height:1000});
 const catalog=(await invoke('commerce_followup_targets')).targets;
 const attentionChoice=catalog.find(value=>value.target.kind==='attention');
 const otherChoice=catalog.find(value=>value.target.kind==='public_source'&&value.target.ref==='gdacs');
 const futureTime=new Date(Date.now()+3600000).toISOString();
 const first=await invoke('commerce_followup_create',{target:otherChoice.target,due_at:futureTime,idempotency_key:'race-first'});
 const second=await invoke('commerce_followup_create',{target:attentionChoice.target,due_at:futureTime,idempotency_key:'race-second'});
 await page.getByRole('button',{name:'复查计划',exact:true}).click();
 await dialog.locator('button.r-notice').filter({hasText:second.label}).waitFor();
 let hold=true,held,failHeld,release;
 const requestHeld=new Promise((resolve,reject)=>{held=resolve;failHeld=reject;}),released=new Promise(resolve=>{release=resolve;});
 await page.route('**/v1/invoke',async route=>{
  const args=route.request().postDataJSON();
  if(hold&&args.tool==='commerce_followup_get'&&args.arguments.followup_id===first.id){
   try{hold=false;const response=await route.fetch();assert.equal((await response.json()).id,first.id);held();await released;await route.fulfill({response});}
   catch(failure){failHeld(failure);await route.abort();}
  }else await route.fallback();
 });
 await dialog.locator('button.r-notice').filter({hasText:first.label}).click();await requestHeld;
 const secondResponse=page.waitForResponse(response=>{try{return response.request().postDataJSON()?.arguments?.followup_id===second.id;}catch{return false;}});
 await dialog.locator('button.r-notice').filter({hasText:second.label}).click();await (await secondResponse).finished();
 await dialog.locator('section.card h3').filter({hasText:second.label}).waitFor();
 const lateResponse=page.waitForResponse(response=>{try{return response.request().postDataJSON()?.arguments?.followup_id===first.id;}catch{return false;}});
 release();await (await lateResponse).finished();await pause(800);
 const regressions=[];
 if(await dialog.locator('section.card h3').innerText()!==second.label)regressions.push('late older detail replaced the latest selection');
 await dialog.locator('button.r-notice').filter({hasText:second.label}).click();
 await dialog.locator('section.card h3').filter({hasText:second.label}).waitFor();
 const source=(await invoke('commerce_attention_get',{item_id:attentionChoice.target.ref})).item;
 const thread=await invoke('commerce_copilot_get',{thread_id:source.thread_id});
 await invoke('commerce_copilot_context',{thread_id:thread.id,context:{module:'products',demo:false},expected_context_sha256:thread.context_sha256});
 await dialog.getByRole('button',{name:'返回原工作',exact:true}).click();await pause(200);
 if(!await dialog.isVisible())regressions.push('stale original action navigated after a context change');
 else await dialog.getByText('原工作范围已变化，请核对当前资料。',{exact:true}).waitFor();
 assert.deepEqual(regressions,[]);
 checks.push('late detail reads cannot replace the latest history selection');
 checks.push('original navigation rechecks current scope before leaving the receipt');
 await page.keyboard.press('Escape');

 assert.equal((await invoke('commerce_task_list')).tasks.length,beforeTasks);
 assert.equal((await invoke('commerce_agent_list')).runs.length,beforeRuns);
 assert.equal(calls.some(name=>['commerce_task_execute','commerce_task_retry','commerce_agent_start','commerce_agent_apply','commerce_copilot_send','commerce_copilot_apply','commerce_intel_refresh','commerce_crawler_start'].includes(name)),false);
 assert.deepEqual(errors,[]);
 await writeFile(path.join(output,'result.json'),JSON.stringify({checks,errors,original_tasks_unchanged:true,model_or_execution_submissions:false},null,2)+'\n');
 console.log(JSON.stringify({passed:checks.length,errors:errors.length}));
}catch(error){
 await writeFile(path.join(output,'failure.json'),JSON.stringify({error:String(error),calls,errors,log,text:page?(await page.locator('body').innerText()).slice(-7000):log},null,2));
 await page?.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;
}finally{await browser?.close();if(child.exitCode===null)child.kill('SIGTERM');await ended;}
