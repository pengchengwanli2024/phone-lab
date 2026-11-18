import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['src/improvement-candidates-state.ts'],bundle:true,format:'cjs',write:false,platform:'node'});
const module={exports:{}};new Function('module','exports',bundle.outputFiles[0].text)(module,module.exports);
const {candidateSummary,domainName,fixName}=module.exports;

test('summary states the window, what repeated, and what was left out',()=>{
  assert.equal(candidateSummary({window_days:7,candidates:[],single_incidents:0,uncoded_failures:{}}),'最近 7 天 · 没有重复出现的失败');
  const text=candidateSummary({window_days:30,candidates:[{},{}],single_incidents:3,uncoded_failures:{model_request:2,extension:1}});
  assert.equal(text,'最近 30 天 · 2 类失败重复出现 · 3 类只出现一次，未列为候选 · 3 次失败没有可归类的原因码');
});
test('domains and fix directions use plain words; unknown values stay readable',()=>{
  assert.equal(domainName('store_read'),'店铺读取');assert.equal(domainName('new_domain'),'new_domain');
  assert.equal(fixName('connector'),'先改连接器');assert.equal(fixName('recovery'),'先补核对入口');assert.equal(fixName('something_else'),'先补检查');
});
test('the panel says who must act and never implies automatic engineering work',()=>{
  const {handlingText}=module.exports;
  const base={window_days:7,single_incidents:0,uncoded_failures:{}};
  assert.equal(handlingText({...base,candidates:[]}),'');
  const open=handlingText({...base,candidates:[{}],engineering:{uncovered_domains:['store_read','model_request']}});
  assert.match(open,/需要由人安排修复/);assert.match(open,/店铺读取、模型请求/);assert.doesNotMatch(open,/已有工程配方/);
  const mixed=handlingText({...base,candidates:[{engineering_feature:'ozon-read-backoff'},{}],engineering:{covered_candidates:['a'],uncovered_domains:['model_request']}});
  assert.match(mixed,/1 项已有工程配方/);assert.match(mixed,/不会自动发起/);assert.match(mixed,/模型请求/);
  const all=handlingText({...base,candidates:[{engineering_feature:'x'}],engineering:{covered_candidates:['a'],uncovered_domains:[]}});
  assert.match(all,/由人明确发起/);assert.doesNotMatch(all,/需要由人安排修复/);
});
