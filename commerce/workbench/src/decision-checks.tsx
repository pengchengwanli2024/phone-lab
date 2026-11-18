import {useRef,useState,type ReactNode} from 'react';
import {api,errorText} from './api';
import {blank,buildInput,InputProblem,kinds,label,problemText,samples,titles,tone,tools,type Form,type Kind} from './decision-checks-state';
import {Badge,Button,Empty,ErrorNotice,Panel} from './ui';
import './decision-checks.css';

type Row=Record<string,any>;
const intro:Record<Kind,string>={
  scorecard:'按复购依赖、净毛利、促销强度、预估ACOS四项给候选打分。缺项或差异未说明时为“待补依据”；结果按输入顺序列出，不是排名，也不是盈利承诺。',
  demand:'把多个来源的月度序列分别判断方向与覆盖率；只有两个来源、来源类型和独立分组都不同的序列方向一致，才给出趋势分类。只描述，不推算销量。',
  competitor:'比较同一平台、国家、商品最近两次快照。来源、口径或币种不一致时标为不可比，不换汇。',
  shipment:'核对货件应收与收货、调拨、调整和已有索赔，区分在途、确认差异与多收，并检查拟索赔数量。不创建或提交索赔；两个窗口天数是你的假设，不是平台政策。',
  experiment:'评估只改一个变量的对照实验（两比例检验，双侧95%）。多个变量、样本不足或差异不够时不宣布胜出；有外部干扰或超预算时结论不能直接采用。',
};
const tableHelp:Record<string,string>={
  scorecard:'每行一个候选。source_kind 填 MANUAL_QUOTE / THIRD_PARTY_ESTIMATE / FIRST_PARTY_ACTUAL / SIMULATION；review_dependency、promo_intensity 填 high / medium / low；differentiation 填 buyer_visible / none / unknown。',
  demand:'每行一个来源的一个月。period 为 YYYY-MM；value 可留空；同一来源同一月出现不同数值会被标为冲突。',
  competitor:'每行一次快照。observed_at 为 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SSZ；填写 price 时必须填 currency。',
  events:'event_type 填 RECEIVED / LOST_FOUND / TRANSFER / ADJUSTMENT；日期为 YYYY-MM-DD。',
  claims:'state 填 OPEN / RESOLVED / REJECTED；被驳回的索赔不计入已索赔。可只保留表头。',
};

function Field({label:text,children,wide}:{label:string;children:ReactNode;wide?:boolean}){return <label className={'ui-field'+(wide?' r-decision-wide':'')}>{text}{children}</label>;}
function Code({code}:{code:string|null|undefined}){return code?<Badge tone={tone(code)}>{label(code)}</Badge>:<span>—</span>;}
function List({items}:{items?:string[]}){return items?.length?<>{items.map(item=><Code key={item} code={item}/>)}</>:<span>—</span>;}
function Assumptions({value}:{value:Row}){return <details className="r-decision-notes"><summary>计算口径与假设</summary><ul>{(value.assumptions||[]).map((note:string)=><li key={note}>{note}</li>)}</ul>{value.thresholds&&<p>阈值：{JSON.stringify(value.thresholds)}</p>}</details>;}

