// Exercise the actual module's event handlers, navigation and async boundaries.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const source=(await readFile(new URL('../web/intel-dashboard-ui.js',import.meta.url),'utf8'))+'\n'+(await readFile(new URL('../web/intel-ui.js',import.meta.url),'utf8'));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const attrs=value=>Object.entries(value||{}).map(([k,v])=>v===false||v===undefined?'':`${k}="${esc(v===true?'':v)}"`).join(' ');
const item=(id='a')=>({id:id.repeat(24),record_sha256:id.repeat(64),source:'wto',title:'Trade bulletin '+id,
  country:null,published:1700000000,collected_at:'2026-01-01T00:00:00Z',url:'https://example.org/'+id,
  category:'trade',location:null,is_viewed:false,is_bookmarked:false,in_latest_snapshot:true,
  revision_count:1,revisions:[],review_task:null});
function fixture(overrides={},options={}){
  const windowEvents=new Map(),events=new Map(), timers=[],calls=[],toasts=[],opened=[];let html='',intel;
  const rows=[item(),item('b')],scroll={scrollTop:230},nodes=new Map();
  const document={activeElement:null,querySelectorAll:()=>[],addEventListener(type,fn){events.set(type,[...(events.get(type)||[]),fn])},
    querySelector(selector){if(selector==='.main-scroll')return scroll;if(selector==='#intel-list-scroll')return {scrollTop:40};
      if(selector==='#intel-reader-title'&&html.includes('intel-reader-title'))return {focus(){document.activeElement={id:'intel-reader-title'}}};
      if((selector.startsWith('#intel-row-')||selector.startsWith('#intel-panel-row-'))&&html.includes(selector.slice(1)))return {focus(){document.activeElement={id:selector.slice(1)}}};
      return nodes.get(selector)||null;},getElementById(id){return this.querySelector('#'+id)}};
  const ui={icon:()=>'',badge:label=>`<span>${esc(label)}</span>`,alert:text=>`<div role="alert">${text}</div>`,
    field:(label,control)=>`<label>${label}${control}</label>`,input:props=>`<input ${attrs(props)}>`,
    select:props=>`<select ${attrs(props)}></select>`,button:({label,attrs:a})=>`<button ${attrs(a)}>${label}</button>`};
  const window={CommerceUI:ui,CommerceSocial:()=>({view:()=>'',aside:()=>'',enter(){}}),addEventListener(type,fn){windowEvents.set(type,[...(windowEvents.get(type)||[]),fn])}};
  let liveOptions;if(options.live)window.CommerceIntelLive=opts=>{liveOptions=opts;return {enter:async()=>{},read:async()=>{},source:()=>null,ribbon:()=>'',panel:()=>'',mapMarkers:()=>'',popup:()=>'',dismiss(){},hasSelection:()=>false}};
  vm.runInNewContext(source,{window,document,location:{hash:''},Date,URL,crypto:globalThis.crypto,
    requestAnimationFrame:fn=>queueMicrotask(fn),setInterval:(fn,ms)=>timers.push({fn,ms}),setTimeout,clearTimeout,console});
  const sources=[{id:'wto',name:'WTO',status:'ok',last_success:1700000000,cached_items:2}];
  const result={items:rows,total:2,offset:0,next_cursor:null,stats:{unviewed:2,bookmarked:0,geolocated:0},markers:[],sources,archive:{archived:2}};
  const prefs={layers:['earthquake','flood','storm','fire','drought','volcano','tsunami','other','waterways'],panels:['trade','macro','energy','logistics'].map(id=>({id,visible:true,collapsed:false,wide:false})),language:'zh',time:'all',region:'global',link_map:false};
  const handlers={commerce_intel_dashboard_get:async()=>({revision:0,preferences:prefs,layers:[],regions:{global:{label:'全球',x:0,y:0,w:720,h:360}},references:[]}),commerce_intel_dashboard_update:async args=>({revision:1,preferences:args.preferences}),commerce_intel_search:async()=>structuredClone(result),commerce_intel_watch_list:async()=>({watches:[]}),
    commerce_crawler_list:async()=>({jobs:[],alerts:[],capacity:null,endurance:null}),commerce_worldmonitor_status:async()=>({}),
    commerce_intel_item_get:async args=>structuredClone(rows.find(r=>r.id===args.item_id)),
    commerce_intel_item_update:async args=>({...structuredClone(rows.find(r=>r.id===args.item_id)),is_viewed:true}),
    commerce_intel_article_list:async()=>({articles:[]}),
    commerce_intel_article_batch_list:async()=>({batches:[]}),
    commerce_intel_reading_get:async()=>({id:'c'.repeat(32),status:'queued',readings:[]}),...overrides};
  const api=async(name,args={})=>{calls.push({name,args});if(!handlers[name])throw Error('Unexpected API '+name);return handlers[name](args)};
  const repaint=()=>{html=intel.view()+intel.aside()};
  intel=window.CommerceIntel({api,esc,toast:x=>toasts.push(x),repaint,isActive:()=>true,
    modal(){},closeModal(){},onExposure:ref=>opened.push(ref)});
  const click=async(action,dataset={})=>{const target={id:dataset.elementId,dataset:{intelAction:action,...dataset},disabled:false,focus(){}};
    for(const fn of events.get('click')||[])fn({target:{closest:s=>s.includes('data-intel-action')||s.includes('data-intel-dashboard')&&dataset.intelDashboard?target:null}});
    await tick();await tick();};
  return {intel,calls,toasts,rows,result,nodes,document,opened,click,liveBlocked:()=>liveOptions.isBlocked(),dispatch(type,event){for(const fn of events.get(type)||[])fn(event)},blur(){for(const fn of windowEvents.get('blur')||[])fn()},pressKey(key){for(const fn of events.get('keydown')||[])fn({key,preventDefault(){},target:{id:'',matches:()=>false}})},get html(){return html},
    async enter(){await intel.enter();await tick();await tick();repaint()},
    async poll(){for(const t of timers.filter(t=>t.ms===3000))await t.fn();await tick();await tick();}};
}

