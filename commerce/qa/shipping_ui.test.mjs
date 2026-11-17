import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {existsSync,readFileSync} from 'node:fs';

class SvgNode extends EventTarget {
  constructor(name,document){super();this.nodeName=name;this.ownerDocument=document;this.attributes=new Map();this.children=[];this.captures=new Set();this.textContent='';this.classList={add(){},remove(){}};}
  getAttribute(key){return this.attributes.get(key)??null;}
  setAttribute(key,value){this.attributes.set(key,String(value));}
  removeAttribute(key){this.attributes.delete(key);}
  appendChild(node){this.children.push(node);return node;}
  replaceChildren(...nodes){this.children=nodes;}
  getBoundingClientRect(){return {width:640,height:340};}
  setPointerCapture(id){this.captures.add(id);}
  hasPointerCapture(id){return this.captures.has(id);}
  releasePointerCapture(id){this.captures.delete(id);}
  focus(){this.ownerDocument.activeElement=this;}
}
const preset={id:'container-20gp',name:'20GP 集装箱参考',kind:'container',model_id:'container-20gp',inner_cm:[590,235.2,239.5],outer_cm:[605.8,243.8,259.1],tare_kg:2350,max_weight_kg:30480,packaging_cost:'',door_cm:[234,229.2],reference:{status:'reference',source_name:'规格示例',source_urls:['https://example.com/specification'],checked_on:'2026-11-16',note:'装货前复测'}};
const packed={carton_name:'合成测试柜',carton_id:'synthetic',kind:'container',inner_cm:[40,30,20],outer_cm:[42,32,22],gross_weight_kg:3,volume_utilization_pct:5,packaging_cost:'',items:[{sku:'A',position_cm:[0,0,0],orientation_cm:[10,10,10],weight_kg:1}]};
function plan(){return {id:'saved',sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),input:{},created_at:'2026-11-16T00:00:00Z',mode:'warehouse',input_units:1,variants:{space:{groups:[{group_id:'BATCH',boxes:[packed],unplaced:[],placed_units:1,input_units:1,quote:null}],complete:true,box_count:1,total_outer_volume_cm3:30000,gross_weight_kg:3,shipping_cost:null,packaging_cost:null,total_cost:null,currency:'CNY'},cost:null},comparisons:[{group_id:'BATCH',candidate_count:1}],notice:'参考尺寸须复测',synthetic:true};}

