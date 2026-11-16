"""A script-free private reading/printing view of an existing frozen application."""
from datetime import datetime,timezone
from html import escape
import json
from pathlib import Path
from research import canonical,digest
from ui.build import generated

ROOT=Path(__file__).resolve().parent
LABELS={'blocked':'发布检查未关闭','outdated':'原方案已变化','needs_changes':'申请待修改','withdrawn':'本地申请已撤回',
        'awaiting_execution_authority':'等待明确执行授权','pending':'待审阅','acknowledged':'申请已阅',
        'not_requested':'尚未读取','running':'正在读取','succeeded':'本次读取已完成','failed':'本次读取失败','interrupted':'读取中断',
        'prepared':'资料已填','missing':'待补充','stale':'已变化','same':'相同','different':'有差异','unknown':'未知',
        'missing_input':'方案待填','not_comparable':'口径不可比较','product_observed':'已回读对应商品，发布状态仍需核对',
        'awaiting_product_id':'导入已受理，等待有效商品 ID','checking':'正在复核平台前值','submitting':'已开始单次提交','accepted':'平台已返回任务','imported_needs_review':'导入完成，审核与可售待核对','import_rejected':'导入被拒绝','owner_confirmed':'负责人核对完成（本人声明）'}
FIELDS={'sku':'SKU','title':'商品标题','description':'商品描述','category_id':'目标类目 ID','price':'售价（原币）','currency':'币种','quantity':'计划上架数量'}

def text(value):
    if value is None or value=='':return '未提供'
    if type(value)is bool:return '是'if value else'否'
    return str(value)

