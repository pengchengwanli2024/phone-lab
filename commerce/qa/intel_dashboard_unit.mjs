import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source=await readFile(new URL('../web/intel-dashboard-ui.js',import.meta.url),'utf8');
const defaults=()=>({layers:['earthquake','flood'],panels:['trade','macro','energy','logistics'].map(id=>({id,visible:true,collapsed:false,wide:false})),language:'zh',time:'all',region:'global',link_map:false});
function fixture({save=async args=>({revision:1,preferences:args.preferences}),read}={}){
  let stored={revision:0,preferences:defaults(),layers:[],regions:{global:{label:'全球',x:0,y:0,w:720,h:360}},references:[]};
  const calls=[],changes=[],events=new Map(),window={CommerceUI:{}};
  const document={activeElement:null,querySelector:()=>null,querySelectorAll:()=>[],elementFromPoint:()=>({dataset:{intelPanel:'macro'},classList:{add(){}},closest(){return this}}),getElementById:()=>null,addEventListener:(type,fn)=>events.set(type,fn)};
  vm.runInNewContext(source,{window,document,requestAnimationFrame:fn=>fn()});
  const controller=window.CommerceIntelDashboard({api:async(name,args)=>{calls.push({name,args});if(name==='commerce_intel_dashboard_get')return structuredClone(read?await read(stored):stored);if(name==='commerce_intel_dashboard_update'){const v=await save(args);stored={...stored,...v};return v;}throw Error('Unexpected execution '+name)},esc:String,repaint(){},onChange:(...v)=>changes.push(v)});
  return {controller,calls,changes,events,stored:()=>stored};
}
test('layout changes persist only after acknowledgment and retain stable panel identities',async()=>{
  const f=fixture();await f.controller.enter();
  const panels=f.controller.panels().reverse();panels[0].collapsed=true;
  assert.equal(await f.controller.change({panels}),true);
  assert.deepEqual(Array.from(f.controller.panels(),p=>p.id),['logistics','energy','macro','trade']);
  assert.equal(f.controller.panels()[0].collapsed,true);
  assert.equal(f.calls[1].args.expected_revision,0);
  assert.equal(f.changes.length,1);
  assert.ok(!f.calls.some(c=>/reading|translation|crawler/.test(c.name)));
});
test('unknown save results are reconciled by an actual read without replaying the write',async()=>{
  let next,reads=0;
  const f=fixture({save:async args=>{next=args.preferences;throw Error('lost_response')},read:async stored=>++reads===1?stored:{...stored,revision:1,preferences:{...next}}});
  await f.controller.enter();assert.equal(await f.controller.change({language:'original'}),true);
  assert.equal(f.controller.preferences().language,'original');
  assert.equal(f.calls.filter(c=>c.name==='commerce_intel_dashboard_update').length,1);
});
test('failed saves keep the old choice and require an explicit retry',async()=>{
  let attempts=0;
  const f=fixture({save:async args=>{if(++attempts===1)throw Error('offline');return {revision:1,preferences:args.preferences}}});
  await f.controller.enter();assert.equal(await f.controller.change({time:'24'}),false);
  assert.equal(f.controller.preferences().time,'all');assert.equal(attempts,1);
  await f.controller.retry();assert.equal(f.controller.preferences().time,'24');assert.equal(attempts,2);
});
test('a conflicting layout is read and never silently overwritten',async()=>{
  let reads=0;
  const f=fixture({save:async()=>{throw Error('intel_dashboard_conflict')},read:async stored=>++reads===1?stored:{...stored,revision:2,preferences:{...stored.preferences,time:'6'}}});
  await f.controller.enter();await f.controller.change({language:'original'});
  assert.equal(f.controller.preferences().language,'zh');assert.equal(f.controller.preferences().time,'6');
  await f.controller.retry();assert.equal(f.calls.filter(c=>c.name==='commerce_intel_dashboard_update').length,1);
});
test('Chinese priority distinguishes machine titles, structured display and original text',async()=>{
  const f=fixture();await f.controller.enter();
  const row={title:'Original',display:{zh_title:'字段整理'},reading:{zh_title:'机器译文'}};
  assert.equal(f.controller.title(row),'机器译文');assert.equal(f.controller.caption(row),'机器译文 · 待校对');
  delete row.reading;assert.equal(f.controller.title(row),'字段整理');assert.equal(f.controller.caption(row),'来源字段整理');
  await f.controller.change({language:'original'});assert.equal(f.controller.title(row),'Original');assert.equal(f.controller.caption(row),'');
});
test('dragging a panel uses the same acknowledged shared ordering as keyboard actions',async()=>{
  const f=fixture();await f.controller.enter();
  f.events.get('pointerdown')({target:{closest:()=>({dataset:{intelPanelDrag:'trade'}})},button:0,pointerId:1,clientX:0,clientY:0});
  f.events.get('pointermove')({pointerId:1,clientX:100,clientY:0,preventDefault(){}});
  f.events.get('pointerup')({pointerId:1});
  await new Promise(setImmediate);
  assert.deepEqual(Array.from(f.controller.panels(),p=>p.id),['macro','trade','energy','logistics']);
  assert.equal(f.calls.at(-1).name,'commerce_intel_dashboard_update');
});

test('panel drag cancels when the pointer is released outside the dashboard',async()=>{
  const f=fixture();await f.controller.enter();
  f.events.get('pointerdown')({target:{closest:()=>({dataset:{intelPanelDrag:'trade'}})},button:0,pointerId:2,clientX:0,clientY:0});
  assert.equal(f.controller.interacting(),true);
  f.events.get('pointermove')({pointerId:2,buttons:0,clientX:20,clientY:0});
  assert.equal(f.controller.interacting(),false);
  assert.equal(f.calls.filter(c=>c.name==='commerce_intel_dashboard_update').length,0);
});
