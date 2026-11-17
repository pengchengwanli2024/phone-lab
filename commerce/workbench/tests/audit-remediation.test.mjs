import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import vm from 'node:vm';
async function compile(entry){const result=await build({entryPoints:[entry],bundle:true,write:false,format:'cjs',platform:'node',external:['react'],loader:{'.css':'empty'}});const module={exports:{}};vm.runInNewContext(result.outputFiles[0].text,{module,exports:module.exports,require:createRequire(import.meta.url),window:{}});return module.exports;}
const {campaignInput}=await compile('src/campaign-scenarios.tsx');
const values={currency:'CNY',commission_rate:'10',purchase_cost:'20'};
const plan={name:' A ',price:'100',merchant_discount:'10',ad_cost_per_unit:'0',affiliate_rate:'5'};
test('pricing comparison reuses the exact current cost inputs and percent contract',()=>{
  const result=campaignInput(values,[plan],'15','unknown');
  assert.equal(result.base.commission_rate,.1);assert.equal(result.plans[0].affiliate_rate,.05);
  assert.equal(result.base.purchase_cost,20);assert.equal(result.plans[0].ad_cost_per_unit,0);
  assert.equal('return_rate' in result.base,false,'unfilled cost remains unknown');
  assert.equal(result.plans[0].name,'A');assert.equal(result.inventory_state,'unknown');
  assert.deepEqual(values,{currency:'CNY',commission_rate:'10',purchase_cost:'20'});
});
test('comparison rejects missing scenario costs, impossible discounts and rates above 100%',()=>{
  for(const change of [{ad_cost_per_unit:''},{affiliate_rate:'101'},{merchant_discount:'100'},{name:' '}])assert.throws(()=>campaignInput(values,[{...plan,...change}],'15','unknown'));
  assert.throws(()=>campaignInput(values,[plan],'','unknown'));
  assert.equal(campaignInput(values,[{...plan,affiliate_rate:'100'}],'0','tight').plans[0].affiliate_rate,1);
});
const {executionTime}=await compile('src/execution-directory.tsx');
test('execution metadata preserves missing time and accepts original epoch or ISO',()=>{
  assert.equal(executionTime(), '时间未记录');assert.equal(executionTime('invalid'),'时间未记录');
  assert.equal(executionTime(1700000000),executionTime('2023-11-14T22:13:20Z'));
});
