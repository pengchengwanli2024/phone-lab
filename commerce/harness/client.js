window.__ModuleLoader__.load({id:'@local/dsh-commerce',factory:require=>{
  const React=require('react');
  const {useEffect,useState,useRef}=React;
  const PANEL='commerce';
  const send=(route,init)=>{
    const fn=globalThis.__DSH_TRANSPORT__?.fetch;
    return fn?fn(route,init):globalThis.fetch(route,init);
  };
  const platformTabs=new Set(['overview','workspace','products','orders','creative','tasks','connections']);
  function CommercePage({product=false,collaborative=false,caseId='',navigation,onOpenProduct,onBackend,onSelected}={}){
    const frame=useRef(null),nonce=useRef(crypto.randomUUID());
    const [html,setHtml]=useState(''),[error,setError]=useState(''),[version,setVersion]=useState(0);
    useEffect(()=>{
      let active=true;const controller=new AbortController();
      send(product?'api/commerce/product-workspace':'api/commerce/workspace',{signal:controller.signal}).then(async r=>{if(!r.ok)throw Error('后台界面加载失败：'+r.status);return r.text()}).then(text=>{if(active){const body=text.replaceAll('__COMMERCE_BRIDGE_NONCE__',nonce.current);setHtml(product?body.replace('__COMMERCE_BOOTSTRAP__',()=>JSON.stringify({embedded:!collaborative,bridge:true,hosted:collaborative,case_id:caseId})):body);setError('')}}).catch(e=>{if(active)setError(e.message)});
      const receive=async event=>{
        const message=event.data;
        if(event.source!==frame.current?.contentWindow||message?.nonce!==nonce.current)return;
        if(message.type==='commerce:workspace-ready'){sendTheme();return}
        if(message.type==='commerce:workspace-open'){onOpenProduct?.();return}
        if(message.type==='commerce:workspace-backend'){onBackend?.();return}
        if(message.type==='commerce:workspace-navigate'&&platformTabs.has(message.tab)){onBackend?.(message.tab);return}
        if(message.type==='commerce:workspace-selected'&&typeof message.case_id==='string'&&/^[a-zA-Z0-9_-]{1,160}$/.test(message.case_id)){if(message.case_id!==caseId)onSelected?.(message.case_id);return}
        if(message.type!=='commerce:call'||typeof message.id!=='string'||typeof message.tool!=='string'||!/^commerce_(?:[a-z_]+|a2ui_[a-z_]+)$/.test(message.tool))return;
        const target=event.source;
        try{
          const response=await send('api/commerce/invoke',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({tool:message.tool,arguments:message.arguments||{}}),signal:controller.signal});
          const result=await response.json();if(!response.ok)throw Error(result.error||'共享后台请求失败');
          if(active&&target===frame.current?.contentWindow)target.postMessage({type:'commerce:result',nonce:nonce.current,id:message.id,result},'*');
        }catch(e){if(active&&target===frame.current?.contentWindow)target.postMessage({type:'commerce:result',nonce:nonce.current,id:message.id,error:e.message},'*')}
      };
      function sendTheme(){if(product&&!collaborative&&active)frame.current?.contentWindow?.postMessage({type:'commerce:theme',nonce:nonce.current,theme:getComputedStyle(document.documentElement).colorScheme==='dark'?'dark':'light'},'*')}
      const observer=new MutationObserver(sendTheme);observer.observe(document.documentElement,{attributes:true,attributeFilter:['style','class']});observer.observe(document.body,{attributes:true,attributeFilter:['data-ds-dark-theme','style']});
      window.addEventListener('message',receive);return()=>{active=false;controller.abort();observer.disconnect();window.removeEventListener('message',receive)};
    },[version,product,collaborative,caseId,onOpenProduct,onBackend,onSelected]);
    const sendNavigation=()=>{if(!product&&navigation&&platformTabs.has(navigation.tab))frame.current?.contentWindow?.postMessage({type:'commerce:host-navigate',nonce:nonce.current,tab:navigation.tab},'*')};
    useEffect(sendNavigation,[navigation,html]);
    const title=product?(collaborative?'商品协作工作区':'商品工作区'):'跨境电商工作台';
    return React.createElement('section',{style:{height:'100%',minHeight:0,minWidth:0,display:'flex',flexDirection:'column',paddingTop:product&&!collaborative?'0px':'var(--dsh-frame-top-clearance,0px)',background:'transparent'},'aria-label':title},error?React.createElement('div',{role:'alert',style:{padding:24}},error,React.createElement('button',{onClick:()=>setVersion(v=>v+1),style:{marginLeft:16}},'重试')):null,html?React.createElement('iframe',{ref:frame,onLoad:sendNavigation,srcDoc:html,sandbox:'allow-scripts allow-forms allow-downloads',title,style:{border:0,width:'100%',height:'100%',flex:1,minHeight:0},referrerPolicy:'no-referrer'}):React.createElement('div',{role:'status',style:{padding:24}},'正在加载电商工作台…'));
  }
  function StoreIcon({size=18}){return React.createElement('svg',{width:size,height:size,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.6,'aria-hidden':true},React.createElement('path',{d:'M4 10v11h16V10M3 3h18l1 7H2zM9 21v-7h6v7'}))}
  function apply(ctx){
    const TYPE='@local/dsh-commerce/product-workspace';
    const backend=tab=>{ctx.layout.selectPanel(PANEL);window.dispatchEvent(new CustomEvent('commerce:backend-navigate',{detail:{tab:platformTabs.has(tab)?tab:'overview'}}))};
    function MainPage(){
      const [product,setProduct]=useState(false),[visited,setVisited]=useState(false),[navigation,setNavigation]=useState(null);
      const openProduct=React.useCallback(()=>{setVisited(true);setProduct(true)},[]);
      const back=React.useCallback(tab=>{setProduct(false);setNavigation({tab:platformTabs.has(tab)?tab:'overview',revision:crypto.randomUUID()})},[]);
      useEffect(()=>{const receive=e=>back(e.detail?.tab);window.addEventListener('commerce:backend-navigate',receive);return()=>window.removeEventListener('commerce:backend-navigate',receive)},[back]);
      const pane=visible=>({height:'100%',minHeight:0,minWidth:0,display:visible?'flex':'none',flexDirection:'column'});
      // Retain both frames so returning to the dashboard keeps unsent input and edits.
      return React.createElement('div',{style:{height:'100%',minHeight:0}},
        React.createElement('div',{style:pane(!product)},React.createElement(CommercePage,{onOpenProduct:openProduct,navigation})),
        visited?React.createElement('div',{style:pane(product)},React.createElement(CommercePage,{product:true,collaborative:true,onBackend:back})):null);
    }
    function ProductPage({useTabInfo}){
      const {tab}=useTabInfo();
      const address=String(tab.contentId||'');
      const match=address.match(/^dsh-resource:\/\/commerce\/product\/([a-zA-Z0-9_-]{1,160})$/);
      const caseId=match?match[1]:'';
      const selected=React.useCallback(id=>tab.actions.openResource('dsh-resource://commerce/product/'+id,{replaceTab:true}),[tab.actions]);
      return React.createElement(CommercePage,{product:true,caseId,onBackend:backend,onSelected:selected});
    }
    ctx.slots.inject('main',()=>ctx.slots.register({name:'main',key:PANEL},MainPage));
    ctx.slots.inject('sidebar.panellist',()=>ctx.slots.register({name:'sidebar.panellist',id:PANEL,order:10,label:()=> '电商工作台'},StoreIcon));
    ctx.effect(()=>ctx.sidebarRightTabs.register({id:TYPE,kind:'commerce-product',patterns:['dsh-resource://commerce/product/**'],title:()=> '商品工作区',keepMounted:true,guide:[{id:'commerce-product',title:()=> '商品工作区',icon:StoreIcon}]}));
    ctx.slots.inject('sidebar.right.pane.tab',()=>ctx.slots.register({name:'sidebar.right.pane.tab',key:TYPE},ProductPage));
  }
  return {apply,inject:['slots','layout','connection','sidebarRight','sidebarRightTabs']};
}});
