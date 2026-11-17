import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {build,transform} from 'esbuild';
const root=new URL('../',import.meta.url);
async function load(path){const x=await build({entryPoints:[new URL(path,root).pathname],bundle:true,write:false,format:'esm',platform:'node'});return import('data:text/javascript;base64,'+Buffer.from(x.outputFiles[0].text).toString('base64'));}
const helpers=await load('src/listing-inheritance.ts'),{gapFields}=await load('src/listing-gap-actions.ts');
const choices=await load('src/listing-choice.ts');
const source=(await readFile(new URL('src/listing-page.tsx',root),'utf8')).replace(/^import .*?;\n/gm,'').replace(/^import '.*?';\n/gm,'');
const compiled=(await transform(source,{loader:'tsx',format:'cjs',jsx:'transform',jsxFactory:'element'})).code;
const text=n=>n==null?'':Array.isArray(n)?n.map(text).join(''):typeof n==='object'?text(n.props?.children):String(n);
function nodes(n,check){if(n==null||typeof n!=='object')return [];if(Array.isArray(n))return n.flatMap(x=>nodes(x,check));return [...(check(n)?[n]:[]),...nodes(n.props?.children,check)];}
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const fields={sku:'sku',title:'Base title',description:'Base description',category_id:'10',price:'100',currency:'CNY',quantity:2,image_refs:['https://example.com/p.png']};
const target={case_id:'exact-case',platform:'ozon',store_ref:'scoped-store',market:'RU'};
function view(){return {target,payload:{fields:structuredClone(fields),language:'ru',fulfillment:'FBS',rules_ref:'rules:1',attributes:[]},base_fields:structuredClone(fields),base_sha256:'base-1',field_overrides:{},name:'Product',revision:0,source_sha256:'source-1',stale:false,preview_sha256:'preview-1',platforms:{ozon:'Ozon'},missing:[],saved_targets:[],checks:[],invalid_source_fields:[],synthetic:false};}
function harness(initial=view()){
 const hooks=[],effects=[],calls=[],productLinks=[];let cursor=0,tree,current=structuredClone(initial),rejectSave=false,rejectRead=false;
 const props={demo:false,active:true,caseId:target.case_id,requestedTarget:target,onProduct:(...args)=>productLinks.push(args),onCase(){},onSelectAction(){},onPlatform(){},onTargetLoaded(){}};
 const context={...helpers,...choices,module:{exports:{}},exports:{},React:{Fragment:'fragment'},element:(type,props,...children)=>({type,props:{...props,children}}),Button:'button',Badge:'badge',Empty:'empty',ErrorNotice:'error',Panel:'section',ListingContext:'listing-context',ListingIdentityStrip:'listing-identity-strip',ListingInheritedField:'inherited-field',ListingObservation:'observation',OperatingGuide:'operating-guide',ListingSchemaPanel:'schema-panel',ListingReleasePanel:'release-panel',ListingActionsPanel:'actions-panel',OwnerReviewPanel:'owner-panel',StorefrontDraft:'storefront-panel',gapFields,enrichProductChoices:async x=>x,structuredClone,URL,Blob,Error,errorText:e=>e.message,
  document:{getElementById:()=>({focus(){},scrollIntoView(){}})},requestAnimationFrame:f=>f(),
  useState:initial=>{const i=cursor++;if(!(i in hooks))hooks[i]=typeof initial==='function'?initial():initial;return [hooks[i],value=>{hooks[i]=typeof value==='function'?value(hooks[i]):value;}];},
  useRef:initial=>{const i=cursor++;if(!(i in hooks))hooks[i]={current:initial};return hooks[i];},
  useEffect:(fn,deps)=>{const i=cursor++,old=hooks[i];if(!old||deps.some((x,j)=>x!==old.deps[j])){old?.cleanup?.();hooks[i]={deps};effects.push(()=>{hooks[i].cleanup=fn();});}},
  api:async(name,args)=>{calls.push({name,args:structuredClone(args)});if(name==='commerce_workspace_list')return {items:[{id:target.case_id,name:'Product',platform:'ozon',market:'RU',synthetic:false}]};if(name==='commerce_catalog_list')return {items:[{id:target.case_id,name:'Product',kind:'inventory',synthetic:false,source_sha256:current.source_sha256}]};if(name==='commerce_catalog_get')return {id:args.case_id,name:'Product',kind:'inventory',synthetic:false,source_sha256:current.source_sha256};if(name==='commerce_listing_get'){if(rejectRead)throw Error('read failed');return structuredClone(current);}if(name==='commerce_listing_save'){if(rejectSave)throw Error('listing_base_fields_changed');current={...current,payload:structuredClone(args.payload),revision:current.revision+1,stale:false};if(args.field_overrides){current.field_overrides=structuredClone(args.field_overrides);current.payload.fields={...current.base_fields,...args.field_overrides};}return structuredClone(current);}throw Error(name);}
 };context.exports=context.module.exports;vm.runInNewContext(compiled,context);
 function render(){cursor=0;tree=context.module.exports.ListingPage(props);while(effects.length)effects.shift()();return tree;}
 async function settle(){for(let i=0;i<4;i++){await flush();render();}}
 async function start(){render();await settle();}
 const button=label=>{const n=nodes(tree,n=>n.type==='button'&&(text(n)===label||n.props['aria-label']===label))[0];assert.ok(n,'button '+label);return n;};
 async function click(label){const n=button(label);assert.ok(!n.props.disabled);await n.props.onClick();await settle();}
 const field=key=>{const n=nodes(tree,n=>n.type==='inherited-field'&&n.props.field===key)[0];assert.ok(n,'field '+key);return n;};
 return {start,render,settle,click,button,field,calls,productLinks,setProps:next=>Object.assign(props,next),get tree(){return tree;},setView:value=>current=structuredClone(value),rejectSave:value=>rejectSave=value,rejectRead:value=>rejectRead=value};
}
test('new listing edits create only the chosen store override and carry both CAS identities',async()=>{
 const h=harness();await h.start();assert.equal(h.field('title').props.overridden,false);h.field('title').props.onOverride();h.render();h.field('title').props.onChange('Store title');h.render();await h.click('保存店铺方案');
 const {args}=h.calls.find(x=>x.name==='commerce_listing_save');assert.deepEqual(args.field_overrides,{title:'Store title'});assert.equal(args.expected_base_sha256,'base-1');assert.equal(args.expected_source_sha256,'source-1');assert.deepEqual(Object.fromEntries(Object.keys(target).map(k=>[k,args[k]])),target);assert.equal(args.payload.fields.description,'Base description');
});
test('restoring a field removes its override without deleting other store differences',async()=>{
 const value=view();value.field_overrides={title:'Store title',price:'88'};value.payload.fields={...fields,...value.field_overrides};const h=harness(value);await h.start();h.field('title').props.onRestore();h.render();assert.equal(h.field('title').props.value,'Base title');assert.equal(h.field('title').props.overridden,false);await h.click('保存店铺方案');assert.deepEqual(h.calls.find(x=>x.name==='commerce_listing_save').args.field_overrides,{price:'88'});
});
test('a base conflict preserves local differences and review rebases inherited fields only',async()=>{
 const h=harness();await h.start();h.field('title').props.onChange('Local store title');h.render();h.rejectSave(true);await h.click('保存店铺方案');assert.equal(h.field('title').props.value,'Local store title');assert.match(text(h.tree),/商品基础资料已更新/);
 const newer=view();newer.base_sha256='base-2';newer.base_fields={...fields,quantity:9,description:'New base description'};newer.payload.fields={...newer.base_fields};h.setView(newer);await h.click('核对保存版本');nodes(h.tree,n=>n.type==='input'&&n.props.type==='checkbox')[0].props.onChange({target:{checked:true}});h.render();await h.click('保留本地修改后重新保存');assert.equal(h.field('title').props.value,'Local store title');assert.equal(h.field('quantity').props.value,9);h.rejectSave(false);await h.click('保存店铺方案');const call=h.calls.filter(x=>x.name==='commerce_listing_save').at(-1);assert.equal(call.args.expected_base_sha256,'base-2');assert.deepEqual(call.args.field_overrides,{title:'Local store title'});assert.equal(call.args.payload.fields.description,'New base description');
});
test('an older backend remains editable without unsupported inheritance arguments',async()=>{
 const value=view();delete value.base_fields;delete value.base_sha256;delete value.field_overrides;const h=harness(value);await h.start();assert.equal(h.field('title').props.overridden,true);assert.equal(h.field('title').props.inheritanceAvailable,false);h.field('title').props.onChange('Old-compatible title');h.render();await h.click('保存店铺方案');const args=h.calls.find(x=>x.name==='commerce_listing_save').args;assert.equal(Object.hasOwn(args,'field_overrides'),false);assert.equal(Object.hasOwn(args,'expected_base_sha256'),false);assert.equal(args.payload.fields.title,'Old-compatible title');
});
test('a platform schema category change is an explicit store field difference',async()=>{
 const h=harness();await h.start();nodes(h.tree,n=>n.type==='schema-panel')[0].props.onChange('20',{type_id:30,attributes:[]});h.render();await h.click('保存店铺方案');const args=h.calls.find(x=>x.name==='commerce_listing_save').args;assert.deepEqual(args.field_overrides,{category_id:'20'});assert.equal(args.payload.ozon.type_id,30);
});
test('missing inherited content returns to the single product editor',async()=>{
 const value=view();value.base_fields.sku='';value.payload.fields.sku='';value.checks=[{id:'content',label:'基础内容',status:'missing'}];const h=harness(value);await h.start();await h.click('处理检查：基础内容');assert.deepEqual(h.productLinks,[[target.case_id,'content']]);
});
test('inherited field rendering has no second editable control',async()=>{
 const src=(await readFile(new URL('src/listing-inherited-field.tsx',root),'utf8')).replace(/^import .*?;\n/gm,'').replace(/^import '.*?';\n/gm,'');const code=(await transform(src,{loader:'tsx',format:'cjs',jsxFactory:'element'})).code;const c={module:{exports:{}},exports:{},Button:'button',element:(type,props,...children)=>({type,props:{...props,children}})};c.exports=c.module.exports;vm.runInNewContext(code,c);const render=c.module.exports.ListingInheritedField;
 const props={field:'title',label:'商品标题',value:'Current product title',overridden:false,inheritanceAvailable:true,onChange(){},onOverride(){},onRestore(){}};const readonly=render(props);assert.equal(nodes(readonly,n=>['input','textarea'].includes(n.type)).length,0);assert.match(text(readonly),/Current product title/);assert.match(text(readonly),/设置店铺差异/);const edited=render({...props,overridden:true});assert.equal(nodes(edited,n=>n.type==='input').length,1);assert.match(text(edited),/恢复商品资料/);
});

