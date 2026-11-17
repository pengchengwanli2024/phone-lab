import {test} from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
const location=new URL('../../harness/invoke-body.js',import.meta.url);
const parseBody=existsSync(location)?(await import(location.href)).parseInvokeBody:undefined;
test('Harness accepts a real shipping CSV beyond the legacy body limit',()=>{
  assert.equal(typeof parseBody,'function');
  const data=parseBody(JSON.stringify({tool:'commerce_shipping_rates_preview',arguments:{content:'渠道,'.repeat(35000),source_ref:'synthetic.csv'}}));
  assert.equal(data.tool,'commerce_shipping_rates_preview');assert.equal(data.arguments.content.length,105000);
});
test('Harness keeps unrelated tools bounded by UTF8 bytes',()=>{
  assert.equal(typeof parseBody,'function');
  assert.throws(()=>parseBody(JSON.stringify({tool:'commerce_status',arguments:{pad:'中'.repeat(50000)}})),error=>error.status===413&&error.message==='request_too_large');
  assert.throws(()=>parseBody(JSON.stringify({tool:'commerce_shipping_rates_preview',arguments:{content:'x'.repeat(1572864)}})),error=>error.status===413);
});
test('Harness rejects nonobject invoke requests before proxying',()=>{
  assert.equal(typeof parseBody,'function');
  for(const body of ['null','[]','1','{'])assert.throws(()=>parseBody(body),error=>error.status===400);
});
test('Harness accepts the same large comparison snapshot without widening other tools',()=>{
  const input={items:[{sku:'合成'.repeat(35000)}]};
  const data=parseBody(JSON.stringify({tool:'commerce_shipping_compare',arguments:{input}}));
  assert.equal(data.arguments.input.items[0].sku.length,70000);
});
