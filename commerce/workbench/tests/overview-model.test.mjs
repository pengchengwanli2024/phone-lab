import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import vm from 'node:vm';
const compiled=await build({entryPoints:['src/overview-model.ts'],bundle:true,write:false,format:'cjs',platform:'node'});
const module={exports:{}};vm.runInNewContext(compiled.outputFiles[0].text,{module,exports:module.exports});
const {coreStages,salesSeries,salesPageContext,inventoryPageContext}=module.exports;
const plain=value=>JSON.parse(JSON.stringify(value));

test('chart views keep real platform days, zero and unit values without inventing missing days',()=>{
 const source={records:[{day:'2026-11-13',amount:'30.125',ordered_units:3},{day:'2026-11-15',amount:'0',ordered_units:0}]};
 assert.deepEqual(plain(salesSeries(source,'amount')),[{day:'2026-11-13',value:30.125},{day:'2026-11-15',value:0}]);
 assert.deepEqual(plain(salesSeries(source,'units')),[{day:'2026-11-13',value:3},{day:'2026-11-15',value:0}]);
 assert.deepEqual(plain(salesSeries(undefined,'amount')),[]);
});
test('product tracks use actual stage checks and keep unavailable, held and blocked distinct',()=>{
 const rows=coreStages({stages:[{id:'S1',name:'Original research check',status:'PASS'},{id:'S3',name:'Quote check',status:'HOLD'},{id:'S2',name:'Economics',status:'BLOCKED'},{id:'S4',name:'Media',status:'unexpected'}]});
 assert.deepEqual(plain(rows.map(row=>row.id)),['S1','S3','S2','S4','S5','S6']);
 assert.deepEqual(plain(rows.map(row=>row.label)),['检查通过','待补齐','受阻','状态待核对','待读取','待读取']);
 assert.equal(rows[0].detail,'Original research check');assert.ok(!rows.some(row=>row.label==='进行中'));
});

test('each chart selector publishes its own scope and freshness instead of inheriting another widget',()=>{
 const sales={stale:true,date_from:'2026-10-17',date_to:'2026-11-15',source_sha256:'a'.repeat(64),records:[]};
 const inventory={stale:false,source_sha256:'b'.repeat(64)};
 const first=salesPageContext(sales,'units'),second=inventoryPageContext(inventory);
 assert.equal(first.entity.id,'sales-ordered-units');assert.equal(first.filters.date_from,'2026-10-17');assert.equal(first.source,'stale');
 assert.equal(second.source,'live');assert.equal(second.filters.date_from,undefined);assert.deepEqual(Object.keys(second.source_refs),['stock']);
 assert.equal(inventoryPageContext(undefined).source,'unavailable');
});
