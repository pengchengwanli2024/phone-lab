import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';

const bundle=await build({entryPoints:['src/decision-checks-state.ts'],bundle:true,format:'cjs',write:false,platform:'node'});
const module={exports:{}};new Function('module','exports',bundle.outputFiles[0].text)(module,module.exports);
const s=module.exports;

test('each check maps to exactly one read-only decision tool',()=>{
  assert.deepEqual(Object.values(s.tools).sort(),['commerce_competitor_changes','commerce_demand_trend_assess','commerce_experiment_evaluate','commerce_selection_scorecard','commerce_shipment_reconcile']);
  assert.deepEqual(s.kinds,Object.keys(s.tools));
});
test('the page calls only those tools and never writes, creates tasks or calls a model',async()=>{
  const source=await readFile('src/decision-checks.tsx','utf8');
  const calls=[...source.matchAll(/api<[^>]*>\(([^,]+),/g)].map(m=>m[1].trim());
  assert.deepEqual(calls,['tools[current]']);
  assert.doesNotMatch(source,/commerce_task_create|commerce_copilot_send|_save'|_submit'|localStorage/);
  assert.match(source,/合成示例/);
});
test('tables parse comma, tab, quotes and CRLF; numbers stay numbers, blanks are omitted',()=>{
  assert.deepEqual(s.parseTable('a,b\r\n"x, ""y""",2\n\n'),[['a','b'],['x, "y"','2']]);
  assert.deepEqual(s.parseTable('a\tb\n1\t2'),[['a','b'],['1','2']]);
  assert.throws(()=>s.parseTable('a\n"open'),s.InputProblem);
  const rows=s.records('sku,source,source_kind,net_margin_pct,estimated_acos_pct\nA,s,MANUAL_QUOTE,30,\n',s.columns.scorecard,'候选');
  assert.deepEqual(rows,[{sku:'A',source:'s',source_kind:'MANUAL_QUOTE',net_margin_pct:30}]);
  assert.throws(()=>s.records('sku,colour\nA,red',s.columns.scorecard,'候选'),/未识别的列：colour/);
  assert.throws(()=>s.records('sku,sku\nA,B',s.columns.scorecard,'候选'),/重复/);
  assert.throws(()=>s.records('sku,net_margin_pct\nA,abc',s.columns.scorecard,'候选'),/第2行的 net_margin_pct 不是数字/);
  assert.throws(()=>s.records('sku\nA,B',s.columns.scorecard,'候选'),/列数多于表头/);
  assert.deepEqual(s.records('id,source_revoked\nr1,true\nr2,否',{text:['id'],number:[],flag:['source_revoked']},'x'),[{id:'r1',source_revoked:true},{id:'r2',source_revoked:false}]);
  assert.deepEqual(s.records('',s.columns.scorecard,'候选'),[]);
});
test('form inputs are built exactly and invalid entries are explained before any request',()=>{
  const shipment=s.buildInput('shipment',{...s.samples.shipment,claim_window_days:'120'});
  assert.deepEqual(shipment.shipment,{shipment_ref:'DEMO-SHIP',sku:'DEMO-A',expected_quantity:100,shipped_date:'2025-01-01'});
  assert.equal(shipment.proposed_claim_quantity,5);assert.equal(shipment.claim_window_days,120);assert.equal('in_transit_window_days' in shipment,false);
  assert.deepEqual(shipment.events[0],{event_type:'RECEIVED',quantity:90,event_date:'2025-01-12',source:'示例入库回执'});
  assert.deepEqual(shipment.claims,[]);
  const experiment=s.buildInput('experiment',{...s.samples.experiment,changed_variables:'主图、价格',external_interference:'大促\n\n断货',budget_cap:'100',budget_spent:'90'});
  assert.deepEqual(experiment.changed_variables,['主图','价格']);assert.deepEqual(experiment.external_interference,['大促','断货']);
  assert.equal(experiment.higher_is_better,true);assert.equal(experiment.budget_spent,90);
  assert.equal(s.buildInput('experiment',{...s.samples.experiment,higher_is_better:'false'}).higher_is_better,false);
  assert.throws(()=>s.buildInput('experiment',{...s.samples.experiment,budget_cap:'1'}),/同时填写/);
  assert.throws(()=>s.buildInput('experiment',{...s.samples.experiment,baseline_trials:'1.5'}),/非负整数/);
  assert.throws(()=>s.buildInput('experiment',{...s.samples.experiment,changed_variables:' '}),/改动的变量/);
  assert.throws(()=>s.buildInput('shipment',{...s.samples.shipment,sku:''}),/请填写SKU/);
  const demand=s.buildInput('demand',s.samples.demand);
  assert.equal(demand.months,12);assert.equal(demand.records.length,24);assert.equal(typeof demand.records[0].value,'number');
  assert.equal(s.buildInput('scorecard',s.samples.scorecard).candidates.length,4);
  assert.equal(s.buildInput('competitor',s.samples.competitor).snapshots[1].rank,12);
  assert.deepEqual(s.buildInput('scorecard',s.blank.scorecard),{candidates:[]});
});
test('backend error codes become specific Chinese messages; unknown codes fall through',()=>{
  assert.equal(s.problemText('decision_duplicate_sku'),'有重复的 SKU');
  assert.match(s.problemText('decision_invalid_net_margin_pct'),/^净毛利不符合要求/);
  assert.match(s.problemText('decision_invalid_baseline_trials'),/^基线样本数不符合要求/);
  assert.match(s.problemText('decision_invalid_unknownfield'),/^unknownfield/);
  assert.equal(s.problemText('request_failed'),'');
});
test('labels and tones keep status words consistent and never colour unknown as success',()=>{
  assert.equal(s.label('HOLD'),'待补依据');assert.equal(s.label('NEW_CODE'),'NEW_CODE');assert.equal(s.label(null),'—');
  assert.equal(s.tone('READY'),'success');assert.equal(s.tone('BLOCKED_EXCESS'),'danger');assert.equal(s.tone('UNKNOWN'),'gray');assert.equal(s.tone('HOLD'),'warning');
  assert.equal(s.tone('SOMETHING_NEW'),'warning');
});
