// Read the actual local workbench through an isolated browser profile.
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,writeFile,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),out=path.join(root,'.local/social-intel/integration');await mkdir(out,{recursive:true});
const token=(await readFile(path.join(root,'.commerce-state/auth.token'),'utf8')).trim();
const profile=await mkdtemp(path.join(tmpdir(),'social-live-reader-'));const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--disable-background-networking',`--user-data-dir=${profile}`,'--remote-debugging-port=0','about:blank'],{stdio:'ignore'});
const delay=ms=>new Promise(r=>setTimeout(r,ms));let ws,seq=0;const waits=new Map(),errors=[];
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++seq,t=setTimeout(()=>reject(Error('CDP timeout')),15000);waits.set(id,{resolve:r=>{clearTimeout(t);resolve(r)},reject});ws.send(JSON.stringify({id,method,params}))})}
async function ev(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value}
async function until(expression){for(let i=0;i<150;i++){if(await ev(expression))return;await delay(60)}throw Error('live UI condition timed out: '+expression)}
try{
 let port;for(let i=0;i<100;i++){try{port=(await readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}await delay(80)}
 const pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=waits.get(m.id);if(p){waits.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text)};
 await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1800,height:1100,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:`http://127.0.0.1:38731/login?token=${encodeURIComponent(token)}#social`});
 await until(`document.querySelectorAll('.social-cards>li').length===13`);
 assert.ok(await ev(`document.querySelector('.social-cards').textContent.includes('网页补充')`));
 await ev(`document.querySelector('#social-filter').value='top';document.querySelector('#social-search').requestSubmit()`);
 await until(`document.querySelectorAll('.social-cards>li').length===9`);
 const counts={};
 for(const category of ['commerce','ai','news']){
  await ev(`document.querySelector('#social-category').value='${category}';document.querySelector('#social-search').requestSubmit()`);
  await until(`document.querySelectorAll('.social-cards>li').length===3&&!document.querySelector('[data-social-action="search"]').disabled`);
  counts[category]=await ev(`document.querySelectorAll('.social-cards>li').length`);
 }
 await ev(`document.querySelector('#social-category').value='all';document.querySelector('#social-search').requestSubmit()`);
 await until(`document.querySelectorAll('.social-cards>li').length===9`);
 const list=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(out,'live-top.png'),Buffer.from(list.data,'base64'));
 await ev(`document.querySelector('[data-social-action="open"]').click()`);
 await until(`!!document.querySelector('#social-reading-title')`);
 assert.ok(await ev(`document.querySelector('.social-reading').textContent.includes('官网补充资料')`));
 assert.ok(await ev(`document.querySelector('.social-reading a').href.startsWith('https://newsroom.tiktok.com/')`));
 await ev(`document.querySelector('[data-social-action="asset"]').click()`);
 await until(`!!document.querySelector('.social-evidence pre')`);
 assert.ok(await ev(`document.querySelector('.social-evidence pre').textContent.includes('source-excerpt-note-v1')`));
 const detail=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(out,'live-reading.png'),Buffer.from(detail.data,'base64'));
 assert.deepEqual(errors,[]);
 const result={status:'passed',scope:'actual shared local service and current built browser UI',records:13,curated_official_records:9,phone_candidates:4,category_top_counts:counts,checks:['authenticated social deep link','official supplement distinct from phone captures','three per category in latest curated batch','readable original/Chinese/source and limitations','registered evidence read and displayed','no runtime exceptions'],store_writes:false,reading_state:'one observed record marked viewed by normal reader'};
 await writeFile(path.join(out,'live-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{ws?.close();chrome.kill('SIGTERM');await delay(350);await rm(profile,{recursive:true,force:true})}
