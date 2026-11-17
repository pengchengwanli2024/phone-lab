/* A product links to the shared creative editor; it never owns a second editor. */
window.CommerceProductCreativeLinks=({api,repaint,getBinding,onOpen,formatProjectLabel=p=>p.name||'未命名项目'})=>{
  const ui=window.CommerceUI,e=ui.escape;
  const state={caseId:'',items:[],busy:false,error:'',generation:0};
  function binding(){return getBinding?.()||null}
  function sync(){const id=binding()?.case_id||'';if(id!==state.caseId){state.caseId=id;state.items=[];state.error='';state.busy=false;state.generation++;}}
  async function enter(){sync();const id=state.caseId;if(!id)return;const generation=++state.generation;state.busy=true;state.error='';repaint();try{const result=await api('commerce_creative_list');if(generation!==state.generation||binding()?.case_id!==id)return;state.items=result.projects.filter(p=>p.case_id===id);}catch{if(generation===state.generation)state.error='内容项目尚未读回，请重新读取。';}finally{if(generation===state.generation){state.busy=false;repaint();}}}
  const button=(label,action,attrs={})=>ui.button({label,attrs:{'data-product-content-action':action,...attrs}});
  function view(){sync();return ui.card({title:'内容项目',content:`${state.error?ui.alert(state.error,'danger'):''}<div class="pw-form-actions">${button('新建内容项目','create',{disabled:state.busy})}${button('刷新项目','refresh',{disabled:state.busy})}</div>${state.busy?'<p role="status">正在读取当前商品的内容项目…</p>':state.items.length?ui.table(['项目','资料版本','操作'],state.items.map(p=>`<tr><td>${e(formatProjectLabel(p,state.items))}${p.synthetic?ui.badge('合成资料','gray'):''}</td><td>${e(p.revision??'未记录')}</td><td>${button('打开内容项目','open',{'data-project':p.id,'aria-label':'打开内容项目：'+formatProjectLabel(p,state.items)})}</td></tr>`)):ui.empty('当前商品还没有内容项目。')}`});}
  document.addEventListener('click',event=>{const target=event.target.closest('[data-product-content-action]');if(!target||target.disabled)return;const b=binding();if(!b?.case_id||!b.source_sha256)return;const action=target.dataset.productContentAction;if(action==='refresh'){void enter();return;}if(action==='open'){const project=state.items.find(p=>p.id===target.dataset.project);if(!project)return;onOpen({...b,project_id:project.id});}else if(action==='create')onOpen({...b});});
  return {view,enter,hasUnsavedChanges:()=>false,discardChanges(){}};
};
