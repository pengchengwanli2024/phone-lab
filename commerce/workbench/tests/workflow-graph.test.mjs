import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const compiled=await build({entryPoints:['src/workflow-graph.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {connectionError,removeStep}=await import('data:text/javascript;base64,'+Buffer.from(compiled.outputFiles[0].text).toString('base64'));
const plan={goal:'synthetic',steps:[{id:'a',title:'A'},{id:'b',title:'B'},{id:'c',title:'C'}],graph:{edges:[{from:'a',to:'b'},{from:'b',to:'c'}],positions:{a:{x:1,y:1},b:{x:2,y:2},c:{x:3,y:3}}}};
test('connections reject cycles, duplicates, self links and missing nodes',()=>{assert.match(connectionError(plan,'c','a'),/循环/);assert.match(connectionError(plan,'a','b'),/存在/);assert.match(connectionError(plan,'a','a'),/自己/);assert.match(connectionError(plan,'a','other'),/有效/);assert.equal(connectionError(plan,'a','c'),'');});
test('removing a step removes its edges and position without mutating the original plan',()=>{const after=removeStep(plan,'b');assert.equal(after.steps.length,2);assert.equal(after.graph.edges.length,0);assert.equal(after.graph.positions.b,undefined);assert.equal(plan.steps.length,3);assert.equal(plan.graph.edges.length,2);});
