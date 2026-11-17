// Real local HTTP/UI acceptance. Synthetic state, no model or external business.
import assert from 'node:assert/strict';
import {goToModule} from './ui_navigation.mjs';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import {readFile,writeFile,mkdtemp,mkdir,readdir,rm} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {tmpdir,homedir} from 'node:os';
import net from 'node:net';
import path from 'node:path';

const root=path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))));
const out=path.resolve(process.env.QA_OUTPUT_DIR||path.join(root,'.local/agent-team/control/operating-ui'));
await mkdir(out,{recursive:true});
let pw;
try{pw=await import(process.env.PLAYWRIGHT_MODULE||'playwright');}catch{
  for(const entry of await readdir(path.join(homedir(),'.npm/_npx')).catch(()=>[])){
    try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',entry,'node_modules/playwright/index.mjs')).href);break;}catch{}
  }
}
assert.ok(pw,'An existing Playwright installation is required.');
const work=await mkdtemp(path.join(tmpdir(),'phone-lab-control-'));
const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
const origin=`http://127.0.0.1:${port}`;
const child=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'commerce/qa/react_workbench_fixture.py')],
  {cwd:root,env:{...process.env,COMMERCE_STATE:work,COMMERCE_PORT:String(port),COMMERCE_QA_OPERATING_CONTROL:'1'},stdio:['ignore','ignore','pipe']});
