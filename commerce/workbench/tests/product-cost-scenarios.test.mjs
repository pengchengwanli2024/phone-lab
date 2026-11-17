import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {transform} from 'esbuild';
import vm from 'node:vm';
const source=(await readFile(new URL('../src/product-cost-scenarios.tsx',import.meta.url),'utf8')).replace(/^import[^\n]*\n/gm,'').replace(/\bexport /g,'');
const compiled=(await transform(source+';this.Component=ProductCostScenarios;',{loader:'tsx',jsxFactory:'h',jsxFragment:'Fragment'})).code;
const flush=()=>new Promise(setImmediate);
const snapshot={caseId:'case-a',sourceSha:'source-a',costRevision:4};
const row=(id,label='同名情景')=>({id,label,source_sha256:'source-a',cost_revision:4,sha256:id.repeat(8),stale:false,input:{currency:'CNY',price:100,commission_rate:.1,payment_rate:0},result:{status:'CALCULATED',price:100,total_cost:60,contribution:40,contribution_rate:.4,currency:'CNY',missing:[]}});
function fixture(api){
 const slots=[],effects=[],requests=[],reports=[],writing=[];let cursor=0,sequence=0,tree,props={snapshot,disabled:false,onEditState:v=>reports.push(v),onWriting:v=>writing.push(v)};
 const context=vm.createContext({Error,TypeError,Number,String,Object,JSON,labels:{currency:'币种',price:'销售单价',commission_rate:'佣金比例',payment_rate:'支付比例'},errorText:e=>e.message,newKey:()=>`scenario-key-${++sequence}`,api:async(name,args)=>{requests.push({name,args:JSON.parse(JSON.stringify(args))});return api(name,args);},h:(type,attributes,...children)=>({type,props:{...attributes,children:children.flat(Infinity)}}),Fragment:Symbol('fragment'),...Object.fromEntries(['Badge','Button','Empty','ErrorNotice','Money','Panel'].map(name=>[name,name])),useState(value){const id=cursor++;if(!(id in slots))slots[id]={value};return [slots[id].value,next=>{slots[id].value=typeof next==='function'?next(slots[id].value):next}];},useRef(value){const id=cursor++;if(!(id in slots))slots[id]={current:value};return slots[id];},useEffect(effect,deps){const id=cursor++,before=slots[id];if(!before||deps.some((v,i)=>v!==before.deps[i])){effects.push(()=>{before?.cleanup?.();slots[id]={deps,cleanup:effect()};});}}});
 vm.runInContext(compiled,context);
 function render(update={}){props={...props,...update};cursor=0;tree=context.Component(props);while(effects.length)effects.shift()();return tree;}
 function all(node=tree){return node&&typeof node==='object'?[node,...[...(node.props?.children||[]),node.props?.action].filter(x=>x!==undefined).flatMap(all)]:[];}
 function text(node=tree){return node==null?'':typeof node==='object'?(node.props?.children||[]).map(text).join(''):String(node);}
 function input(){return all().find(n=>n.type==='input');}
 function button(label){const found=all().find(n=>n.type==='Button'&&text(n)===label);assert.ok(found,`button ${label}`);return found;}
 async function click(label){const b=button(label);assert.equal(!!b.props.disabled,false,`${label} should be enabled`);b.props.onClick();render();await flush();render();}
 function type(value){assert.equal(!!input().props.disabled,false);input().props.onChange({target:{value}});render();}
 render();return {render,click,type,input,button,text,all,requests,reports,writing,unmount:()=>slots.forEach(slot=>slot.cleanup?.())};
}
test('scenario save freezes exact case/source/revision and duplicate labels remain separate records',async()=>{
 const records=[];const f=fixture((name,args)=>{assert.equal(name,'commerce_cost_scenarios_save');records.push(row(String(records.length+1),args.label));return {case_id:'case-a',items:[...records]}});
 f.type(' 同名情景 ');await f.click('保存当前测算为情景');assert.deepEqual(f.requests[0].args,{case_id:'case-a',label:'同名情景',expected_source_sha256:'source-a',expected_revision:4,idempotency_key:'scenario-key-1'});assert.equal(f.input().props.value,'');
 f.type('同名情景');await f.click('保存当前测算为情景');assert.notEqual(f.requests[0].args.idempotency_key,f.requests[1].args.idempotency_key);assert.equal(f.all().filter(n=>n.type==='tr').length,3);assert.match(f.text(),/10%/);assert.match(f.text(),/0%/);assert.equal(f.reports.at(-1),false);
});
test('unsaved parameters disable scenario writes while comparison stays read-only and preserves the label',async()=>{
 const f=fixture(()=>({case_id:'case-a',items:[row('1')]}));f.render({disabled:true});f.type('未保存情景');assert.equal(f.button('保存当前测算为情景').props.disabled,true);await f.click('读取已保存情景');assert.deepEqual(f.requests.map(r=>r.name),['commerce_cost_scenarios_get']);assert.equal(f.input().props.value,'未保存情景');assert.equal(f.reports.at(-1),true);
});
test('failed save preserves input and its intent without automatically repeating the request',async()=>{
 const f=fixture(()=>{throw Error('form_draft_conflict')});f.type('保留名称');await f.click('保存当前测算为情景');assert.equal(f.input().props.value,'保留名称');assert.equal(f.requests.length,1);assert.match(f.text(),/form_draft_conflict/);assert.equal(f.reports.at(-1),true);
});
test('unknown outcome requires a read before explicit retry and reuses the original idempotency key',async()=>{
 let first=true;const f=fixture(name=>{if(name==='commerce_cost_scenarios_save'&&first){first=false;throw TypeError('network interrupted')}return {case_id:'case-a',items:[row('1','保留原意图')]}});f.type('保留原意图');await f.click('保存当前测算为情景');assert.equal(f.button('保存当前测算为情景').props.disabled,true);assert.match(f.text(),/保存回执尚未确认/);await f.click('读取已保存情景');assert.equal(f.requests.filter(r=>r.name==='commerce_cost_scenarios_save').length,1);await f.click('保存当前测算为情景');assert.equal(f.requests[0].args.idempotency_key,f.requests[2].args.idempotency_key);assert.equal(f.input().props.value,'');
});
test('source changes mark retained history stale and a late save cannot claim the new source was saved',async()=>{
 let resolve;const f=fixture(name=>name==='commerce_cost_scenarios_save'?new Promise(r=>resolve=r):{case_id:'case-a',items:[row('1')]});await f.click('读取已保存情景');f.render({snapshot:{...snapshot,sourceSha:'source-b'}});assert.match(f.text(),/依据已变化/);f.type('旧来源请求');const button=f.button('保存当前测算为情景');button.props.onClick();f.render();f.render({snapshot:{...snapshot,sourceSha:'source-c'}});resolve({case_id:'case-a',items:[row('2','旧来源请求')]});await flush();f.render();assert.equal(f.input().props.value,'旧来源请求');assert.doesNotMatch(f.text(),/成本情景已保存/);
});

test('a response from a different product cannot be displayed or reported as a saved scenario',async()=>{
 const f=fixture(()=>({case_id:'case-b',items:[row('other','Wrong product')]}));await f.click('读取已保存情景');assert.doesNotMatch(f.text(),/Wrong product/);assert.match(f.text(),/workspace_source_changed/);f.type('Keep current label');await f.click('保存当前测算为情景');assert.equal(f.input().props.value,'Keep current label');assert.doesNotMatch(f.text(),/成本情景已保存/);
});
