import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';
const source=fs.readFileSync(new URL('../../web/sourcing-ui.js',import.meta.url),'utf8');
function fixture(override=()=>{},onDraft=()=>true){
 const calls=[],dirty=[],window={CommerceUI:{escape:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),button:({label,attrs})=>`<button ${Object.entries(attrs).map(([k,v])=>`${k}="${v}"`).join(' ')}>${label}</button>`,field:(l,c)=>l+c,input:p=>`<input value="${p.value}">`,select:()=>'<select></select>',table:(_h,rs)=>rs.join('')}};
 vm.runInNewContext(source,{window,crypto:{randomUUID}});
 const c=window.CommerceSourcing({repaint(){},onDirty:x=>dirty.push(x),onDraft,api:async(tool,args)=>{calls.push({tool,args:structuredClone(args)});const r=await override(tool,args);if(r!==undefined)return r;if(tool.endsWith('_channels'))return {items:[{id:'yiwugo',label:'义乌购',kind:'批发',search_supported:true,public_preview_supported:true,source_count:0}]};return {items:[]};}});
 return {c,calls,dirty,input:(key,value)=>c.input({dataset:{peSourcing:key},value})};
}
test('late channel response never replaces another case',async()=>{
 let release;const f=fixture((t,a)=>t.endsWith('_channels')&&a.case_id==='a'?new Promise(r=>release=r):undefined);
 const p=f.c.enter('a');await f.c.enter('b');release({items:[{id:'bad',label:'旧商品渠道'}]});await p;assert.doesNotMatch(f.c.view(),/旧商品渠道/);
});
test('unknown preview keeps inputs and idempotency key, then allows receipt reconciliation',async()=>{
 const f=fixture(t=>{if(t.endsWith('_preview'))throw Error('unknown');});await f.c.enter('a');f.input('url','https://en.yiwugo.com/product/detail/1.html');
 await f.c.action('preview-public');assert.equal(f.c.hasUnsavedChanges(),true);assert.match(f.c.view(),/输入已保留/);
 await f.c.action('preview-public');const ps=f.calls.filter(x=>x.tool.endsWith('_preview'));assert.equal(ps[0].args.idempotency_key,ps[1].args.idempotency_key);
});
test('taking a preview requires parent acceptance and does not call a source-save API',async()=>{
 let accepts=false;const f=fixture(t=>t.endsWith('_preview')?{status:'preview_ready',reason:'',draft:{label:'待核款'},product:{title:'待核款',images:[],offers:[]}}:undefined,()=>accepts);
 await f.c.enter('a');f.input('url','https://en.yiwugo.com/product/detail/1.html');await f.c.action('preview-public');await f.c.action('take');assert.equal(f.c.hasUnsavedChanges(),true);
 accepts=true;await f.c.action('take');assert.equal(f.c.hasUnsavedChanges(),false);assert.equal(f.calls.some(x=>x.tool.endsWith('_source_save')),false);
});
test('dirty import cannot silently change channel and malicious source text is escaped',async()=>{
 const f=fixture(t=>t.endsWith('_preview')?{status:'preview_ready',reason:'<script>bad</script>',draft:{label:'x'},product:{title:'<img onerror=bad>',images:[],offers:[]}}:undefined);
 await f.c.enter('a');f.input('url','https://en.yiwugo.com/product/detail/1.html');f.input('platform','jd');assert.match(f.c.view(),/先带入保存或清空/);
 await f.c.action('preview-public');assert.match(f.c.view(),/&lt;script/);assert.doesNotMatch(f.c.view(),/<img onerror/);
});
test('same-case refresh during preview does not strand mutation controls',async()=>{
 let release;const f=fixture(t=>t.endsWith('_preview')?new Promise(r=>release=r):undefined);
 await f.c.enter('a');f.input('url','https://en.yiwugo.com/product/detail/1.html');
 const p=f.c.action('preview-public');assert.equal(f.c.hasActiveMutation(),true);
 await f.c.enter('a',{force:true});release({status:'needs_export',reason:'待补'});await p;
 assert.equal(f.c.hasActiveMutation(),false);await f.c.action('discard');assert.equal(f.c.hasUnsavedChanges(),false);
});
test('persisted search receipt can restore its original leads after reopening',async()=>{
 const f=fixture(t=>t.endsWith('_history')?{items:[{id:'receipt-a',platform:'yiwugo',status:'leads',query:'收纳架',items:[{title:'原线索',url:'https://en.yiwugo.com/product/detail/7.html',snippet:'待核'}]}]}:undefined);
 await f.c.enter('a');assert.match(f.c.view(),/查看这次获取结果/);
 await f.c.action('restore',{dataset:{receipt:'receipt-a'}});assert.match(f.c.view(),/原线索/);assert.match(f.c.view(),/detail\/7.html/);
 assert.equal(f.calls.some(x=>x.tool.endsWith('_search')),false);
});
