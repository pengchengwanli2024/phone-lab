import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {existsSync} from 'node:fs';
let key,selected;
if(existsSync('src/operating-alert-state.ts')){
  const result=await build({entryPoints:['src/operating-alert-state.ts'],bundle:true,write:false,format:'esm',platform:'node'});
  ({alertEvidenceKey:key,selectedAlertEvidence:selected}=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64')));
}
const alert={id:'same-id',title:'待备货',status:'active',severity:'P1',detail:'原记录',kind:'prepare',store_id:'store-a',sku:'sku-a',source_ref:'synthetic:order',source_sha256:'a'.repeat(64),observed_at:'2026-11-17T01:00:00Z',order_id:'order-a'};
test('alert inspection binds original namespace, mode, store scope and all displayed source fields',()=>{
  assert.equal(typeof key,'function');assert.equal(typeof selected,'function');
  const row={alert,live:false},selection=key(row,true,'store-a');
  assert.equal(selected([row],selection,true,'store-a'),row);
  assert.equal(selected([row],selection,false,'store-a'),null);
  assert.equal(selected([row],selection,true,'store-b'),null);
  assert.equal(selected([{...row,live:true}],selection,true,'store-a'),null);
  for(const field of ['id','source_sha256','observed_at','status','store_id','sku','source_ref','order_id','detail']){
    assert.equal(selected([{...row,alert:{...alert,[field]:'changed'}}],selection,true,'store-a'),null,field);
  }
  assert.equal(selected([],selection,true,'store-a'),null);
});
test('equal IDs from imported and platform alerts never select each other',()=>{
  const imported={alert,live:false},platform={alert:{...alert,source:'ozon_api'},live:true};
  assert.equal(selected([platform,imported],key(imported,false,'all'),false,'all'),imported);
  assert.equal(selected([imported,platform],key(platform,false,'all'),false,'all'),platform);
});
