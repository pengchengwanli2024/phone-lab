"""Version-bound local listing review against existing read-only snapshots."""
from decimal import Decimal,InvalidOperation
import json
import re
import time
from research import canonical,digest


def definitions(schema,string):
    target={'case_id':string,'platform':string,'store_ref':{'type':'string','maxLength':100},'market':{'type':'string','maxLength':2}}
    return [
        ('commerce_listing_directory','分页读取当前模式已保存的上架目标、缺项与本地核对状态；不访问平台',schema({'demo':{'type':'boolean'},'store_scope':string,'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':50}})),
        ('commerce_listing_reconcile','按精确店铺、市场与SKU核对已有只读快照，区分差异与不可比较口径；不触发同步',schema(target,list(target))),
        ('commerce_listing_review','将准确版本的本地核对声明追加到原商品产物；不授予平台提交或经营批准',schema({**target,'expected_comparison_sha256':string,'expected_review_sha256':{'type':'string','maxLength':64},'decision':{'type':'string','enum':['reviewed','needs_changes']},'note':string,'confirmed':{'type':'boolean'},'idempotency_key':string},[*target,'expected_comparison_sha256','expected_review_sha256','decision','note','confirmed','idempotency_key'])),
    ]


class ListingReconciliation:
    def __init__(self,service):self.service=service;self.core=service.core;self.workspace=service.product_workspace;self.org=service.organization
    def invoke(self,name,args):return {'commerce_listing_directory':self.directory,'commerce_listing_reconcile':self.get,'commerce_listing_review':self.record}[name](**args)
    @staticmethod
    def kind(target):return 'listing_check_'+digest(canonical(target))[:24]

    def observation(self,target,sku,synthetic):
        base=dict(status='store_unlinked',store_ref=target['store_ref'],configuration_revision=None,resource=None,snapshot_id=None,sha256=None,observed_at=None,fresh=False,match_count=0,matches=[])
        if synthetic:return {**base,'status':'demo_no_platform_read'}
        if target['platform']=='ozon':
            if target['store_ref']!='ozon-live':return base
            live=self.service.live;c=live.config()
            if not c.get('connection_id'):return base
            if target['market']!='RU':return {**base,'status':'scope_mismatch'}
            snap=live.snapshot(c['connection_id'],'stock')
            base.update(configuration_revision=digest(canonical({k:c.get(k)for k in ('connection_id','stock_basis','max_age_seconds')})),connection_id=c['connection_id'],resource='stock')
            if not snap:return {**base,'status':'snapshot_missing'}
            if digest(canonical(snap['data']))!=snap['sha256']:raise ValueError('listing_snapshot_integrity_failed')
            fresh=live._fresh(snap,c)
            scope=self.org.case(target['case_id'])['scope']
            records=[dict(entity_id=r['product_id'],sku=r['offer_id'],title=None,quantity=r['available'],quantity_basis='ozon_fulfillment_aggregate_not_independently_reviewed',amount=None,currency=None,status=None)for r in live.inventory_rows()if r['offer_id']==sku and
                (not scope.get('product_id')or r['product_id']==scope['product_id'])and(not scope.get('inventory_type')or r['type']==scope['inventory_type'])]
            base.update(snapshot_id=snap['id'],sha256=snap['sha256'],observed_at=snap['observed_at'],fresh=fresh)
            detail=self.service.catalog_sync.detail(target['case_id'])
            if detail:
                base.update(detail_snapshot_id=detail['snapshot_id'],detail_sha256=detail['sha256'],detail_observed_at=detail['observed_at'],detail_fresh=detail['fresh'])
                actual=detail['record']
                if detail['fresh']and actual['sku']==sku:
                    for row in records:row.update(title=actual.get('title'),amount=actual.get('price'),currency=actual.get('currency'),status=actual.get('platform_status',{}).get('status_name'))
        else:
            try:c=self.service.platforms.config(target['store_ref'])
            except ValueError:return base
            if c['platform']!=target['platform']or c['market']!=target['market']:return {**base,'status':'scope_mismatch'}
            from platform_connections.protocols import CATALOG
            resources=CATALOG[c['platform']]['resources'];resource='products'if'products'in resources else'stock'if'stock'in resources else None
            base.update(configuration_revision=c['revision'],resource=resource)
            if not resource:return {**base,'status':'resource_not_supported'}
            snap=self.service.platforms.snapshot(c['store_id'],resource)
            base.update(snapshot_id=snap['snapshot_id'],fresh=snap['fresh']and c['scope_reviewed'])
            if not snap['available']:return {**base,'status':'snapshot_missing'}
            doc=snap['document']
            if (doc['store']['store_id']!=c['store_id']or doc['store']['platform']!=c['platform']or doc['store']['market']!=c['market']or doc['store']['revision']!=c['revision']or not doc.get('complete')):raise ValueError('listing_snapshot_scope_invalid')
            base.update(sha256=doc['sha256'],observed_at=doc['observed_at'])
            records=[r for r in doc['records']if r.get('sku')==sku]
        if not sku:return {**base,'status':'sku_required'}
        base.update(match_count=len(records),matches=records[:10])
        base['status']='snapshot_stale'if not base['fresh']else'sku_missing'if not records else'sku_ambiguous'if len(records)!=1 else'observed'
        return base

    @staticmethod
    def differences(fields,observation):
        if observation['status']!='observed':return []
        row=observation['matches'][0];result=[]
        for key,actual in [('title',row.get('title')),('price',row.get('amount')),('currency',row.get('currency')),('quantity',row.get('quantity'))]:
            expected=fields[key];state='unknown'
            if expected in ('',None):state='missing_input'
            elif actual is not None:
                if key=='quantity':state='not_comparable'
                elif key=='price':
                    if not fields['currency']or fields['currency']!=row.get('currency'):state='not_comparable'
                    else:
                        try:state='same'if Decimal(str(expected))==Decimal(str(actual))else'different'
                        except InvalidOperation:state='unknown'
                else:state='same'if expected==actual else'different'
            result.append(dict(field=key,prepared=expected,observed=actual,status=state,quantity_basis=row.get('quantity_basis')if key=='quantity'else None))
        return result

    def get(self,case_id,platform,store_ref,market):
        plan=self.service.listings.get(case_id,platform,store_ref,market);target=plan['target']
        observation=self.observation(target,plan['payload']['fields']['sku'],plan['synthetic'])
        differences=self.differences(plan['payload']['fields'],observation)
        binding=dict(target=target,preview_sha256=plan['preview_sha256'],observation=observation,differences=differences)
        comparison_sha=digest(canonical(binding));head=self.org.artifact(case_id,self.kind(target))
        if head and not head['intact']:raise ValueError('listing_review_integrity_failed')
        review=dict(id=head['id'],sha256=head['sha256'],decision=head['payload']['decision'],note=head['payload']['note'],created_at=head['created_at'],current=head['payload']['comparison_sha256']==comparison_sha)if head else None
        choices=[{k:s[k]for k in ('store_id','platform','market','label')}for s in self.service.platforms.listing()['stores']if s['platform']==platform]
        if platform=='ozon':choices.append(dict(store_id='ozon-live',platform='ozon',market='RU',label=self.service.live.status()['store_label']))
        return {**binding,'comparison_sha256':comparison_sha,'plan_revision':plan['revision'],'plan_stale':plan['stale'],
            'review':review,'store_choices':choices,'external_execution_allowed':False,'platform_submission_verified':False,
            'quantity_interpretation':'reported_scope_only_not_total_sellable_inventory','synthetic':plan['synthetic']}

    def record(self,case_id,platform,store_ref,market,expected_comparison_sha256,expected_review_sha256,decision,note,confirmed,idempotency_key):
        target,_=self.service.listings.scope(case_id,platform,store_ref,market)
        if confirmed is not True or decision not in ('reviewed','needs_changes'):raise ValueError('listing_review_confirmation_required')
        if not isinstance(note,str)or not note.strip()or len(note)>2000:raise ValueError('listing_review_note_required')
        if not isinstance(idempotency_key,str)or not 1<=len(idempotency_key)<=160:raise ValueError('invalid_idempotency_key')
        request_sha=digest(canonical([target,expected_comparison_sha256,expected_review_sha256,decision,note,confirmed]));kind=self.kind(target)
        with self.core.db()as db:old=db.execute('SELECT id,payload,sha FROM org_artifacts WHERE case_id=?AND kind=?AND idem=?',(case_id,kind,idempotency_key)).fetchone()
        if old:
            payload=json.loads(old[1])
            if digest(canonical(payload))!=old[2]:raise ValueError('listing_review_integrity_failed')
            if payload['request_sha256']!=request_sha:raise ValueError('idempotency_conflict')
            return dict(id=old[0],sha256=old[2],external_operations_executed=False)
        view=self.get(**target)
        if view['comparison_sha256']!=expected_comparison_sha256:raise ValueError('listing_comparison_changed')
        if not view['plan_revision']:raise ValueError('listing_save_required')
        if decision=='reviewed'and(view['observation']['status']!='observed'or view['plan_stale']):raise ValueError('listing_observation_required')
        # Keep the original platform lock -> Core lock ordering used by sync.
        with self.service.platforms.configs()as configs,self.core.atomic()as db:
            old=db.execute('SELECT id,payload,sha FROM org_artifacts WHERE case_id=?AND kind=?AND idem=?',(case_id,kind,idempotency_key)).fetchone()
            if old:
                payload=json.loads(old[1])
                if digest(canonical(payload))!=old[2]:raise ValueError('listing_review_integrity_failed')
                if payload['request_sha256']!=request_sha:raise ValueError('idempotency_conflict')
                return dict(id=old[0],sha256=old[2],external_operations_executed=False)
            observation=view['observation']
            if target['platform']!='ozon'and observation['configuration_revision']:
                if configs.get(store_ref,{}).get('revision')!=observation['configuration_revision']:raise ValueError('listing_comparison_changed')
                row=db.execute('SELECT s.id,s.document FROM platform_latest l JOIN platform_snapshots s ON s.id=l.snapshot_id WHERE l.store_id=?AND l.resource=?',(store_ref,observation['resource'])).fetchone()
                if (row[0]if row else None)!=observation['snapshot_id']:raise ValueError('listing_comparison_changed')
                if row:
                    doc=json.loads(row[1])
                    if doc['sha256']!=observation['sha256']or observation['fresh']and time.time()-doc['observed_at']>1800:raise ValueError('listing_comparison_changed')
            elif target['platform']=='ozon'and observation.get('connection_id'):
                current=self.observation(target,self.service.listings.get(**target)['payload']['fields']['sku'],False)
                if current!=observation:raise ValueError('listing_comparison_changed')
            _,scope=self.service.listings.scope(**target)
            checkpoint=self.service.form_drafts.get(scope)
            if checkpoint['revision']!=view['plan_revision']:raise ValueError('listing_comparison_changed')
            self.workspace.guard(case_id,checkpoint['payload']['source_sha256'])
            head=self.org.artifact(case_id,kind)
            if (head['sha256']if head else'')!=expected_review_sha256:raise ValueError('listing_review_conflict')
            payload=dict(target=target,comparison_sha256=expected_comparison_sha256,request_sha256=request_sha,decision=decision,note=note,
                observation_sha256=observation['sha256'],approval_scope='local_listing_observation_only',platform_submission_verified=False)
            return self.org._store(case_id,kind,payload,idempotency_key,_expected_head=head['id']if head else None)

    def directory(self,demo=False,offset=0,limit=25,store_scope='all'):
        catalog=self.service.store_scopes.selection(store_scope,demo)
        if type(demo)is not bool or type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=50:raise ValueError('listing_directory_invalid_page')
        cases=[c for c in self.workspace.listing()['items']if c['synthetic']==demo];targets=[]
        for case in cases:
            source=self.workspace.sources(case['id'])[3]
            targets.extend(self.service.listings.saved_targets(case['id'],source))
        targets=[target for target in targets if self.service.store_scopes.includes_target(target,store_scope,catalog)]
        targets.sort(key=lambda r:(r['case_id'],r['platform'],r['store_ref'],r['market']))
        items=[]
        for target in targets[offset:offset+limit]:
            identity={k:target[k]for k in ('case_id','platform','store_ref','market')};plan=self.service.listings.get(**identity);head=self.org.artifact(identity['case_id'],self.kind(identity))
            comparison=self.get(**identity)
            items.append(dict(target=identity,name=plan['name'],sku=plan['payload']['fields']['sku'],revision=plan['revision'],stale=plan['stale'],missing=plan['missing'],
                observation_status=comparison['observation']['status'],review_status=head['payload']['decision']if head and comparison['review']['current']else'outdated'if head else'not_reviewed',
                release=self.service.listing_releases.summary(identity,plan)))
        return dict(items=items,total=len(targets),offset=offset,next_offset=offset+limit if offset+limit<len(targets)else None,complete=offset==0 and len(items)==len(targets),external_execution_allowed=False)
