import {spawn} from 'node:child_process';
import {mkdtemp,readFile,writeFile,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
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
  const capture=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(root,'qa/implemented-overview.png'),Buffer.from(capture.data,'base64'));
  await evaluate(`document.querySelector('[data-platform="ozon"]').click()`);await until(`document.querySelector('.kpi-value')?.textContent.includes('39,200')`);
  await evaluate(`document.querySelector('[data-platform="all"]').click()`);await until(`document.querySelector('.kpi-value')?.textContent.includes('128,640')`);
  await evaluate(`document.querySelector('[data-tab="orders"]').click()`);await until(`document.querySelectorAll('tbody tr').length===5`);
  await evaluate(`document.querySelector('#query').value='CUP-014';document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true}))`);await until(`document.querySelectorAll('tbody tr').length===1`);
  await evaluate(`document.querySelector('[data-order]').click()`);await until(`!!document.querySelector('[role="dialog"]')`);
  await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});await until(`!document.querySelector('[role="dialog"]')`);
  await evaluate(`document.querySelector('[data-tab="tasks"]').click();document.querySelector('[data-action="new-task"]').click();document.querySelector('#task-title').value='Synthetic cross-client UI acceptance';document.querySelector('[data-action="submit-task"]').click()`);
  await until(`[...document.querySelectorAll('.task-row')].some(row=>row.textContent.includes('Synthetic cross-client UI acceptance'))`);
  await evaluate(`document.querySelector('[data-action="cancel-task"]').click()`);await until(`[...document.querySelectorAll('.task-row')].some(row=>row.textContent.includes('Synthetic cross-client UI acceptance')&&row.textContent.includes('已取消'))`);
  await evaluate(`document.querySelector('[data-tab="overview"]').click();document.querySelector('#demo').click()`);await until(`document.querySelector('.kpi-value')?.textContent==='—'`);
  assert.equal(await evaluate(`document.querySelectorAll('.platform-bar').length`),0);
  await evaluate(`document.querySelector('#demo').click()`);await until(`document.querySelector('.kpi-value')?.textContent.includes('128,640')`);
  await evaluate(`document.querySelector('[data-action="report"]').click()`);await until(`document.querySelector('.dialog pre')?.textContent.includes('本地模板生成')`);
  await evaluate(`document.querySelector('[data-action="close"]').click();document.querySelector('[data-tab="connections"]').click()`);await until(`document.querySelectorAll('.integration').length===4`);
  for(const width of [1440,1024,768]){
    await cdp('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});await delay(100);
    assert.equal(await evaluate(`document.documentElement.scrollWidth<=innerWidth+1`),true,'page overflow at '+width);
  }
  assert.deepEqual(exceptions,[]);
  const result={status:'passed',synthetic:true,checks:['demo totals and five platforms','platform, market and store filters','order search and dialog Escape','shared task create/cancel','honest live empty state','report draft modal','four integration states','no page overflow at 1440/1024/768','no browser runtime exception'],screenshot:'implemented-overview.png'};
  await writeFile(path.join(root,'qa/browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){
  let diagnostic={};
  try{diagnostic={body:(await evaluate('document.body.innerText')).slice(0,700),exceptions};const shot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(root,'qa/browser-diagnostic.png'),Buffer.from(shot.data,'base64'))}catch{}
  const result={status:'failed',synthetic:true,error:error.message,diagnostic};await writeFile(path.join(root,'qa/browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));throw error;
}finally{
  ws?.close();server.kill('SIGTERM');chrome.kill('SIGTERM');await delay(600);await rm(temporary,{recursive:true,force:true});
}
