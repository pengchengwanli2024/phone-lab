import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import path from 'node:path';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['src/capability-history-state.ts'],bundle:true,format:'cjs',write:false,platform:'node'});
const module={exports:{}};new Function('require','module','exports',bundle.outputFiles[0].text)(createRequire(path.resolve('package.json')),module,module.exports);
const {memoryRows,skillRows,historyRows,timeText}=module.exports;
const fact=(id,extra={})=>({id,layer:'L2',content:'fact '+id,status:'confirmed',effective_status:'confirmed',revision:2,synthetic:false,created_at:1000,...extra});
const task=(id,extra={})=>({id,skill_id:'sealeap-'+id,status:'completed',synthetic:false,created_at:'1970-01-01T00:20:00+00:00',adapter:'calc.py',...extra});

test('memory rows keep revision, correction link and the effective state', () => {
  const [stale,corrected]=memoryRows([
    fact('a',{effective_status:'stale',invalid_reason:'memory_fact_changed',layer:'L3',title:'摘录'}),
    fact('b',{supersedes:{id:'memory_0123456789abcdef',revision:3}}),
  ]);
  assert.equal(stale.label,'摘要');assert.equal(stale.title,'摘录');
  assert.equal(stale.status,'来源或事实已失效');assert.equal(stale.tone,'warning');
  assert.ok(stale.meta.includes('失效原因：memory_fact_changed'));
  assert.equal(corrected.status,'已人工确认');assert.equal(corrected.tone,'gray');
  assert.ok(corrected.meta.some(text=>text.startsWith('纠正旧事实 memory_01234567…')&&text.endsWith('（修订 3）')));
  assert.equal(corrected.at,1000000);
});

test('unknown status codes stay visible and unreadable times are not guessed', () => {
  const [memory]=memoryRows([fact('a',{effective_status:'archived',created_at:undefined})]);
  assert.equal(memory.status,'原记录：archived');assert.equal(memory.at,null);
  const [skill]=skillRows([task('x',{status:'queued',created_at:'not a date'})],false);
  assert.equal(skill.status,'原记录：queued');assert.equal(skill.at,null);
  assert.equal(timeText(null),'时间未记录');
});

test('skill tasks are limited to the page data range and flag unknown outcomes', () => {
  const rows=skillRows([task('real'),task('demo',{synthetic:true}),task('cut',{status:'interrupted',adapter:null,mode_id:'m1',source_sha256:'abcdef0123456789'})],false);
  assert.deepEqual(rows.map(row=>row.title),['sealeap-real','sealeap-cut']);
  assert.equal(rows[1].status,'已中断，结果未知');assert.equal(rows[1].tone,'warning');
  assert.deepEqual(rows[1].meta,['无本机计算器','模式 m1','技能版本 abcdef01']);
  assert.deepEqual(skillRows([task('demo',{synthetic:true})],true).map(row=>row.title),['sealeap-demo']);
});

test('history is newest first with untimed records last', () => {
  const rows=historyRows([fact('old',{created_at:10}),fact('none',{created_at:undefined}),fact('new',{created_at:5000})],[task('mid')],false);
  assert.deepEqual(rows.map(row=>row.key),['memory:new','skill:mid','memory:old','memory:none']);
});

test('the page is read-only and admits what is not recorded', async () => {
  const source=await readFile('src/capability-history.tsx','utf8');
  const tools=[...source.matchAll(/'(commerce_[a-z_]+)'/g)].map(match=>match[1]).sort();
  assert.deepEqual(tools,['commerce_memory_list','commerce_skills_cases','commerce_skills_status']);
  // Improvement candidates now have a recorded source (recurring failures); evaluation and rollback still do not.
  assert.match(source,/基线与候选评估、版本回滚目前没有记录来源/);
  assert.match(source,/改进候选来自真实运行中重复出现的失败/);
  assert.doesNotMatch(source,/idempotency_key/);
  const candidates=await readFile('src/improvement-candidates.tsx','utf8');
  assert.deepEqual([...candidates.matchAll(/'(commerce_[a-z_]+)'/g)].map(match=>match[1]),['commerce_operating_retrospect_get']);
  assert.doesNotMatch(candidates,/idempotency_key/);
  assert.match(candidates,/候选不会自动应用，也不会自动创建任务/);
});
