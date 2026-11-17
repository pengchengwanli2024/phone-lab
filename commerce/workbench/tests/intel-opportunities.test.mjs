import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const code=fs.readFileSync(new URL('../../web/intel-opportunities-ui.js',import.meta.url),'utf8');
const definition={id:'workflow',kind:'workflow',name:'Daily',definition:{spec:{steps:[{uses:{builtin:'commerce_intel_opportunity_packet'}},{uses:{builtin:'commerce_intel_opportunity_validate'}}]}}};
function fixture(run){
 const calls=[],listeners={},sources=[];let active=true;
 const escape=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
 const ui={escape,button:({label,attrs={}})=>`<button ${attrs.disabled?'disabled':''}>${escape(label)}</button>`,badge:v=>v,empty:v=>v,alert:v=>v};
 const context=vm.createContext({window:{CommerceUI:ui},crypto:{randomUUID:()=> 'test-id'},document:{addEventListener:(name,fn)=>listeners[name]=fn,removeEventListener:(name,fn)=>{if(listeners[name]===fn)delete listeners[name]}},Set,Date});
 vm.runInContext(code,context);const api=async(name,args)=>{calls.push({name,args});if(name==='commerce_extension_list')return {items:[definition,{id:'other',kind:'workflow',definition:{spec:{steps:[]}}}]};if(name==='commerce_extension_schedule_list')return {schedules:[{extension_id:'workflow',name:'Daily plan',enabled:true,interval_seconds:86400}]};return {runs:[run]};};
 const panel=context.window.CommerceIntelOpportunities({api,repaint:()=>{},isActive:()=>active,onSource:id=>sources.push(id)});return {panel,calls,sources,listeners,deactivate:()=>active=false,activate:()=>active=true};
}
function receipt(){
 const now=Date.now()/1000,hot={status:'unknown',terms:null};
 const packet={schema:'commerce-intel-opportunity-packet-v1',scope:'news_derived_opportunity_hypotheses',not_platform_hot_terms:true,
  packet_sha256:'a'.repeat(64),generated_at:new Date((now-60)*1000).toISOString(),expires_at:new Date((now+3540)*1000).toISOString(),limit:8,
  items:[{id:'1'.repeat(24),title:'Exact source',source:'wto',url:'https://example.com/source',published:now-120,collected_at:now-90,record_sha256:'b'.repeat(64),verification:'publisher_report_not_independently_verified'}],
  source_states:[{source:'wto',cache_status:'ok',last_success:now-90,fresh:true}],
  coverage:{status:'bounded_public_news_sample',selected:1,max_items:8,window_hours:24,selection:'source_balanced_latest_publications',truncated:false,archive_search:true},platform_hot_terms:hot,external_execution_allowed:false};
 const result={schema:'commerce-intel-opportunity-result-v1',scope:packet.scope,not_platform_hot_terms:true,packet_sha256:packet.packet_sha256,
  verification:'news_derived_hypotheses_needs_evidence',external_execution_allowed:false,business_actions_executed:false,summary:'<script>escaped</script>',
  platform_hot_terms:{...hot},coverage:{...packet.coverage},opportunities:[{hypothesis:'Check demand',confidence:'low',status:'needs_evidence',evidence_ids:['1'.repeat(24)],next_checks:['Check costs']}],
  evidence:JSON.parse(JSON.stringify(packet.items))};
 return {id:'extrun_one',extension_id:'workflow',created_at:now,status:'succeeded',test:false,usage:{model_calls:1},output:{packet,result},steps:[
  {id:'root.packet',status:'succeeded',source:{kind:'builtin',tool:'commerce_intel_opportunity_packet',verification:'observed_local_result'},output:JSON.parse(JSON.stringify(packet))},
  {id:'root.validate',status:'succeeded',source:{kind:'builtin',tool:'commerce_intel_opportunity_validate',verification:'observed_local_result'},output:JSON.parse(JSON.stringify(result))}]};
}
test('read-only opportunity panel shows exact validated sources, plan and escaped model text',async()=>{
 const {panel,calls}=fixture(receipt());await panel.enter();const html=panel.view();assert.match(html,/Exact source/);assert.match(html,/Check costs/);assert.match(html,/&lt;script&gt;/);assert.match(html,/24 小时间隔/);assert.match(html,/平台热搜词尚未接入/);assert.equal(calls.length,3);assert.ok(calls.every(x=>/_list$/.test(x.name)));assert.deepEqual(JSON.parse(JSON.stringify(calls[2].args)),{extension_id:'workflow'});
});
test('failed, synthetic test and mixed packet receipts cannot appear as completed opportunity conclusions',async()=>{
 for(const mutate of [r=>r.status='unknown',r=>r.test=true,r=>r.output.result.packet_sha256='wrong',r=>r.output.result.opportunities[0].evidence_ids=['other'],r=>r.output.result.external_execution_allowed=true]){const run=receipt();mutate(run);const {panel}=fixture(run);await panel.enter();assert.ok(!panel.view().includes('Exact source'));}
});
test('hiding invalidates a pending response and performs no model or scheduling action',async()=>{
 const {panel,calls}=fixture(receipt());const pending=panel.enter();panel.hide();await pending;assert.ok(!panel.view().includes('Exact source'));assert.equal(calls.length,1);panel.dispose();
});
test('same hash cannot pair unrelated evidence or an unobserved validator output',async()=>{
 for(const mutate of [r=>r.output.result.evidence[0].record_sha256='c'.repeat(64),r=>r.output.result.evidence[0].title='Wrong source title',r=>r.steps=[],r=>r.steps[1].source.kind='model',r=>r.steps[1].output.summary='Other conclusion',r=>r.output.result.evidence=[null],r=>r.output.result.opportunities=[null]]){
  const run=receipt();mutate(run);const {panel}=fixture(run);await panel.enter();assert.doesNotThrow(()=>panel.view());assert.ok(!panel.view().includes('Check demand'));
 }
});
test('a daily historical observation remains readable with expiry and current-source caveats',async()=>{
 const run=receipt(),now=Date.now()/1000;run.output.packet.generated_at=new Date((now-90000)*1000).toISOString();run.output.packet.expires_at=new Date((now-86400)*1000).toISOString();run.steps[0].output=JSON.parse(JSON.stringify(run.output.packet));
 const {panel}=fixture(run);await panel.enter();const html=panel.view();assert.match(html,/Check demand/);assert.match(html,/历史观察/);assert.match(html,/过期|陈旧/);assert.match(html,/未重验当前来源/);
});
test('successful no-input conditions explain absence without a model conclusion',async()=>{
 const run=receipt();run.output.packet.items=[];run.output.packet.coverage={...run.output.packet.coverage,status:'needs_fresh_sources',selected:0};run.output.result={status:'skipped',reason:'condition_false'};run.usage.model_calls=0;
 run.steps[0].output=JSON.parse(JSON.stringify(run.output.packet));run.steps[1]={id:'root.validate',status:'succeeded',source:{kind:'condition'},output:{...run.output.result}};
 const {panel}=fixture(run);await panel.enter();assert.match(panel.view(),/无新鲜输入/);assert.match(panel.view(),/未调用模型/);assert.ok(!panel.view().includes('Check demand'));
});
test('module deactivation releases busy state without accepting a late result',async()=>{
 const f=fixture(receipt()),pending=f.panel.enter();f.deactivate();await pending;f.activate();const html=f.panel.view();assert.doesNotMatch(html,/正在读取原运行记录/);assert.doesNotMatch(html,/<button disabled/);assert.ok(!html.includes('Exact source'));
});
test('disposed panels cannot restart reads or retain a click listener',async()=>{
 const f=fixture(receipt());const pending=f.panel.enter();f.panel.dispose();await pending;const calls=f.calls.length;await f.panel.enter();assert.equal(f.calls.length,calls);assert.equal(f.listeners.click,undefined);
});
test('no-hypothesis validated receipts distinguish source inputs from an empty input package',async()=>{
 for(const empty of [false,true]){
  const run=receipt();run.output.result.opportunities=[];
  if(empty){run.output.packet.items=[];run.output.packet.coverage={...run.output.packet.coverage,status:'needs_fresh_sources',selected:0};run.output.result.evidence=[];run.output.result.coverage={...run.output.packet.coverage};}
  run.steps[0].output=JSON.parse(JSON.stringify(run.output.packet));run.steps[1].output=JSON.parse(JSON.stringify(run.output.result));
  const f=fixture(run);await f.panel.enter();assert.match(f.panel.view(),empty?/没有可用来源输入/:/有来源输入/);assert.ok(!f.panel.view().includes('Check demand'));
 }
});
test('source navigation stays scoped and untrusted source and hypothesis text are escaped',async()=>{
 const run=receipt();run.output.packet.items[0].title='<img src=x onerror=alert(1)>';run.output.result.evidence=JSON.parse(JSON.stringify(run.output.packet.items));run.output.result.opportunities[0].hypothesis='<svg onload=alert(1)>';run.output.result.opportunities[0].next_checks=['<script>cost</script>'];
 run.steps[0].output=JSON.parse(JSON.stringify(run.output.packet));run.steps[1].output=JSON.parse(JSON.stringify(run.output.result));
 const f=fixture(run);await f.panel.enter();const html=f.panel.view();assert.ok(!html.includes('<img'));assert.ok(!html.includes('<svg'));assert.ok(!html.includes('<script>'));assert.match(html,/&lt;img/);
 const fire=(id,inside=true)=>{const node={dataset:{opportunitySource:id},closest:()=>inside?{}:null};f.listeners.click?.({target:{closest:()=>node}})};
 fire('1'.repeat(24),false);fire('2'.repeat(24));assert.equal(f.sources.length,0);fire('1'.repeat(24));assert.deepEqual(f.sources,['1'.repeat(24)]);f.deactivate();fire('1'.repeat(24));assert.equal(f.sources.length,1);
});
