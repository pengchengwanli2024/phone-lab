import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source=await readFile(new URL('../embedded-map-proxy.js',import.meta.url),'utf8').catch(()=> '');
const renderer=`window.mapInstances=0;window.mapCalls=[];window.CommerceGeoMap=options=>{window.mapInstances++;let active=false;return {mount:(...args)=>{window.mapCalls.push(['mount',...args]);active=!!args[0]&&options.isActive();},beforePaint:()=>{window.mapCalls.push(['beforePaint']);},active:()=>active,zoomPercent:()=>175,bounds:()=>({west:-20,east:30,north:40,south:-10}),focus:(...args)=>window.mapCalls.push(['focus',...args]),box:(...args)=>window.mapCalls.push(['box',...args]),reset:()=>window.mapCalls.push(['reset']),zoomBy:(...args)=>window.mapCalls.push(['zoomBy',...args]),dispose:()=>{active=false;window.mapCalls.push(['dispose']);}};};`;
function harness(){
  const handlers=new Map(),sent=[],timers=new Map();let nextId=0,context;
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.style={};this.dataset={};this.isConnected=true;this.listeners={};}
    appendChild(child){this.children.push(child);child.parentElement=this;if(child.tagName==='SCRIPT')vm.runInContext(child.textContent,context);return child;}
    append(...children){for(const child of children)this.appendChild(child);}
    setAttribute(name,value){this[name]=value;}
    addEventListener(name,fn){this.listeners[name]=fn;}
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null;this.isConnected=false;}
  }
  const parent={postMessage:message=>sent.push(message)},document={createElement:tag=>new Element(tag),head:new Element('head')};
  context=vm.createContext({parent,document,console,crypto:{randomUUID:()=>String(++nextId)},setTimeout:callback=>{const id=++nextId;timers.set(id,callback);return id;},clearTimeout:id=>timers.delete(id),addEventListener:(name,fn)=>{if(!handlers.has(name))handlers.set(name,new Set());handlers.get(name).add(fn);},removeEventListener:(name,fn)=>handlers.get(name)?.delete(fn)});
  context.window=context;vm.runInContext(source.replaceAll('__COMMERCE_BRIDGE_NONCE__','nested-nonce'),context);
  assert.equal(typeof context.CommerceGeoMap,'function','the lazy proxy must preserve the map factory');
  const reply=(message,who=parent)=>{for(const fn of [...handlers.get('message')||[]])fn({source:who,data:message});};
  const result=(request,extra={})=>({type:'commerce:embedded-asset-result',asset:'intel-map',id:request.id,nonce:'nested-nonce',script:renderer,...extra});
  return {context,sent,host:()=>new Element(),reply,result,handlers,timers};
}
async function settle(){for(let i=0;i<8;i++)await Promise.resolve();}

test('maps load only on an active mount and retain current selection and view commands',async()=>{
  const h=harness();let active=false;const map=h.context.CommerceGeoMap({isActive:()=>active});const first=h.host(),latest=h.host(),point={location:{lon:12,lat:23}};
  map.focus(point,4);map.zoomBy(2);map.mount(first,[{id:'old'}],'old');assert.equal(h.sent.length,0);
  active=true;map.mount(first,[{id:'old'}],'old');assert.equal(h.sent.length,1);
  map.beforePaint();map.mount(latest,[{id:'new'}],'new');assert.equal(h.sent.length,1);
  assert.equal(latest.children.length,1,'a repaint while waiting must restore the loading status on the current map');
  assert.equal(latest.children[0].role,'status');
  h.reply(h.result(h.sent[0],{nonce:'wrong'}));h.reply(h.result(h.sent[0]),{});await settle();assert.equal(h.context.mapInstances,undefined);
  h.reply(h.result(h.sent[0]));await settle();
  assert.equal(h.context.mapInstances,1);const mount=h.context.mapCalls.find(call=>call[0]==='mount');assert.equal(mount[1],latest);assert.equal(mount[2][0].id,'new');assert.equal(mount[3],'new');
  assert.equal(h.context.mapCalls.some(call=>call[0]==='focus'&&call[1]===point&&call[2]===4),true);
  assert.equal(h.context.mapCalls.some(call=>call[0]==='zoomBy'&&call[1]===2),true);
  assert.equal(map.active(),true);assert.equal(map.zoomPercent(),175);assert.equal(map.bounds().west,-20);
  map.box({x:1,y:2,w:3});map.reset();map.zoomBy(.5);map.dispose();assert.equal(map.active(),false);
  assert.deepEqual(Array.from(h.context.mapCalls.slice(-4),row=>row[0]),['box','reset','zoomBy','dispose']);
  assert.equal(h.handlers.get('message').size,0);assert.equal(h.timers.size,0);
});

test('switching away or disposing a waiting map prevents a late map mount',async()=>{
  const h=harness();let active=true;const map=h.context.CommerceGeoMap({isActive:()=>active}),host=h.host();
  map.mount(host,[],'');active=false;map.beforePaint();h.reply(h.result(h.sent[0]));await settle();assert.equal(h.context.mapInstances,0);
  active=true;map.mount(host,[],'restored');assert.equal(h.context.mapInstances,1);
  const second=harness(),disposed=second.context.CommerceGeoMap({isActive:()=>true});disposed.mount(second.host(),[],'');disposed.dispose();second.reply(second.result(second.sent[0]));await settle();assert.equal(second.context.mapInstances,0);
});

test('asset failure keeps the fallback usable and offers an explicit retry',async()=>{
  const h=harness(),map=h.context.CommerceGeoMap({isActive:()=>true}),host=h.host();map.mount(host,[],'');
  h.reply(h.result(h.sent[0],{script:undefined,error:'embedded_asset_unavailable'}));await settle();
  assert.equal(map.active(),false);assert.equal(host.children.length,1);const notice=host.children[0];assert.equal(notice.role,'alert');
  const retry=notice.children.find(child=>child.tagName==='BUTTON');assert.ok(retry);
  map.mount(host,[],'retained');assert.equal(h.sent.length,1,'rerenders must not start retry loops');
  retry.listeners.click();assert.equal(h.sent.length,2);h.reply(h.result(h.sent[1]));await settle();assert.equal(map.active(),true);assert.equal(host.children.length,0);
});

test('a failed map restores its retry control after leaving and returning',async()=>{
  const h=harness(),map=h.context.CommerceGeoMap({isActive:()=>true}),host=h.host();map.mount(host,[],'');
  h.reply(h.result(h.sent[0],{error:'unavailable'}));await settle();map.beforePaint();
  const returned=h.host();map.mount(returned,[],'retained');assert.equal(returned.children.length,1);
  assert.equal(returned.children[0].children.some(child=>child.tagName==='BUTTON'),true);
});

test('renderer initialization failure disposes the partial driver and retries the same offline factory',async()=>{
  const h=harness(),map=h.context.CommerceGeoMap({isActive:()=>true}),host=h.host();map.mount(host,[],'');
  const flaky=renderer.replace("window.mapCalls.push(['mount',...args]);","if(!window.failedOnce){window.failedOnce=true;throw Error('synthetic-gpu-initialization-failed');}window.mapCalls.push(['mount',...args]);");
  h.reply(h.result(h.sent[0],{script:flaky}));await settle();assert.equal(map.active(),false);
  const retry=host.children[0].children.find(child=>child.tagName==='BUTTON');assert.ok(retry);retry.listeners.click();await settle();
  assert.equal(map.active(),true);assert.equal(h.context.mapInstances,2);assert.equal(h.context.mapCalls.some(call=>call[0]==='dispose'),true);assert.equal(h.sent.length,1);
});
