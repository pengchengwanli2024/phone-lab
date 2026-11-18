// Real research form -> shared iframe bridge -> isolated HTTP/domain writes.
// Run in scripts/verify.py's existing sanitized source-copy environment.
import assert from 'node:assert/strict';
import {createHash,randomUUID} from 'node:crypto';
import {spawn} from 'node:child_process';
import {access,mkdir,mkdtemp,readFile,readdir,rm,writeFile} from 'node:fs/promises';
import {tmpdir,homedir} from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
import net from 'node:net';
import path from 'node:path';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const out=path.resolve(process.env.QA_OUTPUT_DIR||path.join(root,'.local/agent-team/builder/research-ui'));
await mkdir(out,{recursive:true});
const sources=['commerce/web/workbench.sources.json','commerce/web/workbench.bundle.js',
  'commerce/web/workbench.html','commerce/web/product-workspace.bundle.js','commerce/web/product-research-editor.js'];
const fingerprint=async()=>Object.fromEntries(await Promise.all(sources.map(async name=>
  [name,createHash('sha256').update(await readFile(path.join(root,name))).digest('hex')])));
const result={schema:'product-research-browser-v1',status:'failed',completed:false,syntheticFixture:true,
  scope:'Isolated synthetic HTTP/Chromium; no installed native host, real model or marketplace execution',
  checks:[],errors:[],external:[],intentionalFaults:[]};
