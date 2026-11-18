import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {build,transform} from 'esbuild';
import vm from 'node:vm';
import {createHash} from 'node:crypto';
const helpersCode=await build({entryPoints:['src/listing-choice.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const helpers=await import('data:text/javascript;base64,'+Buffer.from(helpersCode.outputFiles[0].text).toString('base64'));
const source=(await readFile('src/listing-context.tsx','utf8')).replace(/^import .*?;\n/gm,'').replace(/^import '.*?';\n/gm,'');
const compiled=(await transform(source,{loader:'tsx',format:'cjs',jsx:'transform',jsxFactory:'element'})).code;
const text=n=>n==null?'':Array.isArray(n)?n.map(text).join(''):typeof n==='object'?text(n.props?.children):String(n);
function nodes(n,check){if(n==null||typeof n!=='object')return [];if(Array.isArray(n))return n.flatMap(x=>nodes(x,check));return [...(check(n)?[n]:[]),...nodes(n.props?.children,check)];}
const fields={sku:'S1',title:'Proposed title',description:'Proposed prose',category_id:'10',price:'20',currency:'CNY',quantity:null,image_refs:[]};
const target={case_id:'case-A',platform:'ozon',store_ref:'store-A',market:'RU'};
const imageValue=text=>({mime:'image/png',content_base64:Buffer.from(text).toString('base64'),sha256:createHash('sha256').update(text).digest('hex')});
const catalog=id=>({id,name:'Original '+id,kind:'inventory',synthetic:false,source_sha256:'sha-'+id,sku:'SKU-'+id,product_id:id,primary_case_id:id,case_ids:[id],store_identity:{kind:'store',label:'Actual shop',store_ref:'store-A',platform:'ozon',market:'RU',active:true},fields:[{key:'title',original:'Raw title',locator:'source:title'},{key:'description',original:'Raw prose',locator:'source:description'}],images:[{id:'ai',origin:'generated_image'},{id:'raw-'+id,origin:'product_image',source_current:true}]});
const isListingImage=value=>!!value&&typeof value==='object'&&(value.state==='loading'||value.state==='ready'||value.state==='failed');
function harness(){
 const hooks=[],effects=[],requests=[],canonical=[];let cursor=0,tree,imageHook=-1,imageState;
 const props={catalog:catalog('case-A'),error:'',name:'Listing A',target,selected:target,sourceSha:'sha-case-A',base:fields,fields,overrides:{},revision:1,stale:false,dirty:false,active:true,busy:false,onProduct(){},onCanonical:t=>canonical.push(t),onReadSelected(){},onRestoreSelected(){}};
 const c={...helpers,module:{exports:{}},exports:{},React:{Fragment:'fragment'},Button:'button',Badge:'badge',window:{CommerceCatalogPresentation:{plain:v=>String(v).replace(/<[^>]*>/g,'')}},
  element:(type,props,...children)=>typeof type==='function'?type({...props,children}):({type,props:{...props,children}}),
  useState:initial=>{const i=cursor++;if(!(i in hooks))hooks[i]=initial;if(isListingImage(hooks[i])){imageHook=i;imageState=hooks[i];}return [hooks[i],value=>{hooks[i]=typeof value==='function'?value(hooks[i]):value;if(i===imageHook)imageState=hooks[i];}];},
  useRef:initial=>{const i=cursor++;if(!(i in hooks))hooks[i]={current:initial};return hooks[i];},
  useEffect:(fn,deps)=>{const i=cursor++,old=hooks[i];if(!old||deps.some((v,j)=>v!==old.deps[j])){old?.cleanup?.();hooks[i]={deps};effects.push(()=>hooks[i].cleanup=fn());}},
  api:(name,args)=>new Promise((resolve,reject)=>requests.push({name,args,resolve,reject})),
 };c.exports=c.module.exports;vm.runInNewContext(compiled,c);
 const render=(next={},runEffects=true)=>{Object.assign(props,next);cursor=0;tree=c.module.exports.ListingContext(props);if(runEffects)while(effects.length)effects.shift()();return tree;};
 // ready and failed are both finished image reads. failed stays visible for the failure assertions; only loading waits.
 // The deadline bounds a stuck read. The wait itself ends on the real image state, not after a fixed number of turns.
 const settle=async()=>{
  const observed=()=>{
   const state=imageState?.state;
   if(state==='ready'||state==='failed')return state;
   if(state!=='loading')throw new Error('listing image settle saw unexpected state '+state);
   return '';
  };
  if(!observed())await new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>{stop();reject(new Error('listing image settle timed out after 1000ms while state remained '+(imageState?.state??'missing')));},1000);
   let pending;
   const stop=()=>{clearTimeout(timer);if(pending!==undefined)clearImmediate(pending);};
   const pump=()=>{
    pending=undefined;
    try{if(observed()){stop();resolve();return;}}catch(error){stop();reject(error);return;}
    pending=setImmediate(pump);
   };
   pending=setImmediate(pump);
  });
  render();
 };
 return {render,settle,requests,canonical,props,get tree(){return tree;}};
}
test('identity distinguishes raw title, product draft and store proposal without claiming verified facts',()=>{
 const h=harness();h.render({productDraft:{revision:3,stale:false,has_payload:true,source_sha256:'sha-case-A'}});
 const body=text(h.tree);assert.match(body,/SKU-case-A/);assert.match(body,/Actual shop/);assert.match(body,/Raw title/);assert.match(body,/Proposed title/);assert.match(body,/商品稿修订 3/);assert.match(body,/商品信息待核对/);assert.match(body,/未提供/);
 assert.equal(h.requests[0].args.image_id,'raw-case-A');assert.equal(h.requests[0].args.index,1);
});
test('late original-image completion cannot replace the next product or flash the preceding picture',async()=>{
 const h=harness();h.render();h.requests[0].resolve(imageValue('old'));await h.settle();assert.equal(nodes(h.tree,n=>n.type==='img').length,1);
 const next=catalog('case-B');h.render({catalog:next,name:'B',target:{...target,case_id:'case-B'},selected:{...target,case_id:'case-B'},sourceSha:next.source_sha256},false);
 assert.equal(nodes(h.tree,n=>n.type==='img').length,0);h.render();h.requests[1].resolve(imageValue('new'));await h.settle();assert.equal(nodes(h.tree,n=>n.type==='img')[0].props.src,'data:image/png;base64,bmV3');
});
test('catalog and listing source mismatch suppress original values and image reads',()=>{
 const h=harness();h.render({sourceSha:'other-sha'});assert.equal(h.requests.length,0);assert.equal(nodes(h.tree,n=>n.type==='img').length,0);assert.doesNotMatch(text(h.tree),/Raw title/);assert.match(text(h.tree),/原资料版本与当前方案不一致/);
});
test('a slower prior product response cannot overwrite a completed next-product original',async()=>{
 const h=harness();h.render();const next=catalog('case-B');h.render({catalog:next,name:'B',target:{...target,case_id:'case-B'},selected:{...target,case_id:'case-B'},sourceSha:next.source_sha256});
 h.requests[1].resolve(imageValue('new'));await h.settle();h.requests[0].resolve(imageValue('old'));await h.settle();assert.equal(nodes(h.tree,n=>n.type==='img')[0].props.src,'data:image/png;base64,bmV3');
});
test('an alias uses an explicit canonical action and never moves the current target automatically',()=>{
 const h=harness(),aliased={...catalog('case-A'),primary_case_id:'primary',case_ids:['primary','case-A'],case:{scope:{inventory_type:'rfbs'}}};h.render({catalog:aliased});
 assert.equal(h.canonical.length,0);const action=nodes(h.tree,n=>n.type==='button'&&text(n)==='读取该商品的规范上架资料')[0];assert.ok(action);action.props.onClick();assert.equal(h.canonical[0].case_id,'primary');assert.equal(h.canonical[0].store_ref,'store-A');assert.match(text(h.tree),/旧方案和执行记录保持在原工作项/);
});
test('failed and unsupported image data remain explicit and can be retried without adopting an AI picture',async()=>{
 const h=harness();h.render();h.requests[0].resolve({mime:'text/html',content_base64:'not-an-image'});await h.settle();assert.equal(nodes(h.tree,n=>n.type==='img').length,0);assert.match(text(h.tree),/原图未读到/);const retry=nodes(h.tree,n=>n.type==='button'&&text(n)==='重试原图')[0];retry.props.onClick();h.render();assert.equal(h.requests.length,2);assert.equal(h.requests[1].args.image_id,'raw-case-A');
});
test('an unknown catalog never receives the store-product category badge',()=>{
 const h=harness();h.render({catalog:null});assert.match(text(h.tree),/身份资料未读到/);assert.doesNotMatch(text(h.tree),/店铺商品 · 按来源记录/);
});
test('incorrect whole-file hashes reject image data before display',async()=>{
 const h=harness();h.render();h.requests[0].resolve({...imageValue('wrong'),sha256:'0'.repeat(64)});await h.settle();assert.equal(nodes(h.tree,n=>n.type==='img').length,0);assert.match(text(h.tree),/原图未读到/);
});
test('candidate reference image uses scoped original API and identifies competitor ownership without importing its claims',async()=>{
 const h=harness(),candidate={...catalog('case-A'),kind:'candidate',fields:[],images:[{id:'reference',origin:'product_evidence',source_kind:'competitor',role:'original',reference_only:true,case_id:'case-A',entry_id:'entry',entry_sha256:'a'.repeat(64),image_index:0,media_id:'media',sha256:'b'.repeat(64),width:1000,height:1000}]};
 h.render({catalog:candidate});assert.equal(h.requests[0].args.image_id,'reference');h.requests[0].resolve(imageValue('reference'));await h.settle();
 assert.match(nodes(h.tree,n=>n.type==='img')[0].props.alt,/竞品参考图，非自有实物/);assert.match(text(h.tree),/不可直接作上架主图/);assert.doesNotMatch(text(h.tree),/Raw title/);
});
test('small supplier reference visibly remains a thumbnail and cannot become a generation basis',()=>{
 const h=harness(),candidate={...catalog('case-A'),kind:'candidate',fields:[],images:[{id:'thumb',origin:'product_evidence',source_kind:'supplier',role:'original',reference_only:true,case_id:'case-A',entry_id:'entry',entry_sha256:'a'.repeat(64),image_index:0,media_id:'media',sha256:'b'.repeat(64),width:75,height:75}]};
 h.render({catalog:candidate});assert.match(text(h.tree),/货源参考图/);assert.match(text(h.tree),/75 × 75 px 缩略图/);assert.match(text(h.tree),/不可作生图依据/);
});
