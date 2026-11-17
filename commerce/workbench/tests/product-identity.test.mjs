import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const context=vm.createContext({window:{}});vm.runInContext(fs.readFileSync(new URL('../../web/product-identity.js',import.meta.url),'utf8'),context);
const identity=context.window.CommerceProductIdentity;
test('same-name stock keeps FBS and RFBS visible and never drops an identity',()=>{
  const items=['FBS','RFBS'].map((fulfillment,index)=>({id:'case-'+index,name:'同名商品',scope:{sku:'SKU-A',platform:'ozon',market:'RU',fulfillment}}));
  assert.match(identity.label(items[0],items),/同名商品 \/ SKU-A · Ozon · RU · FBS/);
  assert.match(identity.label(items[1],items),/RFBS/);assert.equal(items.length,2);
});
test('missing SKU falls back to product name and a short id unique among peers',()=>{
  const items=['11111111aaaaaaaa','22222222aaaaaaaa'].map(id=>({id:'case_'+id,name:'厨房收纳',scope:{platform:'ozon',market:'RU',inventory_type:'candidate'}}));
  const labels=items.map(item=>identity.label(item,items));
  assert.match(labels[0],/^厨房收纳 · Ozon · RU · 履约未提供 · /);assert.notEqual(labels[0],labels[1]);
});
test('metadata joins by exact case id without joining or deleting matching names',()=>{
  const items=[{id:'one',name:'同名'},{id:'two',name:'同名'}];
  const merged=identity.merge(items,[{id:'two',scope:{sku:'SKU-TWO',fulfillment:'RFBS'}}]);
  assert.equal(merged.length,2);assert.equal(identity.scope(merged[0]).sku,undefined);assert.equal(identity.scope(merged[1]).sku,'SKU-TWO');assert.equal(items[1].scope,undefined);
});
test('full catalog detail and list projections use the same formatter',()=>{
  const scope={sku:'A',platform:'ozon',market:'RU',fulfillment:'FBS'};
  assert.equal(identity.label({id:'one',name:'商品',scope}),identity.label({id:'one',name:'商品',case:{id:'one',scope}}));
});
test('record inventory type distinguishes FBS/RFBS when the connection supports both',()=>{
  const item={id:'one',name:'同名',scope:{fulfillment:['fbs','rfbs'],inventory_type:'rfbs',platform:'ozon',market:'RU'}};
  assert.match(identity.meta(item),/ · RFBS$/);assert.doesNotMatch(identity.meta(item),/FBS \/ RFBS/);
});
