import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';

const root=resolve(import.meta.dirname,'../..');
const sourceRoot=process.env.UI_REMEDIATION_SOURCE_ROOT||root;
const readSource=path=>readFile(resolve(sourceRoot,path),'utf8');
const kit=await readFile(resolve(root,'ui/kit.js'),'utf8');
const [creative,media,intel]=await Promise.all([readSource('creative_ui.js'),readSource('web/media-workflow-ui.js'),readSource('web/intel-ui.js')]);
function surface(){
 const listeners={};
 const document={body:{},activeElement:null,documentElement:{clientWidth:390,dataset:{},getAttribute(){return 'light'},setAttribute(){}},querySelector(){return null},getElementById(){return null},addEventListener(name,fn){(listeners[name]||=[]).push(fn)},removeEventListener(){}};
 const window={dispatchEvent(){},addEventListener(){},matchMedia:()=>({matches:false,addEventListener(){}})};
 const context=vm.createContext({window,document,location:{hash:''},crypto:globalThis.crypto,structuredClone,queueMicrotask,setTimeout,clearTimeout,setInterval(){},requestAnimationFrame(){},URL,Blob,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options?.detail}}});
 vm.runInContext(kit,context);
 const change=async(dataset,value,id='')=>{for(const fn of listeners.change||[])await fn({target:{dataset,value,id,closest(){return {}}}})};
 const click=async(dataset)=>{const button={dataset,disabled:false,closest(){return button}};for(const fn of listeners.click||[])await fn({target:{closest(){return button}},preventDefault(){},stopImmediatePropagation(){}})};
 return {window,document,context,listeners,change,click};
}
const project=()=>({id:'project-a',revision:'1',brief:{product:{name:'合成商品',verified_facts:[]},reference:{},target:{}},assets:[{id:'product-image',kind:'product_image',display_name:'产品图',origin:'imported'},{id:'reference-video',kind:'reference_video',display_name:'参考片',origin:'imported'}],jobs:[],plan:{}});
async function studio(){
 const f=surface(),p=project(),calls=[];let config;
 f.window.CommerceCatalog=()=>({view:()=>'',enter:async()=>{}});
 f.window.CommerceMediaFlow=args=>{config=args;return {view:()=>'<div>统一制作</div>',refresh:async()=>{}}};
 vm.runInContext(creative,f.context);
 const api=async(name,args)=>{calls.push({name,args});if(name==='commerce_creative_list')return {projects:[{id:p.id,name:p.brief.product.name}]};if(['commerce_creative_get','commerce_creative_create'].includes(name))return p;if(name==='commerce_creative_render'||name==='commerce_creative_job_get')return {id:'job-a',status:'completed',input:{kind:'render',revision:'1'},result:{}};return {}};
 const view=f.window.CommerceCreative({api,esc:f.window.CommerceUI.escape,toast(){},repaint(){},isActive:()=>true});
 return {...f,view,calls,config:()=>config};
}
test('new project offers the form submit and clears an existing project without creating another record',async()=>{
 const f=await studio();await f.view.enter();
 assert.doesNotMatch(f.view.view(),/data-creative-action="new"/);
 assert.match(f.view.view(),/创建创意项目/);
 await f.view.openProject('project-a');
 assert.match(f.view.view(),/data-creative-action="new"/);
 await f.click({creativeAction:'new'});
 assert.doesNotMatch(f.view.view(),/data-creative-action="new"/);
 assert.equal(f.calls.filter(x=>x.name==='commerce_creative_create').length,0);
 for(const fn of f.listeners.input)fn({target:{dataset:{creativeField:'name'},value:'新项目'}});
 await f.click({creativeAction:'save'});
 assert.equal(f.calls.filter(x=>x.name==='commerce_creative_create').length,1);
});
test('one creative production stage retains the explicit quick template path and its own asset selection',async()=>{
 const f=await studio();await f.view.openProject('project-a');
 assert.doesNotMatch(f.view.view(),/data-creative-tab="outputs"/);
 assert.match(f.view.view(),/data-creative-tab="workflow"/);
 assert.equal(typeof f.config().localDraftView,'function');
 await f.change({},'reference-video','creative-asset');
 await f.change({},'product-image','creative-template-asset');
 await f.click({creativeAction:'render'});
 assert.equal(f.calls.find(x=>x.name==='commerce_creative_render').args.asset_id,'product-image');
 assert.match(f.config().localDraftView(),/快速模板草稿/);
});
async function production(){
 const f=surface(),p=project(),plans=[];
 f.window.CommerceMediaProvidersFlow=()=>({view:()=>'<section id="generation-services">生成服务</section>',selectPluginPlan:id=>plans.push(id)});
 vm.runInContext(media,f.context);
 const request={id:'request-a',created_at:1,request_sha256:'request-hash',status:'awaiting_media',spec:{format:'product_main',objective:'主图',prompt:'图像制作',shots:[]},assets:[]};
 const api=async()=>({requests:[request],policy:{interval_days:7,enabled:false},direction_current:true,performance:[],reviews:[]});
 const flow=f.window.CommerceMediaFlow({api,repaint(){},getProject:()=>p,localDraftView:()=>'<div id="quick-templates">模板草稿</div>'});
 await flow.openRequest('request-a');return {...f,flow,plans};
}
test('production selects local or generation service while retaining the same request and import review path',async()=>{
 const f=await production();
 assert.match(f.flow.view(),/id="media-production-method"/);
 assert.match(f.flow.view(),/id="quick-templates"/);
 assert.doesNotMatch(f.flow.view(),/id="generation-services"/);
 await f.change({mediaField:'method'},'service');
 const view=f.flow.view();assert.match(view,/id="generation-services"/);assert.doesNotMatch(view,/id="quick-templates"/);
 assert.doesNotMatch(view,/data-media-action="execute"/);
 assert.match(view,/绑定文件，进入待审阅/);assert.match(view,/value="request-a"/);
 await f.change({mediaField:'method'},'local');assert.match(f.flow.view(),/data-media-action="execute"/);
});
test('opening a plugin plan opens its service path and preserves the plan identity',async()=>{
 const f=await production();await f.flow.openRequest('request-a','plan-a');
 assert.match(f.flow.view(),/id="generation-services"/);assert.equal(f.plans.at(-1),'plan-a');
});
test('performance empty state explains the missing local records',async()=>{
 const f=await production();await f.click({mediaAction:'tab',tab:'performance'});
 assert.match(f.flow.view(),/尚未登记效果数据/);assert.doesNotMatch(f.flow.view(),/未授权店铺/);
});
function intelligence(){
 const f=surface();
 f.window.CommerceIntelDashboard=()=>({preferences:()=>({time:'all',language:'zh',layers:['flights']}),controls:()=>'<div id="all-map-controls">2D / 3D / 图层</div>',references:()=>[],panels:()=>[],panelButtons:()=>'',title:row=>row.title,caption:()=>''});
 f.window.CommerceIntelLive=()=>({panel:()=>'<section id="monitor-table">监测表</section>',ribbon:()=>'<div id="market-ribbon">行情摘要</div>',source:()=>null,mapMarkers:()=>'',points:()=>[],hasSelection:()=>false});
 f.window.CommerceSocial=()=>({view:()=>''});
 vm.runInContext(intel,f.context);
 const view=f.window.CommerceIntel({api:async()=>({}),esc:f.window.CommerceUI.escape,toast(){},repaint(){},isActive:()=>true});return {...f,view};
}
test('intelligence defaults to its monitoring table with market summary and display controls collapsed',()=>{
 const f=intelligence(),html=f.view.view();
 assert.match(html,/id="monitor-table"/);
 assert.match(html,/<details class="intel-market-summary"[^>]*><summary>行情摘要<\/summary><div id="market-ribbon"/);
 assert.match(html,/<details id="intel-display-settings"[^>]*><summary>地图与显示设置/);
 assert.doesNotMatch(html,/<details id="intel-display-settings"[^>]*\bopen\b/);
 assert.match(html,/id="all-map-controls"/);
 assert.doesNotMatch(html,/<details id="intel-aux-menu"[^>]*\bopen\b/);
});
test('display settings and low frequency tools retain the chosen disclosure state after repaint',()=>{
 const f=intelligence();for(const fn of f.listeners.toggle)fn({target:{id:'intel-display-settings',open:true}});
 assert.match(f.view.view(),/<details id="intel-display-settings"[^>]*\bopen\b/);
 for(const fn of f.listeners.toggle)fn({target:{id:'intel-aux-menu',open:true}});
 assert.match(f.view.view(),/<details id="intel-aux-menu"[^>]*\bopen\b/);
});

test('closing display settings closes hidden pickers so they cannot block observation refresh',()=>{
 const f=intelligence(),picker={open:true};
 for(const fn of f.listeners.toggle)fn({target:{id:'intel-display-settings',open:false,querySelectorAll:()=>[picker]}});
 assert.equal(picker.open,false);
});
