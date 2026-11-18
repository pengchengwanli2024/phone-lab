import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';

const parentSource=fs.readFileSync(new URL('../../web/product-workspace-ui.js',import.meta.url),'utf8');
const evidenceSource=fs.readFileSync(new URL('../../web/product-evidence-ui.js',import.meta.url),'utf8');
const cut=(a,b)=>parentSource.slice(parentSource.indexOf(a),parentSource.indexOf(b,parentSource.indexOf(a)));
const nextTurn=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({unknown=false,readFailure=false}={}){
  const messages=[],calls=[],announcements=[],s={id:'case-a',tab:'evidence',items:[],data:{},edits:{},dirty:new Set(),researchTaskId:'',researchSequence:0,generation:0,busy:false,error:'',errorCode:''};
  const proposal={revision:0,currency:'CNY'};
  const dossier=()=>({case_id:'case-a',case:{scope:{platform:'ozon',market:'RU'}},name:'A',dossier_sha256:'evidence-a',sources:[],proposal:{...proposal}});
  const parent={postMessage:message=>messages.push(message)};
  let listener,workspaceReads=0;
  const api=async(tool,args)=>{
    calls.push({tool,args});
    if(tool==='commerce_product_evidence_get')return dossier();
    if(tool==='commerce_product_evidence_proposal_save'){
      if(unknown)throw Error('request_outcome_unknown');
      Object.assign(proposal,args.payload,{revision:proposal.revision+1});return {proposal:{...proposal}};
    }
    if(tool==='commerce_workspace_list'){
      workspaceReads++;if(readFailure)throw Error('read_failed');return {items:[{id:'case-a'}]};
    }
    if(tool==='commerce_workspace_get')return {case:{id:'case-a'},forms:{view:{payload:{tab:'evidence'}}}};
    throw Error('unexpected tool '+tool);
  };
  const window={addEventListener:(name,fn)=>{if(name==='message')listener=fn;},CommerceUI:{escape:String}};
  const context=vm.createContext({window,document:{getElementById:()=>({textContent:''}),querySelectorAll:()=>[]},s,parent,api,crypto:{randomUUID},URL,Blob,Uint8Array,atob,btoa,setTimeout,clearTimeout,
    nonce:'nonce',bridged:true,reactHost:true,embedded:true,hostRefreshDeferred:false,lastEditState:'',
    studio:{hasUnsavedChanges:()=>false},researchEditor:{hasActiveMutation:()=>false},modalEdited:false,render(){},announce:text=>announcements.push(text),modelContext:()=>({}),
    quoteDialog(){},selectTab(){},dialog(){},esc:String,btn:()=>'',
    reportResearchSelection(){},enrichIdentity(){},message:error=>error.message,
    tabs:{evidence:'证据与选品'},researchContext:{task:()=>'',artifact(){}},catalog:{},
  });
  vm.runInContext(evidenceSource,context);
  vm.runInContext(cut('  const evidence=','  let copilot,')+
    cut('  function pendingProductSection()','  function modelContext()')+
    cut("  window.addEventListener('message'",'  function announce(')+
    cut('  async function reload(','  function selectTab(')+';this.evidence=evidence;',context);
  return {context,s,messages,calls,announcements,get reads(){return workspaceReads;},c:context.evidence,
    refresh:()=>listener({source:parent,data:{type:'commerce:workspace-refresh',nonce:'nonce',case_id:'case-a'}})};
}

test('evidence save settles the original deferred same-product refresh and clears its warning',async()=>{
  const f=fixture();await f.c.enter('case-a');await f.c.action('proposal-edit');
  f.c.input({dataset:{peField:'selection_reason'},value:'must survive the return'});
  f.refresh();assert.equal(f.messages.at(-1).status,'deferred');assert.equal(f.context.hostRefreshDeferred,true);
  await f.c.action('proposal-save');await nextTurn();
  assert.equal(f.c.hasUnsavedChanges(),false);
  assert.equal(f.reads,1,'successful clean evidence save must read the originally deferred product once');
  assert.equal(f.context.hostRefreshDeferred,false);
  assert.equal(f.s.error,'');assert.equal(f.s.errorCode,'');assert.equal(f.announcements.at(-1),'商品资料已刷新。');
  assert.equal(f.messages.filter(m=>m.type==='commerce:workspace-refresh-result'&&m.status==='refreshed').length,1);
  assert.equal(f.messages.find(m=>m.status==='refreshed').case_id,'case-a');
});

test('other product edits and unknown evidence receipts never trigger a clean refresh',async()=>{
  for(const options of [{unknown:true},{unknown:false}]){
    const f=fixture(options);await f.c.enter('case-a');await f.c.action('proposal-edit');
    f.c.input({dataset:{peField:'selection_reason'},value:'retained input'});
    if(!options.unknown)f.s.dirty.add('cost');
    f.refresh();await f.c.action('proposal-save');await nextTurn();
    assert.equal(f.reads,0);assert.equal(f.context.hostRefreshDeferred,true);
    assert.equal(f.messages.some(m=>m.status==='refreshed'),false);
    if(options.unknown)assert.equal(f.c.hasUnsavedChanges(),true);
  }
});

test('failed deferred read stays recoverable without repeating the evidence save',async()=>{
  const f=fixture({readFailure:true});await f.c.enter('case-a');await f.c.action('proposal-edit');
  f.c.input({dataset:{peField:'selection_reason'},value:'saved once'});f.refresh();
  await f.c.action('proposal-save');await nextTurn();
  assert.equal(f.reads,1);assert.equal(f.context.hostRefreshDeferred,true);
  assert.equal(f.messages.some(m=>m.status==='refreshed'),false);assert.equal(f.s.error,'read_failed');
  assert.equal(f.calls.filter(c=>c.tool==='commerce_product_evidence_proposal_save').length,1);
});
