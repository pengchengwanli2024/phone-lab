import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const read=path=>fs.readFileSync(new URL('../../'+path,import.meta.url),'utf8');
const sources=['ui/kit.js','ui/page-context.js','web/product-identity.js','web/catalog-ui.js'].map(read).join('\n');
const plain=value=>JSON.parse(JSON.stringify(value));
const decode=value=>value.replace(/&(quot|amp|lt|gt|#39);/g,(_,key)=>({quot:'"',amp:'&',lt:'<',gt:'>','#39':"'"}[key]));

function runtime(demo){
 const listeners={},calls=[],selections=[],updates=[];let node=null,html='',catalog;
 const base={page:'workspace',section:'cost',demo,source:'live',entity:{kind:'case',id:'case-A',name:'Old A'},filters:{platform:'old-platform',market:'US',store_ref:'old-store',query:'old query',date_from:'2020-01-01'},source_refs:{case:'a'.repeat(64),cost:'c'.repeat(64)},input:{sku:'A-SKU',purchase_cost:999}};
 const detail={id:'case-B',name:'商品 "B" <资料>',kind:'candidate',synthetic:demo,market:'RU',platform:'ozon',source_sha256:'b'.repeat(64),images:[],case:{scope:{platform:'ozon',market:'RU',store_ref:'B-store',sku:'B-SKU'}},fields:[],suppliers:[],projects:[],source_intact:true};
 const emit=(name,target)=>{for(const fn of listeners[name]||[])fn({target,preventDefault(){}})};
 const target=()=>({isConnected:true,closest:selector=>selector==='[data-ai-context]'?(node.getAttribute(selector.slice(1,-1))?node:null):null,getClientRects:()=>[{}],focus(){document.activeElement=this;emit('focusin',this)}});
 const root={contains:el=>el===node||el?.closest?.('[data-ai-context]')===node,querySelectorAll:selector=>selector==='input[type="search"],input[id$="-query"],input[id$="-keyword"]'&&node?.query?[node.query]:[]};
 const document={body:root,activeElement:null,documentElement:{dataset:{},getAttribute:()=> 'light',setAttribute(){}},addEventListener:(name,fn)=>(listeners[name]||=[]).push(fn),removeEventListener:(name,fn)=>{listeners[name]=(listeners[name]||[]).filter(x=>x!==fn)},getElementById:()=>null,querySelector:selector=>selector.includes(' h2')?node?.heading:selector.includes('[data-catalog-action=open]')?node?.opener:selector.startsWith('[data-catalog-instance=')?node:null};
 const window={matchMedia:()=>({matches:false,addEventListener(){}}),dispatchEvent(){}};
 const context=vm.createContext({window,document,crypto:{randomUUID:()=> 'context-fixture'},queueMicrotask,setTimeout,clearTimeout,URL,Blob,CustomEvent:globalThis.CustomEvent,CSS:{escape:String}});
 vm.runInContext(sources,context);
 function paint(){
  if(node)node.isConnected=false;
  html=catalog.view();const attrs=html.match(/^<section\b([^>]*)>/)?.[1]||'';
  node={isConnected:true,getAttribute:name=>{const value=attrs.match(new RegExp('(?:^|\\s)'+name+'="([^"]*)"'))?.[1];return value===undefined?null:decode(value)},closest:selector=>selector==='[data-ai-context]'&&node.getAttribute('data-ai-context')?node:null,contains:el=>el?.closest?.('[data-ai-context]')===node,querySelectorAll:()=>[]};
  node.heading=html.includes('catalog-detail-header')?target():null;node.opener=target();
  const query=html.match(/<input\b[^>]*id="catalog-query-context-fixture"[^>]*value="([^"]*)"/);
  node.query=query?Object.assign(target(),{id:'catalog-query-context-fixture',value:decode(query[1])}):null;
 }
 catalog=window.CommerceCatalog({api:async(name,args)=>{calls.push({name,args});if(name==='commerce_catalog_list')return {items:[detail]};if(name==='commerce_catalog_get')return detail;if(name==='commerce_agent_cases')return{cases:[]};throw Error(name)},repaint:paint,onSelect:id=>selections.push(id),fixedKind:'candidate',getFilters:()=>({synthetic:demo,market:'RU',private_extra:'must-not-escape'}),directSelect:true,showStoreControls:false});
 paint();const page=window.CommercePageContext.create({getBase:()=>base,root:()=>root,onChange:value=>updates.push(plain(value))});
 async function click(action){const button={disabled:false,dataset:{catalogAction:action,case:'case-B'},closest:selector=>selector==='[data-catalog-action]'?button:node};for(const fn of listeners.click||[])await fn({target:button,preventDefault(){}});await Promise.resolve()}
 return {catalog,page,calls,selections,updates,async start(){await catalog.enter();emit('input',Object.assign(node.query,{value:'商品 B'}));paint();node.query.focus();await Promise.resolve()},click,get html(){return html}};
}

for(const demo of [false,true])test(`catalog preview and return isolate assistant identity, sources and inputs (demo=${demo})`,async()=>{
 const f=runtime(demo);await f.start();await f.click('preview');
 let scope=plain(f.page.snapshot());assert.equal(scope.page,'workspace');assert.equal(scope.section,'product-detail');assert.equal(scope.source,'local');assert.equal(scope.demo,demo);
 assert.deepEqual(scope.entity,{kind:'case',id:'case-B',name:'商品 "B" <资料>'});assert.deepEqual(scope.source_refs,{case:'b'.repeat(64)});assert.equal(scope.input,undefined);
 assert.deepEqual(scope.filters,{market:'RU',platform:'ozon',store_ref:'B-store',query:'商品 B',category:'调研候选'});assert.doesNotMatch(JSON.stringify(scope),/case-A|Old A|old-store|A-SKU|purchase_cost|private_extra/);
 assert.ok(f.updates.some(value=>value.entity?.id==='case-B'),'actual heading focus publishes the preview object');assert.ok(f.html.includes('&quot;B&quot; &lt;资料&gt;'),'metadata and visible text stay escaped');
 await f.click('back');scope=plain(f.page.snapshot());assert.equal(scope.section,'list');assert.equal(scope.entity,undefined);assert.deepEqual(scope.source_refs,{});assert.equal(scope.input,undefined);assert.equal(scope.source,'local');assert.equal(scope.demo,demo);
 assert.deepEqual(scope.filters,{market:'RU',query:'商品 B',category:'调研候选'});assert.doesNotMatch(JSON.stringify(scope),/case-A|case-B|Old A|old-store|B-store|purchase_cost/);assert.equal(f.updates.at(-1).entity,undefined);
 assert.deepEqual(f.selections,[],'previewing and returning never select a workspace item');assert.ok(f.calls.every(call=>['commerce_catalog_list','commerce_catalog_get','commerce_agent_cases'].includes(call.name)));f.page.dispose();f.catalog.dispose();
});
