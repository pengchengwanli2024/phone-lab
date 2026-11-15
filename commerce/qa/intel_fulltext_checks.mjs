// Real authenticated HTTP + opaque iframe: synthetic bodies, no upstream calls.
import assert from 'node:assert/strict';
import path from 'node:path';

export async function intelFulltextChecks({page, output, invoke, checks}) {
  const frame = page.frameLocator('iframe[title="专业业务模块"]');
  const before = (await invoke('commerce_task_list')).tasks.length;
  await frame.locator('[data-intel-action="list-view"]').click();
  if (await frame.locator('[data-intel-action="clear"]').count()) await frame.locator('[data-intel-action="clear"]').click();
  async function search(query) {
    await frame.locator('#intel-query').fill(query);
    await frame.locator('#intel-search button[type="submit"]').click();
    await frame.locator('#intel-search button[type="submit"]:not(:disabled)').waitFor();
  }
  await search('article body');
  assert.equal(await frame.locator('.intel-timeline li').count(), 1);
  assert.match(await frame.locator('.intel-search-match').innerText(), /原文正文命中/);
  assert.equal(await frame.locator('.intel-timeline script').count(), 0);
  await search('合成文章');
  assert.equal(await frame.locator('.intel-timeline li').count(), 1);
  assert.match(await frame.locator('.intel-search-match').innerText(), /中文译文命中.*待核对/s);
  const found = (await invoke('commerce_intel_search', {query:'合成文章'})).items[0];
  assert.equal(found.search_match.evidence[0].independently_verified, false);
  for (const width of [1440,390]) for (const theme of ['light','dark']) {
    await page.setViewportSize({width,height:960});
    await page.locator('#react-theme').selectOption(theme);
    await page.waitForFunction(()=>!document.querySelector('#react-theme')?.disabled);
    await frame.locator('.intel-search-match').waitFor();
    await page.screenshot({path:path.join(output,`intel-fulltext-${width}-${theme}.png`),animations:'disabled'});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.ok(await frame.locator('html').evaluate(node=>node.scrollWidth<=innerWidth+1));
  }
  await frame.locator('.intel-timeline [data-intel-id]').click();
  await frame.locator('.intel-search-evidence').waitFor();
  await frame.locator('.intel-search-evidence summary').click();
  assert.match(await frame.locator('.intel-search-evidence').innerText(), /尚未独立核实/);
  assert.ok((await frame.locator('.intel-search-evidence').innerText()).includes(found.search_match.evidence[0].text_sha256));
  await page.screenshot({path:path.join(output,'intel-fulltext-evidence-390-dark.png'),animations:'disabled'});
  await frame.locator('[data-intel-action="reader-back"]').click();
  assert.equal(await frame.locator('#intel-query').inputValue(), '合成文章');
  assert.equal(await frame.locator('.intel-timeline li').count(), 1);
  assert.equal((await invoke('commerce_task_list')).tasks.length, before);
  checks.push('Fulltext original/Chinese hits expose escaped version-bound excerpts; 1440/390 light/dark and reader return preserve the query without creating tasks');
}