def e(value):return escape(text(value),quote=True)
def label(value):return LABELS.get(value,value)
def pairs(items):return '<dl class="review-pairs">'+''.join('<div><dt>'+e(k)+'</dt><dd>'+e(v)+'</dd></div>'for k,v in items)+'</dl>'
def table(headers,rows,name):
    return '<div class="review-table" role="region" tabindex="0" aria-label="'+e(name)+'"><table><thead><tr>'+''.join('<th scope="col">'+e(h)+'</th>'for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<'+('th scope="row"'if i==0 else'td')+'>'+e(cell)+'</'+('th'if i==0 else'td')+'>'for i,cell in enumerate(row))+'</tr>'for row in rows)+'</tbody></table></div>'
def section(title,body):return '<section class="card"><h2>'+e(title)+'</h2>'+body+'</section>'

def picture(row,index):
    caption='拟上架主图 · 第 1 张'if index==0 else'第 '+str(index+1)+' 张产品图片'
    if row and row.get('status')=='ready'and row.get('mime')in ('image/png','image/jpeg'):
        image='<img src="'+e('data:'+row['mime']+';base64,'+row['content_base64'])+'" alt="产品图片 '+str(index+1)+'">'
    else:image='<div class="review-image-missing">第 '+str(index+1)+(' 张图片文件已变化，暂不可用'if row and row.get('error')=='listing_review_image_changed'else' 张图片尚未读取')+'</div>'
    return '<figure>'+image+'<figcaption>'+e(caption)+'</figcaption></figure>'

def product_overview(payload,media):
    fields=payload['fields'];urls=fields.get('image_refs')or[];images={r['index']:r for r in media}
    main=picture(images.get(0),0)if urls else'<div class="review-image-missing">尚未提供产品图片</div>'
    info='<h3>'+e(fields.get('title'))+'</h3>'+pairs([(FIELDS[k],fields.get(k))for k in ('sku','price','currency','category_id','quantity')]+[('目标语言',payload.get('language')),('履约依据',payload.get('fulfillment'))])
    body=section('产品信息','<div class="review-product">'+main+'<div>'+info+'</div></div>')
    if urls:
        body+=section('产品图片（申请固定版本）','<div class="review-gallery">'+''.join(picture(images.get(i),i)for i in range(len(urls)))+'</div><details><summary>图片来源与读取证据</summary><ol>'+''.join('<li>'+e(url)+pairs([('读取 SHA-256',images.get(i,{}).get('source_sha256')),('读取时刻',images.get(i,{}).get('captured_at')),('预览 SHA-256',images.get(i,{}).get('preview_sha256'))])+'</li>'for i,url in enumerate(urls))+'</ol></details>')
    body+=section('产品描述与参数','<p class="review-description">'+e(fields.get('description'))+'</p>'+pairs([('平台、站点与类目规则依据',payload.get('rules_ref'))]))
    attrs=payload.get('attributes')or[]
    if attrs:body+=section('产品参数',table(['参数','值','依据'],[(a['name'],a['value'],a['source_ref'])for a in attrs],'产品参数与依据'))
    ozon=payload.get('ozon')or{}
    pub=ozon.get('publication')
    if pub:body+=section('整卡发布包装与税率（申请固定值）',pairs([('包装深度（mm）',pub['depth']),('包装宽度（mm）',pub['width']),('包装高度（mm）',pub['height']),('含包装重量（g）',pub['weight']),('包装规格依据',pub['source_ref']),('适用 VAT（平台小数）',pub['vat']),('税率依据',pub['vat_source_ref']),('描述属性 ID',pub['description_attribute_id'])]))
    if ozon.get('attributes'):body+=section('平台规格参数（申请固定值）',pairs([('商品类型 ID',ozon.get('type_id'))])+table(['属性编号','值','依据'],[(a['id'],'、'.join(v.get('value')or('词典值 '+str(v.get('dictionary_value_id','未提供')))for v in a['values']),a.get('source_ref'))for a in ozon['attributes']],'平台规格参数与依据'))
    return body

def render(package,media=None):
    media=media or[]
    r=package['request'];f=r['frozen'];p=f['payload'];fields=p['fields'];target=r['target']
    body='<header><p class="review-kicker">私有审阅材料'+(' · 合成验证资料'if r['synthetic']else'')+'</p><h1>上架申请审阅包</h1><p>'+e(fields.get('title'))+'</p><p class="review-boundary">本地申请与审阅不构成独立专业认证或发布批准。导入受理、商品存在、平台审核与可售分别核对。</p></header>'
    if not r['current']:body+='<p class="review-warning">原方案已变化。本文件保留该历史申请的固定内容，不采用最新编辑替换旧版本。</p>'
    if not r['connection_current']:body+='<p class="review-warning">原店铺连接已变化，旧引用不能自动用于当前连接。</p>'
    body+=product_overview(p,media)
    body+=section('申请范围与状态',pairs([('平台',target['platform']),('店铺标识',target['store_ref']),('市场',target['market']),('商品工作项',target['case_id']),('保存修订',f['revision']),('本地申请状态',label(r['status'])),('本地审阅决定',label(r['decision'])),('申请创建时刻',r['created_at']),('本系统整卡提交记录',{'not_performed_by_this_system':'未执行','platform_task_received':'已发送并收到平台任务，非可售确认','operator_attested_after_unknown_dispatch':'未知提交后由负责人核对声明，非传输证明','dispatch_outcome_unknown':'已尝试，结果未知，禁止重发'}.get(package['application_submission'],'未知')),('平台发布已核实',r['platform_submission_verified'])]))
    checks=f['checks'];professional=next((x for x in checks if x['id']=='professional_gate'),None)
    owner=f.get('owner_review')
    gate='尚未通过'if not professional or professional['status']!='prepared'else'经营负责人签收（非独立认证）'if owner and owner.get('current')else'固定版本记为资料已填，独立核查依据仍需另核'
    body+=section('发布前检查（申请固定版本）','<p>平台规则与资质专业核查：<strong>'+e(gate)+'</strong></p>'+table(['检查','记录状态'],[(x['label'],label(x['status']))for x in checks],'固定版本发布前检查')+'<p>资料已填不代表事实、规则、资质或素材使用权已独立核实。</p>')
    if owner:
        body+=section('负责人核查记录（申请固定版本）',table(['项目','记录'],[('签收方式','经营负责人声明，不属于独立认证'),('核对人',owner['reviewer']),('记录时间',owner['reviewed_at']),('记录状态',owner['status']),('记录 SHA256',owner['review_sha256'])],'负责人核查版本')+table(['核查项','结论','依据','说明'],[(owner['requirements'][k],{'confirmed':'已逐项核对','pending':'待核对','not_applicable':'不适用','rejected':'需修改'}.get(v['status'],v['status']),v['source_ref'],v['note'])for k,v in owner['checks'].items()],'负责人逐项核查依据')+'<p>此记录不授权平台写入；资料变化后须重新核对。</p>')
    submission=r.get('system_submission')
    if submission:
        body+=section('本系统整卡提交记录',pairs([('记录状态',label(submission['state']['status'])),('单次提交已开始',submission['state']['dispatch_started']),('平台任务',submission['state']['task_id']),('执行人',submission['state']['operator']),('计划 SHA256',submission['plan_sha256']),('请求 SHA256',submission['body_sha256'])])+'<details><summary>准确提交请求（含原属性保留项）</summary><pre>'+e(json.dumps(submission['body'],ensure_ascii=False,indent=2))+'</pre></details><p>平台任务受理、导入完成、审核通过与可售分别核对；此记录不表示商品已可售。</p>')
    observation=r.get('observation');external=r.get('external');read=r['read']
    receipt=pairs([('读取状态',label(read['status'])),('读取错误',read.get('error')),('平台任务编号',external.get('task_id')if external else None),('外部提交依据',external.get('source_ref')if external else None)])
    if observation:
        receipt+=pairs([('平台观测状态',label(observation['status'])),('观测时刻',observation['observed_at']),('导出核对时观测仍在有效期内',r['last_observation_fresh']),('导入条目已核对',observation['import_confirmed'])])
        imported=r.get('import_record');product=r.get('product_record')
        if imported:
            receipt+=pairs([('平台原始导入状态',imported['status']),('平台导入返回商品 ID',imported['product_id'])])
            if imported.get('errors'):receipt+=table(['错误码','平台错误信息'],[(x['code'],x['message'])for x in imported['errors']],'平台返回错误')
        if product:receipt+=pairs([('准确回读商品 ID',product['entity_id'])])+table(['平台字段','原始值'],product['statuses'].items(),'平台原始状态')
        if r['differences']:receipt+=table(['字段','申请版本','平台回读','核对'],[(FIELDS.get(d['field'],d['field']),d['prepared'],d['observed'],label(d['status']))for d in r['differences']],'申请与平台差异')
        receipt+=table(['接口','响应证据 SHA-256'],[(x['endpoint'],x['sha256'])for x in observation['evidence']],'平台回读证据')
    else:receipt+='<p>尚无实际平台回读证据，不推定已提交或发布成功。</p>'
    body+=section('外部引用与平台回读',receipt)
    body+=section('审阅说明与历史',pairs([('申请说明',r['note']),('最新审阅说明',r['review_note'])])+table(['时刻','动作','本地决定','说明'],[(h['at'],h['action'],label(h['decision']),h['note'])for h in r['history']],'最近申请历史'))
    evidence=[{k:v for k,v in row.items()if k!='content_base64'}for row in media]
    body+=section('版本与完整性',pairs([('申请编号',r['id']),('申请 SHA-256',r['sha256']),('审阅事件 SHA-256',r['event_sha256']),('商品来源 SHA-256',f['source_sha256']),('交付包 SHA-256',f['delivery_package_sha256']),('本导出数据包 SHA-256',digest(canonical([package,evidence]))),('生成时刻（UTC）',datetime.now(timezone.utc).isoformat())]))
    body+='<footer>包含私有业务资料。此离线文件不调用接口、不上传数据、不提供发布或批准操作；检查清单和观测只对应上述固定版本与时刻。</footer>'
    css=generated()+'\n'+(ROOT/'ui/primitives.css').read_text()+'\n'+(ROOT/'ui/listing-review-report.css').read_text()
    light=json.loads((ROOT/'ui/tokens.json').read_text())['tokens']
    css+='\n@media print{:root:not([data-theme]),:root[data-theme]{'+''.join('--ui-'+k+':'+v+';'for k,v in light.items())+'color-scheme:light}}'
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><meta name="referrer" content="no-referrer"><title>上架申请审阅包</title><style>'+css+'</style></head><body><main class="review-report">'+body+'</main></body></html>'
