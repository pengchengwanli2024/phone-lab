import {goToModule} from './ui_navigation.mjs';
// Real loopback HTTP and browser wizard; all upstreams are synthetic, offline fixtures.
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,readFile,readdir,rm} from 'node:fs/promises';
import {tmpdir,homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import net from 'node:net';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
let playwright;
try{playwright=await import(process.env.PLAYWRIGHT_MODULE||'playwright')}
catch{for(const cache of await readdir(path.join(homedir(),'.npm/_npx'))){try{playwright=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',cache,'node_modules/playwright/index.mjs')).href);break}catch{}}}
assert.ok(playwright);
const temp=await mkdtemp(path.join(tmpdir(),'commerce-live-setup-'));
const state=path.join(temp,'state');await mkdir(state);
const secret='synthetic-browser-session';await writeFile(path.join(state,'auth.token'),secret);
const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
const origin=`http://127.0.0.1:${port}`,env={...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port)};
const server=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'qa/live_http_fixture.py')],{env,stdio:'ignore'});
const checks=[],errors=[];let browser,page;
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const headers={Authorization:'Bearer '+secret,'content-type':'application/json'};
async function action(name){
  const selector='[data-setup-action='+name+']';
  await page.waitForFunction(s=>{const b=document.querySelector(s);return b&&!b.disabled},selector);
  const route=name==='sync'?'sync':name==='test'?'test-feishu':'save';
  const response=page.waitForResponse(r=>r.url()===origin+'/v1/connections/'+route&&r.request().method()==='POST');
  await page.locator(selector).click();await response;
  await page.waitForFunction(s=>{const b=document.querySelector(s);return b&&!b.disabled},selector);
}

