// Bounded standalone-reader checks using a separate temporary Chrome profile.
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,writeFile,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [input,output]=process.argv.slice(2);if(!input||!output)throw Error('input HTML and private output directory required');
await mkdir(output,{recursive:true});const profile=await mkdtemp(path.join(tmpdir(),'social-reader-'));
const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--disable-background-networking','--no-default-browser-check',`--user-data-dir=${profile}`,'--remote-debugging-port=0','about:blank'],{stdio:'ignore'});
const delay=ms=>new Promise(r=>setTimeout(r,ms));let ws,n=0;const waiting=new Map(),errors=[],checks=[];
function cdp(method,params={}){return new Promise((resolve,reject)=>{const id=++n,t=setTimeout(()=>{waiting.delete(id);reject(Error('CDP timeout'))},10000);waiting.set(id,{resolve:r=>{clearTimeout(t);resolve(r)},reject});ws.send(JSON.stringify({id,method,params}))})}
async function ev(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value}
async function check(name,expression){assert.ok(await ev(expression),name);checks.push(name)}
try{
 let debug;for(let i=0;i<100;i++){try{debug=(await readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}await delay(80)}
 const tabs=await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json();ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=waiting.get(m.id);if(p){waiting.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text)};
 await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:pathToFileURL(path.resolve(input)).href});
 for(let i=0;i<100;i++){if(await ev(`!!document.querySelector('#query')`))break;await delay(50)}
 await check('real records rendered',`document.querySelectorAll('[data-record]').length===3`);
 await check('source and limitations visible',`document.querySelector('#detail').textContent.includes('包含 AI 生成素材')&&document.querySelector('#detail').textContent.includes('单条视频链接')`);
 await check('safe original link',`[...document.querySelectorAll('a')].every(a=>['http:','https:','file:'].includes(new URL(a.href).protocol))`);
 await ev(`document.querySelector('#theme').value='dark';document.querySelector('#theme').dispatchEvent(new Event('change'))`);
 await check('shared neutral dark theme',`getComputedStyle(document.body).backgroundColor==='rgb(18, 18, 18)'`);
 const dark=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'reader-dark.png'),Buffer.from(dark.data,'base64'));
 await ev(`document.querySelector('#theme').value='light';document.querySelector('#theme').dispatchEvent(new Event('change'))`);
 await check('shared light theme',`getComputedStyle(document.body).backgroundColor==='rgb(248, 250, 255)'`);
 await ev(`document.querySelector('#theme').value='system';document.querySelector('#theme').dispatchEvent(new Event('change'))`);
 await cdp('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'dark'}]});
 await check('system theme follows preference',`getComputedStyle(document.body).backgroundColor==='rgb(18, 18, 18)'`);
 await ev(`document.querySelector('#query').focus()`);await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
 await check('keyboard reaches topic filter',`document.activeElement.id==='category'`);
 await ev(`document.querySelector('#category').value='ai';document.querySelector('#category').dispatchEvent(new Event('change'))`);
 await check('missing AI records stay empty',`!document.querySelector('[data-record]')&&document.querySelector('#detail').textContent.includes('尚无')`);
 await ev(`document.querySelector('#category').value='all';document.querySelector('#category').dispatchEvent(new Event('change'));document.querySelector('#mode').value='top';document.querySelector('#mode').dispatchEvent(new Event('change'))`);
 await check('incomplete sources excluded from TOP',`!document.querySelector('[data-record]')`);
 await ev(`document.querySelector('#mode').value='all';document.querySelector('#mode').dispatchEvent(new Event('change'));document.querySelector('#query').value='Black Friday';document.querySelector('#query').dispatchEvent(new Event('input'))`);
 await check('original text search works',`document.querySelectorAll('[data-record]').length===1`);
 await ev(`document.querySelector('[data-record]').click()`);await check('selection moves keyboard focus to article',`document.activeElement.id==='detail'`);
 await ev(`document.querySelector('#query').value='';document.querySelector('#query').dispatchEvent(new Event('input'))`);
 await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await check('390px layout has no horizontal overflow',`document.documentElement.scrollWidth<=390`);
 const shot=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(path.join(output,'reader-narrow.png'),Buffer.from(shot.data,'base64'));
 assert.deepEqual(errors,[]);checks.push('no browser runtime exceptions');
 await writeFile(path.join(output,'result.json'),JSON.stringify({status:'passed',checks,scope:'standalone Chrome reader only; Harness and live MCP not tested'},null,2));
 console.log(JSON.stringify({status:'passed',checks:checks.length}));
}finally{ws?.close();chrome.kill('SIGTERM');await delay(300);await rm(profile,{recursive:true,force:true})}
