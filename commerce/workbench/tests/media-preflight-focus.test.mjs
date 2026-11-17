import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const kit=await readFile(new URL('../../ui/kit.js',import.meta.url),'utf8');
const source=await readFile(new URL('../../web/media-workflow-ui.js',import.meta.url),'utf8');

async function fixture(){
 const listeners={},body={},document={body,documentElement:{dataset:{},getAttribute(){return'light'},setAttribute(){}},activeElement:body,
  addEventListener(name,fn){(listeners[name]||=new Set()).add(fn)},removeEventListener(name,fn){listeners[name]?.delete(fn)},querySelector(){return replacement}};
 const replacement={focus(){document.activeElement=replacement}};
 const button={dataset:{mediaAction:'preflight'},disabled:false,closest(){return button}};
 const window={dispatchEvent(){},matchMedia:()=>({matches:false,addEventListener(){}})};
 const context=vm.createContext({window,document,CustomEvent:globalThis.CustomEvent,crypto:globalThis.crypto,queueMicrotask,setTimeout,clearTimeout});
 vm.runInContext(kit,context);vm.runInContext(source,context);
 const project={id:'p',revision:'2',brief:{}};
 const request={id:'r',request_sha256:'frozen',spec:{format:'showcase_video',shots:[{}]},assets:[]};
 let release;const pending=new Promise(resolve=>{release=resolve});
 const flow=window.CommerceMediaFlow({api:async name=>name==='commerce_media_request_preflight'?pending:{requests:[request],policy:{interval_days:7,enabled:false}},repaint(){document.activeElement=body},getProject:()=>project});
 await flow.openRequest('r');
 for(const fn of listeners.change)fn({target:{dataset:{mediaField:'shot.0'},value:'asset',closest(){return{}}}});
 document.activeElement=button;
 const run=[...listeners.click][0]({target:{closest(){return button}},preventDefault(){}});
 return{document,replacement,release,run,moveFocus(){const target={};document.activeElement=target;for(const fn of listeners.focusin||[])fn({target})}};
}

test('preflight returns keyboard focus to its replacement button after repaint',async()=>{
 const f=await fixture();f.release({can_render:true});await f.run;await Promise.resolve();
 assert.equal(f.document.activeElement,f.replacement);
});
test('preflight does not reclaim focus after the user moves to another control',async()=>{
 const f=await fixture();f.moveFocus();f.release({can_render:true});await f.run;await Promise.resolve();
 assert.notEqual(f.document.activeElement,f.replacement);
});
