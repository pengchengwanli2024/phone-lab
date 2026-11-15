// Actual shared UI/API against private synthetic state; no real model or channel.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),output=process.env.QA_OUTPUT_DIR;
assert.ok(output&&process.env.COMMERCE_PYTHON&&process.env.PLAYWRIGHT_MODULE);await mkdir(output,{recursive:true});
const{chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const state=await mkdtemp(path.join(tmpdir(),'commerce-autoloop-'));
const socket=net.createServer();await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
const origin='http://127.0.0.1:'+port,secret='synthetic-followup-only';
const child=spawn(process.env.COMMERCE_PYTHON,[path.join(root,'qa/fixture_followups.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port)},stdio:['ignore','ignore','pipe']});
let log='';child.stderr.on('data',chunk=>{log=(log+chunk).slice(-4000);});const ended=new Promise(resolve=>child.once('close',resolve));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const invoke=async(tool,args={})=>{
 const response=await fetch(origin+'/v1/invoke',{method:'POST',headers:{authorization:'Bearer '+secret,'content-type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'test'})});assert.equal(response.status,200,tool);return response.json();
};
let browser,page;const errors=[],calls=[],checks=[];
try{
 let ready=false;for(let n=0;n<100;n++){try{await invoke('commerce_followup_list');ready=true;break;}catch{}await pause(100);}assert.ok(ready,log);
 const tasksBefore=await invoke('commerce_task_list'),runsBefore=await invoke('commerce_agent_list');
 const target=(await invoke('commerce_followup_targets')).targets.find(value=>value.target.kind==='public_source'&&value.target.ref==='usgs').target;
 const book=async key=>invoke('commerce_followup_create',{target,due_at:new Date(Date.now()+60000).toISOString(),idempotency_key:key});
 const advance=async()=>{const response=await fetch(origin+'/qa/followup-advance',{method:'POST',headers:{authorization:'Bearer '+secret,'content-type':'application/json'},body:'{}'});assert.equal(response.status,200);return response.json();};
 await book('one');await advance();await book('two');await advance();
 const notices=(await invoke('commerce_attention_list',{include_followups:true})).items.filter(value=>value.source==='followup');assert.equal(notices.length,1);assert.equal(notices[0].followup_count,2);
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1440,height:1000},extraHTTPHeaders:{authorization:'Bearer '+secret}});
 await context.route('**/*',route=>route.request().url().startsWith(origin)||route.request().url().startsWith('about:')?route.continue():route.abort());
 page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(request.url().endsWith('/v1/invoke'))calls.push(request.postDataJSON().tool);});
 await page.goto(origin+'/workspace?tab=overview');await page.locator('button.r-notice').filter({hasText:'复查：'}).click();
 const dialog=page.getByRole('dialog',{name:'复查计划'});await dialog.getByRole('button',{name:'标记2条已查看',exact:true}).waitFor();
 checks.push('same bound object has one notice while original receipts remain');
 await book('three');await advance();await dialog.getByRole('button',{name:'标记2条已查看',exact:true}).click();
 await dialog.getByRole('alert').filter({hasText:'已有新的复查回执'}).waitFor();
 assert.equal((await invoke('commerce_followup_list')).items.filter(value=>value.state==='checked').length,3);
 await dialog.getByRole('button',{name:'刷新计划',exact:true}).click();await dialog.getByRole('button',{name:'标记3条已查看',exact:true}).waitFor();
 await dialog.locator('summary').filter({hasText:'任务时间线'}).click();await dialog.getByText('已保存复查回执',{exact:true}).waitFor();
 await dialog.getByRole('button',{name:'标记3条已查看',exact:true}).click();await dialog.getByText('已查看回执',{exact:true}).first().waitFor();
 assert.equal((await invoke('commerce_followup_list')).items.filter(value=>value.state==='acknowledged').length,3);
 checks.push('stale group acknowledgment cannot consume a new unseen receipt');
 checks.push('follow-up timeline reads the original durable receipt');
 await page.keyboard.press('Escape');await page.getByRole('button',{name:'任务',exact:true}).click();
 const row=page.getByRole('row').filter({hasText:'合成时间线任务'});await row.getByRole('button',{name:'查看回执',exact:true}).click();
 const taskDialog=page.getByRole('dialog',{name:'任务与执行回执'});await taskDialog.locator('summary').filter({hasText:'任务时间线'}).click();
 await taskDialog.getByText('任务链额度',{exact:true}).waitFor();await taskDialog.getByText('本地执行结束回执',{exact:true}).waitFor();
 assert.ok((await taskDialog.innerText()).includes('模型步骤 2 / 24'));
 checks.push('original task history joins human approval, model steps, local execution and chain allowance');
 for(const[width,theme]of[[1440,'light'],[390,'light'],[1440,'dark'],[390,'dark']]){
  await page.setViewportSize({width,height:1000});await page.evaluate(value=>document.documentElement.setAttribute('data-theme',value),theme);
  assert.equal(await taskDialog.evaluate(node=>node.scrollWidth>node.clientWidth+1),false);
  await page.screenshot({path:path.join(output,`timeline-${width}-${theme}.png`),fullPage:true});
 }
 checks.push('1440px/390px light/dark timeline layouts and keyboard dialog exit');
 await page.keyboard.press('Escape');assert.equal(await taskDialog.count(),0);
 assert.deepEqual(await invoke('commerce_task_list'),tasksBefore);assert.deepEqual(await invoke('commerce_agent_list'),runsBefore);
 assert.equal(calls.some(name=>['commerce_agent_start','commerce_agent_apply','commerce_copilot_send','commerce_task_execute','commerce_task_retry','commerce_intel_refresh'].includes(name)),false);
 assert.deepEqual(errors,[]);await writeFile(path.join(output,'result.json'),JSON.stringify({checks,errors,original_work_unchanged:true,no_model_or_business_submission:true},null,2)+'\n');console.log(JSON.stringify({passed:checks.length,errors:0}));
}catch(error){await writeFile(path.join(output,'failure.json'),JSON.stringify({error:String(error),log,errors,calls,text:page?(await page.locator('body').innerText()).slice(-6000):''},null,2));await page?.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;}
finally{await browser?.close();if(child.exitCode===null)child.kill('SIGTERM');await ended;}
