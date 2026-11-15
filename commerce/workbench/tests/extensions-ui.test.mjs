import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const kit=await readFile(new URL('../../ui/kit.js',import.meta.url),'utf8');
const source=await readFile(new URL('../../web/extensions-ui.js',import.meta.url),'utf8');
function surface(api){
 const listeners={},window={matchMedia:()=>({matches:false,addEventListener(){}}),dispatchEvent(){}};
 const document={documentElement:{dataset:{}},addEventListener:(type,fn)=>{(listeners[type]||=[]).push(fn)},querySelector(){return null}};
 const context=vm.createContext({window,document,crypto:globalThis.crypto,queueMicrotask,setTimeout,clearTimeout,URL,Blob,CustomEvent:class{}});
 vm.runInContext(kit,context);vm.runInContext(source,context);
 const app=window.CommerceExtensions({api,repaint(){},isActive:()=>true});
 return {app,listeners,async action(name,data={}){const b={dataset:{extensionAction:name,...data},disabled:false,closest(){return {}}};for(const fn of listeners.click||[])await fn({target:{closest:()=>b},preventDefault(){},stopImmediatePropagation(){}})},input(key,value){for(const fn of listeners.input||[])fn({target:{dataset:{extensionField:key},value,closest(){return {}}}})}};
}
test('self-service catalogue exposes all capability kinds and escapes user definitions',async()=>{
 const {app}=surface(async name=>name==='commerce_extension_capabilities'?{templates:[],safe_builtins:['commerce_runtime_status'],default_limits:{max_seconds:300,max_model_calls:8,max_steps:32}}:name==='commerce_extension_list'?{items:[{id:'ext_a',kind:'skill',name:'<script>bad</script>',version:1,enabled:false,test_status:'not_tested',definition:{kind:'skill',name:'<script>bad</script>',spec:{steps:[]}}}]}:name==='commerce_model_list'?{models:[]}:{runs:[],schedules:[]});
 await app.enter();const html=app.view();assert.match(html,/我的技能/);assert.match(html,/插件/);assert.match(html,/Agent/);assert.match(html,/工作流/);assert.match(html,/自动计划/);assert.match(html,/运行记录/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>bad/);
});
test('unavailable registry shows retry without claiming an empty successful catalogue',async()=>{
 const {app}=surface(async()=>{throw Error('offline')});await app.enter();assert.match(app.view(),/暂不可读|未完成|重新读取/);assert.doesNotMatch(app.view(),/已创建|已启用/);
});
test('a late catalogue read cannot replace a newer requested view',async()=>{
 let resolveOld,count=0;const first=new Promise(resolve=>{resolveOld=resolve});
 const {app}=surface(async name=>name==='commerce_extension_list'?(++count===1?first:{items:[{id:'new',kind:'skill',name:'NEW_VERSION',version:1,definition:{kind:'skill',name:'NEW_VERSION',spec:{steps:[]}}}]}):name==='commerce_extension_capabilities'?{templates:[],safe_builtins:[],default_limits:{}}:name==='commerce_model_list'?{models:[]}:{runs:[],schedules:[]});
 const old=app.enter();await Promise.resolve();await app.enter();resolveOld({items:[{id:'old',kind:'skill',name:'OLD_VERSION',version:1,definition:{kind:'skill',name:'OLD_VERSION',spec:{steps:[]}}}]});await old;assert.match(app.view(),/NEW_VERSION/);assert.doesNotMatch(app.view(),/OLD_VERSION/);
});

test('editor uses host builtin names and cannot carry pending schema into another definition',async()=>{
 const a={id:'ext_a',kind:'skill',name:'First',version:1,definition:{id:'ext_a',kind:'skill',name:'First',spec:{steps:[]}}};
 const b={id:'ext_b',kind:'skill',name:'Second',version:1,definition:{id:'ext_b',kind:'skill',name:'Second',spec:{steps:[]}}};let saved;
 const api=async(name,args)=>name==='commerce_extension_capabilities'?{templates:[],safe_builtins:[{name:'commerce_runtime_status',effect:'read'}]}:name==='commerce_model_list'?{models:[]}:name==='commerce_extension_list'?{items:[a,b]}:name==='commerce_extension_get'?(args.extension_id==='ext_a'?a:b):name==='commerce_extension_save'?(saved=structuredClone(args.definition),{...b,definition:saved,version:2}):{runs:[],schedules:[]};
 const x=surface(api);await x.app.enter();await x.action('edit',{id:'ext_a'});x.input('output_schema','{"type":"object","required":["wrong"]}');x.input('output','{"wrong":true}');await x.action('edit',{id:'ext_b'});await x.action('step-add');assert.match(x.app.view(),/builtin:commerce_runtime_status/);assert.doesNotMatch(x.app.view(),/\[object Object\]/);await x.action('save');assert.equal(saved.name,'Second');assert.equal(saved.output_schema,undefined);assert.equal(saved.spec.output,undefined);
});
test('changing the selected definition clears the previous run result',async()=>{
 const a={id:'ext_a',kind:'skill',name:'First',version:1,enabled:true,definition:{kind:'skill',name:'First',spec:{steps:[]}}};
 const api=async(name)=>name==='commerce_extension_capabilities'?{templates:[],safe_builtins:[]}:name==='commerce_extension_list'?{items:[a]}:name==='commerce_model_list'?{models:[]}:name==='commerce_extension_get'?a:name==='commerce_extension_run'?{id:'run_1',status:'succeeded',output:{old_result:true}}:name==='commerce_extension_run_get'?{id:'run_1',status:'succeeded',output:{old_result:true}}:{runs:[],schedules:[]};
 const x=surface(api);await x.app.enter();await x.action('prepare',{id:a.id});await x.action('run');await Promise.resolve();assert.match(x.app.view(),/old_result/);await x.action('new');assert.doesNotMatch(x.app.view(),/old_result/);
});
