import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../../web/product-workspace-ui.js',import.meta.url),'utf8');
const cut=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
const fields={currency:'币种',price:'销售单价',commission_rate:'佣金比例',payment_rate:'支付比例',return_rate:'退货比例',ad_rate:'广告比例'};
function fixture(input={currency:'CNY',price:100,commission_rate:.1,payment_rate:0,return_rate:1,ad_rate:.075}) {
  const events={},controls={},requests=[],dialogs=[];
  const s={id:'exact-case',generation:1,actionEpoch:0,changes:0,busy:false,tab:'cost',edits:{},dirty:new Set(),fieldErrors:{},data:{case:{id:'exact-case',currency:'CNY'},source_sha256:'source',forms:{cost:{payload:{input},revision:3}},calculation:{status:'CALCULATED'}}};
  const context=vm.createContext({s,fields,planEdit:null,modalEdited:false,reportEditState(){},structuredClone,reactHost:false,Object,Number,Set,document:{addEventListener:(name,fn)=>events[name]=fn,getElementById:()=>null,querySelector:()=>null,activeElement:null},window:{},esc:String,ui:{table:(headers,rows)=>rows.join(''),badge:()=>'',field:(label,control)=>label+control,input:props=>{controls[props['data-pw-cost']]=props;return '';}},section:(title,html)=>html,formStatus:()=>'',gaps:()=>'',costSummary:()=>'',btn:()=>'',announce(){},dirty:name=>{s.dirty.add(name);s.changes++;},reload:async()=>{},render(){},closeDialog(){},message:e=>e.message,decimal:n=>Number(n).toFixed(2),amount:(n,c)=>n+' '+c,empty:String,dialog:(title,html)=>dialogs.push(html),api:async(tool,args)=>{requests.push({tool,args});return tool==='commerce_cost_scenarios_get'?{items:[{label:'百分数情景',stale:false,cost_revision:3,input,result:{price:100,total_cost:50,contribution:50,contribution_rate:.5,currency:'CNY'}}]}:{};}});
  const helpers=source.includes('  function costDisplayValue(')?cut('  function costDisplayValue(','  function contentView('):cut('  function costView(','  function contentView(');
  vm.runInContext(cut('  function formData(','  function formStatus(')+helpers+cut('  async function saveForm(','  function openResearchCandidate(')+cut('  async function act(','  document.addEventListener(\'click\'')+cut("  document.addEventListener('input'","  document.addEventListener('change'")+`;this.actions={costView,saveForm,act,costScenarioValue};`,context);
  return {s,events,controls,requests,dialogs,...context.actions};
}
test('product cost stays read-only while saved percentage values remain human readable',()=>{const f=fixture();assert.equal(f.costScenarioValue('commission_rate',.1),'10%');assert.equal(f.costScenarioValue('payment_rate',0),'0%');assert.equal(f.costScenarioValue('return_rate',1),'100%');assert.doesNotMatch(f.costView(),/<input|<form|动态成本测算/);});
test('editing and saving percentages keeps the 0–1 backend contract and exact case',async()=>{
  const f=fixture();
  for(const [key,value] of [['commission_rate','10'],['payment_rate','0'],['return_rate','100']])f.events.input({target:{id:'pw-cost-'+key,dataset:{pwCost:key},value}});
  await f.saveForm('cost');const saved=f.requests[0];
  assert.equal(saved.tool,'commerce_workspace_save');assert.equal(saved.args.case_id,'exact-case');
  assert.deepEqual({...saved.args.payload.input},{currency:'CNY',price:100,commission_rate:.1,payment_rate:0,return_rate:1,ad_rate:.075});
});
test('empty rate stays missing and an out-of-range percentage is rejected before save',async()=>{
  const f=fixture();f.events.input({target:{id:'pw-cost-ad_rate',dataset:{pwCost:'ad_rate'},value:''}});
  assert.equal(Object.hasOwn(f.s.edits.cost.input,'ad_rate'),false);
  f.events.input({target:{id:'pw-cost-commission_rate',dataset:{pwCost:'commission_rate'},value:'101'}});
  await assert.rejects(f.saveForm('cost'),/invalid_commission_rate/);assert.equal(f.requests.length,0);
});
test('saved scenario parameters show percentage units without changing frozen input',async()=>{
  const f=fixture();await f.act('scenario-compare',{});const html=f.dialogs.at(-1);
  assert.match(html,/佣金比例<\/dt><dd>10%/);assert.match(html,/退货比例<\/dt><dd>100%/);
  assert.equal(f.s.data.forms.cost.payload.input.commission_rate,.1);
});
function workflowFixture() {
  const s={dirty:new Set(),data:{stages:['S1','S2','S3','S4','S5'].map(id=>({id,status:'PASS'})),calculation:{status:'CALCULATED',stale:false},artifacts:{images:{intact:true}},content_drafts:[{preflight:{status:'current',ready_for_local_review:true}}],delivery_review:{status:'local_review_recorded'}}};
  const context=vm.createContext({s});vm.runInContext(cut('  function workflow()','  function taskSummary()')+';this.workflow=workflow;',context);return {s,workflow:context.workflow};
}
test('product progression stops at unsaved or stale content and never calls a local review published',()=>{
  const f=workflowFixture();assert.equal(f.workflow().find(row=>!row.complete).action,'listing');
  f.s.dirty.add('content');assert.equal(f.workflow().find(row=>!row.complete).action,'tab-content');
  f.s.dirty.clear();f.s.data.content_drafts[0].preflight.status='stale';assert.equal(f.workflow().find(row=>!row.complete).action,'tab-content');
  assert.doesNotMatch(JSON.stringify(f.workflow()),/已发布/);
});
test('missing media and a non-passing delivery gate stay an actionable media step',()=>{
  const f=workflowFixture();f.s.data.stages.find(row=>row.id==='S4').status='HOLD';
  assert.equal(f.workflow().find(row=>!row.complete).action,'tab-media');
  assert.equal(f.workflow().find(row=>row.id==='review').complete,false);
});
test('product-to-listing, plan and handoff navigation retains the exact case',async()=>{
  const f=fixture(),messages=[];const context=vm.createContext({s:f.s,reactHost:true,parent:{postMessage:value=>messages.push(value)},nonce:'test',document:{},window:{}});
  vm.runInContext(cut('  async function act(',"  document.addEventListener('click'")+';this.act=act;',context);
  for(const action of ['listing','workflow','organization'])await context.act(action,{});
  assert.equal(messages.length,3);for(const value of messages){assert.equal(value.case_id,'exact-case');assert.equal(value.type,'commerce:workspace-navigate');}
});
test('source translation checks return to research before downstream local review',()=>{
  const f=workflowFixture();f.s.data.stages.find(row=>row.id==='S5').status='HOLD';
  assert.equal(f.workflow().find(row=>!row.complete).action,'tab-research');
});