const stopped=new Promise(resolve=>child.once('close',resolve));let stderr='';child.stderr.on('data',c=>stderr+=c.toString());
const manifest=()=>readFile(path.join(root,'commerce/web/workbench.sources.json')).then(v=>createHash('sha256').update(v).digest('hex'));
const result={scope:'Synthetic isolated Chromium; no phone/native/financial action',completed:false,errors:[],external:[],checks:[],sourceSha256:await manifest()};
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
  await page.goto(origin+'/login?token=synthetic-workbench-preview');
  await page.goto(origin+'/workspace?tab=operating-control&demo=true');
  await page.getByRole('heading',{name:'自动经营控制台',exact:true}).waitFor();
  await page.getByText('¥ 2,500.00',{exact:true}).first().waitFor();
  assert.equal(await page.title(),'自动经营 · Phone-Lab');
  assert.ok(await page.getByText('公司本地库存',{exact:true}).isVisible());
  assert.ok(await page.getByRole('button',{name:'调整预算',exact:true}).isDisabled());
  result.checks.push({name:'scope_and_budget',passed:true});
  await page.getByLabel('任务类型',{exact:true}).selectOption('feature');
  await page.getByLabel('任务标题',{exact:true}).fill('SYN物流停滞提醒功能');
  await page.getByLabel('详细要求',{exact:true}).fill('Synthetic acceptance only: retain original task and no external dispatch.');
  const request=page.waitForResponse(r=>r.url().endsWith('/v1/invoke')&&r.request().postDataJSON()?.tool==='commerce_operating_control_task_submit');
  await page.getByRole('button',{name:'登记任务',exact:true}).click();
  const saved=await (await request).json();assert.ok(saved.task_id);assert.equal(saved.status,'queued');assert.equal(saved.external_execution_allowed,false);
  await page.getByText('任务已登记，待派发；尚未执行。',{exact:true}).waitFor();
  const task=await page.evaluate(async id=>{const r=await fetch('/v1/invoke',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tool:'commerce_task_get',arguments:{task_id:id},client:'browser'})});if(!r.ok)throw Error('Original task read failed');return r.json();},saved.task_id);
  assert.equal(task.input.demo,true);assert.equal(task.input.origin,'operating_control');assert.equal(task.status,'queued');
  result.checks.push({name:'original_task_write_and_readback',passed:true});
  await page.reload();await page.getByRole('heading',{name:'自动经营控制台',exact:true}).waitFor();
  await page.getByText('SYN物流停滞提醒功能',{exact:true}).waitFor();
  result.checks.push({name:'refresh_preserves_original_task',passed:true});
  for(const [width,scheme]of [[1440,'light'],[390,'dark']]){
    await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:scheme,reducedMotion:'reduce'});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const fits=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);
    assert.ok(fits,'Control page horizontal overflow');
    await page.screenshot({path:path.join(out,`operating-control-${width}-${scheme}.png`),fullPage:true});
    result.checks.push({name:`viewport_${width}_${scheme}`,passed:fits});
  }
  await page.goto(origin+'/workspace?tab=operating-control&demo=false');
  await page.getByRole('heading',{name:'自动经营控制台',exact:true}).waitFor();
  await page.getByText('尚未配置',{exact:true}).waitFor();
  assert.equal(await page.getByText('SYN物流停滞提醒功能',{exact:true}).count(),0);
  assert.equal(await page.getByText('¥ 2,500.00',{exact:true}).count(),0);
  result.checks.push({name:'synthetic_does_not_leak_into_live',passed:true});
  await page.goto(origin+'/setup');await page.locator('#ozon-client').waitFor();
  const originalAccounts=await page.evaluate(async()=>{const r=await fetch('/v1/connections/status');return (await r.json()).ozon_accounts.accounts;});
  const saveAccount=async(label,client,key)=>{
    await page.locator('#store-label').fill(label);await page.locator('#ozon-client').fill(client);await page.locator('#ozon-key').fill(key);
    const response=page.waitForResponse(r=>r.url()===origin+'/v1/connections/save'&&r.request().method()==='POST');
    await page.locator('[data-setup-action="save-ozon"]').click();const r=await response;assert.equal(r.status(),200);await r.json();
    await page.waitForFunction(()=>document.querySelector('#ozon-key')?.value===''&&!document.querySelector('[data-setup-action="save-ozon"]')?.disabled);
  };
  await saveAccount('SYN店铺A','801234','synthetic-account-alpha-key');
  await saveAccount('SYN店铺B','809876','synthetic-account-beta-key');
  const publicAccounts=await page.evaluate(async()=>{const r=await fetch('/v1/connections/status');if(!r.ok)throw Error('Accounts read failed');return r.json();});
  assert.equal(publicAccounts.ozon_accounts.accounts.length,originalAccounts.length+2);
  assert.ok(originalAccounts.every(a=>publicAccounts.ozon_accounts.accounts.some(b=>b.account_id===a.account_id)));
  for(const secret of ['801234','809876','synthetic-account-alpha-key','synthetic-account-beta-key'])assert.ok(!JSON.stringify(publicAccounts).includes(secret));
  const accountA=publicAccounts.ozon_accounts.accounts.find(a=>a.label==='SYN店铺A');assert.ok(accountA&&!accountA.active);
  const switching=page.waitForResponse(r=>r.url()===origin+'/v1/connections/activate'&&r.request().method()==='POST');
  await page.locator(`[data-ozon-account="${accountA.account_id}"]`).click();assert.equal((await switching).status(),200);
  await page.waitForFunction(()=>document.querySelector('#store-label')?.value==='SYN店铺A');
  assert.equal(await page.locator('#ozon-key').inputValue(),'');
  const switched=await page.evaluate(async()=>{const r=await fetch('/v1/connections/status');return r.json();});
  assert.equal(switched.ozon_accounts.active_account_id,accountA.account_id);assert.equal(switched.sync_enabled,false);assert.equal(switched.notifications_enabled,false);
  assert.equal(switched.ozon_accounts.parallel_store_sync,false);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(out,'ozon-private-accounts-390.png'),fullPage:true});
  result.checks.push({name:'ozon_account_save_and_switch',passed:true},{name:'ozon_accounts_credentials_hidden',passed:true});
  await page.goto(origin+'/legacy');await page.locator('.app[data-view-ready="true"]').waitFor();await goToModule(page,'platforms');
  await page.getByRole('heading',{name:'添加并绑定店铺',exact:true}).waitFor();
  await page.locator('#platform-add-provider').selectOption('amazon');
  const opening=page.waitForResponse(r=>r.url().endsWith('/v1/invoke')&&r.request().postDataJSON()?.tool==='commerce_platform_open_setup');
  await page.locator('[data-platform-action="bind"]').click();assert.equal((await opening).status(),200);
  const opened=JSON.parse(await readFile(path.join(work,'qa-open-url.json'),'utf8'));
  assert.equal(new URL(opened.url).searchParams.get('platform'),'amazon');await page.goto(opened.url);
  await page.waitForFunction(()=>document.querySelector('#private-provider')?.value==='amazon');
  assert.equal(new URL(page.url()).searchParams.has('ticket'),false);
  await page.locator('#private-label').fill('SYN Amazon店铺');await page.locator('#private-market').fill('US');
  await page.locator('#private-region').selectOption('na');await page.locator('#private-marketplace_id').fill('SYNTHETIC12345');
  await page.locator('#private-access_token').fill('synthetic-amazon-access-token');
  await page.locator('#private-scope').check();await page.locator('#private-enabled').check();
  const bindAmazon=page.waitForResponse(r=>r.url().endsWith('/v1/platforms/configure')&&r.request().method()==='POST');
  await page.locator('#private-save').click();const boundResponse=await bindAmazon;assert.equal(boundResponse.status(),200);const bound=await boundResponse.json();
  await page.waitForFunction(()=>document.querySelector('#private-feedback')?.textContent.includes('已保存'));
  assert.equal(await page.locator('#private-access_token').inputValue(),'');
  await page.goto(origin+'/legacy');await page.locator('.app[data-view-ready="true"]').waitFor();await goToModule(page,'platforms');
  await page.locator(`#platform-store option[value="${bound.store_id}"]`).waitFor({state:'attached'});await page.locator('#platform-store').selectOption(bound.store_id);
  await page.getByText('当前没有完整快照。未知数据不会填为0。',{exact:true}).waitFor();
  assert.ok(await page.locator('[data-platform-action="read"]').isEnabled());
  await page.locator(`[data-account-id="${accountA.account_id}"][data-platform-action="account"]`).click();
  await page.getByRole('heading',{name:'Ozon 店铺信息',exact:true}).waitFor();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(out,'multi-store-management-390.png'),fullPage:true});
  result.checks.push({name:'multi_platform_bind_and_readback',passed:true});
  assert.deepEqual(result.errors,[]);assert.deepEqual(result.external,[]);
  assert.equal(await manifest(),result.sourceSha256);result.completed=true;
}catch(e){result.fatal=e.stack;if(page){result.overflow=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,nodes:[...document.querySelectorAll('body *')].map(e=>({tag:e.tagName,id:e.id,cls:typeof e.className==='string'?e.className:'',x:e.getBoundingClientRect().x,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width})).filter(e=>e.right>innerWidth+1||e.x<0).slice(0,20)})).catch(()=>null);await page.screenshot({path:path.join(out,'operating-control-failure.png')}).catch(()=>{});}}
finally{
  if(browser)await browser.close();child.kill('SIGTERM');await stopped;await rm(work,{recursive:true,force:true});
  result.sourceStable=(await manifest())===result.sourceSha256;
  await writeFile(path.join(out,'operating-control-browser.json'),JSON.stringify(result,null,2)+'\n');
  if(!result.completed||!result.sourceStable||result.fatal){process.exitCode=1;console.error(result.fatal||'Control browser acceptance failed');}
  else console.log(JSON.stringify({completed:result.completed,checks:result.checks,sourceStable:result.sourceStable,external:result.external}));
}
