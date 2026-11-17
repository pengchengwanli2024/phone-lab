// Real isolated product interface and HTTP ledgers; no external model or account.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, readdir, mkdir } from 'node:fs/promises';
import { homedir, tmpdir } from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath, pathToFileURL } from 'node:url';
const commerce=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const readManifestHash=()=>readFile(path.join(commerce,'web/workbench.sources.json')).then(raw=>createHash('sha256').update(raw).digest('hex'));
const candidate=await readManifestHash();
let playwright;
try {playwright=await import('playwright')} catch {
  for(const p of await readdir(path.join(homedir(),'.npm/_npx')).catch(()=>[])) {
    try {playwright=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',p,'node_modules/playwright/index.mjs')).href);break} catch {}
  }
}
assert.ok(playwright,'Existing Playwright required');
const state=await mkdtemp(path.join(tmpdir(),'commerce-business-acceptance-'));
const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
const origin=`http://127.0.0.1:${port}`;
const server=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(commerce,'qa/fixture_product_workspace.py')],{env:{...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port),COMMERCE_QA_DELIVERY:'1'},stdio:['ignore','ignore','pipe']});
let errors='';server.stderr.on('data',b=>{errors=(errors+b).slice(-4000)});
let browser;
try {
  let token;
  for(let i=0;i<100;i++) {try {token=await readFile(path.join(state,'auth.token'),'utf8');const r=await fetch(origin+'/v1/health',{headers:{authorization:'Bearer '+token}});if(r.ok)break}catch{}await new Promise(r=>setTimeout(r,100))}
  assert.ok(token,'Fixture did not start: '+errors);
  const {case_id:caseId}=JSON.parse(await readFile(path.join(state,'fixture.json'),'utf8'));
  const invoke=async(tool,args={})=>{const r=await fetch(origin+'/v1/invoke',{method:'POST',headers:{authorization:'Bearer '+token,'content-type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'test'})});assert.equal(r.status,200,tool);return r.json()};
  browser=await playwright.chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:960}}),pageErrors=[],external=[];
  page.on('pageerror',e=>pageErrors.push(e.message));
  await page.route('**/*',r=>{if(r.request().url().startsWith(origin+'/')||/^(data|blob|about):/.test(r.request().url()))return r.continue();external.push(r.request().url());return r.abort()});
  await page.goto(origin+'/login?token='+encodeURIComponent(token));
  await page.goto(origin+'/product-workspace?case_id='+caseId);
  await page.locator('#pw-main[aria-busy="false"]').waitFor();
  await page.locator('[data-pw-tab="overview"]').click();
  await page.getByRole('button',{name:'管理报价',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByRole('button',{name:'新增报价',exact:true}).click();
  const values={supplier:'Synthetic supplier UI',currency:'CNY',purchase_cost:'40',lead_time_days:'10',moq:'20',source_ref:'synthetic:ui-quote',valid_until:new Date(Date.now()+86400000).toISOString(),length_cm:'20',width_cm:'10',height_cm:'5',weight_kg:'0.4',units_per_pack:'1'};
  for(const [key,value] of Object.entries(values))await dialog.locator('#pw-quote-'+key).fill(value);
  await dialog.getByRole('button',{name:'保存报价',exact:true}).click();
  await dialog.getByRole('button',{name:'选用此报价',exact:true}).waitFor();
  let saved=await invoke('commerce_workspace_get',{case_id:caseId});
  assert.equal(saved.supply_quotes.items[0].revision,1);
  // Saving a quote does not silently replace the original supply handoff.
  assert.equal(saved.artifacts.supply.payload.purchase_cost,58);
  await dialog.getByRole('button',{name:'选用此报价',exact:true}).click();
  await dialog.getByText('已选用',{exact:true}).waitFor();
  saved=await invoke('commerce_workspace_get',{case_id:caseId});assert.equal(saved.artifacts.supply.payload.purchase_cost,40);
  await dialog.getByRole('button',{name:'编辑报价',exact:true}).click();
  await dialog.locator('#pw-quote-purchase_cost').fill('35');
  await dialog.getByRole('button',{name:'保存报价',exact:true}).click();
  await dialog.getByText('版本 2',{exact:true}).waitFor();
  saved=await invoke('commerce_workspace_get',{case_id:caseId});assert.equal(saved.supply_quotes.items[0].history.length,2);
  assert.notEqual(saved.stages.find(s=>s.id==='S3').status,'PASS');
  const secondFields={...saved.supply_quotes.items[0].fields,supplier:'Synthetic smaller MOQ',purchase_cost:36,moq:1,source_ref:'synthetic:small-moq'};
  await invoke('commerce_workspace_quote_save',{case_id:caseId,quote_id:'small-moq',payload:secondFields,expected_revision:0,expected_source_sha256:saved.source_sha256,idempotency_key:'small-moq-comparison'});
  await dialog.locator('[data-pw-action="dialog-close"]').click();
  await page.reload();await page.locator('#pw-main[aria-busy="false"]').waitFor();
  await page.getByRole('button',{name:'管理报价',exact:true}).click();
  await dialog.locator('#pw-quote-quantity').fill('13');
  const beforeCompare=await invoke('commerce_workspace_get',{case_id:caseId});
  await dialog.getByRole('button',{name:'比较当前报价',exact:true}).click();
  const comparison=dialog.locator('[aria-label="报价比较结果"]');await comparison.waitFor();
  assert.match(await comparison.innerText(),/468\.00 CNY/);
  assert.match(await comparison.innerText(),/700\.00 CNY/);
  assert.equal((await invoke('commerce_workspace_get',{case_id:caseId})).artifacts.supply.sha256,beforeCompare.artifacts.supply.sha256,'comparing never selects a supplier');
  await dialog.locator('#pw-quote-quantity').fill('14');assert.equal(await comparison.count(),0,'edited quantity withdraws old totals and selection actions');
  await dialog.locator('#pw-quote-quantity').fill('13');
  await dialog.locator('#pw-quote-quantity').press('Enter');await comparison.waitFor();
  const versionBeforeChange=await invoke('commerce_workspace_get',{case_id:caseId}),changed=versionBeforeChange.supply_quotes.items.find(q=>q.quote_id==='small-moq');
  await invoke('commerce_workspace_quote_save',{case_id:caseId,quote_id:'small-moq',payload:{...changed.fields,purchase_cost:37},expected_revision:changed.revision,expected_source_sha256:versionBeforeChange.source_sha256,idempotency_key:'change-after-comparison'});
  await comparison.locator('tr').filter({hasText:'Synthetic smaller MOQ'}).getByRole('button',{name:'选用此报价',exact:true}).click();
  await dialog.getByText('资料已更新，输入已保留。请核对后重新保存。',{exact:true}).waitFor();
  assert.equal(await dialog.locator('#pw-quote-quantity').inputValue(),'13');assert.equal(await comparison.count(),0);
  assert.equal((await invoke('commerce_workspace_get',{case_id:caseId})).artifacts.supply.sha256,beforeCompare.artifacts.supply.sha256,'stale comparison cannot select a changed quote');
  await dialog.getByRole('button',{name:'比较当前报价',exact:true}).click();await comparison.waitFor();
  assert.match(await comparison.innerText(),/481\.00 CNY/);
  // Hold a real read response, close the dialog, then allow the late response.
  let releaseRead,readReached;
  const released=new Promise(resolve=>{releaseRead=resolve}),reached=new Promise(resolve=>{readReached=resolve});
  await page.route('**/v1/invoke',async route=>{
    if(route.request().postDataJSON()?.tool!=='commerce_workspace_quote_compare')return route.continue();
    const response=await route.fetch();readReached();await released;return route.fulfill({response});
  });
  const delayed=page.waitForResponse(response=>response.url().endsWith('/v1/invoke')&&response.request().postDataJSON()?.tool==='commerce_workspace_quote_compare');
  await dialog.getByRole('button',{name:'比较当前报价',exact:true}).click();await reached;
  await dialog.locator('[data-pw-action="dialog-close"]').click();releaseRead();await delayed;
  await page.locator('#pw-main[aria-busy="false"]').waitFor();assert.equal(await dialog.count(),0,'late comparison cannot reopen a closed dialog');
  assert.equal(await page.evaluate(()=>document.activeElement?.dataset.pwAction),'quotes','closing and late results retain the original trigger focus');
  assert.equal(await page.evaluate(()=>document.activeElement?.textContent.trim()),'管理报价','focus returns to the exact product trigger instead of an assistant shortcut');
  await page.unroute('**/v1/invoke');
  await page.getByRole('button',{name:'管理报价',exact:true}).click();
  assert.equal(await dialog.locator('#pw-quote-quantity').inputValue(),'13');
  assert.equal(await comparison.count(),0,'reopening requires a fresh comparison');
  await dialog.getByRole('button',{name:'比较当前报价',exact:true}).click();await comparison.waitFor();
  if(process.env.QA_OUTPUT_DIR) {
    await mkdir(process.env.QA_OUTPUT_DIR,{recursive:true});
    for(const width of [1440,390]) {await page.setViewportSize({width,height:960});for(const theme of ['light','dark']) {
      await page.evaluate(theme=>window.CommerceUI.applyTheme(theme),theme);
      const box=await dialog.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1);
      const moneyCell=await comparison.locator('td:nth-child(5)').first().boundingBox();assert.ok(moneyCell.width>=120,'money columns must remain readable');
      if(width===390){const table=comparison.locator('.ui-table').first();if(await table.evaluate(el=>el.scrollWidth>el.clientWidth+1))assert.equal(await table.getAttribute('tabindex'),'0');else assert.ok(await comparison.locator('td:nth-child(5)').first().isVisible(),'compact money cells remain readable without horizontal scrolling')}
      await page.screenshot({path:path.join(process.env.QA_OUTPUT_DIR,`supply-${width}-${theme}.png`),animations:'disabled'});
    }}
  }
  await page.setViewportSize({width:1440,height:960});
  await comparison.locator('tbody tr').filter({hasText:'Synthetic supplier UI'}).getByRole('button',{name:'选用此报价',exact:true}).click();
  await dialog.getByText('已选用',{exact:true}).waitFor();
  saved=await invoke('commerce_workspace_get',{case_id:caseId});
  const costInput={currency:'CNY',price:239,purchase_cost:35,domestic_shipping:5,packaging:3,fulfillment_cost:12,electronic_fee:0,commission_rate:.1,payment_rate:.02,return_rate:.03,ad_rate:.05};
  const costSaved=await invoke('commerce_workspace_save',{case_id:caseId,form:'cost',payload:{input:costInput},expected_revision:saved.forms.cost.revision,expected_source_sha256:saved.source_sha256});
  await invoke('commerce_workspace_calculate',{case_id:caseId,expected_revision:costSaved.revision,expected_source_sha256:saved.source_sha256});
  await dialog.locator('[data-pw-action="dialog-close"]').click();
  await page.reload();
  await page.locator('#pw-main[aria-busy="false"]').waitFor();
  await page.locator('[data-pw-tab="content"]').click();
  await page.locator('#pw-content-source').selectOption(saved.content_sources[0].id);
  await page.locator('[data-pw-action="fill-content"]').click();
  await page.locator('[data-pw-action="preview-content"]').click();
  await page.getByRole('button',{name:'交付审阅清单',exact:true}).click({timeout:5000});
  await dialog.locator('#pw-delivery-facts-status').selectOption('confirmed');
  await dialog.locator('#pw-delivery-facts-source').fill('synthetic:review-facts');
  assert.equal(await dialog.getByRole('button',{name:'确认本地交付审阅',exact:true}).isEnabled(),false);
  await dialog.getByRole('button',{name:'保存待核清单',exact:true}).click();
  await dialog.getByText('待核清单已保存',{exact:true}).waitFor();
  const delivery=await invoke('commerce_workspace_delivery_get',{case_id:caseId});
  assert.equal(delivery.checks.facts.status,'confirmed');assert.equal(delivery.status,'needs_inputs');
  assert.equal(delivery.checks.media_rights.status,'pending');
  for(const key of ['translation','media_rights','platform_rules']) {
    await dialog.locator('#pw-delivery-'+key+'-status').selectOption('confirmed');
    await dialog.locator('#pw-delivery-'+key+'-source').fill('synthetic:review-'+key);
  }
  assert.equal(await dialog.getByRole('button',{name:'确认本地交付审阅',exact:true}).isEnabled(),true);
  await dialog.getByRole('button',{name:'确认本地交付审阅',exact:true}).click();
  await dialog.getByText('本地交付审阅已记录',{exact:true}).waitFor();
  const completeDelivery=await invoke('commerce_workspace_delivery_get',{case_id:caseId});
  assert.equal(completeDelivery.status,'local_review_recorded');
  const manifest=await invoke('commerce_workspace_delivery_export',{case_id:caseId,expected_package_sha256:completeDelivery.package_sha256});
  assert.equal(JSON.parse(manifest.content).platform_submission,'not_performed');
  if(process.env.QA_OUTPUT_DIR)for(const width of [1440,390]) {await page.setViewportSize({width,height:960});for(const theme of ['light','dark']) {
    await page.evaluate(theme=>window.CommerceUI.applyTheme(theme),theme);
    const box=await dialog.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1);
    await page.screenshot({path:path.join(process.env.QA_OUTPUT_DIR,`delivery-${width}-${theme}.png`),animations:'disabled'});
  }}
  const beforeChange=await invoke('commerce_workspace_get',{case_id:caseId}),quote=beforeChange.supply_quotes.items[0];
  await invoke('commerce_workspace_quote_save',{case_id:caseId,quote_id:quote.quote_id,payload:{...quote.fields,purchase_cost:34},expected_revision:quote.revision,expected_source_sha256:beforeChange.source_sha256,idempotency_key:'changed-after-delivery'});
  await dialog.locator('#pw-delivery-facts-source').fill('synthetic:keep-my-input');
  await dialog.getByRole('button',{name:'保存待核清单',exact:true}).click();
  await dialog.getByText('资料已更新，输入已保留。请核对后重新保存。',{exact:true}).waitFor();
  assert.equal(await dialog.locator('#pw-delivery-facts-source').inputValue(),'synthetic:keep-my-input');
  assert.equal(await dialog.getByRole('button',{name:'确认本地交付审阅',exact:true}).isEnabled(),false);
  await dialog.getByRole('button',{name:'读取当前版本并重新核对',exact:true}).click();
  await dialog.getByText('已读取当前版本，文字已保留，请重新核对。',{exact:true}).waitFor();
  assert.equal(await dialog.locator('#pw-delivery-facts-status').inputValue(),'pending');
  assert.equal(await dialog.locator('#pw-delivery-facts-source').inputValue(),'synthetic:keep-my-input');
  await page.setViewportSize({width:1440,height:960});
  const skillCases=(await invoke('commerce_skills_cases')).cases.length;
  await page.goto(origin+'/legacy?tab=skills');
  await page.locator('#skills-query').fill('sealeap-tiktokshop-unit-economics');
  await page.locator('[data-skills-action="search"]').click();
  await page.locator('[data-skills-action="open"][data-skill="sealeap-tiktokshop-unit-economics"]').click();
  await page.getByRole('button',{name:'检查执行条件',exact:true}).click({timeout:5000});
  const readiness=page.getByRole('region',{name:'技能执行条件',exact:true});
  await readiness.getByText('待补输入或执行器条件',{exact:true}).waitFor();
  await page.locator('[data-skills-action="example"]').click();
  await page.getByRole('button',{name:'检查执行条件',exact:true}).click();
  await readiness.getByText('可明确发起本机离线检查',{exact:true}).waitFor();
  assert.ok((await readiness.innerText()).includes('账户与权限未核实'));
  if(process.env.QA_OUTPUT_DIR)for(const width of [1440,390]) {await page.setViewportSize({width,height:960});for(const theme of ['light','dark']) {
    await page.evaluate(theme=>window.CommerceUI.applyTheme(theme),theme);
    await readiness.scrollIntoViewIfNeeded();
    const fits=await readiness.evaluate(el=>el.querySelector('table').getBoundingClientRect().width<=el.clientWidth+1);
    assert.ok(fits,'skill conditions remain readable without horizontal scrolling');
    await page.screenshot({path:path.join(process.env.QA_OUTPUT_DIR,`readiness-${width}-${theme}.png`),animations:'disabled'});
  }}
  assert.equal((await invoke('commerce_skills_cases')).cases.length,skillCases,'checking readiness creates no task');
  await page.locator('#skills-input').fill('{}');
  assert.equal(await readiness.count(),0,'changing input invalidates the previous readiness card');
  assert.deepEqual(pageErrors,[]);assert.deepEqual(external,[]);
  assert.equal(await readManifestHash(),candidate,'Source candidate changed during UI acceptance');
  console.log(JSON.stringify({status:'Passed',candidate_manifest_sha256:candidate,checks:['quotation save vs select','immutable quote versions','MOQ and pack quantities compare exact goods subtotals without selecting a supplier','edited quantities withdraw old results','stale quotation comparisons cannot select changed versions','late reads do not reopen dialogs and retain trigger focus','comparison columns retain readable widths and keyboard overflow','selected revision invalidates gate','delivery checklist preserves pending rights and blocks incomplete approval','private delivery manifest','read-only skill conditions without preparing tasks','input changes invalidate old readiness','shared views light/dark 1440/390'],page_errors:pageErrors,external_requests:external}));
} finally {await browser?.close();server.kill('SIGTERM');}
