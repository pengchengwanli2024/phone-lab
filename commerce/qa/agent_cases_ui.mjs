import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,readFile,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),tmp=await mkdtemp(path.join(tmpdir(),'commerce-case-'));
const dir=path.join(root,'../.commerce-state/verification/agent-cases');await mkdir(dir,{recursive:true});
const sock=net.createServer();await new Promise(r=>sock.listen(0,'127.0.0.1',r));const port=sock.address().port;await new Promise(r=>sock.close(r));
const state=path.join(tmp,'state');await mkdir(state);await writeFile(path.join(state,'auth.token'),'synthetic-case-ui');
const server=spawn('python3',[path.join(root,'qa/fixture_agent_cases.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port)},stdio:'ignore'});
const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking',`--user-data-dir=${path.join(tmp,'chrome')}`,'--remote-debugging-port=0','about:blank'],{stdio:'ignore'});
const delay=ms=>new Promise(r=>setTimeout(r,ms));let ws;const waits=new Map(),errors=[];let next=0;
function cdp(method,params={}){const id=++next;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('CDP timeout '+method)),15000);waits.set(id,{resolve:v=>{clearTimeout(timer);resolve(v)},reject});ws.send(JSON.stringify({id,method,params}))})}
async function ev(expression){const r=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value}
async function until(expression){for(let i=0;i<200;i++){if(await ev(expression))return;await delay(80)}throw Error('UI timeout '+expression)}
async function call(tool,args={}){const r=await fetch(`http://127.0.0.1:${port}/v1/invoke`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer synthetic-case-ui'},body:JSON.stringify({tool,arguments:args,client:'test'})});const d=await r.json();if(!r.ok)throw Error(d.error);return d}
async function ask(text){await ev(`document.querySelector('#agent-question').value=${JSON.stringify(text)};document.querySelector('#agent-submit').click()`)}
try{
  let cid;for(let i=0;i<120;i++){try{cid=(await call('commerce_agent_cases')).cases[0]?.id;if(cid)break}catch{}await delay(80)}assert.ok(cid);
  let debug;for(let i=0;i<100;i++){try{debug=(await readFile(path.join(tmp,'chrome/DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}await delay(80)}
  const pages=await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json();ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const q=waits.get(m.id);if(q){waits.delete(m.id);m.error?q.reject(Error(m.error.message)):q.resolve(m.result)}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text)};
  await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/login?token=synthetic-case-ui`});await until(`!!document.querySelector('.r-app')`);await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/legacy`});await until(`!!document.querySelector('.kpi-value')`);await ev(`document.querySelector('[data-tab="agent"]').click()`);await until(`!document.querySelector('#agent-submit').disabled`);
  await ev(`document.querySelector('#agent-topic').value='organization_case';document.querySelector('#agent-topic').dispatchEvent(new Event('change',{bubbles:true}))`);await until(`document.querySelector('#agent-case')?.options.length===2`);
  assert.equal(await ev(`document.querySelector('#agent-case').value`),'','no automatic product choice');
  await ask('检查供应链缺项');await until(`document.querySelector('.agent-root')?.textContent.includes('请明确选择工作项')`);assert.equal((await call('commerce_agent_list')).runs.length,0);
  await ev(`document.querySelector('#agent-case').value=${JSON.stringify(cid)};document.querySelector('#agent-stage').value='S3'`);await ask('分析这个工作项的缺项');
  await until(`document.querySelector('.agent-answer')?.textContent.includes('建议待审阅')`);assert.equal((await call('commerce_task_list')).tasks.length,0);
  await ev(`document.querySelector('[data-agent-action="review"]').click()`);await until(`document.querySelector('.dialog pre')?.textContent.includes('evidence_fingerprint')`);
  await call('commerce_organization_currency',{case_id:cid,currency:'USD'});
  await ev(`document.querySelector('[data-agent-action="apply"]').click()`);await until(`document.querySelector('.toast')?.textContent.includes('依据已变化')`);assert.equal((await call('commerce_task_list')).tasks.length,0);
  await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});await until(`!document.querySelector('.dialog')`);
  await call('commerce_organization_currency',{case_id:cid,currency:'CNY'});
  await ask('重新分析该工作项并提出补齐待办');await until(`document.querySelector('.agent-answer')?.textContent.includes('重新分析该工作项')&&document.querySelector('.agent-answer')?.textContent.includes('建议待审阅')`);
  await ev(`document.querySelector('[data-agent-action="review"]').click();document.querySelector('[data-agent-action="apply"]').click()`);await until(`!document.querySelector('.dialog')&&document.querySelector('.agent-answer')?.textContent.includes('已创建岗位补齐待办')`);
  const run=(await call('commerce_agent_list')).runs[0],task=(await call('commerce_task_list')).tasks[0];assert.equal(task.input.organization_case,cid);assert.equal(task.input.organization_stage,'S3');assert.equal(task.input.execution,'not_requested');
  await ev(`document.querySelector('[data-agent-action="case-check"]').click()`);await until(`!!document.querySelector('[data-case-check-status="HOLD"]')`);
  await call('commerce_organization_record',{case_id:cid,kind:'supply',payload:{currency:'CNY',purchase_cost:30,lead_time_days:14,supplier:'synthetic supplier',source_ref:'synthetic:quote'},idempotency_key:'ui-supply'});
  await ev(`document.querySelector('[data-agent-action="case-check"]').click()`);await until(`!!document.querySelector('[data-case-check-status="PASS"]')`);
  const outcome=await call('commerce_agent_case_check',{run_id:run.id,proposal_id:'P1'});assert.equal(outcome.task.status,'queued');assert.equal(outcome.gate_passed,true);assert.equal(outcome.business_closed,false);
  await cdp('Page.reload');await until(`!!document.querySelector('.kpi-value')`);await ev(`document.querySelector('[data-tab="agent"]').click()`);await until(`document.querySelectorAll('.agent-history>button').length===2`);await ev(`document.querySelector('.agent-history>button').click()`);await until(`document.querySelector('.agent-answer')?.textContent.includes('已创建岗位补齐待办')`);
  await ev(`document.querySelector('#agent-topic').value='organization_case';document.querySelector('#agent-topic').dispatchEvent(new Event('change',{bubbles:true}))`);await until(`!!document.querySelector('#agent-case')`);
  await ev(`document.querySelector('#agent-case').value=${JSON.stringify(cid)};document.querySelector('#agent-case').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#agent-stage').value='S3';document.querySelector('#agent-stage').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('[data-agent-action="case-check"]').click()`);await until(`!!document.querySelector('[data-case-check-status="PASS"]')`);
  for(const theme of ['dark','light']){
    await ev(`document.querySelector('#ui-theme').value='${theme}';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);await until(`document.documentElement.dataset.resolvedTheme==='${theme}'&&!document.querySelector('#ui-theme').disabled`);
    for(const width of [1440,1024,768,390]){await cdp('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});await delay(80);assert.equal(await ev(`document.documentElement.scrollWidth<=innerWidth+1`),true,'overflow '+theme+' '+width)}
  }
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});await ev(`document.querySelector('#ui-theme').value='dark';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);await until(`document.documentElement.dataset.resolvedTheme==='dark'`);
  const shot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(dir,'interface.png'),Buffer.from(shot.data,'base64'));assert.deepEqual(errors,[]);
  const result={status:'passed',synthetic:true,checks:['explicit product and stage selection','no automatic import or model call before selection','case-scoped read and proposal','stale approval creates no task','existing organization handoff reused','actual artifact changes rechecked to PASS while task remains queued','history survives reload','390/768/1024/1440 light and dark','no runtime exception'],model_calls:false};await writeFile(path.join(dir,'browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){await writeFile(path.join(dir,'browser.json'),JSON.stringify({status:'failed',error:error.message,errors},null,2));throw error}
finally{ws?.close();server.kill('SIGTERM');chrome.kill('SIGTERM');await delay(600);await rm(tmp,{recursive:true,force:true})}
