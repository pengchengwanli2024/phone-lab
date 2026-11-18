import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['src/operating-health-state.ts'],bundle:true,format:'cjs',write:false,platform:'node'});
const module={exports:{}};new Function('module','exports',bundle.outputFiles[0].text)(module,module.exports);
const {healthStatus,sortedChecks,checkAction,healthSummary}=module.exports;
const check=(id,status,target='connections')=>({id,status,label:id,detail:'',target});

test('problems are listed first and unknown is never shown as normal',()=>{
  const order=sortedChecks([check('a','ok'),check('b','unknown'),check('c','warning'),check('d','critical'),check('e','new_state')]).map(c=>c.id);
  assert.deepEqual(order,['d','c','b','e','a']);
  assert.deepEqual(healthStatus('unknown'),{label:'未读到',tone:'gray'});assert.deepEqual(healthStatus('critical'),{label:'故障',tone:'danger'});
  assert.deepEqual(healthStatus('something'),{label:'状态待核对',tone:'gray'});
});
test('only a check needing attention offers a known destination',()=>{
  assert.equal(checkAction(check('a','ok','tasks')),null);
  assert.deepEqual(checkAction(check('a','warning','tasks')),{tab:'tasks',label:'去任务中心'});
  assert.deepEqual(checkAction(check('a','unknown','platforms')),{tab:'platforms',label:'查看店铺数据'});
  assert.equal(checkAction(check('a','critical','somewhere_else')),null);
});
test('summary counts open and unread checks and states the local-machine dependency',()=>{
  const base={status:'ok',checked_at:1,auto_backup:false,auto_backup_count:0};
  assert.equal(healthSummary({...base,checks:[check('a','ok')]}),'各项检查正常 · 依赖本机保持登录和不休眠');
  assert.equal(healthSummary({...base,checks:[check('a','critical'),check('b','warning'),check('c','unknown'),check('d','ok')]}),'2 项需要处理 · 1 项未读到 · 依赖本机保持登录和不休眠');
});
