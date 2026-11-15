"""Explicit, resumable eight-family synthetic model acceptance. No platform actions."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime import STATE,request

SAMPLES=[
 ('sealeap-ebay-category-keywords','为合成收纳盒制作候选查询、待核类目属性和排除词；没有真实搜索结果，勿声称已检索。',[]),
 ('sealeap-ebay-listing-attributes','制作合成收纳盒的字段级文案修改草稿；原文案只写Storage Box，无类目必填属性证据。',[]),
 ('sealeap-mercadolibre-product-visuals-clips','把合成商品图片元素重新组合成图序和短视频分镜文字简报；没有上传素材或权利文件，不生成媒体或声称已验收。',[]),
 ('sealeap-ebay-advertising','区分General与Priority广告测试所需证据，评估合成数据可确定部分；勿投放或假定当期费率。',['合成Priority报表：点击100，广告花费USD 20，归因销售额USD 100，成交订单5；归因窗口与退款完整性未知。']),
 ('sealeap-ebay-combined-shipping-audit','为同买家两件合成商品设计合箱测试矩阵与实收实付桥接；不发票、不退款。',['合成购物篮2件，每件包装重量0.3kg，合箱后0.65kg；承运合箱报价USD 6，已收运费USD 8。付款状态与平台合并资格未知。']),
 ('sealeap-ebay-ad-attribution','对合成订单记录制作去重与费用差异复核草稿；同一订单的Direct和Halo不可相加。',['合成订单LINE-A成交USD 30，Direct表和Halo表均各记录USD 30；账单广告费USD 3，真实计费规则和费率基数未提供。']),
 ('sealeap-ebay-brand-ip-triage','制作合成疑似图片抄用的权利证据矩阵；权利地域及授权未知，不作侵权定论或发送投诉。',['合成材料只声称两张图外观相似；未提供原始图、作者、创作时间、权属或授权文件。']),
 ('sealeap-athena-1688-procurement','制作合成采购的操作准备方案、阻断项和回读要求；未授权下单、付款、联系或收货确认。',['合成报价为每件CNY 10，数量20件；含税、运费、库存、供应商身份和履约时间未知。'])]


def main():
    folder=STATE.parent;folder.mkdir(parents=True,exist_ok=True)
    path=folder/'model-samples-private.json';records=json.loads(path.read_text()) if path.exists() else []
    for ident,goal,extra in SAMPLES:
        if any(row['skill_id']==ident for row in records):continue
        entry=request('commerce_skills_get',{'skill_id':ident},'test')
        value=entry['draft_input_template'];value['goal']=goal
        value['scope'].update(marketplace='synthetic-US' if 'mercado' not in ident and '1688' not in ident else 'synthetic-MX' if 'mercado' in ident else 'synthetic-CN',currency='CNY' if '1688' in ident else 'USD',period='synthetic-2026-10')
        texts=['合成测试商品为无品牌PP蓝色收纳盒，尺寸20×10×5cm，包装仅含1个盒子；未提供任何销量、认证、用户口碑或权利证明。']+extra
        value['facts']=[dict(id='F'+str(i+1),text=text,source_ref='synthetic_acceptance_fixture',label='synthetic') for i,text in enumerate(texts)]
        mode=entry['subcapabilities'][0]['name'] if entry.get('subcapabilities') else None
        case=request('commerce_skills_prepare',dict(skill_id=ident,input=value,synthetic=True,idempotency_key='workflow-model-case-v1-'+ident,**({'mode_id':mode} if mode else {})),'test')
        row=dict(skill_id=ident,family=entry['draft_contract']['family'],case_id=case['id'],key='workflow-model-draft-v1-'+ident,draft_id=None,status='not_requested')
        # Persist the request key before send; an interrupted send is never recreated.
        records.append(row);path.write_text(json.dumps(records,ensure_ascii=False,indent=2))
        row['status']='send_attempted';path.write_text(json.dumps(records,ensure_ascii=False,indent=2))
        try:
            item=request('commerce_skills_generate',{'case_id':case['id'],'idempotency_key':row['key']},'test');row.update(draft_id=item['id'],status=item['status'])
        except Exception as error:row.update(status='send_outcome_unknown',error_type=type(error).__name__)
        path.write_text(json.dumps(records,ensure_ascii=False,indent=2))
        # Bound concurrent actual requests without replaying a request key.
        while sum(r['status'] in ['queued','running'] for r in records)>=2:
            poll(records,path);time.sleep(1)
    while any(r['status'] in ['queued','running'] for r in records):poll(records,path);time.sleep(1)
    results=[]
    for row in records:
        item=request('commerce_skills_draft_get',{'draft_id':row['draft_id']},'test') if row.get('draft_id') else {}
        result=item.get('result') or {};results.append(dict(skill_id=row['skill_id'],family=row['family'],status=row['status'],sections=len(result.get('sections',[])),questions=len(result.get('questions',[])),citations_validated=bool(result.get('sections')),tools_enabled=result.get('tools_enabled'),source_matches=item.get('source_matches_current'),error=result.get('error')))
    output=dict(synthetic=True,actual_configured_model=True,platform_operations_executed=False,samples=results)
    (folder/'model-result.json').write_text(json.dumps(output,ensure_ascii=False,indent=2));print(json.dumps(output,ensure_ascii=False))


def poll(records,path):
    for row in records:
        if row.get('draft_id') and row['status'] in ['queued','running']:
            row['status']=request('commerce_skills_draft_get',{'draft_id':row['draft_id']},'test')['status']
    path.write_text(json.dumps(records,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
