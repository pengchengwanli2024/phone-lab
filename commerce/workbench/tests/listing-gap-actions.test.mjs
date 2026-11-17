import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {existsSync} from 'node:fs';
let gapFields;
if(existsSync('src/listing-gap-actions.ts')){
  const compiled=await build({entryPoints:['src/listing-gap-actions.ts'],bundle:true,write:false,format:'esm',platform:'node'});
  ({gapFields}=await import('data:text/javascript;base64,'+Buffer.from(compiled.outputFiles[0].text).toString('base64')));
}
const fields={sku:'sku',title:'真实标题',description:'说明',category_id:'10',price:'100',currency:'CNY',quantity:0,image_refs:['https://example.com/a.png']};
const payload={fields,language:'ru',fulfillment:'FBS',rules_ref:'source:rules',attributes:[{name:'材质',value:'ABS',source_ref:'source:material'}]};
function gaps(id,changes={},target={store_ref:'ozon-live',market:'RU'},invalid=[]){assert.equal(typeof gapFields,'function','missing checks must resolve the exact editable fields');return gapFields(id,{...payload,...changes},target,invalid);}
test('filled price and zero quantity are preserved; only missing quantity or currency gets focus',()=>{
  assert.deepEqual(gaps('offer'),[]);assert.equal(gaps('offer',{fields:{...fields,quantity:null}})[0].id,'listing-field-quantity');assert.equal(gaps('offer',{fields:{...fields,currency:''}})[0].id,'listing-field-currency');
});
test('content, locale, identity and media actions locate actual gaps instead of their first filled field',()=>{
  assert.equal(gaps('content',{fields:{...fields,category_id:''}})[0].id,'listing-field-category_id');assert.equal(gaps('locale',{fulfillment:''})[0].id,'listing-fulfillment');assert.equal(gaps('identity',{}, {store_ref:'ozon-live',market:''})[0].id,'listing-market');assert.equal(gaps('media',{fields:{...fields,image_refs:[]}})[0].id,'listing-field-image_refs');assert.deepEqual(gaps('media'),[]);
});
test('attribute references and sanitized invalid fields retain their exact field identity',()=>{
  assert.equal(gaps('attributes',{attributes:[payload.attributes[0],{name:'重量',value:'',source_ref:''}]})[0].id,'listing-attribute-1-value');assert.equal(gaps('source_fields',{},undefined,['image_refs','price'])[0].id,'listing-field-image_refs');assert.deepEqual(gaps('source_fields',{},undefined,['__proto__']),[]);
});
test('navigation metadata never interprets approvals, schema or adapter as editable product fields',()=>{
  for(const id of ['professional_gate','platform_schema','platform_adapter','source','arbitrary'])assert.deepEqual(gaps(id),[]);
});
