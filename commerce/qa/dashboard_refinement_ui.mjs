// Source-backed dashboard interactions and responsive layout, in an isolated synthetic service.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,readFile,readdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir,homedir} from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath,pathToFileURL} from 'node:url';
const commerce=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const output=path.resolve(process.env.QA_OUTPUT_DIR||path.join(commerce,'../.local/coordination/dashboard-refinement-20261116'));
await mkdir(output,{recursive:true});
const manifest=await readFile(path.join(commerce,'web/workbench.sources.json'),'utf8');
const dashboardCss=process.env.COMMERCE_QA_DASHBOARD_CSS_SOURCE==='1'?await readFile(path.join(commerce,'workbench/src/overview-dashboard.css'),'utf8'):null;
let pw;for(const entry of await readdir(path.join(homedir(),'.npm/_npx'))){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',entry,'node_modules/playwright/index.mjs')).href);break}catch{}}
assert.ok(pw,'Use the existing Playwright installation');
const work=await mkdtemp(path.join(tmpdir(),'commerce-dashboard-')),state=path.join(work,'state');await mkdir(state);
const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
const origin=`http://127.0.0.1:${port}`;
const child=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(commerce,'qa/react_workbench_fixture.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port),COMMERCE_QA_PAGE_CONTEXT:'1'},stdio:['ignore','ignore','pipe']});
let serverLog='';child.stderr.on('data',chunk=>serverLog=(serverLog+chunk).slice(-6000));const closed=new Promise(resolve=>child.once('close',resolve));
let browser,page,failOrders=false;const checks=[],errors=[],external=[],mutations=[];const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function invoke(tool,args={}){const response=await fetch(origin+'/v1/invoke',{method:'POST',headers:{authorization:'Bearer synthetic-workbench-preview','content-type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'test'})});assert.equal(response.status,200,tool);return response.json()}
const record=checks.push.bind(checks);checks.push=(...items)=>{console.log(items.join('\n'));return record(...items)};
try{
 let ready=false;for(let i=0;i<100;i++){try{if((await fetch(origin+'/v1/health',{headers:{authorization:'Bearer synthetic-workbench-preview'}})).ok){ready=true;break}}catch{}if(child.exitCode!==null)break;await pause(100)}assert.ok(ready,serverLog);
 const {case_id:caseId}=JSON.parse(await readFile(path.join(state,'fixture.json'),'utf8'));
 for(let i=0;i<6;i++)await invoke('commerce_task_create',{idempotency_key:'dashboard-priority-'+i,kind:'analysis',input:{title:'Synthetic dashboard priority '+i,demo:false}});
 const source=await invoke('commerce_dashboard',{demo:false}),product=await invoke('commerce_workspace_get',{case_id:caseId});
 browser=await pw.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});const context=await browser.newContext({viewport:{width:1586,height:1000}});
 await context.route('**/*',route=>{
  const request=route.request(),url=request.url();if(!url.startsWith(origin+'/')&&!/^(data|blob|about):/.test(url)){external.push(new URL(url).origin);return route.abort()}
  if(url.endsWith('/v1/invoke')){const body=request.postDataJSON(),tool=body.tool;
   if(failOrders&&tool==='commerce_orders_list')return route.fulfill({status:503,json:{error:'synthetic_orders_unavailable'}});
   if(/(copilot_send|live_sync|task_create|task_execute|workspace_save|listing_.*submit|phone_.*control)/.test(tool)){mutations.push(tool);return route.abort()}
  }return route.continue();
 });
 page=await context.newPage();page.setDefaultTimeout(15000);page.on('pageerror',error=>errors.push(error.message));
 await page.goto(origin+'/login?token=synthetic-workbench-preview');await page.goto(origin+'/workspace?host=harness&tab=overview');if(dashboardCss)await page.addStyleTag({content:dashboardCss});
 await page.getByRole('img',{name:/3个真实日数据点/}).waitFor();if(await page.locator('.r-assistant-toggle').getAttribute('aria-pressed')==='true')await page.locator('.r-assistant-toggle').click();
 assert.equal(await page.locator('.r-overview-metrics>div').count(),4);assert.match(await page.locator('.r-overview-metrics').innerText(),/30/);assert.doesNotMatch(await page.locator('.r-dashboard').innerText(),/较昨日|128,560|林悦/);checks.push('Four source-backed metrics retain unknown currency and omit invented comparisons');
 for(const width of [1586,1440,1024,390])for(const theme of ['light','dark']){
  await page.setViewportSize({width,height:1000});await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.querySelector('.r-main').scrollTop=0},theme);
  await page.waitForTimeout(80);const root=await page.locator('.r-main').evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth}));assert.ok(root.scroll<=root.width+1,`${width} ${theme} overflow: ${JSON.stringify(root)}`);
  const priority=await page.locator('.r-dashboard-priorities').boundingBox(),chart=await page.locator('.r-dashboard-chart').boundingBox(),rail=await page.locator('.r-dashboard-rail').boundingBox();
  if(width>=1440){assert.ok(Math.abs(priority.y-chart.y)<2);assert.ok(Math.abs(rail.y-chart.y)<2);for(const panel of await page.locator('.r-dashboard-rail>.r-panel').all()){const bounds=await panel.boundingBox();assert.ok(Math.abs(bounds.x+bounds.width-rail.x-rail.width)<2,'Right-column cards fill the rail width instead of shrinking to content')}}if(width===390){assert.ok(chart.y<priority.y,'Mobile prioritizes the data chart');const targets=await page.locator('.r-dashboard-chart .r-chart-switch button').evaluateAll(els=>els.map(el=>el.getBoundingClientRect().height));assert.ok(targets.every(height=>height>=44),'Mobile chart controls retain 44px touch targets')};
  await page.screenshot({path:output+`/synthetic-${width}-${theme}.png`});
 }checks.push('1586/1440/1024/390px light and dark layouts preserve hierarchy without page overflow');
 await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>document.documentElement.dataset.theme='light');
 await page.getByRole('group',{name:'经营统计视图'}).getByRole('button',{name:'下单件数',exact:true}).click();await page.getByRole('img',{name:/下单件数趋势.*单位件/}).waitFor();assert.equal(await page.locator('.r-sales-chart rect').count(),3);assert.match(await page.locator('.r-trend-summary').innerText(),/3/);
 await page.locator('.r-assistant-toggle').click();await page.locator('[aria-label="销售趋势"]').focus();await page.waitForFunction(()=>document.querySelector('.copilot-page-context')?.textContent.includes('销售趋势'));
 const metadata=JSON.parse(await page.locator('[aria-label="销售趋势"]').getAttribute('data-ai-context'));assert.equal(metadata.entity.id,'sales-ordered-units');assert.equal(metadata.source_refs.sales,source.sales_summary.source_sha256);await page.locator('.r-assistant-toggle').click();checks.push('Amount/unit switching uses the same actual snapshot and preserves assistant context');
 await page.getByRole('group',{name:'经营统计视图'}).getByRole('button',{name:'下单金额',exact:true}).click();await page.locator('.r-sales-details>summary').click();assert.equal(await page.locator('.r-sales-details tbody tr').count(),3);assert.match(await page.locator('.r-sales-details tbody tr').last().innerText(),/0\s+0/);await page.locator('.r-sales-details>summary').click();checks.push('Daily details retain real zero amounts and units');
 await page.getByRole('group',{name:'经营统计视图'}).getByRole('button',{name:'更多统计'}).click();await page.getByRole('list',{name:'发货单状态分布'}).waitFor();assert.match(await page.locator('.r-statistics-columns').innerText(),/同步范围待确认/);await page.getByRole('group',{name:'经营统计视图'}).getByRole('button',{name:'下单金额',exact:true}).click();checks.push('Existing order status, platform composition and scope warnings remain accessible');
 const stock=await page.getByRole('region',{name:'按履约方式的库存统计'}).innerText();assert.ok(stock.includes(String(source.inventory.groups[0].present)));await page.getByRole('group',{name:'库存与提醒视图'}).getByRole('button',{name:/经营提醒/}).click();await page.locator('.r-dashboard-stock').getByText(/当前已读范围内没有经营提醒|仅展示已读经营提醒|当前经营范围/).first().waitFor();await page.getByRole('group',{name:'库存与提醒视图'}).getByRole('button',{name:'库存统计',exact:true}).click();checks.push('Inventory totals and operating-alert tab use existing data and navigation');
 assert.equal(await page.locator('.r-notice').count(),4);await page.getByRole('button',{name:/查看全部 \d+ 项/}).click();assert.ok(await page.locator('.r-notice').count()>4);await page.getByRole('group',{name:'按待办状态筛选'}).getByRole('button',{name:'失败 / 中断',exact:true}).click();await page.getByText('当前已读范围内没有此类待办。',{exact:true}).waitFor();await page.getByRole('group',{name:'按待办状态筛选'}).getByRole('button',{name:'全部',exact:true}).click();checks.push('Priority expansion and status filtering still reflect the actual result set');
 await page.getByRole('button',{name:'复查计划',exact:true}).click();await page.getByRole('dialog').waitFor();await page.getByRole('button',{name:'关闭弹窗',exact:true}).click();checks.push('Follow-up planning remains reachable without creating a schedule');
 failOrders=true;await page.locator('.r-dashboard-heading').getByRole('button',{name:'刷新',exact:true}).click();await page.getByRole('alert').filter({hasText:'发货单统计'}).waitFor();await page.getByRole('img',{name:/3个真实日数据点/}).waitFor();checks.push('A failed order read is explicit while other statistics remain available');failOrders=false;
 await page.goto(origin+'/workspace?host=harness&tab=overview&demo=true');if(dashboardCss)await page.addStyleTag({content:dashboardCss});await page.locator('.r-product-progress').first().waitFor();await page.waitForFunction(()=>!document.querySelector('.r-product-progress')?.textContent.includes('正在读取阶段'));
 if(await page.locator('.r-assistant-toggle').getAttribute('aria-pressed')!=='true')await page.locator('.r-assistant-toggle').click();
 for(const width of [1440,1024,390]){
  await page.setViewportSize({width,height:1000});await page.waitForTimeout(80);
  const clipped=await page.locator('.r-overview-metrics>div>strong').evaluateAll(elements=>elements.flatMap(element=>{const card=element.parentElement.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(element);return [...range.getClientRects()].filter(rect=>rect.width&&rect.height&&(rect.right>card.right-8||rect.left<card.left+8)).map(rect=>({text:element.textContent,right:rect.right,cardRight:card.right}))}));
  assert.deepEqual(clipped,[],`${width}px split dashboard retains the full metric and currency`);
  await page.screenshot({path:output+`/synthetic-split-metrics-${width}.png`});
 }checks.push('1440/1024/390px assistant split keeps the full metric value and currency visible');
 await page.locator('.r-assistant-toggle').click();await page.setViewportSize({width:1440,height:1000});
 const chosen=['S1','S3','S2','S4','S5','S6'];assert.equal(await page.locator('.r-stage-track li.is-passed').count(),product.stages.filter(stage=>chosen.includes(stage.id)&&stage.status==='PASS').length);assert.doesNotMatch(await page.locator('.r-stage-track').innerText(),/进行中|已完成/);await page.screenshot({path:output+'/synthetic-product-stages.png'});await page.locator('.r-product-progress').first().click();await page.frameLocator('iframe[title="完整商品内容编辑"]').getByRole('heading',{name:product.name,exact:true}).waitFor();checks.push('Product-stage checks match server facts and open the exact original workspace');
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(mutations,[]);assert.equal(await readFile(path.join(commerce,'web/workbench.sources.json'),'utf8'),manifest,'Shared bundle changed during verification');
 await writeFile(output+'/tested-manifest.json',manifest);
 await writeFile(output+'/browser.json',JSON.stringify({status:'passed',checks,errors,external,mutations,source_css_override:!!dashboardCss},null,2));console.log(JSON.stringify({status:'passed',checks:checks.length,source_css_override:!!dashboardCss}));
}catch(error){if(page)await page.screenshot({path:output+'/ui-failure.png'});console.error(serverLog);throw error}finally{await browser?.close();child.kill('SIGTERM');await closed;await rm(work,{recursive:true,force:true})}
