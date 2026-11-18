import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import vm from 'node:vm';
const compiled=await build({entryPoints:['src/overview-pipeline.ts'],bundle:true,write:false,format:'cjs',platform:'node'});
const module={exports:{}};vm.runInNewContext(compiled.outputFiles[0].text,{module,exports:module.exports});
const {targetDirectory,pipelineSummary,readCasePipeline,pipelineStep}=module.exports;
const plain=value=>JSON.parse(JSON.stringify(value));
const target=(case_id='case-1',store_ref='SYN-STORE')=>({case_id,platform:'ozon',store_ref,market:'RU'});
const stage=(id,acceptance_status,required=true,missing=[])=>({id,name:'Stage '+id,required_for_goal:required,acceptance_status,capability_status:'partial',missing,blocked_by:[],limitations:[]});
const snapshot=(stages,extra={})=>({schema:'commerce-operating-pipeline-v1',target:target(),goal:'launch',snapshot_sha256:'a'.repeat(64),product_source_sha256:'b'.repeat(64),stages,observed_at:'2026-11-18T00:00:00Z',business_outcome_verified:false,external_execution_allowed:false,unresolved_release_count:0,release_history_complete:true,...extra});

test('saved plans are grouped by exact case and an unfinished directory is not treated as complete',()=>{
 const directory=targetDirectory({items:[{target:target()},{target:target('case-1','SYN-STORE-2')},{target:target('case-2')},{target:{case_id:'case-3',platform:'ozon',store_ref:'',market:'RU'}},{}],next_offset:25});
 assert.deepEqual([...directory.targets.keys()],['case-1','case-2']);
 assert.equal(directory.targets.get('case-1').length,2);
 assert.equal(directory.complete,false);
 assert.equal(targetDirectory({items:[],next_offset:null}).complete,true);
 assert.equal(targetDirectory(undefined).complete,false);
});

test('progress counts only required stages and names the first open one without calling it done',()=>{
 const summary=pipelineSummary(snapshot([stage('research','prepared'),stage('growth','needs_evidence',false),stage('economics','needs_calculation',true,['Recalculate','Second']),stage('listing','unknown')]));
 assert.deepEqual(plain(summary),{total:3,prepared:1,next:{id:'economics',name:'Stage economics',status:'needs_calculation',label:'待更新测算',missing:'Recalculate'},unresolved:false});
 const ready=pipelineSummary(snapshot([stage('research','prepared')]));
 assert.equal(ready.next,null);assert.equal(ready.prepared,1);
 assert.equal(pipelineSummary(snapshot([stage('research','prepared')],{unresolved_release_count:1})).unresolved,true);
 assert.equal(pipelineSummary(snapshot([stage('research','prepared')],{release_history_complete:false})).unresolved,true);
 assert.equal(pipelineSummary(snapshot([stage('listing','brand_new_status')])).next.label,'待核对');
});

test('a case without a saved plan makes no pipeline request and failures stay distinct from absence',async()=>{
 const calls=[];const api=async(tool,args)=>{calls.push([tool,args]);return snapshot([stage('research','needs_evidence')]);};
 assert.deepEqual(plain(await readCasePipeline(api,'case-9',targetDirectory({items:[],next_offset:null}))),{state:'none',incomplete:false});
 assert.deepEqual(plain(await readCasePipeline(api,'case-9',targetDirectory({items:[],next_offset:25}))),{state:'none',incomplete:true});
 assert.deepEqual(plain(await readCasePipeline(api,'case-1',null)),{state:'failed'});
 assert.equal(calls.length,0);
 const directory=targetDirectory({items:[{target:target()},{target:target('case-1','SYN-STORE-2')}],next_offset:null});
 const read=await readCasePipeline(api,'case-1',directory);
 assert.equal(read.state,'ready');assert.equal(read.others,1);assert.equal(read.target.store_ref,'SYN-STORE');
 assert.deepEqual(plain(calls),[['commerce_operating_pipeline_get',{...target(),goal:'launch'}]]);
 assert.deepEqual(plain(pipelineStep(read)),{kind:'product',section:'research',label:'核对市场研究'});
});

test('another store, a write-enabled answer or a rejected read is never shown as this product path',async()=>{
 const directory=targetDirectory({items:[{target:target()}],next_offset:null});
 const other=async()=>snapshot([stage('research','prepared')],{target:target('case-1','OTHER')});
 const writable=async()=>snapshot([stage('research','prepared')],{external_execution_allowed:true});
 const rejected=async()=>{throw Error('unknown_tool');};
 for(const api of [other,writable,rejected])assert.deepEqual(plain(await readCasePipeline(api,'case-1',directory)),{state:'failed'});
});

test('unresolved applications and a fully prepared path both lead to the listing record, not a new draft',()=>{
 const base={state:'ready',target:target(),others:0};
 assert.deepEqual(plain(pipelineStep({...base,summary:{total:1,prepared:0,next:{id:'research',name:'x',status:'needs_evidence',label:'x',missing:''},unresolved:true}})),{kind:'listing',section:'listing-release',label:'核对原申请回执'});
 assert.deepEqual(plain(pipelineStep({...base,summary:{total:1,prepared:1,next:null,unresolved:false}})),{kind:'listing',section:'listing-release',label:'核对上架方案'});
 assert.equal(pipelineStep({state:'none',incomplete:false}),null);assert.equal(pipelineStep({state:'failed'}),null);
});
