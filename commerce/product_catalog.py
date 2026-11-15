"""Read-only product and supply projection over existing, scoped records."""
import json
import re
from urllib.parse import urlsplit
from research import canonical, digest


def definitions(schema, string):
    case = {'case_id': string}
    return [
        ('commerce_catalog_list', '浏览当前范围商品与货源卡片；保留候选、原币和资料来源', schema({'query': {'type':'string','maxLength':200}, 'kind': {'type':'string','enum':['all','candidate','inventory','supply']}})),
        ('commerce_catalog_get', '读取商品图文、规格、货源与创意关联；缺失值不补造', schema(case, ['case_id'])),
        ('commerce_catalog_creative', '按当前商品资料建立关联创意项目；不把研究推断提升为卖点事实', schema({**case,'expected_source_sha256':string,'idempotency_key':string}, ['case_id','expected_source_sha256','idempotency_key'])),
        ('commerce_catalog_image', '读取所选商品登记图片的私有预览；远程仅请求公开HTTPS图片，不携带店铺凭据', schema({**case,'expected_source_sha256':string,'index':{'type':'integer','minimum':0,'maximum':19},'image_id':string}, ['case_id','expected_source_sha256','index'])),
        ('commerce_catalog_image_import','将当前来源图片显式导入同商品创意项目，保留来源与哈希；不核实图片中的主张',schema({**case,'project_id':string,'expected_source_sha256':string,'index':{'type':'integer','minimum':0,'maximum':19},'image_id':string,'kind':{'type':'string','enum':['product_image','reference_image']}},['case_id','project_id','expected_source_sha256','index','kind'])),
    ]


def public_url(value):
    if not isinstance(value,str) or len(value)>2000:return None
    try:
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):return None
        return value
    except ValueError:return None


