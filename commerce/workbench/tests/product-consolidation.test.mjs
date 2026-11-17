import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import {readFileSync} from 'node:fs';
const product=readFileSync(new URL('../../web/product-workspace-ui.js',import.meta.url),'utf8');
const links=readFileSync(new URL('../../web/product-creative-links.js',import.meta.url),'utf8');
const kit=readFileSync(new URL('../../ui/kit.js',import.meta.url),'utf8');
const cut=(s,a,b)=>s.slice(s.indexOf(a),s.indexOf(b,s.indexOf(a)));
test('product cost projection has one edit action and no competing form or scenario writes',()=>{
 const c=vm.createContext({s:{busy:false,data:{forms:{cost:{stale:false}}}},alert:()=>'',costSummary:(_compact,action)=>'<saved-cost>'+action+'</saved-cost>',btn:(label,action)=>'<button data-action="'+action+'">'+label+'</button>'});
 vm.runInContext(cut(product,'  function costView(','  function contentView(')+';this.view=costView;',c);const html=c.view();assert.match(html,/编辑成本/);assert.match(html,/edit-cost/);assert.doesNotMatch(html,/<input|<form|动态成本|保存成本情景/);
 assert.doesNotMatch(product,/ui\.select\(\{id:'pw-case'/,'the directory is the only product selector');
});
test('editing cost routes the exact product to the shared editor without a write',async()=>{
 const messages=[],c=vm.createContext({s:{id:'case-a',busy:false,data:{case:{id:'case-a'}}},bridged:true,parent:{postMessage:m=>messages.push(m)},nonce:'test'});
 vm.runInContext(cut(product,'  async function act(',"  document.addEventListener('click'")+';this.act=act;',c);await c.act('edit-cost',{});assert.equal(messages.length,1);assert.equal(messages[0].type,'commerce:workspace-dynamic-cost');assert.equal(messages[0].case_id,'case-a');assert.equal(messages[0].nonce,'test');
});
test('product content is a read-only project index and stale product reads cannot replace its links',async()=>{
 let binding={case_id:'case-a',source_sha256:'a'.repeat(64)},release;const listeners={},opened=[],window={dispatchEvent(){},matchMedia:()=>({matches:false,addEventListener(){}})},document={documentElement:{dataset:{},getAttribute(){return'light'},setAttribute(){}},addEventListener:(type,fn)=>listeners[type]=fn};
 const c=vm.createContext({window,document,crypto:globalThis.crypto,CustomEvent:globalThis.CustomEvent});vm.runInContext(kit+'\n'+links,c);
 const index=window.CommerceProductCreativeLinks({api:()=>new Promise(r=>{release=r}),getBinding:()=>binding,repaint(){},onOpen:r=>opened.push(r)});
 const old=index.enter();binding={case_id:'case-b',source_sha256:'b'.repeat(64)};index.view();release({projects:[{id:'project-a',case_id:'case-a',name:'OLD_A'}]});await old;assert.doesNotMatch(index.view(),/OLD_A/);
 const current=index.enter();release({projects:[{id:'project-a',case_id:'case-a',name:'OTHER_A'},{id:'project-b',case_id:'case-b',name:'CURRENT_B',revision:2}]});await current;const html=index.view();assert.match(html,/CURRENT_B/);assert.doesNotMatch(html,/OTHER_A|creative-name|creative-brief-form|media-analysis-layout/);
 listeners.click({target:{closest:()=>({disabled:false,dataset:{productContentAction:'open',project:'project-a'}})}});assert.equal(opened.length,0);
 listeners.click({target:{closest:()=>({disabled:false,dataset:{productContentAction:'open',project:'project-b'}})}});assert.equal(opened[0].case_id,'case-b');assert.equal(opened[0].project_id,'project-b');assert.equal(index.hasUnsavedChanges(),false);
});

test('catalog creative links resolve existing project bindings before reaching the master',async()=>{
 const messages=[];let options,release;let serial=0;const detail={id:'project-a',brief:{product_binding:{case_id:'case-a',source_sha256:'a'.repeat(64)}}};const c=vm.createContext({s:{generation:0},crypto:{randomUUID:()=> 'request-'+ ++serial},api:(tool,args)=>{assert.equal(tool,'commerce_creative_get');assert.ok(args.project_id);assert.equal(args.id,undefined);return new Promise(r=>release=r)},bridged:true,nonce:'test',parent:{postMessage:m=>messages.push(m)},render(){},window:{CommerceCatalog:o=>{options=o;return{}},CommerceProductCreativeLinks:()=>({})}});
 vm.runInContext(cut(product,'  function openCreativeMaster(','  let copilot,'),c);await options.onCreative(detail);assert.equal(messages.shift().type,'commerce:workspace-catalog-creative-pending');assert.equal(messages[0].type,'commerce:workspace-catalog-creative');assert.equal(messages[0].case_id,'case-a');assert.equal(messages[0].project_id,'project-a');assert.equal(messages[0].nonce,'test');
 const existing=options.onCreative({id:'project-a'});assert.equal(messages.pop().type,'commerce:workspace-catalog-creative-pending');assert.equal(messages.length,1);release(detail);await existing;assert.equal(messages.length,2);assert.equal(messages[1].project_id,'project-a');
 const late=options.onCreative({id:'project-a'});messages.pop();c.s.generation++;release(detail);await late;assert.equal(messages.length,2);
 const bad=options.onCreative({id:'bad'});messages.pop();release({id:'bad'});await bad;assert.equal(messages.length,2);assert.match(c.s.error,/关联/);
});
test('standalone content navigation fixes a creation identity before leaving the product document',()=>{
 let url;const c=vm.createContext({bridged:false,nonce:'test',crypto:{randomUUID:()=> 'stable-intent'},URL,location:{href:'http://example.test/product-workspace',assign:v=>url=new URL(v)}});vm.runInContext(cut(product,'  function openCreativeMaster(','  const catalog='),c);vm.runInContext(`openCreativeMaster({case_id:'case-a',source_sha256:'${'a'.repeat(64)}'})`,c);assert.equal(url.searchParams.get('creative_intent_id'),'stable-intent');assert.equal(url.searchParams.get('creative_case_id'),'case-a');
});

test('restoring the saved media tab reads its project index for the loaded product',async()=>{
 let enters=0;const c=vm.createContext({tabs:{media:'图片与视频'},s:{id:'case-a',generation:0,researchSequence:0,researchTaskId:'',data:null,dirty:new Set()},modelContext:()=>({}),render(){},bridged:true,embedded:true,reactHost:true,hostRefreshDeferred:false,researchContext:{task:()=>'',artifact(){}},reportResearchSelection(){},studio:{enter:()=>{enters++;}},catalog:{enter(){throw Error('unexpected catalog')}},api:async name=>name==='commerce_workspace_list'?{items:[{id:'case-a'}]}:{case:{id:'case-a'},forms:{view:{payload:{tab:'media'}}}}});
 vm.runInContext(cut(product,'  async function reload(','  function selectTab(')+';this.reload=reload;',c);await c.reload();assert.equal(c.s.tab,'media');assert.equal(c.s.data.case.id,'case-a');assert.equal(enters,1);
});

test('project index delegates sibling identities and opens the exact same-named project',async()=>{
 const listeners={},opened=[],labels=[],binding={case_id:'case-a',source_sha256:'source-a'},window={dispatchEvent(){},matchMedia:()=>({matches:false,addEventListener(){}})},document={documentElement:{dataset:{},getAttribute(){return'light'},setAttribute(){}},addEventListener:(type,fn)=>listeners[type]=fn};
 const c=vm.createContext({window,document,crypto:globalThis.crypto,CustomEvent:globalThis.CustomEvent});vm.runInContext(kit+'\n'+links,c);
 const index=window.CommerceProductCreativeLinks({api:async()=>({projects:[{id:'project-a',case_id:'case-a',name:'same'},{id:'project-b',case_id:'case-a',name:'same'}]}),getBinding:()=>binding,repaint(){},onOpen:r=>opened.push(r),formatProjectLabel:(p,all)=>{labels.push(all.length);return p.name+' #'+p.id;}});
 await index.enter();const html=index.view();assert.match(html,/same #project-a/);assert.match(html,/aria-label="打开内容项目：same #project-b"/);assert.deepEqual([...new Set(labels)],[2]);
 listeners.click({target:{closest:()=>({disabled:false,dataset:{productContentAction:'open',project:'project-b'}})}});assert.equal(opened[0].project_id,'project-b');assert.equal(opened[0].case_id,'case-a');
});
