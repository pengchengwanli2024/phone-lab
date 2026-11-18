import test from 'node:test';
import assert from 'node:assert/strict';
import {packDocument} from '../embed.mjs';
import {registerHooks} from 'node:module';

registerHooks({resolve(specifier,context,nextResolve){
  if(specifier==='./embedded-document'&&context.parentURL?.endsWith('/src/embedded-asset-bridge.ts'))return nextResolve('./embedded-document.ts',context);
  return nextResolve(specifier,context);
}});

async function implementation(){
  const module=await import('../src/embedded-asset-bridge.ts');
  assert.equal(typeof module.handleEmbeddedAsset,'function','the embedded map needs a scoped asset bridge');
  return module.handleEmbeddedAsset;
}

test('map assets require the exact iframe source, nonce, asset and bounded request identity',async()=>{
  const handle=await implementation(),messages=[],source={postMessage:message=>messages.push(message)};
  const scope={source,nonce:'nested-nonce',alive:()=>true};
  const request={type:'commerce:embedded-asset',nonce:'nested-nonce',asset:'intel-map',id:'map-request-1'};
  await handle({source:{},data:request},scope);
  await handle({source,data:{...request,nonce:'wrong'}},scope);
  assert.equal(messages.length,0);
  await handle({source,data:{...request,asset:'arbitrary-script'}},scope);
  assert.equal(messages.length,1);assert.equal(messages[0].error,'embedded_asset_denied');assert.equal(messages[0].script,undefined);
  await handle({source,data:{...request,id:'x'.repeat(161)}},scope);
  assert.equal(messages.length,1);
});

test('a pending asset cannot reply to an iframe replaced while the map tail arrives',async()=>{
  const handle=await implementation(),oldDocument=globalThis.document,oldObserver=globalThis.MutationObserver;
  const script='window.mapAssetSynthetic=true;',packed=packDocument(script);let complete=false,changed,alive=true;const messages=[],source={postMessage:m=>messages.push(m)};
  globalThis.document={readyState:'loading',documentElement:{},getElementById:id=>id==='commerce-embedded-intel-map'?{textContent:packed}:id==='commerce-embedded-intel-map-complete'&&complete?{}:null,addEventListener(){},removeEventListener(){}};
  globalThis.MutationObserver=class{constructor(callback){changed=callback;}observe(){}disconnect(){}};
  try{
    const pending=handle({source,data:{type:'commerce:embedded-asset',asset:'intel-map',id:'map-pending-1',nonce:'nested-nonce'}},{source,nonce:'nested-nonce',alive:()=>alive});
    await Promise.resolve();alive=false;complete=true;changed();await pending;assert.deepEqual(messages,[]);
    await handle({source,data:{type:'commerce:embedded-asset',asset:'intel-map',id:'map-current-1',nonce:'new-nonce'}},{source,nonce:'new-nonce',alive:()=>true});
    assert.equal(messages.length,1);assert.equal(messages[0].script,script);assert.equal(messages[0].nonce,'new-nonce');assert.equal(messages[0].id,'map-current-1');
  }finally{globalThis.document=oldDocument;globalThis.MutationObserver=oldObserver;}
});