test('dashboard is the default and opening/returning from reading preserves its map, position and focus',async()=>{
  const f=fixture();await f.enter();
  assert.ok(f.html.includes('intel-list-scroll'));
  assert.ok(f.html.includes('id="intel-map-svg"'),'The global dashboard lost its default map');
  assert.ok(f.html.includes('intel-topic-panels'),'The dashboard lost its topic panels');
  assert.ok(f.html.includes('data-intel-section="social"'),'The social observation view became unreachable');
  await f.click('',{intelId:f.rows[0].id});
  assert.ok(f.html.includes('id="intel-reader-title"'),'The selected record is still rendered in a remote aside');
  assert.equal(f.document.activeElement?.id,'intel-reader-title');
  await f.click('reader-back');
  assert.ok(f.html.includes('intel-list-scroll'));
  assert.equal(f.document.activeElement?.id,'intel-row-'+f.rows[0].id);
  assert.ok(f.html.includes('id="intel-map-svg"'));
});

test('topic panels show real scoped results and their more action opens the same category list',async()=>{
  const f=fixture({commerce_intel_search:async args=>({items:args.category==='macro'?[{...item('d'),category:'macro',title:'Central bank bulletin'}]:[],total:args.category==='macro'?7:0,offset:0,next_cursor:null,stats:{unviewed:0,bookmarked:0,geolocated:0},markers:[],sources:[],archive:{archived:7}})});
  await f.enter();
  assert.ok(f.html.includes('Central bank bulletin'));
  assert.ok(f.html.includes('7 条'));
  await f.click('category',{category:'macro'});
  assert.equal(f.calls.filter(x=>x.name==='commerce_intel_search').at(-1).args.category,'macro');
  assert.ok(f.html.includes('Central bank bulletin'));
});

