// Operating loop through the real page and HTTP service. Synthetic state and a scripted
// model only: no network, real model, marketplace, payment or message.
import assert from 'node:assert/strict';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import {readFile,writeFile,mkdtemp,mkdir,readdir,rm} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {tmpdir,homedir} from 'node:os';
import net from 'node:net';
import path from 'node:path';

const root=path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))));
const out=path.resolve(process.env.QA_OUTPUT_DIR||path.join(root,'.local/agent-team/control/operating-loop-ui'));
await mkdir(out,{recursive:true});
let pw;
try{pw=await import(process.env.PLAYWRIGHT_MODULE||'playwright');}catch{
  for(const entry of await readdir(path.join(homedir(),'.npm/_npx')).catch(()=>[])){
    try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',entry,'node_modules/playwright/index.mjs')).href);break;}catch{}
  }
}
assert.ok(pw,'An existing Playwright installation is required.');
const work=await mkdtemp(path.join(tmpdir(),'phone-lab-loop-'));
const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
const origin=`http://127.0.0.1:${port}`;
const child=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'commerce/qa/react_workbench_fixture.py')],
  {cwd:root,env:{...process.env,COMMERCE_STATE:work,COMMERCE_PORT:String(port),COMMERCE_QA_OPERATING_CONTROL:'1',COMMERCE_QA_OPERATING_LOOP:'1'},stdio:['ignore','ignore','pipe']});
