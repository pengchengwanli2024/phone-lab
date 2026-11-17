import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const read=name=>fs.readFileSync(new URL('../../web/'+name,import.meta.url),'utf8');
const catalogSource=read('catalog-ui.js'),identitySource=read('product-identity.js');
const tick=()=>new Promise(setImmediate);
const item=(id,{synthetic=false,market='RU',kind='candidate'}={})=>({id,name:id,synthetic,market,kind,platform:'ozon',source_sha256:'sha-'+id,images:[],supplier_count:0});
function runtime({api,options={}}={}){
 const listeners=new Map(),requests=[],selections=[],items=[],queries=[];let paints=0;
 const ui={escape:v=>String(v??''),button:({label,attrs={}})=>`<button ${Object.entries(attrs).map(([k,v])=>`${k}="${v}"`).join(' ')}>${label}</button>`,field:(name,html)=>name+html,input:p=>`<input id="${p.id}" value="${p.value}"/>`,select:({options})=>options.map(o=>`<option value="${o.value}">${o.label}</option>`).join(''),badge:String,alert:(label,tone)=>`<p role="alert" data-tone="${tone}">${label}</p>`,empty:label=>`<p role="status">${label}</p>`,table:(_headers,rows)=>rows.join(''),card:({title,content})=>title+content};
 const document={activeElement:null,body:{},addEventListener:(name,fn)=>{if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn)},removeEventListener:(name,fn)=>listeners.get(name)?.delete(fn),querySelector:()=>null,getElementById:()=>null};
 const context=vm.createContext({window:{CommerceUI:ui},document,crypto:{randomUUID:()=> 'instance-one'},queueMicrotask,Map,Set,setTimeout,clearTimeout,CSS:{escape:String}});
 vm.runInContext(identitySource+catalogSource,context);
 const invoke=async(name,args)=>{requests.push({name,args});if(api)return api(name,args);if(name==='commerce_agent_cases')return {cases:[]};if(name==='commerce_catalog_store_status')return {};return {items:[]}};
 const catalog=context.window.CommerceCatalog({api:invoke,repaint:()=>paints++,onSelect:id=>selections.push(id),onItems:value=>items.push(value),onQuery:value=>queries.push(value),...options});
 async function event(name,target){const ev={target,preventDefault(){}};for(const fn of [...(listeners.get(name)||[])])await fn(ev)}
 const click=(action,id)=>{const b={disabled:false,dataset:{catalogAction:action,case:id},closest:selector=>selector==='[data-catalog-action]'?b:{}};return event('click',b)};
 return {catalog,context,document,listeners,requests,selections,items,queries,click,event,get paints(){return paints}};
}
const sourceRows=[...Array.from({length:21},(_,i)=>item('real-'+(i+1))),item('example',{synthetic:true}),item('US-case',{market:'US'}),item('inventory',{kind:'inventory'})];
test('catalog: shared candidate scope, pagination and direct selection use exact cases',async()=>{
 const f=runtime({api:async name=>name==='commerce_catalog_list'?{items:sourceRows}:{cases:[]},options:{fixedKind:'candidate',getFilters:()=>({synthetic:false,market:'RU'}),directSelect:true,showStoreControls:false,showHeading:false}});
 await f.catalog.enter();let html=f.catalog.view();assert.equal((html.match(/<article /g)||[]).length,20);assert.match(html,/1 \/ 2 · 21件/);assert.doesNotMatch(html,/example|US-case|data-case="inventory"|商品来源筛选|刷新读取状态/);
 assert.deepEqual({...f.requests[0].args},{query:'',kind:'candidate'});await f.click('next');html=f.catalog.view();assert.match(html,/2 \/ 2 · 21件/);assert.match(html,/data-case="real-21"/);
 await f.click('open','real-21');assert.deepEqual(f.selections,['real-21']);assert.equal(f.requests.some(r=>r.name==='commerce_catalog_get'),false);assert.equal(f.requests.some(r=>r.name.startsWith('commerce_catalog_store_')),false);
 await f.click('open','example');assert.deepEqual(f.selections,['real-21']);assert.match(f.catalog.view(),/操作未完成/);
});
test('catalog: candidate preview reuses scoped detail without exposing creation actions',async()=>{
 const detail={...item('candidate'),case:{scope:{market:'RU',sku:'SYN'}},fields:[],suppliers:[],projects:[],source_intact:true};
 const f=runtime({options:{fixedKind:'candidate',directSelect:true,getFilters:()=>({synthetic:false,market:'RU'}),showStoreControls:false},api:async name=>name==='commerce_catalog_list'?{items:[item('candidate')]}:name==='commerce_catalog_get'?detail:{cases:[]}});
 await f.catalog.enter();assert.match(f.catalog.view(),/查看资料/);await f.click('preview','candidate');assert.match(f.catalog.view(),/catalog-detail-header/);assert.doesNotMatch(f.catalog.view(),/建立图片与视频创意项目/);await f.click('select');assert.deepEqual(f.selections,['candidate']);assert.equal(f.requests.some(r=>r.name.includes('creative')),false);
});
test('catalog: a late old-scope read never replaces current candidate results',async()=>{
 let scope={synthetic:false,market:'RU'};const reads=[];
 const f=runtime({options:{fixedKind:'candidate',getFilters:()=>scope,showStoreControls:false},api:(name,args)=>name==='commerce_catalog_list'?new Promise(resolve=>reads.push({args,resolve})):Promise.resolve({cases:[]})});
 const old=f.catalog.enter();scope={synthetic:true,market:'RU'};const current=f.catalog.enter();reads[1].resolve({items:[item('new-example',{synthetic:true})]});await current;reads[0].resolve({items:[item('old-real')]});await old;
 assert.match(f.catalog.view(),/new-example/);assert.doesNotMatch(f.catalog.view(),/old-real/);assert.equal(f.items.length,1);
});
test('catalog: failed search retains query and reports failure without a write',async()=>{
 let failed=false;const f=runtime({options:{fixedKind:'candidate',showStoreControls:false},api:async name=>{if(name==='commerce_agent_cases')return {cases:[]};if(failed)throw Error('offline');return {items:[item('saved')]} }});
 await f.catalog.enter();await f.event('input',{id:'catalog-query-instance-one',value:'long candidate query'});failed=true;await f.catalog.enter();const html=f.catalog.view();assert.match(html,/long candidate query/);assert.match(html,/商品资料暂不可读/);assert.equal(f.queries.at(-1),'long candidate query');assert.equal(f.requests.every(r=>['commerce_catalog_list','commerce_agent_cases'].includes(r.name)),true);
});
test('catalog: delegated search stays busy until its read completes',async()=>{
 let resolve;const f=runtime({options:{fixedKind:'candidate',showStoreControls:false},api:name=>name==='commerce_catalog_list'?new Promise(r=>resolve=r):Promise.resolve({cases:[]})});
 const pending=f.click('search');assert.match(f.catalog.view(),/aria-busy="true"/);resolve({items:[item('loaded')]});await pending;assert.match(f.catalog.view(),/aria-busy="false"/);
});
test('catalog: unmount removes listeners and ignores pending completion',async()=>{
 let resolve;const f=runtime({api:name=>name==='commerce_catalog_list'?new Promise(r=>resolve=r):Promise.resolve({cases:[]}),options:{fixedKind:'candidate',showStoreControls:false}});
 const pending=f.catalog.enter();f.catalog.dispose();const before=f.paints;resolve({items:[item('late')]});await pending;await tick();
 assert.equal(f.paints,before);assert.equal(f.items.length,0);assert.equal(f.catalog.view(),'');assert.equal([...f.listeners.values()].every(set=>set.size===0),true);assert.equal(f.requests.length,1);
});
test('catalog: out-of-mode detail never becomes visible',async()=>{
 const f=runtime({options:{fixedKind:'candidate',getFilters:()=>({synthetic:false,market:'RU'}),showStoreControls:false},api:async name=>name==='commerce_catalog_get'?{...item('other-mode',{synthetic:true}),case:{scope:{market:'RU'}},fields:[],suppliers:[],projects:[],source_intact:true}:{items:[]}});
 await f.catalog.open('other-mode');assert.match(f.catalog.view(),/不属于当前范围/);assert.doesNotMatch(f.catalog.view(),/catalog-detail-header/);
});
test('catalog: existing product list and store-status behavior remains available',async()=>{
 const f=runtime({api:async name=>name==='commerce_catalog_list'?{items:[item('real'),item('example',{synthetic:true})]}:name==='commerce_agent_cases'?{cases:[]}: {}});
 await f.catalog.enter();const html=f.catalog.view();assert.match(html,/data-case="real"/);assert.match(html,/data-case="example"/);assert.equal(f.requests[0].args.kind,'all');assert.equal(f.requests.some(r=>r.name==='commerce_catalog_store_status'),true);
});
test('React wrapper mounts the real catalog, updates scope and cleans up',async()=>{
 const {transformSync}=await import('esbuild');const component=fs.readFileSync(new URL('../src/catalog-browser.tsx',import.meta.url),'utf8');
 const f=runtime(),refs=[],effects=[],pendingEffects=[];f.catalog.dispose();let cursor=0;
 const React={useRef:value=>{const i=cursor++;return refs[i]||(refs[i]={current:value})},useEffect:(fn,deps)=>{const i=cursor++,old=effects[i];if(!old||deps.some((d,n)=>d!==old.deps[n]))pendingEffects.push(()=>{old?.cleanup?.();effects[i]={deps,cleanup:fn()}})}};
 const rows=[item('normal'),item('example',{synthetic:true})],calls=[],host={innerHTML:''};
 const invoke=async(name,args)=>{calls.push({name,args});return name==='commerce_catalog_list'?{items:rows}:{cases:[]}};
 const module={exports:{}};Object.assign(f.context,{module,exports:module.exports,require:name=>name==='react'?React:name==='react/jsx-runtime'?{jsx:(type,props)=>({type,props})}:name==='./api'?{api:invoke}:{}});
 vm.runInContext(transformSync(component,{loader:'tsx',format:'cjs',jsx:'automatic'}).code,f.context);
 const Browser=module.exports.CatalogBrowser;
 async function render(synthetic){cursor=0;const node=Browser({active:true,synthetic,market:'all',refreshKey:0,onSelect(){},onItems(){},onQuery(){}});node.props.ref.current=host;for(const run of pendingEffects.splice(0))run();await tick();}
 await render(false);assert.match(host.innerHTML,/data-case="normal"/);assert.doesNotMatch(host.innerHTML,/data-case="example"/);
 await render(true);assert.match(host.innerHTML,/data-case="example"/);assert.doesNotMatch(host.innerHTML,/data-case="normal"/);assert.equal(calls.filter(c=>c.name==='commerce_catalog_list').length,2);
 for(const effect of effects)effect?.cleanup?.();assert.equal([...f.listeners.values()].every(set=>set.size===0),true);
});

