"""Per-question UI location and bounded local reads; never an execution grant."""
import copy
import math
import re
from datetime import date
from agent_runtime.policy import canonical

PAGES = {
 'overview':('overview','运营台'),'workspace':('organization','商品工作区'),'listing':('organization','上架准备'),'workflow':('organization','工作流画布'),
 'orders':('orders','订单'),'store-ops':('orders','日常运营'),'order-imports':('orders','订单导入'),'products':('products','库存'),
 'operations':('operations','通用成本'),'restock':('operations','补货计划'),'models':('connections','模型管理'),'memory':('connections','业务记忆'),
 'intelligence':('intelligence','全球情报'),'research':('research','研究资料'),'pilots':('pilots','商品候选'),'creative':('creative','创意工作室'),
 'agent':('agent','执行记录'),'tasks':('tasks','任务记录'),'organization':('organization','岗位交接'),'exposure':('exposure','经营关联'),
 'platforms':('platforms','平台数据'),'live':('live','Ozon 经营'),'alerts':('alerts','经营提醒'),'support':('support','客服'),
 'insights':('insights','选品与评论'),'skills':('skills','技能'),'assistant-team':('connections','智能体团队'),'operating-control':('connections','自动经营'),'connections':('connections','接入与知识'),'phones':('intelligence','手机墙')}
SECTIONS={'evidence':'证据与选品','social':'社交观察','overview':'概览','research':'市场研究','media':'图片与视频','tasks':'任务记录','sales-trend':'销售趋势','inventory-statistics':'库存统计','order-status':'发货单状态','platform-sales':'平台销售构成',
 'order-detail':'订单详情','product-detail':'商品详情','cost':'成本测算','stock':'补货测算','plan':'工作计划','content':'商品内容',
 'creative':'图片与视频','review':'资料核对','sources':'资料来源','delivery':'交付核对','details':'详情','list':'列表','map':'地图'}
ENTITY_KINDS=('case','order','product','intel','task','chart','skill','model','aircraft','vessel')
FILTER_KEYS=('platform','market','store_id','store_ref','query','status','source','country','category','hours','scope','view','time','date_from','date_to')
INPUT_KEYS=('sku','title','description','category_id','currency','price','purchase_cost','domestic_shipping','packaging','fulfillment_cost','electronic_fee','commission_rate','payment_rate','return_rate','ad_rate',
 'sold_units','observed_days','window_days','lead_time_days','safety_days','available','on_order','pack_size','moq','quantity','budget')
PAGE_CONTEXT_SCHEMA={'type':'object','properties':{
 'page':{'type':'string','enum':list(PAGES)},'section':{'type':'string','maxLength':64},'demo':{'type':'boolean'},'source':{'type':'string','enum':['live','local','unavailable','stale']},
 'entity':{'type':'object','properties':{'kind':{'type':'string','enum':list(ENTITY_KINDS)},'id':{'type':'string','maxLength':180},'name':{'type':'string','maxLength':120}},'required':['kind','id'],'additionalProperties':False},
 'filters':{'type':'object','properties':{k:{'type':'string','maxLength':160}for k in FILTER_KEYS},'additionalProperties':False},
 'source_refs':{'type':'object','maxProperties':8,'additionalProperties':{'type':'string','pattern':'^[a-f0-9]{64}$'}},
 'input':{'type':'object','properties':{k:{'type':['string','number','null']}for k in INPUT_KEYS},'additionalProperties':False},
 'errors':{'type':'array','maxItems':3,'items':{'type':'string','maxLength':300}},
 'intent':{'type':'string','enum':['current_page','original_thread']}},'required':['page'],'additionalProperties':False}


