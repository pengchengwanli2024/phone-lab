(() => {
  const UI=window.CommerceUI,esc=UI.escape;
  let state=null,busy=false,testResult=null,poll=null;
  const labels={review_orders_scope_first:'请先把订单样本与 OGL 后台核对，并确认读取范围。',fetch_orders_before_scope_review:'请先拉取一次真实订单。',ozon_auth_or_permission:'Ozon 身份验证或权限不足，请核对 Client ID、API Key 及只读角色。',ozon_rate_limited:'Ozon 限流，请稍后再试。',ozon_network_error:'暂时无法连接 Ozon，请检查本机网络。',unexpected_orders_schema:'订单返回结构与当前解析器不同，已停止更新，需要核对接口样本。',unexpected_stock_schema:'库存返回结构与当前解析器不同，已停止更新，需要核对接口样本。',missing_pagination_flag:'订单分页标记缺失，未将部分数据视为完整快照。',missing_pagination_cursor:'库存分页游标缺失，未更新有效快照。',pagination_not_progressing:'分页游标没有前进，已保留上次有效数据。',select_fulfillment_modes:'请至少选择一种实际履约方式。',invalid_client_id:'请填写 Seller API 页面显示的数字 Client ID。',invalid_ozon_api_key:'请填写 API Key；已保存时可留空保留。',review_live_stock_before_confirming_basis:'请先拉取真实库存，再核对可售口径。',verify_feishu_test_and_confirm_receipt_first:'请先发送测试，并确认目标群确实收到了消息。',complete_manual_sync_first:'请先完成一次手动同步。',establish_orders_baseline_first:'请先完成订单初始同步。',configure_feishu_target_first:'请先填写飞书群标签与 Webhook。',invalid_feishu_webhook:'请填写目标群自定义机器人的完整飞书 Webhook 地址。',configure_ozon_first:'请先保存 Ozon 的履约方式和只读凭据。'};
  const message=error=>labels[error]||'操作未完成：'+error;
  const button=(label,action,primary=false,disabled=false)=>UI.button({label,variant:primary?'primary':'secondary',attrs:{'data-setup-action':action,disabled}});
  const field=(id,label,type='text',value='',placeholder='')=>UI.field(label,UI.input({id,type,value,placeholder,autocomplete:type==='password'?'new-password':'off'}));
  const number=(id,label,value,min,max)=>UI.field(label,UI.input({id,type:'number',value,min,max,step:1}));
  const card=(title,content)=>UI.card({title,content});
  function status(text,error=false){const target=document.querySelector('#setup-status');target.innerHTML=UI.alert(text,error?'danger':'info')}
  async function api(path,data){const response=await fetch('/v1/connections/'+path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});let result;try{result=await response.json()}catch{throw Error('local_service_response_failed')}if(!response.ok)throw Error(result.error||'local_service_failed');return result}
  async function refresh(){state=await api('status');paint()}
  function paint(){
    if(!state)return;
    const credentials=state.credentials_present;
    const job=state.last_job;
    const progress=job?`<p class="muted">最近同步：${esc(job.status)}${job.finished?' · '+esc(job.finished):''}</p>${job.result?Object.entries(job.result).map(([kind,value])=>UI.alert(`${kind==='orders'?'订单':'库存'}：${value.status==='success'?'完成，'+value.count+' 条'+(value.baseline_only?'；本次仅建立初始基线':''):message(value.code||value.status)}`,value.status==='success'?'info':'danger')).join(''):''}`:'';
    const orderRows=(state.order_samples||[]).map(r=>`<tr><td>${esc(r.posting_number)}</td><td>${esc(r.status)}</td><td>${r.products.map(p=>esc(p.offer_id||p.sku)+' × '+p.quantity).join('<br>')}</td><td>${esc(r.fulfillment)}</td></tr>`);
    const stockRows=(state.stock_samples||[]).map(r=>`<tr><td>${esc(r.offer_id||r.sku||r.product_id)}</td><td>${esc(r.type)}</td><td>${r.present}</td><td>${r.reserved}</td><td>${r.present>=r.reserved?r.present-r.reserved:'字段异常，需核对'}</td></tr>`);
    document.querySelector('#setup-root').innerHTML=[
      card('第 1 步 · 选择实际履约方式',`<p>可多选。已确认首家店铺使用 OGL，可选择 OGL 保留原名称；其订单接口范围还需用本次只读返回核对，不把它自动改称 FBS 或 FBO。</p><div class="form-actions">${[['OGL','OGL'],['FBS','FBS'],['realFBS','realFBS'],['FBO','FBO']].map(([value,label])=>`<label class="review-check">${UI.input({type:'checkbox',name:'modes',value,checked:state.fulfillment_modes.includes(value)})}${label}</label>`).join('')}</div>${field('store-label','本机店铺标签','text',state.store_label)}`),
      card('第 2 步 · 保存 Ozon 只读凭据',`<p>在 Ozon 卖家后台进入「设置 → 卖家 API → 生成密钥」，为密钥命名并核对角色，选择能读取订单和商品库存的最小权限。角色名称与账号页面为准。</p><p class="muted"><a href="https://global-help.ozon.com/zh/api/intro" target="_blank" rel="noreferrer noopener">Ozon 官方授权说明</a>。不要选择修改库存、发货、价格或广告的用途。</p><div class="analysis-fields">${field('ozon-client','Client ID','password','',credentials.ozon_client_id?'已保存，留空保留':'从 Seller API 页面复制')}${field('ozon-key','API Key','password','',credentials.ozon_api_key?'已保存，留空保留':'仅在这里粘贴 API Key')}${number('lookback','订单同步窗口（天）',state.lookback_days,1,90)}${number('interval','自动同步间隔（秒）',state.interval_seconds,60,3600)}</div><div class="form-actions">${button('保存 Ozon 配置','save-ozon',true)}${button('测试只读连接并拉取数据','sync',false,!state.configured)}</div><p class="muted">初次完整同步只建立基线，不批量推送历史订单。同步覆盖所选时间窗口，不代表全部历史订单。</p>${progress}`),
      card('第 3 步 · 核对真实订单与库存',`<p>订单快照：${state.orders.count===null?'尚未取得':state.orders.count+' 条'}；库存产品快照：${state.stock.count===null?'尚未取得':state.stock.count+' 条'}。${!state.orders.fresh||!state.stock.fresh?'部分数据缺失或已过期。':''}</p>${UI.table(['发货单','平台原状态','商品 / 数量','来源模式'],orderRows,'还没有真实订单样本；接口返回完整空列表也可能是窗口内无订单。')}<p class="muted">订单范围核对：${state.orders_scope_confirmed?'已确认':'未确认'}。请核对相同时间窗口、发货单号、SKU 和数量；OGL 名称来自你的选择，接口模式仍需与后台对应。</p>${button('订单范围已经与 OGL 后台核对','confirm-orders',false,!state.orders.available)}<p>下面保留库存原值。请在 Ozon 后台核对同一商品与履约范围；此接口是履约方式汇总，不能当作单个仓库库存。</p>${UI.table(['SKU / offer','履约范围','原始 present','原始 reserved','候选 present − reserved'],stockRows,'还没有可核对的库存样本。')}<div class="analysis-fields">${UI.field('核对后的可售口径',UI.select({id:'stock-basis',value:state.stock_basis,options:[{value:'unconfirmed',label:'尚未核对，暂不开低库存推送'},{value:'present_minus_reserved',label:'后台可售与 present − reserved 一致'},{value:'present_is_available',label:'后台可售与 present 一致'}]}))}${number('low-threshold','低库存提醒阈值（件）',state.low_stock_threshold,0,1000000)}</div><label class="review-check">${UI.input({type:'checkbox',id:'stock-reviewed'})}我已按同一 SKU 和履约范围核对后台数量</label><div class="form-actions">${button('保存库存口径与阈值','save-stock',true,!state.stock.available)}</div>`),
      card('第 4 步 · 配置飞书提醒群',`<p>在你希望接收提醒的飞书群中，打开「设置 → 群机器人 → 添加机器人 → 自定义机器人」，名称可填“电商出单提醒”。复制 Webhook，并在机器人安全设置中启用签名校验后复制签名密钥。</p><p class="muted">此方式只向该群发提醒，不接收聊天指令，不影响现有 Hermes 网关。<a href="https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot" target="_blank" rel="noreferrer noopener">飞书官方操作说明</a></p><div class="analysis-fields">${field('feishu-label','接收群标签（便于你核对）','text',state.feishu_target_label)}${field('feishu-hook','群机器人 Webhook','password','',credentials.feishu_webhook?'已保存，留空保留':'仅在这里粘贴完整 Webhook')}${field('feishu-sign','签名密钥','password','',credentials.feishu_signing_secret?'已保存，留空保留':'与机器人签名设置保持一致')}</div><div class="form-actions">${button('保存飞书配置','save-feishu',true)}${button('向该群发送一条测试消息','test',false,!credentials.feishu_webhook)}</div>${testResult?UI.alert(testResult.status==='sent'?'飞书接口已接收测试消息，请到目标群查看；接口成功不等于手机已弹通知。':testResult.status==='unknown'?'测试结果不明。先核对群内是否收到，系统不会自动重发。':'测试失败：'+testResult.code,testResult.status==='sent'?'info':'danger'):''}<p class="muted">接口测试：${state.feishu_test_verified?'已接收':'尚未验证'}；你核对群内收件：${state.feishu_received_confirmed?'已确认':'尚未确认'}。</p>${button('我已在目标群收到测试消息','confirm-received',false,!state.feishu_test_verified)}`),
      card('第 5 步 · 开启定时同步与提醒',`<p>自动同步：${state.sync_enabled?'已开启':'未开启'}；飞书推送：${state.notifications_enabled?'已开启':'未开启'}。</p><p class="muted">新发现的待处理发货单会去重提醒。低库存推送需要先核对可售口径。客户姓名、电话、地址不进入提醒。发送结果不明时不自动重发，Mac 休眠或断网时不能保证及时推送。</p><div class="form-actions">${button('开启自动同步','enable-sync',true,!state.orders.available)}${button('开启飞书提醒','enable-notify',true,!state.feishu_test_verified||!state.feishu_received_confirmed||!state.orders.available)}${button('暂停同步和提醒','pause')}</div><p class="muted">通知队列：${state.outbox.map(x=>esc(x.status)+' '+x.count).join('；')||'暂无消息'}。已发送代表接口回执确认；手机提示还受飞书和系统通知设置影响。</p>`)
    ].join('');
    document.querySelectorAll('button[data-setup-action]').forEach(b=>{if(busy)b.disabled=true});
  }
  const value=id=>document.getElementById(id).value.trim();
  async function save(data){await api('save',data);await refresh()}
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-setup-action]');if(!button||busy)return;
    const action=button.dataset.setupAction;busy=true;document.querySelectorAll('button[data-setup-action]').forEach(b=>b.disabled=true);
    try{
      if(action==='save-ozon')await save({store_label:value('store-label'),fulfillment_modes:[...document.querySelectorAll('[name=modes]:checked')].map(e=>e.value),ozon_client_id:value('ozon-client'),ozon_api_key:value('ozon-key'),lookback_days:Number(value('lookback')),interval_seconds:Number(value('interval'))});
      else if(action==='sync'){await api('sync',{});await refresh();status('只读同步已开始；页面会更新结果。');if(!poll)poll=setInterval(async()=>{try{await refresh();if(state.last_job?.status!=='running'){clearInterval(poll);poll=null;status('本次同步已结束，请查看订单、库存状态并核对样本。')}}catch{}},1600)}
      else if(action==='confirm-orders')await save({orders_scope_confirmed:true});
      else if(action==='save-stock')await save({stock_basis:value('stock-basis'),basis_confirmed:document.getElementById('stock-reviewed').checked,low_stock_threshold:Number(value('low-threshold'))});
      else if(action==='save-feishu')await save({feishu_target_label:value('feishu-label'),feishu_webhook:value('feishu-hook'),feishu_signing_secret:value('feishu-sign')});
      else if(action==='test'){testResult=await api('test-feishu',{});await refresh()}
      else if(action==='confirm-received')await save({feishu_received_confirmed:true});
      else if(action==='enable-sync')await save({sync_enabled:true});
      else if(action==='enable-notify')await save({notifications_enabled:true});
      else if(action==='pause')await save({sync_enabled:false,notifications_enabled:false});
      if(action!=='sync')status('操作已完成；配置状态已更新。');
    }catch(error){status(message(error.message),true)}
    finally{busy=false;paint()}
  });
  refresh().then(()=>status('从第 1 步开始。已经保存的密钥不会回填到页面；留空会保留原值。')).catch(error=>status(message(error.message),true));
})();
