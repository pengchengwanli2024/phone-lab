import { useEffect, useRef, useState } from 'react';
import type {PreparedOrderSupport} from './order-support';
import { api } from './api';
import { adoptionErrorText as errorText } from './adoption-errors';
import { Button, Empty, ErrorNotice, Panel } from './ui';
import { requestKey, type ImportBatch } from './adoption-types';
import './adoption.css';

const fields = [['order_id','订单号'],['line_id','订单行号（可选）'],['sku','SKU'],['order_date','订单日期'],['quantity','数量'],['unit_price','单价'],['currency','币种']];
const sample = 'order_id,line_id,sku,order_date,quantity,unit_price,currency\nSYN-1,1,SYN-A,2026-11-01,2,12.50,CNY\nSYN-1,2,SYN-B,2026-11-01,1,3.20,CNY\nSYN-2,1,SYN-C,2026-11-02,1,4.00,USD\n';
const reasonLabels: Record<string,string> = { INVALID_ORDER_ID:'订单号缺失、超长或含控制字符', INVALID_SKU:'SKU缺失、超长或含控制字符', INVALID_LINE_ID:'订单行号缺失、超长或含控制字符', INVALID_QUANTITY:'数量须为1至100000的整数', INVALID_UNIT_PRICE:'单价须为有效的非负金额，最多8位小数', INVALID_ORDER_DATE:'日期无效，或时间缺少明确时区', MISSING_OR_UNSUPPORTED_CURRENCY:'币种缺失或不在当前支持范围', COLUMN_COUNT_MISMATCH:'该行列数与表头不一致', LINE_IDENTITY_CONFLICT:'同一订单行出现不同内容，需先核对', EXISTING_LINE_CONFLICT:'与已保存订单行内容冲突，原记录已保留' };
const stateLabels: Record<string,string> = { preview:'待确认', confirmed:'已确认', partial:'部分导入', rejected:'未导入' };
export function OrderImports({ demo, navigate, onSupport }: { demo: boolean; navigate: (tab: string) => void; onSupport?:(prepared:PreparedOrderSupport)=>Promise<void> }) {
  const [filename,setFilename]=useState('orders.csv'), [content,setContent]=useState('');
  const [platform,setPlatform]=useState('ozon'), [store,setStore]=useState(''), [market,setMarket]=useState('RU');
  const [mapping,setMapping]=useState<Record<string,string>>(Object.fromEntries(fields.map(([key])=>[key,key])));
  const [batch,setBatch]=useState<ImportBatch|null>(null), [history,setHistory]=useState<ImportBatch[]>([]), [error,setError]=useState(''), [busy,setBusy]=useState(false), [checked,setChecked]=useState(false);
  const [orders,setOrders]=useState<Record<string,string|number>[]>([]);
  const [page,setPage]=useState(0),[readingFile,setReadingFile]=useState(false);
  const fileEpoch=useRef(0);
  const generation=useRef(0), keys=useRef(new Map<string,string>());
  function invalidateFileRead(){fileEpoch.current++;setReadingFile(false);}
  function changed(){invalidateFileRead();setBatch(null);setOrders([]);setChecked(false);setPage(0);}
  async function load() { const request=++generation.current; try { const result=await api<{items:ImportBatch[]}>('commerce_order_import_list',{synthetic:demo});if(request===generation.current)setHistory(result.items); } catch(e){if(request===generation.current)setError(errorText(e));} }
  useEffect(()=>{invalidateFileRead();setBusy(false);setError('');setBatch(null);setOrders([]);setChecked(false);setPage(0);void load();return()=>{generation.current++;fileEpoch.current++;};},[demo]);
  async function show(id:string) { invalidateFileRead();const request=++generation.current;setBusy(true);setError('');try { const result=await api<ImportBatch>('commerce_order_import_get',{batch_id:id});const lines=await api<{orders:Record<string,string|number>[]}>('commerce_orders_list',{import_batch_id:id,demo});if(request===generation.current){setBatch(result);setHistory(previous=>[result,...previous.filter(b=>b.id!==result.id)]);setOrders(lines.orders);setChecked(false);setPage(0);} }catch(e){if(request===generation.current)setError(errorText(e));}finally{if(request===generation.current)setBusy(false);} }
  async function support(row:Record<string,string|number>){if(!batch||!onSupport||busy)return;const current=++generation.current;setBusy(true);setError('');try{const prepared=await api<PreparedOrderSupport>('commerce_order_support_prepare',{demo,platform:batch.scope.platform,store_id:batch.scope.store_ref,market:batch.scope.market,order_id:String(row.id),expected_source_sha256:String(row.source_sha256),import_batch_id:batch.id});if(current===generation.current)await onSupport(prepared);}catch(failure){if(current===generation.current)setError(errorText(failure));}finally{if(current===generation.current)setBusy(false);}}
  async function preview() {
    if(readingFile)return;
    const request=++generation.current;setBusy(true);setError('');
    const body={filename,content,scope:{platform,store_ref:store,market},synthetic:demo,field_mapping:Object.fromEntries(Object.entries(mapping).filter(([,v])=>v.trim()))};
    try { const result=await api<ImportBatch>('commerce_order_import_preview',{...body,idempotency_key:requestKey(keys.current,'preview',body)});const lines=result.status==='preview'?[]:(await api<{orders:Record<string,string|number>[]}>('commerce_orders_list',{import_batch_id:result.id,demo})).orders;if(request===generation.current){setBatch(result);setHistory(previous=>[result,...previous.filter(b=>b.id!==result.id)]);setOrders(lines);setChecked(false);setPage(0);} }
    catch(e){if(request===generation.current)setError(errorText(e));}finally{if(request===generation.current)setBusy(false);}
  }
  async function confirm() {
    if(!batch||!checked||batch.synthetic!==demo)return;
    const request=++generation.current;setBusy(true);setError('');
    const body={batch_id:batch.id,expected_sha256:batch.sha256,confirmed:true};
    try { const result=await api<ImportBatch>('commerce_order_import_confirm',{...body,idempotency_key:requestKey(keys.current,'confirm',body)});const lines=await api<{orders:Record<string,string|number>[]}>('commerce_orders_list',{import_batch_id:batch.id,demo});if(request===generation.current){setBatch(result);setHistory(previous=>[result,...previous.filter(b=>b.id!==result.id)]);setOrders(lines.orders);setChecked(false);setPage(0);} }
    catch(e){if(request===generation.current)setError(errorText(e));}finally{if(request===generation.current)setBusy(false);}
  }
  async function fileChanged(file?:File) {
    if(!file){invalidateFileRead();return;}
    if(file.size>512000){invalidateFileRead();setError('CSV文件最多512KB。');return;}
    changed();const request=fileEpoch.current;setReadingFile(true);setError('');
    try{const value=await file.text();if(request!==fileEpoch.current)return;setContent(value);setFilename(file.name);}
    catch{if(request===fileEpoch.current)setError('无法读取文件，原输入已保留。');}
    finally{if(request===fileEpoch.current)setReadingFile(false);}
  }
  const pageSize=50,lastPage=Math.max(0,Math.ceil(orders.length/pageSize)-1),currentPage=Math.min(page,lastPage);
  const visibleOrders=orders.slice(currentPage*pageSize,(currentPage+1)*pageSize);
  return <div className="r-page"><div className="r-page-heading"><h1>订单导入</h1><Button onClick={()=>navigate('orders')}>平台订单</Button></div>
    <p className="adoption-notice">{demo?'合成验证范围':'本机资料范围'} · CSV 导入不代表店铺同步。预览不会写入订单；确认后仅保存映射的订单字段。</p><ErrorNotice>{error}</ErrorNotice>{error===errorText(Error('order_support_editor_open'))&&<Button onClick={()=>navigate('support')}>回到当前编辑</Button>}
    <Panel title="CSV与字段映射"><fieldset disabled={busy} className="adoption-form"><div className="adoption-grid">
      <label className="ui-field">CSV文件<input type="file" accept=".csv,text/csv" onChange={e=>void fileChanged(e.target.files?.[0])}/></label>
      <label className="ui-field">文件名<input value={filename} maxLength={160} onChange={e=>{changed();setFilename(e.target.value);}}/></label>
      <label className="ui-field">平台<select value={platform} onChange={e=>{changed();setPlatform(e.target.value);}}>{['ozon','tiktok','amazon','mercado','temu','local'].map(v=><option key={v}>{v}</option>)}</select></label>
      <label className="ui-field">店铺引用<input value={store} maxLength={100} placeholder="本机脱敏引用" onChange={e=>{changed();setStore(e.target.value);}}/></label>
      <label className="ui-field">市场国家代码<input value={market} maxLength={2} onChange={e=>{changed();setMarket(e.target.value.toUpperCase());}}/></label></div>
      <label className="ui-field">CSV内容<textarea value={content} maxLength={512000} onChange={e=>{changed();setContent(e.target.value);}} spellCheck={false}/></label>
      <div className="adoption-grid">{fields.map(([key,label])=><label className="ui-field" key={key}>{label.replace('（可选）','')}列{label.includes('（可选）')?'（可选）':''}<input value={mapping[key]} maxLength={128} onChange={e=>{changed();setMapping({...mapping,[key]:e.target.value});}}/></label>)}</div>
      <p className="adoption-notice">最多2000行。币种逐行必填，日期使用YYYY-MM-DD或带时区的ISO时间。未提供订单行号时，以同订单内的SKU识别订单行。</p>
      <div className="adoption-actions"><Button primary disabled={readingFile||!content||!store} onClick={()=>void preview()}>{readingFile?'正在读取CSV…':'预览导入'}</Button>{demo&&<Button onClick={()=>{changed();setContent(sample);setFilename('synthetic.csv');setStore('synthetic-store');}}>填入合成示例</Button>}</div>
    </fieldset></Panel>
    {batch&&<Panel title={`${batch.filename} · ${stateLabels[batch.status]||batch.status}`}><p role="status">共{batch.row_count}行 · 可用{batch.valid_count}行 · 已新增{batch.accepted_count}行 · 重复{batch.duplicate_count}行 · 隔离{batch.quarantined_count}行</p>
      {batch.sales_by_currency.length>0&&<div className="r-table-wrap"><table className="data-table"><thead><tr><th>币种</th><th>本批新增订单</th><th>订单行</th><th>数量</th><th>销售额（未扣费）</th></tr></thead><tbody>{batch.sales_by_currency.map(t=><tr key={t.currency}><td>{t.currency}</td><td>{t.order_count}</td><td>{t.line_count}</td><td>{t.unit_count}</td><td>{t.gross_sales}</td></tr>)}</tbody></table></div>}
      <div className="r-table-wrap"><table className="data-table"><thead><tr><th>订单</th><th>行号</th><th>SKU</th><th>数量</th><th>单价</th><th>币种</th><th>操作</th></tr></thead><tbody>{(batch.status==='preview'?batch.preview.map(v=>v.record):visibleOrders).map((r,i)=><tr key={String(r.id||`${r.order_id}:${r.line_id}:${i}`)}><td>{r.order_id}</td><td>{r.line_id}</td><td>{r.sku}</td><td>{r.quantity}</td><td>{r.unit_price}</td><td>{r.currency}</td><td>{batch.status!=='preview'&&onSupport&&<Button disabled={busy} onClick={()=>void support(r)}>起草此订单回复</Button>}</td></tr>)}</tbody></table></div>
      {batch.status!=='preview'&&<nav className="adoption-actions" aria-label="已导入订单分页"><Button disabled={busy||currentPage===0} onClick={()=>setPage(currentPage-1)}>上一页订单</Button><span role="status">{orders.length?currentPage*pageSize+1:0}–{Math.min((currentPage+1)*pageSize,orders.length)} / {orders.length} 条已保存记录</span><Button disabled={busy||currentPage>=lastPage} onClick={()=>setPage(currentPage+1)}>下一页订单</Button></nav>}
      {batch.status==='preview'&&batch.preview_truncated&&<p className="adoption-notice">预览最多展示50条有效记录及50条隔离原因；确认后可翻页查看全部已保存订单。</p>}
      {batch.status!=='preview'&&batch.quarantined_count>batch.quarantined.length&&<p className="adoption-notice">隔离原因展示前{batch.quarantined.length}条；请核对原CSV后再导入。</p>}
      {batch.quarantined_count>0&&<details open><summary>隔离行与原因</summary><ul>{batch.quarantined.map((row,i)=><li key={i}>第{row.row}行：{reasonLabels[row.code]||'该行未通过格式校验'}</li>)}</ul></details>}
      {batch.status==='preview'&&<><label className="adoption-check"><input type="checkbox" checked={checked} disabled={busy} onChange={e=>setChecked(e.target.checked)}/>我已核对当前预览、范围和隔离行，确认导入其中的有效订单行。</label><div className="adoption-actions"><Button primary disabled={busy||!checked} onClick={()=>void confirm()}>确认本机导入</Button></div></>}
    </Panel>}
    <Panel title="导入记录" action={<Button disabled={busy} onClick={()=>void load()}>刷新</Button>}>{history.length?<ul className="adoption-list">{history.map(item=><li key={item.id}><Button disabled={busy} onClick={()=>void show(item.id)}>{item.filename} · {stateLabels[item.status]} · {item.scope.store_ref}</Button></li>)}</ul>:<Empty>当前范围尚无导入记录。</Empty>}</Panel>
  </div>;
}
