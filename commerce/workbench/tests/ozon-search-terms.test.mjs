import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const path=new URL('../../web/ozon-search-terms-ui.js',import.meta.url);
const source='own_store_product_queries_not_global_hotterms',conn='a'.repeat(64),scope='b'.repeat(64),sha='c'.repeat(64);
const period={date_from:'2026-11-07T00:00:00Z',date_to:'2026-11-14T00:00:00Z'};
const identity=(connection=conn,label='测试店铺 A')=>({platform:'ozon',market:'RU',label,connection_sha256:connection});
const status=()=>({source,connection_sha256:conn,store_identity:identity(),configured:true,scope_status:'ready',scope_error:null,scope_sha256:scope,product_count:8,max_products:100,period:{...period},refresh:null,history:[],snapshot:{id:'snapshot',sha256:sha,period:{...period},observed_at:'2026-11-17T08:00:00Z',fresh_period:true,scope_current:true},external_execution_allowed:false,not_global_hot_terms:true});
const data=()=>({source,connection_sha256:conn,store_identity:identity(),scope_sha256:scope,scope_status:'ready',scope_current:true,availability:'snapshot',snapshot_id:'snapshot',snapshot_sha256:sha,period:{...period},analytics_period:{details:{date_from:'2026-11-07 00:00:00 +0000 UTC',date_to:'2026-11-14 00:00:00 +0000 UTC'}},observed_at:'2026-11-17T08:00:00Z',items:[{sku:123,query:'органайзер 收纳',unique_search_users:0,unique_view_users:null,position:0,view_conversion:null,gmv:10000,currency:'5',order_count:null}],products:[{sku:123,name:'收纳商品',offer_id:'SKU-001'}],total:1,returned:1,refresh:null,raw_fields_preserved:true,unique_users_not_summed:true,gmv_not_used_to_infer_orders:true,external_execution_allowed:false,not_global_hot_terms:true});
const job=(state='queued',connection=conn)=>({id:'job-one',status:state,slot:'2026-11-17',period:{...period},source,connection_sha256:connection,store_identity:identity(connection),product_count:8,created_at:'2026-11-17T08:00:00Z',external_execution_allowed:false,queue_is_not_completion:true});
function fixture({statusValue=status(),dataValue=data(),override}={}){
 assert.ok(fs.existsSync(path),'The independent read-only search-term panel is missing');
 const calls=[],listeners={},timers=new Map();let serial=0,active=true,paints=0;
 const escape=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
 const attrs=o=>Object.entries(o||{}).filter(([,v])=>v!==false&&v!=null).map(([k,v])=>`${k}="${escape(v)}"`).join(' ');
 const ui={escape,button:({label,attrs:a={}})=>`<button ${attrs(a)}>${escape(label)}</button>`,input:o=>`<input ${attrs(o)}>`,select:o=>`<select ${attrs(o)}></select>`,field:(label,html)=>`<label>${escape(label)}${html}</label>`,badge:v=>escape(v),empty:v=>`<p>${escape(v)}</p>`,alert:v=>`<p role="alert">${escape(v)}</p>`,table:(headers,rows,empty)=>`<table><thead>${headers.map(escape).join('|')}</thead><tbody>${rows.join('')}</tbody></table>${rows.length?'':escape(empty)}`};
 const context=vm.createContext({window:{CommerceUI:ui},crypto:{randomUUID:()=> 'query-panel'},document:{activeElement:null,addEventListener:(name,fn)=>listeners[name]=fn,removeEventListener:(name,fn)=>{if(listeners[name]===fn)delete listeners[name]}},setTimeout:fn=>{timers.set(++serial,fn);return serial},clearTimeout:id=>timers.delete(id),Date,Set,Map});
 vm.runInContext(fs.readFileSync(path,'utf8'),context);
 const api=async(name,args)=>{calls.push({name,args:JSON.parse(JSON.stringify(args))});const value=override?.(name,args,calls);if(value!==undefined)return await value;if(name==='commerce_ozon_search_terms_status')return structuredClone(statusValue);if(name==='commerce_ozon_search_terms_search')return structuredClone(dataValue);if(name==='commerce_ozon_search_terms_refresh')return job();throw Error('Unexpected tool');};
 const panel=context.window.CommerceOzonSearchTerms({api,repaint:()=>paints++,isActive:()=>active});
 const fire=async(type,dataset={},value='',extra={},inside=true)=>{const node={dataset,value,closest:selector=>selector.includes('data-ozon-search-terms')?(inside?{}:null):node};const event={target:node,key:'',preventDefault(){this.prevented=true},...extra};await listeners[type]?.(event);return event};
 return {panel,calls,listeners,timers,fire,deactivate:()=>active=false,activate:()=>active=true,paints:()=>paints,tick:async()=>{const [id,fn]=timers.entries().next().value||[];if(fn){timers.delete(id);await fn()}}};
}
test('enter only reads current-store snapshots and preserves raw metrics and periods',async()=>{
 const f=fixture();await f.panel.enter();const html=f.panel.view();assert.match(html,/测试店铺 A/);assert.match(html,/органайзер 收纳/);assert.match(html,/不是全平台热搜|不代表全平台热搜/);assert.match(html,/2026-11-07T00:00:00Z/);assert.match(html,/2026-11-07 00:00:00 \+0000 UTC/);assert.match(html,/>0<|0<\/td>/);assert.match(html,/未知/);assert.match(html,/原始.*码|原码/);assert.match(html,/5/);assert.ok(!html.includes('RUB'));assert.match(html,/不.*相加|不可.*合计/);assert.match(html,/GMV.*不.*订单/);assert.ok(f.calls.every(x=>x.name.endsWith('_status')||x.name.endsWith('_search')));f.panel.dispose();
});
test('Chinese and Russian queries remain exact and IME Enter cannot submit',async()=>{
 const f=fixture();await f.panel.enter();await f.fire('input',{ozonQueryInput:'query-panel'},'收纳 органайзер');const before=f.calls.length;await f.fire('keydown',{ozonQueryInput:'query-panel'},'收纳 органайзер',{key:'Enter',isComposing:true,keyCode:229});assert.equal(f.calls.length,before);await f.fire('keydown',{ozonQueryInput:'query-panel'},'收纳 органайзер',{key:'Enter',isComposing:false});assert.deepEqual(f.calls.filter(x=>x.name.endsWith('_search')).at(-1).args,{query:'收纳 органайзер',limit:20});f.panel.dispose();
});
test('a manual refresh uses only the current scope and queued never means success',async()=>{
 const s=status();const f=fixture({statusValue:s,override:name=>{if(name==='commerce_ozon_search_terms_refresh'){s.refresh=job();return structuredClone(s.refresh)}}});await f.panel.enter();assert.equal(f.calls.filter(x=>x.name.endsWith('_refresh')).length,0);await f.fire('click',{ozonQueryRefresh:'query-panel'});assert.equal(f.calls.filter(x=>x.name.endsWith('_refresh')).length,1);assert.match(f.panel.view(),/已排队|排队中/);assert.match(f.panel.view(),/排队.*不|尚未完成/);assert.deepEqual(f.calls.find(x=>x.name.endsWith('_refresh')).args,{expected_connection_sha256:conn});f.panel.dispose();
});
test('unknown jobs never trigger automatic refresh or become analysis conclusions',async()=>{
 const s=status();s.refresh=job('unknown');s.refresh.error='ozon_query_transport_unknown';const f=fixture({statusValue:s});await f.panel.enter();await f.tick();await f.tick();assert.match(f.panel.view(),/结果未知|结果待核对/);assert.match(f.panel.view(),/不自动重试/);assert.equal(f.calls.filter(x=>x.name.endsWith('_refresh')).length,0);f.panel.dispose();
});
test('permission failure and stale prior snapshot remain separate states',async()=>{
 const s=status();s.refresh={...job('failed'),http_status:403,error:'ozon_auth_or_permission'};s.snapshot.fresh_period=false;const d=data();d.availability='stale_snapshot';const f=fixture({statusValue:s,dataValue:d});await f.panel.enter();const html=f.panel.view();assert.match(html,/权限|授权/);assert.match(html,/陈旧|过期/);assert.match(html,/органайзер/);assert.ok(!html.includes('已完成读取 0'));f.panel.dispose();
});
test('not-collected and complete empty results are not zero demand',async()=>{
 for(const collected of [false,true]){const s=status(),d=data();d.items=[];d.products=[];d.total=collected?0:null;d.returned=0;if(!collected){s.snapshot=null;d.availability='not_collected';d.snapshot_sha256=null;delete d.snapshot_id;}const f=fixture({statusValue:s,dataValue:d});await f.panel.enter();assert.match(f.panel.view(),collected?/无匹配|暂无搜索词/:/尚未采集|暂无完整快照/);assert.match(f.panel.view(),/不代表.*需求.*零|不能.*需求.*零/);f.panel.dispose();}
});
test('cross-account and mixed snapshot responses fail closed without showing foreign rows',async()=>{
 for(const mutate of [d=>{d.connection_sha256='d'.repeat(64);d.store_identity=identity(d.connection_sha256,'Other shop')},d=>d.snapshot_sha256='d'.repeat(64)]){const d=data();mutate(d);const f=fixture({dataValue:d});await f.panel.enter();assert.ok(!f.panel.view().includes('органайзер'));assert.match(f.panel.view(),/已变化|不一致|切换/);f.panel.dispose();}
});
test('late replies after hide or dispose cannot repopulate rows or restart polling',async()=>{
 let resolve;const delayed=new Promise(r=>resolve=r),f=fixture({override:name=>name.endsWith('_search')?delayed:undefined});const entered=f.panel.enter();for(let i=0;i<4;i++)await Promise.resolve();f.panel.hide();resolve(data());await entered;f.activate();assert.ok(!f.panel.view().includes('органайзер'));assert.equal(f.timers.size,0);f.panel.dispose();const count=f.calls.length;await f.panel.enter();assert.equal(f.calls.length,count);assert.equal(Object.keys(f.listeners).length,0);
});
test('polling discovers account switches and clears the previous store rows',async()=>{
 const s=status(),f=fixture({statusValue:s});await f.panel.enter();s.connection_sha256='d'.repeat(64);s.store_identity=identity(s.connection_sha256,'测试店铺 B');s.snapshot=null;s.refresh=null;await f.tick();const html=f.panel.view();assert.ok(!html.includes('органайзер'));assert.match(html,/测试店铺 B/);assert.match(html,/切换|已变化/);assert.equal(f.calls.filter(x=>x.name.endsWith('_refresh')).length,0);f.panel.dispose();
});
test('HTML values are escaped and events outside this panel have no effect',async()=>{
 const d=data();d.items[0].query='<img src=x onerror=alert(1)>';d.products[0].name='<svg onload=alert(1)>';const f=fixture({dataValue:d});await f.panel.enter();assert.ok(!f.panel.view().includes('<img'));assert.ok(!f.panel.view().includes('<svg'));assert.match(f.panel.view(),/&lt;img/);const count=f.calls.length;await f.fire('click',{ozonQueryRefresh:'query-panel'},'',{},false);assert.equal(f.calls.length,count);f.panel.dispose();
});
test('invalid limits and too-long queries do not call the service',async()=>{
 const f=fixture();await f.panel.enter();let count=f.calls.length;await f.fire('change',{ozonQueryLimit:'query-panel'},'101');assert.equal(f.calls.length,count);assert.match(f.panel.view(),/1.*100|数量/);await f.fire('input',{ozonQueryInput:'query-panel'},'中'.repeat(101));count=f.calls.length;await f.fire('click',{ozonQuerySearch:'query-panel'});assert.equal(f.calls.length,count);assert.match(f.panel.view(),/100.*字|长度/);f.panel.dispose();
});
test('a changed current product scope reloads the same snapshot and marks it historical',async()=>{
 const s=status(),d=data(),f=fixture({statusValue:s,dataValue:d});await f.panel.enter();const reads=f.calls.filter(x=>x.name.endsWith('_search')).length;s.scope_sha256='e'.repeat(64);s.snapshot.scope_current=false;d.scope_sha256=s.scope_sha256;d.scope_current=false;await f.tick();assert.equal(f.calls.filter(x=>x.name.endsWith('_search')).length,reads+1);assert.match(f.panel.view(),/商品范围已变化|不是当前完整商品范围/);assert.match(f.panel.view(),/органайзер/);f.panel.dispose();
});
test('a late manual refresh receipt from the previous store cannot label the new store completed',async()=>{
 const s=status();let resolve;const delayed=new Promise(r=>resolve=r);const f=fixture({statusValue:s,override:name=>name.endsWith('_refresh')?delayed:undefined});await f.panel.enter();const clicked=f.fire('click',{ozonQueryRefresh:'query-panel'});for(let i=0;i<4;i++)await Promise.resolve();s.connection_sha256='d'.repeat(64);s.store_identity=identity(s.connection_sha256,'测试店铺 B');s.snapshot=null;s.refresh=null;resolve(job('succeeded'));await clicked;const html=f.panel.view();assert.match(html,/测试店铺 B/);assert.ok(!html.includes('органайзер'));assert.ok(!html.includes('原读取任务已完成'));assert.equal(f.calls.filter(x=>x.name.endsWith('_refresh')).length,1);f.panel.dispose();
});
test('inconsistent scope flags and malformed product rows cannot be rendered as a verified snapshot',async()=>{
 for(const mutate of [d=>d.scope_current=false,d=>d.products=[null],d=>d.returned=0]){const d=data();mutate(d);const f=fixture({dataValue:d});await f.panel.enter();assert.ok(!f.panel.view().includes('органайзер'));assert.match(f.panel.view(),/已变化|不可读|核对/);f.panel.dispose();}
});
test('renaming a store without changing its fingerprint keeps the same scoped rows',async()=>{
 const s=status(),f=fixture({statusValue:s});await f.panel.enter();s.store_identity.label='店铺新名称';await f.tick();assert.match(f.panel.view(),/店铺新名称/);assert.match(f.panel.view(),/органайзер/);assert.ok(!f.panel.view().includes('已清除原结果'));f.panel.dispose();
});
test('a rejected connection CAS never retries the read against a new store',async()=>{
 const f=fixture({override:name=>{if(name.endsWith('_refresh'))throw Error('ozon_query_connection_changed')}});await f.panel.enter();await f.fire('click',{ozonQueryRefresh:'query-panel'});await f.tick();assert.equal(f.calls.filter(x=>x.name.endsWith('_refresh')).length,1);assert.deepEqual(f.calls.find(x=>x.name.endsWith('_refresh')).args,{expected_connection_sha256:conn});assert.match(f.panel.view(),/店铺已切换|上一店铺/);assert.ok(!f.panel.view().includes('已返回原读取任务回执'));f.panel.dispose();
});
test('successful original job loads its new matching snapshot without another platform read',async()=>{
 const s=status(),d=data();const f=fixture({statusValue:s,dataValue:d,override:name=>{if(name.endsWith('_refresh')){s.refresh=job('succeeded');s.snapshot.sha256='f'.repeat(64);d.snapshot_sha256=s.snapshot.sha256;d.items[0].query='новый запрос';return structuredClone(s.refresh)}}});await f.panel.enter();await f.fire('click',{ozonQueryRefresh:'query-panel'});const html=f.panel.view();assert.match(html,/原读取任务已完成/);assert.match(html,/новый запрос/);assert.ok(!html.includes('органайзер'));assert.equal(f.calls.filter(x=>x.name.endsWith('_refresh')).length,1);assert.equal(f.calls.filter(x=>x.name.endsWith('_search')).length,2);f.panel.dispose();
});
test('repeat clicks while a manual read is pending cannot create another read',async()=>{
 const s=status();let resolve;const delayed=new Promise(r=>resolve=r),f=fixture({statusValue:s,override:name=>name.endsWith('_refresh')?delayed:undefined});await f.panel.enter();const first=f.fire('click',{ozonQueryRefresh:'query-panel'});for(let i=0;i<4;i++)await Promise.resolve();await f.fire('click',{ozonQueryRefresh:'query-panel'});await f.fire('click',{ozonQueryReload:'query-panel'});assert.equal(f.calls.filter(x=>x.name.endsWith('_refresh')).length,1);s.refresh=job('running');resolve(job());await first;assert.match(f.panel.view(),/正在读取|尚未完成/);assert.equal(f.calls.filter(x=>x.name.endsWith('_refresh')).length,1);f.panel.dispose();
});
