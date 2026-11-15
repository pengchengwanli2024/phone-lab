import {goToModule} from './ui_navigation.mjs';
// Plain Playwright integration runner against isolated real commerce HTTP state.
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,readFile,readdir,rm} from 'node:fs/promises';
import {tmpdir,homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const phase=process.argv.includes('--after')?'after':'before';
let playwright;
try{playwright=await import(process.env.PLAYWRIGHT_MODULE||'playwright')}
catch{for(const cache of await readdir(path.join(homedir(),'.npm/_npx'))){try{playwright=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',cache,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(playwright,'Install Playwright or set PLAYWRIGHT_MODULE');
const temp=await mkdtemp(path.join(tmpdir(),'commerce-workbench-'));
const state=path.join(temp,'state'),notes=path.join(temp,'notes');await mkdir(state);await mkdir(notes);
const secret='synthetic-workbench-only';await writeFile(path.join(state,'auth.token'),secret);
await writeFile(path.join(state,'config.json'),JSON.stringify({knowledge_root:notes}));
await writeFile(path.join(notes,'Inventory.md'),'# Inventory\nRestock when stock is low. <img src=x onerror=alert(1)>');
const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
const origin=`http://127.0.0.1:${port}`;
const server=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'server.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port)},stdio:'ignore'});

const out=process.env.COMMERCE_QA_OUT?path.resolve(process.env.COMMERCE_QA_OUT):path.join(root,'../.commerce-state/verification/workbench-quality');await mkdir(out,{recursive:true});
let browser,page;const exceptions=[],snapshots=[],checks=[];const delay=ms=>new Promise(r=>setTimeout(r,ms));
try{
 for(let n=0;n<100;n++){try{const r=await fetch(origin+'/v1/health',{headers:{Authorization:'Bearer '+secret}});if(r.ok)break}catch{}await delay(100)}
 browser=await playwright.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1440,height:1050},acceptDownloads:true});page=await context.newPage();page.on('pageerror',e=>exceptions.push(e.message));
 await page.goto(origin+'/login?token='+secret);await page.goto(origin+'/legacy');await page.locator('.kpi-value').first().waitFor();
 const tabs=await page.locator('.tabs [data-tab]').evaluateAll(nodes=>nodes.map(n=>({id:n.dataset.tab,label:n.textContent.trim()})));
 for(const tab of tabs){
  await goToModule(page,tab.id);
  await delay(500);
  for(const theme of ['light','dark','system']){
   await page.selectOption('#ui-theme',theme);await delay(100);
   for(const width of [1440,1024,768,390]){
    await page.setViewportSize({width,height:1050});await delay(80);
    const result=await page.evaluate(()=>{
     const visible=e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
     const unlabeled=[...document.querySelectorAll('input,select,textarea')].filter(e=>visible(e)&&!['hidden','submit','button'].includes(e.type)&&!e.getAttribute('aria-label')&&!e.getAttribute('aria-labelledby')&&!e.labels?.length).map(e=>({tag:e.tagName,id:e.id,name:e.name,placeholder:e.placeholder||''}));
     const unnamedButtons=[...document.querySelectorAll('button')].filter(e=>visible(e)&&!e.textContent.trim()&&!e.getAttribute('aria-label')&&!e.getAttribute('aria-labelledby')).map(e=>e.outerHTML.slice(0,180));
     const clippedKpis=[...document.querySelectorAll('.kpi-value')].filter(e=>visible(e)&&(e.scrollWidth>e.clientWidth+1||e.getBoundingClientRect().right>e.closest('.kpi').getBoundingClientRect().right-10)).map(e=>e.textContent);
     const nav=[...document.querySelectorAll('.tabs [data-tab]')];
     const navigation=innerWidth<=780?document.querySelector('#ui-module')?.options.length===nav.length&&visible(document.querySelector('#ui-module')):nav.filter(e=>!e.hidden).every(e=>visible(e)&&e.getBoundingClientRect().right<=innerWidth+1)&&visible(document.querySelector('.tabs [aria-current=page]'))&&[...document.querySelectorAll('[data-module-group]')].every(visible);
     return {overflow:document.documentElement.scrollWidth>innerWidth+1,scrollWidth:document.documentElement.scrollWidth,unlabeled,unnamedButtons,clippedKpis,navigation,heading:document.querySelector('h1')?.textContent,alerts:[...document.querySelectorAll('[role=alert]')].filter(visible).map(e=>e.textContent.slice(0,140))};
    });snapshots.push({tab:tab.id,theme,width,...result});
    if(theme==='light'&&width===1440)await page.screenshot({path:path.join(out,phase+'-'+tab.id+'.png'),fullPage:true});
    if(tab.id==='overview'&&width===390)await page.screenshot({path:path.join(out,phase+'-overview-narrow-'+theme+'.png'),fullPage:true});
   }
  }
 }
 const report={scope:'isolated synthetic data, no model/platform writes',modules:tabs,snapshots,exceptions};
 await writeFile(path.join(out,'survey-'+phase+'.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({modules:tabs.length,combinations:snapshots.length,exceptions,overflow:snapshots.filter(s=>s.overflow).map(s=>({tab:s.tab,width:s.width,theme:s.theme})),unlabeled:snapshots.filter(s=>s.unlabeled.length).map(s=>({tab:s.tab,items:s.unlabeled})).filter((s,i,a)=>a.findIndex(t=>t.tab===s.tab)===i),unnamedButtons:snapshots.filter(s=>s.unnamedButtons.length).length}));
 if(phase==='after'){
  assert.deepEqual(exceptions,[]);
  assert.equal(snapshots.filter(s=>s.overflow||s.unlabeled.length||s.unnamedButtons.length||s.clippedKpis.length||!s.navigation).length,0,'Rendered layout/accessibility/navigation regression');
 }
}finally{await browser?.close();server.kill('SIGTERM');await delay(300);await rm(temp,{recursive:true,force:true})}
