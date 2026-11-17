/** Navigation only; readiness and signoff remain server decisions. */
const labels:Record<string,string>={sku:'SKU',title:'商品标题',description:'商品描述',category_id:'目标类目 ID',price:'售价',currency:'币种',quantity:'计划上架数量',image_refs:'图片链接',language:'目标语言',fulfillment:'履约方案',rules_ref:'规则依据',store_ref:'目标店铺',market:'国家/市场代码'};
const fieldId=(key:string)=>({store_ref:'listing-store-ref',market:'listing-market',language:'listing-language',fulfillment:'listing-fulfillment',rules_ref:'listing-rules_ref'}[key]||'listing-field-'+key);
interface Payload {fields:Record<string,unknown>;language:string;fulfillment:string;rules_ref:string;attributes:{name:string;value:string;source_ref:string}[]}
export function gapFields(check:string,payload:Payload,target:{store_ref:string;market:string},invalid:string[]=[]):{id:string;label:string}[]{
  const missing=(value:unknown)=>value==null||typeof value==='string'&&!value.trim()||Array.isArray(value)&&!value.length;
  const entry=(key:string)=>({id:fieldId(key),label:labels[key]});
  if(check==='source_fields')return invalid.filter(key=>Object.hasOwn(labels,key)).map(entry);
  if(check==='attributes')return payload.attributes.flatMap((row,index)=>(['value','source_ref'] as const).filter(key=>missing(row[key])).map(key=>({id:`listing-attribute-${index}-${key}`,label:`属性 ${index+1} · ${key==='value'?'属性值':'资料依据'}`})));
  const keys:Record<string,string[]>={identity:['store_ref','market'],content:['sku','title','description','category_id'],offer:['price','currency','quantity'],media:['image_refs'],locale:['language','fulfillment'],rules:['rules_ref']};
  const values:Record<string,unknown>={...payload.fields,language:payload.language,fulfillment:payload.fulfillment,rules_ref:payload.rules_ref,...target};
  return (Object.hasOwn(keys,check)?keys[check]:[]).filter(key=>missing(values[key])).map(entry);
}