def validate_page_context(value, scope):
    try:size=len(canonical(value).encode())
    except (ValueError,TypeError,RecursionError):raise ValueError('copilot_invalid_page_context')from None
    if not isinstance(value,dict) or set(value)-set(PAGE_CONTEXT_SCHEMA['properties']) or size>6000:
        raise ValueError('copilot_invalid_page_context')
    page=value.get('page')
    if not isinstance(page,str)or page not in PAGES or value.get('intent','current_page') not in ('current_page','original_thread'):raise ValueError('copilot_invalid_page_context')
    if 'source'in value and value['source']not in ('live','local','unavailable','stale'):raise ValueError('copilot_invalid_page_context')
    expected=PAGES[page][0]
    # A case-bound cost screen intentionally retains its organization permission.
    if expected!=scope['module'] and not(page in ('operations','restock') and scope['module']=='organization' and scope.get('entity',{}).get('kind')=='case'):
        raise ValueError('copilot_page_scope_changed')
    if 'demo'in value and (type(value['demo'])is not bool or value['demo']!=bool(scope.get('demo'))):raise ValueError('copilot_page_scope_changed')
    if 'section'in value and(not isinstance(value['section'],str)or not re.fullmatch('[a-zA-Z0-9_-]{1,64}',value['section'])):raise ValueError('copilot_invalid_page_context')
    filters=value.get('filters',{})
    if not isinstance(filters,dict)or set(filters)-set(FILTER_KEYS):raise ValueError('copilot_invalid_page_context')
    for key,item in filters.items():
        if not isinstance(item,str)or len(item)>160 or '\n'in item:raise ValueError('copilot_invalid_page_context')
        if key in ('platform','market','store_id')and scope.get(key,'all')not in ('all',item):raise ValueError('copilot_page_scope_changed')
        if key.startswith('date_'):
            try:date.fromisoformat(item)
            except ValueError:raise ValueError('copilot_invalid_page_context')from None
    entity=value.get('entity')
    if 'entity'in value:
        if not isinstance(entity,dict)or set(entity)-{'kind','id','name'}or entity.get('kind')not in ENTITY_KINDS or not isinstance(entity.get('id'),str)or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,180}',entity['id']):raise ValueError('copilot_invalid_page_context')
        bound=scope.get('entity',{})
        if entity['kind']!='chart'and bound and (entity['kind'],entity['id'])!=(bound.get('kind'),bound.get('id')):raise ValueError('copilot_page_scope_changed')
        if 'name'in entity and(not isinstance(entity['name'],str)or len(entity['name'])>120):raise ValueError('copilot_invalid_page_context')
    refs=value.get('source_refs',{})
    if not isinstance(refs,dict)or len(refs)>8 or any(not re.fullmatch('[a-z_]{1,40}',k)or not isinstance(v,str)or not re.fullmatch('[a-f0-9]{64}',v)for k,v in refs.items()):raise ValueError('copilot_invalid_page_context')
    from .store_scope import selected, arguments
    if selected(scope):arguments(scope,value)
    elif page=='store-ops' and filters.get('scope','all')!='all':raise ValueError('copilot_page_scope_changed')
    inputs=value.get('input',{})
    if not isinstance(inputs,dict)or set(inputs)-set(INPUT_KEYS)or any(type(v)not in (str,int,float,type(None))or isinstance(v,str)and len(v)>500 or type(v)is float and not math.isfinite(v) for v in inputs.values()):raise ValueError('copilot_invalid_page_context')
    errors=value.get('errors',[])
    if not isinstance(errors,list)or len(errors)>3 or any(not isinstance(v,str)or len(v)>300 for v in errors):raise ValueError('copilot_invalid_page_context')
    encoded=canonical(value)
    if re.search(r'(?i)(bearer\s|sk-[a-z0-9]{16}|-----BEGIN .*PRIVATE KEY|/Users/|/home/)',encoded):raise ValueError('copilot_invalid_page_context')
    return copy.deepcopy(value)


