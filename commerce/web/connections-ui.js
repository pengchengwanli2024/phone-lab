/* One configuration entry; store views retain their existing read receipts. */
window.CommerceConnections=({api,repaint,isActive,toast,getStatus,modal,closeModal})=>{
  const ui=window.CommerceUI,esc=ui.escape;
  const state={catalog:null,live:null,stores:null,error:'',busy:false,generation:0};
  const channels=window.CommerceChannels?.({api,ui,repaint,isActive,toast,modal,closeModal});
  const resources={orders:'订单',products:'商品',stock:'库存'};
  const button=(label,action)=>ui.button({label,attrs:{'data-connection-action':action,disabled:state.busy}});
  async function load(){
    const generation=++state.generation;state.busy=true;
    const results=await Promise.allSettled([api('commerce_platform_catalog'),api('commerce_live_status'),api('commerce_platform_list'),channels?.load()]);
    if(generation!==state.generation)return;
    state.catalog=results[0].status==='fulfilled'?results[0].value:null;
    state.live=results[1].status==='fulfilled'?results[1].value:null;
    state.stores=results[2].status==='fulfilled'?results[2].value.stores:null;
    state.error=results.slice(0,3).flatMap((result,index)=>result.status==='rejected'?[[ '平台目录','Ozon 与飞书','平台连接状态'][index]+'：'+result.reason.message]:[]).join('；');
    state.busy=false;if(isActive())repaint();
  }
  function view(){
    const c=getStatus(),live=state.live;
    const providers=state.catalog?.providers||[];
    const clients=c?.clients||{};
    return `<div class="connections-root"><section class="card"><div class="platform-heading"><h2>店铺与通知连接</h2>${button('刷新连接状态','refresh')}</div><p class="muted" data-ui-help>凭据在本机私有向导填写。配置、读取回执和通知收件分别核对。</p>${state.error?ui.alert(esc(state.error),'danger'):''}${state.busy?'<p role="status">正在读取连接状态…</p>':''}<div class="form-actions">${button('配置 Ozon 与飞书','ozon-setup')}${button('配置多平台只读连接','platform-setup')}</div>${ui.table(['连接','配置与核对'],[
      `<tr><td>Ozon · 俄罗斯</td><td>${live?ui.badge(live.configured?'凭据字段已保存':'凭据待填写','gray')+' '+ui.badge(live.orders_scope_confirmed?'订单范围已核对':'订单范围待核对','gray'):ui.badge('状态未读到','gray')}</td></tr>`,
      `<tr><td>飞书单向通知</td><td>${live?ui.badge(live.feishu_test_verified?'接口测试已接收':'接口测试未完成','gray')+' '+ui.badge(live.feishu_received_confirmed?'群内收件已确认':'群内收件未确认','gray')+' '+ui.badge(live.notifications_enabled?'通知已开启':'通知未开启','gray'):ui.badge('状态未读到','gray')}</td></tr>`,
      ...providers.map(provider=>{const stores=(state.stores||[]).filter(store=>store.platform===provider.id);return `<tr><td>${esc(provider.name)}</td><td>${state.stores===null?'连接状态未读到':!stores.length?'尚未配置连接':stores.map(store=>`<p><strong>${esc(store.label)}</strong>${store.market?' · '+esc(store.market):''}<br>${ui.badge(store.configured?'凭据字段已保存':'凭据待补','gray')} ${ui.badge(store.scope_reviewed?'授权范围已核对':'授权范围待核对','gray')} ${ui.badge(store.enabled?'允许手动读取':'手动读取未启用','gray')}</p>`).join('')}</td></tr>`}),
      ...(!providers.length?[`<tr><td>多平台目录</td><td>${state.busy?'正在读取平台目录…':'平台目录尚未读到'}</td></tr>`]:[])
    ])}<p class="muted" data-ui-help>业务快照、手动读取与同步回执在店铺管理中查看；保存连接不会代替授权范围核对。</p>${providers.length?`<details><summary>查看平台支持范围</summary>${ui.table(['平台','只读范围','口径与限制'],providers.map(provider=>`<tr><td>${esc(provider.name)}</td><td>${esc(provider.resources.map(resource=>resources[resource]||resource).join('、'))}</td><td>${esc(provider.notice)}</td></tr>`))}</details>`:''}</section>
    <section class="card"><div class="platform-heading"><h2>模型与本地服务</h2>${button('管理模型','model-setup')}</div><p class="muted">管理对话使用的本机或兼容模型服务。</p></section>${channels?.view()||''}<section class="card"><div class="platform-heading"><h2>业务资料</h2>${button('资料与业务记忆','knowledge')}</div></section><details class="card"><summary>客户端调用记录</summary>${ui.table(['客户端','最近调用','操作'],[['DeepSeek Harness','harness'],['Hermes','hermes'],['Codex','codex']].map(([name,key])=>`<tr><td>${name}</td><td>${clients[key]?esc(new Date(clients[key]).toLocaleString()):'尚无调用记录'}</td><td>${ui.button({label:'连接方法',action:'client-info',attrs:{'data-client':key}})}</td></tr>`))}<p class="muted">调用记录仅表示访问过共享服务。</p></details></div>`;
  }
  document.addEventListener('click',async event=>{
    const target=event.target.closest('[data-connection-action]');if(!target||state.busy)return;
    const action=target.dataset.connectionAction;
    if(action==='knowledge'){
      if(window.__COMMERCE_LEGACY__)parent.postMessage({type:'commerce:workspace-navigate',nonce:'__COMMERCE_BRIDGE_NONCE__',tab:'memory'},'*');
      else location.assign('/?tab=memory');
      return;
    }
    if(action==='refresh'){await load();return}
    if(!['ozon-setup','platform-setup','model-setup'].includes(action))return;
    target.disabled=true;
    try{const result=await api(action==='model-setup'?'commerce_model_open_setup':action==='ozon-setup'?'commerce_live_open_setup':'commerce_platform_open_setup');toast(result.opened||result.status==='opened_local_private_setup'?'已请求打开本机私有向导，请在浏览器核对。':'打开结果尚未确认，请检查本机浏览器。')}
    catch(error){toast('未能打开私有向导：'+error.message)}
    finally{if(target.isConnected)target.disabled=false}
  });
  return {view,load};
};
