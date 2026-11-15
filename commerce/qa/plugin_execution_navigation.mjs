// Exercise the actual continuation function with reordered network replies.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../web/app.js',import.meta.url),'utf8');
const implementation=source.match(/async function openPluginExecution\(id\)\{[^\n]+/)[0];
function harness(){
 const pending=new Map(),opened=[],state={tab:'tasks'};
 const api=(_,args)=>new Promise(resolve=>pending.set(args.execution_id,resolve));
 const build=new Function('api','state','opened',`let pluginOpenGeneration=0,navigationGeneration=0;
 const navigate=async tab=>{if(state.tab!==tab){navigationGeneration++;state.tab=tab}};
 const creative={openProject:async(...args)=>{if(args[3]())opened.push(args.slice(0,3))}};
 ${implementation}
 return {open:openPluginExecution,away:()=>navigate('orders')};`);
 return {pending,opened,state,...build(api,state,opened)};
}
{
 const h=harness(),a=h.open('A'),b=h.open('B');
 h.pending.get('B')({project_id:'product-B',request_id:'request-B',plan_id:'plan-B'});await b;
 h.pending.get('A')({project_id:'product-A',request_id:'request-A',plan_id:'plan-A'});await a;
 assert.deepEqual(h.opened,[['product-B','request-B','plan-B']]);
}
{
 const h=harness(),a=h.open('A');await h.away();
 h.pending.get('A')({project_id:'product-A',request_id:'request-A',plan_id:'plan-A'});await a;
 assert.equal(h.state.tab,'orders');assert.deepEqual(h.opened,[]);
}
console.log('passed: latest continuation wins; route change invalidates delayed reply');

const creativeSource=await readFile(new URL('../creative_ui.js',import.meta.url),'utf8');
const open=creativeSource.match(/async function open\(id[^\n]+/)[0];
const openProject=creativeSource.match(/async function openProject\(id[^\n]+/)[0];
const pending=new Map(),requests=[],state={revision:0},api=(_,args)=>new Promise(resolve=>pending.set(args.project_id,resolve));
const create=new Function('state','api','requests',`const syncScope=()=>{},paint=()=>{},getBinding=()=>null,formFrom=()=>{},errorText=e=>e.message;
const flow={openRequest:async(id,plan,isCurrent)=>{if(isCurrent())requests.push([id,plan])},refresh:async()=>{}};
${open}
${openProject}
return openProject;`);
const projectOpen=create(state,api,requests);
const a=projectOpen('A','request-A','plan-A'),b=projectOpen('B','request-B','plan-B');
pending.get('B')({id:'B',assets:[]});await b;
pending.get('A')({id:'A',assets:[]});await a;
assert.deepEqual(requests,[['request-B','plan-B']]);
let current=true;const departed=projectOpen('C','request-C','plan-C',()=>current);current=false;
pending.get('C')({id:'C',assets:[]});await departed;
assert.equal(state.project.id,'B');assert.equal(requests.length,1);
console.log('passed: superseded project reads and departed routes cannot select old requests');

const workflowSource=await readFile(new URL('../web/media-workflow-ui.js',import.meta.url),'utf8');
const openRequest=workflowSource.match(/async function openRequest\(id[^\n]+/)[0],reads=[],selected=[],workflow={requestOpenGeneration:0,data:{requests:[{id:'A'},{id:'B'}]}};
const workflowOpen=new Function('s','reads','selected',`const getProject=()=>({id:'project'}),repaint=()=>{};
const refresh=()=>new Promise(resolve=>reads.push(resolve)),providers={selectPluginPlan:id=>selected.push(id)};
${openRequest}
return openRequest;`)(workflow,reads,selected);
const wa=workflowOpen('A','plan-A'),wb=workflowOpen('B','plan-B');reads[1]();await wb;reads[0]();await wa;
assert.equal(workflow.request,'B');assert.deepEqual(selected,['plan-B']);
console.log('passed: reordered same-project workflow refreshes retain latest request and plan');
