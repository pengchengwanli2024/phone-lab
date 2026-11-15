"""Versioned listing preparation over existing product evidence and form drafts.

This module has no marketplace transport or second approval/task ledger.
"""
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import urlsplit
from research import canonical, digest

PLATFORMS={'ozon':'Ozon','tiktok':'TikTok Shop','amazon':'Amazon','mercado':'Mercado Libre',
           'temu':'Temu','shopify':'Shopify','woocommerce':'WooCommerce'}
FIELDS=('sku','title','description','category_id','price','currency','quantity','image_refs')


def definitions(schema,string):
    target={'case_id':string,'platform':{'type':'string','enum':list(PLATFORMS)},
            'store_ref':{'type':'string','maxLength':100},'market':{'type':'string','maxLength':2}}
    return [
        ('commerce_listing_get','读取同商品、目标店铺与市场的上架方案及准备缺项；不访问平台',schema(target,list(target))),
        ('commerce_listing_save','按商品来源和草稿修订保存目标店铺的上架资料；不批准或提交平台',schema({**target,'payload':{'type':'object'},'expected_revision':{'type':'integer','minimum':0},'expected_source_sha256':string},[*target,'payload','expected_revision','expected_source_sha256'])),
        ('commerce_listing_export','导出准确预览版本的私有上架准备包及未关闭检查；不是平台导入格式或发布回执',schema({**target,'expected_preview_sha256':string},[*target,'expected_preview_sha256'])),
        ('commerce_store_workbench','读取当前模式的日常运营待办、商品及通知接入状态；不同步平台或发送消息',schema({'demo':{'type':'boolean'}})),
    ]


def clean_text(value,maximum=500):
    if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError('listing_invalid_text')
    return value.strip()


def validate_payload(payload):
    base={'fields','language','fulfillment','rules_ref','attributes'}
    if type(payload) is not dict or set(payload)-{'ozon'}!=base:raise ValueError('listing_invalid_payload')
    fields=payload['fields']
    if type(fields) is not dict or set(fields)!=set(FIELDS):raise ValueError('listing_invalid_fields')
    value={}
    for key in ('sku','title','description','category_id','currency'):
        value[key]=clean_text(fields[key],10000 if key=='description' else 500)
    if value['currency'] and not re.fullmatch('[A-Z]{3}',value['currency']):raise ValueError('listing_invalid_currency')
    price=fields['price']
    if price not in ('',None):
        if type(price) not in (str,int,float) or not re.fullmatch(r'\d{1,13}(?:\.\d{1,8})?',str(price)):raise ValueError('listing_invalid_price')
        try:
            amount=Decimal(str(price))
            if not amount.is_finite() or not 0<amount<=10**12:raise InvalidOperation()
        except InvalidOperation:raise ValueError('listing_invalid_price') from None
        price=format(amount,'f')
    value['price']=price or ''
    quantity=fields['quantity']
    if quantity is not None and (type(quantity) is not int or not 0<=quantity<=10**9):raise ValueError('listing_invalid_quantity')
    value['quantity']=quantity
    images=fields['image_refs']
    if type(images) is not list or len(images)>20:raise ValueError('listing_invalid_images')
    for image in images:
        clean_text(image,2000)
        try:
            url=urlsplit(image)
            if url.scheme!='https' or not url.hostname or url.username or url.password or url.port not in (None,443):raise ValueError()
        except ValueError:raise ValueError('listing_invalid_images') from None
    value['image_refs']=list(dict.fromkeys(images))
    attributes=payload['attributes']
    if type(attributes) is not list or len(attributes)>100:raise ValueError('listing_invalid_attributes')
    result=[];seen=set()
    for row in attributes:
        if type(row) is not dict or set(row)!={'name','value','source_ref'}:raise ValueError('listing_invalid_attributes')
        row={k:clean_text(v,1000) for k,v in row.items()}
        if not row['name'] or row['name'].casefold() in seen:raise ValueError('listing_invalid_attributes')
        seen.add(row['name'].casefold());result.append(row)
    extra={}
    if 'ozon'in payload:
        from ozon_listing_schema import validate_ozon
        extra['ozon']=validate_ozon(payload['ozon'])
    return {'fields':value,'attributes':result,**{k:clean_text(payload[k],1000) for k in ('language','fulfillment','rules_ref')},**extra}