test('switching modes resets the collapsed operating guide and its read activation together',async()=>{
 const h=harness();await h.start();
 const details=()=>nodes(h.tree,n=>n.type==='details'&&nodes(n,x=>x.type==='summary'&&text(x)==='查看同商品经营缺项').length)[0];
 details().props.onToggle({currentTarget:{open:true}});await h.settle();
 assert.equal(nodes(h.tree,n=>n.type==='operating-guide')[0].props.active,true);
 h.setProps({demo:true});await h.settle();h.setProps({demo:false,requestedTarget:{...target}});await h.settle();
 assert.equal(details().props.open,false);assert.equal(nodes(h.tree,n=>n.type==='operating-guide')[0].props.active,false);
});

test('pending target choices cannot relabel the loaded listing inputs or assistant scope',async()=>{
 const h=harness();await h.start();
 const product=nodes(h.tree,n=>n.type==='select'&&n.props.value===target.case_id)[0];assert.ok(product);product.props.onChange({target:{value:'other-case'}});h.render();
 let context=JSON.parse(h.tree.props['data-ai-context']);assert.equal(context.entity.id,target.case_id);assert.equal(context.entity.name,'Product');assert.deepEqual(context.filters,{platform:target.platform,store_ref:target.store_ref,market:target.market});assert.equal(context.input.title,'Base title');assert.equal(context.source_refs.listing,'preview-1');
 nodes(h.tree,n=>n.type==='input'&&n.props.id==='listing-store-ref')[0].props.onChange({target:{value:'pending-store'}});h.render();
 nodes(h.tree,n=>n.type==='input'&&n.props.id==='listing-market')[0].props.onChange({target:{value:'US'}});h.render();
 context=JSON.parse(h.tree.props['data-ai-context']);assert.equal(context.entity.id,target.case_id);assert.deepEqual(context.filters,{platform:target.platform,store_ref:target.store_ref,market:target.market});
  assert.equal(h.button('保存店铺方案').props.disabled,true);
  assert.equal(nodes(h.tree,n=>n.type==='release-panel')[0].props.dirty,true);
  assert.equal(nodes(h.tree,n=>n.type==='schema-panel')[0].props.dirty,true);
  const identity=nodes(h.tree,n=>n.type==='listing-context')[0];identity.props.onRestoreSelected();await h.settle();assert.equal(h.button('保存店铺方案').props.disabled,false);
});
test('an unread listing target has no loaded object, input or source to attach to the assistant',()=>{
 const h=harness();h.render();const context=JSON.parse(h.tree.props['data-ai-context']);assert.equal(context.entity,undefined);assert.deepEqual(context.filters,{});assert.deepEqual(context.input,{});assert.deepEqual(context.source_refs,{});
});

test('a failed explicit read removes the previous product editor and loaded assistant identity',async()=>{
 const h=harness();await h.start();assert.equal(nodes(h.tree,n=>n.type==='listing-context').length,1);h.rejectRead(true);
 const form=nodes(h.tree,n=>n.type==='form')[0];await form.props.onSubmit({preventDefault(){}});await h.settle();
 assert.equal(nodes(h.tree,n=>n.type==='listing-context').length,0);assert.equal(nodes(h.tree,n=>n.type==='inherited-field').length,0);assert.equal(JSON.parse(h.tree.props['data-ai-context']).entity,undefined);assert.match(text(h.tree),/read failed/);
});
