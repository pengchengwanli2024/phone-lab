import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {normalizeRows,retainedUpdate,viewBounds} from '../map/model.mjs';

const controller=(await readFile(new URL('../map/index.js',import.meta.url),'utf8')).replace(/^import .*;\n/gm,'');
function fixture(){
  class Element {
    constructor(){this.dataset={};this.hidden=false;this.nodes=new Map();this.listeners={};this.clientWidth=1000;this.clientHeight=600;this.isConnected=false;this.style={};const values=new Set();this.classList={add:v=>values.add(v),remove:v=>values.delete(v),contains:v=>values.has(v),toggle:(v,on)=>on?values.add(v):values.delete(v)};}
    querySelector(key){if(!this.nodes.has(key)){const el=new Element();el.hidden=/error|retry|tooltip/.test(key);this.nodes.set(key,el);}return this.nodes.get(key);}
    querySelectorAll(){return ['globe','flat','tilt','retry','cruise','quality'].map(key=>this.querySelector(`[data-geo-action="${key}"]`));}
    addEventListener(key,fn){this.listeners[key]=fn;}
    setAttribute(){}
    prepend(el){el.parentElement=this;el.isConnected=true;}
    replaceChildren(){}
    remove(){this.isConnected=false;}
  }
  const instances={globe:[],flat:[]};
  const renderer=key=>class {
    constructor(host,countries,callbacks){this.callbacks=callbacks;this.view={lng:30,lat:18,zoom:1.6};instances[key].push(this);}
    setView(v){this.view={...v};}getView(){return this.view;}setActive(v){this.active=v;}
    update(){}setQuality(){}setCruise(){}resize(){}dispose(){this.active=false;}
  };
  const stage=new Element(),host=new Element();
  const window={CommerceUI:{button:()=>''},addEventListener(){}};
  vm.runInNewContext(controller,{window,document:{createElement:()=>stage,addEventListener(){},removeEventListener(){}},
    EarthRenderer:renderer('globe'),PlaneRenderer:renderer('flat'),countries:{features:[]},normalizeRows,retainedUpdate,viewBounds,
    matchMedia:()=>({matches:true}),crypto:{randomUUID:()=> 'synthetic-map'},ResizeObserver:class{observe(){}disconnect(){}},
    requestAnimationFrame:()=>0,cancelAnimationFrame(){},performance:{now:()=>0},console:{warn(){}}});
  const map=window.CommerceGeoMap({isActive:()=>true});map.mount(host,[],null);
  const click=action=>stage.listeners.click({target:{closest:()=>({dataset:{geoAction:action}})}});
  return {map,stage,host,instances,click,loading:stage.querySelector('.intel-geo-loading')};
}

test('asynchronous renderer failure restores the SVG and stops the loading overlay',()=>{
  const f=fixture();f.instances.globe[0].callbacks.onReady();f.click('flat');
  f.instances.flat[0].callbacks.onError('Synthetic worker failed');
  assert.equal(f.stage.dataset.ready,'failed');assert.equal(f.loading.hidden,true);
  assert.equal(f.host.classList.contains('has-webgl'),false);assert.equal(f.map.active(),false);
  assert.equal(f.instances.flat[0].active,false);assert.equal(f.stage.querySelector('.intel-geo-retry').hidden,false);
  f.instances.flat[0].callbacks.onReady();assert.equal(f.stage.dataset.ready,'failed');
  f.click('globe');assert.equal(f.host.classList.contains('has-webgl'),true);
});
test('context loss before readiness exposes the fallback without the loading screen',()=>{
  const f=fixture();f.instances.globe[0].callbacks.onContextLost({preventDefault(){}});
  assert.equal(f.stage.dataset.ready,'lost');assert.equal(f.loading.hidden,true);
  assert.equal(f.map.active(),false);assert.equal(f.host.classList.contains('has-webgl'),false);
});
test('inactive and replaced renderers cannot change the current renderer lifecycle',()=>{
  const f=fixture(),old=f.instances.globe[0];old.callbacks.onReady();f.click('flat');
  old.callbacks.onContextLost({preventDefault(){}});f.instances.flat[0].callbacks.onReady();
  assert.equal(f.stage.dataset.ready,'true');assert.equal(f.host.classList.contains('has-webgl'),true);
  f.click('globe');assert.equal(f.stage.dataset.ready,'lost');f.click('retry');
  old.callbacks.onReady();old.callbacks.onError('Late error from disposed renderer');
  assert.equal(f.stage.dataset.ready,'loading');assert.equal(f.loading.hidden,false);
  assert.equal(f.host.classList.contains('has-webgl'),false);
  f.instances.globe[1].callbacks.onReady();assert.equal(f.stage.dataset.ready,'true');
});
