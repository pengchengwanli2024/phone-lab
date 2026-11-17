import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const context=vm.createContext({window:{CommerceUI:{escape:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}}});
vm.runInContext(fs.readFileSync(new URL('../../web/catalog-presentation.js',import.meta.url),'utf8'),context);
const p=context.window.CommerceCatalogPresentation;
test('platform HTML becomes readable inert text without changing source data',()=>{
  const original='<b>Набор</b><br/>Описание &amp; детали<script>window.evil=1</script>';
  const result=p.field({key:'description',original});
  assert.ok(result.includes('Набор\nОписание &amp; детали'));
  assert.ok(!result.includes('<script>'));assert.ok(result.includes('&lt;script&gt;'));
  assert.ok(result.includes('查看原始字段'));assert.equal(context.window.evil,undefined);
});
test('attribute arrays display values and keep exact originals behind disclosure',()=>{
  const original=JSON.stringify([{id:'85',values:[{value:'Нет бренда',dictionary_value_id:126745801}]},{id:'4191',values:[{value:'<b>Описание</b><br>Текст'}]}]);
  const html=p.field({key:'attributes',original});
  assert.match(html,/平台属性 85/);assert.match(html,/Нет бренда/);assert.match(html,/Описание\nТекст/);
  assert.ok(html.indexOf('dictionary_value_id')>html.indexOf('<details class="catalog-original">'));
  assert.equal(JSON.parse(original)[1].values[0].value,'<b>Описание</b><br>Текст');
});
test('dimensions keep the reported unit and raw zero rather than guessing conversion',()=>{
  const rows=p.readable('{"width":0,"height":100,"dimension_unit":"mm"}','dimensions');
  assert.equal(rows.find(r=>r.label==='宽度').value,'0');assert.equal(rows.find(r=>r.label==='尺寸单位').value,'mm');
  assert.equal(p.readable('malformed {','dimensions'),null);
});
test('unknown store and research candidate stay distinct from a named account',()=>{
  assert.equal(p.storeLabel({kind:'candidate'}),'调研候选 · 尚未绑定店铺');
  assert.equal(p.storeLabel({kind:'inventory'}),'店铺身份待核对');
  assert.equal(p.storeLabel({store_identity:{label:'Local Store'}}),'Local Store');
  assert.equal(p.scopes({inventory_scopes:[{inventory_type:'fbs'},{inventory_type:'rfbs'},{inventory_type:'fbs'}]}),'FBS / realFBS');
});