test('a focused topic can open the full category list and exit the focus view',async()=>{
  const f=fixture();await f.enter();await f.click('',{intelDashboard:'focus',panel:'trade'});
  assert.ok(f.html.includes('intel-focused-view'));
  await f.click('category',{category:'trade'});
  assert.ok(!f.html.includes('intel-focused-view'));
  assert.ok(f.html.includes('intel-list-scroll'));
});

test('the canonical dashboard response shares one snapshot across map, list and panels',async()=>{
  const f=fixture();f.result.panels=Object.fromEntries(['trade','macro','energy','logistics'].map(k=>[k,{items:f.rows,total:2}]));
  await f.enter();assert.equal(f.calls.filter(c=>c.name==='commerce_intel_search').length,1);
  assert.equal(f.calls.find(c=>c.name==='commerce_intel_search').args.include_panels,true);
});

test('Escape closes a geographic reference popover before leaving the map',async()=>{
  const preferences={layers:['waterways'],panels:['trade','macro','energy','logistics'].map(id=>({id,visible:true,collapsed:false,wide:false})),language:'zh',time:'all',region:'global',link_map:false};
  const f=fixture({commerce_intel_dashboard_get:async()=>({revision:0,preferences,layers:[],regions:{},references:[{id:'ref-test',title:'合成参考点',layer:'waterways',location:{lon:0,lat:0},source_url:'https://example.org/'}]})});
  const popup={innerHTML:''};f.nodes.set('#intel-cluster-popup',popup);await f.enter();
  await f.click('',{intelReference:'ref-test'});assert.ok(popup.innerHTML.includes('运行状态未知'));
  f.pressKey('Escape');assert.equal(popup.innerHTML,'');assert.ok(f.html.includes('id="intel-map-svg"'));
});

test('list view is optional and returning to dashboard reloads the actual map and panels',async()=>{
  const f=fixture();await f.enter();await f.click('map-toggle');
  assert.ok(!f.html.includes('id="intel-map-svg"'));
  await f.click('map-toggle');
  assert.ok(f.html.includes('id="intel-map-svg"')&&f.html.includes('intel-topic-panels'));
  assert.equal(f.calls.filter(x=>x.name==='commerce_intel_search'&&x.args.category==='all').at(-1).args.include_map,true);
});

test('one failed topic source does not hide the map or the other topic panels',async()=>{
  const f=fixture({commerce_intel_search:async args=>{
    if(args.category==='energy')throw Error('source_unavailable');
    return {items:[item()],total:1,offset:0,next_cursor:null,stats:{unviewed:1,bookmarked:0,geolocated:0},markers:[],sources:[],archive:{archived:1}};
  }});await f.enter();
  assert.ok(f.html.includes('读取失败：source_unavailable'));
  assert.ok(f.html.includes('id="intel-map-svg"')&&f.html.includes('Trade bulletin a'));
});

test('returning from a topic headline restores focus to that headline',async()=>{
  const f=fixture();await f.enter();
  const origin='intel-panel-row-'+f.rows[0].id;
  await f.click('',{intelId:f.rows[0].id,elementId:origin});await f.click('reader-back');
  assert.equal(f.document.activeElement?.id,origin);
});

test('late topic results cannot replace panels from a newer dashboard search',async()=>{
  let finishOld;let first=true;
  const result=title=>({items:[{...item(),title}],total:1,offset:0,next_cursor:null,stats:{unviewed:1,bookmarked:0,geolocated:0},markers:[],sources:[],archive:{archived:1}});
  const f=fixture({commerce_intel_search:async args=>{
    if(args.category==='trade'&&first){first=false;return new Promise(resolve=>{finishOld=resolve})}
    return result('Current bulletin');
  }});await f.enter();await f.click('search');finishOld(result('Old bulletin'));await tick();await tick();
  assert.ok(f.html.includes('Current bulletin')&&!f.html.includes('Old bulletin'));
});

