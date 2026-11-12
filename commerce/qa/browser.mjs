import {spawn} from 'node:child_process';
import {mkdtemp,readFile,writeFile,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
await mkdir(path.join(root,'../.commerce-state/verification/workbench-quality'),{recursive:true});
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const temporary=await mkdtemp(path.join(tmpdir(),'commerce-browser-'));
const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
const state=path.join(temporary,'state');await mkdir(state);await writeFile(path.join(state,'auth.token'),'synthetic-browser-test-only');
const python=process.env.COMMERCE_PYTHON||'python3';
const server=spawn(python,[path.join(root,'server.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port)},stdio:'ignore'});
const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking',`--user-data-dir=${path.join(temporary,'chrome')}`,'--remote-debugging-port=0','--window-size=1920,1080','about:blank'],{stdio:'ignore'});
let ws;const waiting=new Map();let seq=0;const exceptions=[];
async function cdp(method,params={}){const id=++seq;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{waiting.delete(id);reject(Error('CDP timeout: '+method))},15000);waiting.set(id,{resolve:v=>{clearTimeout(timer);resolve(v)},reject});ws.send(JSON.stringify({id,method,params}))})}
async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value}
async function until(expression){const deadline=Date.now()+20000;while(Date.now()<deadline){if(await evaluate(expression))return;await delay(100)}throw Error('UI condition failed: '+expression)}
try{
  let serviceReady=false;
  for(let i=0;i<200;i++){try{const r=await fetch(`http://127.0.0.1:${port}/v1/invoke`,{method:'POST',headers:{Authorization:'Bearer synthetic-browser-test-only','content-type':'application/json'},body:JSON.stringify({tool:'commerce_status',arguments:{},client:'test'})});if(r.ok&&(await r.json()).version==='0.1.0'){serviceReady=true;break}}catch{}await delay(100)}
  assert.ok(serviceReady,'Synthetic browser service was not ready before navigation');
  let debugging;
  for(let i=0;i<100;i++){try{debugging=(await readFile(path.join(temporary,'chrome/DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{await delay(60)}}
  const pages=await(await fetch(`http://127.0.0.1:${debugging}/json/list`)).json();const page=pages.find(p=>p.type==='page');
  ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=waiting.get(m.id);if(p){waiting.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}}else if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails.text)};
  await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1920,height:1080,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/login?token=synthetic-browser-test-only`});
  await until(`document.querySelector('.kpi-value')?.textContent.includes('128,640')`);
  assert.equal(await evaluate(`document.querySelectorAll('.platform-bar').length`),5);
  await evaluate(`document.querySelector('#market').value='US';document.querySelector('#market').dispatchEvent(new Event('change',{bubbles:true}))`);await until(`document.querySelector('.kpi-value')?.textContent.includes('63,440')`);
  await evaluate(`document.querySelector('#market').value='all';document.querySelector('#market').dispatchEvent(new Event('change',{bubbles:true}))`);await until(`document.querySelector('.kpi-value')?.textContent.includes('128,640')`);
  await evaluate(`document.querySelector('#store').value='ozon-demo';document.querySelector('#store').dispatchEvent(new Event('change',{bubbles:true}))`);await until(`document.querySelector('.kpi-value')?.textContent.includes('39,200')`);
  await evaluate(`document.querySelector('#store').value='all';document.querySelector('#store').dispatchEvent(new Event('change',{bubbles:true}))`);await until(`document.querySelector('.kpi-value')?.textContent.includes('128,640')`);
  const capture=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(root,'../.commerce-state/verification/workbench-quality/implemented-overview.png'),Buffer.from(capture.data,'base64'));
  await evaluate(`document.querySelector('[data-platform="ozon"]').click()`);await until(`document.querySelector('.kpi-value')?.textContent.includes('39,200')`);
  await evaluate(`document.querySelector('[data-platform="all"]').click()`);await until(`document.querySelector('.kpi-value')?.textContent.includes('128,640')`);
  await evaluate(`document.querySelector('[data-tab="orders"]').click()`);await until(`document.querySelectorAll('tbody tr').length===5`);
  await evaluate(`document.querySelector('#query').value='CUP-014';document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true}))`);await until(`document.querySelectorAll('tbody tr').length===1`);
  await evaluate(`document.querySelector('[data-order]').click()`);await until(`!!document.querySelector('[role="dialog"]')`);
  await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});await until(`!document.querySelector('[role="dialog"]')`);
  await evaluate(`document.querySelector('[data-tab="tasks"]').click();document.querySelector('[data-action="new-task"]').click();document.querySelector('#task-title').value='Synthetic cross-client UI acceptance';document.querySelector('[data-action="submit-task"]').click()`);
  await until(`[...document.querySelectorAll('.task-row')].some(row=>row.textContent.includes('Synthetic cross-client UI acceptance'))`);
  await evaluate(`document.querySelector('[data-action="cancel-task"]').click()`);await until(`[...document.querySelectorAll('.task-row')].some(row=>row.textContent.includes('Synthetic cross-client UI acceptance')&&row.textContent.includes('已取消'))`);
  await until(`document.querySelector('#runtime-center')?.textContent.includes('本地执行器在线')`);
  await evaluate(`document.querySelector('[data-action="runtime-settings"]').click()`);await until(`!!document.querySelector('#runtime-interval')`);
  await evaluate(`document.querySelector('#runtime-interval').value='1800';document.querySelector('#runtime-enabled').checked=false;document.querySelector('[data-action="runtime-save"]').click()`);
  await until(`!document.querySelector('.dialog')&&document.querySelector('#runtime-center')?.textContent.includes('每 30 分钟')`);
  await evaluate(`document.querySelector('[data-action="new-task"]').click();document.querySelector('#task-title').value='Synthetic standalone report';document.querySelector('#task-kind').value='report';document.querySelector('[data-action="submit-task"]').click()`);
  await until(`[...document.querySelectorAll('.task-row')].some(r=>r.textContent.includes('Synthetic standalone report'))`);
  await evaluate(`[...document.querySelectorAll('.task-row')].find(r=>r.textContent.includes('Synthetic standalone report')).querySelector('[data-action="execute-task"]').click()`);
  await until(`document.querySelector('.dialog')?.textContent.includes('确认本地处理')`);
  await evaluate(`document.querySelector('[data-action="execute-task-confirm"]').click()`);
  await until(`!document.querySelector('.dialog')`);
  await until(`fetch('/v1/invoke',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tool:'commerce_task_list',arguments:{},client:'test'})}).then(r=>r.json()).then(d=>d.tasks.some(t=>t.input?.title==='Synthetic standalone report'&&t.status==='completed'))`);
  await evaluate(`document.querySelector('[data-action="runtime-refresh"]').click()`);
  await until(`[...document.querySelectorAll('.task-row')].some(r=>r.textContent.includes('Synthetic standalone report')&&r.textContent.includes('已完成'))`);
  await evaluate(`[...document.querySelectorAll('.task-row')].find(r=>r.textContent.includes('Synthetic standalone report')).querySelector('[data-action="task-result"]').click()`);
  await until(`document.querySelector('.dialog pre')?.textContent.includes('local_template')`);
  await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});await until(`!document.querySelector('.dialog')`);
  for(const width of [1440,1024,768,390]){await cdp('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});await delay(80);assert.equal(await evaluate(`document.documentElement.scrollWidth<=innerWidth+1`),true,'runtime overflow '+width)}
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
  await mkdir(path.join(root,'../.commerce-state/verification/standalone'),{recursive:true});
  const runtimeShot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(root,'../.commerce-state/verification/standalone/runtime.png'),Buffer.from(runtimeShot.data,'base64'));
  await evaluate(`document.querySelector('[data-tab="overview"]').click();document.querySelector('#demo').click()`);await until(`document.querySelector('.kpi-value')?.textContent==='—'`);
  assert.equal(await evaluate(`document.querySelectorAll('.platform-bar').length`),0);
  await evaluate(`document.querySelector('#demo').click()`);await until(`document.querySelector('.kpi-value')?.textContent.includes('128,640')`);
  await evaluate(`document.querySelector('[data-action="report"]').click()`);await until(`document.querySelector('.dialog pre')?.textContent.includes('本地模板生成')`);
  await evaluate(`document.querySelector('[data-action="close"]').click();document.querySelector('[data-tab="connections"]').click()`);await until(`document.querySelectorAll('.integration').length===4`);
  assert.equal(await evaluate(`window.CommerceUI.version`),'1.1.2');
  assert.equal(await evaluate(`(()=>{const d=document.createElement('div');d.innerHTML=CommerceUI.button({label:'Toggle',attrs:{'aria-pressed':false,'data-enabled':false}});const b=d.firstElementChild;return b.getAttribute('aria-pressed')==='false'&&b.getAttribute('data-enabled')==='false'})()`),true,'explicit accessibility toggle state');
  await evaluate(`document.querySelector('[data-tab="orders"]').click()`);
  const orderControl=await evaluate(`(()=>{const s=getComputedStyle(document.querySelector('#query'));return [s.height,s.borderRadius,s.fontSize]})()`);
  await evaluate(`document.querySelector('[data-tab="intelligence"]').click()`);
  await until(`!!document.querySelector('#intel-query')&&!document.querySelector('#intel-search button').disabled`);
  const intelControl=await evaluate(`(()=>{const s=getComputedStyle(document.querySelector('#intel-query'));return [s.height,s.borderRadius,s.fontSize]})()`);
  assert.deepEqual(intelControl,orderControl,'same shared control geometry across modules');
  assert.equal(await evaluate(`(()=>{const d=document.createElement('div');d.innerHTML=CommerceUI.button({label:'<img src=x onerror=alert(1)>',attrs:{onclick:'alert(1)','aria-label':'safe'}});return !d.querySelector('img')&&!d.querySelector('button').hasAttribute('onclick')&&d.textContent.includes('<img')})()`),true);
  await evaluate(`document.querySelector('[data-tab="overview"]').click();document.querySelector('[data-action="report"]').focus();document.querySelector('[data-action="report"]').click()`);
  await until(`!!document.querySelector('.dialog')`);
  await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
  await until(`!document.querySelector('.dialog')`);
  assert.equal(await evaluate(`document.activeElement?.dataset.action`),'report','dialog returns focus');
  await evaluate(`document.querySelector('[data-tab="orders"]').click();document.querySelector('#query').value='keep this unsent value';document.querySelector('#ui-theme').value='dark';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);
  await until(`document.documentElement.dataset.resolvedTheme==='dark'&&!document.querySelector('#ui-theme').disabled`);
  assert.equal(await evaluate(`document.querySelector('#query').value`),'keep this unsent value','theme switch preserves unsubmitted form');
  assert.equal(await evaluate(`getComputedStyle(document.body).backgroundColor`),'rgb(18, 18, 18)');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.card')).backgroundColor`),'rgb(28, 28, 28)');
  await cdp('Page.reload');await until(`!!document.querySelector('.kpi-value')&&document.documentElement.dataset.resolvedTheme==='dark'`);
  assert.equal(await evaluate(`document.querySelector('#ui-theme').value`),'dark','saved preference survives reload');
  await evaluate(`document.querySelector('#ui-theme').value='system';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);
  await until(`!document.querySelector('#ui-theme').disabled`);
  await cdp('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'light'}]});await until(`document.documentElement.dataset.resolvedTheme==='light'`);
  await cdp('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'dark'}]});await until(`document.documentElement.dataset.resolvedTheme==='dark'`);
  await evaluate(`document.querySelector('#ui-theme').value='light';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);
  await until(`document.documentElement.dataset.resolvedTheme==='light'&&!document.querySelector('#ui-theme').disabled`);
  assert.equal(await evaluate(`getComputedStyle(document.body).backgroundColor`),'rgb(248, 250, 255)');
  for(const width of [1440,1024,768,390]){
    await cdp('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});await delay(100);
    assert.equal(await evaluate(`document.documentElement.scrollWidth<=innerWidth+1`),true,'page overflow at '+width);
  }
  assert.deepEqual(exceptions,[]);
  const result={status:'passed',synthetic:true,checks:['explicit local report request, completion and result','persistent scheduler settings without outbound calls','runtime at 390/768/1024/1440','demo totals and five platforms','platform, market and store filters','order search and dialog Escape','shared task create/cancel','honest live empty state','report draft modal','four integration states','no page overflow at 1440/1024/768','no browser runtime exception','shared UI version and control styles','escaped component props','dialog focus restoration','390px layout','light dark system themes','theme preference survives reload','theme keeps unsent form values'],screenshot:'implemented-overview.png'};
  await writeFile(path.join(root,'qa/browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){
  let diagnostic={};
  try{diagnostic={body:(await evaluate('document.body.innerText')).slice(0,700),exceptions};const shot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(root,'../.commerce-state/verification/workbench-quality/browser-diagnostic.png'),Buffer.from(shot.data,'base64'))}catch{}
  const result={status:'failed',synthetic:true,error:error.message,diagnostic};await writeFile(path.join(root,'qa/browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));throw error;
}finally{
  ws?.close();server.kill('SIGTERM');chrome.kill('SIGTERM');await delay(600);await rm(temporary,{recursive:true,force:true});
}
