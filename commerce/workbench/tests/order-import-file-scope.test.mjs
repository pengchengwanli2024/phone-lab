import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {transform} from 'esbuild';
const source=(await readFile(new URL('../src/order-imports.tsx',import.meta.url),'utf8')).replace(/^import .*?;\n/gm,'').replace(/^import '.*?';\n/gm,'');
const compiled=(await transform(source,{loader:'tsx',format:'cjs',jsx:'transform',jsxFactory:'element'})).code;
const text=n=>n==null?'':Array.isArray(n)?n.map(text).join(''):typeof n==='object'?text(n.props?.children):String(n);
function nodes(n,check){if(n==null||typeof n!=='object')return [];if(Array.isArray(n))return n.flatMap(x=>nodes(x,check));return [...(check(n)?[n]:[]),...nodes(n.props?.children,check)];}
function deferredFile(name,size=10){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {file:{name,size,text:()=>promise},resolve,reject};}
const flush=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
function harness(){
 const hooks=[],effects=[],calls=[];let cursor=0,tree;const props={demo:false,navigate(){}};
 const context={module:{exports:{}},exports:{},React:{Fragment:'fragment'},element:(type,props,...children)=>({type,props:{...props,children}}),Button:'button',Panel:'section',Empty:'empty',ErrorNotice:'error',errorText:e=>e.message,requestKey:()=> 'stable-preview-key',
  useState:initial=>{const i=cursor++;if(!(i in hooks))hooks[i]=typeof initial==='function'?initial():initial;return [hooks[i],value=>{hooks[i]=typeof value==='function'?value(hooks[i]):value;}];},
  useRef:initial=>{const i=cursor++;if(!(i in hooks))hooks[i]={current:initial};return hooks[i];},
  useEffect:(fn,deps)=>{const i=cursor++,old=hooks[i];if(!old||deps.some((x,j)=>x!==old.deps[j])){old?.cleanup?.();hooks[i]={deps};effects.push(()=>{hooks[i].cleanup=fn();});}},
  api:async(name,args)=>{calls.push({name,args});if(name==='commerce_order_import_list')return {items:[]};if(name==='commerce_order_import_preview')return {id:'preview-1',filename:args.filename,status:'preview',sha256:'sha',scope:args.scope,synthetic:args.synthetic,row_count:1,valid_count:1,accepted_count:0,duplicate_count:0,quarantined_count:0,sales_by_currency:[],preview:[],quarantined:[]};throw Error(name);}
 };context.exports=context.module.exports;vm.runInNewContext(compiled,context);
 function render(){cursor=0;tree=context.module.exports.OrderImports(props);while(effects.length)effects.shift()();return tree;}
 async function settle(){for(let i=0;i<3;i++){await flush();render();}}
 async function start(){render();await settle();}
 const field=label=>{const wrapper=nodes(tree,n=>n.type==='label'&&text(n).startsWith(label))[0];assert.ok(wrapper,'field '+label);return nodes(wrapper,n=>['input','textarea','select'].includes(n.type))[0];};
 function edit(label,value){field(label).props.onChange({target:{value}});render();}
 function choose(file){const input=nodes(tree,n=>n.type==='input'&&n.props.type==='file')[0];input.props.onChange({target:{files:file?[file]:[]}});render();}
 const button=label=>{const found=nodes(tree,n=>n.type==='button'&&text(n)===label)[0];assert.ok(found,'button '+label);return found;};
 return {start,settle,render,edit,choose,field,button,calls,setMode(value){props.demo=value;render();},get tree(){return tree;}};
}
test('the latest CSV file wins when an older File.text read resolves last',async()=>{
 const h=harness();await h.start();const a=deferredFile('first.csv'),b=deferredFile('latest.csv');h.choose(a.file);h.choose(b.file);b.resolve('LATEST_B');await h.settle();assert.equal(h.field('CSV内容').props.value,'LATEST_B');a.resolve('OLD_A');await h.settle();assert.equal(h.field('CSV内容').props.value,'LATEST_B');assert.equal(h.field('文件名').props.value,'latest.csv');
});
test('manual CSV edits invalidate a pending file read without losing the manual input',async()=>{
 const h=harness();await h.start();const a=deferredFile('slow.csv');h.choose(a.file);h.edit('CSV内容','MANUAL');h.edit('文件名','manual.csv');a.resolve('OLD_FILE');await h.settle();assert.equal(h.field('CSV内容').props.value,'MANUAL');assert.equal(h.field('文件名').props.value,'manual.csv');
});
test('changing the data mode suppresses an old file success or error',async()=>{
 const h=harness();await h.start();const a=deferredFile('real.csv');h.choose(a.file);h.setMode(true);a.resolve('OLD_REAL');await h.settle();assert.equal(h.field('CSV内容').props.value,'');assert.equal(h.field('文件名').props.value,'orders.csv');
 const b=deferredFile('example.csv');h.choose(b.file);h.setMode(false);b.reject(Error('late read failure'));await h.settle();assert.doesNotMatch(text(h.tree),/无法读取文件/);
});
test('an invalid replacement file invalidates the prior read and preserves existing values',async()=>{
 const h=harness();await h.start();h.edit('CSV内容','EXISTING');h.edit('文件名','existing.csv');const a=deferredFile('slow.csv');h.choose(a.file);h.choose({name:'too-large.csv',size:512001,text(){throw Error('must not read oversize file');}});a.resolve('OLD_FILE');await h.settle();assert.equal(h.field('CSV内容').props.value,'EXISTING');assert.equal(h.field('文件名').props.value,'existing.csv');assert.match(text(h.tree),/CSV文件最多512KB/);
});
test('preview cannot import the previous CSV while the chosen file is still being read',async()=>{
 const h=harness();await h.start();h.edit('店铺引用','synthetic-store');h.edit('CSV内容','PREVIOUS');const a=deferredFile('pending.csv');h.choose(a.file);const preview=nodes(h.tree,n=>n.type==='button'&&/预览导入|正在读取CSV/.test(text(n)))[0];assert.equal(preview.props.disabled,true);await preview.props.onClick();assert.equal(h.calls.filter(c=>c.name==='commerce_order_import_preview').length,0);a.resolve('LATEST');await h.settle();const ready=h.button('预览导入');assert.equal(ready.props.disabled,false);await ready.props.onClick();await h.settle();const call=h.calls.find(c=>c.name==='commerce_order_import_preview');assert.equal(call.args.content,'LATEST');assert.equal(call.args.filename,'pending.csv');assert.equal(call.args.scope.store_ref,'synthetic-store');
});
