import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../../web/product-workspace-ui.js',import.meta.url),'utf8');
const cut=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));

function fixture() {
  const dialogs=[],requests=[],links=[];
  const view={status:'needs_inputs',package_sha256:'old-package',source_sha256:'old-source',professional_gate:'BLOCKED',latest:null,
    automatic_checks:[{id:'cost',label:'同币种贡献与草稿售价',passed:false}],requirements:{facts:'商品事实'},checks:{facts:{status:'pending',source_ref:'',note:''}}};
  const s={id:'same-case',tab:'review',busy:false,actionEpoch:0,generation:1,changes:1,edits:{cost:{input:{currency:'CNY',price:120,commission_rate:.1}}},dirty:new Set(['cost']),fieldErrors:{},data:{case:{id:'same-case',currency:'CNY'},name:'Synthetic item',source_sha256:'old-source',delivery_review:view,forms:{cost:{revision:2,stale:true,payload:{input:{currency:'CNY',price:100,commission_rate:.1}}}},calculation:{status:'HOLD',stale:true}}};
  const context=vm.createContext({s,fields:{currency:'币种',price:'售价',commission_rate:'佣金'},structuredClone,crypto:{randomUUID:()=>`synthetic-${requests.length}`},reactHost:false,bridged:true,nonce:'test',parent:{postMessage:m=>links.push(m)},
    deliveryEdit:null,deliveryError:'',deliveryNotice:'',deliveryEpoch:0,deliveryReturnCase:'',
    document:{getElementById:()=>null,querySelector:()=>null,activeElement:null,body:{}},
    esc:String,alert:String,ui:{badge:(label)=>label,field:(label,input)=>label+input,input:()=>'',select:()=>''},
    btn:(label,action,_primary,attrs={})=>`<button data-pw-action="${action}" ${attrs.disabled?'disabled':''}>${label}</button>`,
    section:(_title,html)=>html,formStatus:()=>'',gaps:()=>'',costSummary:()=>'',announce(){},render(){},closeDialog(){},selectTab:tab=>{s.tab=tab;},
    message:error=>error.message,dialog:(title,body,actions)=>dialogs.push({title,html:body+actions}),
    api:async(tool,args)=>{requests.push({tool,args});if(tool==='commerce_workspace_save')return {};if(tool==='commerce_workspace_calculate')return {status:'CALCULATED'};throw Error('unexpected tool '+tool);},
    reload:async()=>{s.data.source_sha256='new-source';s.data.forms.cost.revision++;s.data.forms.cost.stale=false;s.data.calculation={status:'CALCULATED',stale:false};s.data.delivery_review={...view,source_sha256:'new-source',package_sha256:'new-package',automatic_checks:[{id:'cost',label:'同币种贡献与草稿售价',passed:true}]};return 'refreshed';}});
  vm.runInContext(cut('  function formData(','  function formStatus(')+cut('  function costDisplayValue(','  function contentView(')+cut('  function deliveryEnabled(','  const format =')+cut('  async function saveForm(','  function openResearchCandidate(')+cut('  async function act(',"  document.addEventListener('click'")+`;this.actions={deliveryAction,deliveryDialog,costView,act};`,context);
  return {s,dialogs,requests,links,context,...context.actions};
}

test('delivery cost recovery keeps unsaved opinions and cost input on the same case',async()=>{
  const f=fixture();f.deliveryDialog();
  assert.match(f.dialogs.at(-1).html,/data-pw-action="delivery-open-cost"/);
  vm.runInContext(`deliveryEdit.checks.facts={status:'confirmed',source_ref:'synthetic:opinion',note:'keep my review note'};`,f.context);
  await f.deliveryAction('delivery-open-cost');
  assert.equal(f.s.tab,'cost');assert.equal(f.s.id,'same-case');assert.equal(f.links[0].case_id,'same-case');assert.equal(f.links[0].return_delivery,true);
  assert.equal(f.s.edits.cost.input.price,120);
  assert.match(f.costView(),/data-pw-action="delivery-return"/);
  await f.act('save-calculate',{dataset:{pwAction:'save-calculate'}});
  assert.deepEqual(f.requests.map(row=>[row.tool,row.args.case_id]),[['commerce_workspace_save','same-case'],['commerce_workspace_calculate','same-case']]);
  assert.equal(f.requests[0].args.payload.input.price,120);
  await f.deliveryAction('delivery-return');
  assert.equal(f.s.tab,'review');assert.equal(f.s.id,'same-case');
  assert.match(f.dialogs.at(-1).html,/当前交付版本已改变/);
  assert.match(f.dialogs.at(-1).html,/data-pw-action="delivery-confirm" disabled/);
  assert.equal(vm.runInContext('deliveryEdit.checks.facts.note',f.context),'keep my review note');
  assert.equal(vm.runInContext('deliveryEdit.package',f.context),'old-package');
  await f.deliveryAction('delivery-reset');
  assert.equal(vm.runInContext('deliveryEdit.checks.facts.note',f.context),'keep my review note');
  assert.equal(vm.runInContext('deliveryEdit.checks.facts.source_ref',f.context),'synthetic:opinion');
  assert.equal(vm.runInContext('deliveryEdit.checks.facts.status',f.context),'pending');
  assert.equal(vm.runInContext('deliveryEdit.package',f.context),'new-package');
});

test('delivery return never carries another product review into the current case',async()=>{
  const f=fixture();f.deliveryDialog();await f.deliveryAction('delivery-open-cost');
  f.s.id='another-case';f.s.data.case.id='another-case';
  assert.doesNotMatch(f.costView(),/data-pw-action="delivery-return"/);
  await f.deliveryAction('delivery-return');
  assert.equal(f.s.tab,'cost');assert.equal(f.dialogs.length,1);
});

test('a failed recovery save keeps the original cost edit and review opinion',async()=>{
  const f=fixture();f.deliveryDialog();
  vm.runInContext(`deliveryEdit.checks.facts.note='unsaved opinion';`,f.context);
  await f.deliveryAction('delivery-open-cost');
  f.context.api=async()=>{throw Error('workspace_source_changed');};
  await f.act('save-calculate',{dataset:{pwAction:'save-calculate'}});
  assert.equal(f.s.errorCode,'workspace_source_changed');
  assert.equal(f.s.edits.cost.input.price,120);assert.equal(f.s.dirty.has('cost'),true);
  await f.deliveryAction('delivery-return');
  assert.equal(vm.runInContext('deliveryEdit.checks.facts.note',f.context),'unsaved opinion');
  assert.equal(vm.runInContext('deliveryEdit.package',f.context),'old-package');
  assert.match(f.dialogs.at(-1).html,/data-pw-action="delivery-confirm" disabled/);
});
