// Actual browser + isolated installed Harness bridge acceptance. No shared host restart.
import {fork,spawn,spawnSync} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,readFile,symlink,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const source=process.argv[2];if(!source)throw Error('private source package required');
const output=path.resolve(root,'.local/social-intel/integration');await mkdir(output,{recursive:true});
const tmp=await mkdtemp(path.join(tmpdir(),'social-clients-')),state=path.join(tmp,'state'),profile=path.join(tmp,'host');
await mkdir(state);await mkdir(path.join(profile,'node_modules/@local'),{recursive:true});await symlink(path.join(root,'commerce/harness'),path.join(profile,'node_modules/@local/dsh-commerce'));
await writeFile(path.join(profile,'package.json'),JSON.stringify({name:'social-isolated-acceptance',private:true,dependencies:{'@local/dsh-commerce':'link:'+path.join(root,'commerce/harness')},dsh:{profile:{bundles:['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','@local/dsh-commerce']}}}));
const seed=spawnSync('python3',[path.join(root,'commerce/social_intel/qa_seed.py'),state,path.resolve(source)],{encoding:'utf8'});assert.equal(seed.status,0,seed.stderr);
const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
const env={...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port)};
const server=spawn('python3',[path.join(root,'commerce/server.py')],{env,stdio:'ignore'});
const delay=ms=>new Promise(r=>setTimeout(r,ms));let chrome,host,ws,frameSocket;let seq=0;const waiting=new Map(),errors=[];
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++seq,t=setTimeout(()=>{waiting.delete(id);reject(Error('CDP timeout '+method))},15000);waiting.set(id,{resolve:v=>{clearTimeout(t);resolve(v)},reject});ws.send(JSON.stringify({id,method,params}))})}
async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value}
async function until(ev,expression){for(let i=0;i<150;i++){if(await ev(expression))return;await delay(80)}throw Error('UI condition timed out: '+expression)}
async function checks(ev,scope){
  await until(ev,`!!document.querySelector('[data-tab="intelligence"]')&&!!document.querySelector('.kpi-value')`);
  await ev(`document.querySelector('[data-tab="intelligence"]').click()`);
  await until(ev,`!!document.querySelector('[data-intel-section="social"]')`);
  await ev(`document.querySelector('[data-intel-section="social"]').click()`);
  await until(ev,`document.querySelectorAll('.social-cards>li').length===3`);
  assert.equal(await ev(`document.querySelectorAll('.social-cards>li').length`),3);
  await ev(`document.querySelector('#social-filter').value='top';document.querySelector('#social-search').requestSubmit()`);
  await until(ev,`!!document.querySelector('.social-workspace .ui-empty')&&!document.querySelector('.social-cards')`);
  assert.ok(await ev(`document.querySelector('.social-workspace').textContent.includes('没有满足条件')`));
  await ev(`document.querySelector('#social-filter').value='all';document.querySelector('#social-category').value='ai';document.querySelector('#social-search').requestSubmit()`);
  await until(ev,`!document.querySelector('[data-social-action="search"]').disabled`);
  assert.equal(await ev(`document.querySelectorAll('.social-cards>li').length`),0);
  await ev(`document.querySelector('#social-category').value='all';document.querySelector('#social-query').value='Soap dispenser';document.querySelector('#social-search').requestSubmit()`);
  await until(ev,`document.querySelectorAll('.social-cards>li').length===1`);
  await ev(`document.querySelector('[data-social-action="open"]').click()`);
  await until(ev,`!!document.querySelector('#social-reading-title')`);
  assert.ok(await ev(`document.querySelector('.social-reading').textContent.includes('包含 AI 生成素材')`));
  assert.ok(await ev(`document.querySelector('.social-reading blockquote').textContent.includes('Soap dispenser')`));
  assert.ok(await ev(`document.querySelector('.social-evidence').textContent.includes('内容 SHA-256')`));
  assert.equal(await ev(`document.activeElement.id`),'social-reading-title');
  await ev(`document.querySelector('[data-social-action="asset"]').click()`);
  await until(ev,`!!document.querySelector('.social-evidence img')||!!document.querySelector('.social-workspace [role="alert"]')`);
  assert.ok(await ev(`!!document.querySelector('.social-evidence img')`),await ev(`document.querySelector('.social-workspace [role="alert"]')?.textContent||''`));
  assert.ok(await ev(`document.querySelector('.social-evidence img').naturalWidth>0`));
  const beforeBookmark=await ev(`document.querySelector('[data-social-action="bookmark"]').textContent`);
  await ev(`document.querySelector('[data-social-action="bookmark"]').click()`);
  await until(ev,`document.querySelector('[data-social-action="bookmark"]')?.textContent!==${JSON.stringify(beforeBookmark)}`);
  await ev(`document.querySelector('#ui-theme').value='dark';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);
  await until(ev,`CommerceUI.getTheme().resolved==='dark'&&!document.querySelector('#ui-theme').disabled`);
  assert.equal(await ev(`getComputedStyle(document.body).backgroundColor`),'rgb(18, 18, 18)');
  await ev(`document.querySelector('#ui-theme').value='light';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);
  await until(ev,`CommerceUI.getTheme().resolved==='light'&&!document.querySelector('#ui-theme').disabled`);
  await cdp('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'dark'}]});
  await ev(`document.querySelector('#ui-theme').value='system';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);
  await until(ev,`CommerceUI.getTheme().preference==='system'&&CommerceUI.getTheme().resolved==='dark'&&!document.querySelector('#ui-theme').disabled`);
  await cdp('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'light'}]});
  await until(ev,`CommerceUI.getTheme().resolved==='light'`);
  await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:1100,deviceScaleFactor:1,mobile:false});await delay(180);
  assert.ok(await ev(`document.documentElement.scrollWidth<=innerWidth+1`));
  await ev(`document.querySelector('[data-social-action="back"]').click()`);
  await until(ev,`!!document.querySelector('.social-cards')`);
  assert.ok(await ev(`document.activeElement.id.startsWith('social-row-')`));
  await ev(`document.querySelector('#social-query').focus()`);
  assert.equal(await ev(`document.activeElement.id`),'social-query');
  await ev(`document.querySelector('[data-intel-section="global"]').click()`);
  assert.ok(await ev(`!!document.querySelector('#intel-search')`));
  const result={status:'passed',scope,checks:['shared social section and three private candidates','truthful TOP and empty AI topic','source text search and readable original/Chinese','original AI-content limitation and evidence hashes','actual chunked evidence preview','shared bookmark and current record','reading/back keyboard focus','light/dark/system theme','390px layout','existing global information preserved'],marketplace_calls:false};
  await writeFile(path.join(output,scope+'-result.json'),JSON.stringify(result,null,2));return result;
}
try{
 let auth;for(let i=0;i<100;i++){try{auth=(await readFile(path.join(state,'auth.token'),'utf8')).trim();const r=await fetch(`http://127.0.0.1:${port}/v1/health`,{headers:{Authorization:'Bearer '+auth}});if(r.ok)break}catch{}await delay(80)}
 chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--disable-background-networking',`--user-data-dir=${path.join(tmp,'chrome')}`,'--remote-debugging-port=0','about:blank'],{stdio:'ignore'});
 let debug;for(let i=0;i<100;i++){try{debug=(await readFile(path.join(tmp,'chrome/DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}await delay(80)}
 const pages=await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json();ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=waiting.get(m.id);if(p){waiting.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text)};
 await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1800,height:1200,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/login?token=${encodeURIComponent(auth)}`});
 const browser=await checks(evaluate,'browser');console.log(JSON.stringify({scope:'browser',status:browser.status}));
 await cdp('Emulation.setDeviceMetricsOverride',{width:1800,height:1200,deviceScaleFactor:1,mobile:false});
 const resources='/Applications/DeepSeek Harness.app/Contents/Resources',runtime=resources+'/app.asar/dsh';
 host=fork(runtime+'/node_modules/@deepseek-ai/dsh-desktop-host/lib/index.js',[runtime,profile,resources+'/runtime/primary-runtime',resources+'/runtime/primary-runtime/dependencies/pnpm/bin/pnpm.mjs',resources+'/runtime/bin'],{execPath:'/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness',execArgv:['--expose-internals'],env:{...env,ELECTRON_RUN_AS_NODE:'1',DSH_CLIENT_VERSION:'0.2.2-rc.1',DSH_HOME:path.join(tmp,'dsh-home'),COMMERCE_PYTHON:process.env.COMMERCE_PYTHON||'/opt/homebrew/bin/python3'},stdio:['ignore','ignore','ignore','ipc']});
 const boot=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('isolated host timeout')),45000);host.on('message',m=>{if(m.type==='ready'){clearTimeout(timer);resolve(m)}else if(m.type==='fatal'){clearTimeout(timer);reject(Error('isolated host failed'))}});host.once('exit',()=>reject(Error('isolated host exited')))});
 await cdp('Page.navigate',{url:boot.url});
 await until(evaluate,`!![...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='电商工作台'||b.textContent.trim()==='电商工作台')`);
 await evaluate(`[...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='电商工作台'||b.textContent.trim()==='电商工作台').click()`);
 let target;for(let i=0;i<100;i++){target=(await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json()).find(t=>t.type==='iframe');if(target)break;await delay(80)}assert.ok(target,'sandbox iframe missing');
 frameSocket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((r,j)=>{frameSocket.onopen=r;frameSocket.onerror=j});let fseq=0;const pending=new Map();
 frameSocket.onmessage=e=>{const m=JSON.parse(e.data);const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}};
 async function frameEval(expression){const id=++fseq;const r=await new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error('frame evaluate timeout')),15000);pending.set(id,{resolve:r=>{clearTimeout(t);resolve(r)},reject});frameSocket.send(JSON.stringify({id,method:'Runtime.evaluate',params:{expression,returnByValue:true,awaitPromise:true}}))});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value}
 const harness=await checks(frameEval,'harness');assert.deepEqual(errors,[]);console.log(JSON.stringify({scope:'installed Harness native bridge',status:harness.status}));
}catch(e){await writeFile(path.join(output,'clients-failure.json'),JSON.stringify({status:'failed',error:e.message,browserErrors:errors},null,2));throw e}
finally{frameSocket?.close();ws?.close();chrome?.kill('SIGTERM');if(host?.connected)host.send({type:'shutdown'});await delay(1000);if(host&&host.exitCode===null)host.kill('SIGTERM');server.kill('SIGTERM');await delay(500);await rm(tmp,{recursive:true,force:true})}
