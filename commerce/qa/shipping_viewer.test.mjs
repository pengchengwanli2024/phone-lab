import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {existsSync, readFileSync} from 'node:fs';

// Node has no SVG DOM. Keep only native DOM boundaries in this harness: the
// production viewer still handles all events, state, projection and rendering.
class SvgNode extends EventTarget {
  constructor(name, document) {
    super(); this.nodeName=name; this.ownerDocument=document; this.attributes=new Map();
    this.children=[]; this.textContent=''; this.width=640; this.height=340; this.captures=new Set();
    this.classList={add:name=>this.attributes.set('class',name),remove:()=>this.attributes.delete('class')};
  }
  setAttribute(name,value) { this.attributes.set(name,String(value)); }
  getAttribute(name) { return this.attributes.get(name)??null; }
  removeAttribute(name) { this.attributes.delete(name); }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children=nodes; }
  getBoundingClientRect() { return {width:this.width,height:this.height,left:0,top:0}; }
  setPointerCapture(id) { this.captures.add(id); }
  hasPointerCapture(id) { return this.captures.has(id); }
  releasePointerCapture(id) { this.captures.delete(id); }
  focus() { this.ownerDocument.activeElement=this; }
}
function harness(options={}) {
  const frames=new Map(),observers=[]; let frameId=0;
  const window=Object.assign(new EventTarget(),{
    requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},
    cancelAnimationFrame:id=>frames.delete(id),
    ResizeObserver:class { constructor(callback){this.callback=callback;observers.push(this);} observe(node){this.node=node;} disconnect(){this.node=null;} }
  });
  const document={defaultView:window,createElementNS:(_,name)=>new SvgNode(name,document)};
  const element=new SvgNode('svg',document),changes=[];
  const file=new URL('../web/shipping-viewer.js',import.meta.url);
  const context=vm.createContext({window,document,console,ResizeObserver:window.ResizeObserver});
  vm.runInContext(existsSync(file)?readFileSync(file,'utf8'):'',context);
  assert.equal(typeof window.CommerceShippingViewer?.create,'function','interactive shipping viewer has not been implemented');
  const viewer=window.CommerceShippingViewer.create({element,box:box(),onChange:state=>changes.push({...state}),...options});
  function flush(){const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn());}
  function send(type,properties={}){const event=new Event(type,{cancelable:true});Object.assign(event,{pointerId:1,button:0,pointerType:'mouse',clientX:0,clientY:0,...properties});element.dispatchEvent(event);return event;}
  const descendants=(node=element)=>node.children.flatMap(child=>[child,...descendants(child)]);
  const polygons=()=>descendants().filter(node=>node.nodeName==='polygon'&&node.getAttribute('data-shipping-item')!==null);
  return {element,viewer,changes,send,flush,polygons,descendants,observers,window,frames};
}
function unit(sku,position=[0,0,0],size=[10,10,10]) {return {sku,position_cm:position,orientation_cm:size,weight_kg:1};}
function box(items=[unit('A')]) {return {carton_name:'合成测试箱',inner_cm:[40,30,20],outer_cm:[42,32,22],items,gross_weight_kg:2,volume_utilization_pct:5};}
const faceNames=h=>[...new Set(h.polygons().map(node=>node.getAttribute('data-shipping-face')))].sort();
const geometry=h=>h.polygons().map(node=>node.getAttribute('points')).join('|');
function state(h,next){h.viewer.setState(next);h.flush();}

// Break caught: removing either drag axis or restoring the fixed-angle picture.
test('pointer dragging rotates both camera axes and changes rendered geometry without changing packing coordinates',()=>{
  const source=box(),before=JSON.stringify(source),h=harness({box:source}),first=geometry(h);
  const down=h.send('pointerdown',{clientX:100,clientY:100});
  assert.equal(down.defaultPrevented,true);assert.equal(h.element.ownerDocument.activeElement,h.element);
  h.send('pointermove',{clientX:180,clientY:150});h.flush();
  assert.notEqual(geometry(h),first);assert.notEqual(h.viewer.getState().yaw,40);assert.notEqual(h.viewer.getState().pitch,30);
  assert.equal(JSON.stringify(source),before);assert.equal(h.element.captures.has(1),true);
  h.send('pointerup');assert.equal(h.element.captures.size,0);
  const stopped=geometry(h);h.send('pointermove',{clientX:300});h.flush();assert.equal(geometry(h),stopped);
});

// Break caught: always choosing the original top/front/right faces.
test('visible cuboid faces follow the camera through front, back, above and below',()=>{
  const h=harness();
  for(const [yaw,pitch,want] of [[0,0,['y+']],[90,0,['x+']],[180,0,['y-']],[270,0,['x-']],[0,90,['z+']],[0,-90,['z-']],[40,30,['x+','y+','z+']],[220,-30,['x-','y-','z-']]]){
    state(h,{yaw,pitch});assert.deepEqual(faceNames(h),want,`yaw ${yaw}, pitch ${pitch}`);
  }
});

