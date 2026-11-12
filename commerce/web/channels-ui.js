/* Project channel plans and local client diagnostics; no credential inputs. */
window.CommerceChannels=({api,ui=window.CommerceUI,repaint,isActive,toast,modal,closeModal})=>{
  const esc=ui.escape;
  const s={data:null,error:'',loading:false,request:0,editor:null,editorGeneration:0,poll:0,timer:null};
  const readiness={account_type_required:'请选择账号类型',not_selected:'尚未选择',adapter_missing:'适配器未就绪',authorization_required:'待授权',gateway_not_running:'客户端未运行',scope_and_delivery_not_verified:'范围与送达待核对',unsupported_account_type:'该类型尚未适配',unknown:'状态未知'};
  const running={not_running:'未运行',stale:'状态已过期',connected_reported:'客户端报告连接',not_connected:'未连接',unknown:'未知'};
  const button=(label,action,attrs={})=>ui.button({label,attrs:{'data-channel-action':action,...attrs}});
  const pending=data=>['pending','queued','running','starting'].includes(data?.probe_status);
  function paint(){if(isActive())repaint()}
  async function load(refresh=false,poll=false){
    const request=++s.request;s.loading=true;s.error='';if(!poll)s.poll=0;
    if(s.timer){clearTimeout(s.timer);s.timer=null;}
    if(!poll)paint();
    try{const data=await api('commerce_channel_status',refresh?{refresh:true}:{});if(!Array.isArray(data?.channels))throw Error('invalid_channel_response');if(request===s.request)s.data=data;}
    catch(error){if(request!==s.request)return;s.data=null;s.error=(error.message==='unknown_tool'?'共享后台尚未加载渠道接入，请更新服务后刷新。':'渠道状态未读到，请刷新重试。');}
    finally{if(request===s.request){s.loading=false;paint();}}
    if(request===s.request&&pending(s.data)&&s.poll++<10&&isActive())s.timer=setTimeout(()=>{s.timer=null;if(isActive()&&!document.querySelector('.dialog'))load(false,true)},1000);
  }
  function view(){
    const d=s.data,observed=d?.probe_status==='observed';
    return `<section class="card" aria-label="消息渠道"><div class="platform-heading"><h2>消息渠道</h2>${button(s.loading?'检查中…':'检查客户端','refresh',{disabled:s.loading})}</div>${s.error?ui.alert(s.error,'danger'):''}${pending(d)?'<p role="status">正在核对本机客户端…</p>':''}${d?`${!observed?ui.alert('本机诊断未确认，请检查客户端后重试。'):''}<p class="muted">${esc(d.profile)} · ${!observed?'共享业务核心状态未知':d.shared_core_configured?'共享业务核心已配置':'共享业务核心待配置'}</p>${ui.table(['渠道','接入状态','操作'],d.channels.map(c=>`<tr><td><strong>${esc(c.name)}</strong><br><small class="muted">${esc(c.modes.find(m=>m.id===c.binding.mode)?.label||'账号类型待确认')}</small></td><td>${ui.badge(readiness[c.readiness]||'状态未知','gray')} ${ui.badge(c.delivery_verified?'送达已核对':'送达待核对',c.delivery_verified?'success':'gray')}<details><summary>诊断</summary><p>适配代码：${!observed?'未知':c.adapter_available?'已安装':'未安装'}<br>凭据字段：${!observed?'未知':c.credentials_present?'已配置':'待授权'}<br>客户端：${!observed?'未知':c.gateway_enabled?'已启用':'未启用'}<br>运行状态：${esc(observed?(running[c.runtime_status]||'未知'):'未知')}${c.missing_fields?.length?'<br>待补字段：'+c.missing_fields.map(esc).join('、'):''}</p></details></td><td><div class="form-actions">${button('配置选择','edit',{'data-channel':c.id})}${button('授权步骤','authorize',{'data-channel':c.id})}</div></td></tr>`))}`:!s.error?'<p role="status">正在读取渠道状态…</p>':''}</section>`;
  }
  function edit(id){
    const c=s.data?.channels.find(c=>c.id===id);if(!c)return;
    s.editor={channel:c.id,revision:c.binding.revision,token:++s.editorGeneration};
    modal(c.name+' · 接入选择',`<div id="channel-editor" data-channel-editor="${s.editor.token}">${ui.field('账号类型',ui.select({id:'channel-mode',value:c.binding.mode,options:c.modes.map(m=>({value:m.id,label:m.label+(m.adapter_supported||m.id==='undecided'?'':'（尚未适配）')}))}))}${ui.field('备注（不填写凭据）',ui.input({id:'channel-label',value:c.binding.label||'',maxlength:60,'aria-describedby':'channel-edit-error'}))}<label class="field"><input id="channel-selected" type="checkbox" ${c.binding.selected?'checked':''}>选用此渠道</label><p class="muted">仅保存本项目的接入选择，授权在本机客户端完成。</p><p id="channel-edit-error" role="alert"></p></div>`,button('保存接入选择','save',{id:'channel-save'}));
  }
  function authorize(id){
    const c=s.data?.channels.find(c=>c.id===id);if(!c)return;
    s.editor=null;
    const mode=c.modes.find(m=>m.id===c.binding.mode);
    if(!mode?.adapter_supported){modal(c.name+' · 接入条件',ui.alert(c.binding.mode==='undecided'?'请先选择微信账号类型。':'当前客户端尚未提供所选账号类型的适配。'),button('修改接入选择','edit',{'data-channel':c.id}));return;}
    const command=s.data.setup_command;
    modal(c.name+' · 本机授权',`${s.data.probe_status!=='observed'?ui.alert('共享服务配置状态未确认，请先检查客户端。'):s.data.shared_core_configured?'':ui.alert('专用客户端的共享服务尚未配置，请先完成 commerce-bot 的 MCP 连接。')}<ol><li>在本机终端运行客户端向导。</li><li>选择该渠道，完成账号授权和允许的用户／群范围。</li><li>返回此页检查客户端，再核对实际收发与送达。</li></ol><pre id="channel-setup-command" tabindex="0">${esc(command)}</pre>${s.data.probe_status==='observed'&&!s.data.profile_available?ui.alert('尚未找到项目客户端，请先完成 commerce-bot 配置。'):''}<p class="muted">此入口不启动网关、不发送测试消息。</p>`,button('复制向导命令','copy-command'));
  }
  document.addEventListener('click',async event=>{
    const target=event.target.closest('[data-channel-action]');if(!target)return;
    const action=target.dataset.channelAction;
    if(action==='refresh'){await load(true);return;}
    if(action==='edit'){edit(target.dataset.channel);return;}
    if(action==='authorize'){authorize(target.dataset.channel);return;}
    if(action==='copy-command'){
      const text=document.querySelector('#channel-setup-command')?.textContent;if(!text)return;
      try{await navigator.clipboard.writeText(text);toast('向导命令已复制');}catch{toast('未能复制，请选择命令手动复制。');}return;
    }
    if(action!=='save'||!s.editor||target.disabled)return;
    const editor=s.editor,mode=document.querySelector('#channel-mode'),label=document.querySelector('#channel-label'),selected=document.querySelector('#channel-selected');
    const sameEditor=()=>s.editor===editor&&document.querySelector('#channel-editor')?.dataset?.channelEditor===String(editor.token);
    if(!mode||!label||!selected||!sameEditor())return;
    if(/bearer\s|sk-[a-z0-9]{16}|-----BEGIN|https?:\/\/|\/Users\/|\/home\//i.test(label.value)){const error=document.querySelector('#channel-edit-error');if(error)error.textContent='备注不能填写凭据或本机路径，请使用客户端授权向导。';label.setAttribute?.('aria-invalid','true');return;}
    target.disabled=true;
    try{await api('commerce_channel_configure',{channel:editor.channel,mode:mode.value,selected:selected.checked,label:label.value.trim(),expected_revision:editor.revision});if(sameEditor()){s.editor=null;closeModal();}await load();toast('接入选择已保存');}
    catch(error){const text=['channel_configuration_conflict','channel_binding_conflict','channel_revision_conflict'].includes(error.message)?'配置已有新版本，当前输入仍保留。关闭后刷新并核对。':'保存未确认，当前输入仍保留。请先刷新状态核对。';const node=sameEditor()?document.querySelector('#channel-edit-error'):null;if(node)node.textContent=text;else toast(text);}
    finally{if(target.isConnected)target.disabled=false;}
  });
  return {view,load};
};
