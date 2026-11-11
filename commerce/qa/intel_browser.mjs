import {spawn,spawnSync} from 'node:child_process';
import {mkdtemp,readFile,writeFile,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const live=process.env.COMMERCE_INTEL_LIVE==='1';
const temporary=await mkdtemp(path.join(tmpdir(),'commerce-intel-ui-'));
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const state=path.join(temporary,'state');await mkdir(state);
let port=38731,auth,server;
if(live){auth=(await readFile(path.join(root,'../.commerce-state/auth.token'),'utf8')).trim()}
else{
  const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));port=listener.address().port;await new Promise(r=>listener.close(r));
  auth='synthetic-intel-test-only';await writeFile(path.join(state,'auth.token'),auth);
  const seed=spawnSync('python3',[path.join(root,'qa/seed_intel_workspace.py'),state],{encoding:'utf8'});
  assert.equal(seed.status,0,seed.stderr);
  server=spawn('python3',[path.join(root,'server.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port)},stdio:'ignore'});
}
const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking',`--user-data-dir=${path.join(temporary,'chrome')}`,'--remote-debugging-port=0','about:blank'],{stdio:'ignore'});
let ws,seq=0;const waiting=new Map(),exceptions=[];
async function cdp(method,params={}){const id=++seq;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{waiting.delete(id);reject(Error('CDP timeout'))},15000);waiting.set(id,{resolve:r=>{clearTimeout(timer);resolve(r)},reject});ws.send(JSON.stringify({id,method,params}))})}
async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value}
async function until(expression){const end=Date.now()+20000;while(Date.now()<end){if(await evaluate(expression))return;await delay(100)}throw Error('UI condition failed: '+expression)}
try{
  for(let i=0;i<100;i++){try{const r=await fetch(`http://127.0.0.1:${port}/v1/invoke`,{method:'POST',headers:{Authorization:'Bearer '+auth,'Content-Type':'application/json'},body:JSON.stringify({tool:'commerce_status',arguments:{},client:'test'})});await r.body?.cancel();if(r.ok)break}catch{}await delay(100)}
  let debug;for(let i=0;i<100;i++){try{debug=(await readFile(path.join(temporary,'chrome/DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{await delay(80)}}
  const pages=await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json();ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=waiting.get(m.id);if(p){waiting.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}}else if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails.text)};
  await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1920,height:1200,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:`http://127.0.0.1:${port}/login?token=${encodeURIComponent(auth)}`});
  await until(`!!document.querySelector('[data-tab="intelligence"]')&&!!document.querySelector('.kpi-value')`);
  await evaluate(`document.querySelector('[data-tab="intelligence"]').click()`);
  await until(`document.querySelectorAll('.intel-source-strip .intel-source-pill').length===8&&!document.querySelector('#intel-search button').disabled`);
  assert.ok(await evaluate(`document.querySelector('.mode-bar').textContent.includes('真实公开来源')`));
  await evaluate(`document.querySelector('.intel-source-pill[data-source="fed"]').click()`);
  assert.equal(await evaluate(`document.querySelectorAll('#intel-source-fed [data-intel-action="collect"]').length`),1);
  assert.ok(await evaluate(`document.querySelector('#intel-source-fed [data-intel-action="collect"]').focus();document.activeElement.dataset.intelAction==='collect'`));
  assert.ok(await evaluate(`document.querySelector('#intel-collection-jobs')!==null`));
  if(!live){await until(`!!document.querySelector('[data-intel-action="job-alert-ack"]')`);await evaluate(`document.querySelector('[data-intel-action="job-alert-ack"]').click()`);await until(`!document.querySelector('[data-intel-action="job-alert-ack"]')`);}

  assert.equal(await evaluate(`document.querySelector('#intel-map-svg').getAttribute('viewBox')`),'0 0 720 360');
  if(!live){
    await until(`document.querySelectorAll('.intel-timeline li').length===20`);
    assert.ok(await evaluate(`document.querySelector('.intel-results-head').textContent.includes('48')`));
    const firstIds=await evaluate(`[...document.querySelectorAll('.intel-timeline [data-intel-id]')].map(b=>b.dataset.intelId)`);
    await evaluate(`document.querySelector('[data-intel-action="next"]').click()`);
    await until(`document.querySelector('.intel-pagination').textContent.includes('第 2 页')&&!document.querySelector('#intel-search button').disabled`);
    const secondIds=await evaluate(`[...document.querySelectorAll('.intel-timeline [data-intel-id]')].map(b=>b.dataset.intelId)`);
    assert.ok(firstIds.every(id=>!secondIds.includes(id)),'distinct pages');
    await evaluate(`document.querySelector('[data-intel-action="previous"]').click()`);
    await until(`document.querySelector('.intel-pagination').textContent.includes('第 1 页')&&!document.querySelector('#intel-search button').disabled`);
    assert.deepEqual(await evaluate(`[...document.querySelectorAll('.intel-timeline [data-intel-id]')].map(b=>b.dataset.intelId)`),firstIds);
    await evaluate(`document.querySelector('[data-intel-action="zoom-in"]').click()`);
    assert.ok(await evaluate(`Number(document.querySelector('#intel-map-svg').getAttribute('viewBox').split(' ')[2])<720`));
    const box=await evaluate(`(()=>{const r=document.querySelector('#intel-map-svg').getBoundingClientRect();return{x:r.x+r.width*.65,y:r.y+r.height*.5}})()`);
    const beforeDrag=await evaluate(`document.querySelector('#intel-map-svg').getAttribute('viewBox')`);
    await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',x:box.x,y:box.y});await cdp('Input.dispatchMouseEvent',{type:'mousePressed',x:box.x,y:box.y,button:'left',buttons:1,clickCount:1});
    await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',x:box.x+35,y:box.y+10,button:'left',buttons:1});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',x:box.x+35,y:box.y+10,button:'left',buttons:0,clickCount:1});
    assert.notEqual(await evaluate(`document.querySelector('#intel-map-svg').getAttribute('viewBox')`),beforeDrag,'map pan');
    await evaluate(`document.querySelector('[data-intel-action="map-reset"]').click()`);
    await until(`!!document.querySelector('g[data-intel-cluster]')`);
    await evaluate(`document.querySelector('g[data-intel-cluster]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
    await until(`!!document.querySelector('.intel-cluster-popup [data-intel-id]')`);
    await evaluate(`document.querySelector('.intel-cluster-popup [data-intel-id]').click()`);
    await until(`!!document.querySelector('.intel-record')`);
    assert.ok(await evaluate(`document.querySelector('.intel-record').textContent.includes('尚未独立核实')`));
    await evaluate(`document.querySelector('[data-intel-action="bookmark"]').click()`);
    await until(`document.querySelector('[data-intel-action="bookmark"]')?.textContent==='取消收藏'&&!document.querySelector('[data-intel-action="bookmark"]').disabled`);
    await evaluate(`document.querySelector('[data-intel-view="bookmarked"]').click()`);
    await until(`document.querySelectorAll('.intel-timeline li').length===1&&!document.querySelector('#intel-search button').disabled`);
    assert.ok(await evaluate(`document.querySelector('.intel-filter-chips').textContent.includes('本机积累')`));
    await evaluate(`document.querySelector('[data-intel-action="clear"]').click()`);
    await until(`document.querySelectorAll('.intel-timeline li').length===20&&!document.querySelector('#intel-search button').disabled`);
    await evaluate(`document.querySelector('#intel-query').value='no matching synthetic phrase';document.querySelector('#intel-search button').click()`);
    await until(`document.querySelectorAll('.intel-timeline li').length===0&&!document.querySelector('#intel-search button').disabled`);
    assert.ok(await evaluate(`document.querySelector('.intel-empty').textContent.includes('没有记录')`));
    await evaluate(`document.querySelector('#intel-query').value='墨西哥洪水';document.querySelector('#intel-search button').click()`);
    await until(`document.querySelectorAll('.intel-timeline li').length===1&&!document.querySelector('#intel-search button').disabled`);
    await evaluate(`document.querySelector('#intel-watch-open').focus();document.querySelector('#intel-watch-open').click()`);
    await until(`!!document.querySelector('#intel-watch-name')`);
    await evaluate(`document.querySelector('#intel-watch-name').value='Synthetic Mexico flood';document.querySelector('#intel-watch-save').click()`);
    await until(`!document.querySelector('.dialog')`);
    await evaluate(`document.querySelector('[data-intel-action="side"][data-side="topics"]').click()`);
    await until(`document.querySelectorAll('.intel-watch').length===1`);
    assert.ok(await evaluate(`document.querySelector('.intel-topics').textContent.includes('未启用自动采集')`));
    await cdp('Page.reload');await until(`!!document.querySelector('.kpi-value')`);
    await evaluate(`document.querySelector('[data-tab="intelligence"]').click()`);
    await until(`document.querySelectorAll('.intel-source-strip .intel-source-pill').length===8`);
    await evaluate(`document.querySelector('[data-intel-action="side"][data-side="topics"]').click()`);
    await until(`document.querySelectorAll('.intel-watch').length===1`);
    await evaluate(`document.querySelector('[data-intel-watch]').click()`);
    await until(`document.querySelectorAll('.intel-timeline li').length===1&&!document.querySelector('#intel-search button').disabled`);
    await evaluate(`document.querySelector('.intel-timeline [data-intel-id]').click()`);
    await until(`!!document.querySelector('.intel-record')`);
    await evaluate(`document.querySelector('[data-intel-task]').click()`);
    await until(`document.querySelector('.intel-review').textContent.includes('核查已排队')`);
    const downloads=path.join(temporary,'downloads');await mkdir(downloads);await cdp('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:downloads});
    const selectedId=await evaluate(`document.querySelector('.intel-timeline [data-intel-id]').dataset.intelId`);
    await evaluate(`document.querySelector('[data-intel-action="export"]').click()`);
    let exported;for(let i=0;i<60;i++){try{exported=JSON.parse(await readFile(path.join(downloads,'intel-'+selectedId+'.json'),'utf8'));break}catch{await delay(100)}}
    assert.equal(exported.schema,'commerce-intel-evidence-v1');assert.equal(exported.record.id,selectedId);assert.equal(exported.record.record_sha256.length,64);assert.equal(exported.verification,'publisher_report_not_independently_verified');assert.equal('review_task'in exported.record,false);
    await evaluate(`document.querySelector('.intel-review [data-tab="tasks"]').click()`);
    await until(`document.querySelector('.content').textContent.includes('公开信号影响核查')`);
    await evaluate(`document.querySelector('[data-tab="intelligence"]').click()`);
    await until(`!!document.querySelector('.intel-record')`);
    await evaluate(`document.querySelector('[data-intel-action="side"][data-side="topics"]').click()`);await until(`document.querySelectorAll('.intel-watch').length===1`);
    await evaluate(`document.querySelector('[data-intel-action="watch-remove"]').click()`);await until(`document.querySelectorAll('.intel-watch').length===0`);
    await evaluate(`document.querySelector('[data-intel-action="clear"]').click()`);await until(`document.querySelectorAll('.intel-timeline li').length===20`);
    await evaluate(`document.querySelector('[data-intel-action="filters"]').click();document.querySelector('#intel-scope').value='archive';document.querySelector('#intel-scope').dispatchEvent(new Event('change',{bubbles:true}))`);
    await until(`document.querySelector('.intel-results-head').textContent.includes('49')&&!document.querySelector('#intel-search button').disabled`);
    await evaluate(`document.querySelector('#intel-query').value='Archived';document.querySelector('#intel-search button').click()`);
    await until(`document.querySelectorAll('.intel-timeline li').length===1&&!document.querySelector('#intel-search button').disabled`);
    assert.ok(await evaluate(`document.querySelector('.intel-timeline').textContent.includes('历史采集')`));
    await evaluate(`document.querySelector('[data-intel-action="map-toggle"]').click()`);await until(`!document.querySelector('.intel-map')`);
  }else{
    assert.ok(await evaluate(`document.querySelectorAll('.intel-timeline li').length>0`));
    await evaluate(`document.querySelector('[data-intel-action="filters"]').click();document.querySelector('#intel-source').value='fed';document.querySelector('#intel-source').dispatchEvent(new Event('change',{bubbles:true}))`);
    await until(`!document.querySelector('#intel-search button').disabled&&document.querySelectorAll('.intel-timeline li').length>0`);
    await evaluate(`document.querySelector('.intel-timeline [data-intel-id]').click()`);
    await until(`document.querySelector('.intel-record')?.textContent.includes('译文待校对')`);
    assert.ok(await evaluate(`document.querySelector('.intel-record').textContent.includes('存在数字或单位差异')`));

    await evaluate(`CommerceUI.applyTheme('light');document.querySelector('#ui-theme').value='light'`);
    const shot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(root,'qa/intelligence-live.png'),Buffer.from(shot.data,'base64'));
    await evaluate(`CommerceUI.applyTheme('dark');document.querySelector('#ui-theme').value='dark'`);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.intel-map svg>rect')).fill`),'rgb(22, 22, 22)');
    const darkShot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(root,'qa/intelligence-live-dark.png'),Buffer.from(darkShot.data,'base64'));
  }
  for(const width of [1440,1024,768,390]){await cdp('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});await delay(100);assert.equal(await evaluate(`document.documentElement.scrollWidth<=innerWidth+1`),true,'page overflow '+width)}
  if(!live){
    await evaluate(`document.querySelector('[data-intel-action="clear"]').click()`);
    await until(`!document.querySelector('#intel-search button').disabled`);
    await evaluate(`document.querySelector('[data-intel-action="filters"]').click()`);
    await evaluate(`document.querySelector('#intel-source').value='wto';document.querySelector('#intel-source').dispatchEvent(new Event('change',{bubbles:true}))`);
    await until(`document.querySelectorAll('.intel-timeline li').length===1`);
    await evaluate(`document.querySelector('.intel-timeline [data-intel-id]').click()`);
    await until(`document.querySelector('.intel-record')?.textContent.includes('合成文章 25 USD')`);
    assert.equal(await evaluate(`document.querySelectorAll('.intel-record script').length`),0);
    assert.ok(await evaluate(`document.querySelector('[data-intel-action="article-capture"]').focus();document.activeElement.dataset.intelAction==='article-capture'`));
  }
  assert.deepEqual(exceptions,[]);
  const result={status:'passed',mode:live?'live_public_cache_read_only':'isolated_synthetic',checks:['public source state and truthful mode','map rendering','responsive at 1440/1024/768/390','no runtime exception',...(live?['nonempty live public cache','read-only light/dark screenshot capture','dark map tokens']:['snapshot pagination and distinct pages','map zoom/pan/reset and spatial cluster selection','bookmark and archive filtering','compound Chinese retrieval and empty state','saved topic survives reload and applies filters','topic removal preserves records','version-bound shared task and queue navigation','evidence JSON download and private-mark exclusion','local archive retention view','map/list toggle','escaped article original/Chinese evidence and keyboard control'])],marketplace_calls:false};
  await writeFile(path.join(root,'qa',live?'intel-live-result.json':'intel-browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){if(ws){try{const shot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(root,'qa/intel-diagnostic.png'),Buffer.from(shot.data,'base64'))}catch{}}throw error}
finally{ws?.close();server?.kill('SIGTERM');chrome.kill('SIGTERM');await delay(500);await rm(temporary,{recursive:true,force:true})}