const request=(route,data,extra={})=>fetch(origin+route,{method:'POST',headers:{...headers,...extra},body:JSON.stringify(data)});
async function navigate(tab){await goToModule(page,tab)}
const invoke=async(tool,args={})=>(await request('/v1/invoke',{tool,arguments:args,client:'test'})).json();
try{
  let ready=false;for(let i=0;i<100;i++){try{if((await request('/v1/invoke',{tool:'commerce_status'})).ok){ready=true;break}}catch{}await delay(80)}assert.ok(ready);
  assert.equal((await fetch(origin+'/setup')).status,401);
  assert.equal((await request('/v1/connections/save',{}, {Origin:'https://untrusted.example'})).status,403);
  assert.equal((await invoke('commerce_live_configure',{ozon_api_key:'synthetic'})).error,'unknown_tool');
  const tools=await new Promise((resolve,reject)=>{
    const proc=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'mcp_server.py'),'local'],{env,stdio:['pipe','pipe','ignore']});let out='';proc.stdout.on('data',b=>out+=b);proc.on('error',reject);proc.on('close',code=>code?reject(Error('mcp failed')):resolve(out.trim().split('\n').map(JSON.parse)));
    for(const [id,method,params] of [[1,'initialize',{}],[2,'tools/list',{}],[3,'tools/call',{name:'commerce_live_status',arguments:{}}]])proc.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');proc.stdin.end();
  });
  const names=tools[1].result.tools.map(t=>t.name);assert.ok(names.includes('commerce_live_sync'));assert.ok(!names.some(n=>/^commerce_live_.*(configure|credential)/.test(n)));assert.equal(tools[2].result.structuredContent.configured,false);
  checks.push('Unauthenticated setup and foreign Origin blocked; native MCP discovery/status contains no credential setter');
  const ticket=(await(await request('/v1/connections/ticket',{})).json()).ticket;
  browser=await playwright.chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/setup?ticket='+ticket);await page.locator('#ozon-client').waitFor();assert.equal(page.url(),origin+'/setup');
  assert.equal((await fetch(origin+'/setup?ticket='+ticket,{redirect:'manual'})).status,401);
  assert.ok((await context.cookies()).some(c=>c.name==='commerce_session'&&c.httpOnly&&c.sameSite==='Strict'));
  assert.equal(await page.locator('[name=modes][value=OGL]').isChecked(),true);
  assert.equal(await page.locator('#ozon-client').getAttribute('type'),'password');assert.equal(await page.locator('#ozon-key').getAttribute('type'),'password');
  await action('save-ozon');await page.getByText('请填写 Seller API 页面显示的数字 Client ID。',{exact:true}).waitFor();
  await page.locator('#ozon-client').fill('123456');await page.locator('#ozon-key').fill('synthetic-not-network-key');await action('save-ozon');
  await page.waitForFunction(()=>document.querySelector('#ozon-key')?.placeholder.includes('已保存'));assert.equal(await page.locator('#ozon-key').inputValue(),'');
  const publicStatus=JSON.stringify(await invoke('commerce_live_status'));assert.ok(!publicStatus.includes('synthetic-not-network-key'));assert.ok(!publicStatus.includes('123456'));
  await action('sync');await page.waitForFunction(()=>document.querySelector('#setup-root')?.textContent.includes('SYN-1'));
  await page.waitForFunction(()=>document.querySelector('#setup-root')?.textContent.includes('本次仅建立初始基线'));
  await action('enable-sync');await page.getByText('请先把订单样本与 OGL 后台核对，并确认读取范围。',{exact:true}).waitFor();
  await action('confirm-orders');await page.waitForFunction(()=>document.querySelector('#setup-root')?.textContent.includes('订单范围核对：已确认'));
  await page.locator('#stock-basis').selectOption('present_minus_reserved');await action('save-stock');await page.getByText('请先拉取真实库存，再核对可售口径。',{exact:true}).waitFor();
  await page.locator('#stock-basis').selectOption('present_minus_reserved');await page.locator('#stock-reviewed').check();await action('save-stock');
  await page.waitForFunction(()=>document.querySelector('#stock-basis')?.value==='present_minus_reserved');
  checks.push('OGL preserved; one-use ticket removed from URL; passwords cleared; complete baseline, order scope and stock review enforced');
  await page.locator('#feishu-label').fill('Synthetic test group');await page.locator('#feishu-hook').fill('https://untrusted.example/hook');await action('save-feishu');await page.getByText('请填写目标群自定义机器人的完整飞书 Webhook 地址。',{exact:true}).waitFor();
  await page.locator('#feishu-label').fill('Synthetic test group');await page.locator('#feishu-hook').fill('https://open.feishu.cn/open-apis/bot/v2/hook/00000000-0000-0000-0000-000000000000');await page.locator('#feishu-sign').fill('synthetic-sign');await action('save-feishu');
  await page.waitForFunction(()=>document.querySelector('#feishu-hook')?.placeholder.includes('已保存'));
  assert.ok(await page.locator('[data-setup-action=enable-notify]').isDisabled());await action('test');await page.waitForFunction(()=>document.querySelector('#setup-root')?.textContent.includes('飞书接口已接收测试消息'));
  assert.ok(await page.locator('[data-setup-action=enable-notify]').isDisabled());await action('confirm-received');await page.waitForFunction(()=>!document.querySelector('[data-setup-action=enable-notify]')?.disabled);
  await action('enable-sync');await page.waitForFunction(()=>document.querySelector('#setup-root')?.textContent.includes('自动同步：已开启'));
  await action('enable-notify');await page.waitForFunction(()=>document.querySelector('#setup-root')?.textContent.includes('飞书推送：已开启'));
  await action('pause');await page.waitForFunction(()=>document.querySelector('#setup-root')?.textContent.includes('自动同步：未开启'));
  checks.push('Webhook host validated; synthetic test receipt and user receipt required separately; enable and pause persisted');
  for(const width of [1440,768,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));}
  await page.locator('#ozon-client').focus();await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.id),'ozon-key');
  checks.push('Private wizard fits 1440/768/390 and password fields support keyboard traversal');
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(origin+'/legacy');await page.locator('.app[data-view-ready="true"]').waitFor();await navigate('live');await page.getByRole('heading',{name:'Ozon 经营',level:1,exact:true}).waitFor();const [evidenceDownload]=await Promise.all([page.waitForEvent('download'),page.locator('[data-live-action=export]').click()]);const evidence=JSON.parse(await readFile(await evidenceDownload.path(),'utf8'));assert.equal(evidence.scope.modes[0],'OGL');assert.ok(evidence.snapshots.orders.sha256);assert.ok(!JSON.stringify(evidence).includes('synthetic-not-network-key'));await navigate('alerts');await page.getByText('真实订单与库存提醒',{exact:true}).waitFor();await page.getByText('标为已阅',{exact:true}).first().click();await page.waitForFunction(()=>document.querySelector('.content')?.textContent.includes('已阅'));
  await navigate('live');await page.getByRole('heading',{name:/桌面经营检查/}).waitFor();assert.equal((await invoke('commerce_live_readiness',{scope:'desktop'})).total,6);assert.equal(await page.locator('#demo').count(),0);await navigate('overview');await page.getByLabel('工作台设置',{exact:true}).click();await page.locator('#demo').uncheck();await navigate('orders');await page.waitForFunction(()=>document.querySelector('.content')?.textContent.includes('SYN-1'));
  assert.ok(await page.locator('#store option[value=ozon-live]').count());assert.equal(await page.locator('#store option[value=ozon-demo]').count(),0);await page.locator('[data-order=SYN-1]').click();assert.match(await page.locator('.dialog').textContent(),/SHA-256/);await page.keyboard.press('Escape');
  await navigate('products');await page.waitForFunction(()=>document.querySelector('.content')?.textContent.includes('SYN-SKU'));assert.match(await page.locator('.content').textContent(),/非单仓/);
  checks.push('Workbench native tools show actual fixture orders/stocks and evidence; live alerts acknowledged; real store filter separated from demo');

  await page.locator('[data-action=live-restock]').first().click();await page.locator('#live-plan-row').waitFor();
  assert.equal(await page.locator('#live-plan-row').inputValue(),'10:fbs');
  const saveDraft=async()=>{const response=page.waitForResponse(r=>r.url().endsWith('/v1/invoke')&&r.request().postDataJSON()?.tool==='commerce_live_restock_save');await page.locator('#live-restock-form button[type=submit]').click();await response;await page.waitForFunction(()=>!document.querySelector('#live-restock-form button[type=submit]')?.disabled);};
  await saveDraft();await page.waitForFunction(()=>document.querySelector('#live-planning')?.nextElementSibling?.textContent.includes('当前补货数量保持未知。'));
  for(const [key,value] of Object.entries({sold_units:'60',window_days:'30',lead_time_days:'14',safety_days:'7',pack_size:'6',inbound_units:'0',source_ref:'synthetic:sales.csv row 2 <img src=x onerror=alert(1)>'}))await page.locator('#live-plan-'+key).fill(value);
  await page.locator('[data-live-action=plan-now]').click();await saveDraft();await page.waitForFunction(()=>document.querySelector('#live-planning')?.nextElementSibling?.textContent.includes('整箱建议 42 件'));
  const planDownload=page.waitForEvent('download');await page.locator('[data-live-action=plan-export]').first().click();const plan=JSON.parse(await readFile(await(await planDownload).path(),'utf8'));assert.equal(plan.plan.current_result.suggested_qty,42);assert.equal(plan.plan.stock.key,'10:fbs');assert.ok(plan.field_zh.source_ref);assert.equal(await page.locator('#live-planning').locator('img').count(),0);
  await page.locator('#live-plan-sold_units').fill('61');await page.waitForTimeout(5200);assert.equal(await page.locator('#live-plan-sold_units').inputValue(),'61');
  for(const width of [1440,768,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));assert.ok(await page.locator('#live-plan-sold_units').isVisible(),'Restock input must remain reachable');const box=await page.locator('#live-plan-sold_units').boundingBox();assert.ok(box&&box.width>=80&&box.x>=0&&box.x+box.width<=width+2,'Restock input must fit the visible viewport');}
  await page.locator('#live-plan-sold_units').focus();await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.id),'live-plan-window_days');
  await page.locator('[data-live-action=plan-load]').first().click();await page.waitForFunction(()=>document.querySelector('#live-plan-sold_units')?.value==='60');
  checks.push('Live restock draft holds missing values, binds exact inventory and source, persists rounded result, exports bilingual evidence, preserves edits and fits keyboard/narrow screen');

  assert.deepEqual(errors,[]);
  const result={status:'passed',synthetic:true,external_messages_sent:false,checks,errors};await writeFile(path.join(root,'qa/live-setup-result.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
}catch(error){if(page){const debug=process.env.QA_OUTPUT_DIR;if(debug){await mkdir(debug,{recursive:true});await page.screenshot({path:path.join(debug,'setup-failure.png')});await writeFile(path.join(debug,'setup-failure.html'),await page.content());}console.error(JSON.stringify({visible:await page.locator('.content').innerText().catch(()=>''),readiness:await invoke('commerce_live_readiness',{scope:'desktop'})}));}throw error;}finally{await browser?.close();server.kill('SIGTERM');await delay(150);await rm(temp,{recursive:true,force:true})}
