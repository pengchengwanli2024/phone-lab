import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';

const kit=await readFile(new URL('../../ui/kit.js',import.meta.url),'utf8');
for(const [file,factory,id,formId] of [
  ['ops-ui.js','CommerceOps','ops-store_id','ops-record-form'],
  ['extensions-ui.js','CommerceExtensions','extension-name','extension-editor-form'],
  ['exposure-ui.js','CommerceExposure','exposure-query',null],
])test(`${file}: IME Enter never saves/searches; ordinary Enter keeps its action`,async()=>{
  const handlers={},calls=[];let submits=0,clicks=0,prevented=0;
  const document={body:{},documentElement:{dataset:{},getAttribute(){return 'light';},setAttribute(){}},addEventListener:(name,fn)=>(handlers[name]||=[]).push(fn),querySelector:()=>({click(){clicks++;}}),querySelectorAll:()=>[],getElementById:()=>null};
  const window={addEventListener(){},dispatchEvent(){},matchMedia:()=>({matches:false,addEventListener(){}})};
  const context=vm.createContext({window,document,crypto:globalThis.crypto,structuredClone,CustomEvent:class{},Event:class{},setInterval(){},clearInterval(){},setTimeout,clearTimeout,localStorage:{getItem(){return null;}}});
  vm.runInContext(kit,context);vm.runInContext(await readFile(process.env.UI_REMEDIATION_SOURCE_ROOT?resolve(process.env.UI_REMEDIATION_SOURCE_ROOT,'web',file):new URL('../../web/'+file,import.meta.url),'utf8'),context);
  window[factory]({api:async(name,args)=>{calls.push([name,args]);return {items:[]};},esc:window.CommerceUI.escape,money:String,toast(){},repaint(){},modal(){},closeModal(){},isActive:()=>true,getCostBase:()=>({})});
  const target={id,tagName:'INPUT',value:'合成输入',dataset:formId==='ops-record-form'?{opsField:'store_id'}:{},type:'text',matches:()=>true,closest:()=>null,form:formId?{id:formId,dispatchEvent(){submits++;}}:null};
  for(const fn of handlers.input||[])fn({target});
  const send=async extra=>{for(const fn of handlers.keydown||[])await fn({key:'Enter',keyCode:13,isComposing:false,target,preventDefault(){prevented++;},...extra});await new Promise(setImmediate);};
  await send({isComposing:true});await send({keyCode:229});
  assert.equal(prevented+submits+clicks+calls.length,0,'IME confirmation has no business effect');
  await send({});assert.equal(prevented,1,'the explicit Enter shortcut still executes');
  if(formId==='ops-record-form')assert.equal(submits,1);
  if(formId==='extension-editor-form')assert.equal(clicks,1);
  if(file==='exposure-ui.js')assert.equal(calls.length,1);
});
