import {fork,spawn,execFileSync} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,readFile,symlink,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const tmp=await mkdtemp(path.join(tmpdir(),'commerce-harness-'));
const profile=path.join(tmp,'profile'),state=path.join(tmp,'state');await mkdir(path.join(profile,'node_modules/@local'),{recursive:true});await mkdir(state);
await symlink(path.join(root,'harness'),path.join(profile,'node_modules/@local/dsh-commerce'));
const exposureCase=execFileSync(process.env.COMMERCE_PYTHON||'python3',['-c',`import sys;sys.path[:0]=sys.argv[1:3];from service import Commerce;from fixture_agent_cases import seed;from test_pilot_bridge import seed as seedpilot;app=Commerce(sys.argv[3]);seedpilot(app);print(seed(app))`,root,path.join(root,'qa'),state],{encoding:'utf8'}).trim();
await writeFile(path.join(profile,'package.json'),JSON.stringify({name:'commerce-isolated-acceptance',private:true,dependencies:{'@local/dsh-commerce':'link:'+path.join(root,'harness')},dsh:{profile:{bundles:['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','@local/dsh-commerce']}}}));
const l=net.createServer();await new Promise(r=>l.listen(0,'127.0.0.1',r));const port=l.address().port;await new Promise(r=>l.close(r));
const resources='/Applications/DeepSeek Harness.app/Contents/Resources',runtime=resources+'/app.asar/dsh';
const host=fork(runtime+'/node_modules/@deepseek-ai/dsh-desktop-host/lib/index.js',[runtime,profile,resources+'/runtime/primary-runtime',resources+'/runtime/primary-runtime/dependencies/pnpm/bin/pnpm.mjs',resources+'/runtime/bin'],{execPath:'/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness',execArgv:['--expose-internals'],env:{...process.env,ELECTRON_RUN_AS_NODE:'1',DSH_CLIENT_VERSION:'0.2.2-rc.1',DSH_HOME:path.join(tmp,'dsh-home'),COMMERCE_STATE:state,COMMERCE_PORT:String(port),COMMERCE_PYTHON:process.env.COMMERCE_PYTHON||'/opt/homebrew/bin/python3'},stdio:['ignore','pipe','pipe','ipc']});
const errors=[];for(const stream of [host.stdout,host.stderr])stream.on('data',chunk=>{for(const line of String(chunk).split('\n'))if(/error|failed|cannot|missing/i.test(line)&&!/token|cookie|authorization|bearer/i.test(line))errors.push(line.slice(0,280))});
let chrome,ws,frameSocket;const delay=ms=>new Promise(r=>setTimeout(r,ms));const contexts=new Set();const waits=new Map();let next=0;
async function cdp(method,params={}){const id=++next;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{waits.delete(id);reject(Error('CDP timeout '+method))},15000);waits.set(id,{resolve:x=>{clearTimeout(timer);resolve(x)},reject});ws.send(JSON.stringify({id,method,params}))})}
async function ev(expression,contextId){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,...contextId?{contextId}:{}});return r.result?.value}
try{
  const boot=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Isolated Host startup timeout')),45000);host.on('message',m=>{if(m.type==='ready'){clearTimeout(timer);resolve(m)}else if(m.type==='fatal'){clearTimeout(timer);reject(Error('Host fatal: '+String(m.message).replace(/token=[^\s&]+/g,'token=<redacted>')))}});host.once('exit',code=>reject(Error('Host exited '+code)))});
  const auth=await fetch(boot.url,{redirect:'manual'});const cookie=auth.headers.getSetCookie().map(x=>x.split(';')[0]).join('; ');assert.ok(cookie);await auth.body?.cancel();
  const origin=new URL(boot.url).origin;
  const unauth=await fetch(origin+'/api/commerce/page');assert.equal(unauth.status,401);await unauth.body?.cancel();
  const page=await fetch(origin+'/api/commerce/page',{headers:{cookie}});assert.equal(page.status,200);assert.match(await page.text(),/commerce_dashboard/);
  const invoke=await fetch(origin+'/api/commerce/invoke',{method:'POST',headers:{cookie,'content-type':'application/json'},body:JSON.stringify({tool:'commerce_status',arguments:{}})});assert.equal(invoke.status,200);assert.equal((await invoke.json()).version,'0.1.0');
  chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking',`--user-data-dir=${path.join(tmp,'chrome')}`,'--remote-debugging-port=0','about:blank'],{stdio:'ignore'});
  let debug;
  for(let i=0;i<100;i++){try{debug=(await readFile(path.join(tmp,'chrome/DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{await delay(60)}}
  const pages=await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json();ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const q=waits.get(m.id);if(q){waits.delete(m.id);m.error?q.reject(Error(m.error.message)):q.resolve(m.result)}}else if(m.method==='Runtime.executionContextCreated')contexts.add(m.params.context.id);else if(m.method==='Runtime.executionContextDestroyed')contexts.delete(m.params.executionContextId);else if(m.method==='Runtime.executionContextsCleared')contexts.clear()};
  await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1920,height:1080,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url:boot.url});
  let clicked=false;
  for(let i=0;i<150;i++){
    clicked=await ev(`(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='电商工作台'||b.textContent.trim()==='电商工作台');if(b){b.click();return true}return false})()`);
    if(clicked)break;
    if(i===50)await ev(`(()=>{const b=[...document.querySelectorAll('button')].find(b=>/^(More|更多)/i.test(b.getAttribute('aria-label')||''));b?.click()})()`);
    await delay(100);
  }
  assert.ok(clicked,'Commerce sidebar entry was not available');
  // A sandboxed opaque iframe is a separate process/target in Chromium.
  let target;
  for(let i=0;i<100;i++){target=(await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json()).find(t=>t.type==='iframe');if(target)break;await delay(80)}
  assert.ok(target,'Sandboxed iframe target missing');
  frameSocket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((r,j)=>{frameSocket.onopen=r;frameSocket.onerror=j});
  let fseq=0;const fwait=new Map();
  frameSocket.onmessage=e=>{const m=JSON.parse(e.data);const p=fwait.get(m.id);if(p){fwait.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}};
  async function feval(expression){const id=++fseq;const r=await new Promise((resolve,reject)=>{fwait.set(id,{resolve,reject});frameSocket.send(JSON.stringify({id,method:'Runtime.evaluate',params:{expression,returnByValue:true,awaitPromise:true}}))});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result?.value}
  let ready=false;
  for(let i=0;i<100;i++){if((await feval(`document.querySelector('.kpi-value')?.textContent`))?.includes('128,640')){ready=true;break}await delay(80)}
  assert.ok(ready,'Commerce iframe did not receive authenticated service data');
  assert.equal(await feval(`document.querySelectorAll('.platform-bar').length`),5);
  await feval(`document.querySelector('[data-tab="connections"]').click()`);
  assert.equal(await feval(`document.querySelectorAll('.integration').length`),4);
  await feval(`document.querySelector('[data-tab="intelligence"]').click()`);
  for(let i=0;i<100;i++){if(await feval(`document.querySelectorAll('.intel-source-strip .intel-source-pill').length>=3&&!document.querySelector('#intel-search button').disabled`))break;await delay(80)}
  const expectedSourceIds=JSON.parse((await import('node:child_process')).execFileSync('python3',['-c',`import sys,json;sys.path.insert(0,sys.argv[1]);from intelligence import SOURCES;print(json.dumps(list(SOURCES)))`,root],{encoding:'utf8'}));
  const actualSourceIds=await feval(`[...document.querySelectorAll('.intel-source-strip .intel-source-pill')].map(n=>n.dataset.source||n.id)`);
  assert.deepEqual(actualSourceIds.sort(),expectedSourceIds.sort(),'source inventory rendered without dropping concurrent additions');
  assert.equal(await feval(`document.querySelector('#intel-map-svg').getAttribute('viewBox')`),'0 0 720 360');
  assert.equal(await feval(`window.CommerceUI.version`),'1.1.2');
  await ev(`window.__commerceIntelSubmitted=false;window.addEventListener('message',e=>{if(e.data?.type==='commerce:call'&&e.data.tool==='commerce_intel_search'&&e.data.arguments?.query==='地震')window.__commerceIntelSubmitted=true})`);
  await feval(`document.querySelector('#intel-query').value='地震';document.querySelector('#intel-search button').click()`);
  for(let i=0;i<100;i++){if(await ev(`window.__commerceIntelSubmitted`))break;await delay(50)}
  assert.equal(await ev(`window.__commerceIntelSubmitted`),true,'shared control submits through sandbox bridge');
  await feval(`document.querySelector('#ui-theme').value='dark';document.querySelector('#ui-theme').dispatchEvent(new Event('change',{bubbles:true}))`);
  for(let i=0;i<100;i++){if(await feval(`document.documentElement.dataset.resolvedTheme==='dark'&&!document.querySelector('#ui-theme').disabled`))break;await delay(50)}
  assert.equal(await feval(`getComputedStyle(document.body).backgroundColor`),'rgb(18, 18, 18)');
  assert.equal(await feval(`document.querySelector('#ui-theme').value`),'dark');
  await feval(`document.querySelector('[data-tab="overview"]').click()`);
  await ev(`(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='继续');b?.click()})()`);
  await delay(150);
  await feval(`document.querySelector('[data-tab="tasks"]').click()`);
  for(let i=0;i<100;i++){if(await feval(`!!document.querySelector('#runtime-center')`))break;await delay(100)}
  assert.ok(await feval(`document.querySelector('#runtime-center')?.textContent.includes('独立运行中心')`),'runtime through native bridge');
  await feval(`document.querySelector('[data-action="runtime-settings"]').click()`);
  assert.ok(await feval(`!!document.querySelector('#runtime-interval')`),'runtime dialog in no-forms iframe');
  await feval(`document.querySelector('[data-action="close"]').click()`);
  await feval(`document.querySelector('[data-tab="agent"]').click()`);
  for(let i=0;i<100;i++){if(await feval(`!!document.querySelector('#agent-submit')&&!document.querySelector('#agent-submit').disabled`))break;await delay(100)}
  assert.ok(await feval(`document.querySelector('#agent-role')?.options.length>=5`),'shared role request form through native bridge');
  await feval(`document.querySelector('#agent-topic').value='organization_case';document.querySelector('#agent-topic').dispatchEvent(new Event('change',{bubbles:true}))`);
  assert.equal(await feval(`document.querySelector('#agent-case')?.value`),'','native panel never substitutes a work item');
  assert.ok(await feval(`document.querySelector('#agent-case')?.options.length>=1`),'scoped work-item picker through native bridge');
  await feval(`document.querySelector('[data-tab="exposure"]').click()`);
  for(let i=0;i<100;i++){if(await feval(`document.querySelector('#exposure-case')?.options.length>=2`))break;await delay(80)}
  assert.equal(await feval(`document.querySelector('#exposure-case').value`),'','business mapping requires explicit native selection');
  await feval(`document.querySelector('#exposure-case').value=${JSON.stringify(exposureCase)};document.querySelector('#exposure-case').dispatchEvent(new Event('change',{bubbles:true}))`);
  for(let i=0;i<100;i++){if(await feval(`!!document.querySelector('#exposure-add')`))break;await delay(80)}
  await feval(`document.querySelector('#exposure-add').click();document.querySelector('#exposure-label').value='Synthetic native market';document.querySelector('#exposure-countries').value='MEX';document.querySelector('#exposure-source_ref').value='synthetic:native-bridge';document.querySelector('#exposure-save').click()`);
  for(let i=0;i<100;i++){if(await feval(`!document.querySelector('.dialog')&&document.querySelector('.exposure-root')?.textContent.includes('Synthetic native market')`))break;await delay(80)}
  assert.ok(await feval(`document.querySelector('.exposure-root')?.textContent.includes('Synthetic native market')`),'shared mapping save through native no-forms iframe');
  await feval(`document.querySelector('[data-tab="platforms"]').click()`);
  for(let i=0;i<100;i++){if(await feval(`document.querySelector('.platform-root')?.textContent.includes('Amazon')&&document.querySelector('.platform-root')?.textContent.includes('Temu')`))break;await delay(80)}
  assert.equal(await feval(`document.querySelector('#platform-store')?.value`),'','native platform picker does not select a store');
  assert.ok(await feval(`document.querySelector('.platform-root')?.textContent.includes('Amazon')&&document.querySelector('.platform-root')?.textContent.includes('Temu')`),'current platform catalog through native shared bridge');
  await feval(`document.querySelector('[data-tab="pilots"]').click()`);
  for(let i=0;i<100;i++){if(await feval(`document.querySelector('#pilot-select')?.options.length===2`))break;await delay(80)}
  assert.equal(await feval(`document.querySelector('#pilot-select')?.value`),'','native pilot selection remains explicit');
  await feval(`document.querySelector('#pilot-select').value='synthetic-household-pilot';document.querySelector('#pilot-select').dispatchEvent(new Event('change',{bubbles:true}))`);
  for(let i=0;i<100;i++){if(await feval(`!!document.querySelector('[data-pilot-action="link"]')`))break;await delay(80)}
  await feval(`document.querySelector('[data-pilot-action="link"]').click();document.querySelector('[data-pilot-action="confirm"]').click()`);
  for(let i=0;i<100;i++){if(await feval(`document.querySelector('.pilot-root')?.textContent.includes('已关联当前来源版本')`))break;await delay(80)}
  assert.ok(await feval(`document.querySelector('.pilot-root')?.textContent.includes('已关联当前来源版本')`),'versioned existing pilot link through native shared bridge');
  const shot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(root,'qa/implemented-harness.png'),Buffer.from(shot.data,'base64'));
  const result={status:'passed',runtime:'installed DeepSeek Harness desktop host 0.2.2-rc.1',isolation:'temporary profile and state',checks:['platform catalogue and explicit selection through native bridge','existing pilot source link through native bridge without duplicate tasks','explicit business mapping and synthetic save through native no-forms bridge (no model call)','explicit work-item picker through native bridge (no model call)','bounded role UI and current shared roles through native bridge (no model call)','runtime status through native iframe bridge and settings modal','host bundle activation','unauthenticated page rejected','authenticated Connection Fetch routes','native sidebar panel registration','sandboxed iframe bridge receives five-platform data','connections view','global intelligence through native bridge','shared UI version and no-forms search submission','dark theme saved through native bridge'],warnings:errors};
  await writeFile(path.join(root,'qa/harness-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){await writeFile(path.join(root,'qa/harness-result.json'),JSON.stringify({status:'failed',error:error.message,warnings:errors},null,2));throw error}
finally{
  frameSocket?.close();ws?.close();chrome?.kill('SIGTERM');if(host.connected)host.send({type:'shutdown'});await delay(1500);if(host.exitCode===null)host.kill('SIGTERM');
  try{const descriptor=JSON.parse(await readFile(path.join(state,'runtime.json'),'utf8'));process.kill(descriptor.pid,'SIGTERM')}catch{}
  await delay(500);await rm(tmp,{recursive:true,force:true});
}
