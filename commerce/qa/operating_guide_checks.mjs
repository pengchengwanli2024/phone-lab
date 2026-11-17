import assert from 'node:assert/strict';

export async function operatingGuideChecks({page,origin,invoke,checks,output}){
  const target={case_id:'b619'.repeat(8),platform:'ozon',store_ref:'ozon-live',market:'RU'};
  const address=t=>origin+'/workspace?host=harness&tab=listing&demo=false&'+new URLSearchParams({...t,listing_platform:t.platform,listing_store:t.store_ref,listing_market:t.market});
  const before=(await invoke('commerce_task_list')).tasks.map(t=>t.id),plan=await invoke('commerce_listing_get',target),owner=await invoke('commerce_owner_review_get',target);
  const reads=[];page.on('request',request=>{if(request.url().endsWith('/v1/invoke')){const call=request.postDataJSON();if(call?.tool==='commerce_operating_pipeline_get')reads.push(call.arguments);}});
  await page.goto(address(target));await page.getByRole('heading',{name:'上架准备',exact:true}).waitFor();
  assert.equal(reads.length,0,'collapsed guidance must not start another product scan');
  await page.getByText('查看同商品经营缺项',{exact:true}).click();const launch=page.locator('section').filter({has:page.getByRole('heading',{name:'商品到发布：当前缺项',exact:true})}).last();
  await launch.getByRole('button',{name:'核对市场研究',exact:true}).waitFor();assert.equal(reads.length,1);assert.deepEqual(reads[0],{...target,goal:'launch'});
  assert.ok((await launch.innerText()).includes('以下为原资料诊断'));assert.equal((await invoke('commerce_listing_get',target)).revision,plan.revision);assert.equal((await invoke('commerce_owner_review_get',target)).review_sha256,owner.review_sha256);
  checks.push('Exact Ozon product/store/market guidance reads original pipeline only when expanded; original listing and owner review remain unchanged');
  const listingStage=launch.locator('.r-operation-list > li').filter({hasText:'目标店铺上架与结果回读'});
  const contentLabel=plan.checks.find(c=>c.id==='content').label,offerLabel=plan.checks.find(c=>c.id==='offer').label;
  await listingStage.getByRole('button',{name:'补充：'+contentLabel,exact:true}).waitFor();
  assert.ok((await listingStage.innerText()).includes(offerLabel));assert.doesNotMatch(await listingStage.innerText(),/^\s*(content|offer)\s*$/m);
  await listingStage.getByRole('button',{name:'补充：'+offerLabel,exact:true}).click();await page.waitForFunction(()=>document.activeElement?.id==='listing-field-quantity');
  await page.getByRole('button',{name:'核对申请与回执',exact:true}).click();await page.waitForFunction(()=>document.activeElement?.id==='listing-release');
  assert.equal(await page.locator('#listing-store-ref').inputValue(),target.store_ref);
  checks.push('Original missing-check labels replace implementation IDs; each gap opens its exact original field and receipt navigation focuses the original ledger without changing scope');
  await page.locator('#listing-field-quantity').fill('8');await launch.getByText('当前方案有未保存修改，保存后核对同一版本。',{exact:true}).waitFor();assert.ok(await launch.getByRole('button',{name:'重新核对经营缺项',exact:true}).isDisabled());assert.equal(await launch.getByRole('button',{name:'核对市场研究',exact:true}).count(),0);assert.equal(await page.locator('#listing-field-quantity').inputValue(),'8');
  checks.push('Unsaved listing edits withdraw old guidance and navigation without saving, executing or losing input');
  await page.goto(address(target));await page.getByText('查看同商品经营缺项',{exact:true}).click();await page.getByRole('button',{name:'核对市场研究',exact:true}).waitFor();
  let held,release,delivered;const delivery=new Promise(r=>delivered=r);const entered=new Promise(r=>held=r),gate=new Promise(r=>release=r);const hold=async route=>{const call=route.request().postDataJSON();if(call?.tool==='commerce_operating_pipeline_get'){const response=await route.fetch();held();await gate;await route.fulfill({response});delivered();}else await route.fallback();};
  await page.route('**/v1/invoke',hold);await page.getByRole('button',{name:'重新核对经营缺项',exact:true}).click();await entered;
  await page.locator('#listing-field-quantity').fill('9');release();await delivery;await page.unroute('**/v1/invoke',hold);await page.getByText('当前方案有未保存修改，保存后核对同一版本。',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'核对市场研究',exact:true}).count(),0);assert.equal(await page.locator('#listing-field-quantity').inputValue(),'9');
  checks.push('Late pipeline response cannot restore stale actions after a local edit');
  await page.goto(origin+'/workspace?host=harness&tab=store-ops&demo=false');await page.getByRole('heading',{name:'已保存上架方案',exact:true}).waitFor();
  const entry=page.locator('.r-operation-list > li').filter({hasText:plan.name}).filter({hasText:'ozon-live'}).first();await entry.getByRole('button',{name:'查看日常经营缺项',exact:true}).click();await page.getByRole('heading',{name:'日常经营：当前缺项',exact:true}).waitFor();await page.getByText('处理能力待接入',{exact:false}).first().waitFor();
  assert.ok(reads.some(r=>r.case_id===target.case_id&&r.store_ref===target.store_ref&&r.market==='RU'&&r.goal==='operate'));
  await page.getByRole('button',{name:'核对同商品上架方案与回执',exact:true}).click();await page.getByRole('heading',{name:'上架准备',exact:true}).waitFor();await page.waitForFunction(store=>document.querySelector('#listing-store-ref')?.value===store,target.store_ref);assert.equal(await page.locator('#listing-store-ref').inputValue(),target.store_ref);assert.equal(await page.locator('#listing-market').inputValue(),'RU');
  checks.push('Daily operations expands the exact saved product scope, names missing operational adapters and returns to its original listing/receipts');
  await page.getByText('查看同商品经营缺项',{exact:true}).click();await page.getByRole('button',{name:'核对市场研究',exact:true}).waitFor();
  for(const width of [1440,390])for(const theme of ['light','dark']){await page.setViewportSize({width,height:1000});await page.locator('#react-theme').selectOption(theme);await page.getByRole('heading',{name:'商品到发布：当前缺项',exact:true}).scrollIntoViewIfNeeded();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));if(width===1440&&theme==='light'||width===390&&theme==='dark')await page.screenshot({path:output+`/operating-${width}-${theme}.png`});}
  assert.deepEqual((await invoke('commerce_task_list')).tasks.map(t=>t.id),before);assert.equal((await invoke('commerce_listing_get',target)).revision,plan.revision);assert.equal((await invoke('commerce_owner_review_get',target)).review_sha256,owner.review_sha256);
  checks.push('Operating guidance fits desktop/narrow light/dark and creates no task, publication or signoff');
  await page.setViewportSize({width:1440,height:1000});
  const policy=plan.checks.find(c=>['rules','professional_gate','platform_schema'].includes(c.id)&&c.status!=='prepared')?.id||'rules';
  await page.getByRole('button',{name:'核对发布依据',exact:true}).click();const policyField={rules:'listing-rules_ref',professional_gate:'listing-owner-review',platform_schema:'listing-platform-schema'}[policy];await page.waitForFunction(id=>document.activeElement?.id===id,policyField);
  checks.push('Policy guidance delegates the original listing gate and focuses its rule, owner-review or schema control instead of the product-content review');
  const warning='目标申请历史超过200条，本轮未完整核查；不得推断没有更早未决申请';
  const uncertain=async route=>{if(route.request().postDataJSON()?.tool!=='commerce_operating_pipeline_get')return route.fallback();const response=await route.fetch(),value=await response.json();value.release_history_complete=false;value.stages.find(s=>s.id==='listing').missing.push(warning,'future_check');await route.fulfill({response,json:value});};
  await page.route('**/v1/invoke',uncertain);await page.getByRole('button',{name:'重新核对经营缺项',exact:true}).click();
  const expandedListing=page.locator('.r-operation-list > li').filter({hasText:'目标店铺上架与结果回读'});await expandedListing.getByRole('button',{name:'补充：'+contentLabel,exact:true}).waitFor();await expandedListing.getByText('查看完整缺项与依据限制',{exact:true}).click();
  await expandedListing.getByText(warning,{exact:true}).waitFor();await expandedListing.getByText('发布检查项待核对，请查看发布前检查。',{exact:true}).waitFor();assert.equal(await expandedListing.getByRole('button',{name:warning,exact:true}).count(),0);assert.ok(!(await expandedListing.innerText()).includes('future_check'));await page.unroute('**/v1/invoke',uncertain);
  checks.push('Incomplete original release history keeps its exact diagnostic reason; a new unknown check ID falls back safely without becoming an executable gap');
  // A separate explicit local edit simulates a second operator, after readonly assertions.
  const changed={...plan.payload,fields:{...plan.payload.fields,title:'Synthetic concurrent listing version'}};
  await invoke('commerce_listing_save',{...target,payload:changed,expected_revision:plan.revision,expected_source_sha256:plan.source_sha256});
  await page.getByRole('button',{name:'重新核对经营缺项',exact:true}).click();await page.getByRole('alert').filter({hasText:'经营依据与当前保存方案版本未能匹配'}).waitFor();assert.equal(await page.getByRole('button',{name:'核对市场研究',exact:true}).count(),0);
  await page.reload();await page.getByText('查看同商品经营缺项',{exact:true}).click();await page.getByRole('button',{name:'核对市场研究',exact:true}).waitFor();
  checks.push('A real concurrent original-listing save rejects guidance against the older page preview; explicit reread binds the new version without a second save or old approval');
}

