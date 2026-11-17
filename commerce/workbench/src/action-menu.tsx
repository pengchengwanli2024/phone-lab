import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { Button, Icon } from './ui';
import './action-menu.css';

export interface MenuAction {id:string;label:string;onSelect:()=>void;disabled?:boolean;danger?:boolean}

/** A portal keeps row actions reachable inside horizontally scrolling tables. */
export function MoreActions({actions,label='更多操作'}:{actions:MenuAction[];label?:string}) {
  const [open,setOpen]=useState(false),[position,setPosition]=useState<CSSProperties>({visibility:'hidden'});
  const trigger=useRef<HTMLButtonElement>(null),menu=useRef<HTMLDivElement>(null),id=useId();
  function close(focus=false){setOpen(false);if(focus)trigger.current?.focus({preventScroll:true})}
  useLayoutEffect(()=>{
    if(!open)return;
    function place(){const anchor=trigger.current?.getBoundingClientRect(),panel=menu.current;if(!anchor||!panel)return;const width=Math.min(240,window.innerWidth-24),height=Math.min(panel.scrollHeight,window.innerHeight-24);setPosition({width,left:Math.max(12,Math.min(anchor.right-width,window.innerWidth-width-12)),top:anchor.bottom+8+height<=window.innerHeight-12?anchor.bottom+8:Math.max(12,anchor.top-height-8),maxHeight:window.innerHeight-24,visibility:'visible'})}
    place();
    window.addEventListener('resize',place);return()=>window.removeEventListener('resize',place);
  },[open]);
  useLayoutEffect(()=>{if(open&&position.visibility==='visible')menu.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus({preventScroll:true})},[open,position.visibility]);
  useEffect(()=>{
    if(!open)return;
    const outside=(event:Event)=>{const target=event.target as Node;if(!menu.current?.contains(target)&&!trigger.current?.contains(target))close()};
    const scroll=(event:Event)=>{if(!menu.current?.contains(event.target as Node))close()};
    document.addEventListener('pointerdown',outside);document.addEventListener('focusin',outside);document.addEventListener('scroll',scroll,true);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',outside);document.removeEventListener('scroll',scroll,true)};
  },[open]);
  if(!actions.length)return null;
  return <><button ref={trigger} type="button" className="ui-button r-more-actions-trigger" aria-label={label} title={label} aria-haspopup="menu" aria-expanded={open} aria-controls={id} onClick={()=>{setPosition({visibility:'hidden'});setOpen(value=>!value)}}><Icon name="more"/></button>{open&&createPortal(<div ref={menu} id={id} role="menu" aria-label={label} className="r-action-menu" style={position} onKeyDown={event=>{
    if(event.key==='Escape'){event.preventDefault();close(true);return}
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const items=[...menu.current!.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')],index=items.indexOf(document.activeElement as HTMLButtonElement);items[event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:items.length-1))%items.length]?.focus()}
  }}>{actions.map(action=><Button key={action.id} role="menuitem" disabled={action.disabled} className={action.danger?'ui-danger':''} onClick={()=>{close(true);action.onSelect()}}>{action.label}</Button>)}</div>,document.body)}</>;
}
