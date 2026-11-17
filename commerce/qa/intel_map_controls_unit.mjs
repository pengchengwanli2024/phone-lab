import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source=await readFile(new URL('../web/intel-dashboard-ui.js',import.meta.url),'utf8');
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
const attrs=a=>Object.entries(a||{}).filter(([,v])=>v!==false&&v!==undefined).map(([k,v])=>`${k}="${esc(v===true?'':v)}"`).join(' ');
const ui={button:({label,attrs:a})=>`<button ${attrs(a)}>${label}</button>`,select:a=>`<select ${attrs(a)}></select>`,icon:()=>''};
const preferences=()=>({layers:['earthquake'],panels:[],language:'zh',time:'all',region:'global',link_map:false});
const catalog=[{id:'earthquake',name:'地震',sources:'usgs',kind:'event'},{id:'flights',name:'航班',sources:'opensky',kind:'live_observation'}];
function dashboardFixture({save}={}){
  const events=new Map(),calls=[];
  const document={activeElement:null,querySelector:()=>null,querySelectorAll:()=>[],getElementById:()=>null,addEventListener:(type,fn)=>events.set(type,fn)};
  const window={CommerceUI:ui,addEventListener(){}};vm.runInNewContext(source,{window,document,requestAnimationFrame:fn=>fn()});
  let stored={revision:0,preferences:preferences(),layers:catalog,regions:{},references:[]};
  const controller=window.CommerceIntelDashboard({api:async(name,args)=>{calls.push({name,args});if(name==='commerce_intel_dashboard_get')return structuredClone(stored);if(save)return save(args);stored={...stored,revision:stored.revision+1,preferences:args.preferences};return structuredClone(stored)},esc,repaint(){},isActive:()=>true});
  return {controller,calls,change:async target=>{events.get('change')({target});await new Promise(setImmediate)},click:async action=>{const target={dataset:{intelDashboard:action},disabled:false};events.get('click')({target:{closest:()=>target}});await new Promise(setImmediate)}};
}
test('map layers stay directly reachable when the secondary view options are closed',async()=>{
  const f=dashboardFixture();await f.controller.enter();const html=f.controller.controls({},[]);
  assert.ok(html.indexOf('id="intel-layer-picker"')<html.indexOf('id="intel-control-options"'),'Layer controls are hidden inside secondary view options');
  assert.ok(html.includes('地图图层 1/2'));
  assert.ok(html.includes('尚无观测'),'The layer picker hides unavailable source status');
});
test('show all and hide all affect the acknowledged map layer selection only',async()=>{
  const f=dashboardFixture();await f.controller.enter();await f.click('layers-all');
  assert.deepEqual(Array.from(f.controller.preferences().layers),['earthquake','flights']);
  await f.click('layers-none');assert.deepEqual(Array.from(f.controller.preferences().layers),[]);
  assert.equal(f.controller.preferences().link_map,false);assert.equal(f.calls.filter(c=>c.name==='commerce_intel_dashboard_update').length,2);
});
test('a rejected layer save keeps the acknowledged selection and offers reconciliation',async()=>{
  const f=dashboardFixture({save:async()=>{throw Error('offline')}});await f.controller.enter();
  await f.change({dataset:{intelDashboardLayer:'flights'},checked:true});
  assert.deepEqual(Array.from(f.controller.preferences().layers),['earthquake']);
  assert.ok(f.controller.controls({},[]).includes('核对并重试'));
});
function viewportFixture({stored,blocked=false,width=1200}={}){
  const events=new Map(),saved=[];let resizes=0;
  const element=()=>({dataset:{},style:{values:{},setProperty(k,v){this.values[k]=v},removeProperty(k){delete this.values[k]}},setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]},getBoundingClientRect:()=>({width,height:360})});
  const root=element(),workspace=element(),map=element(),inputWidth=element(),inputHeight=element(),outWidth=element(),outHeight=element(),scope=element();
  const nodes=new Map([['.intel-root',root],['.intel-workspace.with-map',workspace],['.intel-map',map],['#intel-map-size-width',inputWidth],['#intel-map-size-height',inputHeight],['#intel-map-size-width-value',outWidth],['#intel-map-size-height-value',outHeight],['#intel-map-size-scope',scope],['.intel-map-canvas',element()]]);
  const document={querySelector:s=>nodes.get(s)||null,querySelectorAll:()=>[],addEventListener:(type,fn)=>events.set(type,fn)};
  const window={CommerceUI:ui,addEventListener(){},get localStorage(){if(blocked)throw Error('opaque_origin');return {getItem:()=>stored||null,setItem:(key,value)=>saved.push({key,value})}}};
  vm.runInNewContext(source,{window,document,requestAnimationFrame:fn=>fn()});
  assert.equal(typeof window.CommerceIntelMapViewport,'function','The map has no adjustable viewport controller');
  const controller=window.CommerceIntelMapViewport({esc,isActive:()=>true,onResize:()=>resizes++});controller.mount();
  return {controller,map,workspace,inputWidth,outWidth,scope,saved,resizes:()=>resizes,input(axis,value){events.get('input')({target:{dataset:{intelMapSize:axis},value:String(value)}})},reset(){const target={dataset:{intelMapSizeAction:'reset'}};events.get('click')({target:{closest:s=>s==='[data-intel-map-size-action]'?target:null}})}};
}
test('viewport inputs adjust actual layout without repainting or recreating the map',()=>{
  const f=viewportFixture();f.input('width',55);f.input('height',520);
  assert.equal(f.workspace.style.values['--intel-map-width'],'55fr');
  assert.equal(f.workspace.style.values['--intel-side-width'],'45fr');
  assert.equal(f.map.style.values['--intel-map-height'],'520px');
  assert.equal(f.map.dataset.mapHeight,'custom');assert.ok(f.resizes()>=2);
  const next=viewportFixture({stored:f.saved.at(-1).value});
  assert.equal(next.map.style.values['--intel-map-height'],'520px');
  assert.equal(next.workspace.style.values['--intel-map-width'],'55fr');
});
test('viewport bounds reject invalid values and reset restores responsive automatic layout',()=>{
  const f=viewportFixture();f.input('width',999);f.input('height',-4);
  assert.equal(f.workspace.style.values['--intel-map-width'],'80fr');assert.equal(f.map.style.values['--intel-map-height'],'260px');
  f.input('height','invalid');assert.equal(f.map.style.values['--intel-map-height'],'260px');
  f.reset();assert.equal(f.workspace.style.values['--intel-map-width'],undefined);assert.equal(f.map.style.values['--intel-map-height'],undefined);assert.equal(f.map.dataset.mapHeight,'auto');
  assert.deepEqual(JSON.parse(f.saved.at(-1).value),{width:null,height:null});
});
test('an opaque host still adjusts size and identifies that persistence is unavailable',()=>{
  const f=viewportFixture({blocked:true});f.input('height',600);
  assert.equal(f.map.style.values['--intel-map-height'],'600px');assert.match(f.scope.textContent,/仅当前页面/);assert.equal(f.saved.length,0);
});
test('narrow layouts keep the map full width while retaining the desktop preference',()=>{
  const f=viewportFixture({stored:'{"width":60,"height":420}',width:390});
  assert.equal(f.inputWidth.disabled,true);assert.match(f.outWidth.textContent,/铺满/);
  assert.equal(f.map.style.values['--intel-map-height'],'420px');
  assert.equal(f.workspace.style.values['--intel-map-width'],'60fr');
});
test('malformed saved sizes cannot leak invalid CSS into the map',()=>{
  const f=viewportFixture({stored:'{"width":"50;display:none","height":null}'});
  assert.equal(f.workspace.style.values['--intel-map-width'],undefined);assert.equal(f.map.style.values['--intel-map-height'],undefined);
  const html=f.controller.controls();assert.match(html,/type="range"/);assert.match(html,/for="intel-map-size-height"/);
});