test('an explicit layout switch supersedes a pending search and requests the matching map data',async()=>{
  let pause=false;const pending=[];
  const result={items:[],total:0,offset:0,next_cursor:null,stats:{unviewed:0,bookmarked:0,geolocated:0},markers:[],sources:[],archive:{archived:0}};
  const f=fixture({commerce_intel_search:async args=>pause&&args.category==='all'?new Promise(resolve=>pending.push(resolve)):structuredClone(result)});
  await f.enter();pause=true;await f.click('search');await f.click('map-toggle');await f.click('map-toggle');
  const calls=f.calls.filter(x=>x.name==='commerce_intel_search'&&x.args.category==='all');
  assert.equal(calls.length,4,'Explicit view changes were swallowed by a pending query');
  assert.equal(calls.at(-2).args.include_map,false);assert.equal(calls.at(-1).args.include_map,true);
  for(const resolve of pending)resolve(structuredClone(result));await tick();
});

test('returning from a viewed record still restores keyboard focus when it leaves the unread list',async()=>{
  const f=fixture();await f.enter();
  f.nodes.set('#intel-query',{focus(){f.document.activeElement={id:'intel-query'}}});
  f.result.items=[];
  await f.click('',{intelId:f.rows[0].id});await f.click('reader-back');
  assert.equal(f.document.activeElement?.id,'intel-query');
});

test('refresh starts a real persistent collection and reports pending until import succeeds',async()=>{
  let status='queued';const f=fixture({commerce_crawler_start:async()=>({id:'job-a',status,progress:{processed:0,total:8,successful:0}}),
    commerce_crawler_get:async()=>({id:'job-a',status,progress:{processed:status==='succeeded'?8:0,total:8,successful:status==='succeeded'?8:0}})});
  await f.enter();await f.click('refresh');
  assert.equal(f.calls.filter(x=>x.name==='commerce_crawler_start').length,1);
  assert.equal(f.calls.filter(x=>x.name==='commerce_intel_refresh').length,0);
  assert.ok(f.html.includes('排队'));
  assert.ok(!f.toasts.some(x=>x.includes('完成')));
  status='succeeded';await f.poll();
  assert.ok(f.html.includes('已采集并导入'));
  assert.ok(f.calls.filter(x=>x.name==='commerce_intel_search').length>=2);
});

test('an unconfirmed collection submission retries with the same idempotency key',async()=>{
  let attempts=0;const f=fixture({commerce_crawler_start:async()=>{if(++attempts===1)throw Error('Failed to fetch');return {id:'job-b',status:'queued',progress:{processed:0,total:8,successful:0}}}});
  await f.enter();await f.click('refresh');await f.click('refresh');
  const calls=f.calls.filter(x=>x.name==='commerce_crawler_start');
  assert.equal(calls.length,2);
  assert.equal(calls[0].args.idempotency_key,calls[1].args.idempotency_key);
});

test('explicit import reads the existing snapshot and never queues new collection',async()=>{
  const f=fixture({commerce_intel_refresh:async()=>({status:'completed',sources:[{id:'fed',status:'ok',last_success:1700000000}]})});
  await f.enter();await f.click('refresh-one',{source:'fed'});
  assert.equal(f.calls.filter(x=>x.name==='commerce_intel_refresh').length,1);
  assert.ok(!f.calls.some(x=>x.name==='commerce_crawler_start'));
});

test('failed collection retains the readable snapshot and offers an explicit retry',async()=>{
  const job={id:'job-failed',status:'failed',error:'collection_source_check_failed',progress:{processed:8,total:8,successful:6}};
  const f=fixture({commerce_crawler_start:async()=>job,commerce_crawler_get:async()=>job});
  await f.enter();await f.click('refresh');
  assert.ok(f.html.includes('Trade bulletin a'));
  assert.ok(f.html.includes('旧快照保留')&&f.html.includes('重试采集'));
});

