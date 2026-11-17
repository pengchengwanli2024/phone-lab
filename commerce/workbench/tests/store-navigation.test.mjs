import {test} from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import vm from 'node:vm';

const result=await build({entryPoints:['src/navigation.ts'],bundle:true,write:false,format:'cjs',platform:'node'});
const module={exports:{}};vm.runInNewContext(result.outputFiles[0].text,{module,exports:module.exports});
const routes=module.exports;

test('product, listing and operations pages share the store destination',()=>{
  for(const route of ['workspace','pilots','research','insights','operations','workflow','listing','store-ops','orders','order-imports','products','restock','support','alerts','live','platforms']){
    assert.equal(routes.destinationFor(route)?.id,'store-ops',route);
    assert.equal(routes.destinationFor('old:'+route)?.label,'店铺管理',route);
  }
  assert.equal(routes.navigation.some(item=>item.id==='workspace'),false);
});
test('five workflow sections cover each retained store route once',()=>{
  assert.equal(routes.storeSections.length,5);
  const covered=routes.storeSections.flatMap(section=>[...section.primary,...section.secondary]);
  assert.equal(new Set(covered).size,covered.length);
  assert.deepEqual([...covered].sort(),[...routes.destinationFor('workspace').items].sort());
  for(const route of covered)assert.ok(routes.storeSectionFor(route),route);
  assert.equal(routes.storeSectionFor('overview'),undefined);
});
test('route grouping preserves conversation scopes and deep product links',()=>{
  const modules={workspace:'organization',listing:'organization',workflow:'organization',operations:'operations',restock:'operations',orders:'orders','order-imports':'orders',products:'products',alerts:'alerts',creative:'creative'};
  for(const [route,expected]of Object.entries(modules))assert.equal(routes.businessModule(route),expected);
  assert.equal(routes.initialDestination(new URLSearchParams('tab=workspace&case_id=exact-case')),'workspace');
  assert.equal(routes.conversationDestination({module:'organization',entity:{kind:'case',id:'exact-case'}},{page:'workspace'}),'workspace');
  assert.equal(routes.conversationDestination({module:'operations'},{page:'restock'}),'restock');
});
