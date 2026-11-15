import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../web/exposure-ui.js',import.meta.url),'utf8');
function fixture(){
  const calls=[],events=[];let returned=false;
  const row={id:'a'.repeat(24),record_sha256:'b'.repeat(64),title:'Synthetic flood',source:'gdacs'};
  const ui={button:({label})=>`<button>${label}</button>`,alert:x=>`<p>${x}</p>`,empty:x=>`<p>${x}</p>`,
    field:(label,html)=>label+html,input:()=>'',select:p=>`<select id="${p.id}" value="${p.value}">${p.options.map(x=>x.label).join('|')}</select>`};
  const window={CommerceUI:ui},document={querySelector:()=>null,addEventListener:(name,fn)=>events.push({name,fn})};
  vm.runInNewContext(source,{window,document,setInterval(){},crypto:globalThis.crypto,console});
  const api=async(name,args)=>{calls.push({name,args});if(name==='commerce_intel_item_get')return row;if(name==='commerce_agent_cases')return {cases:[{id:'case-a',scope:{sku:'synthetic',market:'MX'}}]};throw Error('Unexpected call '+name)};
  const exposure=window.CommerceExposure({api,esc:String,toast(){},repaint(){},modal(){},closeModal(){},isActive:()=>true,onReturnIntel:()=>{returned=true}});
  return {exposure,calls,row,get returned(){return returned},async back(){for(const e of events.filter(e=>e.name==='click'))await e.fn({target:{closest:()=>({dataset:{exposureAction:'intel-return'},focus(){}})}})}};
}
test('handoff keeps the exact source selected but leaves business scope and execution explicit',async()=>{
  const f=fixture();assert.equal(await f.exposure.select({item_id:f.row.id,record_sha256:f.row.record_sha256}),true);
  await f.exposure.enter();const html=f.exposure.view();
  assert.ok(html.includes(`id="exposure-item" value="${f.row.id}"`));
  assert.ok(html.includes('id="exposure-case" value=""'),'An unrelated case was automatically selected');
  assert.deepEqual(f.calls.map(x=>x.name),['commerce_intel_item_get','commerce_agent_cases']);
  await f.back();assert.equal(f.returned,true);
});
test('handoff rejects a newer source rather than silently assessing an unseen revision',async()=>{
  const f=fixture();await assert.rejects(()=>f.exposure.select({item_id:f.row.id,record_sha256:'c'.repeat(64)}),/exposure_source_changed/);
  assert.deepEqual(f.calls.map(x=>x.name),['commerce_intel_item_get']);
});
