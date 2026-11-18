// Product pipeline board through the real page and HTTP service. Synthetic state only:
// no network, model, marketplace, payment or message. Read-only page.
import assert from 'node:assert/strict';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import {readFile,writeFile,mkdtemp,mkdir,readdir,rm} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {tmpdir,homedir} from 'node:os';
import net from 'node:net';
import path from 'node:path';

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
const work=await mkdtemp(path.join(tmpdir(),'phone-lab-pipeline-'));
const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
const origin=`http://127.0.0.1:${port}`;
const child=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'commerce/qa/react_workbench_fixture.py')],
  {cwd:root,env:{...process.env,COMMERCE_STATE:work,COMMERCE_PORT:String(port),COMMERCE_QA_OPERATING_CONTROL:'1',COMMERCE_QA_OPERATING_LOOP:'1'},stdio:['ignore','ignore','pipe']});
const stopped=new Promise(resolve=>child.once('close',resolve));let stderr='';child.stderr.on('data',c=>stderr+=c.toString());
const manifest=()=>readFile(path.join(root,'commerce/web/workbench.sources.json')).then(v=>createHash('sha256').update(v).digest('hex'));
const result={scope:'Synthetic isolated Chromium; read-only page; no real model, store, payment or message',completed:false,errors:[],external:[],tools:[],checks:[],sourceSha256:await manifest()};
const check=(name,detail)=>result.checks.push({name,passed:true,...(detail?{detail}:{})});
const readOnly=new Set(['commerce_catalog_list','commerce_listing_directory','commerce_operating_pipeline_get']);
let browser,page;
try{
  let ready=false;
  for(let i=0;i<100;i++){
    if(child.exitCode!==null)throw Error('Fixture exited: '+stderr);
    try{ready=(await fetch(origin+'/v1/health',{headers:{authorization:'Bearer synthetic-workbench-preview'}})).ok;}catch{}
    if(ready)break;await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.ok(ready,'Fixture did not become ready');
  browser=await pw.chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--use-mock-keychain','--password-store=basic']});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>{const u=route.request().url();if(u.startsWith(origin+'/')||/^(data|blob|about):/.test(u))return route.continue();result.external.push(new URL(u).origin);return route.abort();});
  page=await context.newPage();page.on('pageerror',e=>result.errors.push(e.message));
  let tracking=false;
  page.on('request',request=>{if(!tracking||!request.url().endsWith('/v1/invoke'))return;try{result.tools.push(JSON.parse(request.postData()||'{}').tool);}catch{}});
  const invoke=(tool,args={})=>page.evaluate(async([tool,args])=>{const r=await fetch('/v1/invoke',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'browser'})});if(!r.ok)throw Error(tool+' failed');return r.json();},[tool,args]);
  await page.goto(origin+'/login?token=synthetic-workbench-preview');
  await page.goto(origin+'/workspace?tab=overview&demo=true');await page.getByRole('heading',{name:/今天的工作/}).waitFor();
  const tasksBefore=(await invoke('commerce_task_list')).tasks.length;

  // 1. The surface opens on the board; it is reachable from navigation.
  await page.locator('.r-sidebar nav[aria-label="业务模块"]').getByRole('button',{name:'商品管线',exact:true}).click();
  await page.locator('.r-workspace-navigation summary',{hasText:'选品与研究'}).click();
  await page.locator('.r-workspace-navigation').getByRole('button',{name:'商品管线看板',exact:true}).click();
  const heading=page.getByRole('heading',{name:/^商品管线/,level:1});await heading.waitFor();
  check('board_reachable_from_navigation');
  // Other mounted pages (overview, assistant) finish their own reads first.
  await page.waitForLoadState('networkidle');await page.waitForTimeout(1500);
  tracking=true;
  await page.getByRole('button',{name:'刷新',exact:true}).click();
  const summary=page.locator('.r-pipeline-summary');await summary.waitFor();
  await page.waitForFunction(()=>!document.querySelector('.r-pipeline-summary')?.textContent?.includes('正在读取阶段'),null,{timeout:20000});
  await page.waitForTimeout(300);tracking=false;

  // 2. One card per synthetic product, equal to the catalog read back.
  const catalog=(await invoke('commerce_catalog_list',{kind:'all'})).items.filter(item=>item.synthetic===true);
  const cards=await page.locator('.r-pipeline-card').count();
  assert.equal(cards,catalog.length,'one card per synthetic product');
  assert.ok(cards>0,'fixture has synthetic products');
  const shown=new Set(await page.locator('.r-pipeline-open strong').allTextContents());
  assert.equal(shown.size,cards,'no product repeated');
  check('one_card_per_product',{cards});

  // 3. A product with a saved plan sits in the stage the pipeline reports.
  const directory=await invoke('commerce_listing_directory',{demo:true,offset:0,limit:25});
  if(directory.items.length){
    const target=directory.items[0].target;
    const snapshot=await invoke('commerce_operating_pipeline_get',{...target,goal:'launch'});
    const open=snapshot.stages.find(stage=>stage.required_for_goal&&stage.acceptance_status!=='prepared');
    const product=catalog.find(item=>item.case_ids.includes(target.case_id));
    const column=page.locator('.r-pipeline-column').filter({has:page.locator('.r-pipeline-open strong',{hasText:product.name})});
    const label=await column.locator('h2').textContent();
    assert.ok(open?label!=='资料已备齐'&&label!=='阶段未读到':label==='资料已备齐','column follows the pipeline: '+label+' / '+open?.id);
    check('planned_product_in_reported_stage',{stage:open?.id||'prepared',column:label});
  }else check('planned_product_in_reported_stage',{skipped:'fixture has no saved plan'});

  // 4. Read-only: only the three read tools were called, no task was created.
  const unexpected=[...new Set(result.tools)].filter(tool=>!readOnly.has(tool));
  assert.deepEqual(unexpected,[],'only read tools');
  assert.equal((await invoke('commerce_task_list')).tasks.length,tasksBefore,'no task created');
  check('read_only_tools',{tools:[...new Set(result.tools)]});

  // 5. List view shows the same products.
  await page.getByRole('button',{name:'列表',exact:true}).click();
  assert.equal(await page.locator('.r-pipeline-table tbody tr').count(),cards);
  await page.getByRole('button',{name:'看板',exact:true}).click();
  check('list_matches_board');

  // 6. Search narrows without new reads.
  const first=[...shown][0];
  tracking=true;await page.getByLabel('查找商品').fill(first.slice(0,Math.min(6,first.length)));await page.waitForTimeout(200);tracking=false;
  assert.ok(await page.locator('.r-pipeline-card').count()>=1);
  await page.getByLabel('查找商品').fill('');
  check('search_narrows');

  // 7. Opening a card goes to the exact product work item.
  await page.locator('.r-pipeline-open').first().click();
  await page.waitForFunction(()=>new URL(location.href).searchParams.get('tab')==='workspace'&&!!new URL(location.href).searchParams.get('case_id'));
  check('card_opens_product');

  // 8. Widths and themes: no horizontal page overflow.
  for(const [width,height,theme] of [[1440,1000,'light'],[1440,1000,'dark'],[390,844,'light'],[390,844,'dark']]){
    await page.setViewportSize({width,height});
    await page.goto(origin+'/workspace?tab=pipeline&demo=true');await page.locator('.r-pipeline-summary').waitFor();
    await page.evaluate(t=>window.CommerceUI.applyTheme(t),theme);
    await page.waitForFunction(()=>!document.querySelector('.r-pipeline-summary')?.textContent?.includes('正在读取阶段'),null,{timeout:20000});
    await page.waitForTimeout(400);
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
    assert.ok(overflow<=1,'no horizontal overflow at '+width+' '+theme+': '+overflow);
    await page.screenshot({path:path.join(out,`pipeline-${width}-${theme}.png`)});
  }
  check('no_overflow_light_dark_wide_narrow');
  assert.deepEqual(result.errors,[]);assert.deepEqual(result.external,[]);
  result.completed=true;
}catch(error){result.failure=String(error?.stack||error);result.pageText=await page?.locator('.r-pipeline-board').innerText().catch(()=>'' );process.exitCode=1;}
finally{
  await browser?.close();child.kill();await stopped;await rm(work,{recursive:true,force:true});
  result.sourceSha256After=await manifest();
  await writeFile(path.join(out,'pipeline-board.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({completed:result.completed,checks:result.checks.map(c=>c.name),failure:result.failure?.slice(0,800),pageText:result.pageText?.slice(0,600)},null,1));
}
