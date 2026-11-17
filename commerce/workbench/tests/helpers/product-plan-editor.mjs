import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';
const source=readFileSync(new URL('../../../web/product-workspace-ui.js',import.meta.url),'utf8');
const cut=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
export function planEditorFixture(payload={goal:'Original goal',steps:[{id:'step_a',title:'Same title',task_id:'task_a'},{id:'step_b',title:'Same title',task_id:'task_b'}]},options={}){
 const listeners={},requests=[],dialogs=[],focused=[];
 const caseId=options.caseId||'exact-case';
 const s={id:caseId,generation:1,actionEpoch:0,changes:0,busy:false,tab:'overview',edits:{},dirty:new Set(),fieldErrors:{},data:{case:{id:caseId},source_sha256:options.sourceSha||'a'.repeat(64),forms:{plan:{payload:structuredClone(payload),revision:options.revision??2}}}};
 const document={addEventListener:(name,fn)=>listeners[name]=fn,getElementById:id=>({focus:()=>focused.push(id)}),querySelector:()=>null,activeElement:null};
 const context=vm.createContext({s,document,reportEditState(){},modalEdited:false,fields:{},structuredClone,crypto:{randomUUID},reactHost:true,planEdit:null,
  esc:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  ui:{field:(label,control)=>label+control,input:p=>'<input id="'+p.id+'" value="'+p.value+'">'},
  btn:(label,action,_primary,attrs={})=>'<button data-pw-action="'+action+'" '+(attrs.disabled?'disabled':'')+'>'+label+'</button>',
  alert:(text)=>text,dialog:(title,body,actions)=>dialogs.push({title,body,actions}),closeDialog:()=>{context.planEdit=null;},
  dirty:form=>{s.dirty.add(form);s.changes++;},render(){},announce(){},message:e=>e.message,reload:async()=> 'refreshed',
  api:async(tool,args)=>{requests.push({tool,args:structuredClone(args)});if(options.failSave)throw Error('request_outcome_unknown');return {};}
 });
 vm.runInContext(cut('  function formData(','  function formStatus(')+cut('  async function saveForm(','  function openResearchCandidate(')+cut('  function goalDialog(','  function download(')+cut('  async function act(',"  document.addEventListener('click'")+cut("  document.addEventListener('input'","  document.addEventListener('change'")+`;this.goalDialog=goalDialog;this.act=act;`,context);
 return {s,context,requests,dialogs,focused,open:()=>context.goalDialog(),input:(id,value)=>listeners.input({target:id==='pw-goal'?{id,value,dataset:{}}:{id:'pw-plan-title-'+id,value,dataset:{pwPlanStep:id}}}),action:(action,id)=>context.act(action,{dataset:{step:id}}),get draft(){return context.planEdit;},get saved(){return requests.at(-1)?.args.payload;}};
}
