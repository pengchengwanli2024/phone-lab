import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source=await readFile('../web/copilot-ui.js','utf8');
async function render(code){
  const calls=[],listeners={addEventListener(){},removeEventListener(){}};
  const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const ui={escape,icon:()=>'',moduleDetails:()=>({label:'全球情报'}),badge:escape,alert:escape,field:()=>'',select:()=>'',button:({label})=>escape(label)};
  const document={...listeners,querySelector:()=>null,querySelectorAll:()=>[],getElementById:()=>null,activeElement:null};
  const window={...listeners,CommerceUI:ui,innerWidth:1440,dispatchEvent(){}};
  const context={module:'intelligence',demo:false};
  const run={id:'original-run',status:'unknown',host_diagnostic:code?{code}:null,
    result:{error:'agent_provider_outcome_unknown',observations:[]},actions:[]};
  const thread={id:'original-thread',context,context_sha256:'scope',turns:[{question:'原问题',run}],latest_run:run,
    model_selection:{model_id:'project-default',available:true,sha256:'a'.repeat(64)}};
  vm.runInNewContext(source,{window,document,crypto:{randomUUID:()=> 'synthetic-key'},setInterval(){},clearInterval(){},CustomEvent:class{},localStorage:{getItem:key=>key.startsWith('commerce-copilot-selection:')?thread.id:null,setItem(){}}});
  const controller=window.CommerceCopilot({inline:true,compact:true,getContext:()=>context,repaint(){},
    api:async(name)=>{calls.push(name);if(name==='commerce_model_list')return{models:[{id:'project-default',selectable:true}]};if(name==='commerce_copilot_list')return{threads:[thread]};if(name==='commerce_copilot_get')return thread;throw Error('unexpected effect '+name);}});
  controller.open(undefined,{focus:false});await new Promise(setImmediate);
  const html=controller.view();controller.dispose();return {html,calls};
}

test('original unknown output-limit result explains interruption without replaying it',async()=>{
  const {html,calls}=await render('native_output_limit');
  assert.match(html,/模型输出额度耗尽，完整分析未生成/);
  assert.match(html,/原请求未重发/);assert.match(html,/原问题/);
  assert.ok(calls.every(name=>/_(get|list)$/.test(name)));
});
test('invalid native JSON explains rejection while missing or unknown diagnostics stay unknown',async()=>{
  assert.match((await render('native_invalid_json')).html,/结果格式无效/);
  for(const code of [null,'other-code','toString']){
    const {html}=await render(code);assert.match(html,/结果尚未确认，请先核对原记录/);
  }
});