// Break caught: sorting far-to-near in one camera direction only.
test('near items cover far items and the order reverses behind the carton',()=>{
  const h=harness({box:box([unit('BACK',[0,0,0]),unit('FRONT',[0,20,0])])});
  state(h,{yaw:0,pitch:0});assert.deepEqual(h.polygons().map(p=>p.getAttribute('data-shipping-sku')),['BACK','FRONT']);
  state(h,{yaw:180,pitch:0});assert.deepEqual(h.polygons().map(p=>p.getAttribute('data-shipping-sku')),['FRONT','BACK']);
});

function coveringSku(h,[x,y]) {
  return h.polygons().filter(p=>{
    const v=p.getAttribute('points').split(' ').map(point=>point.split(',').map(Number));let inside=false;
    for(let i=0,j=v.length-1;i<v.length;j=i++)if((v[i][1]>y)!==(v[j][1]>y)&&x<(v[j][0]-v[i][0])*(y-v[i][1])/(v[j][1]-v[i][1])+v[i][0])inside=!inside;
    return inside;
  }).at(-1)?.getAttribute('data-shipping-sku');
}

// Break caught: average face-depth sorting covers a nearby small item with a
// wide rear face. The two sample pixels are hand-projected x-y=2.8,z=5 rays.
test('wide rear faces never paint over a nearer small cuboid with overlapping depth ranges',()=>{
  const h=harness({box:box([unit('WIDE',[0,0,0],[30,1,10]),unit('SMALL',[5,2,0],[1,1,10])])});
  state(h,{yaw:45,pitch:0});assert.equal(coveringSku(h,[301.143,230.609]),'SMALL');
  state(h,{yaw:225,pitch:0});assert.equal(coveringSku(h,[338.857,230.609]),'WIDE');
});

// Break caught: count/layer filters dropping original packing order or mutating the source.
test('count and layer filters keep original packing indices and leave source items intact',()=>{
  const source=box([unit('A'),unit('B',[10,0,0]),unit('C',[0,0,10])]),h=harness({box:source});
  h.viewer.setFilter({count:2,layer:'0'});h.flush();assert.equal(h.viewer.getState().visibleCount,2);
  h.viewer.setFilter({layer:'10'});h.flush();assert.equal(h.polygons().length,0);
  h.viewer.setFilter({count:3});h.flush();assert.equal(h.viewer.getState().visibleCount,1);
  assert.ok(h.polygons().every(p=>p.getAttribute('data-shipping-item')==='2'));
  h.viewer.setFilter({count:0,layer:'all'});h.flush();assert.equal(h.polygons().length,0);
  assert.equal(source.items.length,3);
});

// Break caught: unbounded wheel zoom or wheel scrolling instead of zooming.
test('wheel zoom changes geometry, consumes its event and clamps both zoom extremes',()=>{
  const h=harness(),before=geometry(h);
  const event=h.send('wheel',{deltaY:-250,deltaMode:0});h.flush();
  assert.equal(event.defaultPrevented,true);assert.ok(h.viewer.getState().zoom>1);assert.notEqual(geometry(h),before);
  h.send('wheel',{deltaY:-100000,deltaMode:0});assert.equal(h.viewer.getState().zoom,4);
  h.send('wheel',{deltaY:100000,deltaMode:0});assert.equal(h.viewer.getState().zoom,.25);
  h.viewer.zoomIn();assert.ok(h.viewer.getState().zoom>.25);h.viewer.zoomOut();assert.ok(h.viewer.getState().zoom>=.25);
});

// Break caught: treating the second touch as a rotation or losing one-finger recovery.
test('two pointers pinch zoom and lifting one pointer resumes drag without a jump',()=>{
  const h=harness(),start=h.viewer.getState();
  h.send('pointerdown',{pointerType:'touch',pointerId:1,clientX:100,clientY:100});
  h.send('pointerdown',{pointerType:'touch',pointerId:2,clientX:200,clientY:100});
  h.send('pointermove',{pointerType:'touch',pointerId:2,clientX:300,clientY:100});h.flush();
  assert.equal(h.viewer.getState().zoom,2);assert.equal(h.viewer.getState().yaw,start.yaw);assert.equal(h.viewer.getState().pitch,start.pitch);
  h.send('pointerup',{pointerId:2});h.send('pointermove',{pointerId:1,clientX:110,clientY:100});h.flush();
  assert.ok(Math.abs(h.viewer.getState().yaw-start.yaw)<20);assert.notEqual(h.viewer.getState().yaw,start.yaw);
});

// Break caught: keyboard-only users cannot manipulate the camera or leave page defaults stolen.
test('focused scene supports arrows, zoom keys and Home while ignoring unrelated keys',()=>{
  const h=harness(),original=geometry(h);
  assert.equal(h.element.getAttribute('tabindex'),'0');assert.ok(h.element.getAttribute('aria-describedby'));
  assert.ok(h.descendants().some(node=>node.nodeName==='desc'&&/方向键/.test(node.textContent)));
  assert.equal(h.send('keydown',{key:'ArrowRight'}).defaultPrevented,true);
  assert.equal(h.send('keydown',{key:'ArrowUp'}).defaultPrevented,true);
  h.send('keydown',{key:'+'});h.flush();assert.notEqual(geometry(h),original);assert.ok(h.viewer.getState().zoom>1);
  h.send('keydown',{key:'Home'});h.flush();assert.equal(geometry(h),original);
  assert.equal(h.send('keydown',{key:'Tab'}).defaultPrevented,false);
  const zoom=h.viewer.getState().zoom;h.send('keydown',{key:'+',ctrlKey:true});assert.equal(h.viewer.getState().zoom,zoom);
});

