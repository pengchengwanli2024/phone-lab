"""An explicit offline fixture for responsible-owner UI, never a real signoff."""
import base64,copy,hashlib
from datetime import datetime,timezone,timedelta
from research import canonical
from organization import stamp
from fixture_listing_schema import seed as seed_schema
from test_organization import OrganizationTests

CASE='b619'*8
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII=')

def install(app):
    config=app.live.config();scope=dict(platform='ozon',market='RU',product_id='30',sku='SYN-OWNER-REVIEW',inventory_type='fbs',row_key='30:fbs',origin='inventory_scope_not_independently_verified',label='合成负责人核查验收')
    with app.core.db()as db:db.execute('INSERT OR IGNORE INTO org_cases VALUES (?,?,?,?,?,?)',(CASE,config['connection_id'],'30:fbs',canonical(scope),'CNY',stamp()))
    helper=OrganizationTests();helper.app=app;helper.org=app.organization;helper.cid=CASE;helper.case=app.organization.case(CASE);helper.prepare_cost()
    project=app.creative.create({'product':{'name':'Synthetic owner-review fixture','verified_facts':[]}},'fixture-owner-project')
    path=app.state/'synthetic-owner-product.png';path.write_bytes(PNG)
    asset=app.creative.register(project['id'],'product_image',path,{'source_ref':'synthetic:owner-fixture','usage_scope':'synthetic_only'})
    app.organization.deliver(CASE,project['id'],[asset['id']],'fixture-owner-delivery')
    doc=app.business.template('listing')['document'];now=datetime.now(timezone.utc)
    doc.update(synthetic=False,scope={'platform':'ozon','store_ref':config['connection_id'],'subject_ref':CASE},label='Synthetic owner-review source',observed_at=now.isoformat(),valid_until=(now+timedelta(days=1)).isoformat())
    for row in doc['records']:
        if row['key']=='price':row['value']='100.00'
        elif row['key']=='currency':row['value']='CNY'
        elif row['key']=='title':row['value']='合成验收商品 · 负责人核查'
        elif row['key']=='image_refs':row['value']=['https://example.com/synthetic-owner.png']
    source=app.business.import_source(doc,'fixture-owner-facts');view=app.product_workspace.get(CASE)
    saved=app.product_workspace.save(CASE,'content',dict(source_id=source['source_id'],fields={r['key']:r['value']for r in doc['records']}),0,view['source_sha256'])
    app.product_workspace.submit_content(CASE,saved['revision'],view['source_sha256'])
    review=app.product_workspace.delivery.get(CASE)
    app.product_workspace.delivery.record(CASE,review['package_sha256'],review['source_sha256'],'',{k:dict(status='confirmed',source_ref='synthetic:'+k,note='Synthetic offline operator fixture')for k in review['requirements']},'reviewed',True,'fixture-owner-local-review')
    seed_schema(app,app.listing_schema.connection(config))
    target=dict(case_id=CASE,platform='ozon',store_ref='ozon-live',market='RU');plan=app.listings.get(**target);payload=copy.deepcopy(plan['payload'])
    payload['fields']['category_id']='10';payload['ozon']={'type_id':20,'attributes':[{'id':101,'values':[{'dictionary_value_id':8,'value':'Synthetic brand'}],'source_ref':'synthetic:brand'},{'id':102,'values':[{'dictionary_value_id':0,'value':'3'}],'source_ref':'synthetic:count'}]}
    app.listings.save(**target,payload=payload,expected_revision=plan['revision'],expected_source_sha256=plan['source_sha256'])
    view=app.owner_reviews.get(**target);assert all(c['ready']for c in view['automatic_checks']),view['automatic_checks']
    from listing_review_media import descriptor
    r=dict(id='owner-review:'+view['binding_sha256'],sha256=view['binding_sha256'],data=dict(synthetic=False,frozen=dict(payload=payload)))
    for i in range(len(payload['fields']['image_refs'])):
        _,_,cache=descriptor(app.owner_reviews,r,i);cache.parent.mkdir(exist_ok=True,mode=0o700);cache.write_bytes(PNG);cache.chmod(0o600)
    original_image=app.owner_reviews.image
    def image(**args):
        current=app.owner_reviews.snapshot({k:args[k]for k in ('case_id','platform','store_ref','market')})
        assert args['case_id']==CASE
        frozen=dict(id='owner-review:'+current['binding_sha256'],sha256=current['binding_sha256'],data=dict(synthetic=False,frozen=dict(payload=current['product'])))
        _,_,cache=descriptor(app.owner_reviews,frozen,args['index']);cache.parent.mkdir(exist_ok=True,mode=0o700);cache.write_bytes(PNG);cache.chmod(0o600)
        return original_image(**args)
    app.owner_reviews.image=image
