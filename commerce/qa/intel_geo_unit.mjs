import test from 'node:test';
import assert from 'node:assert/strict';
import {altitudeForZoom,zoomForAltitude,viewBounds,clusterRows,normalizeRows,shortLongitude,retainedUpdate} from '../workbench/map/model.mjs';

test('map and globe share a reversible geographic scale and shortest date-line rotation',()=>{
  for(const zoom of [1,2.5,4,7])assert.ok(Math.abs(zoomForAltitude(altitudeForZoom(zoom))-zoom)<1e-8);
  assert.equal(shortLongitude(179,-179),181);
  assert.equal(shortLongitude(-179,179),-181);
});
test('focused geographic bounds wrap the date line and stay inside the poles',()=>{
  const b=viewBounds({lng:179,lat:80,zoom:4},2);
  assert.ok(b.west>b.east);assert.equal(b.north,90);assert.ok(b.south>=-90);
  assert.deepEqual(viewBounds({lng:80,lat:20,zoom:1},2),{west:-180,east:180,south:-90,north:90});
});
test('invalid positions never enter the renderer and observation times remain source facts',()=>{
  const rows=normalizeRows([{id:'a',kind:'flight',location:{lat:30,lon:120},observed_at:12},{id:'b',location:{lat:91,lon:0}},{id:'c',location:{lat:0,lon:NaN}}]);
  assert.equal(rows.length,1);assert.equal(rows[0].observed_at,12);assert.equal(rows[0].location.lon,120);
});
test('low zoom aggregates every observation without mixing aircraft and events',()=>{
  const rows=normalizeRows([{id:'a',kind:'flight',location:{lat:30,lon:120}},{id:'b',kind:'flight',location:{lat:30.1,lon:120.1}},{id:'c',kind:'event',location:{lat:30,lon:120}}]);
  const clusters=clusterRows(rows,1);assert.equal(clusters.length,2);
  assert.equal(clusters.reduce((n,r)=>n+(r.children?.length||1),0),3);
  assert.equal(clusterRows(rows,6).length,3);
});
test('repainting a panel keeps the existing geographic data object when observations are unchanged',()=>{
  const rows=normalizeRows([{id:'a',kind:'flight',location:{lat:30,lon:120},observed_at:12}]);
  const original=retainedUpdate(null,rows);const same=retainedUpdate(original,structuredClone(rows));
  assert.equal(same,original);
  assert.notEqual(retainedUpdate(original,[{...rows[0],observed_at:13}]),original);
  assert.notEqual(retainedUpdate(original,[{...rows[0],altitude_m:11000}]),original);
});

test('resuming an idle globe cannot recursively start another loop through a synchronous control change',async()=>{
 const {animationGate}=await import('../workbench/map/model.mjs');let starts=0,stops=0;
 const gate=animationGate(()=>{starts++;gate.start()},()=>stops++);
 gate.start();gate.start();assert.equal(starts,1);gate.stop();gate.stop();assert.equal(stops,1);
 gate.start();assert.equal(starts,2);gate.stop();assert.equal(stops,2);
});
