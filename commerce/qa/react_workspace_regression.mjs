// Real shared React/iframe workflow against an isolated, synthetic HTTP service.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile, access } from 'node:fs/promises';
import { tmpdir, homedir } from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath, pathToFileURL } from 'node:url';

const commerce = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const output = path.resolve(process.env.QA_OUTPUT_DIR || path.join(commerce, '../.commerce-state/verification/react-regression'));
await mkdir(output, { recursive: true });
const manifestPath = path.join(commerce, 'web/workbench.sources.json');
const manifestHash = () => readFile(manifestPath).then(body => createHash('sha256').update(body).digest('hex'));
const candidate = await manifestHash();
if (process.env.QA_EXPECTED_MANIFEST) assert.equal(candidate, process.env.QA_EXPECTED_MANIFEST, 'Candidate changed before regression');
let playwright;
try { playwright = await import(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch {
  const cache = path.join(homedir(), '.npm/_npx');
  for (const entry of await readdir(cache).catch(() => [])) {
    try { playwright = await import(pathToFileURL(path.join(cache, entry, 'node_modules/playwright/index.mjs')).href); break; } catch {}
  }
}
assert.ok(playwright, 'Use the existing Playwright installation or set PLAYWRIGHT_MODULE; this test never installs dependencies.');
const work = await mkdtemp(path.join(tmpdir(), 'commerce-react-regression-'));
const state = path.join(work, 'state'); await mkdir(state);
const listener = net.createServer();
await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
const port = listener.address().port;
await new Promise(resolve => listener.close(resolve));
const origin = `http://127.0.0.1:${port}`;
const server = spawn(process.env.COMMERCE_PYTHON || 'python3', [path.join(commerce, 'qa/react_workbench_fixture.py')], {
  env: { ...process.env, COMMERCE_STATE: state, COMMERCE_PORT: String(port) }, stdio: ['ignore', 'ignore', 'pipe'],
});
let serverLog = '';
server.stderr.on('data', chunk => { serverLog = (serverLog + chunk.toString()).slice(-32768); });
const closed = new Promise(resolve => server.once('close', resolve));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const checks = [], errors = [], external = [], intelTraffic = [];
assert.ok(process.env.QA_INTEL_ONLY !== '1' || process.env.COMMERCE_QA_INTEL === '1', 'Intelligence-only mode needs its synthetic fixture');
let browser, page;
const invoke = async (tool, args = {}) => {
  const response = await fetch(origin + '/v1/invoke', {
    method: 'POST', headers: { authorization: 'Bearer synthetic-workbench-preview', 'content-type': 'application/json' },
    body: JSON.stringify({ tool, arguments: args, client: 'test' }),
  });
  assert.equal(response.status, 200, tool + ' failed'); return response.json();
};
const inventory = async () => ({
  tasks: (await invoke('commerce_task_list')).tasks.length,
  surfaces: (await invoke('commerce_a2ui_list')).surfaces.length,
  threads: (await invoke('commerce_copilot_list')).threads.length,
});
async function find(label) {
  await page.locator('.r-search').click();
  const dialog = page.getByRole('dialog'); await dialog.getByRole('searchbox').fill(label);
  await dialog.locator('.r-finder-list button').first().click();
}
try {
  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) break;
    try { const response = await fetch(origin + '/v1/health', { headers: { authorization: 'Bearer synthetic-workbench-preview' } }); if (response.ok) { ready = true; break; } } catch {}
    await pause(100);
  }
  assert.ok(ready, 'Isolated fixture did not start');
  const { case_id: caseId } = JSON.parse(await readFile(path.join(state, 'fixture.json'), 'utf8'));
  const original = await invoke('commerce_workspace_get', { case_id: caseId }), before = await inventory();
  let executablePath = process.env.CHROME_PATH;
  if (!executablePath) {
    const macChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
    try { await access(macChrome); executablePath = macChrome; } catch {}
  }
  browser = await playwright.chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await context.route('**/*', route => {
    const url = route.request().url();
    if (url.startsWith(origin + '/') || /^(data|blob|about):/.test(url)) return route.continue();
    external.push(new URL(url).origin); return route.abort();
  });
  page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { const body = request.postData(); if (body?.includes('commerce_intel_')) intelTraffic.push(JSON.parse(body)); });
  await page.goto(origin + '/login?token=synthetic-workbench-preview');
  await page.goto(origin + `/workspace?host=harness&tab=workspace&case_id=${caseId}&demo=true`);
  if (process.env.QA_INTEL_ONLY !== '1') {
  const product = page.frameLocator('iframe[title="完整商品内容编辑"]');
  await product.locator('#pw-main[aria-busy="false"]').waitFor();
  await product.locator('#copilot-message').fill('synthetic-unsent-product-draft');
  await product.locator('[data-pw-tab="cost"]').click();
  await product.locator('#pw-cost-purchase_cost').fill('34');
  const originalFrame = await page.locator('iframe[title="完整商品内容编辑"]').getAttribute('srcdoc');
  await page.getByRole('button', {name:'切换智能助手',exact:true}).click();
  await product.locator('#product-app[data-chat-visible="false"]').waitFor();
  await page.getByRole('button', {name:'切换智能助手',exact:true}).click();
  await product.locator('#product-app[data-chat-visible="true"]').waitFor();
  await page.getByRole('button', {name:'设置',exact:true}).click();
  const settings = page.getByRole('dialog');
  await settings.getByRole('switch', {name:'示例数据',exact:true}).uncheck();
  await settings.getByRole('button', {name:'取消切换',exact:true}).click();
  assert.equal(await settings.getByRole('switch', {name:'示例数据',exact:true}).isChecked(), true);
  await page.keyboard.press('Escape');
  await page.getByRole('button', {name:'用户',exact:true}).click();
  await page.getByRole('dialog').getByText('已连接 · v0.1.0', {exact:true}).waitFor();
  assert.match(await page.getByRole('dialog').innerText(), /独立账号\s+尚未接入/);
  await page.keyboard.press('Escape');
  assert.equal(await product.locator('#copilot-message').inputValue(), 'synthetic-unsent-product-draft');
  assert.equal(await product.locator('#pw-cost-purchase_cost').inputValue(), '34');
  assert.equal(await page.locator('iframe[title="完整商品内容编辑"]').getAttribute('srcdoc'), originalFrame);
  checks.push('Product assistant toggles, settings cancellation and local user status preserve the mounted frame and unsaved input');

  await find('operations');
  const cost = page.locator('.r-cost-page');
  await cost.locator('input[name="price"]').fill('129');
  assert.match(await cost.innerText(), /未关联商品/);
  assert.deepEqual(await inventory(), before, 'Opening general cost must not create tasks, surfaces or conversations');
  checks.push('General-cost initial load is read-only');

  await find('restock');
  const legacy = page.frameLocator('iframe[title="专业业务模块"]');
  await legacy.locator('#analysis-available').fill('77');
  assert.equal(await legacy.locator('#commerce-copilot,.workspace-assistant-rail').count(), 0);
  await find('support'); await legacy.locator('.business-root').waitFor();
  assert.match(await legacy.locator('.business-root').innerText(), /本机全部/);
  await find('connections'); await legacy.locator('.connections-root').waitFor();
  assert.equal(await legacy.locator('[data-connection-action="ozon-setup"]').count(), 1);
  assert.equal(await legacy.locator('[data-connection-action="platform-setup"]').count(), 1);
  checks.push('Support and the unique connection hub retain original leaf routes without a second assistant');
  if (process.env.QA_CHANNELS === '1') {
    const channels = legacy.locator('section[aria-label="消息渠道"]');
    await channels.locator('[data-channel-action="edit"][data-channel="feishu"]').waitFor();
    assert.equal(await channels.locator('tbody tr').count(), 4);
    await channels.locator('[data-channel-action="edit"][data-channel="feishu"]').click();
    await legacy.locator('#channel-label').fill('Synthetic channel <label>');
    await legacy.locator('#channel-selected').check();
    await legacy.locator('#channel-save').click();
    await legacy.locator('#channel-mode').waitFor({state:'detached'});
    const plan = (await invoke('commerce_channel_status')).channels[0].binding;
    assert.equal(plan.label, 'Synthetic channel <label>'); assert.equal(plan.selected, true); assert.equal(plan.revision, '1');
    await channels.locator('[data-channel-action="edit"][data-channel="feishu"]').click();
    assert.equal(await legacy.locator('#channel-label').inputValue(), plan.label);
    await legacy.locator('#channel-label').fill('Synthetic unsaved second edit');
    await invoke('commerce_channel_configure', {channel:'feishu',mode:'app',selected:true,label:'Synthetic concurrent update',expected_revision:'1'});
    await legacy.locator('#channel-save').click();
    await legacy.locator('#channel-edit-error').getByText('配置已有新版本', {exact:false}).waitFor();
    assert.equal(await legacy.locator('#channel-label').inputValue(), 'Synthetic unsaved second edit');
    await legacy.getByRole('dialog').getByRole('button', {name:'关闭',exact:true}).click();
    checks.push('Four-channel configuration persists escaped labels and rejects a stale revision while preserving unsaved input');

    // Hold only this synthetic mutation's response after its real local commit.
    let release, committed;
    const held = new Promise(resolve => { release=resolve; });
    const didCommit = new Promise(resolve => { committed=resolve; });
    const handler = async route => {
      const body=route.request().postDataJSON();
      if(body?.tool!=='commerce_channel_configure')return route.fallback();
      const response=await route.fetch(); committed(); await held; await route.fulfill({response});
    };
    await page.route('**/v1/invoke',handler);
    try {
      await channels.locator('[data-channel-action="refresh"]').click();
      await channels.locator('[data-channel-action="edit"][data-channel="feishu"]').click();
      await legacy.locator('#channel-label').fill('Synthetic delayed save');
      await legacy.locator('#channel-save').click(); await didCommit;
      await legacy.getByRole('dialog').getByRole('button', {name:'关闭',exact:true}).click();
      await channels.locator('[data-channel-action="edit"][data-channel="dingtalk"]').click();
      await legacy.locator('#channel-label').fill('Synthetic next-dialog draft');
      release(); await page.waitForLoadState('networkidle');
      assert.match(await legacy.getByRole('dialog').innerText(), /钉钉/);
      assert.equal(await legacy.locator('#channel-label').inputValue(), 'Synthetic next-dialog draft');
      await legacy.getByRole('dialog').getByRole('button', {name:'关闭',exact:true}).click();
    } finally { release(); await page.unroute('**/v1/invoke',handler); }
    checks.push('A delayed committed channel save cannot close a newer dialog or erase its draft');
    const initialTheme=await page.locator('#react-theme').inputValue();
    await page.locator('#react-theme').selectOption('dark');
    await page.setViewportSize({width:390,height:844});
    await channels.locator('[data-channel-action="edit"][data-channel="dingtalk"]').click();
    const modalBox=await legacy.getByRole('dialog').boundingBox();
    assert.ok(modalBox.x>=0&&modalBox.x+modalBox.width<=391);
    assert.ok(await page.locator('html').evaluate(node=>node.scrollWidth<=node.clientWidth+1));
    assert.ok(await legacy.locator('html').evaluate(node=>node.scrollWidth<=node.clientWidth+1));
    await page.screenshot({path:path.join(output,'isolated-channels-mobile-dark.png')});
    await legacy.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).click();
    await page.setViewportSize({width:1440,height:960});
    await page.locator('#react-theme').selectOption(initialTheme);
    checks.push('Channel selection remains operable at 390px in dark mode without overflowing either document');
  }

  await page.locator('.r-business-nav').getByRole('button', { name: '商品', exact: true }).click();
  assert.equal(await product.locator('#copilot-message').inputValue(), 'synthetic-unsent-product-draft');
  assert.equal(await product.locator('#pw-cost-purchase_cost').inputValue(), '34');
  await find('operations'); assert.equal(await cost.locator('input[name="price"]').inputValue(), '129');
  assert.match(await cost.innerText(), /未关联商品/);
  await find('restock'); assert.equal(await legacy.locator('#analysis-available').inputValue(), '77');
  checks.push('Product draft, product cost, general-cost input and restock input survive module round trips');

  // Keyboard resizing exercises the actual root-to-product layout bridge.
  await page.locator('.r-business-nav').getByRole('button', { name: '运营台', exact: true }).click();
  const separator = page.locator('.r-chat-splitter'); await separator.focus(); await page.keyboard.press('Home');
  const rootWidth = (await page.locator('.r-shared-assistant').boundingBox()).width;
  await page.locator('.r-business-nav').getByRole('button', { name: '商品', exact: true }).click();
  const productAssistant = product.locator('.pw-conversation');
  await page.waitForTimeout(150);
  assert.ok(Math.abs((await productAssistant.boundingBox()).width - rootWidth) <= 3, 'Opaque product frame did not adopt the shared AI width');
  assert.equal(await product.locator('#copilot-message').inputValue(), 'synthetic-unsent-product-draft');
  checks.push('Shared AI width crosses the opaque frame without rebuilding the product');

  const productHtml = await page.locator('iframe[title="完整商品内容编辑"]').getAttribute('srcdoc');
  const nonce = productHtml.match(/const nonce = '([^']+)', pending = new Map/)[1];
  const currentWidth = await page.locator('.r-work-area').evaluate(node => node.style.getPropertyValue('--r-chat-width'));
  await page.evaluate(nonce => window.dispatchEvent(new MessageEvent('message', {
    source: window, data: { type: 'commerce:workspace-chat-width', nonce, width: 600 },
  })), nonce);
  await product.locator('body').evaluate((_node, nonce) => {
    parent.postMessage({ type: 'commerce:workspace-chat-width', nonce: 'wrong-scope', width: 600 }, '*');
    for (const width of [-1, 961, NaN, Infinity, '640']) parent.postMessage({ type: 'commerce:workspace-chat-width', nonce, width }, '*');
  }, nonce);
  await page.waitForTimeout(100);
  assert.equal(await page.locator('.r-work-area').evaluate(node => node.style.getPropertyValue('--r-chat-width')), currentWidth);
  checks.push('Width bridge rejects a foreign source, wrong nonce and invalid width values');

  const after = await invoke('commerce_workspace_get', { case_id: caseId });
  assert.equal(after.source_sha256, original.source_sha256);
  assert.deepEqual(after.forms.cost, original.forms.cost);
  assert.deepEqual(after.tasks, original.tasks);
  assert.deepEqual(await inventory(), before);
  checks.push('Original product source, saved cost, tasks and conversation inventory remain unchanged');
  await page.screenshot({ path: path.join(output, 'isolated-workspace.png') });

  await find('operations');
  await page.reload(); await cost.locator('input[name="price"]').waitFor();
  await page.locator('.r-business-nav').getByRole('button', { name: '商品', exact: true }).click();
  await find('operations'); await cost.locator('input[name="price"]').waitFor();
  assert.deepEqual(await inventory(), before, 'General-cost refresh/reopen must stay read-only');
  checks.push('Refreshing and reopening general cost do not create tasks or surfaces');

  // The fixture patches only the model provider; the UI, HTTP, dialogue store
  // and bounded read executor are real. No real model or marketplace is called.
  await page.locator('.r-business-nav').getByRole('button', { name: '运营台', exact: true }).click();
  const assistant = page.locator('.r-shared-assistant');
  await assistant.locator('#copilot-message').fill('synthetic-root-draft');
  await page.getByRole('button', {name:'切换智能助手',exact:true}).click();
  await page.getByRole('button', {name:'切换智能助手',exact:true}).click();
  assert.equal(await assistant.locator('#copilot-message').inputValue(), 'synthetic-root-draft');
  await assistant.locator('#copilot-message').fill('Synthetic fixture: inspect the permitted current context.');
  await assistant.locator('[data-copilot-action="send"]').click();
  await assistant.getByText('合成验收：已读取当前允许的商品资料；成本仍由确定性计算器核对。', { exact: false }).waitFor();
  const conversations = await invoke('commerce_copilot_list');
  assert.equal(conversations.threads.length, before.threads + 1);
  const dialogue = await invoke('commerce_copilot_get', { thread_id: conversations.threads[0].id });
  assert.equal(dialogue.turns.length, 1);
  assert.equal((await inventory()).tasks, before.tasks);
  assert.equal((await inventory()).surfaces, before.surfaces);
  checks.push('A single explicit synthetic-model dialogue returns through the real shared assistant without duplicate turns or tasks');
  }
  if (process.env.COMMERCE_QA_INTEL === '1') {
    const legacy = page.frameLocator('iframe[title="专业业务模块"]');
    await find('intelligence');
    const searchReady = async () => {
      await legacy.locator('#intel-search button[type="submit"]:not(:disabled)').waitFor();
      assert.equal(await legacy.locator('.intel-error').count(), 0);
    };
    await searchReady();
    assert.equal(await legacy.locator('.intel-timeline li').count(), 20);
    const ids = () => legacy.locator('.intel-timeline [data-intel-id]').evaluateAll(nodes => nodes.map(n => n.dataset.intelId));
    const first = await ids();
    await legacy.locator('[data-intel-action="next"]').click(); await searchReady();
    await legacy.locator('.intel-pagination').filter({ hasText: '第 2 页' }).waitFor({timeout:5000});
    assert.ok((await ids()).every(id => !first.includes(id)), JSON.stringify({first,second:await ids(),pagination:await legacy.locator('.intel-pagination').innerText(),stream:await legacy.locator('.intel-stream').innerText()}));
    await legacy.locator('[data-intel-action="previous"]').click(); await searchReady();
    assert.deepEqual(await ids(), first);
    checks.push('Intelligence pagination loads distinct stable pages through the real iframe bridge');

    await legacy.locator('[data-intel-action="filters"]').click();
    for (const source of ['hmrc', 'transport']) {
      await legacy.locator('#intel-source').selectOption(source); await searchReady();
      assert.equal(await legacy.locator('.intel-timeline li').count(), 1);
      assert.match(await legacy.locator('.intel-timeline').innerText(), new RegExp('Synthetic ' + source));
    }
    await legacy.locator('#intel-category').selectOption('logistics'); await searchReady();
    assert.equal(await legacy.locator('.intel-timeline li').count(), 1);
    await legacy.locator('#intel-watch-open').click();
    await legacy.locator('#intel-watch-name').fill('Synthetic logistics watch');
    await legacy.locator('#intel-watch-save').click();
    await legacy.locator('#intel-watch-name').waitFor({ state: 'detached' });
    const saved = (await invoke('commerce_intel_watch_list')).watches;
    assert.equal(saved.length, 1); assert.equal(saved[0].matches, 1);
    assert.equal(saved[0].notification_enabled, false);
    checks.push('HMRC, DfT and logistics filters and saved watches use the advertised backend contract');

    await legacy.locator('.intel-timeline [data-intel-id]').click();
    const selectedId = (await invoke('commerce_intel_search', {source:'transport',category:'logistics'})).items[0].id;
    await legacy.locator('.intel-record').waitFor();
    await searchReady();
    assert.equal((await invoke('commerce_intel_item_get', { item_id: selectedId })).is_viewed, true);
    await legacy.locator('[data-intel-action="bookmark"]').click();
    await legacy.getByRole('button', { name: '取消收藏', exact: true }).waitFor();
    assert.equal((await invoke('commerce_intel_item_get', { item_id: selectedId })).is_bookmarked, true);
    await legacy.locator('[data-intel-task]').click();
    await legacy.locator('.intel-review').getByText('核查已排队', { exact: false }).waitFor();
    assert.equal((await inventory()).tasks, before.tasks + 1);
    await page.screenshot({ path: path.join(output, 'isolated-intelligence.png') });
    checks.push('Opening, bookmarking and creating an explicit evidence-bound review persist real synthetic state');
    await page.reload(); await legacy.locator('#intel-search').waitFor(); await searchReady();
    assert.equal((await invoke('commerce_intel_watch_list')).watches.length, 1);
    assert.equal((await invoke('commerce_intel_item_get', { item_id: selectedId })).is_bookmarked, true);
    assert.equal((await inventory()).tasks, before.tasks + 1);
    checks.push('Intelligence records and saved searches survive reload without a duplicate review task');
  }
  assert.deepEqual(errors, []); assert.deepEqual(external, []);
  assert.equal(await manifestHash(), candidate, 'Candidate changed during regression');
  const report = { status: 'Passed', synthetic: true, candidate_manifest_sha256: candidate, layout: 'Hosted layout over authenticated HTTP; native DSH verified separately', checks, before, after: await inventory(), page_errors: errors, external_requests: external };
  await writeFile(path.join(output, 'react-workspace-regression.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report));
} catch (error) {
  await writeFile(path.join(output, 'isolated-server.log'), serverLog);
  if (page) await page.screenshot({ path: path.join(output, 'isolated-failure.png') }).catch(() => {});
  if (process.env.COMMERCE_QA_INTEL === '1' && page) {
    await writeFile(path.join(output, 'intel-traffic.json'), JSON.stringify({intelTraffic},null,2));
  }
  await writeFile(path.join(output, 'react-workspace-regression.json'), JSON.stringify({ status: 'Failed', candidate_manifest_sha256: candidate, checks, error: error.message, page_errors: errors }, null, 2) + '\n');
  throw error;
} finally {
  await browser?.close();
  if (server.exitCode === null) server.kill('SIGTERM');
  const stopped = await Promise.race([closed.then(() => true), pause(5000).then(() => false)]);
  if (!stopped) { server.kill('SIGKILL'); await closed; }
  await rm(work, { recursive: true, force: true });
}