test('a late old-job poll cannot replace the newer explicitly submitted collection',async()=>{
  let submissions=0,reads=0,finishOld;
  const old={id:'old-job',status:'succeeded',progress:{processed:8,total:8,successful:8}};
  const current={id:'new-job',status:'queued',progress:{processed:0,total:1,successful:0}};
  const f=fixture({commerce_crawler_start:async()=>++submissions===1?old:current,
    commerce_crawler_get:async args=>{if(args.job_id==='new-job')return current;if(++reads===1)return old;return new Promise(resolve=>{finishOld=resolve})}});
  await f.enter();await f.click('refresh');await f.click('source-panel');
  await f.click('collect',{source:'fed'});finishOld(old);await tick();await tick();
  await f.click('reader-back');await f.poll();
  assert.ok(f.calls.some(x=>x.name==='commerce_crawler_get'&&x.args.job_id==='new-job'),
    'Late old data stopped polling the newly accepted job');
});

test('Chinese reading sends only displayed source revisions and keeps pending status visible',async()=>{
  const f=fixture({commerce_intel_reading_start:async()=>({id:'c'.repeat(32),status:'queued',readings:[]})});
  await f.enter();await f.click('reading-start');
  const request=f.calls.find(x=>x.name==='commerce_intel_reading_start');
  assert.ok(request,'No explicit Chinese reading request was submitted');
  assert.deepEqual(JSON.parse(JSON.stringify(request?.args.input)),{records:f.rows.map(r=>({item_id:r.id,record_sha256:r.record_sha256}))});
  assert.ok(f.html.includes('中文标题')&&f.html.includes('排队'));
});

test('business relationship navigation passes the exact selected revision without creating an assessment',async()=>{
  const f=fixture();await f.enter();await f.click('',{intelId:f.rows[0].id});await f.click('exposure');
  assert.equal(f.opened[0]?.item_id,f.rows[0].id);
  assert.equal(f.opened[0]?.record_sha256,f.rows[0].record_sha256);
  assert.ok(!f.calls.some(x=>x.name==='commerce_exposure_assess'));
});

test('fulltext snippets stay escaped and reader shows the exact result evidence',async()=>{
  const f=fixture({commerce_intel_item_get:async()=>item(),commerce_intel_item_update:async()=>({...item(),is_viewed:true})});
  f.rows[0].search_match={material_sha256:'c'.repeat(64),evidence:[{kind:'translation',snippet:'合成关税 <script>unsafe</script>',article_id:'d'.repeat(32),record_sha256:'a'.repeat(64),text_sha256:'e'.repeat(64),independently_verified:false}]};
  await f.enter();
  assert.ok(f.html.includes('intel-search-match'),'result needs a visible hit explanation');
  assert.ok(f.html.includes('&lt;script>unsafe&lt;/script>'));
  assert.ok(!f.html.includes('<script>unsafe</script>'));
  await f.click('',{intelId:f.rows[0].id});
  assert.ok(f.html.includes('本次检索依据'));
  assert.ok(f.html.includes('e'.repeat(64)));
  assert.ok(f.html.includes('尚未独立核实'));
});

test('body batch requires a preview and reports stored captures separately from current coverage',async()=>{
  const plan={filters:{query:'',source:'all',scope:'latest'},limit:20,sha256:'d'.repeat(64),records:[{item_id:'a'.repeat(24),record_sha256:'a'.repeat(64),source:'wto',title:'Synthetic'}],coverage:{matched:2,current_ready:0,unsupported:1,invalid_url:0,missing_supported:1}};
  const job={id:'e'.repeat(32),status:'completed',revision:3,records:[{...plan.records[0],status:'ready',source_record_changed:false}],counts:{captured:1,current_ready:1,failed:0,pending:0,superseded:0}};
  const f=fixture({commerce_intel_article_plan:async()=>plan,commerce_intel_article_batch_start:async()=>job});
  await f.enter();assert.ok(f.html.includes('补齐正文'));
  await f.click('article-plan');assert.ok(!f.calls.some(r=>r.name==='commerce_intel_article_batch_start'));
  await f.click('article-batch-start');
  assert.equal(f.calls.find(r=>r.name==='commerce_intel_article_batch_start').args.expected_plan_sha256,plan.sha256);
  assert.ok(f.html.includes('已留存 1')&&f.html.includes('当前可用 1'));
});

