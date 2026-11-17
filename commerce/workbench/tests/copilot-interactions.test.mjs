import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

let source='';
try { source=await readFile(new URL('../../web/copilot-interactions.js',import.meta.url),'utf8'); }
catch(error) { if(error.code!=='ENOENT')throw error; }
const forbidden=()=>{throw Error('reading helpers must not perform effects')};
const window={};
vm.runInNewContext(source,{window,URL,fetch:forbidden,document:new Proxy({},{get:forbidden}),localStorage:new Proxy({},{get:forbidden}),setTimeout:forbidden,addEventListener:forbidden});
const helper=window.CommerceCopilotInteractions;
const ready=()=>assert.ok(helper,'independent reading helpers are missing');
const plain=value=>JSON.parse(JSON.stringify(value));

test('renders readable headings paragraphs flat lists and inline emphasis',()=>{
  ready();
  const html=helper.markdown('# 结论\n\n第一行\n第二行 **重点** 与 *提示*。\n\n- 核对来源\n- 保留未知\n\n3. 第三步\n4. 第四步');
  assert.match(html,/<h1>结论<\/h1>/);
  assert.match(html,/<p>第一行<br>第二行 <strong>重点<\/strong> 与 <em>提示<\/em>。<\/p>/);
  assert.match(html,/<ul><li>核对来源<\/li><li>保留未知<\/li><\/ul>/);
  assert.match(html,/<ol start="3"><li>第三步<\/li><li>第四步<\/li><\/ol>/);
});

test('raw HTML and all code are escaped instead of becoming active markup',()=>{
  ready();
  const html=helper.markdown('<script>alert(1)</script>\n\n`<img src=x onerror=alert(2)>`\n\n```html\n<a href="javascript:alert(3)">**literal**</a>\n```');
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img'));
  assert.match(html,/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html,/<code>&lt;img src=x onerror=alert\(2\)&gt;<\/code>/);
  assert.match(html,/<pre><code class="language-html">&lt;a href=&quot;javascript:alert\(3\)&quot;&gt;\*\*literal\*\*&lt;\/a&gt;<\/code><\/pre>/);
});

