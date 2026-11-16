import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
async function component(entry, name) {
  const compiled = await build({ entryPoints: [entry], bundle: true, write: false, format: 'cjs', platform: 'node', external: ['react'], loader: { '.css': 'empty' } });
  const module = { exports: {} };
  vm.runInNewContext(compiled.outputFiles[0].text, { module, exports: module.exports, require, window: { CommerceUI: { icon: () => '' } } });
  return module.exports[name];
}

test('the operational home retains sales and statistical panels while loading', async () => {
  const Overview = await component('src/overview.tsx', 'Overview');
  const html = renderToStaticMarkup(React.createElement(Overview, { demo: false, navigate() {}, onThread() {}, onResearch() {} }));
  assert.match(html, /支付销售额/);
  assert.match(html, /经营概览/);
  assert.match(html, /平台销售构成/);
});

const dashboard = { sales: null, currency: 'USD', orders: 8, pending: 0, stock_alerts: null, data_source: 'ozon_api', rate_note: '金额未核对', platforms: [] };
const Statistics = await component('src/overview-statistics.tsx', 'OverviewStatistics');
const render = props => renderToStaticMarkup(React.createElement(Statistics, { dashboard, demo: false, loading: false, navigate() {}, ...props }));

test('live status counts use snapshot rows and preserve stale and scope warnings', () => {
  const html = render({ orders: { orders: [
    { status: 'delivering', status_zh: '配送中' }, { status: 'delivering', status_zh: '配送中' }, { status: 'cancelled', status_zh: '已取消' },
  ], total: 3, data_source: 'ozon_api', stale: true, scope_confirmed: false, observed_at: '2026-11-15T09:15:29Z' } });
  assert.match(html, /配送中<\/span><strong>2 条/);
  assert.match(html, /已取消<\/span><strong>1 条/);
  assert.match(html, /同步快照.*3.*条发货单/);
  assert.match(html, /快照已过期/);
  assert.match(html, /同步范围待确认/);
  assert.match(html, /17:15:29/);
  assert.match(html, /待处理发货单<\/span><strong>0<\/strong>/);
  assert.match(html, /支付销售额<\/span><strong>待核对<\/strong>/);
  assert.match(html, /尚无经过核对的销售额与趋势数据/);
});

test('platform amounts render as a labelled example and a known zero stays zero', () => {
  const html = render({ demo: true, dashboard: { ...dashboard, sales: 0, platforms: [{ id: 'ozon', name: 'Ozon', amount: 0 }, { id: 'amazon', name: 'Amazon', amount: 1234.5 }] }, orders: { orders: [], total: 0, data_source: 'synthetic' } });
  assert.match(html, /示例平台销售构成/);
  assert.match(html, /1,234\.50/);
  assert.match(html, /支付销售额<\/span><strong><span class="r-number">0\.00/);
  assert.doesNotMatch(html, /NaN|Infinity|快照已过期/);
});

test('a failed read differs from a disconnected or empty snapshot', () => {
  assert.match(render({ dashboard: undefined }), /销售统计未读到/);
  assert.match(render({}), /发货单统计未读到/);
  assert.match(render({ orders: { orders: [], total: 0, data_source: 'not_connected' } }), /尚无发货单快照/);
  assert.match(render({ orders: { orders: [], total: 0, data_source: 'ozon_api', stale: false, scope_confirmed: true } }), /当前快照没有发货单/);
});

test('real daily amounts and inventory are shown without assigning a currency or hiding anomalies', () => {
  const html = render({ dashboard: { ...dashboard, sales: 0.3, currency: '', sales_label: '下单金额（平台口径）',
    sales_summary: { date_from: '2026-11-13', date_to: '2026-11-15', ordered_units: 3, stale: true, observed_at: '2026-11-16T00:00:00Z', records: [
      { day: '2026-11-13', amount: '0.1', ordered_units: 1 }, { day: '2026-11-14', amount: '0.2', ordered_units: 2 }, { day: '2026-11-15', amount: '0', ordered_units: 0 },
    ] }, inventory: { sku_count: 2, stale: false, observed_at: '2026-11-16T00:00:00Z', scope: '按履约方式汇总，非单仓', orderable_basis: 'present - reserved', groups: [
      { type: 'fbs', rows: 2, present: 12, reserved: 3, orderable_api: 9, inconsistent_rows: 0 },
      { type: 'fbo', rows: 1, present: 1, reserved: 2, orderable_api: null, inconsistent_rows: 1 },
    ] } } });
  assert.match(html, /下单金额（平台口径）/);
  assert.match(html, /3个真实日数据点，币种未返回/);
  assert.match(html, /销售快照已过期/);
  assert.match(html, /按日明细（3 天）/);
  assert.match(html, /2026-11-15<\/td><td>0<\/td><td>0/);
  assert.match(html, /FBS<\/td><td>2<\/td><td>12<\/td><td>3<\/td><td>9/);
  assert.match(html, /待核对（1 条异常）/);
  assert.doesNotMatch(html, /USD|RUB|CNY|NaN|Infinity/);
});