test('uncertain batch start can be found through explicit history without resubmitting',async()=>{
  let accepted=false;
  const job={id:'f'.repeat(32),status:'completed',revision:2,filters:{source:'fed'},created_at:1700000000,records:[],counts:{captured:1,current_ready:1,failed:0,pending:0,superseded:0}};
  const f=fixture({commerce_intel_article_plan:async()=>({filters:{},limit:20,sha256:'a'.repeat(64),records:[{source:'fed',title:'Synthetic'}],coverage:{matched:1,current_ready:0,missing_supported:1,unsupported:0,invalid_url:0}}),
    commerce_intel_article_batch_start:async()=>{accepted=true;throw Error('synthetic_response_lost');},commerce_intel_article_batch_list:async()=>({batches:accepted?[job]:[]}),commerce_intel_article_batch_get:async()=>job});
  await f.enter();assert.ok(f.html.includes('正文批次'));
  await f.click('article-plan');await f.click('article-batch-start');
  await f.click('article-batch-history');await f.click('article-batch-select',{batch:job.id});
  assert.equal(f.calls.filter(r=>r.name==='commerce_intel_article_batch_start').length,1);
  assert.ok(f.html.includes('当前可用 1'));
});

async function mapGestureFixture({captureThrows=false,width=720}={}){
  const f=fixture({}, {live:true});await f.enter();let viewBox='';
  const map={isConnected:true,getBoundingClientRect:()=>({width}),setAttribute(name,value){if(name==='viewBox')viewBox=value},setPointerCapture(){if(captureThrows)throw Error('InvalidStateError')},releasePointerCapture(){}};
  f.nodes.set('#intel-map-svg',map);await f.click('zoom-in');
  const target={closest:selector=>selector==='#intel-map-svg'?map:null};
  const event=(x,buttons=1)=>({target,pointerId:7,button:0,buttons,clientX:x,clientY:100});
  return {...f,map,event,viewBox:()=>viewBox};
}
test('map capture failure stays usable and a missed pointerup cannot block later clicks',async()=>{
  const f=await mapGestureFixture({captureThrows:true});
  f.dispatch('pointerdown',f.event(100));assert.equal(f.liveBlocked(),true);
  assert.doesNotThrow(()=>f.dispatch('pointermove',f.event(140)));
  f.dispatch('pointermove',f.event(150,0));await new Promise(r=>setTimeout(r,2));
  assert.equal(f.liveBlocked(),false);assert.doesNotMatch(f.viewBox(),/NaN|Infinity/);
});
test('lost capture and leaving the window release the map interaction lock',async()=>{
  const f=await mapGestureFixture();
  f.dispatch('pointerdown',f.event(100));f.dispatch('pointermove',f.event(140));
  f.dispatch('lostpointercapture',{pointerId:7,target:f.map});await new Promise(r=>setTimeout(r,2));
  assert.equal(f.liveBlocked(),false);
  f.dispatch('pointerdown',f.event(100));f.dispatch('pointermove',f.event(140));f.blur();await new Promise(r=>setTimeout(r,2));
  assert.equal(f.liveBlocked(),false);
});
test('a hidden map with zero width cannot start a nonfinite pan',async()=>{
  const f=await mapGestureFixture({width:0});f.dispatch('pointerdown',f.event(100));f.dispatch('pointermove',f.event(140));
  assert.equal(f.liveBlocked(),false);assert.doesNotMatch(f.viewBox(),/NaN|Infinity/);
});
