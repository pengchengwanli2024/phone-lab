import {useEffect,useRef,useState} from 'react';
import {api,errorText} from './api';
import {Badge,Button,Empty,ErrorNotice,Panel} from './ui';
import type {ListingTarget} from './listing-observation';
import {PublicationFields,type Publication} from './listing-publication-fields';

export type OzonAttribute={id:number;values:{dictionary_value_id:number;value:string}[];source_ref:string};
export type OzonPayload={type_id:number;attributes:OzonAttribute[];publication?:Publication};
type Category={category_id:number;type_id:number;label:string;path:string;disabled:boolean};
type Attribute={id:number;name:string;description:string;type:string;is_required:boolean;is_collection:boolean;dictionary_id:number;max_value_count:number;complex_id:number};
type Metadata={sha256:string|null;fresh:boolean;observed_at:string|null};
interface SchemaView {
  categories:Metadata&{items:Category[];total:number;offset:number;next_offset:number|null};
  attributes:Metadata&{items:Attribute[]};
  values:Metadata&{items:{id:number;value:string}[];has_next:boolean;next_cursor:number|null};
  validation:{status:string;issues:{attribute_id:number;code:string;name:string}[]};
  refresh:{id:string;status:string;resource:string;error:string|null}|null;
  synthetic:boolean;
}
const labels:Record<string,string>={scope_not_supported:'先关联 Ozon 俄罗斯店铺',missing_connection:'先配置原 Ozon 只读接入',missing_category_tree:'尚未读取类目',invalid_schema:'平台资料完整性校验失败，需重新读取',stale_schema:'类目或属性资料已过期',missing_type:'请选择准确的类目与商品类型',invalid_type:'所选类目与类型不在当前目录',disabled_type:'平台已停用该类目或类型',missing_attributes:'尚未读取对应属性',incomplete:'属性仍有待补充项',limited_check_passed:'类目与简单属性结构检查通过'};
const issues:Record<string,string>={required:'必填',source_required:'缺少产品资料依据',complex_not_assessed:'复合属性仍需专门核对',too_many_values:'超出允许值数量',dictionary_value_not_current:'字典值或标签尚未由当前资料确认',unexpected_dictionary_id:'该属性不使用字典 ID',empty_value:'值为空',invalid_integer:'需要整数',invalid_number:'需要有效数值',invalid_boolean:'需要 true 或 false',type_not_assessed:'此字段类型尚未适配',unknown_attribute:'当前类型没有此属性'};
function failure(e:unknown){const c=e instanceof Error?e.message:'';return ({listing_schema_refresh_tree_first:'先读取当前类目目录，再读取所选类型属性。',listing_schema_dictionary_unavailable:'先读取对应属性，并确认它使用字典。',listing_schema_demo_no_network:'示例模式只使用合成资料，不调用实际店铺。',listing_schema_refresh_busy:'已有资料读取在进行，等待当前回执。',listing_schema_integrity_failed:'已留存资料校验失败，请重新读取。',listing_schema_connection_changed:'店铺连接已变化，本次结果未采用。',ozon_auth_or_permission:'当前接入无此资料的读取权限。',ozon_network_error:'Ozon 资料读取连接失败，已保留旧资料。',ozon_rate_limited:'Ozon 已限流，请稍后再读取。'}as Record<string,string>)[c]||errorText(e);}

