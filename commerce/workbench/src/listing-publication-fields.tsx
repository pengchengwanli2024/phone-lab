import {Button} from './ui';
import type {OzonPayload} from './listing-schema';
export interface Publication {depth:number|null;width:number|null;height:number|null;weight:number|null;dimension_unit:''|'mm';weight_unit:''|'g';vat:string;source_ref:string;vat_source_ref:string;description_attribute_id:number}
export const blankPublication=():Publication=>({depth:null,width:null,height:null,weight:null,dimension_unit:'',weight_unit:'',vat:'',source_ref:'',vat_source_ref:'',description_attribute_id:0});
export function PublicationFields({value,metadata,description,disabled,onChange,onCopyDescription}:{value:OzonPayload;metadata:{id:number;name:string;type:string;dictionary_id:number;complex_id:number}[];description:string;disabled:boolean;onChange:(value:OzonPayload)=>void;onCopyDescription:(id:number)=>void}){
  const pub=value.publication||blankPublication();
  const update=<K extends keyof Publication>(key:K,v:Publication[K])=>onChange({...value,publication:{...pub,[key]:v}});
  return <fieldset className="r-schema-attribute" disabled={disabled}><legend>整卡发布资料</legend>
    <p className="r-footnote">按实物包装填写毫米和克，不推算尺寸、重量或税率。只准备商品资料与价格，计划数量不会在整卡导入中写入库存。</p>
    <div className="r-listing-fields">{(['depth','width','height','weight']as const).map(key=><label className="ui-field" key={key}>{{depth:'包装深度',width:'包装宽度',height:'包装高度',weight:'含包装重量'}[key]}<input type="number" min={0} step={1} value={pub[key]??''} onChange={e=>update(key,e.target.value===''?null:Number(e.target.value))}/></label>)}
      <label className="ui-field">尺寸单位<select value={pub.dimension_unit} onChange={e=>update('dimension_unit',e.target.value as Publication['dimension_unit'])}><option value="">请选择</option><option value="mm">毫米（mm）</option></select></label>
      <label className="ui-field">重量单位<select value={pub.weight_unit} onChange={e=>update('weight_unit',e.target.value as Publication['weight_unit'])}><option value="">请选择</option><option value="g">克（g）</option></select></label>
    </div><label className="ui-field">包装规格依据<input value={pub.source_ref} maxLength={1000} onChange={e=>update('source_ref',e.target.value)}/></label>
    <div className="r-listing-fields"><label className="ui-field">适用税率（平台小数格式）<input value={pub.vat} maxLength={20} inputMode="decimal" onChange={e=>update('vat',e.target.value)}/></label><label className="ui-field">税率依据<input value={pub.vat_source_ref} maxLength={1000} onChange={e=>update('vat_source_ref',e.target.value)}/></label></div>
    <label className="ui-field">产品描述对应的平台属性<select value={pub.description_attribute_id||''} onChange={e=>update('description_attribute_id',Number(e.target.value)||0)}><option value="">选择当前类目的文本属性</option>{metadata.filter(r=>!r.dictionary_id&&!r.complex_id&&['string','text'].includes(r.type.toLowerCase())).map(row=><option value={row.id} key={row.id}>{row.name} · {row.id}</option>)}</select></label>
    <Button disabled={!pub.description_attribute_id||!description} onClick={()=>onCopyDescription(pub.description_attribute_id)}>将当前描述填入此属性</Button>
    <p className="r-footnote">映射后仍需核对该属性的产品资料依据。类目、必填属性、当前负责人签收与单次执行确认分别检查。</p>
  </fieldset>;
}
