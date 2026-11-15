import {useEffect,useRef,useState} from 'react';
import {api,errorText} from './api';
import {Badge,Button,Empty,ErrorNotice,Panel} from './ui';
import {listingActionLabels} from './listing-actions';
import type {ListingTarget} from './listing-observation';

interface Directory {items:{id:string;target:ListingTarget;name:string;sku:string;created_at:string;status:string;current:boolean;approval_fresh:boolean;requires_readback:boolean}[];total:number;offset:number;next_offset:number|null;configured:boolean;status:string}

export function ListingActionDirectory({demo,active,onListing}:{demo:boolean;active:boolean;onListing:(target:ListingTarget,actionId?:string)=>void}){
  const [data,setData]=useState<Directory|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const epoch=useRef(0);
  async function load(offset=0){const sequence=++epoch.current;setBusy(true);setError('');try{const value=await api<Directory>('commerce_listing_action_directory',{demo,offset,limit:5});if(sequence!==epoch.current)return;if(value.items.length===0&&offset>0&&value.total>0){void load();return;}setData(value);}catch(e){if(sequence===epoch.current){setData(null);setError(errorText(e));}}finally{if(sequence===epoch.current)setBusy(false);}}
  useEffect(()=>{setData(null);setError('');if(active)void load();return()=>{epoch.current++;};},[active,demo]);
  return <section aria-label="图片动作恢复"><Panel title="图片动作" action={<Button disabled={busy} onClick={()=>void load(data?.offset||0)}>{busy?'读取中…':'刷新图片动作'}</Button>}>
    <ErrorNotice>{error}</ErrorNotice>
    {data?.items.length?<ul className="r-operation-list">{data.items.map(row=><li key={row.id} data-image-action={row.id}><div><strong>{row.name}</strong><p>{row.sku} · {new Date(row.created_at).toLocaleString()}</p><Badge>{listingActionLabels[row.status]||row.status}</Badge>{row.requires_readback?<p>继续原动作核对结果，勿重复提交。</p>:!row.current?<p>原来源或连接已变化，旧动作不能提交。</p>:row.status==='approved'&&!row.approval_fresh?<p>原核对已超过执行有效期，需重新核对。</p>:null}</div><Button onClick={()=>onListing(row.target,row.id)}>继续准确图片动作</Button></li>)}</ul>:<Empty>{busy?'正在读取图片动作…':error?'图片动作未完整读回，请刷新重试。':data?.status==='demo_no_shop_read'?'示例范围不读取真实店铺图片动作。':data?.status==='not_configured'?'尚未配置店铺，无法读取图片动作。':data?'当前店铺尚无图片动作。':'图片动作尚未读回。'}</Empty>}
    {data&&data.total>5&&<div className="r-actions"><Button disabled={busy||!data.offset} onClick={()=>void load(Math.max(0,data.offset-5))}>上一页图片动作</Button><span>{data.offset+1}–{data.offset+data.items.length} / {data.total}</span><Button disabled={busy||data.next_offset===null} onClick={()=>void load(data.next_offset!)}>下一页图片动作</Button></div>}
  </Panel></section>;
}