function Result({kind,value}:{kind:Kind;value:Row}){
  if(kind==='scorecard')return <>
    <p className="r-decision-summary">共 {value.candidate_count} 个：数据就绪 {value.status_counts.READY}，待补依据 {value.status_counts.HOLD}，不建议 {value.status_counts.REJECT}</p>
    <div className="r-table-wrap"><table className="data-table"><caption className="sr-only">选品记分卡结果</caption><thead><tr><th scope="col">SKU</th><th scope="col">结论</th><th scope="col">四项得分</th><th scope="col">广告后盈余</th><th scope="col">待补</th><th scope="col">说明</th></tr></thead>
    <tbody>{value.matrix.map((row:Row)=><tr key={row.sku}><th scope="row">{row.sku}{row.title&&<small>{row.title}</small>}{row.estimated&&<small>估算数据 · {row.source}</small>}</th><td><Code code={row.status}/></td>
      <td>{row.scores?Object.entries(row.scores).map(([k,v])=><small key={k}>{label(k)} {String(v)}</small>):'—'}</td><td>{row.profit_after_ads_pct!=null?row.profit_after_ads_pct+'%':'—'}</td><td><List items={row.needs_evidence}/></td><td>{row.reason}</td></tr>)}</tbody></table></div></>;
  if(kind==='demand')return <>
    <p className="r-decision-summary"><Code code={value.classification}/> <Code code={value.consistency}/> {value.country_code} · {value.query} · 截至 {value.as_of_month}，{value.months} 个月</p>
    <div className="r-table-wrap"><table className="data-table"><caption className="sr-only">各来源序列</caption><thead><tr><th scope="col">来源</th><th scope="col">方向</th><th scope="col">变化</th><th scope="col">覆盖</th><th scope="col">季节性</th><th scope="col">不可用原因</th></tr></thead>
    <tbody>{value.cards.map((card:Row,i:number)=><tr key={i}><th scope="row">{card.source_id}<small>{card.source_type} · 分组 {card.independent_group} · {card.country_code} · {card.metric}（{card.unit}）{card.series_version}</small></th><td><Code code={card.direction}/></td>
      <td>{card.change_pct!=null?card.change_pct+'%':'—'}</td><td>{Math.round(card.coverage*100)}%</td><td>{card.seasonal?'是':'否'}</td><td><List items={card.reasons}/>{card.conflicting_months?.length?<small>冲突月份 {card.conflicting_months.join('、')}</small>:null}</td></tr>)}</tbody></table></div></>;
  if(kind==='competitor')return <div className="r-table-wrap"><table className="data-table"><caption className="sr-only">竞品快照变化</caption><thead><tr><th scope="col">商品</th><th scope="col">价格</th><th scope="col">评分</th><th scope="col">评论数</th><th scope="col">排名</th></tr></thead>
    <tbody>{value.products.map((p:Row)=><tr key={p.platform+p.country_code+p.external_id}><th scope="row">{p.external_id}<small>{p.platform} · {p.country_code} · {p.snapshot_count} 次快照 · 最新 {p.observed_at}</small></th>
      {['price','rating','review_count','rank'].map(field=>{const c=p.changes[field];return <td key={field}>{c.reason?<Code code={c.reason}/>:<>{c.previous} → {c.current}<small>{c.absolute}{c.percent!=null?'（'+c.percent+'%）':''}{field==='price'&&p.currency?' '+p.currency:''}</small></>}</td>;})}</tr>)}</tbody></table></div>;
  if(kind==='shipment')return <>
    <p className="r-decision-summary"><Code code={value.state}/> 待处理差异 {value.pending_variance} 件{value.over_received?'，多收 '+value.over_received+' 件':''}{value.proposed_claim&&<> · 拟索赔 {value.proposed_claim.quantity} 件：<Code code={value.proposed_claim.verdict}/></>}</p>
    <dl className="r-decision-facts">{[['应收',value.expected_quantity],['已收（含找回）',value.received_quantity],['调拨（排除）',value.transfers_excluded],['调整（排除）',value.adjustments_excluded],['已索赔',value.already_claimed],['发货后天数',value.age_days],['索赔窗口剩余天数',value.claim_window_days_remaining]].map(([k,v])=><div key={k as string}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl>
    {value.warnings.length>0&&<p className="r-decision-warn">需要核对：<List items={value.warnings}/></p>}</>;
  return <>
    <p className="r-decision-summary"><Code code={value.outcome}/> {value.reason}{value.decision_ready?'':'；暂不能直接据此决策'}</p>
    <dl className="r-decision-facts">{[['基线',value.baseline.successes+' / '+value.baseline.trials+(value.baseline.rate?'（'+value.baseline.rate+'）':'')],['变体',value.variant.successes+' / '+value.variant.trials+(value.variant.rate?'（'+value.variant.rate+'）':'')],['z 值',value.z_score??'—'],['阈值',value.threshold_z],['每组最少样本',value.min_sample_per_arm]].map(([k,v])=><div key={k as string}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl>
    {value.flags.length>0&&<p className="r-decision-warn">需要复核：<List items={value.flags}/>{value.external_interference.length?'（'+value.external_interference.join('；')+'）':''}</p>}</>;
}

function Inputs({kind,form,set}:{kind:Kind;form:Form;set:(key:string,value:string)=>void}){
  const text=(key:string,name:string,extra:Record<string,unknown>={})=><Field label={name}><input value={form[key]||''} onChange={e=>set(key,e.target.value)} {...extra}/></Field>;
  const area=(key:string,name:string,help:string,rows=6)=><Field label={name} wide><textarea rows={rows} spellCheck={false} value={form[key]||''} onChange={e=>set(key,e.target.value)} aria-describedby={'dc-help-'+key}/><small id={'dc-help-'+key} className="r-decision-help">{help}</small></Field>;
  if(kind==='scorecard')return area('table','候选表（CSV 或从表格直接粘贴）',tableHelp.scorecard,8);
  if(kind==='competitor')return area('table','快照表（CSV 或从表格直接粘贴）',tableHelp.competitor,8);
  if(kind==='demand')return <>{text('country_code','国家代码',{maxLength:2,placeholder:'RU'})}{text('query','查询词',{maxLength:200})}{text('as_of_month','截至月份',{placeholder:'YYYY-MM'})}
    <Field label="窗口月数"><select value={form.months||'12'} onChange={e=>set('months',e.target.value)}>{['12','24','36'].map(v=><option key={v} value={v}>{v}</option>)}</select></Field>{area('table','月度序列表',tableHelp.demand,8)}</>;
  if(kind==='shipment')return <>{text('shipment_ref','货件编号')}{text('sku','SKU')}{text('expected_quantity','应收数量',{inputMode:'numeric'})}{text('shipped_date','发货日期',{type:'date'})}{text('as_of','核对日期',{type:'date'})}
    {text('proposed_claim_quantity','拟索赔数量（可留空）',{inputMode:'numeric'})}{text('in_transit_window_days','在途观察天数（默认14）',{inputMode:'numeric'})}{text('claim_window_days','索赔窗口天数（默认90）',{inputMode:'numeric'})}
    {area('events','收货事件',tableHelp.events,5)}{area('claims','已有索赔',tableHelp.claims,3)}</>;
  return <>{text('primary_metric','主要指标')}<Field label="指标方向"><select value={form.higher_is_better||'true'} onChange={e=>set('higher_is_better',e.target.value)}><option value="true">越高越好</option><option value="false">越低越好</option></select></Field>
    {text('baseline_trials','基线样本数',{inputMode:'numeric'})}{text('baseline_successes','基线达成数',{inputMode:'numeric'})}{text('variant_trials','变体样本数',{inputMode:'numeric'})}{text('variant_successes','变体达成数',{inputMode:'numeric'})}
    {text('min_sample_per_arm','每组最少样本（默认100）',{inputMode:'numeric'})}{text('budget_cap','预算上限（可留空）',{inputMode:'decimal'})}{text('budget_spent','已花费（可留空）',{inputMode:'decimal'})}
    {area('changed_variables','本次改动的变量（每行一个；多于一个时不宣布胜出）','例如：主图',2)}{area('external_interference','外部干扰（每行一条，可留空）','例如：平台大促、断货、竞品降价',2)}</>;
}

/** Read-only page over the five stateless decision checks. Nothing is saved. */
export function DecisionChecks(){
  const [kind,setKind]=useState<Kind>('scorecard');
  const [forms,setForms]=useState<Record<Kind,Form>>(()=>({...blank}));
  const [results,setResults]=useState<Partial<Record<Kind,{value:Row;basis:string;sample:boolean}>>>({});
  const [errors,setErrors]=useState<Partial<Record<Kind,string>>>({}),[busy,setBusy]=useState(false),[samplesUsed,setSamplesUsed]=useState<Partial<Record<Kind,boolean>>>({});
  const version=useRef(0),form=forms[kind],result=results[kind],basis=JSON.stringify(form),stale=!!result&&result.basis!==basis;
  const set=(key:string,value:string)=>setForms(all=>({...all,[kind]:{...all[kind],[key]:value}}));
  async function run(){
    if(busy)return;const request=++version.current,current=kind,snapshot=basis,sample=!!samplesUsed[kind];
    setErrors(all=>({...all,[current]:''}));
    let input:object;
    try{input=buildInput(current,forms[current]);}catch(failure){setErrors(all=>({...all,[current]:failure instanceof InputProblem?failure.message:'输入无法解析'}));return;}
    setBusy(true);
    try{const value=await api<Row>(tools[current],{input});if(request===version.current)setResults(all=>({...all,[current]:{value,basis:snapshot,sample}}));}
    catch(failure){if(request===version.current){const code=failure instanceof Error?failure.message:'';setErrors(all=>({...all,[current]:problemText(code)||errorText(failure)}));}}
    finally{if(request===version.current)setBusy(false);}
  }
  return <div className="r-page r-decision-checks">
    <div className="r-page-heading"><div><h1>经营决策检查</h1><p>用你提供的数据做五类只读检查。不读取店铺、不保存、不建任务、不调用模型；每个结果都需要人工核对来源后再使用。</p></div></div>
    <div className="r-tabs" role="group" aria-label="检查类型">{kinds.map(id=><Button key={id} aria-pressed={kind===id} onClick={()=>setKind(id)}>{titles[id]}</Button>)}</div>
    <Panel title={titles[kind]} action={<div className="r-actions"><Button onClick={()=>{setForms(all=>({...all,[kind]:{...samples[kind]}}));setSamplesUsed(all=>({...all,[kind]:true}));}}>填入合成示例</Button><Button onClick={()=>{setForms(all=>({...all,[kind]:{...blank[kind]}}));setSamplesUsed(all=>({...all,[kind]:false}));}}>清空</Button></div>}>
      <p className="r-decision-intro">{intro[kind]}</p>
      <ErrorNotice>{errors[kind]}</ErrorNotice>
      <form className="r-decision-form" onSubmit={e=>{e.preventDefault();void run();}}><fieldset disabled={busy}><legend className="sr-only">{titles[kind]}输入</legend>
        <div className="r-decision-grid"><Inputs kind={kind} form={form} set={set}/></div>
        <div className="r-actions r-decision-submit"><Button primary type="submit">{busy?'检查中…':'检查'}</Button></div></fieldset></form>
      <section className="r-decision-result" aria-live="polite" aria-label="检查结果">
        {result&&!stale?<>{result.sample&&<p className="r-decision-sample"><Badge tone="warning">合成示例</Badge> 以下结果来自示例数据，不代表任何店铺。</p>}<Result kind={kind} value={result.value}/><Assumptions value={result.value}/></>
          :<Empty>{result?'输入已变化，请重新检查。':'填写数据后点“检查”。'}</Empty>}
      </section>
    </Panel>
  </div>;
}