test('catalog detail translates known business fields while preserving source values and unknown extension keys',async()=>{
 const known={category:'类目路径与编号',availability:'库存与可售状态',brand:'品牌与型号',barcode:'条码',fulfillment:'履约方式与仓库',policy_notes:'合规与资料冲突',product_id:'平台商品编号',reviews:'评论与评分',rich_content:'图文详情与媒体',search_context:'搜索与采集范围'};
 const fields=[...Object.keys(known),'custom_extension','toString','constructor','__proto__'].map(key=>({key,original:'original-'+key,zh:'原文校对-'+key,reviewed:true}));
 const detail={...item('candidate'),case:{scope:{market:'RU',sku:'SYN'}},fields,suppliers:[],projects:[],source_intact:true};
 const f=runtime({options:{fixedKind:'candidate',getFilters:()=>({synthetic:false,market:'RU'}),showStoreControls:false},api:async name=>name==='commerce_catalog_get'?detail:{items:[]}});await f.catalog.open('candidate');const html=f.catalog.view();
 for(const [key,label]of Object.entries(known)){assert.ok(html.includes('<td>'+label+'</td>'),label);assert.ok(!html.includes('<td>'+key+'</td>'),key);assert.ok(html.includes('original-'+key));assert.ok(html.includes('原文校对-'+key));}
 for(const key of ['custom_extension','toString','constructor','__proto__'])assert.ok(html.includes('<td>'+key+'</td>'),key);
 assert.match(html,/已校对 · 待核实/);assert.equal(f.requests.some(r=>r.name.includes('save')),false);
});

