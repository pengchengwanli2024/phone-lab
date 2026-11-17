import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
const compiled=await build({entryPoints:['src/listing-choice.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {listingChoices,listingChoiceLabel,listingStores,originalListingImage,listingImagePresentation,sourceField,sameListingTarget}=await import('data:text/javascript;base64,'+Buffer.from(compiled.outputFiles[0].text).toString('base64'));
const card=(id,connection='A')=>({id,name:'Product '+id,kind:'inventory',synthetic:false,source_sha256:'sha-'+id,sku:'SAME',product_key:connection+id,primary_case_id:id,case_ids:[id,id+'-rfbs'],inventory_scopes:[{case_id:id+'-rfbs',inventory_type:'rfbs'}],store_identity:{kind:'store',active:true,label:'Shop '+connection,connection_id:connection,platform:'ozon',store_ref:'store-'+connection,market:'RU'}});
test('canonical choices preserve same-SKU different products and stores without all fulfillment duplicates',()=>{
  const a=card('p1'),b=card('p2'),c=card('p3','B'),raw=[...a.case_ids,...b.case_ids,...c.case_ids].map(id=>({id,name:id,candidate:false,synthetic:false}));
  const choices=listingChoices([a,b,c],raw,false,'p1');assert.deepEqual(choices.map(x=>x.id),['p1','p2','p3']);assert.equal(new Set(choices.map(x=>x.sku)).size,1);
});
test('a deep-linked fulfillment case is retained only as an explicit alias with the canonical entry',()=>{
  const a=card('p1');const choices=listingChoices([a],[{id:'p1-rfbs',name:'Original inventory',candidate:false,synthetic:false}],false,'p1-rfbs');
  assert.equal(choices.length,2);assert.equal(choices[0].aliasOf,'p1');assert.match(listingChoiceLabel(choices[0]),/原履约范围 rfbs/);assert.match(listingChoiceLabel(choices[1]),/Shop A/);
});
test('same-name inventory options expose their distinct real SKU before a narrow select truncates the name',()=>{
  const base={id:'case-d',name:'Комплект: шапка и шарф',candidate:false,synthetic:false,store:{label:'Shop A'}};
  const d=listingChoiceLabel({...base,sku:'SYN01D'}),e=listingChoiceLabel({...base,id:'case-e',sku:'SYN01E'});
  assert.ok(d.startsWith('SKU SYN01D · '));assert.ok(e.startsWith('SKU SYN01E · '));assert.match(d,/Комплект: шапка и шарф/);assert.match(e,/Комплект: шапка и шарф/);
  assert.notEqual(d.slice(0,10),e.slice(0,10));assert.equal(base.id,'case-d');
});
test('candidate option labels distinguish a private lead identifier from a saleable SKU',()=>{
  const candidate={id:'exact-candidate-case',name:'Research pencil case',candidate:true,synthetic:false,sku:'CANDIDATE:source-123'};
  const label=listingChoiceLabel(candidate);assert.ok(label.startsWith('候选 · Research pencil case · 待建立SKU'));
  assert.match(label,/资料编号 CANDIDATE:source-123$/);assert.doesNotMatch(label,/^SKU /);assert.equal(candidate.id,'exact-candidate-case');assert.equal(candidate.sku,'CANDIDATE:source-123');
});
test('unavailable catalog does not expose every raw inventory scope as separate products or mix demo',()=>{
  const raw=[{id:'legacy',name:'Legacy',candidate:false,synthetic:false},{id:'other',name:'Other',candidate:false,synthetic:false},{id:'demo',name:'Demo',candidate:false,synthetic:true}];
  assert.deepEqual(listingChoices([],raw,false,'legacy').map(x=>x.id),['legacy']);assert.deepEqual(listingChoices([],raw,false,'demo'),[]);
});
test('store choices require actual active identities; an ambiguous reusable alias is excluded',()=>{
  const a=card('one'),b=card('two');assert.equal(listingStores([a,b],false).length,1);
  const inactive=card('inactive','B');inactive.store_identity.active=false;assert.equal(listingStores([a,inactive],false).length,1);
  const collision=card('collision','B');collision.store_identity.store_ref=a.store_identity.store_ref;assert.deepEqual(listingStores([a,collision],false),[]);
});
test('identity image selects only a current product original, never latest AI or layout output',()=>{
  const d={...card('p'),images:[{id:'ai',origin:'generated_image'},{id:'layout',origin:'image_layout_draft'},{id:'old',origin:'product_image',source_current:false},{id:'original',origin:'product_image',source_current:true}]};
  assert.equal(originalListingImage(d).image.id,'original');assert.equal(originalListingImage(d).index,3);
  assert.equal(originalListingImage({...d,images:d.images.slice(0,3)}),null);
});
test('source values preserve missing and zero; description uses only unambiguous simple original attribute',()=>{
  const d={...card('p'),price:0,currency:null,fields:[{key:'attributes',original:JSON.stringify([{id:4191,complex_id:'0',values:[{value:'Original description'}]}])}]};
  assert.equal(sourceField(d,'price'),0);assert.equal(sourceField(d,'currency'),null);assert.equal(sourceField(d,'quantity'),null);assert.equal(sourceField(d,'description'),'Original description');
  d.fields[0].original=JSON.stringify([{id:4191,complex_id:'1',values:[{value:'Complex value'}]}]);assert.equal(sourceField(d,'description'),null);
});
test('loaded target equality includes product, platform, store and market',()=>{
  const t={case_id:'p',platform:'ozon',store_ref:'shop',market:'RU'};assert.equal(sameListingTarget(t,{...t}),true);
  for(const key of Object.keys(t))assert.equal(sameListingTarget(t,{...t,[key]:'other'}),false);
});
const evidenceImage=(source_kind='competitor')=>({id:'reference-'+source_kind,origin:'product_evidence',source_kind,role:'original',reference_only:true,case_id:'p',entry_id:'entry',entry_sha256:'a'.repeat(64),image_index:0,media_id:'media',sha256:'b'.repeat(64),width:1000,height:1000});
test('candidate references prefer a scoped competitor original over supplier and never select generated evidence',()=>{
 const supplier=evidenceImage('supplier'),competitor=evidenceImage(),d={...card('p'),kind:'candidate',images:[{...competitor,id:'generated',role:'generated'},supplier,competitor]};
 assert.equal(originalListingImage(d).image.id,competitor.id);assert.equal(originalListingImage(d).index,2);
 assert.equal(originalListingImage({...d,images:[supplier]}).image.id,supplier.id);
 assert.equal(originalListingImage({...d,kind:'inventory'}),null);
 for(const changed of [{reference_only:false},{case_id:'other'},{entry_sha256:'invalid'},{image_index:-1},{media_id:''}])assert.equal(originalListingImage({...d,images:[{...competitor,...changed}]}),null);
});
test('reference labels preserve external ownership and mark small supplier thumbnails unsuitable for generation',()=>{
 const candidate={...card('p'),kind:'candidate'},supplier={...evidenceImage('supplier'),width:40,height:40};
 const info=listingImagePresentation(candidate,supplier);assert.equal(info.label,'货源参考图');assert.equal(info.thumbnail,true);assert.match(info.hint,/非自有实物/);assert.match(info.hint,/不可作生图依据/);assert.match(info.hint,/40 × 40/);
 assert.equal(listingImagePresentation(candidate,evidenceImage()).label,'竞品参考图');assert.equal(listingImagePresentation(card('p'),supplier).label,'原始图库预览');
});
