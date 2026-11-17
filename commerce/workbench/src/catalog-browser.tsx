import { useEffect, useRef } from 'react';
import './product-label';
import '../../web/catalog-ui.js';
import '../../web/catalog-ui.css';
import {api} from './api';

export interface CatalogItem {
  id:string;name:string;kind:'candidate'|'inventory';synthetic:boolean;market?:string;platform?:string;
}
interface CatalogController {view:()=>string;enter:()=>Promise<void>;open:(id:string)=>Promise<void>;dispose:()=>void}
interface CatalogOptions {
  api:(tool:string,args?:object)=>Promise<unknown>;repaint:()=>void;onSelect?:(id:string)=>void;
  fixedKind?:'candidate';getFilters?:()=>{synthetic:boolean;market:string};onItems?:(items:CatalogItem[])=>void;
  onQuery?:(query:string)=>void;directSelect?:boolean;showStoreControls?:boolean;showHeading?:boolean;
}
declare global {interface Window {CommerceCatalog:(options:CatalogOptions)=>CatalogController}}
interface Props {
  active:boolean;synthetic:boolean;market:string;refreshKey:number;
  onSelect:(id:string)=>void;onItems:(items:CatalogItem[])=>void;onQuery:(query:string)=>void;
}
/** Candidate browsing uses the same scoped catalog and controls as product selection. */
export function CatalogBrowser(props:Props){
  const host=useRef<HTMLDivElement>(null),controller=useRef<CatalogController|null>(null),current=useRef(props);current.current=props;
  useEffect(()=>{
    let alive=true;
    const paint=()=>{if(alive&&host.current&&controller.current)host.current.innerHTML=controller.current.view()};
    controller.current=window.CommerceCatalog({api,repaint:paint,fixedKind:'candidate',directSelect:true,showStoreControls:false,showHeading:false,
      getFilters:()=>({synthetic:current.current.synthetic,market:current.current.market}),
      onSelect:id=>current.current.onSelect(id),onItems:items=>current.current.onItems(items),onQuery:query=>current.current.onQuery(query)});
    paint();
    return()=>{alive=false;controller.current?.dispose();controller.current=null;};
  },[]);
  useEffect(()=>{if(props.active)void controller.current?.enter();},[props.active,props.synthetic,props.market,props.refreshKey]);
  return <div ref={host} className="r-shared-catalog"/>;
}
