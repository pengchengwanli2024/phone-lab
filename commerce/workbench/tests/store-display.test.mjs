import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import path from 'node:path';
import vm from 'node:vm';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['src/store-display.ts'],bundle:true,format:'cjs',write:false,platform:'node'});
const module={exports:{}};new Function('require','module','exports',bundle.outputFiles[0].text)(createRequire(path.resolve('package.json')),module,module.exports);
const {internalSku,skuText,storeName,scopeName,platformName}=module.exports;
const source=(id,kind,label,platform='ozon',market='RU')=>({id,kind,label,platform,market,sha256:id,revision:0,linked_to:id,link_current:true,linked:false});
const catalog=(sources,mapping,stores)=>({demo:false,sha256:'x',complete:true,unavailable:[],sources,mapping,stores});

test('an internal candidate key is shown as a record number and never as a store SKU',()=>{
  assert.equal(internalSku('CANDIDATE:source-1'),true);assert.equal(internalSku('candidate_abc'),true);
  assert.equal(internalSku('CAND-01'),false);assert.equal(internalSku('SKU-CANDIDATE:1'),false);assert.equal(internalSku(''),false);assert.equal(internalSku(null),false);
  assert.equal(skuText('CANDIDATE:source-1'),'待建立 SKU · 资料编号 CANDIDATE:source-1');
  assert.equal(skuText(' A-1 '),'SKU A-1');assert.equal(skuText(''),'');assert.equal(skuText(undefined),'');
});
test('a store reference gains a readable name only from its own store view and stays visible',()=>{
  const target={platform:'ozon',store_ref:'ozon-live',market:'RU'};
  assert.equal(storeName(target),'ozon-live');assert.equal(storeName({...target,store_ref:''}),'店铺待核对');
  const live=source('live-1','live','彭城俄罗斯店'),listing=source('listing-1','listing','ozon-live');
  assert.equal(storeName(target,catalog([live,listing],{'live-1':'live-1','listing-1':'listing-1'},[{id:'live-1',label:'彭城俄罗斯店',platform:'ozon',market:'RU',source_ids:['live-1']},{id:'listing-1',label:'ozon-live',platform:'ozon',market:'RU',source_ids:['listing-1']}])),'彭城俄罗斯店（ozon-live）');
  const custom={platform:'ozon',store_ref:'shop-b',market:'RU'},saved=source('listing-2','listing','shop-b'),named=source('platform-2','platform','二号店');
  const linked=catalog([saved,named],{'listing-2':'platform-2','platform-2':'platform-2'},[{id:'platform-2',label:'二号店',platform:'ozon',market:'RU',source_ids:['platform-2','listing-2']}]);
  assert.equal(storeName(custom,linked),'二号店（shop-b）');
  const apart=catalog([saved,named],{'listing-2':'listing-2','platform-2':'platform-2'},[{id:'listing-2',label:'shop-b',platform:'ozon',market:'RU',source_ids:['listing-2']},{id:'platform-2',label:'二号店',platform:'ozon',market:'RU',source_ids:['platform-2']}]);
  assert.equal(storeName(custom,apart),'shop-b');
  assert.equal(storeName({...custom,market:'KZ'},linked),'shop-b');
  assert.equal(storeName({platform:'tiktok',store_ref:'ozon-live',market:'RU'},catalog([live],{'live-1':'live-1'},[])),'ozon-live');
  assert.equal(storeName(target,catalog([live,source('live-2','live','另一店')],{},[])),'ozon-live');
});
test('alert store names come from the projected store view; platform names are readable',()=>{
  const value=catalog([],{},[{id:'view-1',label:'彭城俄罗斯店',platform:'ozon',market:'RU',source_ids:[]}]);
  assert.equal(scopeName('ozon-live','view-1',value),'彭城俄罗斯店（ozon-live）');assert.equal(scopeName('ozon-live',null,value),'ozon-live');
  assert.equal(scopeName('ozon-live','missing',value),'ozon-live');assert.equal(scopeName(undefined,undefined,value),'');
  assert.equal(platformName('ozon'),'Ozon');assert.equal(platformName('newshop'),'newshop');assert.equal(platformName(''),'平台待核对');
});
test('legacy product labels keep the candidate key out of the SKU position',async()=>{
  const window={};vm.runInNewContext(await readFile('../web/product-identity.js','utf8'),{window});
  const identity=window.CommerceProductIdentity,scope={sku:'CANDIDATE:k1',platform:'ozon',market:'RU',inventory_type:'candidate',origin:'research_candidate_not_inventory',label:'笔袋'};
  const label=identity.label({id:'case_abcdef123456',name:'笔袋',scope});
  assert.doesNotMatch(label,/CANDIDATE/);assert.equal(label,'笔袋 · Ozon · RU · 履约未提供 · 调研候选 · ef123456');
  assert.equal(identity.skuText('CANDIDATE:k1'),'待建立 SKU · 资料编号 CANDIDATE:k1');assert.equal(identity.skuText('A-1'),'SKU · A-1');
  assert.match(identity.label({id:'one',name:'商品',scope:{sku:'A-1',platform:'ozon',market:'RU',fulfillment:'FBS'}}),/^商品 \/ A-1 · Ozon · RU · FBS$/);
});
