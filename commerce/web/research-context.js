/* Read-side research identity. It never replaces the current item's write base. */
((target)=>{
  const valid=value=>typeof value==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(value);
  function task(value){if(value==null||value==='')return '';if(!valid(value))throw Error('workspace_research_context_invalid');return value}
  function resource(caseId,taskId=''){if(!valid(caseId))throw Error('workspace_research_context_invalid');const value=new URL('dsh-resource://commerce/product/'+caseId);if(task(taskId))value.searchParams.set('research_task_id',taskId);return value.href}
  function parseResource(address){try{const value=new URL(address);if(value.protocol!=='dsh-resource:'||value.host!=='commerce'||value.username||value.password||value.hash)return null;const match=value.pathname.match(/^\/product\/([a-zA-Z0-9_-]{1,160})$/);if(!match||[...value.searchParams.keys()].some(key=>key!=='research_task_id')||value.searchParams.getAll('research_task_id').length>1)return null;return {caseId:match[1],researchTaskId:task(value.searchParams.get('research_task_id'))}}catch{return null}}
  function artifact(data,requested=''){
    const selected=data.research_context;
    if(requested&&(!selected||selected.task_id!==task(requested)))throw Error('workspace_research_context_unavailable');
    if(selected){if(selected.read_only!==true||!selected.artifact||selected.artifact.id!==selected.artifact_id)throw Error('workspace_research_context_unavailable');return selected.artifact}
    return data.artifacts.research;
  }
  function merge(data,readback,requested){
    if(data.case.id!==readback.case.id)throw Error('workspace_research_context_invalid');
    artifact(readback,requested);
    return {...data,research_context:readback.research_context,research_contexts:readback.research_contexts};
  }
  const revision=value=>{const number=typeof value==='number'?value:typeof value==='string'&&/^[1-9]\d*$/.test(value)?Number(value):NaN;return Number.isSafeInteger(number)&&number>=1?number:NaN};
  const newer=(current,readback)=>current&&revision(current.revision)>revision(readback.revision)?current:readback;
  const mergeJob=(jobs,readback)=>jobs.map(job=>job.task_id===readback.task_id?newer(job,readback):job);
  const mergeJobs=(jobs,readback)=>{const known=new Map(jobs.map(job=>[job.task_id,job]));return readback.map(job=>newer(known.get(job.task_id),job))};
  target.CommerceResearchContext=Object.freeze({task,artifact,merge,mergeJob,mergeJobs,resource,parseResource});
})(typeof window==='object'?window:globalThis);
