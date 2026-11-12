"""Explicit offline scopes and invented acceptance examples; no platform tariffs."""
import copy
import json

FUNCTION_ADAPTERS={
 'sealeap-walmart-wfs-box-reconciliation':('check_box_manifest.py','walmart_boxes','Input plan/box consistency only; physical contents and shipment status are unverified.'),
 'sealeap-amazon-ca-apparel-ads':('budget_mix_check.py','ca_budget','Historical course allocation comparison only; not current account budget advice.'),
 'sealeap-apollo-ad-planning':('ad_economics.py','apollo_ads','Evidence-labelled contribution and ad economics only; no campaign launch.'),
 'sealeap-apollo-price-discounts':('discount_plan.py','discounts','Offline SKU discount draft and scope checks only; no price or promotion write.'),
 'sealeap-apollo-batch-title-rewrite':('check_titles.py','titles','Title validation against caller-declared policy only; policy authenticity and publishing unverified.'),
 'sealeap-apollo-competitor-monitor':('snapshots.py','snapshots','Supplied snapshot normalization and comparable differences only; no persistent monitor or collection.'),
 'sealeap-amazon-prime-day-planning':('filter_insights.py','prime_insights','Bundled 2025 historical reference filtering only; not current insights or a full event plan.'),
 'sealeap-ozon-mpstats-data-audit':('validate_data.py','mpstats_audit','Mapped external estimate structure and declared as-of freshness only; no API or source authenticity proof.')}


def example_input(operation,source_folder):
    if operation=='walmart_boxes':return {'input_kind':'synthetic','plan':[{'shipment_id':'SYN-SHIP','destination':'SYN-FC','sku':'SYN-SKU','units':3}],
      'boxes':[{'shipment_id':'SYN-SHIP','destination':'SYN-FC','box_id':'SYN-BOX','receiving_label_id':'SYN-LABEL','items':[{'sku':'SYN-SKU','units':3}]}]}
    if operation=='ca_budget':return dict(input_kind='synthetic',product='coat',stage='new',allocation=dict(sp_manual_keywords=40,sb_sbv=30,sp_auto=20,sp_product_targeting=10))
    if operation=='apollo_ads':
        def cell(value,ratio=False):return dict(value=value,label='ASSUMPTION',evidence_id='SYN-EVIDENCE',**({} if ratio else {'currency':'USD'}))
        return dict(input_kind='synthetic',currency='USD',evidence=[dict(id='SYN-EVIDENCE',source='Invented acceptance fixture, not account data',collected_at='2026-11-01T00:00:00Z',data_period='synthetic cohort')],
            net_revenue_per_unit=cell(40),ad_revenue_per_order=cell(40),unit_costs={k:cell(v) for k,v in dict(purchase=10,inbound=1,platform=2,fulfillment=4,storage=0,returns=1,other=0).items()},target_acos=cell(.2,True),ad_cvr=cell(.1,True))
    if operation=='discounts':return dict(input_kind='synthetic',store_ref='synthetic-store',marketplace='US',snapshot_at='2026-11-01T00:00:00Z',evidence_id='SYN-EVIDENCE',targets=[dict(sku='SYN-SKU',promotion_id='SYN-ACTIVITY',target_percent=15)],activities=[dict(promotion_id='SYN-ACTIVITY',status='ACTIVE',items=[dict(sku='SYN-SKU',discount_percent=10)])])
    if operation=='titles':return dict(input_kind='synthetic',rows=[dict(sku='SYN-SKU',marketplace='US',product_type='SYNTHETIC_TYPE',title='Synthetic storage box',highlight='Invented test draft')],policy=dict(verified=True,source='SYNTHETIC policy, not current Amazon rules',checked_at='2026-11-01',marketplace='US',product_types=['SYNTHETIC_TYPE'],title_max=100,highlight_max=125,count_method='codepoints'))
    if operation=='snapshots':
        a=dict(own_asin='SYNTHETIC0',asin='SYNTHETIC1',marketplace='US',source='synthetic:export',data_mode='SYNTHETIC',captured_at='2026-11-01T00:00:00Z',evidence_id='SYN-EVIDENCE',verification_reason='Invented matching fixture',status='verified',detail_asin='SYNTHETIC1',relevance='matched',metrics=dict(price=dict(value=20,unit='USD',label='ASSUMPTION',period='synthetic comparable period',evidence_id='SYN-EVIDENCE')))
        b=copy.deepcopy(a);b['captured_at']='2026-11-02T00:00:00Z';b['metrics']['price']['value']=18
        return dict(input_kind='synthetic',records=[a,b])
    if operation=='prime_insights':return dict(input_kind='synthetic',marketplace='US',basis_note='Test filter over bundled 2025 reference data, not current performance.')
    if operation=='mpstats_audit':return dict(input_kind='synthetic',document=json.loads((source_folder/'references/synthetic-data.json').read_text()),as_of='2026-09-28',max_age_days=7)
    raise ValueError('sealeap_example_not_defined')
