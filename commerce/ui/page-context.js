/* Registered UI metadata and visible error feedback; no cookies or arbitrary form scraping. */
(() => {
  const labels={overview:'运营台',workspace:'商品工作区',listing:'上架准备',workflow:'工作流画布',orders:'订单','store-ops':'日常运营','order-imports':'订单导入',products:'库存',operations:'成本与定价',restock:'补货计划',models:'模型管理',memory:'资料与知识',intelligence:'全球情报',research:'研究资料',pilots:'商品候选',creative:'创意工作室',agent:'模型分析',tasks:'任务中心',organization:'岗位交接',exposure:'经营关联',platforms:'平台数据',live:'Ozon 经营',alerts:'经营提醒',support:'客服',insights:'选品与评论',skills:'技能','assistant-team':'智能体团队','operating-control':'自动经营',connections:'连接与授权',phones:'手机墙',tools:'工具发现'};
  const sections={evidence:'证据与选品',shipping:'装箱与运费',social:'社交观察',overview:'概览',research:'市场研究',media:'图片与视频',tasks:'任务中心','sales-trend':'销售趋势','inventory-statistics':'库存统计','order-status':'发货单状态','platform-sales':'平台销售构成','order-detail':'订单详情','product-detail':'商品详情',cost:'成本测算',stock:'补货测算',plan:'工作计划',content:'商品内容',creative:'图片与视频',review:'资料核对',sources:'资料来源',delivery:'交付核对',details:'详情',list:'列表',map:'地图'};
  const filterKeys=new Set(['platform','market','store_id','store_ref','query','status','source','country','category','hours','scope','view','time','date_from','date_to']);
  const inputKeys=new Set(['sku','title','description','category_id','currency','price','purchase_cost','domestic_shipping','packaging','fulfillment_cost','electronic_fee','commission_rate','payment_rate','return_rate','ad_rate','sold_units','window_days','observed_days','lead_time_days','safety_days','available','on_order','pack_size','moq','quantity','budget']);
  const clean=value=>{
    if(!value||typeof value!=='object'||!Object.hasOwn(labels,value.page))return null;
    const out={page:value.page,demo:value.demo===true};
    if(['live','local','unavailable','stale'].includes(value.source))out.source=value.source;
    if(typeof value.section==='string'&&/^[a-zA-Z0-9_-]{1,64}$/.test(value.section))out.section=value.section;
    if(value.entity&&['case','order','product','intel','task','chart','skill','model','aircraft','vessel'].includes(value.entity.kind)&&typeof value.entity.id==='string'&&/^[a-zA-Z0-9_.:/-]{1,180}$/.test(value.entity.id))out.entity={kind:value.entity.kind,id:value.entity.id,...(typeof value.entity.name==='string'?{name:value.entity.name.slice(0,120)}:{})};
    for(const [key,allowed,max]of [['filters',filterKeys,160],['input',inputKeys,20000]])if(value[key]&&typeof value[key]==='object'){
      const fields=Object.entries(value[key]).filter(([k,v])=>allowed.has(k)&&(!['platform','market','store_id','store_ref'].includes(k)||v!=='')&&(typeof v==='string'&&v.length<=max&&!/\n|bearer\s|sk-[a-z0-9]{16}|\/Users\//i.test(v)||key==='input'&&(typeof v==='number'&&Number.isFinite(v)||v===null)));
      if(fields.length)out[key]=Object.fromEntries(fields.map(([k,v])=>[k,key==='input'&&typeof v==='string'&&v.length>220?v.slice(0,220)+'…[已截断]':v]));
    }
    if(value.source_refs&&typeof value.source_refs==='object')out.source_refs=Object.fromEntries(Object.entries(value.source_refs).filter(([k,v])=>/^[a-z_]{1,40}$/.test(k)&&typeof v==='string'&&/^[a-f0-9]{64}$/.test(v)).slice(0,8));
    if(Array.isArray(value.errors))out.errors=value.errors.filter(v=>typeof v==='string'&&!/bearer\s|sk-[a-z0-9]{16}|\/Users\//i.test(v)).slice(0,3).map(v=>v.slice(0,300));
    return out;
  };
  const marker=element=>{try{return JSON.parse(element?.getAttribute?.('data-ai-context')||'{}')}catch{return {}}};
  const label=value=>{const location=[labels[value?.page],sections[value?.section]||value?.section,value?.entity?.kind==='chart'?'':value?.entity?.name||value?.entity?.id].filter(Boolean).join(' › ');const details=[value?.filters?.platform&&value.filters.platform!=='all'?value.filters.platform==='ozon'?'Ozon':value.filters.platform:'',value?.filters?.store_id&&value.filters.store_id!=='all'?value.filters.store_id:'',value?.filters?.scope&&value.filters.scope!=='all'?(value.filters.scope==='unassigned'?'未关联店铺':'店铺视图 #'+value.filters.scope.slice(-6)):'',!value?.filters?.store_id||value.filters.store_id==='all'?value?.filters?.store_ref||'':'',value?.filters?.market&&value.filters.market!=='all'?value.filters.market:'',value?.filters?.date_from&&value.filters.date_to?value.filters.date_from+' — '+value.filters.date_to:'',value?.demo?'示例数据':({live:'真实数据',local:'本机资料',unavailable:'暂无真实数据',stale:'真实快照已过期'}[value?.source]||'按本页来源')].filter(Boolean).join(' · ');return [location,details].filter(Boolean).join(' · ')};
  window.CommercePageContext={clean,label,create({getBase,root=()=>document.body,onChange=()=>{}}){
    let selected=null,last='',disposed=false,scheduled=false,observed=null,observer=null,inputTimer=null;
    function snapshot(){
      const base=getBase()||{},node=root(),pageMarker=[...(node?.querySelectorAll?.('[data-ai-page]')||[])].find(el=>el.getAttribute('data-ai-page')===base.page&&!el.closest?.('[hidden]'));
      if(selected&&(!selected.isConnected||node&&!node.contains(selected)&&!selected.closest?.('.dialog,.r-dialog')))selected=null;
      const page={...base,...marker(pageMarker)},selection=marker(selected);
      const searches=[...(node?.querySelectorAll?.('input[type="search"],input[id$="-query"],input[id$="-keyword"]')||[])].filter(el=>el.getClientRects?.().length);const search=searches.find(el=>el===document.activeElement)||searches[0];if(search&&typeof search.value==='string')page.filters={...page.filters,query:search.value.slice(0,160)};
      const feedback=[...(node?.querySelectorAll?.('[role="alert"],.alert.error')||[])].filter(el=>el.getClientRects?.().length&&!el.closest?.('#commerce-copilot')).map(el=>el.textContent?.trim()).filter(Boolean);if(feedback.length)page.errors=feedback;
      return clean({...page,...selection,page:base.page,demo:typeof page.demo==='boolean'?page.demo:base.demo,filters:selection.replace_filters?selection.filters:{...page.filters,...selection.filters},source_refs:selection.source_refs||page.source_refs});
    }
    function changed(){if(disposed)return;const node=root();if(node!==observed){observer?.disconnect();observed=node;if(node&&typeof MutationObserver!=='undefined'){observer=new MutationObserver(notify);observer.observe(node,{subtree:true,childList:true,attributes:true,attributeFilter:['data-ai-context','data-ai-page','hidden']})}}const value=snapshot(),signature=JSON.stringify(value);if(signature!==last){last=signature;onChange(value)}}
    function notify(){if(scheduled||disposed)return;scheduled=true;Promise.resolve().then(()=>{scheduled=false;changed()})}
    function select(event){const node=root(),target=event.target;if(!node||!target||target.closest?.('#commerce-copilot')||!node.contains(target)&&!target.closest?.('.dialog,.r-dialog'))return;const next=target.closest?.('[data-ai-context]');if(next)selected=next;if(event.type==='input'||event.type==='change'){/* Trusted events may flush microtasks before the framework's bubbling input handler. */if(inputTimer===null)inputTimer=setTimeout(()=>{inputTimer=null;notify()},0)}else notify()}
    for(const name of ['pointerdown','focusin','change','input'])document.addEventListener(name,select,true);
    changed();
    return {snapshot,changed,reset(){selected=null;last='';changed()},dispose(){disposed=true;if(inputTimer!==null)clearTimeout(inputTimer);observer?.disconnect();for(const name of ['pointerdown','focusin','change','input'])document.removeEventListener(name,select,true)}};
  }};
})();
