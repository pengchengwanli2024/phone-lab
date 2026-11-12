"""Per-source draft contracts. Automatic routing is not domain acceptance."""
import hashlib
import json
import re
from sealeap_methodology import method_for,review_requirements

# Source/input revisions change the contract hash, not the unchanged wire shape.
VERSION='source-bound-draft-v2'
FAMILIES={
 'research':['evidence_scope','findings','comparison','validation_plan'],
 'listing':['product_fact_audit','content_draft','field_rule_gaps','review_checks'],
 'creative':['identity_constraints','creative_draft','production_brief','review_checks'],
 'advertising':['metric_scope','diagnosis','test_plan','budget_guards'],
 'inventory':['identity_scope','operations_plan','exceptions','readback_checks'],
 'finance':['scope_and_inputs','calculation_or_gaps','scenario_review','cash_risks'],
 'compliance':['applicability','evidence_gaps','issues_for_review','specialist_checks'],
 'operation_plan':['target_and_action','preconditions','operator_plan','readback_checks','blockers']}
LABELS=dict(research='研究分析',listing='商品文案',creative='创意制作简报',advertising='广告诊断',inventory='库存履约方案',finance='财务口径复核',compliance='合规材料初筛',operation_plan='外部操作准备')


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def contract_for(entry,mode_id=None):
    if entry.get('adapter'):return None
    text=' '.join([entry['id'],entry['title']]).lower()
    rules=[
      ('compliance',r'合规|侵权|专利|商标|vero|compliance|patent|restricted|ip-risk|ppwr'),
      ('operation_plan',r'采购与履约|账户.*配置|收款|payments|procurement|content-management|account-management|catalog-media|listing-management|order-fulfillment|purchase-order|refund|publish|upload|api-patch'),
      ('finance',r'利润|经济性|费用|账单|现金|佣金|结算|pricing|economics|profit|margin|cash|fee-|commission|reimbursement|reconcil'),
      ('listing',r'listing|文案|标题|bullet|copywriting|search-terms|product-description'),
      ('creative',r'创意|图片|视频|分镜|拍摄|ugc|image|video|creative|photo'),
      ('advertising',r'广告|投流|投放|营销|推广|marketing|acos|ppc|advertising|ad-|campaign|attribution|roas'),
      ('inventory',r'库存|补货|履约|物流|发货|售后|退货|inventory|stock|fulfillment|shipping|logistics|fba'),
      ('research',r'选品|研究|竞品|关键词|需求|review|research|keyword|market|niche')]
    family='research';matched='fallback_source_workflow'
    for candidate,pattern in rules:
        match=re.search(pattern,text)
        if match:family=candidate;matched=match.group(0);break
    method=method_for(entry)
    selected=method['mode_methods'].get(mode_id) if mode_id else None
    if mode_id and selected is None:raise ValueError('sealeap_mode_not_in_skill')
    requirements=review_requirements(method)+(selected['inputs']+selected['deliverables'] if selected else [])
    inputs=[r['text'] for r in method['inputs']]
    outputs=[s['text'] for s in entry['sections'] if re.search('交付|输出|output',s['heading'],re.I)]
    required=['marketplace'] if entry['platform']!='cross_platform' else []
    if family in ['advertising','finance','inventory']:required+=['currency','period']
    value=dict(version=VERSION,input_source_revision='registered-input-sources-v1',skill_id=entry['id'],source_sha256=entry['source_sha256'],family=family,label=LABELS[family],
        classification_basis=matched,classification_review='automatically_derived_requires_domain_review',
        required_scope=required,minimum_fact_count=1,sections=FAMILIES[family],
        source_input_excerpt=' '.join(inputs)[:4000] or ('已找到各模式的原文输入；请选择本次模式，再核对对应输入。' if method['mode_methods'] else entry['description']),
        source_delivery_excerpt=' '.join(outputs)[:4000] or entry['description'],
        method_sha256=method['sha256'],source_requirements=requirements,source_extraction_gaps=method['extraction_gaps'],
        mode_id=mode_id,mode_selection_required=method['mode_selection_required'],
        required_source_paths=sorted({'SKILL.md'}|{r['source']['path'] for r in requirements}),
        source_requirement_scope=method['scope'],source_requirement_review='pending_model_and_business_review',
        model_scope='evidence_bound_draft_only',platform_operations_enabled=False,
        acceptance=['exact_source_and_contract_binding','citations_resolve_to_supplied_facts_or_selected_skill_files','output_sections_match_contract','missing_inputs_explicit','human_business_review_required'],
        limits=['Minimum input gating is not validation of every original business input.','Platform rules, rights, credentials and account access are not independently verified.','Model schema/citation checks are not proof of factual correctness or operational completion.'])
    return dict(value,sha256=digest(value))


def input_template(entry,mode=None):
    required=sorted({field for cap in (mode or {}).get('capabilities',[]) for field in cap.get('required_fields',[])})
    return dict(goal=entry['title'],scope=dict(platform=entry['platform'],marketplace=None,currency=None,period=None,target_language='zh'),facts=[],parameters={key:None for key in required})


def validate_input(data,contract):
    if not isinstance(data,dict) or set(data)-{'goal','scope','facts','parameters'}:raise ValueError('sealeap_draft_input_use_template')
    if len(canonical(data))>24000:raise ValueError('sealeap_draft_input_too_large')
    goal=data.get('goal');scope=data.get('scope',{});facts=data.get('facts',[]);parameters=data.get('parameters',{})
    if goal is not None and (not isinstance(goal,str) or len(goal)>1500):raise ValueError('sealeap_draft_goal_invalid')
    if not isinstance(scope,dict) or any(not isinstance(v,(str,type(None))) or isinstance(v,str) and len(v)>300 for v in scope.values()):raise ValueError('sealeap_draft_scope_invalid')
    if set(scope)-{'platform','marketplace','currency','period','product_id','fulfillment','target_language','source_window'}:raise ValueError('sealeap_draft_scope_invalid')
    if not isinstance(parameters,dict) or not isinstance(facts,list) or len(facts)>40:raise ValueError('sealeap_draft_facts_invalid')
    def check_keys(value):
        if isinstance(value,dict):
            if any(re.search(r'password|secret|token|cookie|api_key|authorization',str(k),re.I) for k in value):raise ValueError('sealeap_draft_credentials_require_private_setup')
            for item in value.values():check_keys(item)
        elif isinstance(value,list):
            for item in value:check_keys(item)
    check_keys(parameters)
    missing=[]
    if not isinstance(goal,str) or not goal.strip():missing.append('goal')
    missing.extend('scope.'+key for key in contract['required_scope'] if not scope.get(key))
    known=set();usable=[]
    for fact in facts:
        if not isinstance(fact,dict) or set(fact)-{'id','text','source_ref','label'}:raise ValueError('sealeap_draft_fact_invalid')
        ident=fact.get('id');text=fact.get('text');source=fact.get('source_ref');label=fact.get('label','provided')
        if not isinstance(ident,str) or not re.fullmatch('F[1-9][0-9]?',ident) or ident in known:raise ValueError('sealeap_draft_fact_id_invalid')
        if not isinstance(text,str) or not 0<len(text)<=1500 or not isinstance(source,str) or not 0<len(source)<=500 or label not in ['provided','synthetic','estimate','unknown']:raise ValueError('sealeap_draft_fact_invalid')
        known.add(ident)
        if label!='unknown':usable.append(dict(id=ident,text=text,source_ref=source,label=label))
    if len(usable)<contract['minimum_fact_count']:missing.append('facts_with_source')
    return dict(goal=goal or '',scope=scope,facts=usable,parameters=parameters),missing
