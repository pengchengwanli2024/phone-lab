import assert from 'node:assert/strict';
import path from 'node:path';
export async function listingReviewChecks({page,origin,caseId,output,invoke,checks}){
  async function find(text){await page.locator('.r-search').click();const d=page.getByRole('dialog');await d.getByRole('searchbox').fill(text);await d.locator('.r-finder-list button').first().click();}
  const target={case_id:caseId,platform:'ozon',store_ref:'synthetic-listing-store',market:'RU'};
  const before=(await invoke('commerce_task_list')).tasks.length;
  await find('日常运营');
  const directory=page.getByRole('heading',{name:'已保存上架方案',exact:true}).locator('..').locator('..');
  await directory.getByRole('button',{name:'继续此店铺方案',exact:true}).click();
  const listing=page.locator('.r-listing-page');
  await listing.getByRole('textbox',{name:'核对说明',exact:true}).fill('Synthetic review draft retained across modules');
  await find('日常运营');await directory.getByRole('button',{name:'继续此店铺方案',exact:true}).click();
  assert.equal(await listing.getByRole('textbox',{name:'核对说明',exact:true}).inputValue(),'Synthetic review draft retained across modules');
  await listing.getByRole('checkbox',{name:'确认记录当前版本的本地核对结果'}).check();
  await listing.getByRole('button',{name:'保存核对记录',exact:true}).click();
  await listing.getByRole('region',{name:'已保存的上架核对'}).waitFor();
  const first=await invoke('commerce_listing_reconcile',target);assert.equal(first.review.decision,'needs_changes');assert.equal(first.review.current,true);assert.equal(first.platform_submission_verified,false);
  await listing.getByRole('button',{name:'处理检查：目标语言与履约方案',exact:true}).click();
  await page.waitForFunction(()=>document.activeElement?.id==='listing-language');
  assert.equal(await page.evaluate(()=>document.activeElement?.id),'listing-language');
  await listing.getByRole('textbox',{name:'核对说明',exact:true}).fill('Synthetic conflict draft');
  await invoke('commerce_listing_review',{...target,expected_comparison_sha256:first.comparison_sha256,expected_review_sha256:first.review.sha256,decision:'needs_changes',note:'Synthetic concurrent local review',confirmed:true,idempotency_key:'synthetic-concurrent-listing-review'});
  await listing.getByRole('checkbox',{name:'确认记录当前版本的本地核对结果'}).check();await listing.getByRole('button',{name:'保存核对记录',exact:true}).click();
  await listing.getByRole('alert').filter({hasText:'已有新的核对记录'}).waitFor();
  assert.equal(await listing.getByRole('textbox',{name:'核对说明',exact:true}).inputValue(),'Synthetic conflict draft');
  await listing.getByRole('button',{name:'刷新核对',exact:true}).click();
  await listing.locator('button:not(:disabled)').filter({hasText:'刷新核对'}).waitFor();
  await listing.getByRole('checkbox',{name:'确认记录当前版本的本地核对结果'}).check();await listing.getByRole('button',{name:'保存核对记录',exact:true}).click();
  await listing.getByText('Synthetic conflict draft',{exact:true}).first().waitFor();
  const saved=await invoke('commerce_listing_get',target),second={...target,store_ref:'synthetic-second-store'};
  const blank=await invoke('commerce_listing_get',second);await invoke('commerce_listing_save',{...second,payload:saved.payload,expected_revision:blank.revision,expected_source_sha256:blank.source_sha256});
  await find('日常运营');await directory.locator('li').filter({hasText:'synthetic-second-store'}).getByRole('button',{name:'继续此店铺方案',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#listing-store-ref')?.value==='synthetic-second-store');
  assert.equal(await listing.locator('#listing-store-ref').inputValue(),second.store_ref);
  await page.reload();await listing.getByRole('textbox',{name:'商品标题',exact:true}).waitFor();
  assert.equal(await listing.locator('#listing-store-ref').inputValue(),second.store_ref,'reload must preserve exact saved target');
  for(const width of [1440,390])for(const theme of ['light','dark']){
    await page.setViewportSize({width,height:960});await page.locator('#react-theme').selectOption(theme);await page.waitForFunction(()=>!document.querySelector('#react-theme')?.disabled);
    await page.screenshot({path:path.join(output,`listing-review-${width}-${theme}.png`),animations:'disabled'});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  }
  assert.equal((await invoke('commerce_task_list')).tasks.length,before);
  checks.push('Saved listing directory returns the exact store/market through reload; local review CAS and draft retention, missing-field focus and original pending gates remain intact');
  await page.setViewportSize({width:1440,height:960});
  await page.goto(origin+`/workspace?host=harness&tab=workspace&case_id=${caseId}&demo=true`);
}