const intelSource=await readFile(new URL('../web/intel-ui.js',import.meta.url),'utf8');
async function mapFixture(){
  const events=new Map(),calls=[];let html='',intel,offline=false;
  const markers=['earthquake','flood'].map((layer,i)=>({id:(i?'b':'a').repeat(24),source:i?'gdacs':'usgs',title:layer,location:{lat:i*10,lon:i*20},display:{layer}}));
  const document={activeElement:null,querySelector:()=>null,querySelectorAll:()=>[],getElementById:()=>null,addEventListener:(type,fn)=>events.set(type,[...(events.get(type)||[]),fn])};
  const window={CommerceUI:{...ui,badge:()=>'',alert:text=>`<p role="alert">${text}</p>`,field:()=>'',input:()=>''},CommerceSocial:()=>({view:()=>'',aside:()=>'',enter(){}}),addEventListener(){}};
  vm.runInNewContext(source+'\n'+intelSource,{window,document,location:{hash:''},Date,URL,crypto:globalThis.crypto,setTimeout,clearTimeout,setInterval(){},requestAnimationFrame:fn=>fn()});
  let prefs={...preferences(),layers:['earthquake','flood']};
  const repaint=()=>{html=intel.view()};
  const api=async(name,args={})=>{calls.push({name,args});if(name==='commerce_intel_dashboard_get')return {revision:0,preferences:prefs,layers:catalog,regions:{},references:[]};if(name==='commerce_intel_dashboard_update'){prefs=args.preferences;return {revision:1,preferences:prefs};}if(name==='commerce_intel_search'){if(offline)throw Error('offline');return {items:[],total:2,stats:{geolocated:2},map_stats:{matched:2},sources:[],markers,archive:{archived:2},panels:{}};}if(name==='commerce_crawler_list')return {jobs:[],alerts:[]};if(name==='commerce_intel_article_batch_list')return {batches:[]};if(name==='commerce_intel_watch_list')return {watches:[]};return {}};
  intel=window.CommerceIntel({api,esc,repaint,toast(){},isActive:()=>true});await intel.enter();await new Promise(setImmediate);repaint();
  return {get html(){return html},calls,setOffline:()=>{offline=true},async layerOff(id){for(const fn of events.get('change'))fn({target:{dataset:{intelDashboardLayer:id},checked:false}});await new Promise(setImmediate);await new Promise(setImmediate)},async focus(){for(const fn of events.get('click'))fn({target:{closest:s=>s==='[data-intel-dashboard]'?{dataset:{intelDashboard:'focus',panel:'map'}}:null}});await new Promise(setImmediate)},escapePicker(){let focused=false;const picker={open:true,querySelector:()=>({focus(){focused=true}})};const event={key:'Escape',defaultPrevented:false,target:{id:'intel-layer-earthquake',closest:s=>s==='.intel-picker'?picker:null,matches:()=>false},preventDefault(){this.defaultPrevented=true},stopPropagation(){}};for(const fn of events.get('keydown'))fn(event);return {picker,focused}}};
}
test('turning off a layer hides its retained points even if the next search fails',async()=>{
  const f=await mapFixture();assert.ok(f.html.includes('id="intel-map-'+('a'.repeat(24))+'"'));
  f.setOffline();await f.layerOff('earthquake');
  assert.ok(!f.html.includes('id="intel-map-'+('a'.repeat(24))+'"'),'A hidden layer is still drawn from the previous snapshot');
  assert.ok(f.html.includes('id="intel-map-'+('b'.repeat(24))+'"'),'The remaining visible layer was discarded');
  assert.ok(f.html.includes('检索失败'));assert.equal(f.calls.at(-1).args.map_layers.includes('earthquake'),false);
});
test('Escape closes a map picker and restores its summary without leaving the focused map',async()=>{
  const f=await mapFixture();await f.focus();assert.ok(f.html.includes('intel-focused-view'));
  const {picker,focused}=f.escapePicker();assert.equal(picker.open,false);assert.equal(focused,true);
  assert.ok(f.html.includes('intel-focused-view'),'Picker Escape also navigated away from the map');
});
