// The browser fetches the three packed business documents on demand; the map is
// only fetched when the intelligence page needs it. Synthetic fixture, no network.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import net from 'node:net';
import {mkdtemp,rm,mkdir,writeFile,readdir} from 'node:fs/promises';
import {gzipSync} from 'node:zlib';
import {tmpdir,homedir} from 'node:os';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

const root=path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))));
const out=path.resolve(process.env.QA_OUTPUT_DIR||path.join(root,'.local/coordination/frontend-pipeline-20261118/browser'));
await mkdir(out,{recursive:true});
let pw;
try{pw=await import(process.env.PLAYWRIGHT_MODULE||'playwright');}catch{
  for(const entry of await readdir(path.join(homedir(),'.npm/_npx')).catch(()=>[])){
    try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',entry,'node_modules/playwright/index.mjs')).href);break;}catch{}
  }
}
assert.ok(pw,'An existing Playwright installation is required.');
const work=await mkdtemp(path.join(tmpdir(),'phone-lab-docs-'));
const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
const origin='http://127.0.0.1:'+port;
const child=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'commerce/qa/react_workbench_fixture.py')],
  {cwd:root,env:{...process.env,COMMERCE_STATE:work,COMMERCE_PORT:String(port)},stdio:['ignore','ignore','pipe']});
