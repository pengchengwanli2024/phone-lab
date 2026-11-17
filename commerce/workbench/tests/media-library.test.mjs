import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {createHash,webcrypto} from 'node:crypto';

const root=new URL('../../',import.meta.url),flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const hash=data=>createHash('sha256').update(data).digest('hex');
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lO8AAAAASUVORK5CYII=','base64');
const scopeA={kind:'store',label:'Synthetic A',account_id:'account-A',connection_id:'connection-A',platform:'ozon',market:'RU',active:true,store_ref:'ozon-live'};
const scopeB={...scopeA,label:'Synthetic B',account_id:'account-B',connection_id:'connection-B',active:false,store_ref:null};
function row(id='A',bytes=png,extra={}){return {id:'creative:'+id,origin:'creative',project_id:'project-'+id,project_name:'Synthetic project '+id,asset_id:'asset-'+id,asset_kind:'generated_image',kind:'generated_image',role:'generated_image',display_name:'approved-'+id+'.png',source_url:'https://example.invalid/source',sha256:hash(bytes),size:bytes.length,width:1,height:1,synthetic:false,case_id:'case-'+id,product_id:'product-'+id,sku:'SKU-'+id,product_name:'Synthetic product '+id,product_readable:true,store_identity:scopeA,storage_status:'registered_local_file',review_status:'unreviewed',publication_approved:false,quality_verified:false,rendition:'unknown',preview:{available:true,tool:'commerce_creative_asset_read',arguments:{project_id:'project-'+id,asset_id:'asset-'+id,offset:'0'}},...extra};}
function listing(rows,args,extra={}){return {synthetic:args.synthetic,items:rows.slice(args.offset,args.offset+args.limit),total:rows.length,offset:args.offset,limit:args.limit,next_offset:args.offset+args.limit<rows.length?args.offset+args.limit:null,kinds:['all','generated_image'],stores:[{store_ref:'account-A',label:'Synthetic A',kind:'store',active:true},{store_ref:'account-B',label:'Synthetic B',kind:'store',active:false}],store_facets_complete:true,issues:[],...extra};}
function packet(bytes,offset=0,{evidence=false,mime='image/png',sha256=hash(bytes)}={}){const part=bytes.subarray(offset,offset+49152),end=offset+part.length;return {size:bytes.length,sha256,mime,content_base64:part.toString('base64'),next_offset:evidence?(end===bytes.length?null:end):String(end),...(evidence?{status:'archived'}:{done:end===bytes.length})};}
function deferred(){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
async function harness({rows=[row()],overrides={},synthetic=false,digest}={}){
 const listeners={},calls=[],created=[],revoked=[],downloads=[],callbacks=[],timers=new Map();let active=true,screen='',app,timerId=0;
 const body={append(){}},document={body,activeElement:body,documentElement:{dataset:{}},addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn),removeEventListener:(type,fn)=>listeners[type]=(listeners[type]||[]).filter(v=>v!==fn),getElementById:()=>null,createElement:name=>{assert.equal(name,'a');return {href:'',download:'',click(){downloads.push({href:this.href,filename:this.download});},remove(){}};}};
 const api=async(name,args)=>{calls.push({name,args:structuredClone(args)});if(overrides[name])return overrides[name](args);if(name==='commerce_media_library_list')return listing(rows,args);if(name==='commerce_creative_asset_read')return packet(png,Number(args.offset));throw Error('Unexpected tool '+name);};
 const context={window:{matchMedia:()=>({matches:false,addEventListener(){}}),dispatchEvent(){}},document,CustomEvent:class{},crypto:{randomUUID:()=> 'synthetic-media-library',subtle:{digest:digest||((...args)=>webcrypto.subtle.digest(...args))}},Blob,Uint8Array,TextDecoder,atob,URL:{createObjectURL:blob=>{const url='blob:synthetic-'+created.length;created.push({url,blob});return url;},revokeObjectURL:url=>revoked.push(url)},setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id)};
 vm.runInNewContext(await readFile(new URL('ui/kit.js',root),'utf8'),context,{filename:'ui/kit.js'});
 vm.runInNewContext(await readFile(new URL('web/media-library-ui.js',root),'utf8'),context,{filename:'web/media-library-ui.js'});
 app=context.window.CommerceMediaLibrary({api,synthetic,repaint:()=>screen=app.view(),isActive:()=>active,onProduct:id=>callbacks.push(id)});
 const hostSelector='[data-media-library-id="synthetic-media-library"]';
 const emit=async(type,target)=>{for(const handler of [...(listeners[type]||[])])await handler({target,preventDefault(){}});};
 const click=(action,mediaId='')=>{const b={disabled:false,dataset:{mediaLibraryAction:action,mediaId},closest:selector=>selector===hostSelector?{}:null};return emit('click',{closest:selector=>selector==='[data-media-library-action]'?b:null});};
 return {app,calls,created,revoked,downloads,callbacks,listeners,click,change:(name,value)=>emit('change',{id:'media-library-'+name+'-synthetic-media-library',value}),input:value=>emit('input',{id:'media-library-query-synthetic-media-library',value}),submit:()=>emit('submit',{closest:selector=>selector===hostSelector?{}:null,matches:selector=>selector==='[data-media-library-search]'}),setActive:value=>active=value,runTimers:()=>{for(const fn of [...timers.values()])fn();},get screen(){return screen||app.view();}};
}

