import {test} from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import vm from 'node:vm';

const result=await build({entryPoints:['src/navigation.ts'],bundle:true,write:false,format:'cjs',platform:'node'});
const module={exports:{}};vm.runInNewContext(result.outputFiles[0].text,{module,exports:module.exports});
const routes=module.exports;

const surfaces={
  overview:['overview'],
  workspace:['pipeline','pilots','research','insights','decisions','workspace','operations','workflow','creative','listing'],
  'store-ops':['store-ops','alerts','orders','order-imports','support','products','restock','platforms','live'],
  tasks:['tasks','organization','agent','operating-control','assistant-team'],
  intelligence:['intelligence','exposure'],
  skills:['skills','tools','models','connections','memory','phones'],
};
test('six work surfaces group every retained route exactly once',()=>{
  assert.equal(JSON.stringify(routes.navigation.map(item=>[item.id,item.label])),JSON.stringify([['overview','运营台'],['workspace','商品管线'],['store-ops','店铺运营'],['tasks','智能体团队'],['intelligence','情报'],['skills','系统']]));
  for(const [id,items]of Object.entries(surfaces)){
    assert.equal(JSON.stringify(routes.destinationFor(id).items),JSON.stringify(items),id);
    for(const route of items){assert.equal(routes.destinationFor(route)?.id,id,route);assert.equal(routes.destinationFor('old:'+route)?.id,id,route);}
  }
  const all=routes.navigation.flatMap(item=>[...item.items]);
  assert.equal(new Set(all).size,all.length);
  for(const item of routes.navigation)assert.ok(item.items.includes(item.id),'selecting '+item.label+' opens one of its own pages');
  for(const route of all)assert.ok(routes.labels[route],route+' has a label');
});
test('sections cover their surface once and never cross into another',()=>{
  for(const item of routes.navigation){
    if(!item.sections){assert.ok(['overview','intelligence','skills'].includes(item.id));continue;}
    const covered=item.sections.flatMap(section=>[...section.primary,...section.secondary]);
    assert.equal(JSON.stringify(covered),JSON.stringify(item.items),item.id);
    for(const section of item.sections){assert.ok(covered.includes(section.defaultRoute));for(const route of [...section.primary,...section.secondary])assert.equal(routes.sectionFor('old:'+route).id,section.id);}
  }
  assert.equal(routes.storeSections.length,4);
  assert.equal(routes.storeSectionFor('orders').id,'fulfillment');
  // Product preparation left daily store operations; automation left settings.
  assert.equal(routes.storeSectionFor('workspace'),undefined);assert.equal(routes.sectionFor('workspace').id,'product');
  assert.equal(routes.sectionFor('creative').id,'launch');assert.equal(routes.sectionFor('operating-control').id,'autonomy');
  assert.equal(routes.sectionFor('overview'),undefined);
});
test('route grouping preserves conversation scopes and deep product links',()=>{
  const modules={workspace:'organization',listing:'organization',workflow:'organization',operations:'operations',restock:'operations',orders:'orders','order-imports':'orders',products:'products',alerts:'alerts',creative:'creative'};
  for(const [route,expected]of Object.entries(modules))assert.equal(routes.businessModule(route),expected);
  assert.equal(routes.initialDestination(new URLSearchParams('tab=workspace&case_id=exact-case')),'workspace');
  assert.equal(routes.conversationDestination({module:'organization',entity:{kind:'case',id:'exact-case'}},{page:'workspace'}),'workspace');
  assert.equal(routes.conversationDestination({module:'operations'},{page:'restock'}),'restock');
});
