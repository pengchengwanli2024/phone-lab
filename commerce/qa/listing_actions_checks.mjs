import assert from 'node:assert/strict';
import path from 'node:path';

export async function listingActionsChecks({page,origin,output,invoke,checks}){
  const previous=page.url(),id='a819'.repeat(8),taskCount=(await invoke('commerce_task_list')).tasks.length;
  await page.goto(origin+'/workspace?host=harness&tab=listing&demo=false&case_id='+id+'&listing_platform=ozon&listing_store=ozon-live&listing_market=RU');
  const panel=page.locator('#listing-image-actions');await panel.getByRole('heading',{name:'现有商品图片变更',exact:true}).waitFor();
  await panel.getByRole('button',{name:'读取平台当前图库',exact:true}).click();
  await panel.getByText(/原图库 1 张/).waitFor();
  const input=panel.getByLabel('新图库HTTPS直链，每行一张',{exact:true}),urls='https://example.com/new-main.jpg\nhttps://example.com/new-detail.jpg';
  await input.fill(urls);
  await page.getByRole('button',{name:'运营台',exact:true}).first().click();
  await page.getByRole('button',{name:'商品',exact:true}).first().click();
  await page.frameLocator('iframe[title="完整商品内容编辑"]').getByRole('button',{name:'上架准备',exact:true}).click();
  assert.equal(await input.inputValue(),urls);
  assert.equal(new URL(page.url()).searchParams.get('listing_store'),'ozon-live');
  await panel.getByRole('button',{name:'固定图片变更版本',exact:true}).click();
  await panel.getByText('待核对图片',{exact:true}).waitFor();
  assert.equal(await panel.getByRole('button',{name:'执行一次图片更新',exact:true}).count(),0);
  await panel.getByRole('button',{name:'保存核对草稿',exact:true}).click();
  let view=await invoke('commerce_listing_action_get',{case_id:id});assert.equal(view.items[0].state.status,'draft');assert.equal(view.items[0].state.dispatch_started,false);
  await panel.getByLabel('核对方式',{exact:true}).selectOption('owner_manual');
  await panel.getByLabel('核对人声明',{exact:true}).fill('Synthetic operator');
  for(const [key,label]of Object.entries(view.requirements)){
    await panel.getByLabel(label+'结论',{exact:true}).selectOption('confirmed');
    await panel.getByLabel(label+'依据',{exact:true}).fill('synthetic-evidence:'+key);
  }
  await panel.getByRole('checkbox',{name:'确认本次人工核对声明；批准仅限上述图片数组',exact:true}).check();
  await panel.getByRole('button',{name:'批准本次图片版本',exact:true}).click();
  await panel.getByText('本次人工图片核对已记录',{exact:true}).waitFor();
  const execute=panel.getByRole('button',{name:'执行一次图片更新',exact:true});assert.equal(await execute.isDisabled(),true);
  let failOnce=true;
  const failRead=async route=>{const body=route.request().postData();if(failOnce&&body&&JSON.parse(body).tool==='commerce_listing_action_get'){failOnce=false;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'commerce_service_unavailable'})});}return route.fallback();};
  await page.route('**/v1/invoke',failRead);
  await panel.getByRole('button',{name:'读取当前记录',exact:true}).click();
  await panel.getByText('原来源或连接已变化，不能提交此旧动作。',{exact:true}).waitFor();
  assert.equal(await execute.isDisabled(),true);
  await panel.getByRole('button',{name:'读取当前记录',exact:true}).click();
  await panel.getByText('原来源或连接已变化，不能提交此旧动作。',{exact:true}).waitFor({state:'detached'});
  await page.unroute('**/v1/invoke',failRead);
  checks.push('A failed current-state read preserves old evidence and inputs but revokes positive execution readiness; an explicit successful re-read restores it without a write');
  await panel.getByRole('checkbox',{name:'我明确授权将此商品图库替换为上述完整数组',exact:true}).check();
  await execute.click();await panel.getByText('接口已返回，等待实际图库回读',{exact:true}).waitFor();
  view=await invoke('commerce_listing_action_get',{case_id:id});assert.equal(view.items[0].state.dispatch_started,true);
  await page.reload();await panel.getByText('接口已返回，等待实际图库回读',{exact:true}).waitFor();
  assert.equal(await panel.getByRole('button',{name:'执行一次图片更新',exact:true}).count(),0);
  checks.push('Existing-gallery image plan retains unsaved URLs across module navigation; incomplete review cannot execute, exact owner review and a separate execution confirmation precede a single mock write, and reloading never replays it');
  await panel.getByRole('button',{name:'只读核对平台图片结果',exact:true}).click();await panel.getByText('结果未确认，请先回读',{exact:true}).waitFor();
  view=await invoke('commerce_listing_action_get',{case_id:id});const recoveryId=view.items[0].id;
  for(let i=0;i<11;i++)await invoke('commerce_listing_action_prepare',{case_id:id,expected_source_sha256:view.source_sha256,expected_gallery_sha256:view.gallery.sha256,image_urls:['https://example.com/history-only-'+i+'.jpg'],idempotency_key:'synthetic-recovery-history-'+i});
  assert.equal((await invoke('commerce_listing_action_get',{case_id:id})).items.some(a=>a.id===recoveryId),false);
  await page.getByRole('button',{name:'店铺管理',exact:true}).first().click();
  await page.getByRole('button',{name:'日常运营',exact:true}).click();
  await page.getByRole('heading',{name:'图片动作',exact:true}).waitFor();
  const directoryRegion=page.getByRole('region',{name:'图片动作恢复',exact:true});
  let failDirectory=true;const failDirectoryRead=async route=>{const body=route.request().postData();if(failDirectory&&body&&JSON.parse(body).tool==='commerce_listing_action_directory'){failDirectory=false;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'commerce_service_unavailable'})});}return route.fallback();};
  await page.route('**/v1/invoke',failDirectoryRead);await directoryRegion.getByRole('button',{name:'刷新图片动作',exact:true}).click();await directoryRegion.getByText('图片动作未完整读回，请刷新重试。',{exact:true}).waitFor();assert.equal(await directoryRegion.getByText('当前店铺尚无图片动作。',{exact:true}).count(),0);await directoryRegion.getByRole('button',{name:'刷新图片动作',exact:true}).click();await directoryRegion.getByRole('button',{name:'下一页图片动作',exact:true}).waitFor();await page.unroute('**/v1/invoke',failDirectoryRead);
  const recovery=page.locator('[data-image-action="'+recoveryId+'"]');
  await page.getByRole('button',{name:'下一页图片动作',exact:true}).click();await page.getByText('6–10 / 12',{exact:true}).waitFor();
  await page.getByRole('button',{name:'下一页图片动作',exact:true}).click();await page.getByText('11–12 / 12',{exact:true}).waitFor();
  await recovery.getByText('结果未确认，请先回读',{exact:true}).waitFor();
  for(const [width,height,theme]of [[1440,1000,'light'],[390,900,'dark']]){await page.setViewportSize({width,height});await page.getByLabel('界面主题',{exact:true}).selectOption(theme);await page.getByRole('region',{name:'图片动作恢复',exact:true}).scrollIntoViewIfNeeded();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));await page.screenshot({path:path.join(output,`listing-actions-directory-${theme}-${width}.png`)});}
  await page.setViewportSize({width:1440,height:1000});
  await recovery.getByRole('button',{name:'继续准确图片动作',exact:true}).click();
  await panel.getByText('结果未确认，请先回读',{exact:true}).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('image_action_id'),recoveryId);
  await page.reload();await panel.getByText('结果未确认，请先回读',{exact:true}).waitFor();
  assert.equal(await panel.getByRole('button',{name:'执行一次图片更新',exact:true}).count(),0);
  checks.push('Daily operations recovers an exact unknown image action older than the ten latest records; route and reload retain the original action without replaying a write');
  await panel.getByRole('button',{name:'查看平台回读图片',exact:true}).click();await panel.getByRole('img',{name:'平台回读图片 1',exact:true}).waitFor();
  assert.equal(await panel.getByRole('img').count(),2);
  await panel.getByLabel('逐图核对说明',{exact:true}).fill('Synthetic transformed URLs; owner compared both images and their order.');
  await panel.getByRole('checkbox',{name:'我已逐张核对平台当前图片与顺序，确认与本次图片方案一致',exact:true}).check();
  await panel.getByRole('button',{name:'记录人工逐图完成',exact:true}).click();await panel.getByText('已记录人工逐图核对完成',{exact:true}).waitFor();
  view=await invoke('commerce_listing_action_get',{case_id:id,action_id:recoveryId});const recovered=view.items.find(a=>a.id===recoveryId);assert.equal(recovered.state.status,'owner_confirmed');assert.equal(recovered.state.observation.exact_images,false);
  const workspace=await invoke('commerce_workspace_get',{case_id:id});assert.equal(workspace.stages.find(s=>s.id==='S6').status,'BLOCKED');
  for(const [width,height,theme]of [[1440,1000,'light'],[390,900,'dark']]){
    await page.setViewportSize({width,height});await page.getByLabel('界面主题',{exact:true}).selectOption(theme);
    await page.getByRole('button',{name:'图片变更',exact:true}).click();
    if(width===1440)assert.ok(await panel.evaluate(e=>e.getBoundingClientRect().width)>800);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
    await page.screenshot({path:path.join(output,`listing-actions-${theme}-${width}.png`)});
  }
  assert.equal((await invoke('commerce_task_list')).tasks.length,taskCount);
  checks.push('Platform-rewritten image URLs retain uncertainty; actual decoded preview files and explicit visual attestation close only the image action, while original S6 and whole-listing gates stay blocked at 1440/390 light/dark');
  const invalidRoute=new URL(page.url());invalidRoute.searchParams.set('image_action_id','invalid-id');await page.goto(invalidRoute.href);await panel.getByText('未找到指定图片动作，请从日常运营重新选择准确记录。',{exact:true}).waitFor();assert.equal(await panel.getByRole('button',{name:'执行一次图片更新',exact:true}).count(),0);assert.equal(await panel.getByText('待核对图片',{exact:true}).count(),0);
  checks.push('Failed action-directory reads remain incomplete and retryable; an invalid historical action reference reports an error without substituting the newest action');
  await page.setViewportSize({width:1440,height:960});await page.goto(previous);
}
