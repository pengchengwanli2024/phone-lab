window.__ModuleLoader__.load({id:'@local/dsh-commerce',factory:require=>{
  const React=require('react');
  const {useEffect,useState,useRef}=React;
  const PANEL='commerce';
  const send=(route,init)=>{
    const fn=globalThis.__DSH_TRANSPORT__?.fetch;
    return fn?fn(route,init):globalThis.fetch(route,init);
  };
  const platformTabs=new Set(['overview','workspace','products','orders','creative','tasks','connections','pilots','models','intelligence']);
  function CommercePage({product=false,collaborative=false,caseId='',researchTaskId='',navigation,onOpenProduct,onBackend,onSelected}={}){
    const frame=useRef(null),nonce=useRef(crypto.randomUUID()),researchRequest=useRef(researchTaskId),callbacks=useRef({onOpenProduct,onBackend,onSelected});researchRequest.current=researchTaskId;callbacks.current={onOpenProduct,onBackend,onSelected};
    const [html,setHtml]=useState(''),[error,setError]=useState(''),[version,setVersion]=useState(0);
    useEffect(()=>{
      let active=true;const controller=new AbortController();
      send(product?'api/commerce/product-workspace':'api/commerce/workspace',{signal:controller.signal}).then(async r=>{if(!r.ok)throw Error('后台界面加载失败：'+r.status);return r.text()}).then(text=>{if(active){const body=text.replaceAll('__COMMERCE_BRIDGE_NONCE__',nonce.current);setHtml(product?body.replace('__COMMERCE_BOOTSTRAP__',()=>JSON.stringify({embedded:!collaborative,bridge:true,hosted:collaborative,case_id:caseId,research_task_id:researchRequest.current})):body);setError('')}}).catch(e=>{if(active)setError(e.message)});
      const receive=async event=>{
        const message=event.data;
        if(event.source!==frame.current?.contentWindow||message?.nonce!==nonce.current)return;
        if(message.type==='commerce:copilot-draft'){
          if(typeof message.id!=='string'||message.id.length>80)return;
          try{
            if(typeof message.key!=='string'||message.key.length>8000||!message.key.startsWith('commerce-copilot-draft-v1:'))throw Error('invalid_draft_key');
            const scope=message.key.slice(26);if(scope.startsWith('new:')){let context;try{context=JSON.parse(scope.slice(4))}catch{}if(!context||typeof context.module!=='string'||!/^[a-z_]{1,40}$/.test(context.module)||typeof context.demo!=='boolean')throw Error('invalid_draft_key')}else if(!/^[a-zA-Z0-9_-]{1,160}$/.test(scope))throw Error('invalid_draft_key');
            if(!['read','write'].includes(message.op))throw Error('invalid_draft_operation');
            if(message.op==='write'&&(typeof message.value!=='string'||message.value.length>2000||typeof message.expected!=='string'||message.expected.length>2000))throw Error('invalid_draft_value');
            const operate=()=>{if(!active||event.source!==frame.current?.contentWindow)throw Error('draft_storage_unavailable');const stored=localStorage.getItem(message.key)||'';if(message.op==='read')return stored;if(stored!==message.expected)throw Error('draft_storage_conflict');localStorage.setItem(message.key,message.value);return message.value};
            const locks=globalThis.navigator?.locks,value=locks?await locks.request(message.key,operate):operate();
            if(active&&event.source===frame.current?.contentWindow)event.source.postMessage({type:'commerce:copilot-draft-result',nonce:nonce.current,id:message.id,value},'*');
          }catch(error){if(active&&event.source===frame.current?.contentWindow)event.source.postMessage({type:'commerce:copilot-draft-result',nonce:nonce.current,id:message.id,error:error.message},'*')}
          return;
        }
        if(message.type==='commerce:workspace-ready'){sendTheme();sendResearchContext();return}
        if(message.type==='commerce:workspace-research'&&typeof message.task_id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(message.task_id)){callbacks.current.onBackend?.('pilots',message.task_id);return}
        if(message.type==='commerce:workspace-open'){callbacks.current.onOpenProduct?.();return}
        if(message.type==='commerce:workspace-backend'){callbacks.current.onBackend?.();return}
        if(message.type==='commerce:workspace-navigate'&&platformTabs.has(message.tab)){callbacks.current.onBackend?.(message.tab);return}
        if(message.type==='commerce:workspace-selected'&&typeof message.case_id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(message.case_id)){if(message.research_task_id!=null&&(typeof message.research_task_id!=='string'||(message.research_task_id&&!/^[a-zA-Z0-9_-]{1,160}$/.test(message.research_task_id))))return;if(researchRequest.current&&message.research_task_id==null){setError('当前界面尚未确认本次研究快照，请刷新后重试。');return}const selectedTask=message.research_task_id||'';if(message.case_id!==caseId||selectedTask!==researchRequest.current)callbacks.current.onSelected?.(message.case_id,selectedTask);return}
        if(message.type!=='commerce:call'||typeof message.id!=='string'||typeof message.tool!=='string'||!/^commerce_(?:[a-z_]+|a2ui_[a-z_]+)$/.test(message.tool))return;
        const target=event.source;
        try{
          const response=await send('api/commerce/invoke',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({tool:message.tool,arguments:message.arguments||{}}),signal:controller.signal});
          const result=await response.json();if(!response.ok)throw Error(result.error||'共享后台请求失败');
          if(active&&target===frame.current?.contentWindow)target.postMessage({type:'commerce:result',nonce:nonce.current,id:message.id,result},'*');
        }catch(e){if(active&&target===frame.current?.contentWindow)target.postMessage({type:'commerce:result',nonce:nonce.current,id:message.id,error:e.message},'*')}
      };
      function sendResearchContext(){if(product&&active)frame.current?.contentWindow?.postMessage({type:'commerce:workspace-research-context',nonce:nonce.current,case_id:caseId,research_task_id:researchRequest.current},'*')}
      function sendTheme(){if(product&&!collaborative&&active)frame.current?.contentWindow?.postMessage({type:'commerce:theme',nonce:nonce.current,theme:getComputedStyle(document.documentElement).colorScheme==='dark'?'dark':'light'},'*')}
      const observer=new MutationObserver(sendTheme);observer.observe(document.documentElement,{attributes:true,attributeFilter:['style','class']});observer.observe(document.body,{attributes:true,attributeFilter:['data-ds-dark-theme','style']});
      window.addEventListener('message',receive);return()=>{active=false;controller.abort();observer.disconnect();window.removeEventListener('message',receive)};
    },[version,product,collaborative,caseId]);
    const sendNavigation=()=>{if(!product&&navigation&&platformTabs.has(navigation.tab))frame.current?.contentWindow?.postMessage({type:'commerce:host-navigate',nonce:nonce.current,tab:navigation.tab,...(navigation.research_task_id?{research_task_id:navigation.research_task_id}:{})},'*')};
    useEffect(sendNavigation,[navigation,html]);
    const sendRequestedResearch=()=>{if(product)frame.current?.contentWindow?.postMessage({type:'commerce:workspace-research-context',nonce:nonce.current,case_id:caseId,research_task_id:researchTaskId},'*')};
    useEffect(sendRequestedResearch,[product,caseId,researchTaskId,html]);
    const title=product?(collaborative?'商品协作工作区':'商品工作区'):'跨境电商工作台';
    return React.createElement('section',{style:{height:'100%',minHeight:0,minWidth:0,display:'flex',flexDirection:'column',paddingTop:product&&!collaborative?'0px':'var(--dsh-frame-top-clearance,0px)',background:'transparent'},'aria-label':title},error?React.createElement('div',{role:'alert',style:{padding:24}},error,React.createElement('button',{onClick:()=>setVersion(v=>v+1),style:{marginLeft:16}},'重试')):null,html?React.createElement('iframe',{ref:frame,onLoad:()=>{sendNavigation();sendRequestedResearch()},srcDoc:html,sandbox:'allow-scripts allow-forms allow-downloads',title,style:{border:0,width:'100%',height:'100%',flex:1,minHeight:0},referrerPolicy:'no-referrer'}):React.createElement('div',{role:'status',style:{padding:24}},'正在加载电商工作台…'));
  }
  function StoreIcon({size=18}){return React.createElement('svg',{width:size,height:size,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.6,'aria-hidden':true},React.createElement('path',{d:'M4 10v11h16V10M3 3h18l1 7H2zM9 21v-7h6v7'}))}
  function apply(ctx){
    const TYPE='@local/dsh-commerce/product-workspace';
    let pendingNavigation=null;
    const backend=(tab,taskId='')=>{const navigation={tab:platformTabs.has(tab)?tab:'overview',...(tab==='pilots'&&/^[a-zA-Z0-9_-]{1,160}$/.test(taskId)?{research_task_id:taskId}:{}),revision:crypto.randomUUID()};pendingNavigation=navigation;ctx.layout.selectPanel(PANEL);window.dispatchEvent(new CustomEvent('commerce:backend-navigate',{detail:navigation}))};
    function MainPage(){
      const [product,setProduct]=useState(false),[visited,setVisited]=useState(false),[navigation,setNavigation]=useState(()=>pendingNavigation);
      const openProduct=React.useCallback(()=>{setVisited(true);setProduct(true)},[]);
      const back=React.useCallback((tab,taskId='')=>{setProduct(false);setNavigation({tab:platformTabs.has(tab)?tab:'overview',...(tab==='pilots'&&/^[a-zA-Z0-9_-]{1,160}$/.test(taskId)?{research_task_id:taskId}:{}),revision:crypto.randomUUID()})},[]);
      useEffect(()=>{const receive=e=>{const request=pendingNavigation;if(!request||request.revision!==e.detail?.revision)return;pendingNavigation=null;back(request.tab,request.research_task_id)};window.addEventListener('commerce:backend-navigate',receive);if(pendingNavigation)receive({detail:pendingNavigation});return()=>window.removeEventListener('commerce:backend-navigate',receive)},[back]);
      const pane=visible=>({height:'100%',minHeight:0,minWidth:0,display:visible?'flex':'none',flexDirection:'column'});
      // Retain both frames so returning to the dashboard keeps unsent input and edits.
      return React.createElement('div',{style:{height:'100%',minHeight:0}},
        React.createElement('div',{style:pane(!product)},React.createElement(CommercePage,{onOpenProduct:openProduct,navigation})),
        visited?React.createElement('div',{style:pane(product)},React.createElement(CommercePage,{product:true,collaborative:true,onBackend:back})):null);
    }
    function ProductPage({useTabInfo}){
      const {tab}=useTabInfo();
      const address=String(tab.contentId||'');
      let parsed=address==='sidebar://commerce-product'?{caseId:'',researchTaskId:''}:undefined;try{const url=new URL(address),match=url.pathname.match(/^\/product\/([a-zA-Z0-9_-]{1,160})$/),values=url.searchParams.getAll('research_task_id');if(url.protocol==='dsh-resource:'&&url.host==='commerce'&&!url.username&&!url.password&&!url.hash&&match&&values.length<=1&&[...url.searchParams.keys()].every(key=>key==='research_task_id')&&(!values[0]||/^[a-zA-Z0-9_-]{1,160}$/.test(values[0])))parsed={caseId:match[1],researchTaskId:values[0]||''}}catch{}
      const selected=React.useCallback((id,taskId='')=>{if(!/^[a-zA-Z0-9_-]{1,160}$/.test(id)||(taskId&&!/^[a-zA-Z0-9_-]{1,160}$/.test(taskId)))return;const url=new URL('dsh-resource://commerce/product/'+id);if(taskId)url.searchParams.set('research_task_id',taskId);tab.actions.openResource(url.href,{replaceTab:true})},[tab.actions]);
      if(!parsed)return React.createElement('div',{role:'alert'},'研究链接无效，请从原研究任务重新打开。');
      return React.createElement(CommercePage,{product:true,...parsed,onBackend:backend,onSelected:selected});
    }
    ctx.slots.inject('main',()=>ctx.slots.register({name:'main',key:PANEL},MainPage));
    ctx.slots.inject('sidebar.panellist',()=>ctx.slots.register({name:'sidebar.panellist',id:PANEL,order:10,label:()=> '电商工作台'},StoreIcon));
    ctx.effect(()=>ctx.sidebarRightTabs.register({id:TYPE,kind:'commerce-product',patterns:['dsh-resource://commerce/product/**'],title:()=> '商品工作区',keepMounted:true,guide:[{id:'commerce-product',title:()=> '商品工作区',icon:StoreIcon}]}));
    ctx.slots.inject('sidebar.right.pane.tab',()=>ctx.slots.register({name:'sidebar.right.pane.tab',key:TYPE},ProductPage));
  }
  return {apply,inject:['slots','layout','connection','sidebarRight','sidebarRightTabs']};
}});
