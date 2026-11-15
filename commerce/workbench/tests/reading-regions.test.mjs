import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const source = await readFile(process.env.UI_KIT_SOURCE || '../ui/kit.js', 'utf8');
function setup() {
  let onResize, onMutation; const observed = new Set();
  class ResizeObserver { constructor(fn) { onResize=fn; } observe(el) { observed.add(el); } unobserve(el) { observed.delete(el); } disconnect() { observed.clear(); } }
  class MutationObserver { constructor(fn) { onMutation=fn; } observe() {} disconnect() {} }
  const window = { matchMedia: () => ({matches:false,addEventListener(){}}), dispatchEvent(){} };
  vm.runInNewContext(source, { window, document:{documentElement:{dataset:{}}}, CustomEvent:class{}, ResizeObserver, MutationObserver, requestAnimationFrame:fn=>fn() });
  const nodes=[]; const root={querySelectorAll:()=>nodes};
  function element(width=200, content=600, attrs={}) {
    const attributes=new Map(Object.entries(attrs));
    return {clientWidth:width,scrollWidth:content,isConnected:true,getAttribute:k=>attributes.get(k)??null,
      hasAttribute:k=>attributes.has(k),setAttribute:(k,v)=>attributes.set(k,v),removeAttribute:k=>attributes.delete(k),
      matches:()=>true,closest:()=>({querySelector:()=>({textContent:'原业务结果'})})};
  }
  return {ui:window.CommerceUI,root,nodes,element,observed,resize:el=>onResize([{target:el}]),mutation:()=>onMutation()};
}
test('overflowing results become keyboard-readable and leave the tab order after reflow',()=>{
  const s=setup(),el=s.element();s.nodes.push(el);const stop=s.ui.observeReadingRegions(s.root);
  assert.equal(el.getAttribute('tabindex'),'0');assert.equal(el.getAttribute('role'),'region');
  assert.match(el.getAttribute('aria-label'),/原业务结果.*横向滚动/);
  el.clientWidth=800;s.resize(el);assert.equal(el.getAttribute('tabindex'),null);assert.equal(el.getAttribute('role'),null);
  el.clientWidth=200;s.resize(el);assert.equal(el.getAttribute('tabindex'),'0');stop();assert.equal(el.getAttribute('tabindex'),null);
});
test('a repaint releases detached results and preserves pre-existing accessible names',()=>{
  const s=setup(),first=s.element(200,600,{role:'group','aria-label':'原名称',tabindex:'-1'});s.nodes.push(first);
  const stop=s.ui.observeReadingRegions(s.root);assert.equal(first.getAttribute('aria-label'),'原名称');
  const second=s.element();first.isConnected=false;s.nodes.splice(0,1,second);s.mutation();
  assert.equal(s.observed.has(first),false);assert.equal(second.getAttribute('tabindex'),'0');
  assert.equal(first.getAttribute('tabindex'),'-1');stop();assert.equal(s.observed.size,0);
});
test('controlled detail targets accept programmatic focus without introducing positive tab order',()=>{
  const {ui}=setup();
  assert.match(ui.card({attrs:{id:'skills-detail',tabindex:-1}}),/tabindex="-1"/);
  assert.match(ui.attributes({tabindex:0}),/tabindex="0"/);
  assert.equal(ui.attributes({tabindex:3,onclick:'unsafe()'}),'');
});