test('same-name creative project links are distinguishable and still open their original project ids',async()=>{
 const projects=[{id:'aaaaaaaa11111111',name:'合成商品。',source_current:true},{id:'bbbbbbbb11111111',name:'合成商品。',source_current:true},{id:'cccccccc22222222',name:'合成商品。',source_current:true},{id:'project-unique',name:'唯一项目',source_current:true}];const opened=[];
 const detail={...item('candidate'),case:{scope:{market:'RU',sku:'SYN'}},fields:[],suppliers:[],projects,source_intact:true};
 const f=runtime({options:{fixedKind:'candidate',getFilters:()=>({synthetic:false,market:'RU'}),showStoreControls:false,onCreative:p=>opened.push(p.id)},api:async name=>name==='commerce_catalog_get'?detail:{items:[]}});await f.catalog.open('candidate');
 const links=[...f.catalog.view().matchAll(/<button[^>]*data-catalog-action="project"[^>]*data-project="([^"]+)"[^>]*>([^<]*)<\/button>/g)].map(m=>({id:m[1],label:m[2]}));assert.equal(links.length,4);assert.equal(new Set(links.slice(0,3).map(x=>x.label)).size,3);
 for(const link of links.slice(0,3)){assert.ok(link.label.startsWith('合成商品。 · #'));const suffix=link.label.split('#').at(-1);assert.ok(link.id.endsWith(suffix));assert.ok(suffix.length>=8&&suffix.length<link.id.length);}
 assert.ok(links[0].label.split('#').at(-1).length>8,'shared eight-character suffixes must be extended');assert.equal(links[3].label,'唯一项目');
 for(const project of projects){const b={disabled:false,dataset:{catalogAction:'project',project:project.id},closest:()=>({})};await f.event('click',{closest:()=>b});}
 assert.deepEqual(opened,projects.map(p=>p.id));assert.equal(f.requests.some(r=>r.name.includes('creative')),false);
});

