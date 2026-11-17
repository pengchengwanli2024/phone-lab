import {test} from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import vm from 'node:vm';

const result=await build({entryPoints:['src/module-navigation-layout.ts'],bundle:true,write:false,format:'cjs',platform:'node'});
const module={exports:{}};vm.runInNewContext(result.outputFiles[0].text,{module,exports:module.exports});
const fit=(...args)=>Array.from(module.exports.visibleModuleLinks(...args));

test('a roomy module row retains every destination in its original order',()=>{
 assert.deepEqual(fit([60,110,90,110,90],600,2),[0,1,2,3,4]);
});
test('a narrow row keeps the active destination and leaves room for More',()=>{
 assert.deepEqual(fit([60,110,90,110,90],290,4),[0,4]);
 assert.deepEqual(fit([60,110,90,110,90],290,0),[0,1]);
});
test('a label wider than the row stays selected while all other destinations remain in More',()=>{
 assert.deepEqual(fit([70,900,80],180,1),[1]);
 assert.deepEqual(fit([70,900,80],0,1),[1]);
});
test('the exact fit does not reserve a redundant overflow trigger',()=>{
 assert.deepEqual(fit([70,80,90],248,1),[0,1,2]);
 assert.deepEqual(fit([],248,0),[]);
});
