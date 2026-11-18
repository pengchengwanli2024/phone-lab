import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';

const data=JSON.parse(await readFile(new URL('../map/countries.generated.json',import.meta.url),'utf8'));
const numbers=[];const walk=value=>{if(typeof value==='number')numbers.push(value);else if(value&&typeof value==='object')for(const item of Object.values(value))walk(item);};
walk(data);

test('country outlines are stored at the precision of their 1:110m source',()=>{
  assert.ok(numbers.length>10000,'outline data is present');
  for(const value of numbers)assert.equal(value,Math.round(value*1e4)/1e4);
});
test('every country keeps a name, Chinese label, centroid and a closed outline',()=>{
  assert.ok(data.features.length>=170);
  for(const country of data.features){
    const {name,zh,lng,lat,area}=country.properties;
    assert.ok(name&&zh,'named');assert.ok(Math.abs(lng)<=180&&Math.abs(lat)<=90,name);assert.ok(area>=0,name);
    const rings=country.geometry.type==='Polygon'?country.geometry.coordinates:country.geometry.coordinates.flat();
    for(const ring of rings){assert.ok(ring.length>=4,name);assert.deepEqual(ring[0],ring.at(-1),name+' ring closed');}
  }
});
