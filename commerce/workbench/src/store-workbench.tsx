import { useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import { readAttentionTarget, type AttentionPage } from './attention-state';
import type { CaseItem, OpsAlert, LiveStatus } from './types';
import { Followups } from './followups';
import { Badge, Button, Empty, ErrorNotice, Panel } from './ui';
import './operations-workbench.css';
import {observationLabels,type ListingTarget} from './listing-observation';
import {releaseStatusLabels} from './listing-release';
import {StoreScopeEditor,storeScopeLabel,storeScopeError,type StoreScopeCatalog} from './store-scopes';
import {ListingActionDirectory} from './listing-action-directory';
import {OperatingGuide} from './operating-guide';
import {OperatingAlertEvidence} from './operating-alert-evidence';
import {alertEvidenceKey,selectedAlertEvidence,type AlertEvidence} from './operating-alert-state';

interface Channel {id:string;name:string;readiness:string;delivery_verified:boolean;binding:{selected:boolean}}
interface Workbench {
  store_scope?:string;store_scopes?:StoreScopeCatalog;demo:boolean;products:CaseItem[];imported_alerts:{alerts:AlertEvidence[]}|null;live_alerts:{alerts:AlertEvidence[]}|null;
  attention:AttentionPage|null;live:(LiveStatus&{notifications_enabled:boolean;feishu_received_confirmed:boolean})|null;
  channels:{channels:Channel[]}|null;platforms:{stores:{store_id:string;label:string;platform:string;market:string;configured:boolean;scope_reviewed:boolean;snapshots:Record<string,{fresh:boolean;record_count:number|null}>}[]}|null;
  unavailable:string[];access:{remote_access_enabled:boolean;platform_writes_enabled:boolean;deployment:string};
}
const sourceNames:Record<string,string>={products:'商品工作项',imported_alerts:'导入提醒',live_alerts:'店铺提醒',live:'Ozon状态',attention:'模型与研究待办',channels:'消息渠道',platforms:'平台接入'};
const readiness:Record<string,string>={account_type_required:'待选择账号类型',not_selected:'未启用',unsupported_account_type:'账号类型未支持',unknown:'状态未知',adapter_missing:'适配未就绪',authorization_required:'待授权',gateway_not_running:'渠道未运行',scope_and_delivery_not_verified:'待核对范围与送达'};
export function StoreWorkbench({demo,active,navigate,onThread,onResearch,onListing,storeScope='all',onStoreScope}:{storeScope?:string;onStoreScope?:(value:string)=>void;demo:boolean;active:boolean;navigate:(tab:string,id?:string)=>void;onThread:(id:string)=>void;onResearch:(id:string)=>void;onListing:(target:ListingTarget,actionId?:string)=>void}) {
  const [data,setData]=useState<Workbench|null>(null),[busy,setBusy]=useState(true),[error,setError]=useState(''),[query,setQuery]=useState(''),[filter,setFilter]=useState('all');
  const [catalog,setCatalog]=useState<StoreScopeCatalog|null>(null);
  function chooseScope(value:string){epoch.current++;setData(null);setDirectory(null);onStoreScope?.(value);}
  const [working,setWorking]=useState(''),[followup,setFollowup]=useState<string|null>(null),[notice,setNotice]=useState('');
  const [directory,setDirectory]=useState<{items:{target:ListingTarget;name:string;sku:string;revision:number;stale:boolean;missing:string[];observation_status:string;review_status:string;release?:{submission_status?:string;request_id:string;current:boolean;decision:string;read_status:string;observation_status:string|null}|null}[];total:number;offset:number;next_offset:number|null}|null>(null),[directoryError,setDirectoryError]=useState(''),[listingQuery,setListingQuery]=useState(''),[directoryBusy,setDirectoryBusy]=useState(false);
  const [guideKey,setGuideKey]=useState('');
  const [evidenceKey,setEvidenceKey]=useState('');
  const directoryRequest=useRef(0);
  const epoch=useRef(0);
  async function load(){const generation=++epoch.current;setEvidenceKey('');setBusy(true);setError('');
    try{const result=await api<Workbench>('commerce_store_workbench',{demo,...(storeScope!=='all'?{store_scope:storeScope}:{})});if(generation===epoch.current){setData(result);if(result.store_scopes)setCatalog(result.store_scopes);return generation;}return null;}
    catch(e){if(generation===epoch.current){setData(null);setError(storeScopeError(e));}return null;}
    finally{if(generation===epoch.current)setBusy(false);}
  }
  async function loadDirectory(offset=0,generation=epoch.current){if(generation!==epoch.current)return;const request=++directoryRequest.current;setDirectoryError('');setDirectoryBusy(true);try{const value=await api<NonNullable<typeof directory>>('commerce_listing_directory',{demo,offset,limit:25,...(storeScope!=='all'?{store_scope:storeScope}:{})});if(generation===epoch.current&&request===directoryRequest.current){if(value.items.length===0&&value.offset>0&&value.total>0){void loadDirectory(0,generation);return;}setDirectory(value);}}catch(e){if(generation===epoch.current&&request===directoryRequest.current){setDirectory(null);setDirectoryError(errorText(e));}}finally{if(generation===epoch.current&&request===directoryRequest.current)setDirectoryBusy(false);}}
  useEffect(()=>{if(active){setWorking('');setData(null);setDirectory(null);setNotice('');void load().then(generation=>{if(generation!==null)return loadDirectory(0,generation);});}return ()=>{epoch.current++;};},[active,demo,storeScope]);
  async function readCatalog(){const value=await api<StoreScopeCatalog>('commerce_store_scope_list',{demo});setCatalog(value);}
  function linkedCatalog(value:StoreScopeCatalog){setCatalog(value);if(storeScope!=='all'&&storeScope!=='unassigned'&&value.mapping[storeScope]&&value.mapping[storeScope]!==storeScope)chooseScope(value.mapping[storeScope]);else{void load().then(generation=>{if(generation!==null)return loadDirectory(0,generation);});}}
  async function openAttention(id:string){const generation=epoch.current;setWorking(id);setError('');
    try{const target=await readAttentionTarget(api,id);if(generation!==epoch.current)return;
      if(target.type==='thread')onThread(target.id);else if(target.type==='research')onResearch(target.id);else if(target.type==='followup')setFollowup(target.id);else navigate('old:agent',target.id);}
    catch(e){if(generation===epoch.current)setError(errorText(e));}finally{if(generation===epoch.current)setWorking('');}
  }
  async function acknowledge(alert:OpsAlert,live:boolean){const generation=epoch.current;setWorking(alert.id);setError('');
    try{await api(live?'commerce_live_ack':'commerce_ops_ack',{alert_id:alert.id,...(live?{}:{demo})});if(generation!==epoch.current)return;setNotice('已记录查看，原业务仍需继续处理。');await load();}
    catch(e){if(generation===epoch.current)setError(errorText(e));}finally{if(generation===epoch.current)setWorking('');}
  }
  const alerts=[...(data?.live_alerts?.alerts||[]).map(alert=>({alert,live:true})),...(data?.imported_alerts?.alerts||[]).map(alert=>({alert,live:false}))]
    .filter(({alert})=>alert.status!=='resolved'&&(filter==='all'||(filter==='stale'?alert.status==='suspended':alert.status==='active'))&&[alert.title,alert.sku,alert.store_id].join(' ').toLowerCase().includes(query.toLowerCase()));
  const visiblePlans=(directory?.items||[]).filter(r=>[r.name,r.sku,r.target.platform,r.target.store_ref,r.target.market].join(' ').toLowerCase().includes(listingQuery.toLowerCase()));
  const evidence=active&&!busy?selectedAlertEvidence(alerts,evidenceKey,demo,storeScope):null;
  const products=(data?.products||[]).filter(p=>[p.name,p.platform,p.market].join(' ').toLowerCase().includes(query.toLowerCase()));
  const hasAside=storeScope==='all'||!!data?.live||!!data?.platforms?.stores.length;
  return <div className="r-page r-store-workbench" data-ai-page="store-ops" data-ai-context={JSON.stringify({filters:{scope:storeScope},...(catalog&&data?{source_refs:{store_scope:catalog.sha256}}:{})})}><div className="r-page-heading"><h1>日常运营{demo&&<small className="r-inline-source">示例数据</small>}</h1><Button disabled={busy} icon="refresh" onClick={()=>void load().then(generation=>{if(generation!==null)return loadDirectory(directory?.offset||0,generation);})}>刷新当前资料</Button></div>
    <ErrorNotice>{error}</ErrorNotice>{data?.unavailable.length? <ErrorNotice>部分资料未读到：{data.unavailable.map(k=>sourceNames[k]||k).join('、')}。当前列表不完整。</ErrorNotice>:null}

    <div className="r-list-filters"><label className="ui-field">店铺视图<select value={storeScope} disabled={busy&&!catalog} onChange={e=>chooseScope(e.target.value)}><option value="all">全部店铺与未关联资料</option><option value="unassigned">未关联店铺</option>{catalog&&storeScope!=='all'&&storeScope!=='unassigned'&&!catalog.stores.some(item=>item.id===storeScope)&&<option value={storeScope}>原店铺身份已变化，请重新选择</option>}{catalog?.stores.map(item=><option key={item.id} value={item.id}>{storeScopeLabel(item,catalog.sources.find(source=>source.id===item.id)?.kind)}</option>)}</select></label><label className="ui-field">查找商品或提醒<input type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="商品、SKU或店铺"/></label><label className="ui-field">经营提醒状态<select value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">全部未解决</option><option value="active">待查看</option><option value="stale">资料已陈旧</option></select></label></div>
    {catalog&&<StoreScopeEditor key={`${demo}:${active}:${storeScope}`} catalog={catalog} refresh={readCatalog} changed={linkedCatalog}/>}
    {catalog&&!catalog.complete&&<ErrorNotice>部分店铺来源未读回：{catalog.unavailable.join('、')}。当前范围不完整。</ErrorNotice>}
    <p role="status">{busy?'正在读取运营资料…':notice}</p>
    {!data?(!busy&&!error&&<Empty>运营资料尚未读回。</Empty>):<>
      <div className="r-store-columns" style={!hasAside?{gridTemplateColumns:'minmax(0,1fr)'}:undefined}><div><Panel title="经营提醒" action={<Button onClick={()=>navigate('alerts')}>全部提醒</Button>}>
        {alerts.length?<ul className="r-operation-list">{alerts.map(({alert,live})=><li key={`${live}:${alert.id}`}><div><strong>{alert.title}</strong><p>{[alert.store_id,alert.sku,alert.detail].filter(Boolean).join(' · ')}</p><Badge>{live?'店铺只读快照':'导入资料'} · {alert.status==='suspended'?'已挂起':alert.status==='acknowledged'?'已查看':'待查看'}</Badge></div><div className="r-actions"><Button onClick={()=>setEvidenceKey(alertEvidenceKey({alert,live},demo,storeScope))}>核对原记录</Button>{alert.status==='active'&&<Button disabled={!!working} onClick={()=>void acknowledge(alert,live)}>标为已阅</Button>}</div></li>)}</ul>:<Empty>{data.unavailable.some(k=>['imported_alerts','live_alerts'].includes(k))?'提醒尚未完整读取。':'当前已读范围没有匹配提醒。'}</Empty>}
      </Panel>
      {!demo&&<ListingActionDirectory storeScope={storeScope} demo={demo} active={active} onListing={onListing}/>}
      <Panel title="已保存上架方案" action={<Button disabled={directoryBusy} onClick={()=>void loadDirectory(directory?.offset||0)}>{directoryBusy?'读取中…':'刷新方案目录'}</Button>}>
        <ErrorNotice>{directoryError}</ErrorNotice><label className="ui-field">查找本页方案<input type="search" value={listingQuery} onChange={e=>setListingQuery(e.target.value)} placeholder="商品、SKU、平台或店铺"/></label>
        {visiblePlans.length?<ul className="r-operation-list">{visiblePlans.map(r=><li key={JSON.stringify(r.target)}><div><strong>{r.name}</strong><p>{r.target.platform} · {r.target.store_ref} · {r.target.market} · 修订 {r.revision}</p><Badge>{r.stale?'商品资料已变化':r.review_status==='reviewed'?'当前版本已核对':r.review_status==='needs_changes'?'待补充或修改':r.review_status==='outdated'?'旧核对已失效':'待核对'}</Badge><p>{observationLabels[r.observation_status]||r.observation_status} · {r.missing.length} 项发布前检查未关闭</p>{r.release&&<p>{r.release.current?'当前发布申请':'旧版发布申请'} · {releaseStatusLabels[r.release.decision]||r.release.decision} · {releaseStatusLabels[r.release.submission_status||r.release.observation_status||r.release.read_status]||'回执待核对'}</p>}</div><div className="r-actions"><Button onClick={()=>onListing(r.target)}>继续此店铺方案</Button><Button aria-expanded={guideKey===JSON.stringify(r.target)} onClick={()=>setGuideKey(guideKey===JSON.stringify(r.target)?'':JSON.stringify(r.target))}>查看日常经营缺项</Button></div></li>)}</ul>:<Empty>{directoryBusy?'正在读取方案目录…':directory?.items.length?'本页没有匹配方案。':directory?'当前模式尚无已保存方案。':'方案目录尚未读回。'}</Empty>}
        {directory&&directory.total>25&&<div className="r-actions"><Button disabled={directoryBusy||!directory.offset} onClick={()=>void loadDirectory(Math.max(0,directory.offset-25))}>上一页方案</Button><span>{directory.offset+1}–{directory.offset+directory.items.length} / {directory.total}</span><Button disabled={directoryBusy||directory.next_offset===null} onClick={()=>void loadDirectory(directory.next_offset!)}>下一页方案</Button></div>}
      </Panel>
      {visiblePlans.filter(r=>JSON.stringify(r.target)===guideKey).map(r=><OperatingGuide key={guideKey} target={r.target} revision={r.revision} version={JSON.stringify([r.revision,r.stale,r.release])} active={active&&!directoryBusy} goal="operate" onListing={onListing} onProduct={id=>navigate('workspace',id)}/>)}
      <Panel title="商品与上架" action={<Button onClick={()=>navigate('workspace')}>商品工作区</Button>}>
        {products.length?<ul className="r-operation-list">{products.map(p=><li key={p.id}><div><strong>{p.name}</strong><p>{p.platform} · {p.market} · {p.candidate?'研究候选':'已有商品工作项'} · #{p.id.slice(0,8)}</p></div><div className="r-actions"><Button onClick={()=>navigate('workspace',p.id)}>继续商品</Button><Button onClick={()=>navigate('listing',p.id)}>上架准备</Button></div></li>)}</ul>:<Empty>当前范围没有匹配商品。</Empty>}
      </Panel>
      <p className="r-footnote">{storeScope!=='all'?'跨业务待办':data.attention?`${data.attention.items.length}${data.attention.has_more?'+':''} 项跨业务待办${data.attention.complete?'':' · 资料未完整读回'}`:'跨业务待办尚未读回'} <Button onClick={()=>navigate('overview')}>运营台统一处理</Button></p>
      </div>{hasAside&&<aside aria-label="平台与通知接入状态"><Panel title="平台资料" action={<Button onClick={()=>navigate('platforms')}>管理平台数据</Button>}>
        {demo?<p>示例范围不混入真实店铺经营快照。</p>:<>{(storeScope==='all'||data.live)&&<><p>Ozon：{data.live?(data.live.configured?'已配置 · 需在原经营页核对范围与新鲜度':'待配置'):'状态未读回'}</p><div className="r-actions"><Button onClick={()=>navigate('live')}>Ozon 经营资料</Button><Button onClick={()=>navigate('orders')}>订单管理</Button><Button onClick={()=>navigate('restock')}>补货测算</Button></div></>}
          {data.platforms?.stores.length?<ul className="r-operation-list">{data.platforms.stores.map(s=><li key={s.store_id}><div><strong>{s.label}</strong><p>{s.platform} · {s.market}</p><Badge>{!s.configured?'待配置':!s.scope_reviewed?'授权范围待核对':Object.values(s.snapshots).every(r=>r.fresh)?'当前只读快照':'快照待更新或读取'}</Badge><p>{Object.entries(s.snapshots).map(([key,r])=>`${({products:'商品',stock:'库存',orders:'订单'}as Record<string,string>)[key]||key}：${r.record_count??'未读取'}${r.fresh?'':' · 非当前有效'}`).join('；')}</p></div></li>)}</ul>:storeScope==='all'?<p>尚无其它平台接入记录。</p>:null}</>}
      </Panel>{storeScope==='all'&&<Panel title="手机与通知" action={<Button onClick={()=>navigate('connections')}>管理接入</Button>}>
        <dl className="r-notification-state"><dt>手机工作区</dt><dd>与电脑共用当前业务资料与处理记录</dd><dt>远程访问</dt><dd>{data.access.remote_access_enabled?'按已配置入口访问':'未启用 · 当前服务仅接受本机访问'}</dd><dt>平台经营写入</dt><dd>{data.access.platform_writes_enabled?'按授权范围处理':'尚未启用'}</dd><dt>Ozon单向通知</dt><dd>{data.live?(data.live.notifications_enabled?'已开启 · ':'未开启 · ')+(data.live.feishu_received_confirmed?'已有人工收件确认':'手机收件待核对'):demo?'示例范围不查询真实经营通知':'状态未读到'}</dd></dl>
        {data.channels?.channels.length?<ul className="r-operation-list">{data.channels.channels.map(c=><li key={c.id}><span>{c.name}</span><Badge>{readiness[c.readiness]||'待核对'}</Badge></li>)}</ul>:<p>渠道状态尚未读回。</p>}
        <p>通知送达与业务完成分别记录。</p>
      </Panel>}</aside>}</div>
    </>}
    {evidence&&<OperatingAlertEvidence row={evidence} close={()=>setEvidenceKey('')} refresh={()=>void load()} onOriginal={()=>{setEvidenceKey('');navigate('alerts');}}/>}
    {followup!==null&&<Followups demo={demo} followupId={followup} close={()=>setFollowup(null)} changed={()=>void load()} openOriginal={action=>{setFollowup(null);if(action.type==='thread')onThread(action.id);else if(action.type==='research')onResearch(action.id);else navigate(action.type==='tasks'?'tasks':'old:agent',action.id);}}/>}
  </div>;
}
