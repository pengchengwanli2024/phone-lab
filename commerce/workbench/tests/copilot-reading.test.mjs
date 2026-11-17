import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const source=await readFile('../web/copilot-reading.js','utf8').catch(e=>{if(e.code==='ENOENT')return '';throw e;});
const composer=await readFile('../web/copilot-ui.js','utf8');
const thread=(count,start=0)=>({id:'original',turns:Array.from({length:count},(_,i)=>({id:'t'+(i+start),run:{id:'r'+(i+start)}}))});
function reading(){const sandbox={};vm.runInNewContext(source,sandbox);assert.equal(typeof sandbox.CommerceCopilotReading?.create,'function','long conversation must have a bounded reading window');return sandbox.CommerceCopilotReading.create(40);}
test('200 loaded turns render only the latest 40 and every old turn remains reachable',()=>{
  const r=reading(),t=thread(200),seen=new Set();let range=r.range(t);assert.equal(range.turns.length,40);assert.equal(range.turns[0].id,'t160');
  while(true){range=r.range(t);range.turns.forEach(turn=>seen.add(turn.id));if(!range.before)break;r.move(t,-1);}
  assert.equal(seen.size,200);assert.equal(t.turns.length,200);r.latest(t);assert.equal(r.range(t).after,0);
});
test('new turns do not displace an older reading window and the current reading anchor remains visible',()=>{
  const r=reading(),t=thread(200);r.range(t);r.move(t,-1);const before=r.range(t).turns[0].id;t.turns.push(...thread(10,200).turns);assert.equal(r.range(t).turns[0].id,before);assert.ok(r.range(t).after>0);
  r.latest(t);const first=r.range(t).turns[0].id;t.turns.push(...thread(60,210).turns);const range=r.range(t,{anchor:'turn:'+first,bottom:false});assert.equal(range.turns[0].id,first);assert.equal(range.turns.length,40);
});
test('prepend and updated receipts keep the stable first identity while replacing the original run data',()=>{
  const r=reading(),t=thread(200);r.range(t);r.move(t,-1);const first=r.range(t).turns[0].id;t.turns.unshift(...thread(20,-20).turns);t.turns=t.turns.map(turn=>turn.id===first?{...turn,run:{...turn.run,status:'completed'}}:turn);const range=r.range(t);assert.equal(range.turns[0].id,first);assert.equal(range.turns[0].run.status,'completed');assert.equal(range.turns.length,40);
});
test('another thread starts at its own newest records and a shortened response cannot exceed bounds',()=>{
  const r=reading(),t=thread(200);r.range(t);r.move(t,-1);const other={...thread(90),id:'other'};assert.equal(r.range(other).turns[0].id,'t50');other.turns=other.turns.slice(0,3);assert.equal(r.range(other).turns.length,3);assert.equal(r.range(other).before,0);
});
test('one original 40-turn page needs only one Older action and exposes its first turn',()=>{
  const r=reading(),t=thread(40,40);r.range(t);t.turns.unshift(...thread(40).turns);const range=r.move(t,-1);assert.equal(range.turns[0].id,'t0');assert.equal(range.before,0);
});
test('main chat bounds rendered messages and browses all loaded history without another API or losing draft',async t=>{
  const handlers=new Map(),calls=[],scope={module:'overview',demo:true},listeners={addEventListener(name,fn){if(!handlers.has(name))handlers.set(name,[]);handlers.get(name).push(fn);},removeEventListener(){}};
  const escape=value=>String(value??'').replaceAll('<','&lt;').replaceAll('"','&quot;');const ui={escape,icon:()=>'',badge:escape,alert:escape,button:({label,attrs})=>`<button ${Object.entries(attrs).map(([k,v])=>k+'="'+escape(v)+'"').join(' ')}>${escape(label)}</button>`};
  const document={...listeners,querySelector:()=>null,getElementById:()=>null,activeElement:null},window={...listeners,CommerceUI:ui,innerWidth:1440,dispatchEvent(){}};window.parent=window;
  vm.runInNewContext(source+'\n'+composer,{window,document,setInterval(){},clearInterval(){},setTimeout,clearTimeout,CustomEvent:class{},localStorage:{getItem:()=>null,setItem(){}}});
  const value={...thread(240),context:scope,context_sha256:'scope',latest_run:null};value.turns.forEach((turn,i)=>{turn.question='原问题'+i;turn.run={...turn.run,status:'completed',result:{answer:'原答复'+i}}});value.latest_run=value.turns.at(-1).run;
  const controller=window.CommerceCopilot({api:async name=>{calls.push(name);if(name==='commerce_model_list')return {models:[]};if(name==='commerce_copilot_list')return {threads:[]};if(name==='commerce_copilot_get')return value;throw Error(name);},inline:true,compact:true,getContext:()=>scope,scopeLabel:()=> '测试',repaint(){}});t.after(()=>controller.dispose());controller.open(undefined,{focus:false});await new Promise(setImmediate);await controller.openThread(value.id);
  const emit=(name,event)=>handlers.get(name)?.forEach(fn=>fn(event));emit('input',{target:{id:'copilot-message',value:'保持中文草稿'}});
  let html=controller.view();assert.equal((html.match(/class="copilot-message copilot-user"/g)||[]).length,40);assert.ok(html.includes('原问题239'));assert.ok(!html.includes('原问题0<'));
  const before=calls.length,target={dataset:{copilotAction:'older'},closest:selector=>selector==='[data-copilot-action]'?target:null};emit('click',{target,preventDefault(){}});await new Promise(setImmediate);html=controller.view();assert.ok(html.includes('原问题160'));assert.ok(html.includes('保持中文草稿'));assert.equal(calls.length,before);
  target.dataset.copilotAction='newest';emit('click',{target,preventDefault(){}});await new Promise(setImmediate);assert.ok(controller.view().includes('原问题239'));assert.equal(calls.length,before);assert.equal(value.turns.length,240);
});
