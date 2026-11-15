// Controlled promises execute the actual editors; no browser, model or network.
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=await readFile('commerce/web/business-ui.js','utf8');
function harness(){const handlers={},pending=[],modals=[];const document={addEventListener:(k,h)=>handlers[k]=h,querySelectorAll:()=>[],querySelector:()=>({}),getElementById:()=>null};const ui={button:()=>'',field:(_l,v)=>v,select:v=>v.value};const window={CommerceUI:ui,CommerceBusinessForms:()=>({importEditor:()=>'',draftEditor:()=>''})};const api=(tool,args)=>new Promise(resolve=>pending.push({tool,args,resolve}));vm.runInNewContext(source,{window,document,crypto:{randomUUID:()=>''},setTimeout});const app=window.CommerceBusiness({api,esc:String,toast:()=>{},repaint:()=>{},modal:(_t,b)=>modals.push(b),closeModal:()=>{},isActive:()=>true});return {handlers,pending,modals,app}}
const template=()=>({document:{kind:'facts',records:[],scope:{}},required_fields:{}});
const event=(id,value)=>({target:{id,value,matches:()=>false}});
for(const id of ['business-import-kind','business-kind']){
 const h=harness(),first=h.handlers.change(event(id,'shipping')),latest=h.handlers.change(event(id,'purchase'));await Promise.resolve();await Promise.resolve();assert.equal(h.pending.length,2);
 h.pending[1].resolve(template());await latest;h.pending[0].resolve(template());await first;
 assert.equal(h.modals.length,1,id);assert.ok(h.modals[0].includes('purchase'),id);
}
const h=harness(),opening=h.handlers.change(event('business-import-kind','shipping'));h.app.cancelEditor();h.pending[0].resolve(template());await opening;assert.equal(h.modals.length,0,'closed editor cannot reopen');
console.log(JSON.stringify({status:'passed',checks:['latest import template','latest draft template','close invalidates pending editor']}));
