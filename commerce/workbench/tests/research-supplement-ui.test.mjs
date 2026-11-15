import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { build } from 'esbuild';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const compiled = await build({ entryPoints: ['src/research-details.tsx'], bundle: true, write: false, format: 'cjs', platform: 'node', external: ['react', 'react/jsx-runtime'] });
const module = { exports: {} };
vm.runInNewContext(compiled.outputFiles[0].text, { module, exports: module.exports, require: createRequire(import.meta.url), window: { CommerceUI: { icon: () => '' } } });
const { ResearchDetails } = module.exports;
const report = { summary: '本轮补证分析', findings: ['供给样本仍待核验'], limitations: ['销量和利润未知'], evidence_refs: ['S4'] };
const base = { schema: 'commerce-market-research-v1', task_id: 'task-a', run_id: 'new-run', thread_id: 'thread-a', status: 'partial', phase: 'finished', revision: 20, query: '俄罗斯 Ozon 厨房收纳', market: 'RU', source_count: 1, candidate_count: 0, error: null, questions: [], candidates: [], sources: [], report, updated_at: '2026-11-13T14:00:00Z' };
const render = changes => renderToStaticMarkup(createElement(ResearchDetails, { job: { ...base, ...changes }, busy: false, refresh() {}, cancel() {}, resume() {}, openCandidate() {}, openThread() {} }));
const captured = { id: 'S1', url: 'https://example.com/catalog/', title: '目录正文', captured_at: '2026-11-13T14:00:00Z', sha256: 'raw-html-hash', status: 'collected', error: null, evidence_kind: 'public_page', excerpt: '目录样本' };
const imported = { ...captured, id: 'S4', title: 'Ozon 官方商品笔记', status: 'imported', evidence_kind: 'imported_public_notes', provenance: 'operator_import_unverified', sha256: 'notes-document-hash', snapshot_age: 'Crawled: 2 weeks ago', imported_at: '2026-11-13T15:00:00Z', source_ref: { id: 'source-a', version: 2, sha256: 'notes-document-hash' } };

test('imported notes stay separate from collected HTML and retain their age and pinned version', () => {
  const html = render({ sources: [captured, imported], supplemental_source_count: 1 });
  assert.match(html, /采集来源 1/); assert.match(html, /补充资料 1/);
  assert.match(html, /补充资料（未核验）/); assert.match(html, /外部公开资料笔记/); assert.match(html, /未独立核验/); assert.match(html, /非本机原始网页/);
  assert.match(html, /Crawled: 2 weeks ago/); assert.match(html, /资料版本 2/);
  assert.match(html, /资料文档 SHA-256/); assert.match(html, /notes-document-hash/);
  assert.equal(html.split('>已采集<').length - 1, 1);
});
test('older jobs remain readable and a failed capture is never promoted by a supplement', () => {
  const failed = { ...captured, id: 'S3', status: 'failed', title: '', sha256: null, excerpt: '', error: 'market_research_source_timeout' };
  const legacy = render({ sources: [captured, failed] });
  assert.ok(!legacy.includes('补充资料 0')); assert.match(legacy, /来源访问超时/); assert.match(legacy, /未采集成功/);
  const supplemented = render({ sources: [failed, imported], supplemental_source_count: 1 });
  assert.match(supplemented, /来源访问超时/); assert.match(supplemented, /补充资料（未核验）/);
});
test('prior reports and prior candidates remain visible without calling them the current round', () => {
  const html = render({ report_history: [{ revision: 18, run_id: 'old-run', report: { ...report, summary: '<img onerror=bad>旧分析', evidence_refs: ['S1'] } }], candidates: [{ case_id: 'old-case', name: '旧候选', source_ids: ['S1'], research_run_id: 'old-run' }, { case_id: 'new-case', name: '新候选', source_ids: ['S4'], research_run_id: 'new-run' }], candidate_count: 2 });
  assert.match(html, /历史分析/); assert.match(html, /修订 18/); assert.match(html, /旧分析/); assert.ok(!html.includes('<img'));
  assert.match(html, /旧候选/); assert.match(html, /新候选/); assert.match(html, /此前候选/); assert.match(html, /本轮候选/);
});
test('superseded supplemental notes retain their document but are not shown as active imported evidence', () => {
  const html = render({ sources: [{ ...imported, id: 'S4', status: 'superseded' }, { ...imported, id: 'S5' }], supplemental_source_count: 1 });
  assert.match(html, /补充资料 1/); assert.equal(html.split('>已替代补证<').length - 1, 1);
  assert.equal(html.split('>补充资料（未核验）<').length - 1, 1); assert.equal(html.split('notes-document-hash').length - 1, 2);
  assert.ok(!html.includes('未采集成功'));
});
