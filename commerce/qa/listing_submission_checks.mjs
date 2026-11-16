import assert from 'node:assert/strict';
import path from 'node:path';
export async function listingSubmissionChecks({page,origin,output,invoke,checks}){
 const target={case_id:'b619'.repeat(8),platform:'ozon',store_ref:'ozon-live',market:'RU'};
 const url=origin+'/workspace?host=harness&tab=listing&demo=false&case_id='+target.case_id+'&listing_platform=ozon&listing_store=ozon-live&listing_market=RU';
 await page.goto(url);const panel=page.getByRole('region',{name:'单商品整卡提交',exact:true});
 const probe=panel.getByRole('button',{name:'只读核对发布前平台资料',exact:true}),freeze=panel.getByRole('button',{name:'固定准确整卡请求',exact:true});
 await probe.waitFor();assert.ok(await freeze.isDisabled());assert.equal((await (await fetch(origin+'/qa-submission')).json()).writes,0);
 await probe.click();await page.waitForFunction(()=>Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='固定准确整卡请求'&&!b.disabled));
 await freeze.click();await panel.getByText('待明确执行确认',{exact:true}).waitFor();
 await panel.getByText('准确请求 JSON 与 SHA256',{exact:true}).click();const body=JSON.parse(await panel.locator('pre').innerText());assert.ok(body.items[0].attributes.some(a=>a.id===999));assert.equal(body.items[0].depth,100);assert.ok(!('quantity'in body.items[0]));
 const submit=panel.getByRole('button',{name:'确认并单次提交到 Ozon',exact:true});assert.ok(await submit.isDisabled());
 await panel.getByRole('textbox',{name:'本次执行人',exact:true}).fill('Synthetic UI operator');await panel.getByRole('checkbox',{name:'确认按此准确请求更新现有商品的资料、价格和图片，不写库存',exact:true}).check();await submit.click();
 const unknown=process.env.COMMERCE_QA_SUBMISSION_UNKNOWN==='1';
 await panel.getByText(unknown?'提交结果未知，禁止重发':'平台返回任务，等待回读',{exact:true}).waitFor();
 assert.equal((await (await fetch(origin+'/qa-submission')).json()).writes,1);
 await page.reload();await panel.getByText(unknown?'提交结果未知，禁止重发':'平台返回任务，等待回读',{exact:true}).waitFor();assert.equal(await panel.getByRole('button',{name:'确认并单次提交到 Ozon',exact:true}).count(),0);await panel.getByText('本次执行或核对人：Synthetic UI operator',{exact:true}).waitFor();
 const release=page.locator('#listing-release');
 if(unknown){
  await release.getByRole('textbox',{name:'Ozon 导入任务编号',exact:true}).fill('777777');await release.getByRole('textbox',{name:'外部提交依据',exact:true}).fill('synthetic:operator-platform-task');
  await release.getByRole('checkbox',{name:'确认此任务是我在 Ozon 后台核对的对应引用，尚非本系统提交回执',exact:true}).check();await release.getByRole('button',{name:'记录外部任务引用',exact:true}).click();
 }
 await release.getByRole('button',{name:'读取并核对外部回执',exact:true}).click();await release.getByText('已回读对应商品，发布状态仍需核对',{exact:true}).waitFor();
 if(unknown){
  await probe.click();await page.waitForFunction(()=>Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='只读核对发布前平台资料'&&!b.disabled));
  await panel.getByText('核对未知提交并记录本人声明',{exact:true}).click();await panel.getByRole('textbox',{name:'平台核对人',exact:true}).fill('Synthetic UI owner');await panel.getByRole('textbox',{name:'平台核对依据',exact:true}).fill('synthetic:platform-checked');await panel.getByRole('textbox',{name:'逐项核对说明',exact:true}).fill('Synthetic owner checked original task, exact product, images, complete attributes, packaging and VAT');await panel.getByRole('checkbox',{name:/已在 Ozon 后台逐项核对该任务/}).check();await panel.getByRole('button',{name:'记录未知提交核对声明',exact:true}).click();await panel.getByText('负责人核对完成（本人声明）',{exact:true}).waitFor();
 }else await panel.getByText('导入任务已完成，审核与可售待核对',{exact:true}).waitFor();
 checks.push(unknown?'Unknown transport result persists after reload, never replays, and closes only after matched fresh import/product reads and an explicit owner declaration':'UI preflight freezes exact before/after, preserves existing simple attributes, requires named confirmation, submits once, and reads the original task without claiming sellable status');
 const r=(await invoke('commerce_listing_release_get',target)).request;
 const exported=JSON.parse((await invoke('commerce_listing_release_export',{request_id:r.id,expected_event_sha256:r.event_sha256})).content);assert.equal(exported.application_submission,unknown?'operator_attested_after_unknown_dispatch':'platform_task_received');assert.equal(exported.request.platform_submission_verified,false);
 for(const width of [1440,390])for(const theme of ['light','dark']){
  await page.setViewportSize({width,height:960});await page.locator('#react-theme').selectOption(theme);await page.waitForFunction(()=>!document.querySelector('#react-theme')?.disabled);await panel.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,`submission-${width}-${theme}.png`),animations:'disabled'});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 }
 checks.push('Frozen submission review and truthful export fit light/dark 1440/390; source evidence and request SHA remain visible');
 await page.reload();await panel.waitFor();assert.equal((await (await fetch(origin+'/qa-submission')).json()).writes,1);
 const legacy=async route=>{const call=route.request().postDataJSON();if(['commerce_listing_get','commerce_listing_release_get'].includes(call?.tool)){const response=await route.fetch(),body=await response.json();delete body.submission_available;delete body.submission_supported;await route.fulfill({response,json:body});}else await route.fallback();};
 await page.route('**/v1/invoke',legacy);await page.reload();await release.getByText('Synthetic exact publication request',{exact:true}).waitFor();assert.equal(await panel.count(),0);await page.unrouteAll({behavior:'wait'});checks.push('Older services hide the new submission controls; browsing and reload never submit a second body');await page.setViewportSize({width:1440,height:960});
}
