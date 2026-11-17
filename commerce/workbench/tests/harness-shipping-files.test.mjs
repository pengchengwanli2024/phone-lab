import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

function setup(){
  let definition;const refs=[],handlers=new Set(),registrations=new Map(),replies=[],revoked=[],saves=[];
  const React={useEffect:fn=>fn(),useState:value=>[value,()=>{}],useRef:value=>{const ref={current:value};refs.push(ref);return ref;},useCallback:fn=>fn,createElement:(type,props,...children)=>({type,props,children})};
  const window={__ModuleLoader__:{load:next=>definition=next},addEventListener:(_name,fn)=>handlers.add(fn),removeEventListener:(_name,fn)=>handlers.delete(fn),dispatchEvent(){}};
  const context={window,TextEncoder,TextDecoder,Blob,URL:{createObjectURL:()=> 'blob:native-host',revokeObjectURL:url=>revoked.push(url)},crypto:{randomUUID:()=> 'frame-nonce'},AbortController,MutationObserver:class{observe(){}disconnect(){}},document:{documentElement:{},body:{}},getComputedStyle:()=>({colorScheme:'light'}),fetch:async()=>({ok:true,text:async()=>'<html></html>'}),CustomEvent:class{},setTimeout,clearTimeout};
  vm.createContext(context);for(const file of ['../ui/shipping-files.js','../harness/client.js'])vm.runInContext(readFileSync(file,'utf8'),context);
  const ctx={fileActions:{save:async(source,mode)=>{saves.push({source,mode});return {status:'saved',path:'/synthetic/Downloads/packing.csv'};}},slots:{inject:(_name,fn)=>fn(),register:(config,component)=>{if(config.name==='main')registrations.set(config.key,component);}},effect:fn=>fn(),sidebarRightTabs:{register(){}},layout:{selectPanel(){}}};
  definition.factory(()=>React).apply(ctx);const main=registrations.get('commerce')(),page=main.children[0].children[0];refs.length=0;page.type(page.props);const frame={postMessage:value=>replies.push(value)};refs[0].current={contentWindow:frame};
  return {saves,replies,revoked,request:async(data,source=frame)=>{for(const fn of handlers)await fn({source,data});}};
}
const message={type:'commerce:shipping-file',nonce:'frame-nonce',id:'file-request',op:'download',args:{file:{content:'sku,quantity\r\nA,2\r\n',filename:'packing.csv',mime_type:'text/csv;charset=utf-8'}}};
test('Harness uses official native download and returns saved only after host receipt',async()=>{
  const h=setup();await h.request(message);
  assert.equal(h.saves.length,1);assert.equal(h.saves[0].mode,'download');assert.equal(h.saves[0].source.name,'packing.csv');assert.equal(h.saves[0].source.url,'blob:native-host');assert.deepEqual(h.revoked,['blob:native-host']);
  assert.equal(h.replies[0].result.status,'saved');assert.equal(h.replies[0].result.filename,'packing.csv');
});
test('Harness file bridge refuses foreign frames, nonces and path requests',async()=>{
  const h=setup();await h.request(message,{});await h.request({...message,nonce:'wrong'});assert.equal(h.saves.length,0);assert.equal(h.replies.length,0);
  await h.request({...message,args:{file:{...message.args.file,filename:'../unsafe.csv'}}});assert.equal(h.saves.length,0);assert.match(h.replies[0].error,/file/);
});