test('inline code and unmatched or multiline fences preserve literal contents',()=>{
  ready();
  assert.match(helper.markdown('``a ` b`` and **bold**'),/<code>a ` b<\/code> and <strong>bold<\/strong>/);
  assert.equal(helper.markdown('```js\nconst x = "<tag>";\n**literal**'),'<pre><code class="language-js">const x = &quot;&lt;tag&gt;&quot;;\n**literal**</code></pre>');
  assert.match(helper.markdown('~~~\n[x](https://example.test)\n~~~'),/<pre><code>\[x\]\(https:\/\/example\.test\)<\/code><\/pre>/);
  assert.match(helper.markdown('unmatched ` <b>'),/unmatched ` &lt;b&gt;/);
});

test('only explicit http and https links become escaped external anchors',()=>{
  ready();
  const html=helper.markdown('[**来源**](https://example.test/a?q=1&b=2) [普通](http://example.test/)');
  assert.match(html,/<a href="https:\/\/example\.test\/a\?q=1&amp;b=2" target="_blank" rel="noopener noreferrer"><strong>来源<\/strong><\/a>/);
  assert.match(html,/href="http:\/\/example\.test\/"/);
  for(const url of ['javascript:alert(1)','JaVaScRiPt:alert(1)','data:text/html,<script>x</script>','file:///tmp/private','//example.test/','https:\\evil.test','java\nscript:alert(1)','https://example.test/\nmalicious','https://user:pass@example.test/']) {
    assert.ok(!helper.markdown(`[unsafe](${url})`).includes('<a '),url);
  }
  const attribute=helper.markdown('[x](https://example.test/&quot;onclick=&quot;evil)');
  assert.ok(!attribute.includes(' onclick='));
  assert.match(attribute,/&amp;quot;/);
});

test('images become optional safe links and never load remote media',()=>{
  ready();
  const html=helper.markdown('![示意图](https://example.test/private.png) ![unsafe](data:image/svg+xml,evil)');
  assert.ok(!html.includes('<img'));
  assert.match(html,/href="https:\/\/example\.test\/private.png"[^>]*>图片：示意图<\/a>/);
  assert.equal((html.match(/<a /g)||[]).length,1);
});

test('tables preserve escaped and code literal pipes and apply fixed alignments',()=>{
  ready();
  const html=helper.markdown('| 名称 | 数值 |\n| :--- | ---: |\n| A\\|B | `x|y` |\n| **重点** | <img src=x> |');
  assert.match(html,/<div class="copilot-markdown-table"><table>/);
  assert.match(html,/<th style="text-align:left">名称<\/th><th style="text-align:right">数值<\/th>/);
  assert.match(html,/<td style="text-align:left">A\|B<\/td><td style="text-align:right"><code>x\|y<\/code><\/td>/);
  assert.match(html,/<strong>重点<\/strong>/);
  assert.match(html,/&lt;img src=x&gt;/);
  assert.ok(!html.includes('<img'));
  assert.ok(!helper.markdown('plain | text\n--- invalid | value').includes('<table>'));
});

test('tables stop at unrelated blocks and malformed row lengths remain visible',()=>{
  ready();
  const html=helper.markdown('a | b\n--- | ---\nx | y\n\n## Next\n\nnot | a | matching row');
  assert.match(html,/<\/tbody><\/table><\/div><h2>Next<\/h2>/);
  assert.match(html,/<p>not \| a \| matching row<\/p>/);
});

test('rendering bounds very large untrusted output and marks truncation honestly',()=>{
  ready();
  const html=helper.markdown('x'.repeat(5000)+'TAIL_SENTINEL'+'<img>'.repeat(10000));
  assert.ok(!html.includes('TAIL_SENTINEL'));
  assert.ok(!html.includes('<img'));
  assert.match(html,/5000/);
  assert.ok(html.length<5200);
  assert.equal(helper.markdown(null),'');
  assert.equal(helper.markdown({toString:forbidden}), '');
});

test('copy text remains the actual source, including Markdown and line endings',()=>{
  ready();
  const text='## 原始回答\r\n\n**重点** [来源](https://example.test) <literal>';
  assert.equal(helper.plainText(text),text);
  assert.equal(helper.plainText(null),'');
  assert.equal(helper.plainText({text:'not the actual source'}),'');
});

test('overview suggestions address the visible overview without assuming a foreign market',()=>{
  ready();
  const context={module:'overview',platform:'all',market:'all'};
  const original=JSON.stringify(context);
  const rows=plain(helper.suggestions(context,{page:'overview',section:'sales-trend'}));
  assert.ok(rows.length>0&&rows.length<=3);
  assert.ok(rows.every(row=>Array.isArray(row)&&row.length===2&&row.every(value=>typeof value==='string'&&value.length>0)));
  assert.match(rows.flat().join(' '),/概览|趋势|经营/);
  assert.doesNotMatch(rows.flat().join(' '),/俄罗斯|Ozon|ozon|RU|厨房/);
  assert.equal(JSON.stringify(context),original);
});

test('intelligence suggestions explain news sources and selected records',()=>{
  ready();
  const rows=plain(helper.suggestions({module:'intelligence'},{page:'intelligence',entity:{kind:'intel',id:'abc'}}));
  assert.match(rows.flat().join(' '),/情报/);
  assert.match(rows.flat().join(' '),/来源|时效/);
  assert.doesNotMatch(rows.flat().join(' '),/利润|库存|俄罗斯/);
});

test('suggestions prioritize the visible page, selected object and cost section',()=>{
  ready();
  const samples=[
    [{module:'overview'},{page:'orders',entity:{kind:'order',id:'order-one'}},/订单/],
    [{module:'products'},{page:'products',entity:{kind:'product',id:'sku-one'}},/商品|库存/],
    [{module:'organization',entity:{kind:'case',id:'case-one'}},{page:'workspace',section:'cost'},/测算|成本|参数/],
    [{module:'tasks'},{page:'tasks',entity:{kind:'task',id:'task-one'}},/进度|阻塞|恢复/],
    [{module:'creative'},{page:'creative'},/创意|制作|主张/],
    [{module:'organization'},{page:'listing',entity:{kind:'case',id:'case-one'}},/上架|内容/],
  ];
  for(const [scope,page,words] of samples){
    const rows=plain(helper.suggestions(scope,page));
    assert.ok(rows.length<=3);
    assert.match(rows.flat().join(' '),words);
  }
  assert.doesNotMatch(plain(helper.suggestions({module:'research'},{page:'overview'})).flat().join(' '),/候选|俄罗斯/);
  const moved=plain(helper.suggestions({module:'products',entity:{kind:'product',id:'old-sku'}},{page:'creative'})).flat().join(' ');
  assert.match(moved,/创意|制作/);
  assert.doesNotMatch(moved,/库存/);
});

test('suggestions return fresh data and tolerate unknown or absent page state',()=>{
  ready();
  const original=plain(helper.suggestions());
  const changed=helper.suggestions();changed[0][0]='changed';
  assert.deepEqual(plain(helper.suggestions()),original);
  assert.ok(helper.suggestions(null,null).length<=3);
});
