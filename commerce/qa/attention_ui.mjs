// Render the real shared artifact with synthetic state and no inference workers.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath, pathToFileURL } from 'node:url';

assert.ok(process.env.PLAYWRIGHT_MODULE && process.env.COMMERCE_PYTHON && process.env.QA_OUTPUT_DIR);
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const work = await mkdtemp(path.join(tmpdir(), 'commerce-attention-'));
const state = path.join(work, 'state'); await mkdir(state);
const output = process.env.QA_OUTPUT_DIR; await mkdir(output, { recursive: true });
const listener = net.createServer(); await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
const port = listener.address().port; await new Promise(resolve => listener.close(resolve));
const origin = 'http://127.0.0.1:' + port;
const server = spawn(process.env.COMMERCE_PYTHON, [path.join(root, 'qa/fixture_attention.py')], {
  env: { ...process.env, COMMERCE_STATE: state, COMMERCE_PORT: String(port) }, stdio: ['ignore', 'ignore', 'pipe'],
});
let stderr = ''; server.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-4000); });
const ended = new Promise(resolve => server.once('close', resolve));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const calls = [], errors = [], checks = [];
let browser, page;
const invoke = async (tool, args = {}) => {
  const response = await fetch(origin + '/v1/invoke', { method: 'POST', headers: {
    authorization: 'Bearer synthetic-attention-browser-only', 'content-type': 'application/json',
  }, body: JSON.stringify({ tool, arguments: args, client: 'test' }) });
  assert.equal(response.status, 200); return response.json();
};
try {
  let ready = false;
  for (let index = 0; index < 100; index++) {
    if (server.exitCode !== null) break;
    try { await invoke('commerce_attention_list'); ready = true; break; } catch {}
    await pause(100);
  }
  assert.ok(ready, 'fixture startup: ' + stderr);
  const fixture = JSON.parse(await readFile(path.join(state, 'fixture.json'), 'utf8'));
  const before = await invoke('commerce_task_list');
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, extraHTTPHeaders: { authorization: 'Bearer synthetic-attention-browser-only' } });
  await context.route('**/*', route => route.request().url().startsWith(origin) || route.request().url().startsWith('about:') ? route.continue() : route.abort());
  page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().endsWith('/v1/invoke')) { try { calls.push(request.postDataJSON().tool); } catch {} }
  });
  await page.goto(origin + '/workspace');
  const notices = page.locator('.r-overview-grid').getByRole('region').first();
  await page.getByRole('button', { name: '加载更多模型与研究事项' }).waitFor();
  assert.equal(await page.getByText('DEMO_ONLY_ATTENTION').count(), 0);
  const count = await page.locator('.r-notice').count();
  await page.getByRole('button', { name: '加载更多模型与研究事项' }).click();
  await page.waitForFunction(previous => document.querySelectorAll('.r-notice').length > previous, count);
  checks.push('unresolved pagination and real/demo separation');

  await page.locator('.r-notice').filter({ hasText: '合成待补充：请明确本轮预算' }).click();
  await page.locator('#copilot-message').waitFor();
  assert.ok(calls.includes('commerce_attention_get'));
  assert.equal(calls.includes('commerce_copilot_send'), false);
  checks.push('revalidated opening of the original conversation without inference');

  await page.locator('.r-notice').filter({ hasText: '执行结果尚未确认，不会自动重发。' }).click();
  const legacy = page.frameLocator('iframe[title="专业业务模块"]');
  await legacy.locator('.agent-answer').getByText('合成事项 3', { exact: false }).waitFor();
  assert.equal(calls.includes('commerce_agent_start'), false);
  checks.push('exact standalone result opens through the nonce-bound legacy bridge');

  await page.goto(origin + '/workspace');
  await page.locator('.r-notice').filter({ hasText: '请调研俄罗斯厨房收纳用品并保存候选' }).click();
  await page.getByRole('dialog', { name: '市场研究' }).waitFor();
  assert.equal(calls.includes('commerce_market_research_resume'), false);
  checks.push('research attention opens the original task without replay');

  for (const [width, appearance] of [[1440, 'light'], [390, 'light'], [1440, 'dark'], [390, 'dark']]) {
    await page.setViewportSize({ width, height: 1000 }); await page.emulateMedia({ colorScheme: appearance });
    await page.goto(origin + '/workspace');
    await page.getByRole('button', { name: '加载更多模型与研究事项' }).waitFor();
    await page.locator('.r-notice').first().waitFor();
    if (width < 768) {
      const pageButton = page.getByRole('button', { name: '工作页面', exact: true });
      if (await pageButton.count()) await pageButton.click();
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    assert.equal(overflow, false, `${width}/${appearance} horizontal overflow`);
    await page.screenshot({ path: path.join(output, `attention-${width}-${appearance}.png`), fullPage: true });
  }
  checks.push('1440px and 390px in light and dark appearances without horizontal overflow');

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(origin + '/workspace');
  await page.getByRole('button', { name: '加载更多模型与研究事项' }).click();
  let releaseRead, markHeld;
  const gate = new Promise(resolve => { releaseRead = resolve; });
  const held = new Promise(resolve => { markHeld = resolve; });
  let blockNext = true;
  await page.route('**/v1/invoke', async route => {
    const request = route.request().postDataJSON();
    if (blockNext && request.tool === 'commerce_copilot_get' && request.arguments?.thread_id === fixture.thread_id) {
      blockNext = false; markHeld(); await gate;
    }
    await route.continue();
  });
  await page.locator('.r-notice').filter({ hasText: '合成待补充：请明确本轮预算' }).click();
  await held;
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await page.getByRole('switch', { name: '示例数据' }).check();
  await page.getByRole('button', { name: '切换数据范围', exact: true }).click();
  const settled = page.waitForResponse(response => {
    if (!response.url().endsWith('/v1/invoke')) return false;
    const request = response.request().postDataJSON();
    return request.tool === 'commerce_copilot_get' && request.arguments?.thread_id === fixture.thread_id;
  });
  releaseRead(); await settled; await pause(250);
  assert.equal(await page.getByText('合成待补充：请明确本轮预算', { exact: true }).count(), 0, 'a delayed original-thread read crossed the data-mode boundary');
  checks.push('mode changes invalidate delayed original-thread navigation');

  await page.setViewportSize({ width: 1440, height: 1000 });
  await writeFile(path.join(state, 'fail-attention'), 'synthetic failure');
  await page.getByRole('button', { name: '刷新', exact: true }).first().click();
  await page.getByRole('alert').filter({ hasText: '事项来源暂未完整读到' }).waitFor();
  assert.equal(await page.locator('.r-notice').filter({ hasText: '合成待补充' }).count(), 0);
  checks.push('failed refresh clears stale model notices and reports an incomplete read');

  const after = await invoke('commerce_task_list');
  assert.equal(after.tasks.length, before.tasks.length);
  assert.deepEqual(errors, []);
  assert.ok(calls.every(name => !['commerce_agent_apply', 'commerce_copilot_apply', 'commerce_task_execute', 'commerce_task_retry', 'commerce_market_research_resume', 'commerce_agent_start', 'commerce_copilot_send'].includes(name)));
  await writeFile(path.join(output, 'result.json'), JSON.stringify({ checks, errors, business_tasks_unchanged: true, model_or_execution_submissions: false }, null, 2));
  console.log(JSON.stringify({ passed: checks.length, errors: errors.length }));
} catch (error) {
  await writeFile(path.join(output, 'failure.json'), JSON.stringify({ error: String(error), calls, errors,
    frames: page ? await Promise.all(page.frames().map(async frame => ({ url: frame.url(), text: (await frame.locator('body').innerText().catch(() => '')).slice(-9000) }))) : [] }, null, 2));
  await page?.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
  throw error;
} finally {
  await browser?.close();
  if (server.exitCode === null) server.kill('SIGTERM');
  await ended;
}