const stopped=new Promise(resolve=>child.once('close',resolve));let stderr='';child.stderr.on('data',chunk=>stderr+=chunk.toString());
const result={scope:'Synthetic isolated Chromium; documents fetched same-origin; no real model, store or message',completed:false,errors:[],external:[],documents:[],checks:[]};
const check=name=>result.checks.push({name,passed:true});
let browser,page;
try{
  let ready=false;
  for(let i=0;i<100;i++){
    if(child.exitCode!==null)throw Error('Fixture exited: '+stderr);
    try{ready=(await fetch(origin+'/v1/health',{headers:{authorization:'Bearer synthetic-workbench-preview'}})).ok;}catch{}
    if(ready)break;await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.ok(ready,'Fixture did not become ready');
  browser=await pw.chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>{const url=route.request().url();if(url.startsWith(origin+'/')||/^(data|blob|about):/.test(url))return route.continue();result.external.push(new URL(url).origin);return route.abort();});
  page=await context.newPage();page.on('pageerror',error=>result.errors.push(error.message));
  page.on('request',request=>{const url=request.url();if(url.includes('/workspace/document/'))result.documents.push(url.split('/').pop());});
  const servedWire=async()=>gzipSync(Buffer.from(await (await page.request.get(origin+'/workspace')).text(),'utf8'),{level:9}).length;

  // 1. The served page carries no packed payload, only the executable artifact.
  await page.goto(origin+'/login?token=synthetic-workbench-preview');
  await page.goto(origin+'/workspace?tab=overview&demo=true');
  await page.getByRole('heading',{name:/今天的工作/}).waitFor();
  const served=await (await page.request.get(origin+'/workspace')).text();
  for(const id of ['legacy','product','intel-map']){
    assert.match(served,new RegExp('<script id="commerce-embedded-'+id+'" type="application/octet-stream" data-commerce-fetch="1"></script>'),'block '+id+' is deferred');
  }
  assert.ok(!/type="application\/octet-stream">[A-Za-z0-9+/]{1000}/.test(served),'no packed base64 rides along');
  const wire=await servedWire();
  assert.ok(wire/1024<520,'served page '+Math.round(wire/1024)+' KiB gzip stays under 520 KiB');
  assert.deepEqual(result.documents,[],'the overview page needs no document');
  check('overview_ships_without_documents');

  // 2. A legacy page fetches exactly its own document and renders.
  await page.goto(origin+'/workspace?tab=orders&demo=true');
  await page.waitForFunction(()=>document.querySelector('iframe'),null,{timeout:30000});
  let legacyFrame;
  for(let i=0;i<100&&!legacyFrame;i++){legacyFrame=page.frames().find(frame=>frame!==page.mainFrame());if(!legacyFrame)await page.waitForTimeout(150);}
  assert.ok(legacyFrame,'legacy iframe mounted');
  await legacyFrame.locator('body').first().waitFor({timeout:30000});
  await legacyFrame.evaluate(()=>document.querySelector('script')!==null||document.body.children.length>0);
  assert.deepEqual(result.documents,['legacy'],'only the legacy document was fetched');
  check('legacy_page_fetches_its_document');

  // 3. Reloading costs one request per document, never a duplicate for the same load.
  await page.goto(origin+'/workspace?tab=products&demo=true');
  await page.waitForFunction(()=>document.querySelector('iframe'),null,{timeout:30000});
  await page.waitForTimeout(2500);
  assert.equal(result.documents.filter(entry=>entry==='legacy').length,2,'one fetch per document load: '+JSON.stringify(result.documents));
  check('one_fetch_per_document_load');

  // 4. The product workspace fetches the product document.
  await page.goto(origin+'/workspace?tab=workspace&demo=true');
  await page.waitForFunction(()=>document.querySelector('iframe'),null,{timeout:30000});
  await page.waitForTimeout(2500);
  assert.ok(result.documents.includes('product'),'product document fetched: '+JSON.stringify(result.documents));
  check('product_page_fetches_its_document');

  // 5. The intelligence page fetches the map only there, and still renders it.
  await page.goto(origin+'/workspace?tab=intelligence&demo=true');
  await page.waitForFunction(()=>document.querySelector('iframe'),null,{timeout:30000});
  const deadline=Date.now()+60000;let staged=false;
  while(Date.now()<deadline&&!staged){
    for(const frame of page.frames()){if(await frame.locator('#intel-geo-stage').count().catch(()=>0))staged=true;}
    if(!staged)await page.waitForTimeout(200);
  }
  assert.ok(staged,'map stage mounted');
  assert.ok(result.documents.includes('intel-map'),'map document fetched: '+JSON.stringify(result.documents));
  const mapFrame=page.frames().find(async frame=>await frame.locator('#intel-geo-stage').count().catch(()=>0))||page.frames()[page.frames().length-1];
  for(const frame of page.frames()){
    if(await frame.locator('#intel-geo-stage').count().catch(()=>0)){
      const ready=await frame.evaluate(()=>document.querySelector('#intel-geo-earth')?.dataset.ready==='true');
      assert.equal(ready,true,'3D globe still initialises from the fetched document');
      const error=await frame.evaluate(()=>document.querySelector('#intel-geo-stage')?.dataset.error||'');
      assert.equal(error,'','no map error: '+error);
    }
  }
  check('intelligence_fetches_the_map_and_renders_it');

  // 6. Only the three known identifiers are reachable, and only when signed in.
  for(const id of ['other','../../server.py','legacy2']){
    const response=await page.request.get(origin+'/workspace/document/'+encodeURIComponent(id));
    assert.ok([401,404].includes(response.status()),'unknown document '+id+' is refused: '+response.status());
  }
  const anonymous=await page.request.get(origin+'/workspace/document/legacy',{headers:{cookie:''}});
  assert.equal(anonymous.status(),401,'documents require the session like every other page');
  check('only_known_documents_behind_the_session');
  assert.deepEqual(result.errors,[]);assert.deepEqual(result.external,[]);
  result.completed=true;
}catch(error){result.failure=String(error?.stack||error).slice(0,800);
  result.pageText=await page?.evaluate(()=>document.querySelector('.r-main')?.textContent?.slice(0,400)).catch(()=>'');
  process.exitCode=1;}
finally{
  await browser?.close();child.kill();await stopped;await rm(work,{recursive:true,force:true});
  await writeFile(path.join(out,'embedded-documents.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({completed:result.completed,checks:result.checks.map(entry=>entry.name),documents:result.documents,errors:result.errors.slice(0,5),failure:result.failure?.slice(0,600),pageText:result.pageText?.slice(0,300)},null,1));
}
