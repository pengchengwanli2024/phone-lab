import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const code=await readFile(new URL('../web/intel-live-ui.js',import.meta.url),'utf8');
function fixture({api,localEvaluation=false}={}){
  const events={},calls=[],timers=[],window={CommerceUI:{input:()=>'<input>',button:({label,attrs={}})=>`<button ${Object.entries(attrs).map(([k,v])=>`${k}="${v}"`).join(' ')}>${label}</button>`}};
  const flight={id:'flight-abcdef',kind:'flight',callsign:'TEST',location:{lon:121,lat:31},observed_at:100,speed_kmh:360,source_url:'https://opensky-network.org/'};
  const quote={id:'SPX',name:'标普500',price:100,change_percent:-1,currency:'USD',symbol:'SPX',series:[99,100],observed_at:100,source_url:'https://finance.yahoo.com/'};
  const state={sources:{markets:{items:[quote],status:'ready'},flights:{items:[flight],matched:1,status:'ready'},vessels:{items:[],status:'requires_config'}}};
  if(localEvaluation)Object.assign(state.sources.flights,{mode:'local_evaluation',status:'evaluation',next_refresh:0,interval_seconds:900});
  const document={activeElement:null,hidden:false,querySelector:()=>null,getElementById:()=>null,addEventListener:(k,f)=>events[k]=f};
  vm.runInNewContext(code,{window,document,requestAnimationFrame:f=>f(),setInterval:f=>timers.push(f),Date,Map,Number,JSON,MouseEvent:class{}});
  const controller=window.CommerceIntelLive({api:async(name,args)=>{calls.push({name,args});return api?await api(name,args):structuredClone(state)},esc:String,repaint(){},bounds:()=>({west:-180,east:180,north:90,south:-90}),preferences:()=>({layers:['flights']}),isActive:()=>true,onLocate(){}});
  const click=(action,key)=>events.click({target:{closest:()=>({dataset:{intelLive:action,key}})}});
  return {controller,calls,click,document,timers,state};
}
test('quotes open with actual source time without becoming location popups',async()=>{
  const f=fixture();await f.controller.read();f.click('quote','SPX');
  assert.match(f.controller.panel(),/较|观测/);assert.equal(f.controller.popup(),'');assert.equal(f.controller.hasSelection(),false);
  assert.match(f.controller.panel(),/Yahoo|finance.yahoo/);
});
test('position markers use enabled layers and keyboard-addressable observations',async()=>{
  const f=fixture();await f.controller.read();const html=f.controller.mapMarkers({w:720},1);
  assert.match(html,/data-intel-live="map"/);assert.match(html,/tabindex="0"/);
  f.click('map','flight:21:4');assert.equal(f.controller.hasSelection(),true);assert.match(f.controller.popup(),/360/);
  f.controller.clear();assert.equal(f.controller.popup(),'');
});
test('missing AIS credentials show a configuration path rather than fabricated vessels',async()=>{
  const f=fixture();await f.controller.read();f.click('tab','vessels');
  assert.match(f.controller.panel(),/AISSTREAM_API_KEY/);assert.match(f.controller.panel(),/待配置/);
  assert.ok(f.calls.every(c=>c.name==='commerce_intel_live_get'));
});
test('expired browser login is distinct from an unavailable observation snapshot',async()=>{
  const expired=fixture({api:async()=>{throw Error('authentication_required')}});await expired.controller.read();
  assert.match(expired.controller.panel(),/登录连接已过期.*本机工作台入口重新打开/);
  const unavailable=fixture({api:async()=>{throw Error('request_failed')}});await unavailable.controller.read();
  assert.match(unavailable.controller.panel(),/快照暂时无法读取/);
});
test('background polling pauses while a user is editing a field',async()=>{
  const f=fixture();await f.controller.read();f.document.activeElement={matches:()=>true};await f.timers[0]();
  assert.equal(f.calls.length,1);
});
test('late viewport reads cannot replace newer position filters',async()=>{
  const pending=[];const f=fixture({api:()=>new Promise(resolve=>pending.push(resolve))});
  const old=f.controller.read(),latest=f.controller.read();
  pending[1]({sources:{flights:{items:[],matched:2}}});await latest;
  pending[0]({sources:{flights:{items:[],matched:100}}});await old;
  assert.equal(f.controller.source('flights').matched,2);
});
test('local development samples require a manual click and never enter automatic polling',async()=>{
  const f=fixture({localEvaluation:true});await f.controller.read();await f.timers[0]();
  assert.ok(f.calls.every(c=>c.name==='commerce_intel_live_get'));
  f.click('tab','flights');await new Promise(setImmediate);
  assert.match(f.controller.panel(),/读取测试样本/);assert.match(f.controller.panel(),/本地开发测试/);
  f.click('refresh');await new Promise(setImmediate);
  const request=f.calls.find(c=>c.name==='commerce_intel_live_refresh');
  assert.equal(request.args.source,'flights');assert.equal(request.args.evaluation,true);
});

