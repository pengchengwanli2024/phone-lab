import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import vm from 'node:vm';

const result=await build({entryPoints:['src/navigation.ts'],bundle:true,write:false,format:'cjs',platform:'node'});
const module={exports:{}};
vm.runInNewContext(result.outputFiles[0].text,{module,exports:module.exports});
test('the documented social hash still opens intelligence through the unified entry',()=>{
  assert.equal(module.exports.initialDestination(new URLSearchParams(), '#social'),'intelligence');
  assert.equal(module.exports.initialDestination(new URLSearchParams(), '#main-workspace'),'overview');
});
test('an explicit destination keeps precedence over a retained section hash',()=>{
  assert.equal(module.exports.initialDestination(new URLSearchParams('tab=orders'), '#social'),'orders');
  assert.equal(module.exports.initialDestination(new URLSearchParams('tab=intelligence'), '#social'),'intelligence');
});
