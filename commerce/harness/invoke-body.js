const shippingIntake=new Set(['commerce_shipping_rates_preview','commerce_shipping_rates_import','commerce_shipping_input_preview','commerce_shipping_plan_create','commerce_shipping_compare']);
export function parseInvokeBody(body){
  const fail=(message,status)=>{throw Object.assign(Error(message),{status});};
  const size=Buffer.byteLength(body,'utf8');if(size>1572864)fail('request_too_large',413);
  let data;try{data=JSON.parse(body);}catch{fail('invalid_request',400);}
  if(!data||typeof data!=='object'||Array.isArray(data))fail('invalid_request',400);
  if(size>131072&&!shippingIntake.has(data.tool))fail('request_too_large',413);
  return data;
}
