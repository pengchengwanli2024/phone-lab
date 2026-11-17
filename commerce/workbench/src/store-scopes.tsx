import {useEffect,useRef,useState} from 'react';
import {api,errorText,newKey} from './api';
import {Button,ErrorNotice} from './ui';
export interface StoreSource {id:string;kind:string;label:string;platform:string;market:string;sha256:string;revision:number;linked_to:string;link_current:boolean;linked:boolean}
export interface StoreScopeCatalog {demo:boolean;sha256:string;complete:boolean;unavailable:string[];stores:{id:string;label:string;platform:string;market:string;source_ids:string[]}[];sources:StoreSource[];mapping:Record<string,string>}
const kinds:Record<string,string>={live:'Ozon快照',platform:'平台接入',manual:'人工资料',listing:'上架目标'};
export const storeScopeLabel=(item:{label:string;platform:string;market:string;id:string},kind?:string)=>`${item.label} · ${item.platform} · ${item.market}${kind?' · '+(kinds[kind]||kind):''} · ${item.id.slice(-6)}`;
const errors:Record<string,string>={store_scope_not_found:'所选店铺身份已变化，请核对来源后重新选择。',store_scope_catalog_changed:'来源或关联已更新，请读取当前关联后核对。',store_scope_revision_conflict:'关联已被其它窗口修改，本次选择已保留。',store_scope_boundary_mismatch:'只能关联同平台、同市场的来源。',store_scope_link_chain_forbidden:'该来源仍有其它资料依赖，请先将这些来源分开。',store_scope_idempotency_conflict:'原请求内容已变化，请读取当前关联核对。'};
export const storeScopeError=(failure:unknown)=>errors[failure instanceof Error?failure.message:'']||errorText(failure);
export function StoreScopeEditor({catalog,refresh,changed}:{catalog:StoreScopeCatalog;refresh:()=>Promise<void>;changed:(value:StoreScopeCatalog)=>void}){
  const [sourceId,setSource]=useState(''),[target,setTarget]=useState(''),[checked,setChecked]=useState(false),[busy,setBusy]=useState(false),[unknown,setUnknown]=useState(false),[error,setError]=useState('');
  const pending=useRef<{fingerprint:string;key:string}|null>(null),epoch=useRef(0);
  useEffect(()=>{setChecked(false);setUnknown(false);setBusy(false);return()=>{epoch.current++;};},[catalog.sha256]);
  const source=catalog.sources.find(item=>item.id===sourceId);
  function choose(id:string){setSource(id);setTarget('');setChecked(false);setError('');}
  async function save(){if(!source||!target||!checked||busy||unknown)return;const revision=++epoch.current;setBusy(true);setError('');
    const args={demo:catalog.demo,source_id:source.id,store_scope:target,expected_catalog_sha256:catalog.sha256,expected_revision:source.revision,confirmed:true};
    const fingerprint=JSON.stringify(args);if(pending.current?.fingerprint!==fingerprint)pending.current={fingerprint,key:newKey()};
    try{const result=await api<StoreScopeCatalog>('commerce_store_scope_link',{...args,idempotency_key:pending.current.key});if(revision===epoch.current){pending.current=null;setChecked(false);changed(result);}}
    catch(failure){if(revision===epoch.current){setError(storeScopeError(failure));if(failure instanceof TypeError||failure instanceof Error&&failure.message==='request_outcome_unknown')setUnknown(true);}}
    finally{if(revision===epoch.current)setBusy(false);}
  }
  async function read(){if(busy)return;setBusy(true);try{await refresh();setUnknown(false);setChecked(false);setError('');}catch(failure){setError(storeScopeError(failure));}finally{setBusy(false);}}
  return <details className="r-store-scope-editor"><summary>关联同店铺来源</summary><ErrorNotice>{error}</ErrorNotice>
    <p className="r-footnote">仅将同一实际店铺的不同来源或别名归入同一视图，平台和市场须一致。原记录、授权和执行范围各自保留。</p>
    <div className="r-list-filters"><label className="ui-field">资料来源<select disabled={busy||unknown} value={sourceId} onChange={e=>choose(e.target.value)}><option value="">请选择来源</option>{catalog.sources.map(item=><option key={item.id} value={item.id}>{storeScopeLabel(item,item.kind)}{item.link_current?'':' · 关联待核对'}</option>)}</select></label>
    <label className="ui-field">归入店铺视图<select disabled={!source||busy||unknown} value={target} onChange={e=>{setTarget(e.target.value);setChecked(false);}}><option value="">请选择目标</option>{source&&<option value={source.id}>将此来源单独显示</option>}{catalog.stores.filter(item=>item.id!==sourceId&&item.platform===source?.platform&&item.market===source?.market).map(item=><option key={item.id} value={item.id}>{storeScopeLabel(item)}</option>)}</select></label></div>
    {source&&<p className="r-footnote">当前关联：{catalog.stores.find(item=>item.id===catalog.mapping[source.id])?.label||'待核对'} · 修订 {source.revision}{!source.link_current?' · 原连接已变化，旧关联暂停':''}</p>}
    <label className="adoption-check"><input type="checkbox" checked={checked} disabled={busy||unknown||!source||!target} onChange={e=>setChecked(e.target.checked)}/>已核对来源和目标属于同一店铺</label>
    {unknown&&<p role="status">保存结果尚未确认，请先读取当前关联核对。</p>}
    <div className="r-actions"><Button disabled={busy||!checked||!target||unknown} onClick={()=>void save()}>保存关联</Button><Button disabled={busy} onClick={()=>void read()}>读取当前关联</Button></div>
  </details>;
}
