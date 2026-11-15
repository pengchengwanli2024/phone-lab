// Controlled promises execute the actual recovery function without a browser/API.
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=await readFile('commerce/web/app.js','utf8');
const body=source.slice(source.indexOf('  async function applyFormRestore()'),source.indexOf('  function researchView()'));
for(const scenario of ['scope','edit','cancel','page','unchanged']){
 let release;const wait=new Promise(r=>release=r);
 const context={scope:{module:'research',form:'research',case_id:'A'},state:{tab:'research'},formRestoreGeneration:1,
  pendingFormRestore:{id:1,revision:0,view:'research',kind:'research',scope:{module:'research',form:'research',case_id:'A'},saved:{payload:{record:{platform:'research',value:'saved A'}}}},
  collection:{platform:'research',record:{value:'current A'},revision:0},api:()=>wait,close(){},paint(){},toast(){}};
 context.formScope=()=>context.scope;context.formRevision=()=>context.collection.revision;vm.createContext(context);vm.runInContext(body,context);
 let rejected=false;const done=vm.runInContext('applyFormRestore()',context).catch(()=>{rejected=true});
 if(scenario==='scope'){context.scope={module:'research',form:'ozon',case_id:'B'};context.collection.platform='ozon';context.collection.record={value:'new B'}}
 if(scenario==='edit'){context.collection.revision++;context.collection.record={value:'user edit'}}
 if(scenario==='cancel'){context.pendingFormRestore=null;context.formRestoreGeneration++}
 if(scenario==='page')context.state.tab='operations';
 const before=JSON.stringify(context.collection.record);release({});await done;
 if(scenario==='unchanged'){assert.equal(rejected,false);assert.equal(context.collection.record.value,'saved A')}
 else{assert.equal(rejected,true,scenario);assert.equal(JSON.stringify(context.collection.record),before,scenario)}
}
console.log(JSON.stringify({status:'passed',checks:['scope switch','edit during check','cancel','page switch','valid restore']}));