const check=(name,details={})=>result.checks.push({name,passed:true,...details});
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function deadline(promise,ms,message){
  let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(message)),ms);})]);}
  finally{clearTimeout(timer);}
}
let work,child,stopped,browser,page,origin,releaseSave=()=>{},saveFinished=Promise.resolve();
let stderr='',spawnFailure='';
try{
  result.startHashes=await fingerprint();
  assert.equal(process.env.VERIFY_NODE_GUARD_ACTIVE,'1','Use the verifier network-guard environment');
  assert.ok(process.env.PYTHONPATH?.split(path.delimiter).includes(path.join(root,'scripts/verification')),
    'The Python fixture must inherit the verification preload path');
  let playwright;
  try{playwright=await import(process.env.PLAYWRIGHT_MODULE||'playwright');}
  catch{
    for(const entry of await readdir(path.join(homedir(),'.npm/_npx')).catch(()=>[])){
      try{playwright=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',entry,'node_modules/playwright/index.mjs')).href);break;}catch{}
    }
  }
  assert.ok(playwright?.chromium,'An existing Playwright installation is required; this gate never installs');
  const chrome=process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  await access(chrome);
  work=await mkdtemp(path.join(tmpdir(),'phone-lab-research-ui-'));
  const probe=net.createServer();
  await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));
  const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
  origin='http://127.0.0.1:'+port;
  // Inherit the sanitized environment, including PYTHONPATH and both guards.
  child=spawn(process.env.COMMERCE_PYTHON||'python3',[path.join(root,'commerce/qa/react_workbench_fixture.py')],
    {cwd:root,env:{...process.env,COMMERCE_STATE:work,COMMERCE_PORT:String(port)},stdio:['ignore','ignore','pipe']});
  stopped=new Promise(resolve=>child.once('close',resolve));
  child.on('error',error=>{spawnFailure=error.message;});
  child.stderr.on('data',chunk=>{stderr=(stderr+chunk.toString()).slice(-32768);});
  let ready=false;
  for(let attempt=0;attempt<150;attempt++){
    if(spawnFailure||child.exitCode!==null)throw Error('Owned fixture failed to start: '+spawnFailure);
    try{ready=(await fetch(origin+'/v1/health',{headers:{authorization:'Bearer synthetic-workbench-preview'}})).ok;}catch{}
    if(ready)break;await pause(100);
  }
  assert.ok(ready,'Owned synthetic fixture did not become ready');
  const invoke=async(tool,args={})=>{
    const response=await fetch(origin+'/v1/invoke',{method:'POST',
      headers:{authorization:'Bearer synthetic-workbench-preview','content-type':'application/json'},
      body:JSON.stringify({tool,arguments:args,client:'test'})});
    assert.equal(response.status,200,'Synthetic HTTP invocation failed: '+tool);
    return response.json();
  };
  const caseId=JSON.parse(await readFile(path.join(work,'fixture.json'),'utf8')).case_id;
  const workspace=()=>invoke('commerce_workspace_get',{case_id:caseId});
  const assertReadback=(value,receipt)=>{
    assert.equal(value.case.id,caseId);assert.equal(receipt.case_id,caseId);
    assert.equal(value.source_sha256,receipt.source_sha256);
    assert.equal(value.artifacts.research.id,receipt.artifact_id);
    assert.equal(value.artifacts.research.sha256,receipt.artifact_sha256);
    assert.equal(value.artifacts.research.intact,true);
    assert.equal(receipt.external_execution_allowed,false);
    assert.equal(receipt.external_operations_executed,false);
    assert.equal(receipt.publication_ready,false);
  };
  const original=await workspace();
  browser=await playwright.chromium.launch({headless:true,executablePath:chrome,
    args:['--use-mock-keychain','--password-store=basic']});
  const context=await browser.newContext({viewport:{width:1440,height:900}});
  await context.route('**/*',route=>{
    const url=route.request().url();
    if(url.startsWith(origin+'/')||/^(data|blob|about):/.test(url))return route.continue();
    result.external.push(new URL(url).origin);return route.abort();
  });
  page=await context.newPage();page.on('pageerror',error=>result.errors.push(error.message));
  const requests=[];
  page.on('request',request=>{
    if(request.url()===origin+'/v1/invoke'&&request.method()==='POST')requests.push(request.postDataJSON());
  });
  await page.goto(origin+'/login?token=synthetic-workbench-preview');
  const url=origin+'/workspace?tab=workspace&demo=true&case_id='+caseId;
  await page.goto(url);
  const product=page.frameLocator('iframe[title="完整商品内容编辑"]');
  const editor=()=>product.getByRole('dialog',{name:'补充当前商品研究资料',exact:true});
  const openEditor=async()=>{
    await product.locator('#pw-main[aria-busy="false"]').waitFor();
    await product.getByRole('tab',{name:'市场研究',exact:true}).click();
    await product.getByRole('button',{name:'补充资料',exact:true}).click();
    const dialog=editor();await dialog.locator('[data-pre-action="save"]:not(:disabled)').waitFor();
    return dialog;
  };
  const fillTitle=async(dialog,originalText,chineseText)=>{
    await dialog.locator('#pre-field-select').selectOption('title');
    await dialog.locator('#pre-original').fill(originalText);
    await dialog.locator('#pre-zh').fill(chineseText);
    assert.equal(await dialog.locator('#pre-reviewed').isChecked(),false,'Editing clears the old review flag');
    await dialog.locator('#pre-reviewed').check();
  };
  const saveResponse=()=>page.waitForResponse(response=>response.url()===origin+'/v1/invoke'
    &&response.request().postDataJSON()?.tool==='commerce_workspace_research_save');
  const modeGuard=async(blocked)=>{
    await page.getByRole('button',{name:'设置',exact:true}).click();
    const settings=page.getByRole('dialog',{name:'设置',exact:true});
    // A pointer click in the first frames after showModal() can still be routed to the
    // sandboxed product iframe underneath. Keyboard input follows focus, which the modal
    // already owns, so toggle the switch the way a keyboard user does and assert the result.
    const examples=settings.locator('#settings-examples');
    await examples.focus();await page.keyboard.press('Space');
    assert.equal(await examples.isChecked(),false,'Example-data switch must turn off');
    await settings.getByRole('button',{name:'切换数据范围',exact:true}).waitFor();
    await settings.getByRole('button',{name:'切换数据范围',exact:true}).click();
    const guard=page.getByRole('dialog',{name:blocked?'研究保存尚未确认':'保留当前商品的未保存输入',exact:true});
    await guard.waitFor();
    assert.equal(await guard.getByRole('button',{name:'放弃修改并继续',exact:true}).count(),blocked?0:1);
    return guard;
  };

  let dialog=await openEditor();
  const savedOriginal='Synthetic researched blender 12 kg';
  const savedChinese='合成研究榨汁机 12 kg，仍需核对来源。';
  await fillTitle(dialog,savedOriginal,savedChinese);
  const savedResponse=saveResponse();
  await dialog.locator('[data-pre-action="save"]').click();
  const firstResponse=await savedResponse;assert.equal(firstResponse.status(),200);
  const firstReceipt=await firstResponse.json();
  await dialog.waitFor({state:'hidden'});
  await product.getByText('当前商品研究资料已保存并精确读回；仍需核对完整缺项与来源。',{exact:true}).waitFor();
  let current=await workspace();assertReadback(current,firstReceipt);
  assert.notEqual(current.artifacts.research.id,original.artifacts.research.id);
  assert.equal(current.artifacts.research.payload.record.fields.title.original,savedOriginal);
  assert.equal(current.artifacts.research.payload.record.fields.title.zh,savedChinese);
  assert.equal(current.artifacts.research.payload.record.fields.title.reviewed,true);
  check('same_page_edit_save_readback');
  await page.reload();dialog=await openEditor();
  await dialog.locator('#pre-field-select').selectOption('title');
  assert.equal(await dialog.locator('#pre-original').inputValue(),savedOriginal);
  assert.equal(await dialog.locator('#pre-zh').inputValue(),savedChinese);
  assert.equal(await dialog.locator('#pre-reviewed').isChecked(),true);
  assertReadback(await workspace(),firstReceipt);check('refresh_preserves_saved_revision');
  await dialog.locator('[data-pre-action="close"]').click();await dialog.waitFor({state:'hidden'});

  dialog=await openEditor();
  const localOriginal='Synthetic local edit retained after a competing source change';
  await fillTitle(dialog,localOriginal,'另一合成调用变更后保留本地输入。');
  const base=await workspace(),competing=structuredClone(base.artifacts.research.payload.record);
  competing.raw_excerpt+=' A separate synthetic caller advanced this research head.';
  const competingReceipt=await invoke('commerce_workspace_research_save',{case_id:caseId,record:competing,
    expected_source_sha256:base.source_sha256,expected_artifact_id:base.artifacts.research.id,
    idempotency_key:'research-browser-competing-'+randomUUID()});
  const rejectedResponse=saveResponse();
  await dialog.locator('[data-pre-action="save"]').click();
  const rejected=await rejectedResponse;assert.ok(!rejected.ok(),'The stale browser save must be rejected');
  const rejectedBody=await rejected.json();
  assert.ok(['workspace_source_changed','workspace_research_conflict'].includes(rejectedBody.error));
  await dialog.getByText(/输入已保留，请(?:读取并核对当前保存版本|核对后再保存)/).waitFor();
  assert.equal(await dialog.locator('#pre-original').inputValue(),localOriginal);
  assertReadback(await workspace(),competingReceipt);
  check('changed_source_head_rejects_and_preserves_input');
  await dialog.locator('[data-pre-action="close"]').click();
  await dialog.getByRole('button',{name:'放弃本次输入',exact:true}).click();await dialog.waitFor({state:'hidden'});

  current=await workspace();
  const sparse=structuredClone(current.artifacts.research.payload.record);delete sparse.fields;
  const holdReceipt=await invoke('commerce_workspace_research_save',{case_id:caseId,record:sparse,
    expected_source_sha256:current.source_sha256,expected_artifact_id:current.artifacts.research.id,
    idempotency_key:'research-browser-sparse-'+randomUUID()});
  assert.equal(holdReceipt.validation_status,'HOLD');
  await page.setViewportSize({width:390,height:844});await page.reload();dialog=await openEditor();
  await dialog.locator('#pre-field-select').selectOption('title');
  assert.equal(await dialog.locator('#pre-original').inputValue(),'');
  assert.equal(await dialog.locator('#pre-zh').inputValue(),'');
  assertReadback(await workspace(),holdReceipt);
  check('sparse_hold_record_opens');
  const box=await dialog.boundingBox();
  assert.ok(box&&box.x>=-1&&box.x+box.width<=391,'The research dialog fits the narrow shared page');
  assert.ok(await product.locator('html').evaluate(element=>element.scrollWidth<=element.clientWidth+1));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  check('research_form_390');
  await page.screenshot({path:path.join(out,'product-research-390.png')});
  const sparseCheck=await invoke('commerce_collection_check',{record:sparse});
  const issue=sparseCheck.issues.find(row=>row.field==='description');
  assert.ok(issue,'The sparse record has a concrete editable description gap');
  await dialog.getByRole('button',{name:issue.message,exact:true}).click();
  const focus=await dialog.locator('#pre-original').evaluate(element=>new Promise(resolve=>requestAnimationFrame(()=>{
    const control=element.getBoundingClientRect(),modal=element.closest('.dialog').getBoundingClientRect();
    const top=Math.max(0,modal.top),bottom=Math.min(innerHeight,modal.bottom);
    resolve({focused:document.activeElement===element,editable:!element.disabled&&!element.readOnly,
      selected:document.querySelector('#pre-field-select').value,top:control.top,bottom:control.bottom,
      clipTop:top,clipBottom:bottom,fullyVisible:control.top>=top-1&&control.bottom<=bottom+1});
  })));
  assert.ok(focus.focused&&focus.editable&&focus.selected==='description'&&focus.fullyVisible,
    'A concrete gap must reveal and focus its editable field: '+JSON.stringify(focus));
  check('issue_link_focus_visible',focus);
  await dialog.locator('[data-pre-action="close"]').click();await dialog.waitFor({state:'hidden'});
  await page.setViewportSize({width:1440,height:900});

  dialog=await openEditor();
  const uncertainOriginal='Synthetic original-case save with a withheld committed response';
  await fillTitle(dialog,uncertainOriginal,'合成保存结果未确认时保持原商品和原请求。');
  const frameBefore=await page.locator('iframe[title="完整商品内容编辑"]').getAttribute('srcdoc');
  let committedResolve,committedReject,finishedResolve;
  const committed=new Promise((resolve,reject)=>{committedResolve=resolve;committedReject=reject;});
  const held=new Promise(resolve=>{releaseSave=resolve;});
  saveFinished=new Promise(resolve=>{finishedResolve=resolve;});
  const withheld=async route=>{
    const call=route.request().postDataJSON();
    if(call?.tool!=='commerce_workspace_research_save')return route.fallback();
    try{
      // Commit through the real endpoint, then lose only the response.
      const response=await route.fetch();assert.equal(response.status(),200);
      const receipt=await response.json();committedResolve({args:call.arguments,receipt});
      await held;await route.abort('failed');
    }catch(error){committedReject(error);result.errors.push('Owned save fault handler failed: '+error.message);await route.abort().catch(()=>{});}
    finally{finishedResolve();}
  };
  await page.route('**/v1/invoke',withheld);
  const beforePending=requests.filter(row=>row.tool==='commerce_workspace_research_save').length;
  await dialog.locator('[data-pre-action="save"]').click();
  const pending=await deadline(committed,15000,'The real synthetic save did not commit');
  assert.equal(pending.args.case_id,caseId);assertReadback(await workspace(),pending.receipt);
  assert.equal(await dialog.locator('#pre-original').isDisabled(),true);
  let guard=await modeGuard(true);
  await guard.getByRole('button',{name:'返回当前编辑',exact:true}).click();
  assert.equal(await page.locator('iframe[title="完整商品内容编辑"]').getAttribute('srcdoc'),frameBefore);
  assert.equal(await dialog.locator('#pre-original').inputValue(),uncertainOriginal);
  assert.equal(new URL(page.url()).searchParams.get('demo'),'true');
  check('inflight_mode_switch_keeps_original_editor');
  releaseSave();await deadline(saveFinished,5000,'The owned response-fault route did not finish');
  result.intentionalFaults.push('A real committed save response was withheld and then aborted');
  await dialog.locator('[data-pre-action="retry"]:not(:disabled)').waitFor();
  await dialog.getByText('原保存结果待确认；编辑已暂停，避免重复保存。',{exact:true}).waitFor();
  guard=await modeGuard(true);
  await guard.getByRole('button',{name:'返回当前编辑',exact:true}).click();
  assert.equal(await dialog.locator('#pre-original').inputValue(),uncertainOriginal);
  assert.equal(await dialog.locator('#pre-original').isDisabled(),true);
  assert.equal(requests.filter(row=>row.tool==='commerce_workspace_research_save').length,beforePending+1,'An unresolved write is never automatically resent');
  await page.unroute('**/v1/invoke',withheld);
  const retryResponse=saveResponse();
  await dialog.locator('[data-pre-action="retry"]').click();
  const retried=await retryResponse;assert.equal(retried.status(),200);
  assert.deepEqual(retried.request().postDataJSON().arguments,pending.args,'Recovery reuses the exact original request and case');
  assert.deepEqual(await retried.json(),pending.receipt,'Recovery returns the original durable receipt');
  await dialog.waitFor({state:'hidden'});
  assertReadback(await workspace(),pending.receipt);
  assert.equal(new URL(page.url()).searchParams.get('case_id'),caseId);
  assert.equal(new URL(page.url()).searchParams.get('demo'),'true');
  check('unknown_mode_switch_and_same_request_recovery');

  const beforeDiscard=await workspace();
  dialog=await openEditor();
  await dialog.locator('#pre-field-select').selectOption('title');
  await dialog.locator('#pre-original').fill('Synthetic unsaved input that may be explicitly discarded');
  guard=await modeGuard(false);
  await guard.getByRole('button',{name:'放弃修改并继续',exact:true}).click();
  await page.waitForURL(value=>!value.searchParams.has('demo')||value.searchParams.get('demo')==='false');
  assert.equal(await page.locator('.r-data-scope').innerText(),'当前资料');
  await product.locator('#pw-main[aria-busy="false"]').waitFor();
  assert.equal(await editor().count(),0);
  const afterDiscard=await workspace();
  assert.equal(afterDiscard.source_sha256,beforeDiscard.source_sha256);
  assert.equal(afterDiscard.artifacts.research.id,beforeDiscard.artifacts.research.id);
  assert.equal(afterDiscard.artifacts.research.payload.record.fields.title.original,uncertainOriginal);
  check('ordinary_dirty_can_be_discarded');
  assert.equal(requests.some(row=>/commerce_(?:copilot_send|live_sync|.*submit|.*generate)/.test(row.tool)),false,'The form regression never requests a model or external execution');
  assert.deepEqual(result.errors,[]);assert.deepEqual(result.external,[]);
  result.browser=await browser.version();result.completed=true;
}catch(error){
  result.fatal=error.stack||String(error);
  if(page)await page.screenshot({path:path.join(out,'product-research-failure.png')}).catch(()=>{});
}finally{
  releaseSave();await deadline(saveFinished,5000,'Owned response route cleanup timed out').catch(error=>{result.fatal ||= error.message;});
  await browser?.close().catch(error=>{result.fatal ||= error.message;});
  if(child){
    if(child.exitCode===null)child.kill('SIGTERM');
    try{await deadline(stopped,5000,'Owned fixture cleanup timed out');}
    catch{child.kill('SIGKILL');await stopped;}
  }
  if(work)await rm(work,{recursive:true,force:true});
  try{result.endHashes=await fingerprint();result.sourceStable=JSON.stringify(result.startHashes)===JSON.stringify(result.endHashes);}
  catch(error){result.sourceStable=false;result.fatal ||= error.message;}
  const passed=result.completed&&result.sourceStable&&!result.fatal&&result.checks.length>0
    &&result.checks.every(row=>row.passed===true)&&result.errors.length===0&&result.external.length===0;
  result.status=passed?'passed':'failed';
  await writeFile(path.join(out,'product-research-browser.json'),JSON.stringify(result,null,2)+'\n');
  if(!passed){await writeFile(path.join(out,'product-research-fixture.log'),stderr);process.exitCode=1;console.error(result.fatal||'Research browser acceptance failed');}
  else console.log(JSON.stringify({completed:result.completed,sourceStable:result.sourceStable,checks:result.checks,external:result.external}));
}
