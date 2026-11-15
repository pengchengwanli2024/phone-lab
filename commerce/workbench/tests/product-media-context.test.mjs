import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const source=await readFile(new URL('../../creative_ui.js',import.meta.url),'utf8');
const kit=await readFile(new URL('../../ui/kit.js',import.meta.url),'utf8');
function surface(){
 const window={dispatchEvent(){},matchMedia:()=>({matches:false,addEventListener(){}})},document={addEventListener(){},querySelector(){return null},documentElement:{dataset:{},getAttribute(){return 'light'},setAttribute(){}}};
 const context=vm.createContext({window,document,crypto:globalThis.crypto,queueMicrotask,setTimeout,clearTimeout,URL,Blob,CustomEvent:class {constructor(type,options){this.type=type;this.detail=options?.detail}}});
 vm.runInContext(kit,context);
 window.CommerceMediaFlow=()=>({view:()=>'<div>production flow</div>',refresh:async()=>{}});
 window.CommerceCatalog=()=>({view:()=>'',enter:async()=>{}});
 vm.runInContext(source,context);
 let binding={case_id:'case-a',source_sha256:'source-a'};
 const projects=['a','b'].map(id=>({id,name:'PRODUCT_'+id,case_id:'case-'+id,revision:'1'}));
 const api=async(name,args)=>name==='commerce_creative_list'?{projects}:name==='commerce_creative_get'?{
  ...projects.find(p=>p.id===args.project_id),brief:{product:{name:'PRODUCT_'+args.project_id,verified_facts:[]},product_binding:{case_id:'case-'+args.project_id}},assets:[],jobs:[],plan:{}}:{};
 const studio=window.CommerceCreative({api,esc:window.CommerceUI.escape,toast(){},repaint(){},isActive:()=>true,getBinding:()=>binding});
 return {studio,setBinding:value=>{binding=value}};
}
test('a selected product only exposes its own creative projects',async()=>{
 const {studio}=surface();await studio.enter();
 assert.match(studio.view(),/PRODUCT_a/);assert.doesNotMatch(studio.view(),/PRODUCT_b/);
 await studio.openProject('b');assert.doesNotMatch(studio.view(),/PRODUCT_b/);
});
test('switching the parent product removes the previous product creative editor',async()=>{
 const {studio,setBinding}=surface();await studio.enter();await studio.openProject('a');
 assert.match(studio.view(),/PRODUCT_a/);
 setBinding({case_id:'case-b',source_sha256:'source-b'});
 assert.doesNotMatch(studio.view(),/PRODUCT_a/);
});
