import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { randomUUID } from 'node:crypto';
const read=name=>fs.readFileSync(new URL('../../web/'+name,import.meta.url),'utf8');
const product=read('product-workspace-ui.js');
const cut=(start,end)=>product.slice(product.indexOf(start),product.indexOf(end,product.indexOf(start)));
const tick=()=>new Promise(setImmediate);
function documentFixture() {
  const nodes=new Map();const body={id:'',isConnected:true};
  const document={body,activeElement:body,getElementById:id=>nodes.get(id)||null,querySelector:()=>({contains:node=>node!==body}),addEventListener(){}};
  function field(id,start=0,end=start,type='search') {const node={id,type,disabled:false,isConnected:true,selectionStart:start,selectionEnd:end,selectionDirection:'forward',focus(){document.activeElement=node;},setSelectionRange(a,b,direction){this.selectionStart=a;this.selectionEnd=b;this.selectionDirection=direction;}};nodes.set(id,node);return node;}
  function repaint({focus=null,remove=false}={}) {const old=document.activeElement;if(old!==body){old.isConnected=false;if(remove)nodes.delete(old.id);else field(old.id,0,0,old.type);}document.activeElement=body;if(focus)focus.focus();}
  return {document,field,repaint,body};
}
function productFixture(options={}) {
  const dom=documentFixture();let reply;const s={items:[{id:'exact-case',name:'产品'}]};
  const context=vm.createContext({...dom,s,root:{contains:node=>node!==dom.body},identity:{merge:items=>items},render:()=>dom.repaint(options),api:()=>new Promise(resolve=>reply=resolve)});
  vm.runInContext(cut('  let identityItems;','  async function reload(')+';this.start=enrichIdentity;',context);
  return {...dom,start:context.start,reply:value=>reply(value)};
}
function catalogFixture(options={}) {
  const dom=documentFixture();let reply;
  const context=vm.createContext({...dom,window:{CommerceUI:{escape:String},CommerceProductIdentity:{merge:items=>items}},crypto:{randomUUID},setTimeout,clearTimeout,Map,Set});
  vm.runInContext(read('catalog-ui.js'),context);
  const catalog=context.window.CommerceCatalog({repaint:()=>dom.repaint(options),api:async tool=>tool==='commerce_catalog_list'?{items:[]} : tool==='commerce_agent_cases'?new Promise(resolve=>reply=resolve):{}});
  return {...dom,start:()=>catalog.enter(),reply:value=>reply(value)};
}
for(const [name,make] of [['product',productFixture],['catalog',catalogFixture]]) {
  test(`${name}: delayed scope response preserves the currently focused exact input and selection`,async()=>{
    const f=make();f.field('earlier',1,2).focus();await f.start();
    f.field('current-search',2,6).focus();f.reply({cases:[]});await tick();
    assert.equal(f.document.activeElement.id,'current-search');assert.equal(f.document.activeElement.selectionStart,2);assert.equal(f.document.activeElement.selectionEnd,6);
  });
  test(`${name}: an intentional newer focus is not replaced after repaint`,async()=>{
    const options={},f=make(options),destination=f.field('destination');options.focus=destination;
    await f.start();f.field('query',1,3).focus();f.reply({cases:[]});await tick();
    assert.equal(f.document.activeElement,destination);
  });
}