export function ListingSchemaPanel({target,payload,active,previewSha,dirty,busy,onChange,onSave,publicationSupported=false}:{
  target:ListingTarget;payload:{fields:{category_id:string;description?:string};ozon?:OzonPayload};active:boolean;previewSha:string;dirty:boolean;busy:boolean;
  publicationSupported?:boolean;onChange:(category:string,value:OzonPayload)=>void;onSave:()=>void;
}){
  const [data,setData]=useState<SchemaView|null>(null),[error,setError]=useState(''),[reading,setReading]=useState(false),[query,setQuery]=useState(''),[selected,setSelected]=useState(''),[optional,setOptional]=useState(false);
  const [attributeId,setAttributeId]=useState(0),[cursor,setCursor]=useState(0),[poll,setPoll]=useState(false);
  const epoch=useRef(0),writing=useRef(false),mounted=useRef(true);
  const identity=JSON.stringify(target),context=identity+':'+payload.fields.category_id+':'+(payload.ozon?.type_id||0),draft=JSON.stringify(payload);
  const categoryId=/^[1-9][0-9]{0,15}$/.test(payload.fields.category_id)?Number(payload.fields.category_id):0;
  const typ=payload.ozon?.type_id||0;
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;epoch.current++;};},[]);
  useEffect(()=>{epoch.current++;setData(null);setSelected('');setQuery('');setAttributeId(0);setCursor(0);setPoll(false);},[context]);
  async function load(offset=0,attribute=attributeId,page=cursor,search=query){const current=++epoch.current;setReading(true);
    try{const result=await api<SchemaView>('commerce_listing_schema_get',{...target,payload,query:search,offset,category_id:categoryId,type_id:typ,attribute_id:attribute,last_value_id:page});if(current!==epoch.current||!mounted.current)return;setData(result);setPoll(result.refresh?.status==='running');if(result.refresh?.status==='failed')setError(failure(new Error(result.refresh.error||'listing_schema_read_failed')));}
    catch(e){if(current===epoch.current&&mounted.current){setError(failure(e));setPoll(false);}}
    finally{if(current===epoch.current&&mounted.current)setReading(false);}
  }
  useEffect(()=>{if(!active)return;epoch.current++;const timer=setTimeout(()=>void load(0,attributeId,cursor),200);return()=>{clearTimeout(timer);epoch.current++;};},[context,draft,active,previewSha]);
  useEffect(()=>{if(!active||!poll)return;const timer=setTimeout(()=>void load(data?.categories.offset||0),600);return()=>clearTimeout(timer);},[active,poll,data]);
  async function refresh(resource:'tree'|'attributes'|'values',attribute=0,page=0){if(writing.current)return;writing.current=true;setError('');const current=++epoch.current;setReading(true);
    try{await api('commerce_listing_schema_refresh',{...target,resource,category_id:categoryId,type_id:typ,attribute_id:attribute,last_value_id:page});if(current!==epoch.current||!mounted.current)return;setAttributeId(attribute);setCursor(page);await load(0,attribute,page);}
    catch(e){if(current===epoch.current&&mounted.current){setError(failure(e));await load(0,attribute,page);}}
    finally{writing.current=false;if(current===epoch.current&&mounted.current)setReading(false);}
  }
  function apply(){const option=data?.categories.items.find(c=>`${c.category_id}:${c.type_id}`===selected);if(!option||option.disabled)return;
    if(String(option.category_id)===payload.fields.category_id&&option.type_id===typ)return;
    if(payload.ozon?.attributes.length&&!window.confirm('更换类目或类型会移除原类型的 Ozon 属性输入，通用商品资料保留。继续更换？'))return;
    onChange(String(option.category_id),{...payload.ozon,type_id:option.type_id,attributes:[],...(payload.ozon?.publication?{publication:{...payload.ozon.publication,description_attribute_id:0}}:{})});
  }
  function update(schema:Attribute,row:OzonAttribute|null){const old=payload.ozon?.attributes||[];onChange(payload.fields.category_id,{...payload.ozon,type_id:typ,attributes:row?[...old.filter(r=>r.id!==schema.id),row]:old.filter(r=>r.id!==schema.id)});}
  const pending=reading||data?.refresh?.status==='running';
  const scopeReady=target.store_ref==='ozon-live'&&target.market==='RU';
  return <div className="r-listing-observation" id="listing-platform-schema" tabIndex={-1}><Panel title="Ozon 类目与平台属性" action={<Button disabled={busy||pending} onClick={()=>{setError('');void load();}}>检查当前输入</Button>}>
    <ErrorNotice>{error}</ErrorNotice>
    {!scopeReady?<Empty>先在“平台快照与核对”中关联已配置的 Ozon 俄罗斯店铺。</Empty>:<>
      <p role="status"><Badge tone={data?.validation.status==='limited_check_passed'?'blue':'gray'}>{data?labels[data.validation.status]||'检查状态未确认':'正在读取本机类目资料…'}</Badge>{pending&&' · 正在读取资料'}{dirty&&' · 当前输入尚未保存'}</p>
      {data?.synthetic&&<p>示例模式仅使用明确标注的合成资料，不读取实际店铺。</p>}
      <div className="r-observation-grid"><section aria-label="Ozon 类目与类型">
        <form className="r-actions r-schema-search" onSubmit={e=>{e.preventDefault();setError('');void load(0);}}><label className="ui-field">查找类目或类型<input value={query} maxLength={100} onChange={e=>setQuery(e.target.value)}/></label><Button disabled={pending} type="submit">查找类目</Button><Button disabled={pending||busy||data?.synthetic} onClick={()=>void refresh('tree')}>读取平台类目</Button></form>
        {data?.categories.sha256?<><label className="ui-field">准确类目与商品类型<select aria-label="准确类目与商品类型" size={6} value={selected} disabled={pending} onChange={e=>setSelected(e.target.value)}><option value="" disabled>选择类目与商品类型</option>{data.categories.items.map(c=><option key={`${c.category_id}:${c.type_id}`} value={`${c.category_id}:${c.type_id}`} disabled={c.disabled}>{c.path} · {c.category_id} / {c.type_id}{c.disabled?' · 停用':''}</option>)}</select></label>
          <div className="r-actions"><Button disabled={!selected||pending||busy} onClick={apply}>应用所选类型</Button><Button disabled={!data.categories.offset||pending} onClick={()=>void load(Math.max(0,data.categories.offset-50))}>上一页类目</Button><Button disabled={data.categories.next_offset===null||pending} onClick={()=>void load(data.categories.next_offset||0)}>下一页类目</Button></div><p className="r-footnote">匹配 {data.categories.total} 个类型 · {data.categories.fresh?'目录在有效期内':'目录已过期，需重新读取'}</p></>:<Empty>尚未留存平台类目目录。读取操作只获取元数据。</Empty>}
        <p>当前类目 {payload.fields.category_id||'未选'} · 类型 {typ||'未选'}</p>
        <Button disabled={!categoryId||!typ||pending||busy||data?.synthetic} onClick={()=>void refresh('attributes')}>读取该类型属性</Button>
        <p className="r-footnote">字典值的显示名称与 ID 一起保存。类目、属性与字典资料过期或变化后重新检查。</p>
        {data&&<details><summary>平台资料版本</summary><p className="r-code">{data.categories.sha256||'尚无类目快照'}</p><p className="r-code">{data.attributes.sha256||'尚无属性快照'}</p></details>}
      </section><section aria-label="Ozon 平台属性输入">
        <label><input type="checkbox" checked={optional} onChange={e=>setOptional(e.target.checked)}/>显示可选属性</label>
        {!data?.attributes.items.length?<Empty>选定类型后，读取其必填属性及字典。</Empty>:data.attributes.items.filter(s=>optional||s.is_required||payload.ozon?.attributes.some(r=>r.id===s.id)).map(s=>{
          const row=payload.ozon?.attributes.find(r=>r.id===s.id),values=row?.values||[{dictionary_value_id:0,value:''}];
          const options=attributeId===s.id?data.values.items:[];
          const setValues=(v:OzonAttribute['values'])=>update(s,{id:s.id,values:v,source_ref:row?.source_ref||''});
          return <fieldset className="r-schema-attribute" key={s.id} disabled={busy||!!s.complex_id}><legend>{s.name} · {s.id}{s.is_required?' · 必填':''}</legend>
            {s.complex_id?<p>复合属性需要专门适配与核对，当前不会将它判为通过。</p>:<>
              {values.map((value,i)=><div className="r-actions" key={i}>{s.dictionary_id?<label className="ui-field">{s.name} 字典值 {i+1}<select aria-label={`${s.name} 字典值 ${i+1}`} value={value.dictionary_value_id||''} onChange={e=>{const option=options.find(v=>v.id===Number(e.target.value));if(option)setValues(values.map((v,j)=>j===i?{dictionary_value_id:option.id,value:option.value}:v));}}><option value="">先读取并选择准确字典值</option>{value.dictionary_value_id>0&&!options.some(v=>v.id===value.dictionary_value_id)&&<option value={value.dictionary_value_id}>{value.value} · 已保存值 {value.dictionary_value_id}</option>}{options.map(v=><option key={v.id} value={v.id}>{v.value} · {v.id}</option>)}</select></label>:<label className="ui-field">{s.name} 属性值 {i+1}<input value={value.value} maxLength={5000} onChange={e=>setValues(values.map((v,j)=>j===i?{dictionary_value_id:0,value:e.target.value}:v))}/></label>}{values.length>1&&<Button aria-label={`移除 ${s.name} 的第 ${i+1} 个值`} onClick={()=>setValues(values.filter((_,j)=>j!==i))}>移除值</Button>}</div>)}
              {s.dictionary_id>0&&<div className="r-actions"><Button disabled={pending||data.synthetic} onClick={()=>void refresh('values',s.id,0)}>读取 {s.name} 字典</Button><Button disabled={pending} onClick={()=>{setAttributeId(s.id);setCursor(0);void load(0,s.id,0);}}>查看已留存字典</Button>{attributeId===s.id&&data.values.has_next&&<Button disabled={pending||data.synthetic} onClick={()=>void refresh('values',s.id,data.values.next_cursor||0)}>读取下一页字典</Button>}</div>}
              {s.is_collection&&(!s.max_value_count||values.length<s.max_value_count)&&<Button onClick={()=>setValues([...values,{dictionary_value_id:0,value:''}])}>添加属性值</Button>}
              <label className="ui-field">{s.name} 产品资料依据<input value={row?.source_ref||''} maxLength={1000} onChange={e=>update(s,{id:s.id,values,source_ref:e.target.value})}/></label>
              {row&&<Button onClick={()=>update(s,null)}>清除此属性</Button>}
            </>}
            {data.validation.issues.filter(v=>v.attribute_id===s.id).map((v,i)=><p className="r-footnote" key={i}>{issues[v.code]||'需要人工核对'}</p>)}
          </fieldset>;
        })}
        <div className="r-form-actions"><Button primary disabled={busy||!dirty} onClick={onSave}>保存类目与属性</Button></div>
      </section></div>
      {publicationSupported&&typ>0&&<PublicationFields value={payload.ozon||{type_id:typ,attributes:[]}} metadata={data?.attributes.items||[]} description={payload.fields.description||''} disabled={busy||!!pending} onChange={value=>onChange(payload.fields.category_id,value)} onCopyDescription={id=>{const schema=data?.attributes.items.find(r=>r.id===id);if(schema)update(schema,{id,source_ref:payload.ozon?.attributes.find(a=>a.id===id)?.source_ref||'',values:[{dictionary_value_id:0,value:payload.fields.description||''}]});}}/>}
      <p className="r-footnote">这里只检查类目与简单属性结构。包装尺寸、图片、运费、类目资质及平台规则仍需各自核验；未提交平台。</p>
    </>}
  </Panel></div>;
}
