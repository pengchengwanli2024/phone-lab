"""Offline category evidence for the single-item publication contract."""
import uuid
from datetime import datetime,timezone
from research import canonical,digest
from ozon_listing_schema import project
from test_listing_schema import TREE,ATTR,VALUES

def metadata(app):
 c=app.listing_schema.connection(app.live.config());base={};attr_parent={}
 entries=[('tree',TREE,0),('attributes',{'result':ATTR['result']+[
  dict(id=8229,name='Synthetic type',type='String',is_required=True,is_collection=False,dictionary_id=20,max_value_count=1,attribute_complex_id=0),
  dict(id=4191,name='Synthetic description',type='String',is_required=False,is_collection=False,dictionary_id=0,max_value_count=1,attribute_complex_id=0)]},0),('values',VALUES,101),('values',{'result':[dict(id=20,value='Synthetic type')],'has_next':False},8229)]
 with app.core.atomic()as db:
  for resource,raw,attribute in entries:
   parents={}if resource=='tree'else base.copy()if resource=='attributes'else attr_parent.copy()
   data=project(resource,raw);data.update(response_sha256='a'*64,parent_references=parents);kind=app.listing_schema.kind(resource,10,20,attribute,0);sha=digest(canonical(data));ident=uuid.uuid4().hex
   db.execute('INSERT INTO live_snapshots VALUES(?,?,?,?,?,?)',(ident,c,kind,canonical(data),sha,datetime.now(timezone.utc).isoformat()));db.execute('INSERT OR REPLACE INTO live_latest VALUES(?,?,?)',(c,kind,ident))
   if resource=='tree':base[kind]=sha
   if resource=='attributes':attr_parent={**base,kind:sha}

def install(app):
    import base64,copy,os,ozon_reader
    from fixture_owner_review import install as owner_install,CASE,PNG
    from listing_release import ListingReleases
    from listing_review_media import descriptor
    from listing_release_reads import PRODUCT_PATH,IMPORT_PATH
    from listing_submission_protocol import ATTR_PATH
    from listing_action_protocol import READ_PATH
    try:app.organization.case(CASE)
    except ValueError:owner_install(app)
    metadata(app);target=dict(case_id=CASE,platform='ozon',store_ref='ozon-live',market='RU');v=app.listings.get(**target);p=copy.deepcopy(v['payload'])
    p.update(language='ru',fulfillment='Synthetic OGL',rules_ref='synthetic:platform-rules')
    p['ozon']['attributes']+=[dict(id=8229,values=[dict(dictionary_value_id=20,value='Synthetic type')],source_ref='synthetic:type'),dict(id=4191,values=[dict(dictionary_value_id=0,value=p['fields']['description'])],source_ref='synthetic:description')]
    p['ozon']['publication']=dict(depth=100,width=80,height=50,dimension_unit='mm',weight=200,weight_unit='g',vat='0.22',source_ref='synthetic:package',vat_source_ref='synthetic:tax',description_attribute_id=4191)
    app.listings.save(**target,payload=p,expected_revision=v['revision'],expected_source_sha256=v['source_sha256'])
    owner=app.owner_reviews.get(**target)
    app.owner_reviews.record(**target,expected_binding_sha256=owner['binding_sha256'],expected_review_sha256=owner['review_sha256'],checks={k:dict(status='confirmed',source_ref='synthetic:'+k,note='Synthetic explicit responsible owner')for k in owner['requirements']},decision='owner_confirmed',reviewer='Synthetic owner',confirmed=True,idempotency_key='synthetic-publish-owner')
    v=app.listings.get(**target);assert not v['missing'],v['checks']
    request=app.listing_releases.create(**target,expected_preview_sha256=v['preview_sha256'],note='Synthetic exact publication request',confirmed=True,idempotency_key='synthetic-publish-request')
    app.listing_releases.review(request['id'],'','acknowledged','Synthetic application read',True,'synthetic-publish-ack')
    original_reader=app.listing_releases.reader;original_credentials=app.listing_releases.credentials
    def credentials(r):return ListingReleases.credentials(app.listing_releases,r)if r['data']['target']['case_id']==CASE else original_credentials(r)
    app.listing_releases.credentials=credentials
    remote=dict(id=30,offer_id=p['fields']['sku'],name='Original synthetic title',price='90.00',currency_code='CNY',old_price='0',statuses=dict(is_created=True,is_failed=False))
    attrs=dict(id=30,offer_id=p['fields']['sku'],description_category_id=10,type_id=20,barcode='SYN-BAR',attributes=[dict(attribute_id=999,complex_id=0,values=[dict(dictionary_value_id=0,value='Preserved synthetic attribute')])],complex_attributes=[])
    urls=['https://example.com/original-publication.png'];state=dict(writes=0,task_id='777777',request_id=request['id'])
    def reader(path,body,*args):
        if path==PRODUCT_PATH and(body.get('offer_id')==[p['fields']['sku']]or body.get('product_id')==[30]):raw=dict(items=[copy.deepcopy(remote)])
        elif path==ATTR_PATH:raw=dict(result=[copy.deepcopy(attrs)])
        elif path==READ_PATH:raw=dict(items=[dict(product_id=30,primary_photo=urls[:1],photo=urls[1:],color_photo=[],photo_360=[],errors=[])])
        elif path==IMPORT_PATH and body['task_id']==777777:raw=dict(result=dict(items=[dict(offer_id=p['fields']['sku'],product_id=30,status='imported',errors=[])]))
        else:
            if original_reader is ozon_reader.post:raise AssertionError('unlisted synthetic publication read')
            return original_reader(path,body,*args)
        return raw,'c'*64
    def writer(body,*args):
        assert args[0]=='123456';state['writes']+=1;item=body['items'][0];remote.update(name=item['name'],price=item['price'],currency_code=item['currency_code']);urls[:]=item['images'];attrs.update(attributes=copy.deepcopy(item['attributes']),**{k:item[k]for k in ('depth','width','height','weight','dimension_unit','weight_unit')})
        if os.environ.get('COMMERCE_QA_SUBMISSION_UNKNOWN')=='1':raise ValueError('ozon_write_outcome_unknown')
        return dict(result=dict(task_id=777777)),'d'*64
    app.listing_submissions.reader=reader;app.listing_submissions.writer=writer;app.listing_releases.reader=reader
    def image(request_id,expected_request_sha256,index):
        r=app.listing_releases.request(request_id)
        if r['data']['target']['case_id']==CASE:
            _,_,cache=descriptor(app.listing_releases,r,index);cache.parent.mkdir(exist_ok=True,mode=0o700);cache.write_bytes(PNG);cache.chmod(0o600)
        return ListingReleases.image(app.listing_releases,request_id,expected_request_sha256,index)
    app.listing_releases.image=image
    import server
    previous=server.Handler.do_GET
    def get(handler):
        if handler.path=='/qa-submission':return handler.answer(200,state)
        return previous(handler)
    server.Handler.do_GET=get
    return state