export async function dailyExceptionChecks({page,origin,invoke,checks,output}){
  const now=Date.now(),record={event_id:'synthetic-r2-original',platform:'ozon',store_id:'SYN-R2-STORE',market:'RU',fulfillment:'FBS',warehouse:'SYN-R2-WH',observed_at:new Date(now-60000).toISOString(),source_ref:'synthetic:r2-order-observation',kind:'order',data:{order_id:'SYN-R2-ORDER',sku:'SYN-R2-SKU',quantity:2,status:'awaiting_packaging',ship_by:new Date(now+3600000).toISOString()}};
  await invoke('commerce_ops_record',{demo:true,record});const initial=await invoke('commerce_ops_list',{demo:true});const alert=initial.alerts.find(a=>a.order_id===record.data.order_id&&a.kind==='prepare');assert.ok(alert);assert.equal(alert.status,'active');
  await page.goto(origin+'/workspace?host=harness&tab=store-ops&demo=true');
  const row=page.locator('.r-operation-list > li').filter({hasText:record.data.sku}).first(),trigger=row.getByRole('button',{name:'核对原记录',exact:true});
  await trigger.click();const evidence=page.getByRole('dialog',{name:'经营提醒原记录',exact:true});await evidence.waitFor();await evidence.getByText('核对来源版本与规则',{exact:true}).click();
  for(const value of [record.data.order_id,record.data.sku,record.source_ref,record.observed_at,alert.source_sha256])assert.ok((await evidence.innerText()).includes(value));
  for(const width of [1440,390])for(const theme of ['light','dark']){await page.keyboard.press('Escape');await evidence.waitFor({state:'detached'});await page.setViewportSize({width,height:1000});await page.locator('#react-theme').selectOption(theme);await trigger.click();await evidence.waitFor();await evidence.getByText('核对来源版本与规则',{exact:true}).click();assert.ok(await evidence.evaluate(el=>el.scrollWidth<=el.clientWidth+1));if(output&&(width===1440&&theme==='light'||width===390&&theme==='dark'))await page.screenshot({path:output+`/exception-${width}-${theme}.png`});}
  await page.setViewportSize({width:1440,height:1000});
  assert.ok((await evidence.innerText()).includes('已阅不等于处理完成'));assert.equal((await invoke('commerce_ops_list',{demo:true})).alerts.find(a=>a.id===alert.id).status,'active');
  await page.keyboard.press('Escape');await evidence.waitFor({state:'detached'});assert.equal(await trigger.evaluate(el=>el===document.activeElement),true);
  await trigger.click();await evidence.waitFor();
  const fail=async route=>{if(route.request().postDataJSON()?.tool==='commerce_store_workbench')await route.abort();else await route.fallback();};await page.route('**/v1/invoke',fail);
  await evidence.getByRole('button',{name:'重新核对当前来源',exact:true}).click();await evidence.waitFor({state:'detached'});await page.getByRole('alert').first().waitFor();await page.unroute('**/v1/invoke',fail);
  assert.equal(await page.getByRole('button',{name:'核对原记录',exact:true}).count(),0);
  await page.getByRole('button',{name:'刷新当前资料',exact:true}).click();await trigger.waitFor();
  checks.push('Daily exception opens its exact original order/SKU/source/time/hash in place; Esc restores its trigger, readonly inspection does not acknowledge, failed refresh withdraws old detail and list before explicit recovery');
  await page.goto(origin+'/workspace?host=harness&tab=alerts&demo=true');const frame=page.frameLocator('iframe[title="专业业务模块"]');await frame.locator('#store-local-operations > summary').click();await frame.locator('#ops-scope').selectOption('demo');await frame.locator(`[data-ops-action="ack"][data-id="${alert.id}"]`).click();
  await frame.getByText('已阅 · 未确认处理',{exact:true}).waitFor();const acknowledged=(await invoke('commerce_ops_list',{demo:true})).alerts.find(a=>a.id===alert.id);assert.equal(acknowledged.status,'acknowledged');assert.equal(acknowledged.source_sha256,alert.source_sha256);
  await frame.getByText('手工补录与本地规则',{exact:true}).click();await frame.getByText('批量接入与数据模板',{exact:true}).click();
  const closedRecord={...record,event_id:'synthetic-r2-source-closed',observed_at:new Date().toISOString(),data:{...record.data,status:'cancelled'}};
  const imported=page.waitForResponse(response=>response.url().endsWith('/v1/invoke')&&response.request().postDataJSON()?.tool==='commerce_ops_record');
  await frame.locator('#ops-import').setInputFiles({name:'synthetic-r2-order-closed.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(closedRecord))});const receipt=await(await imported).json();assert.equal(receipt.status,'recorded');
  await frame.getByText('已由后续记录关闭',{exact:true}).first().waitFor();await frame.getByRole('button',{name:'刷新提醒',exact:true}).click();const closed=(await invoke('commerce_ops_list',{demo:true})).alerts.find(a=>a.id===alert.id);assert.equal(closed.status,'resolved');
  const repeated=await invoke('commerce_ops_record',{demo:true,record:closedRecord});assert.equal(repeated.status,'duplicate');assert.equal((await invoke('commerce_ops_list',{demo:true})).alerts.find(a=>a.id===alert.id).status,'resolved');
  checks.push('One isolated Ozon order exception follows original source → visible alert → acknowledge without resolving → explicit newer cancellation-source import → original alert closed → reread/idempotent receipt; no marketplace cancellation or message');
}
