window.__ModuleLoader__.load({id:'@local/dsh-commerce',factory:require=>{
  const React=require('react');
  const {useEffect,useState,useRef}=React;
  const PANEL='commerce';
  const send=(route,init)=>{
    const fn=globalThis.__DSH_TRANSPORT__?.fetch;
    return fn?fn(route,init):globalThis.fetch(route,init);
  };
  function CommercePage(){
    const frame=useRef(null),nonce=useRef(crypto.randomUUID());
    const [html,setHtml]=useState(''),[error,setError]=useState(''),[version,setVersion]=useState(0);
    useEffect(()=>{
      let active=true;const controller=new AbortController();
      send('api/commerce/page',{signal:controller.signal}).then(async r=>{if(!r.ok)throw Error('后台界面加载失败：'+r.status);return r.text()}).then(text=>{if(active){setHtml(text.replaceAll('__COMMERCE_BRIDGE_NONCE__',nonce.current));setError('')}}).catch(e=>{if(active)setError(e.message)});
      const receive=async event=>{
        const message=event.data;
        if(event.source!==frame.current?.contentWindow||message?.type!=='commerce:call'||message.nonce!==nonce.current||typeof message.id!=='string'||typeof message.tool!=='string'||!/^commerce_[a-z_]+$/.test(message.tool))return;
        const target=event.source;
        try{
          const response=await send('api/commerce/invoke',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({tool:message.tool,arguments:message.arguments||{}}),signal:controller.signal});
          const result=await response.json();if(!response.ok)throw Error(result.error||'共享后台请求失败');
          if(active&&target===frame.current?.contentWindow)target.postMessage({type:'commerce:result',nonce:nonce.current,id:message.id,result},'*');
        }catch(e){if(active&&target===frame.current?.contentWindow)target.postMessage({type:'commerce:result',nonce:nonce.current,id:message.id,error:e.message},'*')}
      };
      window.addEventListener('message',receive);return()=>{active=false;controller.abort();window.removeEventListener('message',receive)};
    },[version]);
    return React.createElement('section',{style:{height:'100%',minHeight:0,minWidth:0,display:'flex',flexDirection:'column',paddingTop:'var(--dsh-frame-top-clearance,0px)',background:'#f8faff'},'aria-label':'电商工作台'},error?React.createElement('div',{role:'alert',style:{padding:24}},error,React.createElement('button',{onClick:()=>setVersion(v=>v+1),style:{marginLeft:16}},'重试')):null,html?React.createElement('iframe',{ref:frame,srcDoc:html,sandbox:'allow-scripts allow-downloads',title:'跨境电商工作台',style:{border:0,width:'100%',height:'100%',flex:1,minHeight:0},referrerPolicy:'no-referrer'}):React.createElement('div',{role:'status',style:{padding:24}},'正在加载电商工作台…'));
  }
  function StoreIcon({size=18}){return React.createElement('svg',{width:size,height:size,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.6,'aria-hidden':true},React.createElement('path',{d:'M4 10v11h16V10M3 3h18l1 7H2zM9 21v-7h6v7'}))}
  function apply(ctx){
    ctx.slots.inject('main',()=>ctx.slots.register({name:'main',key:PANEL},CommercePage));
    ctx.slots.inject('sidebar.panellist',()=>ctx.slots.register({name:'sidebar.panellist',id:PANEL,order:10,label:()=> '电商工作台'},StoreIcon));
  }
  return {apply,inject:['slots','layout','connection']};
}});