def read_page(service, scope, page):
    from .reads import filters as scope_filters, projection
    from agent_runtime.policy import project
    value=validate_page_context(page,scope);route=value['page'];entity=value.get('entity')or scope.get('entity')or{};filters=scope_filters(scope)
    filters.update({k:v for k,v in value.get('filters',{}).items()if k in filters})
    result={'page':route,'label':PAGES[route][1],'section':value.get('section'),'section_label':SECTIONS.get(value.get('section'),'当前页面'),
            'filters':{**value.get('filters',{}),**filters},'selection':entity,'displayed_source_refs':value.get('source_refs',{}),'ui_input':value.get('input',{}),'ui_errors':value.get('errors',[]),
            'ui_state_verified':False,'external_execution_allowed':False,'data':None,'source_status':'not_available'}
    try:
        if route=='overview':
            data=service.invoke('commerce_dashboard',filters,'local')
            result['data']={k:copy.deepcopy(data[k])for k in ('sales','sales_exact','sales_label','currency','orders','pending','stock_alerts','rate_note','sales_summary','inventory','updated_at','data_source')if k in data}
            actual={'sales':(data.get('sales_summary')or{}).get('source_sha256'),'stock':(data.get('inventory')or{}).get('source_sha256')}
        elif route=='store-ops' and scope.get('store_scope'):
            from .store_scope import arguments, validate_binding, projection as store_projection
            validate_binding(service,scope,value)
            data=service.invoke('commerce_store_workbench',arguments(scope,value),'local')
            result['data']=store_projection(data);actual={'store_scope':data['selected_scope']['catalog_sha256']}
        elif route in ('orders','store-ops','order-imports','products'):
            tool='commerce_products_list'if route=='products'else'commerce_orders_list'
            args={**filters,**({'query':value.get('filters',{}).get('query','')[:100],'status':value.get('filters',{}).get('status','')[:40]}if tool.endswith('orders_list')else{})}
            data=service.invoke(tool,args,'local');key='products'if route=='products'else'orders';rows=data[key]
            if route=='products':rows=[r for r in rows if value.get('filters',{}).get('query','').lower()in canonical(r).lower()]
            if entity.get('kind')in ('order','product'):
                rows=[r for r in rows if entity['id']in (str(r.get('id','')),str(r.get('sku','')),str(r.get('stock_row_key','')))]
            result['data']=projection(tool,{**data,key:rows});result['data']['visible_total']=len(rows)
            if entity.get('kind')in ('order','product'):
                fields=('sku','name','product','platform','market','amount','currency','status','available','threshold','price','scope','observed_at','source_sha256','stale','data_source')
                result['data']['selected']=[{k:r[k]for k in fields if k in r}for r in rows[:3]]
                result['data']['entity_details_available']=True
            actual={'record':rows[0].get('source_sha256')}if rows else{}
        elif entity.get('kind')=='case':
            if scope.get('entity')!={'kind':'case','id':entity['id']}:raise ValueError('copilot_page_scope_changed')
            data=service.invoke('commerce_workspace_get',{'case_id':entity['id']},'local');result['data']=projection('commerce_workspace_get',data);actual={'case':data['source_sha256']}
            target=value.get('filters',{})
            if route=='listing' and all(target.get(k) for k in ('platform','store_ref','market')):
                listing=service.invoke('commerce_listing_get',dict(case_id=entity['id'],**{k:target[k] for k in ('platform','store_ref','market')}),'local')
                result['data']['listing']={k:copy.deepcopy(listing[k])for k in ('target','name','revision','stale','missing','checks','preview_sha256')if k in listing}
                result['data']['listing']['fields']={k:listing.get('payload',{}).get('fields',{}).get(k)for k in ('sku','title','price','currency','quantity')}
                actual['listing']=listing.get('preview_sha256')
        elif route in ('intelligence','research'):
            if entity.get('kind')=='intel':
                data=service.invoke('commerce_intel_item_get',{'item_id':entity['id']},'local');result['data']=project('commerce_intel_item_get',data)
                docs=service.invoke('commerce_intel_article_list',{'item_id':entity['id']},'local').get('articles',[])
                doc=docs[0]if docs else{}
                article=doc.get('article')or{}
                if doc.get('status')=='ready'and doc.get('record_sha256')==data.get('record_sha256'):
                    from article_binding import bind
                    article=bind(article)
                    result['data']['article']={k:article[k]for k in ('content_sha256','record_sha256','source_url','captured_at')}
                    result['data']['article'].update(text=article['text'][:2000],text_truncated=len(article['text'])>2000,source_trust='untrusted_reference_data')
                else:result['data']['article_status']=doc.get('status','not_captured')
            else:
                display=value.get('filters',{})
                args={k:display[k]for k in ('source','category','country','hours','scope','view')if k in display}
                data=service.invoke('commerce_intel_search',{**args,'query':display.get('query','')[:100],'limit':'20'},'local');result['data']=project('commerce_intel_search',data)
            actual={'intel':data.get('record_sha256'),'article':result['data'].get('article',{}).get('content_sha256')}if entity.get('kind')=='intel'else{}
        elif route=='assistant-team':
            catalog=service.assistant_team.catalog()
            data={'profiles':[{k:p[k]for k in ('id','name','role_id','enabled','revision')}for p in catalog['profiles']],
                  'channels':[{k:c[k]for k in ('id','name','member_ids','revision')}for c in catalog['channels']]}
            result['data']=data;actual={}
        elif route=='operating-control':
            data=service.operating_control.get(bool(scope.get('demo')))
            result['data']={k:data[k]for k in ('scope','budget','mobile','autonomy','tasks','decisions','configuration_revision')};actual={}
        elif route=='models':
            data=service.invoke('commerce_model_list',{},'local');rows=[r for r in data.get('models',[])if (not entity.get('id')or r['id']==entity['id'])and value.get('filters',{}).get('query','').lower()in canonical({k:r.get(k)for k in ('id','label','provider')}).lower()];result['data']={'models':[{k:r[k]for k in ('id','label','provider','selectable')if k in r}for r in rows[:30]]};actual={}
        elif route in ('tasks','agent'):
            data=service.invoke('commerce_task_list',{},'local');rows=data.get('tasks',[])
            if entity.get('kind')=='task':rows=[r for r in rows if r['id']==entity['id']]
            query=value.get('filters',{}).get('query','').lower();status=value.get('filters',{}).get('status','all')
            rows=[r for r in rows if query in (r['id']+' '+str(r.get('input',{}).get('title',''))).lower()and(status=='all'or status==r['status']or status=='active'and r['status']in ('queued','running','cancelling')or status=='attention'and r['status']in ('blocked','failed','interrupted','unknown','needs_input','awaiting_input','awaiting_review','review','partial'))]
            result['data']={'tasks':[{'id':r['id'],'status':r['status'],'title':r.get('input',{}).get('title','')}for r in rows[:20]],'total':len(rows)};actual={}
        elif route=='skills':
            if entity.get('kind')=='skill':
                data=service.invoke('commerce_skills_get',{'skill_id':entity['id']},'local');result['data']=projection('commerce_skills_get',data)
            else:
                data=service.invoke('commerce_skills_search',{'query':value.get('filters',{}).get('query','')[:100],'limit':5},'local');result['data']=projection('commerce_skills_search',data)
            actual={}
        elif route in ('connections','platforms','live'):
            data=service.invoke('commerce_live_status',{},'local');result['data']={k:data[k]for k in ('configured','orders','stock','sales','stock_basis','orders_scope_confirmed')if k in data};actual={}
        else:return result
        result['source_status']='not_connected'if data.get('data_source')=='not_connected'else'read';result['display_changed']=any(actual.get(key)!=sha for key,sha in value.get('source_refs',{}).items()if key in actual)
        if route=='overview'and value.get('filters',{}).get('date_from'):
            summary=data.get('sales_summary')or{}
            result['display_changed']=result['display_changed']or any(value['filters'].get(key)!=summary.get(key)for key in ('date_from','date_to'))
        if len(canonical(result).encode())>15000:result['data']=None;result['source_status']='too_large'
    except ValueError as error:
        result['source_status']='unavailable';code=str(error);result['error_code']=code if re.fullmatch('[a-z_]{1,80}',code)else'page_read_failed'
    return result
