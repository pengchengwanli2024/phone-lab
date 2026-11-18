import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

const require=createRequire(import.meta.url);
const compiled=await build({entryPoints:['src/overview.tsx'],bundle:true,write:false,format:'cjs',platform:'node',external:['react'],loader:{'.css':'empty'}});
const module={exports:{}};
vm.runInNewContext(compiled.outputFiles[0].text,{module,exports:module.exports,require,window:{CommerceUI:{icon:()=>''}}});
const {overviewWorkQueue,Overview}=module.exports;
const plain=value=>JSON.parse(JSON.stringify(value));
const task=(id,status)=>({id,status,kind:'analysis',input:{title:'Task '+id,organization_case:'case-1'}});
const attention=(id,kind,extra={})=>({id,source:'research',source_id:'research-1',kind,title:'Evidence review',detail:'Check the current source',status:'needs_input',action:{type:'research',id:'research-1'},...extra});

test('queued and running work is visible separately from decisions waiting for a person',()=>{
 const queue=overviewWorkQueue([task('queued','queued'),task('running','running'),task('input','needs_input'),task('review','awaiting_review'),task('unknown','unknown'),task('failed','interrupted'),task('done','succeeded')],[],[]);
 assert.deepEqual(plain(queue.inProgress.map(row=>row.id)),['queued','running']);
 assert.deepEqual(plain(queue.notices.map(row=>[row.id,row.category])),[['failed','failed'],['unknown','unknown'],['review','review'],['input','input']]);
 assert.equal(queue.notices.find(row=>row.id==='input').caseId,'case-1');
 assert.equal(queue.notices.find(row=>row.id==='unknown').status,'unknown');
});

test('linked attention retains its exact resolver identity without duplicating the shared task',()=>{
 const original=attention('attention-unique','unknown',{task_id:'original-task'});
 const queue=overviewWorkQueue([task('original-task','running')],[original],[]);
 assert.equal(queue.inProgress.length,0);
 assert.equal(queue.notices.length,1);
 assert.equal(queue.notices[0].attentionId,'attention-unique');
 assert.equal(queue.notices[0].target,'');
 assert.equal(queue.notices[0].category,'unknown');
 assert.equal(queue.notices[0].detail,original.detail);
 assert.equal(queue.notices[0].actionLabel,'核对原结果');
 assert.equal(original.task_id,'original-task');
});

test('unresolved reminders preserve source context and stale status, while resolved ones leave the queue',()=>{
 const alert=(id,status,kind='order')=>({id,status,kind,title:'Order check',detail:'Original receipt required',sku:'SYN-SKU',store_id:'SYN-STORE'});
 const queue=overviewWorkQueue(undefined,[],[alert('resolved','resolved'),alert('stale','active','data_stale'),alert('suspended','suspended'),alert('unread','active')]);
 assert.deepEqual(plain(queue.notices.map(row=>[row.id,row.category])),[['stale','stale'],['suspended','stale'],['unread','input']]);
 for(const notice of queue.notices){assert.equal(notice.target,'alerts');assert.match(notice.sourceLabel,/SYN-STORE/);assert.match(notice.detail,/SYN-SKU.*Original receipt/);}
});

test('the initial home places the work queue before metrics and keeps statistics available on demand',()=>{
 const html=renderToStaticMarkup(React.createElement(Overview,{demo:false,navigate(){},onThread(){},onResearch(){}}));
 assert.ok(html.indexOf('需要处理')<html.indexOf('aria-label="经营指标"'));
 assert.ok(html.indexOf('aria-label="经营指标"')<html.indexOf('最近任务'));
 assert.match(html,/<details class="r-dashboard-analytics"><summary>/);
 assert.match(html,/经营统计与库存/);
 assert.match(html,/平台销售构成/);
 assert.match(html,/库存统计/);
 assert.doesNotMatch(html,/2025年01月21日|继续上次工作/);
});
