import {useRef,useState} from 'react';
import {api,errorText} from './api';
import {toInput,type Values} from './cost-input';
import {Button,Empty,ErrorNotice,Money,Panel} from './ui';
export interface CampaignDraft {name:string;price:string;merchant_discount:string;ad_cost_per_unit:string;affiliate_rate:string}
interface Result {status:string;currency:string;missing?:string[];assumptions?:string[];plans:{name:string;net_revenue:number;contribution:number;ad_allowance_at_target:number;recommendation:string}[]}
export function campaignInput(values:Values,plans:CampaignDraft[],target:string,inventory:string) {
  const number=(raw:string,label:string,maximum=Number.MAX_VALUE)=>{if(!raw.trim())throw Error('请填写'+label+'，没有该项请填 0');const value=Number(raw);if(!Number.isFinite(value)||value<0||value>maximum)throw Error(label+'超出有效范围');return value;};
  return {base:toInput(values),target_contribution:number(target,'目标单件贡献'),inventory_state:inventory,plans:plans.map(plan=>{
    if(!plan.name.trim())throw Error('请填写方案名称');
    const price=number(plan.price,'售价'),discount=number(plan.merchant_discount,'商家优惠');
    if(price-discount<.01)throw Error('优惠后售价须大于 0');
    return {name:plan.name.trim(),price,merchant_discount:discount,ad_cost_per_unit:number(plan.ad_cost_per_unit,'每单广告费'),affiliate_rate:number(plan.affiliate_rate,'达人佣金率',100)/100};
  })};
}
export function CampaignScenarios({values,disabled}:{values:Values;disabled:boolean}) {
  const [plans,setPlans]=useState<CampaignDraft[]>(['A','B'].map(name=>({name:'方案 '+name,price:'',merchant_discount:'',ad_cost_per_unit:'',affiliate_rate:''}))),[target,setTarget]=useState(''),[inventory,setInventory]=useState('unknown'),[result,setResult]=useState<Result|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const version=useRef(0),snapshot=useRef(''),current=JSON.stringify({values,plans,target,inventory});
  const stale=snapshot.current!==current;
  async function compare(){if(busy||disabled)return;const request=++version.current;setBusy(true);setError('');setResult(null);
    try{const input=campaignInput(values,plans,target,inventory);const value=await api<Result>('commerce_campaign_compare',{input});if(request===version.current){snapshot.current=current;setResult(value);}}
    catch(failure){if(request===version.current)setError(failure instanceof Error&&failure.message.startsWith('请')||failure instanceof Error&&failure.message.includes('须大于')?failure.message:errorText(failure));}
    finally{if(request===version.current)setBusy(false);}
  }
  return <details className="r-campaign-scenarios"><summary>定价、优惠与投流对比</summary><Panel title="促销方案">
    <p className="r-footnote">沿用上方当前成本输入。每单广告替代基础广告比例，结果仅作测算。</p><ErrorNotice>{error}</ErrorNotice>
    <fieldset disabled={busy||disabled}><div className="r-cost-fields"><label className="ui-field">目标单件贡献（{values.currency||'同币种'}）<input type="number" min="0" step="any" value={target} onChange={e=>setTarget(e.target.value)}/></label><label className="ui-field">库存情况（人工判断）<select value={inventory} onChange={e=>setInventory(e.target.value)}>{Object.entries({unknown:'尚未核实',sufficient:'充足',tight:'紧张',overstock:'积压'}).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label></div>
    {plans.map((plan,index)=><fieldset key={index} className="r-cost-group"><legend>{plan.name||`方案 ${index+1}`}</legend><div className="r-cost-fields">{Object.entries({name:'方案名称',price:'售价',merchant_discount:'商家优惠 / 单',ad_cost_per_unit:'广告费 / 单',affiliate_rate:'达人佣金率（%）'}).map(([key,label])=><label className="ui-field" key={key}>{label}<input type={key==='name'?'text':'number'} min={key==='name'?undefined:0} max={key==='affiliate_rate'?100:undefined} maxLength={key==='name'?80:undefined} step="any" value={plan[key as keyof CampaignDraft]} onChange={e=>setPlans(rows=>rows.map((row,i)=>i===index?{...row,[key]:e.target.value}:row))}/></label>)}</div></fieldset>)}<Button primary onClick={()=>void compare()}>比较方案</Button></fieldset>
    {result&&!stale?(result.status==='HOLD'?<p role="status">成本参数待补充：{result.missing?.join('、')}</p>:<><div className="r-table-wrap"><table className="data-table"><thead><tr><th>方案</th><th>优惠后收入</th><th>单件贡献</th><th>目标广告额度 / 单</th></tr></thead><tbody>{result.plans.map(row=><tr key={row.name}><td>{row.name}</td><td><Money value={row.net_revenue} currency={result.currency}/></td><td><Money value={row.contribution} currency={result.currency}/></td><td><Money value={row.ad_allowance_at_target} currency={result.currency}/></td></tr>)}</tbody></table></div>{result.plans.map(row=><p key={row.name}>{row.name}：{row.recommendation}</p>)}<details><summary>计算口径</summary>{result.assumptions?.map(note=><p key={note}>{note}</p>)}</details></>):<Empty>{result?'参数已变化，请重新比较。':'填写两组方案后比较。'}</Empty>}
  </Panel></details>;
}
