import {Badge,Button,Dialog} from './ui';
import type {AlertEvidenceRow} from './operating-alert-state';

export function OperatingAlertEvidence({row,close,refresh,onOriginal}:{row:AlertEvidenceRow;close:()=>void;refresh:()=>void;onOriginal:()=>void}){
  const {alert,live}=row;
  const source=live?'店铺只读快照':alert.source==='synthetic'?'合成示例资料':'手工或导入资料 · 未独立核实';
  return <Dialog title="经营提醒原记录" close={close}>
    <h3>{alert.title}</h3>
    <p><Badge>{source}</Badge> <Badge>{({active:'待查看',acknowledged:'已查看',suspended:'资料已陈旧 · 已挂起',resolved:'已由后续记录关闭'}as Record<string,string>)[alert.status]||'状态待核对'}</Badge></p>
    <p className="r-readable">{alert.detail}</p>
    <dl className="r-notification-state">
      <dt>店铺</dt><dd>{alert.store_id||'未提供'}</dd>
      <dt>平台 / 市场</dt><dd>{[alert.platform,alert.market].filter(Boolean).join(' / ')||'未提供'}</dd>
      <dt>订单 / 发货单</dt><dd className="r-readable">{alert.order_id||'未提供；可能为库存提醒'}</dd>
      <dt>商品 SKU</dt><dd className="r-readable">{alert.sku||'未提供'}</dd>
      <dt>仓库 / 履约范围</dt><dd className="r-readable">{alert.warehouse||'未提供'}</dd>
      <dt>来源核对时间</dt><dd>{alert.observed_at||'未提供'}</dd>
      <dt>来源记录</dt><dd className="r-readable">{alert.source_ref||'未提供'}</dd>
    </dl>
    <details><summary>核对来源版本与规则</summary>
      <p className="r-readable">记录 SHA-256：{alert.source_sha256||'未提供'}</p>
      <p className="r-readable">提醒标识：{alert.id}</p>
      <p>资料有效期：{alert.rules?.max_age_minutes===undefined?'未提供':`${alert.rules.max_age_minutes} 分钟`}；发货预警提前：{alert.rules?.dispatch_warning_hours===undefined?'未提供':`${alert.rules.dispatch_warning_hours} 小时`}。</p>
    </details>
    <p>已阅不等于处理完成。请以原来源的后续记录及平台回执核对处理结果。</p>
    <div className="r-actions"><Button onClick={refresh}>重新核对当前来源</Button><Button onClick={onOriginal}>前往经营提醒处理</Button></div>
  </Dialog>;
}
