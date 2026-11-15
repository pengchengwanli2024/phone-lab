import assert from 'node:assert/strict';
import path from 'node:path';
export async function ownerReviewChecks({page,origin,output,invoke,checks}){
  const target={case_id:'b619'.repeat(8),platform:'ozon',store_ref:'ozon-live',market:'RU'},tasks=(await invoke('commerce_task_list')).tasks.length;
  const url=origin+'/workspace?host=harness&tab=listing&demo=false&case_id='+target.case_id+'&listing_platform=ozon&listing_store=ozon-live&listing_market=RU';
  await page.goto(url);const panel=page.locator('#listing-owner-review');
  await panel.getByText('待逐项核对',{exact:true}).waitFor();assert.ok(await panel.getByRole('button',{name:'签收当前版本',exact:true}).isDisabled());
  await page.getByRole('button',{name:'处理检查：平台规则与资质专业核查',exact:true}).click();await page.waitForFunction(()=>document.activeElement?.id==='listing-owner-review');
  await panel.getByText('核对保存版本的产品信息与图片',{exact:true}).click();await panel.getByRole('img',{name:'申请产品图片 1',exact:true}).waitFor();
  assert.ok(await panel.getByRole('img',{name:'申请产品图片 1',exact:true}).evaluate(img=>img.complete&&img.naturalWidth>0));
  await panel.getByRole('textbox',{name:'经营负责人姓名或标识',exact:true}).fill('Synthetic owner');
  const first=(await invoke('commerce_owner_review_get',target)),keys=Object.keys(first.requirements);
  await panel.getByRole('textbox',{name:'核对说明 · '+first.requirements[keys[0]],exact:true}).fill('Synthetic pending draft');
  await panel.getByRole('button',{name:'保存核查草稿',exact:true}).click();await panel.getByText('核查草稿已保存。',{exact:true}).waitFor();
  await page.reload();await panel.getByRole('textbox',{name:'经营负责人姓名或标识',exact:true}).waitFor();assert.equal(await panel.getByRole('textbox',{name:'核对说明 · '+first.requirements[keys[0]],exact:true}).inputValue(),'Synthetic pending draft');
  checks.push('Owner review is reachable from the missing gate, shows decoded saved-product images, and persists a pending checklist without signing or submitting');
  await panel.getByRole('textbox',{name:'核对说明 · '+first.requirements[keys[0]],exact:true}).fill('Synthetic unsaved conflict retained');
  let v=await invoke('commerce_owner_review_get',target);
  await invoke('commerce_owner_review_record',{...target,expected_binding_sha256:v.binding_sha256,expected_review_sha256:v.review_sha256,checks:v.checks,decision:'save',reviewer:'Synthetic other window',confirmed:false,idempotency_key:'synthetic-owner-conflict'});
  await panel.getByRole('button',{name:'保存核查草稿',exact:true}).click();await panel.getByRole('alert').filter({hasText:'当前输入保留'}).waitFor();assert.equal(await panel.getByRole('textbox',{name:'核对说明 · '+first.requirements[keys[0]],exact:true}).inputValue(),'Synthetic unsaved conflict retained');
  await panel.getByRole('button',{name:'读取当前核查包',exact:true}).click();await panel.getByRole('button',{name:'采用当前核查包并重新核对',exact:true}).click();
  for(const key of keys){await panel.getByRole('combobox',{name:'核对结论 · '+first.requirements[key],exact:true}).selectOption(key==='qualifications'?'not_applicable':'confirmed');await panel.getByRole('textbox',{name:'依据或记录位置 · '+first.requirements[key],exact:true}).fill('synthetic:'+key);if(key==='qualifications')await panel.getByRole('textbox',{name:'核对说明 · '+first.requirements[key],exact:true}).fill('Synthetic rule: certificate not applicable');}
  assert.ok(await panel.getByRole('button',{name:'签收当前版本',exact:true}).isDisabled());
  await panel.getByRole('checkbox').check();await panel.getByRole('button',{name:'签收当前版本',exact:true}).click();await panel.getByText('已记录经营负责人签收；不属于独立认证，未提交平台。',{exact:true}).waitFor();
  v=await invoke('commerce_owner_review_get',target);assert.equal(v.current,true);assert.equal(v.independent_certification,false);assert.equal(v.external_execution_allowed,false);
  assert.equal((await invoke('commerce_organization_board',{case_id:target.case_id})).stages.find(s=>s.id==='S6').status,'PASS');
  checks.push('Concurrent owner edits preserve input and require explicit current-package adoption; all criteria, evidence, owner identity and declaration are needed for a version-bound non-independent signoff');
  for(const width of [1440,390])for(const theme of ['light','dark']){
    await page.setViewportSize({width,height:960});await page.locator('#react-theme').selectOption(theme);await page.waitForFunction(()=>!document.querySelector('#react-theme')?.disabled);
    await panel.getByRole('heading',{name:'经营负责人发布前核查',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,`owner-review-${width}-${theme}.png`),animations:'disabled'});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  }
  let plan=await invoke('commerce_listing_get',target);await invoke('commerce_listing_save',{...target,payload:{...plan.payload,fields:{...plan.payload.fields,title:'Synthetic changed product title'}},expected_revision:plan.revision,expected_source_sha256:plan.source_sha256});
  await panel.getByRole('button',{name:'读取当前核查包',exact:true}).click();await panel.getByText('资料版本已变化',{exact:true}).waitFor();assert.ok(await panel.getByRole('button',{name:'签收当前版本',exact:true}).isDisabled());assert.equal(await panel.getByRole('combobox').first().inputValue(),'pending');
  await panel.getByRole('checkbox').check();await panel.getByRole('button',{name:'撤销签收',exact:true}).click();await panel.getByText('已撤销负责人签收，原历史保留。',{exact:true}).waitFor();
  assert.equal((await invoke('commerce_owner_review_get',target)).current,false);assert.equal((await invoke('commerce_task_list')).tasks.length,tasks);
  checks.push('Signed owner package fits light/dark 1440/390; changing saved product data invalidates signoff, clears carried conclusions, and withdrawal retains history with no external task');
  const legacy=async route=>{const call=route.request().postDataJSON();if(call?.tool==='commerce_listing_get'){const response=await route.fetch();const body=await response.json();delete body.owner_review_available;await route.fulfill({response,json:body});}else await route.fallback();};
  await page.route('**/v1/invoke',legacy);await page.reload();await page.getByRole('heading',{name:'上架准备',exact:true}).waitFor();await page.locator('#listing-release').waitFor();assert.equal(await panel.count(),0);await page.unroute('**/v1/invoke',legacy);
  checks.push('Older services without the capability flag keep the existing listing page and do not expose an unusable owner-review action');
  await page.setViewportSize({width:1440,height:960});
}
