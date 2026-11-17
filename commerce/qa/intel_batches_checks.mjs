import assert from 'node:assert/strict';
import path from 'node:path';
export async function intelBatchesChecks({page,output,invoke,checks}){
  const f=page.frameLocator('iframe[title="专业业务模块"]');
  const before=(await invoke('commerce_task_list')).tasks.length;
  if(await f.locator('[data-intel-action="clear"]').count())await f.locator('[data-intel-action="clear"]').click();
  await f.locator('#intel-search button[type="submit"]:not(:disabled)').waitFor();
  if(!await f.locator('#intel-source').isVisible())await f.locator('[data-intel-action="filters"]').click();
  await f.locator('#intel-source').selectOption('fed');
  await f.locator('#intel-search button[type="submit"]:not(:disabled)').waitFor();
  if(!await f.locator('[data-intel-action="article-plan"]').isVisible())await f.locator('#intel-aux-menu>summary').click();
  await f.locator('[data-intel-action="article-plan"]').click();
  const dialog=f.getByRole('dialog');await dialog.getByText('补齐当前范围正文',{exact:true}).waitFor();
  assert.match(await dialog.innerText(),/本次按来源均衡选择 1 条/);
  assert.equal((await invoke('commerce_intel_article_batch_list')).batches.length,0);
  await dialog.getByRole('button',{name:'开始本次采集',exact:true}).click();
  const progress=f.getByRole('region',{name:'正文采集进度'});
  await progress.getByText(/当前可用 1/).waitFor({timeout:10000});
  const job=(await invoke('commerce_intel_article_batch_list')).batches[0];assert.equal(job.status,'completed');
  assert.equal(job.translation_started,false);assert.equal(job.counts.current_ready,1);
  await f.locator('#intel-query').fill('batch customs');await f.locator('#intel-search button[type="submit"]').click();
  await f.locator('#intel-search button[type="submit"]:not(:disabled)').waitFor();assert.equal(await f.locator('.intel-timeline li').count(),1);
  assert.match(await f.locator('.intel-search-match').innerText(),/原文正文命中/);
  for(const width of [1440,390])for(const theme of ['light','dark']){
    await page.setViewportSize({width,height:960});await page.locator('#react-theme').selectOption(theme);
    await page.waitForFunction(()=>!document.querySelector('#react-theme')?.disabled);
    await page.screenshot({path:path.join(output,`body-batch-${width}-${theme}.png`),animations:'disabled'});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.ok(await f.locator('html').evaluate(n=>n.scrollWidth<=innerWidth+1));
  }
  await page.reload();await f.locator('.intel-batch-status').waitFor();assert.match(await f.locator('.intel-batch-status').innerText(),/当前可用 1/);
  assert.equal((await invoke('commerce_intel_article_batch_list')).batches[0].id,job.id);
  assert.equal((await invoke('commerce_task_list')).tasks.length,before);
  checks.push('Body preview is read-only; one explicit batch persists original captures, exposes progress, becomes searchable and survives reload without replay or translation');
}
