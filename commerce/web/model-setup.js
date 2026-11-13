/* Private HTTP-only model setup. Keys never enter MCP, storage or URLs. */
(()=>{
  const ui=window.CommerceUI,esc=ui.escape,root=document.getElementById('model-setup-root');
  let models=[],editing=null,busy=false,message='',error='';
  const engines={llama_cpp:'llama.cpp',vllm:'vLLM',custom:'自定义兼容服务'};
  const errors={model_invalid_endpoint:'服务地址须为本机/私网 HTTP 或 HTTPS，不能含账号、查询参数或完整请求路径。',model_profile_changed:'配置已被其它页面更新，请刷新后核对。',model_test_failed:'测试未返回正确结果，请核对服务、模型 ID、认证和 JSON 输出支持。',model_not_ready:'请先测试当前配置，再启用模型。',model_test_unknown:'测试超时，服务是否完成推理仍未知。不会自动重试，请先核对服务状态。',model_test_busy:'已有模型正在测试，请稍后再试。',authentication_required:'本机登录已失效，请从工作台重新打开模型管理。',model_invalid_model:'请填写正确的模型 ID。',model_invalid_label:'请填写模型名称。'};
  async function request(path,data){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),95000);try{const r=await fetch(path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(data),signal:controller.signal});const value=await r.json();if(!r.ok)throw Error(errors[value.error]||'请求未完成，请核对配置后重试。');return value}catch(e){if(e.name==='AbortError')throw Error('请求超时，结果尚未确认。请刷新状态，不会自动重试。');throw e}finally{clearTimeout(timer)}}
  async function load(){const result=await request('/v1/invoke',{tool:'commerce_model_list',arguments:{},client:'browser'});models=result.models;if(editing)editing=models.find(m=>m.id===editing.id)||null;}
  const button=(label,action,attrs={},variant='secondary')=>ui.button({label,variant,attrs:{'data-model-action':action,disabled:busy,...attrs}});
  function render(){
    const p=editing||{},custom=models.filter(m=>m.engine!=='builtin');
    root.innerHTML=`<header class="platform-heading"><h1>模型与本地服务</h1>${button('刷新','refresh')}</header><p class="muted">为对话配置模型服务。保存、推理测试和启用分别进行；切换模型在原会话中完成。</p>${error?ui.alert(error,'danger'):''}${message?`<p role="status">${esc(message)}</p>`:''}<section class="card"><h2>已配置模型</h2>${ui.table(['模型','服务','状态','操作'],models.map(m=>`<tr><td>${esc(m.label)}<br><small class="muted">${esc(m.model||'')}</small></td><td>${esc(engines[m.engine]||'项目既有路由')}</td><td>${esc(m.engine==='builtin'?'按请求检查':m.selectable?'已启用':m.test_status==='passed'?'测试通过 · 未启用':m.test_status==='unknown'?'测试结果未知':m.test_status==='failed'?'测试未通过':'待测试')}</td><td>${m.engine==='builtin'?'在对话中选择':`${button('编辑','edit',{'data-id':m.id})} ${button('测试','test',{'data-id':m.id})} ${button(m.enabled?'停用':'启用',m.enabled?'disable':'enable',{'data-id':m.id,disabled:busy||(!m.enabled&&m.test_status!=='passed')})}`}</td></tr>`))}</section><section class="card"><header class="platform-heading"><h2>${editing?'编辑模型':'添加模型'}</h2>${editing?button('添加其它模型','new'):''}</header><form id="model-profile-form"><div class="model-fields">${ui.field('显示名称',ui.input({name:'label',value:p.label||'',required:true,maxlength:80,autocomplete:'off'}))}${ui.field('服务类型',ui.select({name:'engine',value:p.engine||'llama_cpp',options:Object.entries(engines).map(([value,label])=>({value,label}))}))}${ui.field('服务基础地址',ui.input({name:'base_url',value:p.base_url||'http://127.0.0.1:8080/v1',required:true,placeholder:'http://127.0.0.1:8080/v1',autocomplete:'off'}))}${ui.field('模型 ID',ui.input({name:'model',value:p.model||'',required:true,maxlength:160,placeholder:'服务实际提供的模型 ID',autocomplete:'off'}))}<div class="model-wide">${ui.field(p.key_configured?'API 密钥（已保存，留空保留）':'API 密钥（本地服务可留空）',ui.input({type:'password',name:'api_key',value:'',autocomplete:'new-password'}))}</div><label><input type="checkbox" name="json_mode" ${p.json_mode!==false?'checked':''}> 请求 JSON 对象输出</label><label><input type="checkbox" name="clear_api_key"> 清除已保存密钥</label></div><div class="model-actions">${ui.button({label:busy?'处理中…':'保存配置',variant:'primary',attrs:{type:'submit',disabled:busy}})}</div></form></section><details class="card"><summary>本地服务接入要求</summary><p>llama.cpp 与 vLLM 使用其兼容聊天 API 的基础地址和模型 ID。服务应已经启动并加载模型；本页不执行安装命令或下载模型。</p><p>JSON 模式不受支持时可取消该选项，回复仍须通过项目的结构化结果与工具范围校验。配置测试只发送合成问题，不读取项目业务资料。</p></details>`;
  }
  root.addEventListener('click',async event=>{
    const b=event.target.closest('[data-model-action]');if(!b||busy)return;
    const action=b.dataset.modelAction,p=models.find(m=>m.id===b.dataset.id);
    if(action==='edit'){editing=p;error='';message='';render();root.querySelector('[name="label"]').focus();return}
    if(action==='new'){editing=null;error='';message='';render();return}
    const form=root.querySelector('form'),draft=form?new FormData(form):null;
    busy=true;error='';message=action==='test'?'正在发送一次合成推理测试…':'';render();
    try{
      if(action==='test'){await request('/v1/models/test',{model_id:p.id,expected_revision:p.revision});message='模型返回了正确测试响应，可明确启用。'}
      else if(action==='enable'||action==='disable'){await request('/v1/models/enabled',{model_id:p.id,expected_revision:p.revision,enabled:action==='enable'});message=action==='enable'?'模型已启用，可在对话中选择。':'模型已停用，后续请求不会继续派发。'}
      await load();
    }catch(e){error=e.message}finally{busy=false;render();if(draft&&action!=='edit'&&action!=='new'){for(const [k,v]of draft){const e=root.querySelector(`[name="${k}"]`);if(e&&e.type!=='password'&&e.type!=='checkbox')e.value=v;}}}
  });
  root.addEventListener('submit',async event=>{
    if(event.target.id!=='model-profile-form')return;event.preventDefault();if(busy)return;
    const form=event.target,f=new FormData(form),data={label:f.get('label'),engine:f.get('engine'),base_url:f.get('base_url'),model:f.get('model'),api_key:f.get('api_key'),json_mode:f.has('json_mode'),clear_api_key:f.has('clear_api_key'),...(editing?{id:editing.id,expected_revision:editing.revision}:{})};
    busy=true;error='';message='';form.querySelector('[name="api_key"]').value='';
    const submit=form.querySelector('button[type="submit"]');submit.disabled=true;
    try{editing=await request('/v1/models/configure',data);await load();message='配置已保存。请测试当前配置，再启用。';render()}catch(e){error=e.message;let notice=root.querySelector('[data-model-save-error]');if(!notice){notice=document.createElement('p');notice.dataset.modelSaveError='';notice.setAttribute('role','alert');form.prepend(notice)}notice.textContent=error}finally{data.api_key='';busy=false;if(submit.isConnected)submit.disabled=false;else render()}
  });
  request('/v1/invoke',{tool:'commerce_ui_get_preferences',arguments:{},client:'browser'}).then(p=>ui.applyTheme(p.theme)).catch(()=>{});
  load().then(render).catch(e=>{error=e.message;render()});
})();
