import { useEffect, useRef, useState, type RefObject } from 'react';
import '../../ui/page-context.js';
import type { BusinessContext, PageContext } from './types';

export function useAssistantPage(page: string, context: BusinessContext, root: RefObject<HTMLElement | null>, frame: PageContext | null) {
  const latest=useRef({page,context,frame});latest.current={page,context,frame};
  const [snapshot,setSnapshot]=useState<PageContext>({page,demo:!!context.demo});
  const controller=useRef<ReturnType<Window['CommercePageContext']['create']>|null>(null);
  useEffect(()=>{
    controller.current=window.CommercePageContext.create({root:()=>root.current,getBase:()=>{
      const value=latest.current,scope=value.context;
      return {...value.frame,page:value.page,demo:value.frame?.demo??!!scope.demo,...(scope.entity&&!value.frame?.entity?{entity:scope.entity}:{}),filters:{...(scope.platform?{platform:scope.platform}:{}),...(scope.store_id?{store_id:scope.store_id}:{}),...(scope.market?{market:scope.market}:{}),...value.frame?.filters}};
    },onChange:value=>{if(value)setSnapshot(value)}});
    return()=>controller.current?.dispose();
  },[]);
  useEffect(()=>{controller.current?.reset()},[page]);
  useEffect(()=>{controller.current?.changed()},[page,context,frame]);
  return snapshot;
}
