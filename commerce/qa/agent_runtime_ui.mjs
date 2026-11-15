import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,readFile,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),tmp=await mkdtemp(path.join(tmpdir(),'commerce-agent-'));
const dir=path.join(root,'../.commerce-state/verification/agent-runtime');await mkdir(dir,{recursive:true});
const sock=net.createServer();await new Promise(r=>sock.listen(0,'127.0.0.1',r));const port=sock.address().port;await new Promise(r=>sock.close(r));
const state=path.join(tmp,'state');await mkdir(state);await writeFile(path.join(state,'auth.token'),'synthetic-agent-ui');
const server=spawn('python3',[path.join(root,'qa/fixture_agent_runtime.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port)},stdio:'ignore'});
const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking',`--user-data-dir=${path.join(tmp,'chrome')}`,'--remote-debugging-port=0','about:blank'],{stdio:'ignore'});
const delay=ms=>new Promise(r=>setTimeout(r,ms));let ws;const waits=new Map(),errors=[];let next=0;
function cdp(method,params={}){const id=++next;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('CDP timeout '+method)),15000);waits.set(id,{resolve:v=>{clearTimeout(timer);resolve(v)},reject});ws.send(JSON.stringify({id,method,params}))})}
async function ev(expression){const r=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value}
async function until(expression){for(let i=0;i<200;i++){if(await ev(expression))return;await delay(80)}throw Error('UI timeout '+expression)}
async function call(tool,args={}){const r=await fetch(`http://127.0.0.1:${port}/v1/invoke`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer synthetic-agent-ui'},body:JSON.stringify({tool,arguments:args,client:'test'})});const d=await r.json();if(!r.ok)throw Error(d.error);return d}
async function ask(question,params=''){await ev(`document.querySelector('#agent-question').value=${JSON.stringify(question)};document.querySelector('#agent-parameters').value=${JSON.stringify(params)};document.querySelector('#agent-submit').click()`)}
try{
  for(let i=0;i<120;i++){try{await call('commerce_agent_status');break}catch{}await delay(80)}
  let debug;for(let i=0;i<100;i++){try{debug=(await readFile(path.join(tmp,'chrome/DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}await delay(80)}
  const pages=await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json();ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const q=waits.get(m.id);if(q){waits.delete(m.id);m.error?q.reject(Error(m.error.message)):q.resolve(m.result)}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text)};
  await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/login?token=synthetic-agent-ui`});await until(`!!document.querySelector('.r-app')`);await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/legacy`});await until(`!!document.querySelector('[data-tab="agent"]')&&!!document.querySelector('.kpi-value')`);
  await ev(`document.querySelector('[data-tab="agent"]').click()`);await until(`document.querySelector('#agent-role')?.options.length===12&&!document.querySelector('#agent-submit').disabled`);
  await ask('synthetic report','{"demo":true}');await until(`document.querySelector('.agent-answer')?.textContent.includes('建议待审阅')`);
  assert.equal((await call('commerce_task_list')).tasks.length,0,'model does not approve itself');
  await ev(`document.querySelector('[data-agent-action="review"]').focus();document.querySelector('[data-agent-action="review"]').click()`);await until(`document.querySelector('.dialog pre')?.textContent.includes('"demo": true')`);
  await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});await until(`!document.querySelector('.dialog')`);assert.equal(await ev(`document.activeElement?.dataset.agentAction`),'review');
  await ev(`document.querySelector('[data-agent-action="review"]').click();document.querySelector('[data-agent-action="apply"]').click()`);await until(`!document.querySelector('.dialog')&&document.querySelector('.agent-answer')?.textContent.includes('已提交共享任务')`);
  for(let i=0;i<80;i++){if((await call('commerce_task_list')).tasks[0]?.status==='completed')break;await delay(100)}
  assert.equal((await call('commerce_task_list')).tasks[0].status,'completed');
  const original=(await call('commerce_agent_list')).runs[0];
  await cdp('Page.reload');await until(`!!document.querySelector('.kpi-value')`);await ev(`document.querySelector('[data-tab="agent"]').click()`);await until(`document.querySelectorAll('.agent-history>button').length===1`);
  await ev(`document.querySelector('.agent-history>button').click()`);await until(`document.querySelector('.agent-answer')?.textContent.includes('已提交共享任务')`);
  await ask('clarify');await until(`document.querySelector('.agent-answer')?.textContent.includes('等待补充信息')`);await ev(`document.querySelector('[data-agent-action="reply"]').click()`);
  await ask('已补充，请检查当前状态');await until(`document.querySelector('.agent-answer')?.textContent.includes('分析已返回')`);
  const reply=(await call('commerce_agent_list')).runs[0];assert.ok(reply.parent_id);
  await ev(`document.querySelector('[data-agent-action="new"]').click()`);
  await ask('slow');await until(`document.querySelector('.agent-answer')?.textContent.includes('正在分析')`);await ev(`document.querySelector('[data-agent-action="cancel"]').click()`);await until(`document.querySelector('.agent-answer')?.textContent.includes('已取消')`);
  await ask('unknown');await until(`document.querySelector('.agent-answer')?.textContent.includes('模型结果未知')`);
  const count=(await call('commerce_agent_list')).runs.length;await delay(1600);assert.equal((await call('commerce_agent_list')).runs.length,count,'unknown does not resubmit');
  await ev(`document.querySelector('.agent-history>button:last-child').click()`);await until(`document.querySelector('.agent-answer')?.textContent.includes('synthetic report')`);
  for(const theme of ['dark','light']){
    await ev(`document.querySelector('#ui-theme').value='${theme}';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);await until(`document.documentElement.dataset.resolvedTheme==='${theme}'&&!document.querySelector('#ui-theme').disabled`);
    for(const width of [1440,1024,768,390]){await cdp('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});await delay(80);assert.equal(await ev(`document.documentElement.scrollWidth<=innerWidth+1`),true,'overflow '+theme+' '+width)}
  }
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});await ev(`document.querySelector('#ui-theme').value='dark';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);await until(`document.documentElement.dataset.resolvedTheme==='dark'`);
  const shot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(dir,'interface.png'),Buffer.from(shot.data,'base64'));
  assert.deepEqual(errors,[]);
  const result={status:'passed',synthetic:true,checks:['form DOM values and shared role list','bounded tool read and reviewable answer','no task before explicit approval','review parameters and Escape focus','shared local task completes','history and action survives reload','clarification reply lineage','running cancel','unknown does not retry','390/768/1024/1440 light and dark','no browser exception'],model_calls:false};await writeFile(path.join(dir,'browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){await writeFile(path.join(dir,'browser.json'),JSON.stringify({status:'failed',error:error.message,errors},null,2));throw error}
finally{ws?.close();server.kill('SIGTERM');chrome.kill('SIGTERM');await delay(600);await rm(tmp,{recursive:true,force:true})}