const stopped=new Promise(resolve=>child.once('close',resolve));let stderr='';child.stderr.on('data',c=>stderr+=c.toString());
const manifest=()=>readFile(path.join(root,'commerce/web/workbench.sources.json')).then(v=>createHash('sha256').update(v).digest('hex'));
const result={scope:'Synthetic isolated Chromium and scripted model; no real model, store, payment or message',completed:false,errors:[],external:[],checks:[],sourceSha256:await manifest()};
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
  browser=await pw.chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--use-mock-keychain','--password-store=basic']});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>{const u=route.request().url();if(u.startsWith(origin+'/')||/^(data|blob|about):/.test(u))return route.continue();result.external.push(new URL(u).origin);return route.abort();});
  page=await context.newPage();page.on('pageerror',e=>result.errors.push(e.message));
  const invoke=(tool,args={})=>page.evaluate(async([tool,args])=>{const r=await fetch('/v1/invoke',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'browser'})});if(!r.ok)throw Error(tool+' failed');return r.json();},[tool,args]);
  const open=async demo=>{await page.goto(origin+'/workspace?tab=operating-control&demo='+demo);await page.getByRole('heading',{name:'经营回路',exact:true}).waitFor();};
  await page.goto(origin+'/login?token=synthetic-workbench-preview');
  await open(true);
  const panel=page.locator('section.r-panel').filter({has:page.getByRole('heading',{name:'经营回路',exact:true})});
  const button=name=>panel.getByRole('button',{name,exact:true});
  await panel.getByText('还没有开启回路的商品',{exact:false}).waitFor();
  const tasksBefore=(await invoke('commerce_task_list')).tasks.length;

  // 1. A saved grant is disabled and dispatches nothing.
  await button('新建授权').click();
  const choice=panel.locator('#loop-choice');
  await choice.locator('option[value="0"]').waitFor({state:'attached'});await choice.selectOption('0');
  await panel.locator('#loop-level').selectOption('prepare');
  assert.ok(await panel.getByRole('checkbox',{name:/市场研究与选品/}).isChecked(),'Workable stages are preselected');
  assert.equal(await panel.getByRole('checkbox',{name:/目标店铺上架与结果回读/}).isChecked(),false,'Listing is never preselected');
  await button('保存授权').click();
  await panel.getByText('授权已保存，仍为未启用。',{exact:false}).waitFor();
  await panel.getByText('未启用',{exact:true}).waitFor();
  let view=await invoke('commerce_operating_loop_get');
  assert.equal(view.grants.length,1);assert.equal(view.grants[0].enabled,false);assert.equal(view.grants[0].synthetic,true);
  assert.deepEqual(view.work,[]);assert.equal(view.external_execution_allowed,false);
  check('saved_grant_is_disabled_and_idle');

  // 2. Enabling and one explicit check hands the first open stage to its owner.
  await button('启用').click();await panel.getByText('运行中',{exact:true}).waitFor();
  let decided=false;
  for(let i=0;i<60&&!decided;i++){
    await button('立即检查一次').click();
    await panel.locator('.r-loop-status').waitFor();
    decided=await panel.getByRole('heading',{name:/^等你决定/}).isVisible();
    if(!decided)await page.waitForTimeout(300);
  }
  assert.ok(decided,'The scripted stage owner did not return a proposal');
  view=await invoke('commerce_operating_loop_get');
  assert.equal(view.work.length,1);
  assert.deepEqual([view.work[0].stage_id,view.work[0].owner,view.work[0].status],['research','scout','awaiting_decision']);
  assert.equal((await invoke('commerce_task_list')).tasks.length,tasksBefore,'A proposal alone creates no task');
  await panel.getByText('合成验收：补齐当前阶段的岗位产物',{exact:true}).waitFor();
  check('stage_owner_proposal_waits_for_decision');

  // 3. Approval resumes the original handoff exactly once and survives reload.
  await button('批准交接').click();
  await panel.getByText('已批准，原岗位交接任务已登记。',{exact:false}).waitFor();
  view=await invoke('commerce_operating_loop_get');
  assert.equal(view.work[0].status,'completed');
  const task=await invoke('commerce_task_get',{task_id:view.work[0].decision.task_id});
  assert.equal(task.input.organization_case,view.grants[0].target.case_id);assert.equal(task.input.organization_stage,'S1');
  assert.equal((await invoke('commerce_task_list')).tasks.length,tasksBefore+1);
  await open(true);
  await panel.getByText('已结束（1）',{exact:true}).waitFor();
  assert.equal(await panel.getByRole('heading',{name:/^等你决定/}).count(),0);
  check('approval_resumes_original_handoff_once');

  // 4. Unchanged evidence stays idle: no new work item, request or task.
  await button('立即检查一次').click();
  await panel.getByText('证据没有变化，没有新工单。',{exact:false}).waitFor();
  view=await invoke('commerce_operating_loop_get');
  assert.equal(view.work.length,1);assert.equal((await invoke('commerce_task_list')).tasks.length,tasksBefore+1);
  check('unchanged_evidence_stays_idle');

  // 5. Disabling stops later dispatch and keeps the record.
  await button('停用').click();await panel.getByText('未启用',{exact:true}).waitFor();
  assert.equal(await button('立即检查一次').count(),0);
  assert.equal((await invoke('commerce_operating_loop_get')).grants[0].enabled,false);
  check('disable_keeps_history');

  for(const [width,scheme]of [[1440,'light'],[390,'dark']]){
    await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:scheme,reducedMotion:'reduce'});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    if(width===390){await button('新建授权').click();await panel.locator('#loop-level').waitFor();}
    const fits=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);
    assert.ok(fits,'Loop panel horizontal overflow at '+width);
    await page.screenshot({path:path.join(out,`operating-loop-${width}-${scheme}.png`),fullPage:true});
    check(`viewport_${width}_${scheme}`);
  }
  await page.setViewportSize({width:1440,height:1000});

  // Run health: real checks from the isolated service, and the one setting on this panel.
  const health=page.locator('section.r-panel').filter({has:page.getByRole('heading',{name:'运行健康',exact:true})});
  await health.getByText('后台工作器',{exact:true}).waitFor();
  const read=await invoke('commerce_operating_health_get');
  assert.equal(read.auto_backup,false,'Automatic backup is off until explicitly enabled');
  assert.equal(await health.locator('.r-oc-records>li').count(),read.checks.length);
  const first=await health.locator('.r-oc-records>li').first().innerText(),worst=read.checks.find(c=>c.status==='critical')||read.checks.find(c=>c.status==='warning');
  if(worst)assert.ok(first.includes(worst.label)||read.checks.filter(c=>c.status===worst.status).some(c=>first.includes(c.label)),'Problems are listed first');
  assert.ok(await health.getByText('依赖本机保持登录和不休眠',{exact:false}).isVisible());
  await health.getByRole('button',{name:'开启每日自动备份',exact:true}).click();
  await health.getByRole('button',{name:'关闭每日自动备份',exact:true}).waitFor();
  assert.equal((await invoke('commerce_operating_health_get')).auto_backup,true);
  await open(true);
  await health.getByRole('button',{name:'关闭每日自动备份',exact:true}).click();
  await health.getByRole('button',{name:'开启每日自动备份',exact:true}).waitFor();
  assert.equal((await invoke('commerce_operating_health_get')).auto_backup,false);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  // A check that needs attention must lead somewhere: the fixture has queued tasks nobody will run.
  assert.equal(read.checks.find(c=>c.id==='unassigned').status,'warning');
  await health.getByRole('button',{name:'去任务中心',exact:true}).click();
  await page.locator('.r-app[data-module="tasks"]').waitFor();
  await open(true);
  check('run_health_reads_real_checks_and_backup_setting_persists');

  // 6. The synthetic grant never appears in the live scope.
  await open(false);
  await panel.getByText('还没有开启回路的商品',{exact:false}).waitFor();
  assert.equal(await panel.getByText('便携式榨汁机',{exact:false}).count(),0);
  check('synthetic_does_not_leak_into_live');

  assert.deepEqual(result.errors,[]);assert.deepEqual(result.external,[]);
  assert.equal(await manifest(),result.sourceSha256);result.completed=true;
}catch(e){result.fatal=e.stack;if(page)result.panelText=await page.locator('.r-operating-control').innerText().then(text=>text.slice(0,1500)).catch(()=>null);if(page)await page.screenshot({path:path.join(out,'operating-loop-failure.png'),fullPage:true}).catch(()=>{});}
finally{
  if(browser)await browser.close();child.kill('SIGTERM');await stopped;await rm(work,{recursive:true,force:true});
  result.sourceStable=(await manifest())===result.sourceSha256;
  await writeFile(path.join(out,'operating-loop-browser.json'),JSON.stringify(result,null,2)+'\n');
  if(!result.completed||!result.sourceStable||result.fatal){process.exitCode=1;console.error(result.fatal||'Loop browser acceptance failed');}
  else console.log(JSON.stringify({completed:result.completed,checks:result.checks,sourceStable:result.sourceStable,external:result.external}));
}
