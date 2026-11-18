// Decision checks page through the real page and HTTP service. Synthetic state only:
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
const out=path.resolve(process.env.QA_OUTPUT_DIR||path.join(root,'.local/coordination/paos-adoption-20261118/browser'));
await mkdir(out,{recursive:true});
let pw;
try{pw=await import(process.env.PLAYWRIGHT_MODULE||'playwright');}catch{
  for(const entry of await readdir(path.join(homedir(),'.npm/_npx')).catch(()=>[])){
    try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',entry,'node_modules/playwright/index.mjs')).href);break;}catch{}
  }
}
assert.ok(pw,'An existing Playwright installation is required.');
const work=await mkdtemp(path.join(tmpdir(),'phone-lab-decisions-'));
const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
const origin=`http://127.0.0.1:${port}`;
const child=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'commerce/qa/react_workbench_fixture.py')],
  {cwd:root,env:{...process.env,COMMERCE_STATE:work,COMMERCE_PORT:String(port),COMMERCE_QA_OPERATING_CONTROL:'1',COMMERCE_QA_OPERATING_LOOP:'1'},stdio:['ignore','ignore','pipe']});
const stopped=new Promise(resolve=>child.once('close',resolve));let stderr='';child.stderr.on('data',c=>stderr+=c.toString());
const manifest=()=>readFile(path.join(root,'commerce/web/workbench.sources.json')).then(v=>createHash('sha256').update(v).digest('hex'));
const result={scope:'Synthetic isolated Chromium; read-only page; no real model, store, payment or message',completed:false,errors:[],external:[],tools:[],checks:[],sourceSha256:await manifest()};
const check=(name,detail)=>result.checks.push({name,passed:true,...(detail?{detail}:{})});
const decisionTools=['commerce_selection_scorecard','commerce_demand_trend_assess','commerce_competitor_changes','commerce_shipment_reconcile','commerce_experiment_evaluate'];
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

  const nav=page.locator('.r-sidebar nav[aria-label="业务模块"]');
  await nav.getByRole('button',{name:'商品管线',exact:true}).click();
  await page.locator('.r-workspace-navigation summary',{hasText:'选品与研究'}).click();
  await page.waitForLoadState('networkidle');await page.waitForTimeout(800);
  tracking=true;
  await page.locator('.r-workspace-navigation').getByRole('button',{name:'经营决策检查',exact:true}).click();
  const root=page.locator('.r-decision-checks');
  await root.getByRole('heading',{name:'经营决策检查',level:1}).waitFor();
  check('reachable_from_navigation');
  const expectations={选品记分卡:/共 4 个：数据就绪 1，待补依据 2，不建议 1/,需求趋势:/新兴[\s\S]*两源互证/,竞品变化:/1000\.00 → 900\.00/,货件差异:/确认差异[\s\S]*在确认差异内/,实验评估:/变体更好/};
  const seen={};
  for(const [title,pattern] of Object.entries(expectations)){
    await root.getByRole('group',{name:'检查类型'}).getByRole('button',{name:title,exact:true}).click();
    await root.getByRole('button',{name:'填入合成示例'}).click();
    await root.getByRole('button',{name:'检查',exact:true}).click();
    const region=root.getByRole('region',{name:'检查结果'});
    await region.getByText('合成示例',{exact:true}).waitFor();
    const text=await region.innerText();assert.ok(pattern.test(text),title+' 结果不符，实际为：'+JSON.stringify(text.slice(0,400)));
    seen[title]=text.replace(/\s+/g,' ').slice(0,100);
  }
  check('five_checks_render_backend_results',seen);
  const direct=await invoke('commerce_selection_scorecard',{input:{candidates:[{sku:'DEMO-A',source:'合成示例',source_kind:'MANUAL_QUOTE',review_dependency:'low',net_margin_pct:32,promo_intensity:'medium',estimated_acos_pct:12,differentiation:'buyer_visible'}]}});
  assert.equal(direct.status_counts.READY,1);
  const minimum=root.getByLabel('每组最少样本（默认100）');
  await minimum.fill('2000');
  await root.getByText('输入已变化，请重新检查。').waitFor();
  await root.getByRole('button',{name:'检查',exact:true}).click();
  await root.getByRole('region',{name:'检查结果'}).getByText('无法下结论').waitFor();
  check('stale_result_is_cleared_and_rechecked');
  const before=result.tools.length;
  await root.getByLabel('预算上限（可留空）').fill('10');
  await root.getByRole('button',{name:'检查',exact:true}).click();
  await root.getByRole('alert').getByText('预算上限与已花费需同时填写或同时留空').waitFor();
  assert.equal(result.tools.length,before,'invalid form must not reach the service');
  await root.getByRole('group',{name:'检查类型'}).getByRole('button',{name:'选品记分卡',exact:true}).click();
  await root.getByRole('button',{name:'清空'}).click();
  await root.getByRole('button',{name:'检查',exact:true}).click();
  await root.getByRole('alert').getByText(/候选行不符合要求/).waitFor();
  check('invalid_input_explained');
  await root.getByRole('group',{name:'检查类型'}).getByRole('button',{name:'实验评估',exact:true}).focus();
  await page.keyboard.press('Enter');
  assert.equal(await root.getByRole('button',{name:'实验评估',exact:true}).getAttribute('aria-pressed'),'true');
  await root.getByLabel('预算上限（可留空）').fill('');
  await root.getByLabel('主要指标').focus();await page.keyboard.press('Enter');
  await root.getByRole('region',{name:'检查结果'}).getByText('无法下结论').waitFor();
  check('keyboard_switch_and_submit');
  await page.screenshot({path:path.join(out,'decisions-1440-light.png'),fullPage:false});
  await page.setViewportSize({width:390,height:900});
  await page.evaluate(()=>window.CommerceUI.applyTheme('dark'));
  await page.waitForTimeout(300);
  const overflow=await page.evaluate(()=>{const el=document.querySelector('.r-decision-checks');return {page:document.documentElement.scrollWidth-document.documentElement.clientWidth,section:el.scrollWidth-el.clientWidth};});
  assert.ok(overflow.page<=1&&overflow.section<=1,JSON.stringify(overflow));
  await page.screenshot({path:path.join(out,'decisions-390-dark.png'),fullPage:false});
  check('viewport_390_dark_no_overflow',overflow);
  tracking=false;
  const extra=[...new Set(result.tools)].filter(name=>!decisionTools.includes(name));
  assert.deepEqual(extra,[],'page called non-decision tools: '+extra.join(','));
  assert.equal((await invoke('commerce_task_list')).tasks.length,tasksBefore,'no task created');
  check('only_decision_tools_and_no_writes',{tools:[...new Set(result.tools)]});
  assert.deepEqual(result.errors,[]);assert.deepEqual(result.external,[]);
  result.completed=true;
}catch(error){result.failure=String(error?.stack||error);process.exitCode=1;}
finally{
  await browser?.close();child.kill('SIGTERM');await stopped;await rm(work,{recursive:true,force:true});
  result.sourceSha256After=await manifest();
  await writeFile(path.join(out,'result.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({completed:result.completed,checks:result.checks.map(c=>c.name),failure:result.failure?.slice(0,1500),errors:result.errors,external:result.external}));
}
