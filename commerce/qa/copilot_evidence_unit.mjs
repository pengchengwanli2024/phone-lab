import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const window={};
vm.runInNewContext(await readFile(new URL('../web/copilot-evidence.js',import.meta.url),'utf8'),{window,URL,Date,Map,Set,JSON});
const helper=window.CommerceAssistantEvidence;
const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');

test('public evidence shows useful title, link and publication limits',()=>{
 const html=helper.render({id:'R1',tool:'commerce_web_search',data:{retrieved_at:1794790800,groups:[{label:'东南亚',status:'ready',items:[{title:'Public headline',url:'https://example.com/news',summary:'Public source statement',publication_status:'unconfirmed',content_status:'search_summary_only'}]}]}},esc);
 assert.match(html,/Public headline/);assert.match(html,/href="https:\/\/example.com\/news"/);
 assert.match(html,/发布时间待核对/);assert.match(html,/搜索摘要/);assert.doesNotMatch(html,/commerce_web_search/);
});
test('public JSON evidence identifies its format and bounded excerpt',()=>{
 const html=helper.render({id:'R1',tool:'commerce_web_read',data:{items:[{url:'https://example.com/data',title:'Official data',status:'ready',content_status:'json_data',text_truncated:true,text:'{"value":2}'}]}},esc);
 assert.match(html,/公开数据已读取/);assert.match(html,/内容已限量/);assert.match(html,/发布时间待核对/);
});
test('partial regional retrieval keeps results and names the failed region',()=>{
 const html=helper.render({id:'R1',tool:'commerce_web_search',data:{groups:[{label:'俄罗斯',status:'failed',error:'web_provider_timeout',items:[]},{label:'中东',status:'ready',items:[{title:'Kept',url:'https://example.com/a'}]}]}},esc);
 assert.match(html,/俄罗斯/);assert.match(html,/超时/);assert.match(html,/Kept/);
});
test('empty local retrieval is one meaningful line rather than an empty source card',()=>{
 const html=helper.render({id:'R2',tool:'commerce_intel_search',data:{total:0,items:[]}},esc);
 assert.match(html,/本机资料.*0.*匹配/);assert.doesNotMatch(html,/ui-evidence|blockquote|commerce_intel_search/);
});
test('identical tool observations share a group while retaining both reference IDs',()=>{
 const groups=helper.group([{id:'R1',tool:'commerce_intel_search',sha256:'abc',data:{total:0}},{id:'R2',tool:'commerce_intel_search',sha256:'abc',data:{total:0}},{id:'R3',tool:'commerce_web_search',sha256:'def',data:{}}]);
 assert.equal(groups.length,2);assert.deepEqual(Array.from(groups[0].references),['R1','R2']);
});
test('source content is escaped and executable or private links never become anchors',()=>{
 const html=helper.render({id:'R1',tool:'commerce_web_read',data:{items:[{title:'<img src=x onerror=evil()>',url:'javascript:evil()',text:'<script>evil()</script>',status:'ready'},{title:'Private',url:'http://127.0.0.1/a',status:'ready'}]}},esc);
 assert.doesNotMatch(html,/<script|<img|href="(?:javascript|http:\/\/127)/);assert.match(html,/&lt;img/);
});
test('running retrieval exposes its actual phase',()=>{
 assert.match(helper.progress({trace:[{event:'tool_started',tool:'commerce_web_search'}]}),/检索公开/);
 assert.match(helper.progress({trace:[{event:'tool_started',tool:'commerce_web_read'}]}),/读取.*原文/);
 assert.match(helper.progress({trace:[{event:'tool_started',tool:'commerce_web_read'},{event:'read_tool',tool:'commerce_web_read'}]}),/整理/);
});
test('a saved analysis displays actual content and original source links',()=>{
 const html=helper.archive({analysis:'保存的中文分析',source_links:[{title:'Original source',url:'https://example.com/a'}]},esc);
 assert.match(html,/保存的中文分析/);assert.match(html,/Original source/);assert.match(html,/href="https:\/\/example.com\/a"/);
});
test('Chinese analysis formats emphasis and bullets while keeping HTML inert',()=>{
 const html=helper.prose('**地区观察**\n- 来源陈述\n- <img src=x onerror=evil()>',esc);
 assert.match(html,/<strong>地区观察<\/strong>/);assert.match(html,/<ul><li>来源陈述<\/li>/);
 assert.doesNotMatch(html,/<img|onerror="/);assert.match(html,/&lt;img/);
});