class ProductCatalog:
    def __init__(self, service): self.service=service; self.workspace=service.product_workspace

    def get(self, case_id):
        case,artifacts,facts,source=self.workspace.sources(case_id)
        research=artifacts['research'];record=(research or {}).get('payload',{}).get('record',{}) if not research or research['intact'] else {}
        fields=[{'key':k,'original':v.get('original',''),'zh':v.get('zh',''),'reviewed':v.get('reviewed',False),'kind':v.get('kind','unverified'),
                 'source_url':public_url(v.get('source_url') or record.get('source_url')), 'locator':v.get('locator','')}
                for k,v in record.get('fields',{}).items() if isinstance(v,dict) and (v.get('original') or v.get('zh'))]
        order=['title','description','attributes','variants','category','price','availability','dimensions','weight','brand','images']
        fields.sort(key=lambda r:order.index(r['key']) if r['key'] in order else len(order))
        values={r['key']:r for r in fields}
        images=[];seen=set()
        def add_url(url,ref):
            url=public_url(url)
            if url and url not in seen and len(images)<20:
                seen.add(url);images.append({'url':url,'origin':'source_link_unverified','source_ref':ref})
        for text in (values.get('images',{}).get('original',''), values.get('images',{}).get('zh','')):
            for link in re.findall(r'https://[^\s<>"\]]+',text):add_url(link.rstrip('，。；,)'),(research or {}).get('id'))
        offer=None
        # Public research candidates keep the exact captured offer and image
        # links. A title match never joins unrelated product records.
        with self.service.core.db() as db:
            jobs=db.execute('SELECT document FROM market_research_jobs ORDER BY rowid DESC LIMIT 100').fetchall()
        for (encoded,) in jobs:
            job=json.loads(encoded)
            if not any(c.get('case_id')==case_id for c in job.get('candidates',[])):continue
            for page in job.get('_captures',[]):
                if page.get('capture_sha256')!=digest(canonical({k:v for k,v in page.items() if k!='capture_sha256'})):continue
                item=next((r for r in page.get('products',[]) if r.get('url')==case['scope'].get('source_ref')),None)
                if not item:continue
                offer=item
                for link in item.get('images',[]):add_url(link,page.get('sha256'))
                break
            if offer:break
        price=None;currency=None;source_facts=[];store_facts=[];store_observed=None
        for entry in facts:
            doc=self.service.business.source(entry['id'])
            if not doc.get('fresh') or not doc.get('current'):continue
            rows=doc['document']['records'];v={r['key']:r['value'] for r in rows}
            platform_source=doc['document']['origin_ref']=='private-export:ozon-'+case_id
            if platform_source:
                store_observed=doc['document']['observed_at']
                for key in ('title','description','attributes','category_id','type_id','dimensions','weight','platform_status'):
                    if key not in v or key in values:continue
                    value=v[key];field={'key':key,'original':value if isinstance(value,str)else json.dumps(value,ensure_ascii=False),
                        'zh':'','reviewed':False,'kind':'platform_unverified','source_url':None,'locator':entry['id']+':'+key}
                    fields.append(field);values[key]=field
            if price is None and v.get('price') is not None:price=v['price'];currency=v.get('currency')
            for link in v.get('image_refs',[]) if isinstance(v.get('image_refs'),list) else []:add_url(link,entry['id'])
            target=store_facts if platform_source else source_facts
            target.extend({'id':'source'+str(len(target)+i),'text':str(v[k])[:500],'evidence_ref':entry['id']+':'+k} for i,k in enumerate(('description',)) if v.get(k))
        fields.sort(key=lambda r:order.index(r['key'])if r['key']in order else len(order))
        suppliers=[]
        for q in self.workspace.supply.listing(case_id)['items']:
            suppliers.append({**q['fields'],'quote_id':q['quote_id'],'revision':q['revision'],'status':q['status'],'missing':q['missing'],'independently_verified':False})
        supply=artifacts['supply']
        if supply and supply['intact'] and not suppliers:suppliers=[{**supply['payload'],'status':'source_supplied','independently_verified':False}]
        projects=[]
        with self.service.core.db() as db:
            for pid,raw,revision in db.execute('SELECT id,brief,revision FROM creative_projects ORDER BY rowid DESC'):
                b=json.loads(raw);binding=b.get('product_binding',{})
                if binding.get('case_id')!=case_id:continue
                projects.append({'id':pid,'name':b.get('product',{}).get('name',''),'revision':str(revision),'source_current':binding.get('source_sha256')==source})
                for aid,kind,metadata in db.execute("SELECT id,kind,metadata FROM creative_assets WHERE project=? AND kind IN ('product_image','generated_image','image_layout_draft') ORDER BY rowid DESC LIMIT 12",(pid,)).fetchall():
                    meta=json.loads(metadata)
                    if len(images)<20:images.insert(0,{'project_id':pid,'asset_id':aid,'origin':kind,'sha256':meta['sha256'],'source_ref':meta.get('source_ref'),'source_current':binding.get('source_sha256')==source})
        for image in images:image['id']=digest(canonical(image))
        name=case['scope'].get('label') or values.get('title',{}).get('zh') or values.get('title',{}).get('original') or self.workspace.label(case)
        return {'id':case_id,'name':name,'case':case,'kind':'candidate' if case['scope'].get('origin')=='research_candidate_not_inventory' else 'inventory',
                'price':price,'currency':currency,'price_text':values.get('price',{}).get('original') or (str(offer.get('price',''))+' '+str(offer.get('currency',''))+' · 采集报价' if offer and offer.get('price') else None),
                'source_sha256':source,'source_url':public_url(case['scope'].get('source_ref')) or public_url(record.get('source_url')),
                'captured_at':store_observed or record.get('captured_at') or None,'fields':fields,'images':images,'suppliers':suppliers,
                'source_facts':source_facts,'store_facts':store_facts,'projects':projects,'source_intact':not any(a and not a['intact'] for a in artifacts.values()),
                'synthetic':case['scope'].get('synthetic') is True,'independently_verified':False,'external_execution_allowed':False}

    def listing(self,query='',kind='all'):
        if not isinstance(query,str) or len(query)>200 or kind not in ('all','candidate','inventory','supply'):raise ValueError('catalog_invalid_filter')
        result=[]
        for case in self.workspace.org.cases():
            d=self.get(case['id'])
            if kind=='supply' and not d['suppliers'] or kind not in ('all','supply',d['kind']):continue
            if query.casefold() not in canonical([d['name'],d['case']['scope'],d['fields'],d['suppliers']]).casefold():continue
            result.append({k:d[k] for k in ('id','name','kind','price','currency','price_text','source_url','source_sha256','captured_at','synthetic','images')} | {'supplier_count':len(d['suppliers']),'platform':case['scope'].get('platform'),'market':case['scope'].get('market')})
        return {'items':result,'independently_verified':False}

    def creative(self,case_id,expected_source_sha256,idempotency_key):
        with self.service.core.atomic():
            self.workspace.guard(case_id,expected_source_sha256);d=self.get(case_id)
            brief={'synthetic':d['synthetic'],'product_binding':{'case_id':case_id,'source_sha256':expected_source_sha256},
                   'product':{'name':d['name'][:120],'verified_facts':d['source_facts'][:20]},
                   'target':{'language':'zh','country':d['case']['scope'].get('market','')},'reference':{}}
            return self.service.creative.create(brief,'catalog:'+digest(canonical([case_id,idempotency_key])))

    def image(self,case_id,expected_source_sha256,index,image_id=None):
        d=self.get(case_id)
        if d['source_sha256']!=expected_source_sha256:raise ValueError('workspace_source_changed')
        if image_id:index=next((i for i,r in enumerate(d['images']) if r['id']==image_id),-1)
        if type(index) is not int or not 0<=index<len(d['images']):raise ValueError('catalog_image_not_found')
        from catalog_media import preview
        return preview(self.service,d['images'][index],expected_source_sha256)

    def image_import(self,case_id,project_id,expected_source_sha256,index,kind,image_id=None):
        import base64
        import uuid
        if kind not in ('product_image','reference_image'):raise ValueError('catalog_invalid_image_kind')
        d=self.get(case_id);project=self.service.creative.get(project_id)
        if project['brief'].get('product_binding',{}).get('case_id')!=case_id:raise ValueError('catalog_project_outside_scope')
        if image_id:index=next((i for i,r in enumerate(d['images']) if r['id']==image_id),-1)
        image=self.image(case_id,expected_source_sha256,index,image_id)
        key=digest(canonical([case_id,d['images'][index],kind]))
        with self.service.core.atomic() as db:
            self.workspace.guard(case_id,expected_source_sha256)
            for aid,metadata in db.execute('SELECT id,metadata FROM creative_assets WHERE project=? AND kind=?',(project_id,kind)):
                meta=json.loads(metadata)
                if meta.get('catalog_reference')==key:return {'asset':{'id':aid,'kind':kind,**meta},'reused':True}
            suffix='.png' if image['mime']=='image/png' else '.jpg'
            temp=self.service.creative.folder(project_id)/(uuid.uuid4().hex+suffix)
            try:
                temp.write_bytes(base64.b64decode(image['content_base64']));temp.chmod(0o600)
                media=self.service.creative.probe(temp)
                if media['width']<=0:raise ValueError('creative_image_required')
                asset=self.service.creative.register(project_id,kind,temp,{'display_name':d['name'][:100]+' · 来源图片',
                    'origin':'catalog_import_unverified','source_ref':d['images'][index].get('url') or d['images'][index].get('source_ref') or 'catalog:'+case_id,
                    'catalog_reference':key,'catalog_source_sha256':expected_source_sha256,'media':media})
            finally:temp.unlink(missing_ok=True)
        return {'asset':asset,'reused':False}

    def invoke(self,name,args):
        return {'commerce_catalog_list':self.listing,'commerce_catalog_get':self.get,'commerce_catalog_creative':self.creative,'commerce_catalog_image':self.image,'commerce_catalog_image_import':self.image_import}[name](**args)