function harness({orders=[],handleApi,save=async()=>({status:'requested',filename:'plan.csv'}),pick=async()=>({status:'cancelled'}),readCsv}={}) {
  const comparisonTimers=new Map();let comparisonTimerId=-1;
  const listeners={},nodes={},window=Object.assign(new EventTarget(),{matchMedia:()=>({matches:false,addEventListener(){}})});
  const document={defaultView:window,documentElement:{dataset:{},style:{setProperty(){}}},addEventListener:(type,fn)=>listeners[type]=fn,querySelector:selector=>nodes[selector]||null,querySelectorAll:selector=>selector==='[data-shipping-action]'?Object.values(nodes).filter(node=>node.dataset?.shippingAction):[],createElementNS:(_,name)=>new SvgNode(name,document)};
  const sandbox={window,document,console,Intl,Date,Number,JSON,Set,Map,Promise,URL,Blob,TextDecoder,TextEncoder,setTimeout:(fn,ms)=>{if(ms===350){const id=comparisonTimerId--;comparisonTimers.set(id,fn);return id;}return setTimeout(fn,ms);},clearTimeout:id=>{if(comparisonTimers.has(id))comparisonTimers.delete(id);else clearTimeout(id);},CustomEvent:class extends Event {constructor(type,args){super(type);this.detail=args.detail;}}};
  vm.createContext(sandbox);
  for(const source of ['../ui/status.js','../ui/kit.js','../web/shipping-viewer.js','../ui/shipping-files.js'])if(existsSync(new URL(source,import.meta.url)))vm.runInContext(readFileSync(new URL(source,import.meta.url),'utf8'),sandbox);
  // Saving belongs to the host, so isolate only that external boundary. Once the
  // shared file helper exists, reads exercise its real validation and decoding.
  const fileRequests=[];
  window.CommerceShippingFiles={...window.CommerceShippingFiles,readCsv:readCsv||window.CommerceShippingFiles?.readCsv||(async(file)=>({content:new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer()),filename:file.name,bytes:file.size})),createClient:()=>({request:(op,args)=>{fileRequests.push({op,args});return op==='pick-csv'?pick(args):save(args.file);},dispose(){}})};
  vm.runInContext(readFileSync(new URL('../web/shipping-ui.js',import.meta.url),'utf8'),sandbox);
  let app,html='',pending,created,paints=0,active=true;
  const summary=plan(),apiCalls=[];
  const api=async(name,args)=>{
    apiCalls.push({name,args});const handled=handleApi?.(name,args);if(handled!==undefined)return handled;
    if(name==='commerce_shipping_state')return {rate_books:[],model_catalog:{models:[preset],notice:'商品直接装入所选箱型或柜型；参考值可修改'},plans:[{id:'saved',created_at:'2026-11-16',mode:'warehouse',input_units:20,synthetic:true}]};
    if(name==='commerce_shipping_plan_create'){created=args.input;return new Promise(resolve=>pending=resolve);}
    if(name==='commerce_shipping_compare')return comparison(args.input);
    if(name==='commerce_shipping_plan_get')return {...summary,input:created};
    if(name==='commerce_shipping_rates_preview')return {sha256:args.content+'-hash',rates:[],source_ref:args.source_ref,synthetic:args.synthetic};
    if(name==='commerce_shipping_rates_import')return {id:'rates-saved'};
    if(name==='commerce_shipping_export'||name==='commerce_shipping_template')return {filename:'plan.csv',mime_type:'text/csv;charset=utf-8',content:'sku,quantity\nA,1'};
    throw Error(name);
  };
  function repaint(){paints++;html=app.view();for(const key of Object.keys(nodes))delete nodes[key];for(const tag of html.match(/<button\b[^>]*>/g)||[]){const action=tag.match(/data-shipping-action="([^"]+)"/)?.[1];if(action)nodes[`[data-shipping-action="${action}"]`]={disabled:/\sdisabled(?:\s|>)/.test(tag),textContent:action,dataset:{shippingAction:action}};}let resultHtml='';nodes['#shipping-result']={get innerHTML(){return resultHtml;},set innerHTML(value){resultHtml=value;for(const id of ['shipping-step','shipping-step-label','shipping-camera'])nodes['#'+id]={textContent:'',value:''};if(value.includes('id="shipping-scene"'))nodes['#shipping-scene']=new SvgNode('svg',document);else delete nodes['#shipping-scene'];}};nodes['.shipping-rates']={open:/<details class="shipping-rates"[^>]*\bopen(?:\s|>)/.test(html)};for(const id of ['shipping-step','shipping-step-label','shipping-camera'])nodes['#'+id]={textContent:'',value:''};if(html.includes('id="shipping-scene"'))nodes['#shipping-scene']=new SvgNode('svg',document);app.afterPaint();}
  app=window.CommerceShipping({api,ui:window.CommerceUI,esc:v=>String(v??''),repaint,isActive:()=>active,getOrders:()=>orders});
  const click=(action,extra={})=>{const tag=(nodes['#shipping-result']?.innerHTML.match(/<button\b[^>]*>/g)||[]).find(tag=>tag.includes(`data-shipping-action="${action}"`)&&(!extra.model||tag.includes(`data-model="${extra.model}"`)));const b={dataset:{shippingAction:action,...extra},disabled:tag?/\sdisabled(?:\s|>)/.test(tag):nodes[`[data-shipping-action="${action}"]`]?.disabled};listeners.click({target:{closest:selector=>selector==='[data-shipping-action]'?b:null}});};
  const clickLabel=label=>{
    const button=(html.match(/<button\b[^>]*>[^<]*<\/button>/g)||[]).find(tag=>tag.slice(tag.indexOf('>')+1,-9)===label);assert.ok(button,`missing rendered button: ${label}`);
    const dataset=Object.fromEntries([...button.matchAll(/data-([a-z-]+)="([^"]*)"/g)].map(([,key,value])=>[key.replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase()),value]));
    const target={dataset,disabled:/\sdisabled(?:\s|>)/.test(button)};listeners.click({target:{closest:selector=>selector==='[data-shipping-action]'?target:null}});
  };
  const input=(dataset,value)=>listeners.input({target:{dataset,value,closest:()=>true,type:'number'}});
  const change=(id,value,dataset={},files)=>listeners.change({target:{id,value,dataset,files,closest:()=>true}});
  return {app,click,clickLabel,input,change,repaint,apiCalls,fileRequests,runComparisonTimers:async()=>{const tasks=[...comparisonTimers.values()];comparisonTimers.clear();for(const fn of tasks)await fn();},setActive:value=>{active=value;},get activeElement(){return document.activeElement;},node:selector=>nodes[selector],get paints(){return paints;},get html(){return html;},get calculate(){return nodes['[data-shipping-action="calculate"]'];},resolve:(result=summary)=>pending(result),get created(){return created;}};
}
const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function comparison(input,total='9300.00'){
  return {persisted:false,input_sha256:'compare-input',models:['20gp','40gp','40hq'].map((code,i)=>{
    const p=plan(),id='container-'+code;p.id='preview-'+code;p.sha256=code.repeat(32);p.input=JSON.parse(JSON.stringify(input));p.input.cartons=[{...preset,id,model_id:id,name:code.toUpperCase()+' 集装箱参考'}];p.persisted=false;p.variants.space.groups[0].boxes[0]={...packed,carton_name:code.toUpperCase()+' 预览柜',inner_cm:[40+i*20,30,20]};
    return {model_id:id,model:p.input.cartons[0],status:'ready',plan:p,selected_variant:'space',summary:{box_count:1,placed_units:1,unplaced_units:0,volume_utilization_pct:[59.6,58.4,51.9][i],shipping_cost:total,packaging_cost:'0.00',total_cost:i===1?total:'10850.00',currency:'CNY',complete:true}};
  })};
}
async function containerForm(h){await h.app.open();h.click('example');await h.change('shipping-model','container-20gp');h.click('add-model');}

// Break caught: container comparisons still require three mutating plan calls.
test('container models render side by side from one debounced read-only request',async()=>{
  const h=harness();await containerForm(h);await h.runComparisonTimers();await tick();
  const requests=h.apiCalls.filter(x=>x.name==='commerce_shipping_compare');assert.equal(requests.length,1);assert.equal(requests[0].args.input.items[0].quantity,12);
  assert.equal(h.apiCalls.filter(x=>x.name==='commerce_shipping_plan_create').length,0);
  for(const code of ['20GP','40GP','40HQ'])assert.match(h.node('#shipping-result').innerHTML,new RegExp(`查看${code}装柜`));
  assert.match(h.node('#shipping-result').innerHTML,/59\.6/);assert.match(h.node('#shipping-result').innerHTML,/58\.4/);assert.match(h.node('#shipping-result').innerHTML,/51\.9/);assert.match(h.node('#shipping-result').innerHTML,/9300\.00/);
});

// Break caught: each keystroke writes a draft or a stale result interrupts editing.
test('quantity and dimension edits coalesce and update only the result area',async()=>{
  const h=harness();await containerForm(h);await h.runComparisonTimers();await tick();const paints=h.paints;
  h.input({shippingItem:'0',key:'quantity'},'61');h.input({shippingItem:'0',key:'quantity'},'62');h.input({shippingItem:'0',key:'length_cm'},'110');await h.runComparisonTimers();await tick();
  const requests=h.apiCalls.filter(x=>x.name==='commerce_shipping_compare');assert.equal(requests.length,2);assert.equal(requests[1].args.input.items[0].quantity,62);assert.equal(requests[1].args.input.items[0].length_cm,110);assert.equal(h.paints,paints);
});

// Break caught: an old network response can overwrite the newest model prices.
test('the newest comparison wins when an earlier quantity response arrives last',async()=>{
  const waiting=[];const h=harness({handleApi:(name,args)=>name==='commerce_shipping_compare'?new Promise(resolve=>waiting.push({resolve,input:args.input})):undefined});await containerForm(h);h.runComparisonTimers();await tick();
  h.input({shippingItem:'0',key:'quantity'},'63');h.runComparisonTimers();await tick();assert.equal(waiting.length,2);
  waiting[1].resolve(comparison(waiting[1].input,'222.00'));await tick();waiting[0].resolve(comparison(waiting[0].input,'111.00'));await tick();
  assert.match(h.node('#shipping-result').innerHTML,/222\.00/);assert.doesNotMatch(h.node('#shipping-result').innerHTML,/111\.00/);
});

// Break caught: model buttons change a label while retaining another model's scene.
test('each model selects its own plan in the shared real 3D viewer',async()=>{
  const h=harness();await containerForm(h);await h.runComparisonTimers();await tick();
  for(const code of ['20gp','40gp','40hq']){h.click('view-model',{model:'container-'+code});assert.match(h.node('#shipping-result').innerHTML,new RegExp(code.toUpperCase()+' 预览柜'));assert.ok(h.node('#shipping-scene'));assert.match(h.node('#shipping-camera').textContent,/显示 1 \/ 1 件/);}
});

// Break caught: an unconfirmed edited quote silently keeps the previous prices.
test('editing quote content clears pricing and selecting a saved version recalculates it',async()=>{
  const h=harness();await containerForm(h);h.input({shippingField:'rate_book_id'},'old-book');await h.runComparisonTimers();await tick();
  h.input({shippingField:'rateContent'},'changed tariff');await h.runComparisonTimers();await tick();
  let calls=h.apiCalls.filter(x=>x.name==='commerce_shipping_compare');assert.equal(calls.at(-1).args.input.rate_book_id,'');
  h.input({shippingField:'rate_book_id'},'new-book');await h.runComparisonTimers();await tick();calls=h.apiCalls.filter(x=>x.name==='commerce_shipping_compare');assert.equal(calls.at(-1).args.input.rate_book_id,'new-book');
});

// Break caught: a read-only preview's absent id is sent directly to export.
test('export saves just the selected model snapshot before requesting its immutable file',async()=>{
  const h=harness();await containerForm(h);await h.runComparisonTimers();await tick();h.click('view-model',{model:'container-40hq'});h.click('export',{format:'json'});await tick();
  assert.equal(h.created.cartons.length,1);assert.equal(h.created.cartons[0].model_id,'container-40hq');assert.equal(h.apiCalls.filter(x=>x.name==='commerce_shipping_export').length,0);
  const saved=plan();saved.id='saved-hq';saved.input=h.created;saved.input_sha256='saved-input';h.resolve(saved);await tick();
  assert.equal(h.apiCalls.find(x=>x.name==='commerce_shipping_export').args.plan_id,'saved-hq');assert.equal(h.fileRequests.filter(x=>x.op==='download').length,1);
});

// Break caught: returning to the page revives a comparison started before departure.
test('a comparison response from before leaving cannot revive after returning',async()=>{
  let finish;const h=harness({handleApi:(name,args)=>name==='commerce_shipping_compare'?new Promise(resolve=>finish=()=>resolve(comparison(args.input,'111.00'))):undefined});
  await containerForm(h);h.runComparisonTimers();await tick();h.setActive(false);h.app.beforePaint();h.setActive(true);h.repaint();finish();await tick();
  assert.doesNotMatch(h.node('#shipping-result').innerHTML,/111\.00/);
});

// Break caught: invalid intermediate input leaves a previous price or enabled 3D selection.
test('clearing a required quantity removes stale model prices without requesting a calculation',async()=>{
  const h=harness();await containerForm(h);await h.runComparisonTimers();await tick();const calls=h.apiCalls.length;
  h.input({shippingItem:'0',key:'quantity'},'');await h.runComparisonTimers();await tick();
  assert.equal(h.apiCalls.length,calls);assert.doesNotMatch(h.node('#shipping-result').innerHTML,/9300\.00/);assert.ok(!h.node('#shipping-scene'));
});

// Break caught: switching model while a preview is being saved exports the old model.
test('switching model during lazy persistence cannot open a download for the old selection',async()=>{
  const h=harness();await containerForm(h);await h.runComparisonTimers();await tick();h.click('view-model',{model:'container-20gp'});h.click('export',{format:'json'});await tick();
  h.click('view-model',{model:'container-40hq'});const saved=plan();saved.id='old-selection';h.resolve(saved);await tick();
  assert.equal(h.apiCalls.filter(x=>x.name==='commerce_shipping_export').length,0);assert.equal(h.fileRequests.filter(x=>x.op==='download').length,0);
});

// Break caught: a model refresh paused during CSV validation never resumes after preview.
test('completing an unconfirmed rate preview resumes geometry comparison without old pricing',async()=>{
  let finish;const h=harness({handleApi:name=>name==='commerce_shipping_rates_preview'?new Promise(resolve=>finish=resolve):undefined});await containerForm(h);await h.runComparisonTimers();await tick();
  const intake=h.change('',undefined,{shippingFile:'rates'},[csv('new-rates.csv','new-content')]);await tick();await h.runComparisonTimers();const before=h.apiCalls.filter(x=>x.name==='commerce_shipping_compare').length;
  finish({sha256:'new-preview',rates:[]});await intake;await h.runComparisonTimers();await tick();
  const requests=h.apiCalls.filter(x=>x.name==='commerce_shipping_compare');assert.equal(requests.length,before+1);assert.equal(requests.at(-1).args.input.rate_book_id,'');
});

test('manual calculation also refuses pricing from an unconfirmed edited quote',async()=>{
  const h=harness();await containerForm(h);h.input({shippingField:'rate_book_id'},'old-book');h.input({shippingField:'rateContent'},'new tariff');h.click('calculate');assert.equal(h.created.rate_book_id,'');
});

test('cancelling a chooser resumes a comparison paused during that chooser',async()=>{
  let choose;const h=harness({pick:()=>new Promise(resolve=>choose=resolve)});await containerForm(h);h.click('pick-file',{kind:'rates'});await h.runComparisonTimers();
  assert.equal(h.apiCalls.filter(x=>x.name==='commerce_shipping_compare').length,0);choose({status:'cancelled'});await tick();await h.runComparisonTimers();await tick();assert.equal(h.apiCalls.filter(x=>x.name==='commerce_shipping_compare').length,1);
});

test('returning to a model reuses its completed immutable save after switching during export',async()=>{
  const h=harness();await containerForm(h);await h.runComparisonTimers();await tick();h.click('view-model',{model:'container-40hq'});h.click('export',{format:'json'});await tick();
  h.click('view-model',{model:'container-20gp'});const saved=plan();saved.id='saved-hq-once';h.resolve(saved);await tick();h.click('view-model',{model:'container-40hq'});h.click('export',{format:'json'});await tick();
  assert.equal(h.apiCalls.filter(x=>x.name==='commerce_shipping_plan_create').length,1);assert.equal(h.apiCalls.find(x=>x.name==='commerce_shipping_export').args.plan_id,'saved-hq-once');
});

// Break caught: the model-template button still downloads the legacy carton
// columns and cannot carry container doors or source metadata back through CSV.
test('the rendered carton/container template button requests the models template',async()=>{
  const h=harness();await h.app.open();h.clickLabel('下载箱型/柜型CSV模板');await tick();
  const requests=h.apiCalls.filter(call=>call.name==='commerce_shipping_template');assert.equal(requests.length,1);assert.equal(requests[0].args.kind,'models');
});

// Break caught: editing a form field advances its revision and discards the
// unrelated in-flight model/rate/history catalog response.
test('a delayed catalog still populates models, rates and history after a form edit without replacing that edit',async()=>{
  let complete;const h=harness({handleApi:name=>name==='commerce_shipping_state'?new Promise(resolve=>complete=resolve):undefined});
  const opening=h.app.open();h.input({shippingField:'origin'},'CN');
  complete({model_catalog:{models:[preset]},rate_books:[{id:'delayed-rates',source_ref:'延迟报价目录',rate_count:1}],plans:[{id:'delayed-plan',created_at:'2026-11-16',mode:'warehouse',input_units:3,synthetic:false}]});await opening;
  assert.match(h.html,/value="container-20gp"/);assert.match(h.html,/value="delayed-rates"/);assert.match(h.html,/data-id="delayed-plan"/);
  assert.match(h.html,/data-shipping-field="origin"[^>]*value="CN"/);
});

// Break caught: an older refresh overwrites a newer catalog in the same session.
test('a newer catalog refresh wins when the previous refresh replies last',async()=>{
  const pending=[];const h=harness({handleApi:name=>name==='commerce_shipping_state'?new Promise(resolve=>pending.push(resolve)):undefined});
  const first=h.app.open();const second=h.app.open();
  pending[1]({model_catalog:{models:[{...preset,name:'当前模型'}]},rate_books:[],plans:[]});await second;
  pending[0]({model_catalog:{models:[{...preset,name:'过期模型'}]},rate_books:[],plans:[]});await first;
  assert.match(h.html,/当前模型/);assert.doesNotMatch(h.html,/过期模型/);
});

test('closing the workbench discards a later catalog receipt without repainting',async()=>{
  let complete;const h=harness({handleApi:name=>name==='commerce_shipping_state'?new Promise(resolve=>complete=resolve):undefined});
  const opening=h.app.open();h.app.close();const paints=h.paints;
  complete({model_catalog:{models:[preset]},rate_books:[],plans:[]});await opening;assert.equal(h.paints,paints);
  h.repaint();assert.doesNotMatch(h.html,/value="container-20gp"/);
});

test('editing while a calculation is pending immediately re-enables compare and drops late result',async()=>{
  const h=harness();await h.app.open();h.click('example');h.click('calculate');
  assert.equal(h.calculate.disabled,true);
  h.input({shippingItem:'0',key:'quantity'},'13');
  assert.equal(h.calculate.disabled,false);
  h.resolve();await tick();
  assert.equal(h.calculate.disabled,false);
  assert.ok(!h.html.includes('id="shipping-scene"'));
});

test('opening history cancels the pending calculation state',async()=>{
  const h=harness();await h.app.open();h.click('example');h.click('calculate');h.click('history',{id:'saved'});await tick();
  assert.equal(h.calculate.disabled,false);
  h.resolve();await tick();assert.equal(h.calculate.disabled,false);
});

test('aggregated order summaries cannot become one invented SKU',async()=>{
  const h=harness({orders:[{id:'posting-1',sku:'A, B',product:'A × 2；B × 3',data_source:'ozon_api'}]});
  await h.app.open();h.click('orders');await tick();
  assert.ok(!h.html.includes('value="A, B"'));
  assert.match(h.html,/明细|逐行/);
});

test('imported order lines keep one order grouping rather than the line display id',async()=>{
  const h=harness({orders:[{id:'ORDER-1:A',order_id:'ORDER-1',sku:'A',quantity:2},{id:'ORDER-1:B',order_id:'ORDER-1',sku:'B',quantity:3}]});
  await h.app.open();h.click('orders');await tick();
  assert.equal((h.html.match(/value="ORDER-1"/g)||[]).length,2);
});

// Break caught: catalog choices are decorative or lose physical/model metadata.
test('adding and editing a catalog container submits its physical model with unknown packaging price intact',async()=>{
  const h=harness();await h.app.open();h.click('example');await h.change('shipping-model','container-20gp');h.click('add-model');
  h.input({shippingCarton:'3',key:'door_cm.0'},'233');h.click('calculate');
  const actual=h.created.cartons[3];assert.equal(actual.kind,'container');assert.equal(actual.model_id,'container-20gp');assert.equal(actual.packaging_cost,'');
  assert.deepEqual(Array.from(actual.door_cm),[233,229.2]);assert.equal(actual.reference.source_name,'规格示例');assert.equal(actual.reference.status,'customized_reference');
  assert.match(h.html,/箱型\/柜型|箱型与柜型/);h.resolve();await tick();assert.match(h.html,/包装费.*(?:未知|尚未提供)|(?:未知|尚未提供).*包装费/);
});

// Break caught: a fully custom container cannot reach the real plan request.
test('a custom container edits inner, outer, tare, gross and door dimensions before planning',async()=>{
  const h=harness();await h.app.open();h.click('example');await h.change('shipping-model','custom-container');h.click('add-model');
  for(const [key,value]of Object.entries({'inner_cm.0':'100','inner_cm.1':'80','inner_cm.2':'70','outer_cm.0':'110','outer_cm.1':'90','outer_cm.2':'80',tare_kg:'5',max_weight_kg:'100','door_cm.0':'75','door_cm.1':'60'}))h.input({shippingCarton:'3',key},value);
  h.click('calculate');assert.equal(h.created.cartons[3].kind,'container');assert.equal(h.created.cartons[3].model_id,'custom');assert.deepEqual(Array.from(h.created.cartons[3].inner_cm),[100,80,70]);assert.equal(h.created.cartons[3].tare_kg,5);assert.equal(h.created.cartons[3].max_weight_kg,100);
});

const csv=(name,content)=>{const bytes=new TextEncoder().encode(content);return {name,type:'text/csv',size:bytes.byteLength,arrayBuffer:async()=>bytes.buffer};};

// Break caught: the visible picker still relies on an opaque child-frame input,
// defers the trusted picker request, or leaves a selected rate unpreviewed.
test('the visible rate picker immediately requests the host chooser and automatically previews its selected CSV',async()=>{
  const h=harness({pick:async()=>({status:'selected',filename:'host-rates.csv',bytes:12,content:'host-content'})});await h.app.open();
  h.clickLabel('选择报价 CSV');assert.equal(h.fileRequests.length,1);assert.equal(h.fileRequests[0].op,'pick-csv');assert.equal(h.fileRequests[0].args.kind,'rates');
  await tick();const preview=h.apiCalls.find(call=>call.name==='commerce_shipping_rates_preview');assert.equal(preview.args.content,'host-content');assert.equal(preview.args.source_ref,'host-rates.csv');assert.match(h.html,/host-rates\.csv/);assert.equal(h.node('.shipping-rates').open,true);
  assert.equal(h.apiCalls.filter(call=>call.name==='commerce_shipping_rates_import').length,0);
});

// Break caught: cancelling the native chooser clears the user's form, previously
// loaded filename, or the confirmation for an already valid preview.
test('cancelling a host file choice preserves the existing file, form and rate confirmation',async()=>{
  const h=harness();await h.app.open();await h.change('',undefined,{shippingFile:'rates'},[csv('kept.csv','kept-content')]);h.input({shippingField:'origin'},'KEEP');h.repaint();
  h.clickLabel('选择报价 CSV');await tick();assert.match(h.html,/已取消选择/);assert.match(h.html,/kept\.csv/);assert.match(h.html,/data-shipping-field="origin"[^>]*value="KEEP"/);
  h.click('import-rates');await tick();assert.equal(h.apiCalls.find(call=>call.name==='commerce_shipping_rates_import').args.expected_sha256,'kept-content-hash');
});

// Break caught: a chooser reply can replace rows/preview after the user edits
// the form, closes the workbench or navigates to another module.
for(const departure of ['edit','close','tab'])test(`a stale host chooser receipt after ${departure} cannot replace current input`,async()=>{
  let selected;const h=harness({pick:()=>new Promise(resolve=>selected=resolve)});await h.app.open();h.clickLabel('选择报价 CSV');
  if(departure==='edit')h.input({shippingField:'origin'},'LATEST');else if(departure==='close')h.app.close();else{h.setActive(false);h.app.beforePaint();}
  selected({status:'selected',filename:'stale.csv',bytes:5,content:'stale'});await tick();assert.equal(h.apiCalls.filter(call=>call.name==='commerce_shipping_rates_preview').length,0);
  if(departure==='edit'){assert.match(h.html,/data-shipping-field="origin"[^>]*value="LATEST"/);assert.doesNotMatch(h.html,/stale\.csv/);assert.doesNotMatch(h.html,/正在选择 CSV/);}
});

// Break caught: returning to the workbench revives a chooser opened before the
// module was deactivated, even though no form field or revision changed.
test('a chooser receipt stays expired after leaving and returning to the active workbench',async()=>{
  let selected;const h=harness({pick:()=>new Promise(resolve=>selected=resolve)});await h.app.open();h.clickLabel('选择报价 CSV');
  h.setActive(false);h.app.beforePaint();h.setActive(true);h.repaint();selected({status:'selected',filename:'before-navigation.csv',bytes:3,content:'old'});await tick();
  assert.equal(h.apiCalls.filter(call=>call.name==='commerce_shipping_rates_preview').length,0);assert.doesNotMatch(h.html,/before-navigation\.csv/);assert.doesNotMatch(h.html,/正在选择 CSV/);
});

// Break caught: a generic upstream chooser timeout is presented as a failed
// download or a cancellation despite having no selection receipt.
test('a generic host chooser timeout reports selection unknown and asks the user to close its chooser',async()=>{
  const h=harness({pick:async()=>{throw Error('request_outcome_unknown');}});await h.app.open();h.clickLabel('选择报价 CSV');await tick();
  assert.match(h.html,/选择结果尚未确认/);assert.match(h.html,/关闭文件选择框/);assert.doesNotMatch(h.html,/保存结果尚未确认|已取消选择/);
});

// Break caught: selecting a rate file stops before preview or forgets its name after paint.
test('a selected CSV is read and previewed immediately, persists its filename, and imports only after hash-bound confirmation',async()=>{
  const h=harness();await h.app.open();await h.change('',undefined,{shippingFile:'rates'},[csv('quotation.csv','first-content')]);
  assert.equal(h.apiCalls.filter(c=>c.name==='commerce_shipping_rates_preview').length,1);assert.equal(h.apiCalls.filter(c=>c.name==='commerce_shipping_rates_import').length,0);
  assert.match(h.html,/quotation\.csv/);assert.equal(h.node('.shipping-rates').open,true,'a newly selected rate file opens its preview');h.click('add-item');assert.match(h.html,/quotation\.csv/);h.click('import-rates');await tick();
  const request=h.apiCalls.find(c=>c.name==='commerce_shipping_rates_import').args;assert.equal(request.content,'first-content');assert.equal(request.source_ref,'quotation.csv');assert.equal(request.expected_sha256,'first-content-hash');
});

// Break caught: a slow first file can replace a newer preview and authorize stale content.
test('a later rate selection wins over an earlier pending preview',async()=>{
  let first;const h=harness({handleApi:(name,args)=>name==='commerce_shipping_rates_preview'&&args.content==='first'?new Promise(resolve=>first=resolve):undefined});await h.app.open();
  const older=h.change('',undefined,{shippingFile:'rates'},[csv('old.csv','first')]);await tick();await h.change('',undefined,{shippingFile:'rates'},[csv('new.csv','second')]);
  first({sha256:'wrong-old-hash',rates:[]});await older;h.click('import-rates');await tick();
  const request=h.apiCalls.find(c=>c.name==='commerce_shipping_rates_import').args;assert.equal(request.content,'second');assert.equal(request.expected_sha256,'second-hash');
});

// Break caught: cancelled/failed reads still reach the preview API or erase the current rows.
test('cancelling an in-flight file read ignores its eventual content and keeps cancellation visible',async()=>{
  let complete;const h=harness({readCsv:()=>new Promise(resolve=>complete=resolve)});await h.app.open();
  const pending=h.change('',undefined,{shippingFile:'items'},[csv('items.csv','sku')]);h.click('cancel-file',{kind:'items'});complete({filename:'items.csv',content:'stale',bytes:3});await pending;
  assert.equal(h.apiCalls.filter(c=>c.name==='commerce_shipping_input_preview').length,0);assert.match(h.html,/已取消/);
});

test('failed file validation is shown next to the selected file and cannot become an import',async()=>{
  const h=harness({readCsv:async()=>{throw Error('文件必须使用 UTF-8 编码');}});await h.app.open();await h.change('',undefined,{shippingFile:'rates'},[csv('bad.csv','x')]);
  assert.match(h.html,/bad\.csv/);assert.match(h.html,/UTF-8/);assert.equal(h.apiCalls.filter(c=>c.name==='commerce_shipping_rates_preview').length,0);
});

// Break caught: editing the source after a preview reuses the old confirmation hash.
test('editing rate source invalidates the confirmation until a fresh preview succeeds',async()=>{
  const h=harness();await h.app.open();await h.change('',undefined,{shippingFile:'rates'},[csv('rates.csv','first')]);h.input({shippingField:'rateSource'},'changed');h.click('import-rates');await tick();
  assert.equal(h.apiCalls.filter(c=>c.name==='commerce_shipping_rates_import').length,0);
});

// Break caught: repeated export clicks create duplicate saves or requested is reported saved.
test('export stays pending once and distinguishes requested browser download from confirmed native save',async()=>{
  let complete;const h=harness({save:()=>new Promise(resolve=>complete=resolve)});await h.app.open();h.click('example');h.click('calculate');h.resolve();await tick();
  h.click('export',{format:'csv'});await tick();h.click('export',{format:'csv'});assert.equal(h.apiCalls.filter(c=>c.name==='commerce_shipping_export').length,1);
  complete({status:'requested',filename:'plan.csv'});await tick();assert.match(h.html,/已请求.*下载/);assert.doesNotMatch(h.html,/已保存[：:]\s*plan\.csv/);
});

for(const [status,message]of [['saved',/已保存[：:]\s*plan\.csv/],['cancelled',/已取消.*(?:保存|plan\.csv)/]])test(`native export ${status} result is reported accurately`,async()=>{
  const h=harness({save:async()=>({status,filename:'plan.csv'})});await h.app.open();h.click('example');h.click('calculate');h.resolve();await tick();h.click('export',{format:'csv'});await tick();assert.match(h.html,message);
});

test('a missing save receipt is reported as unknown rather than a successful download',async()=>{
  const h=harness({save:async()=>{throw Error('request_outcome_unknown');}});await h.app.open();h.click('example');h.click('calculate');h.resolve();await tick();h.click('export',{format:'csv'});await tick();
  assert.match(h.html,/结果.*(?:未确认|未知)|尚未确认/);assert.doesNotMatch(h.html,/已保存[：:]\s*plan\.csv/);
});

// Break caught: viewer toolbar repaints the form, or repaint/unmount retains old listeners.
test('viewer toolbar changes camera without repainting the form and restores camera after repaint',async()=>{
  const h=harness();await h.app.open();h.click('example');h.click('calculate');h.resolve();await tick();const paints=h.paints,old=h.node('#shipping-scene');
  h.click('zoom-in');assert.equal(h.paints,paints);assert.match(h.node('#shipping-camera').textContent,/120%/);h.repaint();assert.match(h.node('#shipping-camera').textContent,/120%/);
  const event=new Event('wheel',{cancelable:true});event.deltaY=-200;old.dispatchEvent(event);assert.match(h.node('#shipping-camera').textContent,/120%/);
  h.click('reset-view');assert.match(h.node('#shipping-camera').textContent,/100%/);h.app.beforePaint();h.click('close');
});

// Break caught: an export prepared after leaving or changing the plan still
// opens a save/download UI for an obsolete request.
for(const departure of ['tab','close','edit'])test(`export preparation cannot launch a save after ${departure}`,async()=>{
  let ready;const saves=[];const h=harness({handleApi:name=>name==='commerce_shipping_export'?new Promise(resolve=>ready=resolve):undefined,save:async file=>{saves.push(file);return {status:'saved',filename:file.filename};}});
  await h.app.open();h.click('example');h.click('calculate');h.resolve();await tick();h.click('export',{format:'csv'});await tick();
  if(departure==='tab'){h.setActive(false);h.app.beforePaint();}else if(departure==='close')h.app.close();else h.input({shippingItem:'0',key:'quantity'},'99');
  ready({filename:'old.csv',mime_type:'text/csv',content:'old'});await tick();assert.equal(saves.length,0);
});

test('closing while native save is pending keeps its outcome unknown after a late receipt',async()=>{
  let receipt;const h=harness({save:()=>new Promise(resolve=>receipt=resolve)});await h.app.open();h.click('example');h.click('calculate');h.resolve();await tick();h.click('export',{format:'csv'});await tick();
  h.app.close();receipt({status:'saved',filename:'plan.csv'});await tick();await h.app.open();assert.match(h.html,/结果尚未确认/);assert.doesNotMatch(h.html,/已保存[：:]\s*plan\.csv/);
});

test('an unavailable native save action gives a readable failure without retrying the export',async()=>{
  const h=harness({save:async()=>{throw Error('shipping_native_download_unavailable');}});await h.app.open();h.click('example');h.click('calculate');h.resolve();await tick();h.click('export',{format:'csv'});await tick();
  assert.match(h.html,/无法打开原生保存窗口/);assert.equal(h.apiCalls.filter(c=>c.name==='commerce_shipping_export').length,1);
});

test('imported model CSV rows retain physical values and provenance in the next plan',async()=>{
  const h=harness({handleApi:name=>name==='commerce_shipping_input_preview'?{rows:[preset],row_count:1}:undefined});await h.app.open();h.click('example');await h.change('',undefined,{shippingFile:'cartons'},[csv('models.csv','fixture-models')]);h.click('calculate');
  assert.equal(h.created.cartons.length,1);assert.equal(h.created.cartons[0].model_id,'container-20gp');assert.equal(h.created.cartons[0].reference.source_name,'规格示例');assert.equal(h.created.cartons[0].door_cm[0],234);
});

// Break caught: one-click model selection leaves focus behind on a removed button.
test('choosing a model moves keyboard focus directly to its live 3D scene',async()=>{
  const h=harness();await containerForm(h);await h.runComparisonTimers();await tick();h.click('view-model',{model:'container-40hq'});assert.equal(h.activeElement,h.node('#shipping-scene'));
});