test('local sessions expose start and stop without claiming operating authorization',async()=>{
  const f=fixture({localEvaluation:true});await f.controller.read();f.click('tab','flights');await new Promise(setImmediate);
  assert.match(f.controller.panel(),/连续测试60分钟/);
  f.click('session-start');await new Promise(setImmediate);
  assert.deepEqual(structuredClone(f.calls.find(c=>c.name==='commerce_intel_live_refresh').args),{source:'flights',evaluation_session:'start',minutes:60});
  f.state.sources.flights.evaluation_session={active:true,until:Date.now()/1000+3600};
  await f.controller.read();assert.match(f.controller.panel(),/停止连续测试/);
  f.click('session-stop');await new Promise(setImmediate);
  assert.equal(f.calls.filter(c=>c.name==='commerce_intel_live_refresh').at(-1).args.evaluation_session,'stop');
});
test('session polling follows the deadline and cannot resume a stopped test',async()=>{
  const f=fixture({localEvaluation:true});f.state.sources.flights.evaluation_session={active:true,until:Date.now()/1000+60};
  await f.controller.read();await f.timers[0]();
  assert.equal(f.calls.filter(c=>c.name==='commerce_intel_live_refresh').length,1);
  f.state.sources.flights.evaluation_session.active=false;await f.controller.read();await f.timers[0]();
  assert.equal(f.calls.filter(c=>c.name==='commerce_intel_live_refresh').length,1);
});
test('expired observations cannot remain in an open location detail',async()=>{
  const f=fixture();await f.controller.read();f.controller.mapMarkers({w:720},1);f.click('map','flight:21:4');
  assert.ok(f.controller.hasSelection());
  Object.assign(f.state.sources.flights,{items:[],availability:'expired',matched:0});await f.controller.read();
  assert.equal(f.controller.hasSelection(),false);assert.match(f.controller.panel(),/位置样本已过期/);
});
test('out of view is distinct from a missing or expired sample',async()=>{
  const f=fixture();Object.assign(f.state.sources.flights,{items:[],matched:0,fresh_count:32,availability:'outside_filter'});
  await f.controller.read();f.click('tab','flights');await new Promise(setImmediate);
  assert.match(f.controller.panel(),/已有 32 条有效位置/);
  assert.doesNotMatch(f.controller.panel(),/样本已过期/);
});
test('a narrow viewport shows matched positions separately from the valid snapshot',async()=>{
  const f=fixture();Object.assign(f.state.sources.flights,{matched:1,fresh_count:5000});
  await f.controller.read();f.click('tab','flights');await new Promise(setImmediate);
  assert.match(f.controller.panel(),/当前地图视野 1 条/);assert.match(f.controller.panel(),/快照内有效 5,000 条/);
});
test('unknown quote change has no direction color and FX retains four decimals',async()=>{
  const f=fixture();Object.assign(f.state.sources.markets.items[0],{change_percent:null,symbol:'CNY=X',price:7.1234});
  await f.controller.read();assert.match(f.controller.ribbon(),/7.1234/);assert.doesNotMatch(f.controller.ribbon(),/is-up|is-down/);
});

test('GPU-capable servers negotiate a bounded position budget while older servers keep the old contract',async()=>{
 const f=fixture();f.state.position_capacity=10000;f.state.position_limit=600;
 await f.controller.read();assert.equal(f.calls.length,2);assert.equal(f.calls[0].args.limit,undefined);assert.equal(f.calls[1].args.limit,10000);
 await f.controller.read();assert.equal(f.calls.at(-1).args.limit,10000);
});
