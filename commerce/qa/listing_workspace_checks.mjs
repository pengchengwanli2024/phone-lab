import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

export async function listingWorkspaceChecks({page,origin,caseId,output,invoke,checks}) {
  async function find(text){await page.locator('.r-search').click();const d=page.getByRole('dialog');await d.getByRole('searchbox').fill(text);await d.locator('.r-finder-list button').first().click();}
  await page.goto(origin+`/workspace?host=harness&tab=workspace&case_id=${caseId}&demo=true`);
  const product=page.frameLocator('iframe[title="完整商品内容编辑"]');
  await product.getByRole('button',{name:'上架准备',exact:true}).click();
  const listing=page.locator('.r-listing-page');await listing.getByRole('textbox',{name:'商品标题',exact:true}).waitFor();
  await listing.getByRole('textbox',{name:'目标店铺标识'}).fill('synthetic-listing-store');
  await listing.getByRole('button',{name:'读取店铺方案',exact:true}).click();
  await listing.getByRole('textbox',{name:'商品标题',exact:true}).fill('Synthetic listing version');
  await listing.getByRole('spinbutton',{name:'计划上架数量'}).fill('0');
  await listing.getByRole('textbox',{name:'目标语言'}).fill('ru');
  await listing.getByRole('button',{name:'保存店铺方案',exact:true}).click();
  await listing.getByText('店铺上架方案已保存，尚未提交平台。',{exact:true}).waitFor();
  const target={case_id:caseId,platform:'ozon',store_ref:'synthetic-listing-store',market:'RU'};
  let saved=await invoke('commerce_listing_get',target);assert.equal(saved.revision,1);assert.equal(saved.payload.fields.quantity,0);
  assert.equal((await invoke('commerce_listing_get',{...target,platform:'amazon'})).revision,0);
  await listing.getByRole('textbox',{name:'商品标题',exact:true}).fill('Synthetic unsaved listing');
  await find('日常运营');const desk=page.locator('.r-store-workbench');await desk.getByRole('heading',{name:'商品与上架',exact:true}).waitFor();
  await desk.getByText('未启用 · 当前服务仅接受本机访问',{exact:true}).waitFor();
  assert.equal(await desk.getByRole('button',{name:'上架准备',exact:true}).count(),1);
  await find('上架准备');assert.equal(await listing.getByRole('textbox',{name:'商品标题',exact:true}).inputValue(),'Synthetic unsaved listing');
  await listing.getByText('选择商品与目标店铺',{exact:true}).click();
  await listing.getByRole('textbox',{name:'目标店铺标识'}).fill('another-store');
  await listing.getByRole('button',{name:'读取店铺方案',exact:true}).click();
  await listing.getByRole('button',{name:'保留当前编辑',exact:true}).click();
  assert.equal(await listing.getByRole('textbox',{name:'目标店铺标识'}).inputValue(),target.store_ref);
  assert.equal(await listing.getByRole('textbox',{name:'商品标题',exact:true}).inputValue(),'Synthetic unsaved listing');
  await invoke('commerce_listing_save',{...target,payload:{...saved.payload,fields:{...saved.payload.fields,title:'Synthetic concurrent version'}},expected_revision:saved.revision,expected_source_sha256:saved.source_sha256});
  await listing.getByRole('button',{name:'保存店铺方案',exact:true}).click();
  await listing.getByRole('alert').waitFor();
  assert.equal(await listing.getByRole('textbox',{name:'商品标题',exact:true}).inputValue(),'Synthetic unsaved listing');
  await listing.getByRole('button',{name:'核对保存版本',exact:true}).click();
  await listing.getByRole('checkbox',{name:'已核对当前商品资料与保存版本'}).check();
  await listing.getByRole('button',{name:'保留本地修改后重新保存',exact:true}).click();
  await listing.getByRole('button',{name:'保存店铺方案',exact:true}).click();
  await listing.getByText('店铺上架方案已保存，尚未提交平台。',{exact:true}).waitFor();
  saved=await invoke('commerce_listing_get',target);assert.equal(saved.revision,3);assert.equal(saved.payload.fields.title,'Synthetic unsaved listing');
  const downloadPromise=page.waitForEvent('download');await listing.getByRole('button',{name:'导出准备包',exact:true}).click();
  const download=await downloadPromise,body=JSON.parse(await readFile(await download.path(),'utf8'));
  assert.equal(body.platform_submission,'not_performed');assert.ok(body.preflight.missing.includes('platform_adapter'));
  for(const width of [1440,390])for(const theme of ['light','dark']){
    await page.setViewportSize({width,height:960});await page.evaluate(t=>window.CommerceUI.applyTheme(t),theme);
    await page.screenshot({path:path.join(output,`listing-diagnostic-${width}-${theme}.png`)});
    assert.ok(await listing.evaluate(el=>el.scrollWidth<=el.clientWidth+1),JSON.stringify(await listing.evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth,overflow:[...el.querySelectorAll('*')].filter(x=>x.getBoundingClientRect().right>el.getBoundingClientRect().right+1).slice(0,12).map(x=>({tag:x.tagName,cls:x.className,right:x.getBoundingClientRect().right,width:x.getBoundingClientRect().width}))}))));
    await page.screenshot({path:path.join(output,`listing-${width}-${theme}.png`),animations:'disabled'});
    await find('日常运营');await desk.getByRole('heading',{name:'手机与通知',exact:true}).waitFor();
    assert.ok(await desk.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    await page.screenshot({path:path.join(output,`store-ops-${width}-${theme}.png`),animations:'disabled'});
    await find('上架准备');
  }
  await page.setViewportSize({width:1440,height:960});
  checks.push('Per-store listing preparation, conflict recovery, private export and original product navigation over the real iframe bridge');
  await find('operations');
  await page.locator('.r-cost-page input[name="price"]').waitFor();
  const html=await page.locator('iframe[title="完整商品内容编辑"]').getAttribute('srcdoc');
  const nonce=html.match(/const nonce\s*=\s*["']([^"']+)["']/)?.[1];
  assert.ok(nonce,'Expected the real product frame nonce');
  await product.locator('body').evaluate((_node,nonce)=>parent.postMessage({type:'commerce:workspace-navigate',nonce,tab:'workspace'},'*'),nonce);
  await page.waitForTimeout(100);
  assert.ok(await page.locator('.r-cost-page input[name="price"]').isVisible(),'Late navigation from an inactive product frame must not replace the current page');
  checks.push('Daily operations and mobile layout retain original alerts, pending work and honest remote/channel readiness');
  await page.goto(origin+`/workspace?host=harness&tab=workspace&case_id=${caseId}&demo=true`);
}
