import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

test('page metadata cannot repaint a controlled input before its bubbling input handler',async()=>{
 const source=await readFile('../ui/page-context.js','utf8'),handlers={},timers=[],updates=[],window={};
 const search={value:'',getClientRects:()=>[{}],closest:()=>null};
 const root={contains:()=>true,querySelectorAll:selector=>selector.includes('input[type="search"]')?[search]:[]};
 const document={activeElement:search,addEventListener:(name,fn)=>{handlers[name]=fn},removeEventListener(){}};
 vm.runInNewContext(source,{window,document,setTimeout:fn=>{timers.push(fn);return timers.length}});
 const controller=window.CommercePageContext.create({root:()=>root,getBase:()=>({page:'memory'}),onChange:value=>updates.push(value)});
 updates.length=0;search.value='new query';handlers.input({type:'input',target:search});
 // Trusted DOM events can run a microtask checkpoint between capture and bubble.
 await Promise.resolve();assert.equal(updates.length,0,'metadata must wait for the input owner');
 search.value='committed query';for(const fn of timers)fn();await Promise.resolve();
 assert.equal(updates.at(-1).filters.query,'committed query');controller.dispose();
});