// Break caught: carton switches assigning one SKU a different color.
test('explicit SKU palette stays stable across boxes and fallback color is SKU based',()=>{
  const h=harness({box:box([unit('A')]),palette:{A:'var(--ui-color-success)'}});
  const fill=h.polygons()[0].getAttribute('fill');assert.match(fill,/var\(--ui-color-success\)/);
  h.viewer.setBox(box([unit('B'),unit('A',[10,0,0])]));h.flush();
  assert.equal(h.polygons().find(p=>p.getAttribute('data-shipping-sku')==='A').getAttribute('fill'),fill);
  const fallback=h.polygons().find(p=>p.getAttribute('data-shipping-sku')==='B').getAttribute('fill');
  h.viewer.setBox(box([unit('B')]));h.flush();assert.equal(h.polygons()[0].getAttribute('fill'),fallback);
});

// Break caught: resizing leaving the old projection/viewBox or a zero-size SVG producing NaN.
test('resize observer refits geometry without altering camera zoom and handles hidden containers',()=>{
  const h=harness(),before=geometry(h);state(h,{zoom:1.5});
  h.element.width=360;h.element.height=260;h.observers[0].callback();h.flush();
  assert.equal(h.element.getAttribute('viewBox'),'0 0 360 260');assert.notEqual(geometry(h),before);assert.equal(h.viewer.getState().zoom,1.5);
  h.element.width=0;h.element.height=0;h.observers[0].callback();h.flush();assert.doesNotMatch(geometry(h),/NaN|Infinity/);
});

// Break caught: detached viewers retain pointer/wheel/keyboard/resize handlers or pending animation frames.
test('destroy releases captures and ignores every event and scheduled repaint after unmount',()=>{
  const h=harness();h.send('pointerdown');h.send('pointermove',{clientX:100});
  h.viewer.destroy();h.flush();const before=geometry(h),camera={...h.viewer.getState()},changeCount=h.changes.length;
  assert.equal(h.element.captures.size,0);assert.equal(h.observers[0].node,null);assert.equal(h.frames.size,0);
  h.send('pointermove',{clientX:200});h.send('wheel',{deltaY:100});h.send('keydown',{key:'ArrowLeft'});h.observers[0].callback();h.flush();
  assert.deepEqual({...h.viewer.getState()},camera);assert.equal(geometry(h),before);assert.equal(h.changes.length,changeCount);
});

// Break caught: host readout falling out of sync with API or pointer camera state.
test('camera callbacks report bounded state, visible count and a resettable default view',()=>{
  const h=harness({initialState:{yaw:765,pitch:-45,zoom:10}});
  assert.equal(h.viewer.getState().yaw,45);assert.equal(h.viewer.getState().pitch,-45);assert.equal(h.viewer.getState().zoom,4);
  h.viewer.rotateBy(20,100);h.flush();assert.equal(h.changes.at(-1).yaw,65);assert.equal(h.changes.at(-1).pitch,55);
  h.viewer.reset();h.flush();assert.equal(h.changes.at(-1).zoom,1);assert.equal(h.changes.at(-1).visibleCount,1);assert.equal(h.changes.at(-1).totalCount,1);
  const before={...h.viewer.getState()};h.viewer.setState({yaw:NaN,pitch:Infinity,zoom:'bad'});assert.deepEqual({...h.viewer.getState()},before);
});

// Break caught: missing or empty cartons crashing or leaving an old box onscreen.
test('empty cartons clear items and malformed dimensions never render invalid coordinates',()=>{
  const h=harness();h.viewer.setBox(null);h.flush();assert.equal(h.polygons().length,0);assert.equal(h.viewer.getState().totalCount,0);
  h.viewer.setBox({...box(),inner_cm:[0,null,'invalid']});h.flush();assert.equal(h.polygons().length,0);assert.doesNotMatch(geometry(h),/NaN|Infinity/);
});

// Break caught: the supported 500-unit plan overflowing recursive sorting or
// producing invalid geometry when the camera crosses a view octant.
test('a 500-unit carton remains complete while rotating through all camera octants',()=>{
  const items=Array.from({length:500},(_,i)=>unit(`S${i%4}`,[(i%10)*2,Math.floor(i/10)%10*2,Math.floor(i/100)*2],[2,2,2]));
  const h=harness({box:box(items)});
  for(const pitch of [-40,40])for(const yaw of [40,130,220,310]){
    state(h,{yaw,pitch});assert.equal(new Set(h.polygons().map(p=>p.getAttribute('data-shipping-item'))).size,500);assert.doesNotMatch(geometry(h),/NaN|Infinity/);
  }
});
