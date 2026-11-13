import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source=await readFile('../harness/client.js','utf8');
function fixture(address){
  let definition,selectedPanel;const components=new Map(),opened=[],effects=[],listeners=new Map(),updates=[],events=[];
  const React={useEffect:fn=>effects.push(fn),useState:value=>[typeof value==='function'?value():value,value=>updates.push(value)],useRef:value=>({current:value}),useCallback:fn=>fn,createElement:(type,props,...children)=>({type,props,children})};
  const window={__ModuleLoader__:{load:value=>{definition=value}},addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name),dispatchEvent:event=>{events.push(event);listeners.get(event.type)?.(event)}};
  let request=0;vm.runInNewContext(source,{window,URL,crypto:{randomUUID:()=> 'navigation-'+ ++request},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}}});
  definition.factory(()=>React).apply({slots:{inject:(_slot,fn)=>fn(),register:(config,component)=>components.set(config.name+':'+(config.key||config.id),component)},effect:fn=>fn(),sidebarRightTabs:{register(){}},layout:{selectPanel:()=>selectedPanel?.()}});
  const Product=components.get('sidebar.right.pane.tab:@local/dsh-commerce/product-workspace');
  return {element:Product({useTabInfo:()=>({tab:{contentId:address,actions:{openResource:(...args)=>opened.push(args)}}})}),opened,updates,mainNavigation:()=>components.get('main:commerce')().children[0].children[0].props.navigation,flushEffects:()=>effects.splice(0).forEach(fn=>fn()),onSelect:fn=>selectedPanel=fn,replay:index=>window.dispatchEvent(events[index])};
}
test('actual Harness product tab passes the originating task and preserves it on selection',()=>{
  const s=fixture('dsh-resource://commerce/product/case-a?research_task_id=task-a');assert.equal(s.element.props.caseId,'case-a');assert.equal(s.element.props.researchTaskId,'task-a');
  s.element.props.onSelected('case-a','task-b');assert.equal(s.opened[0][0],'dsh-resource://commerce/product/case-a?research_task_id=task-b');assert.equal(s.opened[0][1].replaceTab,true);
});
test('legacy Harness product links stay valid while malformed explicit contexts fail visibly',()=>{
  assert.equal(fixture('dsh-resource://commerce/product/case-a').element.props.researchTaskId,'');
  for(const url of ['dsh-resource://commerce/product/case-a?research_task_id=../bad','dsh-resource://commerce/product/case-a?research_task_id=a&research_task_id=b']){
    const {element}=fixture(url);assert.equal(element.type,'div');assert.equal(element.props.role,'alert');
  }
});
test('the official empty product guide opens a generic workspace while other sidebar links fail',()=>{
  const guide=fixture('sidebar://commerce-product').element;
  assert.equal(guide.props.caseId,'');assert.equal(guide.props.researchTaskId,'');assert.equal(guide.props.product,true);
  for(const url of ['sidebar://other','sidebar://commerce-product?research_task_id=task-a','sidebar://commerce-product/'])assert.equal(fixture(url).element.props.role,'alert');
});
test('returning from a resource before the main panel mounts retains the original task once',()=>{
  const f=fixture('dsh-resource://commerce/product/case-a?research_task_id=task-a');
  f.element.props.onBackend('pilots','task-a');const initial=f.mainNavigation();
  assert.equal(initial?.tab,'pilots');assert.equal(initial?.research_task_id,'task-a');
  f.flushEffects();assert.equal(f.mainNavigation(),null);
});
test('only the latest pending resource navigation is delivered on a cold mount',()=>{
  const f=fixture('sidebar://commerce-product');f.element.props.onBackend('pilots','old-task');f.element.props.onBackend('pilots','new-task');
  assert.equal(f.mainNavigation()?.research_task_id,'new-task');
});
test('a warm resource return is delivered and consumed without replay on the next mount',()=>{
  const f=fixture('sidebar://commerce-product');assert.equal(f.mainNavigation(),null);f.flushEffects();
  f.element.props.onBackend('pilots','task-a');assert.equal(f.updates.at(-1).tab,'pilots');assert.equal(f.updates.at(-1).research_task_id,'task-a');
  assert.equal(f.mainNavigation(),null);
});
test('synchronous mounting consumes a cold return exactly once',()=>{
  const f=fixture('sidebar://commerce-product');f.onSelect(()=>{f.mainNavigation();f.flushEffects()});f.element.props.onBackend('pilots','task-a');
  assert.equal(f.updates.filter(value=>value?.tab==='pilots').length,1);
});
test('a consumed older return event cannot replace the newer task',()=>{
  const f=fixture('sidebar://commerce-product');f.mainNavigation();f.flushEffects();f.element.props.onBackend('pilots','task-a');f.element.props.onBackend('pilots','task-b');f.replay(0);
  assert.equal(f.updates.at(-1).research_task_id,'task-b');assert.equal(f.updates.filter(value=>value?.tab==='pilots').length,2);
});
