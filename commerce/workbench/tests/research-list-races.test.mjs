import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

test('late list read cannot undo the completed detail refresh',async()=>{
  const source=await readFile('src/candidates.tsx','utf8'),helper=await readFile('../web/research-context.js','utf8');
  const old={task_id:'task-a',revision:1,status:'unknown',candidate_count:0,candidates:[]},fresh={...old,revision:5,status:'partial',candidate_count:1,candidates:[{case_id:'case-a'}]};
  const state={jobs:[old],job:null},requests=[];
  const context=vm.createContext({window:{},generation:{current:0},detailGeneration:{current:0},selected:{current:'task-a'},setLoading(){},setError(){},setJobError(){},setItems(){},setDetailLoading(){},setDetailError(){},setJob:value=>state.job=value,setJobs:value=>state.jobs=typeof value==='function'?value(state.jobs):value,errorText:error=>error.message,api:(name,args)=>new Promise(resolve=>requests.push({name,args,resolve}))});
  vm.runInContext(helper,context);
  const functions=source.slice(source.indexOf('async function load('),source.indexOf('  useEffect(',source.indexOf('async function readTask('))).replace('id: string','id').replace(/api<[^>]+>/g,'api');
  vm.runInContext(functions,context);
  const list=context.load(),detail=context.readTask('task-a');
  requests.find(r=>r.name==='commerce_market_research_get').resolve(fresh);await detail;
  requests.find(r=>r.name==='commerce_workspace_list').resolve({items:[{id:'case-a',candidate:true}]});requests.find(r=>r.name==='commerce_market_research_list').resolve({jobs:[old]});await list;
  assert.equal(state.jobs[0],fresh);assert.equal(state.job,fresh);
});