test('metadata-only entry separates unknown store, preserves unknown values and never approves by filename',async()=>{
 const unknown=row('unknown',png,{store_identity:{kind:'unassigned'},sku:null,width:null,height:null,size:null,sha256:null,display_name:'<img src=x onerror=alert(1)> approved.png',product_readable:false,preview:{available:false,tool:null,arguments:{}},storage_status:'link_only'});
 const h=await harness({rows:[row(),unknown]});await h.app.enter();
 assert.deepEqual(h.calls,[{name:'commerce_media_library_list',args:{synthetic:false,query:'',store_ref:'all',kind:'all',limit:20,offset:0}}]);
 assert.match(h.screen,/未知店铺 \/ 未绑定素材/);assert.match(h.screen,/尺寸未知 · 大小未知/);assert.match(h.screen,/AI生成 · 当前用途未审核/);
 assert.match(h.screen,/&lt;img src=x onerror=alert\(1\)&gt;/);assert.doesNotMatch(h.screen,/<img|<iframe|href="https:/);
 assert.equal(h.created.length,0);assert.equal((h.screen.match(/data-media-library-action="product"/g)||[]).length,1);
 await h.click('product',unknown.id);assert.equal(h.callbacks.length,0);await h.click('product','creative:A');assert.deepEqual(h.callbacks,['case-A']);
});

test('search, exact store facets, kind and pagination use bounded explicit synthetic scope',async()=>{
 const rows=Array.from({length:21},(_,i)=>row(String(i))),h=await harness({rows});await h.app.enter();
 assert.match(h.screen,/value="account-B"/);assert.match(h.screen,/1–20 \/ 共21项/);
 await h.click('next');assert.equal(h.calls.at(-1).args.offset,20);assert.match(h.screen,/21–21 \/ 共21项/);
 await h.click('prev');assert.equal(h.calls.at(-1).args.offset,0);
 const before=h.calls.length;await h.input('  SKU  ');assert.equal(h.calls.length,before);await h.submit();assert.equal(h.calls.at(-1).args.query,'SKU');
 await h.change('store','account-A');assert.equal(h.calls.at(-1).args.store_ref,'account-A');assert.equal(h.calls.at(-1).args.connection_id,undefined);
 await h.change('kind','generated_image');assert.equal(h.calls.at(-1).args.kind,'generated_image');assert.equal(h.calls.at(-1).args.limit,20);
 const demo=await harness({rows:[row('demo',png,{synthetic:true})],synthetic:true});await demo.app.enter();assert.equal(demo.calls[0].args.synthetic,true);assert.match(demo.screen,/当前为合成资料/);
});

test('creative chunks retain original scope and create an image URL only after complete SHA verification; close releases it',async()=>{
 const bytes=Buffer.concat([png,Buffer.alloc(50000)]),h=await harness({rows:[row('large',bytes)],overrides:{commerce_creative_asset_read:args=>packet(bytes,Number(args.offset))}});await h.app.enter();
 await h.click('preview','creative:large');
 assert.deepEqual(h.calls.filter(c=>c.name==='commerce_creative_asset_read').map(c=>c.args),[{project_id:'project-large',asset_id:'asset-large',offset:'0'},{project_id:'project-large',asset_id:'asset-large',offset:'49152'}]);
 assert.equal(h.created.length,1);assert.equal(h.created[0].blob.size,bytes.length);assert.match(h.screen,/<img src="blob:synthetic-0"/);assert.match(h.screen,/不代表内容审核/);
 await h.click('close');assert.deepEqual(h.revoked,['blob:synthetic-0']);assert.doesNotMatch(h.screen,/<img/);
});

test('evidence image packets preserve exact source version/index and numeric offset',async()=>{
 const sha256='f'.repeat(64),item=row('evidence',png,{id:'evidence:exact',origin:'product_evidence',kind:'supplier_image',role:'original',entry_id:'source-exact',entry_sha256:sha256,image_index:2,preview:{available:true,tool:'commerce_product_evidence_image',arguments:{case_id:'case-evidence',entry_id:'source-exact',expected_entry_sha256:sha256,index:2,offset:0}}});
 const h=await harness({rows:[item],overrides:{commerce_product_evidence_image:()=>packet(png,0,{evidence:true})}});await h.app.enter();await h.click('preview',item.id);
 assert.deepEqual(h.calls.at(-1).args,{case_id:'case-evidence',entry_id:'source-exact',expected_entry_sha256:sha256,index:2,offset:0});assert.equal(h.created.length,1);
});

test('tampered bytes, mixed packet metadata and repeated offsets cannot display or download a file',async()=>{
 const corrupted=Buffer.from(png);corrupted[20]^=1;
 const cases=[()=>packet(corrupted,0,{sha256:hash(png)}),()=>({...packet(png),sha256:'e'.repeat(64)}),()=>({...packet(png),next_offset:'0'}),()=>({...packet(png),size:png.length+1}),()=>({...packet(png),done:false})];
 for(const response of cases){const h=await harness({overrides:{commerce_creative_asset_read:response}});await h.app.enter();await h.click('download','creative:A');assert.equal(h.created.length,0);assert.equal(h.downloads.length,0);assert.match(h.screen,/读取或SHA核对未通过/);}
});

test('oversized/unknown files and a forged tool contract are blocked before a media request',async()=>{
 const rows=[row('big',png,{size:8*1024*1024+1}),row('unknown',png,{size:null}),row('forged',png,{preview:{available:true,tool:'commerce_listing_submission_submit',arguments:{}}})];
 const h=await harness({rows});await h.app.enter();for(const item of rows){await h.click('preview',item.id);await h.click('download',item.id);}
 assert.equal(h.calls.length,1);assert.match(h.screen,/超过8 MB/);assert.match(h.screen,/大小或SHA登记不完整/);assert.equal(h.downloads.length,0);
 const v=await harness({rows:[row('video',png,{kind:'video',width:1280,height:720})]});await v.app.enter();await v.click('preview','creative:video');assert.equal(v.calls.length,1);assert.match(v.screen,/当前页面不播放/);
});

test('filter, hide, close and disposal invalidate pending downloads and prevent later file reads',async()=>{
 for(const action of ['filter','hide','close','dispose']){
  const pending=deferred(),h=await harness({overrides:{commerce_creative_asset_read:()=>pending.promise}});await h.app.enter();const reading=h.click('download','creative:A');await flush();
  if(action==='filter')await h.change('store','account-A');else if(action==='close')await h.click('close');else h.app[action]();
  pending.resolve(packet(png));await reading;assert.equal(h.created.length,0);assert.equal(h.downloads.length,0);
  if(action==='dispose'){assert.equal(Object.values(h.listeners).reduce((sum,items)=>sum+items.length,0),0);await h.app.enter();assert.equal(h.calls.filter(c=>c.name==='commerce_media_library_list').length,1);}
 }
});

test('a late list cannot replace a newer exact-store response and a scope mismatch reports unknown rather than zero',async()=>{
 const pending=deferred();let reads=0;const b=row('B',png,{store_identity:scopeB,product_readable:false});
 const h=await harness({overrides:{commerce_media_library_list:args=>++reads===1?pending.promise:listing([b],args)}});
 const first=h.app.enter();await flush();await h.change('store','unassigned');await flush();assert.match(h.screen,/索引暂不可读/);assert.match(h.screen,/素材总数待核对/);assert.doesNotMatch(h.screen,/共0项/);
 pending.resolve(listing([row('OLD')],{synthetic:false,offset:0,limit:20}));await first;assert.doesNotMatch(h.screen,/approved-OLD/);
});

test('a newer exact store wins a refresh race and source protocol bytes can identify a local PNG with generic MIME',async()=>{
 const pending=deferred();let reads=0;const a=row(),b=row('B',png,{store_identity:scopeB,product_readable:false});
 const h=await harness({overrides:{commerce_media_library_list:args=>++reads===1?listing([a],args):reads===2?pending.promise:listing([b],args),commerce_creative_asset_read:()=>packet(png,0,{mime:'application/octet-stream'})}});
 await h.app.enter();const refresh=h.click('refresh');await flush();await h.change('store','account-B');await flush();
 assert.match(h.screen,/approved-B\.png/);pending.resolve(listing([a],{synthetic:false,offset:0,limit:20}));await refresh;
 assert.match(h.screen,/approved-B\.png/);assert.doesNotMatch(h.screen,/approved-A\.png/);
 await h.click('preview',b.id);assert.equal(h.created.length,1);assert.equal(h.created[0].blob.type,'image/png');
});

test('HTML documents are escaped plain text and downloads request only a verified local binary URL',async()=>{
 const bytes=Buffer.from('<script>alert("untrusted")</script><img src="https://example.invalid/remote">'),item=row('html',bytes,{kind:'document',asset_kind:'production_manifest',display_name:'../../approved.html'});
 const h=await harness({rows:[item],overrides:{commerce_creative_asset_read:()=>packet(bytes,0,{mime:'text/html'})}});await h.app.enter();await h.click('preview',item.id);
 assert.match(h.screen,/&lt;script&gt;/);assert.doesNotMatch(h.screen,/<script|<iframe|<img src="https:/);assert.equal(h.created.length,0);
 await h.click('download',item.id);assert.equal(h.downloads.length,1);assert.match(h.downloads[0].href,/^blob:/);assert.doesNotMatch(h.downloads[0].filename,/[\\/]/);assert.match(h.downloads[0].filename,/\.bin$/);
 assert.equal(h.created[0].blob.type,'application/octet-stream');assert.match(h.screen,/已请求浏览器下载/);h.app.hide();assert.deepEqual(h.revoked,['blob:synthetic-0']);
});

test('hiding during digest suppresses object URLs and text preview remains bounded',async()=>{
 const pending=deferred(),h=await harness({digest:()=>pending.promise});await h.app.enter();const reading=h.click('preview','creative:A');await flush();h.app.hide();pending.resolve(await webcrypto.subtle.digest('SHA-256',png));await reading;assert.equal(h.created.length,0);assert.equal(h.downloads.length,0);
 const text=Buffer.from('x'.repeat(110000)),t=await harness({rows:[row('text',text,{kind:'document'})],overrides:{commerce_creative_asset_read:args=>packet(text,Number(args.offset),{mime:'text/plain'})}});await t.app.enter();await t.click('preview','creative:text');assert.match(t.screen,/仅预览前100000字符/);assert.equal((t.screen.match(/<pre[^>]*>(.*?)<\/pre>/s)||[])[1].length,100000);
});

test('file presence and an approved original request do not promote quality/publication status; inactive products do not navigate',async()=>{
 const item=row('inactive',png,{store_identity:scopeB,product_readable:false,review_status:'local_review_recorded',request_reviews:[{decision:'approved'}]});const h=await harness({rows:[item]});await h.app.enter();
 assert.match(h.screen,/AI生成 · 当前用途未审核/);assert.match(h.screen,/原请求有本地审阅记录/);assert.match(h.screen,/当前用途和发布仍待核对/);assert.doesNotMatch(h.screen,/data-media-library-action="product"/);
 await h.click('product',item.id);assert.equal(h.callbacks.length,0);await h.click('preview',item.id);assert.equal(h.created.length,1);h.app.dispose();assert.deepEqual(h.revoked,['blob:synthetic-0']);assert.equal(h.app.view(),'');
});
