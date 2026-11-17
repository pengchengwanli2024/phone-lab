import {useLayoutEffect,useRef,useState} from 'react';
import {Button} from './ui';
import {MoreActions} from './action-menu';
import {visibleModuleLinks} from './module-navigation-layout';
import './module-navigation.css';

export function ModuleNavigation({items,active,label,navigate}:{items:{id:string;label:string}[];active:string;label:string;navigate:(id:string)=>void}){
  const nav=useRef<HTMLElement>(null),measure=useRef<HTMLDivElement>(null),returnFocus=useRef(false);
  const [shown,setShown]=useState(()=>items.map(item=>item.id));
  const signature=items.map(item=>item.id+':'+item.label).join('|');
  useLayoutEffect(()=>{
    const host=nav.current,labels=measure.current;if(!host||!labels)return;
    function fit(){
      if(!host||!labels||!host.clientWidth)return;
      const style=getComputedStyle(host),available=host.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
      const widths=[...labels.children].map(child=>child.getBoundingClientRect().width);
      const next=visibleModuleLinks(widths,available,items.findIndex(item=>item.id===active)).map(index=>items[index].id);
      const focused=document.activeElement as HTMLElement|null;
      if(host.contains(focused)&&((focused?.dataset.moduleLink&&!next.includes(focused.dataset.moduleLink))||(focused?.classList.contains('r-more-actions-trigger')&&next.length===items.length)))returnFocus.current=true;
      setShown(current=>current.join('|')===next.join('|')?current:next);
    }
    fit();const observer=new ResizeObserver(fit);observer.observe(host);observer.observe(labels);
    return()=>observer.disconnect();
  },[signature,active]);
  useLayoutEffect(()=>{
    if(!returnFocus.current)return;returnFocus.current=false;
    const host=nav.current;
    (host?.querySelector<HTMLButtonElement>('.r-more-actions-trigger')||host?.querySelector<HTMLButtonElement>('[aria-current=page]'))?.focus({preventScroll:true});
  },[shown]);
  const hidden=items.filter(item=>!shown.includes(item.id));
  return <nav ref={nav} className="r-section-tabs r-module-navigation" aria-label={label}>
    {items.filter(item=>shown.includes(item.id)).map(item=><Button key={item.id} className="r-module-link" title={item.label} data-module-link={item.id} aria-current={item.id===active?'page':undefined} onClick={()=>navigate(item.id)}><span>{item.label}</span></Button>)}
    <MoreActions label={label.replace(/页面$/,'')+'更多页面'} actions={hidden.map(item=>({id:item.id,label:item.label,onSelect:()=>navigate(item.id)}))}/>
    <div ref={measure} className="r-module-measure" aria-hidden="true">{items.map(item=><button key={item.id} type="button" className="ui-button" tabIndex={-1}>{item.label}</button>)}</div>
  </nav>;
}