test('the creative project selector distinguishes same-name records while preserving option values and selected title',async()=>{
 const rows=[{id:'aaaaaaaa11111111',name:'合成商品。',synthetic:true},{id:'bbbbbbbb11111111',name:'合成商品。',synthetic:true},{id:'cccccccc22222222',name:'合成商品。',synthetic:true},{id:'project-unique',name:'唯一项目',synthetic:false}],calls=[],listeners={};
 const projects=rows.map(p=>({id:p.id,revision:1,assets:[],jobs:[],plan:{},brief:{synthetic:p.synthetic,product:{name:p.name,verified_facts:[]},reference:{},target:{language:'zh'}}}));
 const document={body:{},activeElement:null,documentElement:{dataset:{},getAttribute(){return'light'},setAttribute(){}},querySelector:()=>null,getElementById:()=>null,addEventListener:(name,fn)=>(listeners[name]||=[]).push(fn),removeEventListener(){}};
 const window={matchMedia:()=>({matches:false,addEventListener(){}}),dispatchEvent(){}};
 const context=vm.createContext({window,document,crypto:globalThis.crypto,queueMicrotask,setTimeout,clearTimeout,URL,Blob,CustomEvent:globalThis.CustomEvent});
 vm.runInContext(fs.readFileSync(new URL('../../ui/kit.js',import.meta.url),'utf8')+identitySource+catalogSource,context);
 window.CommerceMediaFlow=()=>({view:()=>'',refresh:async()=>{},hasUnsavedChanges:()=>false,discardChanges(){}});
 vm.runInContext(fs.readFileSync(new URL('../../creative_ui.js',import.meta.url),'utf8'),context);
 const studio=window.CommerceCreative({api:async(name,args)=>{calls.push({name,args});if(name==='commerce_creative_list')return{projects:rows};if(name==='commerce_creative_get')return projects.find(p=>p.id===args.project_id);throw Error(name)},esc:window.CommerceUI.escape,toast(){},repaint(){},isActive:()=>true});
 await studio.enter();
 const selector=()=>studio.view().match(/<select\b[^>]*id="creative-project-select"[^>]*>[\s\S]*?<\/select>/)?.[0];
 const options=[...selector().matchAll(/<option value="([^"]+)"[^>]*>([^<]*)<\/option>/g)].map(m=>({id:m[1],label:m[2]}));
 assert.deepEqual(options.map(o=>o.id),rows.map(p=>p.id));assert.equal(new Set(options.slice(0,3).map(o=>o.label)).size,3);
 for(const option of options.slice(0,3)){assert.ok(option.label.startsWith('合成示例 · 合成商品。 · #'));const suffix=option.label.split('#').at(-1);assert.ok(option.id.endsWith(suffix));assert.ok(suffix.length>=8&&suffix.length<option.id.length)}
 assert.ok(options[0].label.split('#').at(-1).length>8,'colliding short ids extend in the global selector too');assert.equal(options[3].label,'唯一项目');
 for(const [index,p]of rows.entries()){
  for(const handler of listeners.change)await handler({target:{id:'creative-project-select',value:p.id,dataset:{}}});
  assert.equal(studio.pageContext().filters.project_id,p.id);assert.equal(calls.filter(c=>c.name==='commerce_creative_get').at(-1).args.project_id,p.id);
  const html=selector();assert.ok(html.includes('title="'+options[index].label.replace(/^合成示例 · /,'')+'"'));assert.ok(html.includes('<option value="'+p.id+'" selected>'));
 }
 assert.ok(calls.every(c=>['commerce_creative_list','commerce_creative_get'].includes(c.name)));
});