class ListingWorkspace:
    def __init__(self,service):
        self.service=service;self.workspace=service.product_workspace;self.core=service.core

    def scope(self,case_id,platform,store_ref,market):
        if platform not in PLATFORMS:raise ValueError('listing_invalid_platform')
        store_ref=clean_text(store_ref,100)
        if re.search(r'://|bearer\s|sk-[a-zA-Z0-9]{16}',store_ref,re.I):raise ValueError('listing_invalid_store')
        if market and not re.fullmatch('[A-Z]{2}',market):raise ValueError('listing_invalid_market')
        self.workspace.org.case(case_id)
        target=dict(case_id=case_id,platform=platform,store_ref=store_ref,market=market)
        return target,dict(module='product_workspace',form='listing_'+digest(canonical(target))[:32],case_id=case_id)

    def saved_targets(self,case_id,source_sha256):
        result=[]
        with self.core.db() as db:
            rows=db.execute('SELECT scope,payload,revision,updated FROM form_drafts').fetchall()
        for raw_scope,raw_payload,revision,updated in rows:
            scope=json.loads(raw_scope)
            if scope.get('module')!='product_workspace' or scope.get('case_id')!=case_id or not scope.get('form','').startswith('listing_'):continue
            envelope=json.loads(raw_payload);target=envelope.get('target')
            # Early local checkpoints remain directly readable by their target;
            # only explicitly stored identities enter the selectable directory.
            if not target:continue
            _,expected=self.scope(**target)
            if expected!=scope:raise ValueError('listing_target_binding_changed')
            result.append({**target,'revision':revision,'saved_at':updated,'stale':envelope['source_sha256']!=source_sha256})
        return sorted(result,key=lambda r:(r['platform'],r['store_ref'],r['market']))

    def get(self,case_id,platform,store_ref,market):
        target,scope=self.scope(case_id,platform,store_ref,market)
        snapshot=self.workspace.get(case_id);saved=self.service.form_drafts.get(scope);envelope=saved['payload']
        invalid_source_fields=[]
        if envelope:payload=envelope['data']
        else:
            fields={k:'' for k in FIELDS};fields.update(quantity=None,image_refs=[])
            # Seed only the same product's source fields. A cross-platform plan
            # remains unverified and never updates those original facts.
            store_attributes=None
            for source in reversed(snapshot['content_sources']):
                if source.get('fresh') and source.get('current'):
                    fields.update({r['key']:r['value'] for r in source['document']['records'] if r['key'] in FIELDS})
                    if platform=='ozon'and store_ref=='ozon-live'and source['document']['origin_ref']=='private-export:ozon-'+case_id:
                        values={r['key']:r['value']for r in source['document']['records']}
                        if values.get('type_id')and values.get('attributes')is not None:
                            store_attributes={'type_id':int(values['type_id']),'attributes':[
                                {'id':int(a['id']),'values':[{'dictionary_value_id':int(v['dictionary_value_id']),'value':v['value']}for v in a['values']],
                                 'source_ref':source['id']+':attributes:'+a['id']}for a in values['attributes']if a.get('complex_id','0')=='0']}
            draft=snapshot['forms']['content']
            if draft['payload'] and not draft['stale']:fields.update(draft['payload'].get('fields',{}))
            blank={k:'' for k in FIELDS};blank.update(quantity=None,image_refs=[])
            payload={'fields':blank,'language':'','fulfillment':'','rules_ref':'','attributes':[]}
            # Old content checkpoints allow partially typed values. Keep an
            # explicit issue instead of crashing the editor or coercing a value
            # such as True into a valid quantity/price.
            for key,value in fields.items():
                candidate={**payload,'fields':{**payload['fields'],key:value}}
                try:payload=validate_payload(candidate)
                except ValueError:invalid_source_fields.append(key)
            if store_attributes is not None:
                try:payload=validate_payload({**payload,'ozon':store_attributes})
                except ValueError:invalid_source_fields.append('ozon')
        stale=bool(envelope and envelope['source_sha256']!=snapshot['source_sha256'])
        fields=payload['fields'];checks=[]
        def check(ident,label,ok,status='missing'):
            checks.append(dict(id=ident,label=label,status='prepared' if ok else status))
        check('identity','目标店铺与国家/市场已填写',bool(target['store_ref'] and target['market']))
        check('content','SKU、标题、描述与类目资料',all(fields.get(k) for k in ('sku','title','description','category_id')))
        check('offer','原币售价与明确数量',bool(fields.get('price') and fields.get('currency') and fields.get('quantity') is not None))
        check('media','图片链接及原素材交付审阅',bool(fields.get('image_refs')) and snapshot['delivery_review']['status']=='local_review_recorded')
        check('locale','目标语言与履约方案',bool(payload['language'] and payload['fulfillment']))
        check('rules','平台/站点/类目规则依据',bool(payload['rules_ref']))
        check('attributes','所填属性均带资料依据',all(r['value'] and r['source_ref'] for r in payload['attributes']))
        check('source','当前商品资料版本',not stale,'stale')
        check('source_fields','载入字段格式与类型',not invalid_source_fields)
        owner=self.service.owner_reviews.state(target)
        owner_current=owner['current']and snapshot['delivery_review']['professional_gate']=='PASS'
        check('professional_gate','平台规则与资质专业核查',owner_current,'blocked')
        check('platform_adapter','平台提交与发布后回读适配',False,'blocked')
        platform_schema=self.service.listing_schema.evaluate(target,payload,snapshot['case']['scope'].get('synthetic')is True)
        check('platform_schema','平台类目与属性结构',platform_schema['status']=='limited_check_passed','blocked')
        preview=dict(schema='commerce-listing-preparation-v1',target=target,payload=payload,
                     source_sha256=snapshot['source_sha256'],saved_source_sha256=envelope['source_sha256'] if envelope else None,
                     revision=saved['revision'],checks=checks,delivery_package_sha256=snapshot['delivery_review']['package_sha256'],
                     delivery_status=snapshot['delivery_review']['status'],invalid_source_fields=invalid_source_fields,platform_schema=platform_schema)
        # Keep unsigned historical preparation hashes stable; signed applications
        # additionally freeze the exact scoped owner statement, never execution authority.
        if owner['review_id']:
            preview['owner_review']={k:owner[k]for k in ('review_id','review_sha256','reviewer','reviewed_at','policy','decision','status','independent_certification','external_execution_allowed')}
            preview['owner_review']['current']=owner_current
            preview['owner_review'].update(checks=owner['recorded_checks'],requirements=owner['requirements'],binding_sha256=owner['recorded_binding_sha256'])
        return {**preview,'name':snapshot['name'],'platform_name':PLATFORMS[platform],
                'platforms':PLATFORMS,'stale':stale,'saved_at':saved['saved_at'],
                'missing':[r['id'] for r in checks if r['status']!='prepared'],
                'preview_sha256':digest(canonical(preview)),'external_execution_allowed':False,
                'saved_targets':self.saved_targets(case_id,snapshot['source_sha256']),
                'owner_review_available':True,'rules_independently_verified':False,'synthetic':snapshot['case']['scope'].get('synthetic') is True}

    def save(self,case_id,platform,store_ref,market,payload,expected_revision,expected_source_sha256):
        payload=validate_payload(payload);target,scope=self.scope(case_id,platform,store_ref,market)
        with self.core.atomic():
            self.workspace.guard(case_id,expected_source_sha256)
            self.service.form_drafts.save(scope,{'data':payload,'source_sha256':expected_source_sha256,'target':target},expected_revision)
            return self.get(**target)

    def export(self,case_id,platform,store_ref,market,expected_preview_sha256):
        with self.core.atomic():
            value=self.get(case_id,platform,store_ref,market)
            if value['preview_sha256']!=expected_preview_sha256:raise ValueError('listing_preview_changed')
            if not value['revision']:raise ValueError('listing_save_required')
            if value['stale']:raise ValueError('workspace_source_changed')
            body={'schema':'commerce-private-listing-package-v1','preflight':value,
                  'platform_submission':'not_performed','platform_import_format':False,
                  'contains_private_business_data':True,'external_execution_allowed':False}
            return {'filename':'listing-'+platform+'-'+case_id+'.json','content':json.dumps(body,ensure_ascii=False,indent=2)}

    def invoke(self,name,args):
        if name=='commerce_store_workbench':return self.workbench(**args)
        return {'commerce_listing_get':self.get,'commerce_listing_save':self.save,'commerce_listing_export':self.export}[name](**args)

    def workbench(self,demo=False):
        if type(demo) is not bool:raise ValueError('invalid_demo')
        unavailable=[]
        def read(name,call):
            try:return call()
            except Exception:
                unavailable.append(name);return None
        cases=read('products',self.workspace.listing)
        alerts=read('imported_alerts',lambda:self.service.operations.list(demo))
        live=read('live',self.service.live.status) if not demo else None
        live_alerts=read('live_alerts',self.service.live.alerts) if not demo else None
        attention=read('attention',lambda:self.service.attention.listing(demo=demo,limit=100,include_followups=True))
        channels=read('channels',self.service.channels.status)
        platforms=read('platforms',self.service.platforms.listing)
        return dict(schema='commerce-store-workbench-v1',demo=demo,
                    products=[c for c in cases['items'] if c['synthetic']==demo] if cases else [],
                    imported_alerts=alerts,live_alerts=live_alerts,live=live,attention=attention,
                    channels=channels,platforms=platforms,unavailable=unavailable,
                    access={'deployment':'local_only','remote_access_enabled':False,'platform_writes_enabled':False},
                    external_messages_sent=False)
