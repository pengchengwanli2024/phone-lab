/* One configuration entry; store views retain their existing read receipts. */
window.CommerceConnections=({api,repaint,isActive,toast,getStatus,knowledgeView,modal,closeModal})=>{
  const ui=window.CommerceUI,esc=ui.escape;
  const state={catalog:null,live:null,error:'',busy:false,generation:0};
  const channels=window.CommerceChannels?.({api,ui,repaint,isActive,toast,modal,closeModal});
  const resources={orders:'订单',products:'商品',stock:'库存'};
  const button=(label,action)=>ui.button({label,attrs:{'data-connection-action':action,disabled:state.busy}});
  async function load(){
    const generation=++state.generation;state.busy=true;
    const results=await Promise.allSettled([api('commerce_platform_catalog'),api('commerce_live_status'),channels?.load()]);
    if(generation!==state.generation)return;
    state.catalog=results[0].status==='fulfilled'?results[0].value:null;
    state.live=results[1].status==='fulfilled'?results[1].value:null;
    state.error=results.slice(0,2).flatMap((result,index)=>result.status==='rejected'?[(index?'Ozon 与飞书':'平台目录')+'：'+result.reason.message]:[]).join('；');
    state.busy=false;if(isActive())repaint();
  }
  function view(){
    const c=getStatus(),live=state.live;
    const providers=state.catalog?.providers||[];
    const clients=c?.clients||{};
    return `<div class="connections-root"><section class="card"><div class="platform-heading"><h2>店铺与通知连接</h2>${button('刷新连接状态','refresh')}</div><p class="muted" data-ui-help>凭据在本机私有向导填写。配置、读取回执和通知收件分别核对。</p>${state.error?ui.alert(esc(state.error),'danger'):''}${state.busy?'<p role="status">正在读取连接状态…</p>':''}${ui.table(['连接','配置与核对','操作'],[
      `<tr><td>Ozon · 俄罗斯</td><td>${live?ui.badge(live.configured?'凭据字段已保存':'凭据待填写','gray')+' '+ui.badge(live.orders_scope_confirmed?'订单范围已核对':'订单范围待核对','gray'):ui.badge('状态未读到','gray')}</td><td rowspan="2">${button('配置 Ozon 与飞书','ozon-setup')}</td></tr>`,
      `<tr><td>飞书单向通知</td><td>${live?ui.badge(live.feishu_test_verified?'接口测试已接收':'接口测试未完成','gray')+' '+ui.badge(live.feishu_received_confirmed?'群内收件已确认':'群内收件未确认','gray')+' '+ui.badge(live.notifications_enabled?'通知已开启':'通知未开启','gray'):ui.badge('状态未读到','gray')}</td></tr>`,
      `<tr><td>其他平台</td><td>${providers.length?providers.map(provider=>esc(provider.name)).join('、'):'平台目录尚未读到'}</td><td>${button('配置多平台只读连接','platform-setup')}</td></tr>`
    ])}<p class="muted" data-ui-help>业务快照、手动读取与同步回执在店铺管理中查看；保存连接不会代替授权范围核对。</p>${providers.length?`<details><summary>查看平台支持范围</summary>${ui.table(['平台','只读范围','口径与限制'],providers.map(provider=>`<tr><td>${esc(provider.name)}</td><td>${esc(provider.resources.map(resource=>resources[resource]||resource).join('、'))}</td><td>${esc(provider.notice)}</td></tr>`))}</details>`:''}</section>
    ${channels?.view()||''}<section class="card"><h2>客户端</h2>${ui.table(['客户端','最近调用','操作'],[['DeepSeek Harness','harness'],['Hermes','hermes'],['Codex','codex']].map(([name,key])=>`<tr><td>${name}</td><td>${clients[key]?esc(new Date(clients[key]).toLocaleString()):'尚无调用记录'}</td><td>${ui.button({label:'连接方法',action:'client-info',attrs:{'data-client':key}})}</td></tr>`))}<p class="muted" data-ui-help>调用记录表示曾访问共享服务，不代表模型、平台授权或界面渲染已通过验证。</p></section>${knowledgeView()}</div>`;
  }
  document.addEventListener('click',async event=>{
    const target=event.target.closest('[data-connection-action]');if(!target||state.busy)return;
    const action=target.dataset.connectionAction;
    if(action==='refresh'){await load();return}
    if(!['ozon-setup','platform-setup'].includes(action))return;
    target.disabled=true;
    try{const result=await api(action==='ozon-setup'?'commerce_live_open_setup':'commerce_platform_open_setup');toast(result.opened||result.status==='opened_local_private_setup'?'已请求打开本机私有向导，请在浏览器核对。':'打开结果尚未确认，请检查本机浏览器。')}
    catch(error){toast('未能打开私有向导：'+error.message)}
    finally{if(target.isConnected)target.disabled=false}
  });
  return {view,load};
};
