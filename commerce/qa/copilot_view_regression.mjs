// Real DOM regression over shared sources; fixture reads never call a model.
import assert from 'node:assert/strict';
import { readFile, readdir, mkdir } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
let playwright;
try { playwright = await import('playwright'); } catch {
  for (const entry of await readdir(path.join(homedir(), '.npm/_npx')).catch(() => [])) {
    try { playwright = await import(pathToFileURL(path.join(homedir(), '.npm/_npx', entry, 'node_modules/playwright/index.mjs')).href); break; } catch {}
  }
}
assert.ok(playwright, 'Existing Playwright required; no dependencies are installed.');
const browser = await playwright.chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  await page.route('https://commerce.fixture.test/**', route => route.fulfill({ contentType: 'text/html', body: '<main><input id="outside" aria-label="其它输入"><div id="host"></div></main>' }));
  await page.goto('https://commerce.fixture.test/');
  await page.addStyleTag({ content: (await readFile(path.join(root, 'web/style.css'), 'utf8')) + (await readFile(path.join(root, 'ui/primitives.css'), 'utf8')) + (await readFile(path.join(root, 'web/copilot-ui.css'), 'utf8')) + '#host{height:850px;width:420px}.copilot-shell{height:850px!important}' });
  await page.addScriptTag({ content: await readFile(path.join(root, 'ui/kit.js'), 'utf8') });
  await page.addScriptTag({ content: await readFile(process.env.COPILOT_SOURCE || path.join(root, 'web/copilot-ui.js'), 'utf8') });
  await page.evaluate(() => {
    const context = { module: 'products', demo: true, platform: 'ozon', store_id: 'ozon-demo', market: 'RU', entity: { kind: 'product', id: 'TEST-SKU' } };
    window.calls = [];
    const run = i => ({ id: 'run-' + i, status: i === 14 ? 'running' : 'completed', result: { answer: ('合成回答 ' + i + '，仅用于保持阅读位置。').repeat(4), observations: [{ id: 'O1', tool: 'commerce_runtime_status', data: { worker: 'stopped_or_stale' } }] } });
    window.thread = { id: 'thread', context, context_sha256: 'synthetic', turns: Array.from({ length: 15 }, (_, i) => ({ id: 'turn-' + i, question: '合成问题 ' + i, run: run(i) })), latest_run: run(14) };
    window.otherThread = { id: 'other-thread', context: { ...context, entity: { kind: 'product', id: 'OTHER-SKU' } }, context_sha256: 'other-synthetic', turns: [], latest_run: null };
    window.controller = window.CommerceCopilot({ inline: true, compact: true, getContext: () => context, repaint() { document.querySelector('#host').innerHTML = window.controller.view(); window.controller.afterPaint(); }, api: async (name, args) => { window.calls.push(name); if (name === 'commerce_model_list') return { models: [{ id: 'project-default', label: '合成模型', selectable: true }], default_model_id: 'project-default' }; if (name === 'commerce_copilot_list') return { threads: [window.thread, window.otherThread] }; if (name === 'commerce_copilot_get') return structuredClone(args.thread_id === 'other-thread' ? window.otherThread : window.thread); throw Error(name); } });
    window.controller.open(undefined, { focus: false });
  });
  await page.waitForFunction(() => document.querySelectorAll('.copilot-assistant').length === 15);
  const composer = page.locator('#copilot-message');
  await composer.fill('未发送的中文草稿，保留光标');
  await composer.evaluate(el => { el.setSelectionRange(3, 7); window.originalComposer = el; });
  await page.evaluate(() => { document.querySelectorAll('.copilot-evidence')[3].open = true; document.querySelector('#copilot-log').scrollTop = 650; });
  const initialTop = await page.locator('#copilot-log').evaluate(el => el.scrollTop);
  await page.evaluate(() => window.controller.contextChanged());
  assert.equal(await composer.inputValue(), '未发送的中文草稿，保留光标');
  assert.deepEqual(await composer.evaluate(el => [el.selectionStart, el.selectionEnd]), [3, 7]);
  assert.ok(await page.locator('.copilot-evidence').nth(3).evaluate(el => el.open), 'open evidence survives repaint');
  assert.ok(Math.abs(await page.locator('#copilot-log').evaluate(el => el.scrollTop) - initialTop) < 2, 'reading scroll survives repaint');
  assert.ok(await composer.evaluate(el => el === window.originalComposer), 'same-scope draft editor keeps DOM identity');
  const anchor = await page.locator('#copilot-log').evaluate(log => {
    const top = log.getBoundingClientRect().top;
    const item = [...log.querySelectorAll('[data-message-key]')].find(el => el.getBoundingClientRect().bottom > top + 1);
    return { key: item.dataset.messageKey, offset: item.getBoundingClientRect().top - top };
  });
  await page.evaluate(() => {
    window.thread.latest_run.status = 'completed';
    window.thread.latest_run.actions = [{ proposal_id: 'P1', task_id: 'fixture-task', receipt: { task_id: 'fixture-task', status: 'queued', outcome: 'pending' } }];
    window.thread.turns[0].run.result.answer += '较早回复更新。'.repeat(100);
    window.thread.turns[14].run.result.answer += ' 轮询读取回执';
    window.controller.contextChanged();
  });
  // Latest model run is complete; only the original pending task keeps polling.
  const reads = await page.evaluate(() => window.calls.filter(name => name === 'commerce_copilot_get').length);
  await page.waitForFunction(n => window.calls.filter(name => name === 'commerce_copilot_get').length > n, reads);
  await page.waitForFunction(() => document.querySelector('#copilot-log').textContent.includes('轮询读取回执'));
  const offset = await page.locator('#copilot-log').evaluate((log, key) => [...log.querySelectorAll('[data-message-key]')].find(el => el.dataset.messageKey === key).getBoundingClientRect().top - log.getBoundingClientRect().top, anchor.key);
  assert.ok(Math.abs(offset - anchor.offset) < 2, 'polling holds the visible message when earlier content grows');
  assert.ok(await page.locator('.copilot-evidence').nth(3).evaluate(el => el.open));
  assert.deepEqual(await composer.evaluate(el => [el.selectionStart, el.selectionEnd]), [3, 7]);
  await composer.dispatchEvent('compositionstart');
  await page.evaluate(() => { window.imeComposer = document.querySelector('#copilot-message'); window.thread.turns[14].run.result.answer += ' 新回执'; window.controller.contextChanged(); });
  assert.ok(await composer.evaluate(el => el === window.imeComposer), 'refresh does not replace active IME editor');
  await composer.dispatchEvent('compositionend');
  await page.waitForFunction(() => document.querySelector('#copilot-log').textContent.includes('新回执'));
  await page.locator('#outside').focus();
  await page.evaluate(() => window.controller.contextChanged());
  assert.equal(await page.evaluate(() => document.activeElement.id), 'outside', 'background update never steals outside focus');
  await composer.fill('原商品的组合输入');
  await composer.dispatchEvent('compositionstart');
  await page.evaluate(() => window.controller.openThread('other-thread'));
  await composer.fill('原商品的组合输入完成');
  await composer.dispatchEvent('compositionend');
  await page.waitForFunction(() => !document.querySelector('#copilot-log').textContent.includes('合成问题 14'));
  assert.equal(await composer.inputValue(), '', 'finishing old IME input never enters another product draft');
  await page.evaluate(() => window.controller.openThread('thread'));
  assert.equal(await composer.inputValue(), '原商品的组合输入完成', 'completed composition stays with its original thread');
  await composer.dispatchEvent('compositionstart');
  await page.evaluate(() => { window.controller.close(); window.thread.turns[14].run.result.answer += ' 关闭后刷新'; window.controller.open(undefined, { focus: false }); });
  await page.waitForFunction(() => document.querySelector('#copilot-log')?.textContent.includes('关闭后刷新'), null, { timeout: 4000 });
  assert.equal(await composer.inputValue(), '原商品的组合输入完成', 'closing mid-composition leaves no stale composition lock');
  assert.ok((await page.evaluate(() => window.calls)).every(name => !/send|execute|apply/.test(name)));
  await page.evaluate(() => {
    window.thread.turns[14].run.result.observations = [{ id: 'R1', tool: 'commerce_workspace_get', data: {
      source_sha256: 'synthetic-gap-source', stages: [
        { id: 'S3', name: '供应链资料', role: 'sourcer', status: 'BLOCKED', missing: 3, gaps_truncated: true, gaps: [
          { id: 'artifact', status: 'HOLD', reason: '缺少采购报价 <script>bad()</script>', owner: 'sourcer', verify: '补齐明确币种与报价来源后重新核对' },
          { id: 'currency', status: 'FAIL', reason: '报价币种不一致', owner: 'sourcer', verify: '核对原始报价币种' },
        ] },
        { id: 'S7', name: '广告归因', role: 'grower', status: 'BLOCKED', missing: 1, gaps: [
          { id: 'capability', status: 'BLOCKED', reason: '尚未接入广告消耗', owner: 'grower', verify: '补充真实数据与适配器后复验' },
        ] },
      ],
    } }];
    window.controller.contextChanged();
  });
  const gapEvidence = page.locator('.copilot-workspace-evidence');
  await gapEvidence.waitFor({ state: 'attached' });
  assert.equal(await gapEvidence.count(), 1, 'workspace observations have readable gap evidence');
  assert.ok((await gapEvidence.textContent()).includes('补齐明确币种与报价来源后重新核对'));
  assert.ok((await gapEvidence.textContent()).includes('待补资料'));
  assert.ok((await gapEvidence.textContent()).includes('检查不符'));
  assert.ok((await gapEvidence.textContent()).includes('受阻'));
  assert.ok((await gapEvidence.textContent()).includes('其余缺项'));
  assert.equal(await gapEvidence.locator('script').count(), 0, 'source descriptions remain text');
  assert.equal(await gapEvidence.locator('button').count(), 0, 'reading gaps grants no execution action');
  assert.ok((await gapEvidence.textContent()).includes('历史读取快照'));
  await gapEvidence.evaluate(el => {
    el.closest('.copilot-evidence').open = true;
    el.querySelectorAll('details').forEach(detail => { detail.open = true; });
    document.querySelector('#host').style.width = 'min(420px, 100%)';
    el.scrollIntoView();
  });
  if (process.env.QA_OUTPUT_DIR) await mkdir(process.env.QA_OUTPUT_DIR, { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await gapEvidence.evaluate(el => {
        el.closest('.copilot-evidence').open = true;
        el.querySelectorAll('details').forEach(detail => { detail.open = true; });
        el.scrollIntoView({ block: 'start' });
      });
      assert.ok(await gapEvidence.evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'gap evidence wraps within the available width');
      if (process.env.QA_OUTPUT_DIR) await page.screenshot({ path: path.join(process.env.QA_OUTPUT_DIR, `workspace-gaps-${width}-${theme}.png`) });
    }
  }
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.evaluate(() => { document.documentElement.dataset.theme = 'light'; });
  await page.evaluate(() => {
    window.controller.dispose();
    const context = { module: 'overview', demo: true };
    window.createdThread = { id: 'created-thread', context, context_sha256: 'created-scope', turns: [], latest_run: null };
    window.controller = window.CommerceCopilot({ inline: true, compact: true, getContext: () => context, repaint() { document.querySelector('#host').innerHTML = window.controller.view(); window.controller.afterPaint(); }, api: async name => {
      if (name === 'commerce_model_list') return { models: [{ id: 'project-default', label: '合成模型', selectable: true }] };
      if (name === 'commerce_copilot_list') return { threads: [] };
      if (name === 'commerce_copilot_open') { window.newOpened = true; return window.createdThread; }
      throw Error(name);
    } });
    window.controller.open(undefined, { focus: false });
    window.lockHeld = false;
    navigator.locks.request('commerce-copilot-draft-v1:created-thread', async () => { window.lockHeld = true; await new Promise(resolve => { window.releaseDraftLock = resolve; }); });
  });
  await page.waitForFunction(() => window.lockHeld);
  await composer.fill('创建前输入');
  await page.locator('[data-copilot-action="new"]').click();
  await page.waitForFunction(() => window.newOpened);
  await composer.fill('迁移等待时继续输入');
  await page.evaluate(() => window.releaseDraftLock());
  await page.waitForFunction(() => document.querySelector('[data-copilot-action="new"]:not(:disabled)'));
  assert.equal(await composer.inputValue(), '迁移等待时继续输入', 'an explicit new conversation keeps input typed while its draft migration waits');
  await page.evaluate(() => window.controller.dispose());
  console.log('Passed: draft identity, selection, IME deferral and cross-thread isolation, close recovery, delayed draft migration, readable workspace gaps at 1440/390 in light/dark, escaped source text, evidence disclosure, scroll anchor under real polling, pending receipt reads, outside focus, and no model sends.');
} finally { await browser.close(); }
