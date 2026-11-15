"""Version-bound local review over original content, media and business receipts."""
import json
import time
from decimal import Decimal, InvalidOperation
from research import canonical, digest

REQUIREMENTS={'facts':'商品事实与引用已核对','translation':'翻译与中文字段已校对',
              'media_rights':'素材对应关系与使用权资料已核对','platform_rules':'平台及类目规则资料已人工核对'}


def checklist(value):
    if type(value) is not dict or set(value)!=set(REQUIREMENTS):raise ValueError('workspace_delivery_invalid_checks')
    out={}
    for key,row in value.items():
        if type(row) is not dict or set(row)-{'status','source_ref','note'} or row.get('status') not in ('pending','confirmed','rejected'):
            raise ValueError('workspace_delivery_invalid_checks')
        source=row.get('source_ref','');note=row.get('note','')
        if type(source) is not str or len(source)>500 or type(note) is not str or len(note)>1000 or (row['status']=='confirmed' and not source.strip()):
            raise ValueError('workspace_delivery_evidence_required')
        out[key]={'status':row['status'],'source_ref':source,'note':note}
    return out


class DeliveryReview:
    def __init__(self, workspace):
        self.workspace=workspace;self.org=workspace.org;self.core=workspace.core;self.business=workspace.service.business

    def from_snapshot(self,snapshot):
        cid=snapshot['case']['id'];draft=next(iter(snapshot['content_drafts']),None)
        stages={s['id']:s for s in snapshot['stages']};calculation=snapshot['calculation']
        price_matches=False
        if draft and calculation['status']=='CALCULATED' and not calculation['stale']:
            fields=draft['draft']['content']['fields']
            try:price_matches=fields.get('currency')==calculation.get('currency') and Decimal(str(fields.get('price')))==Decimal(str(calculation['price']))
            except (InvalidOperation,TypeError,KeyError):pass
        checks=[dict(id='content',label='内容字段、引用与当前来源',passed=bool(draft and draft['preflight']['ready_for_local_review'])),
                dict(id='translation',label='原文、译文与工作项范围',passed=stages['S5']['status']=='PASS'),
                dict(id='images',label='原图片交付文件、哈希及版本',passed=stages['S4']['status']=='PASS'),
                dict(id='cost',label='同币种贡献与草稿售价',passed=stages['S2']['status']=='PASS' and price_matches)]
        binding=dict(source_sha256=snapshot['source_sha256'],draft_id=draft['id'] if draft else None,
                     draft_sha256=draft['draft']['draft_sha256'] if draft else None,checks=checks)
        package_sha=digest(canonical(binding));latest=self.org.artifact(cid,'delivery_review')
        current=bool(latest and latest['intact'] and latest['payload']['package_sha256']==package_sha)
        manual=latest['payload']['checks'] if current else {k:dict(status='pending',source_ref='',note='') for k in REQUIREMENTS}
        ready=all(r['passed'] for r in checks) and all(r['status']=='confirmed' for r in manual.values())
        status='ready_for_local_review' if ready else 'needs_inputs'
        if latest and not current:status='stale'
        elif current and latest['payload']['decision']=='rejected':status='rejected'
        elif current and latest['payload']['decision']=='reviewed':
            receipt=next((r for r in draft['receipts'] if r['id']==latest['payload'].get('receipt_id')),None) if draft else None
            status='local_review_recorded' if ready and receipt and receipt['expires_at']>time.time() and draft['receipts'][-1]['id']==receipt['id'] else 'review_expired_or_superseded'
        return dict(case_id=cid,source_sha256=snapshot['source_sha256'],package_sha256=package_sha,
                    draft_id=binding['draft_id'],status=status,requirements=REQUIREMENTS,
                    automatic_checks=checks,checks=manual,latest=latest,
                    professional_gate=stages['S6']['status'],professional_gate_policy='owner_attested_not_independently_verified',platform_rules_verified=False,
                    approval_scope='local_delivery_review_only',external_execution_allowed=False)

    def get(self,case_id):return self.workspace.get(case_id)['delivery_review']

    def record(self,case_id,expected_package_sha256,expected_source_sha256,expected_review_sha256,checks,decision,confirmed,idempotency_key):
        checks=checklist(checks)
        if decision not in ('save','reviewed','rejected') or (decision!='save' and confirmed is not True):raise ValueError('workspace_delivery_confirmation_required')
        if type(idempotency_key) is not str or not 1<=len(idempotency_key)<=160:raise ValueError('invalid_idempotency_key')
        request_sha=digest(canonical([expected_package_sha256,expected_source_sha256,expected_review_sha256,checks,decision,confirmed]))
        with self.core.atomic() as db:
            self.org.case(case_id)
            prior=db.execute("SELECT id,payload,sha FROM org_artifacts WHERE case_id=? AND kind='delivery_review' AND idem=?",(case_id,idempotency_key)).fetchone()
            if prior:
                if json.loads(prior[1])['request_sha256']!=request_sha:raise ValueError('organization_idempotency_conflict')
                return dict(id=prior[0],sha256=prior[2],reused=True,external_execution_allowed=False)
            self.workspace.guard(case_id,expected_source_sha256)
            view=self.get(case_id);head=view['latest']
            if view['package_sha256']!=expected_package_sha256:raise ValueError('workspace_delivery_package_changed')
            if (head['sha256'] if head else '')!=expected_review_sha256:raise ValueError('workspace_delivery_review_conflict')
            if decision=='reviewed' and (not all(r['passed'] for r in view['automatic_checks']) or not all(r['status']=='confirmed' for r in checks.values())):
                raise ValueError('workspace_delivery_incomplete')
            receipt=None
            if decision!='save':
                if not view['draft_id']:raise ValueError('workspace_delivery_draft_required')
                draft=self.business.get(view['draft_id'])
                receipt=self.business.review(draft['id'],draft['draft']['draft_sha256'],decision,True,'delivery:'+digest(canonical([case_id,idempotency_key])),'版本绑定的本地交付审阅；不授予平台操作或独立合规结论。',_reuse=True)
            payload=dict(package_sha256=expected_package_sha256,checks=checks,decision=decision,
                         binding_source_sha256=expected_source_sha256,draft_id=view['draft_id'],
                         receipt_id=receipt['id'] if receipt else None,request_sha256=request_sha)
            return self.org._store(case_id,'delivery_review',payload,idempotency_key,_expected_head=head['id'] if head else None)

    def export(self,case_id,expected_package_sha256):
        with self.core.atomic():
            snapshot=self.workspace.get(case_id);view=snapshot['delivery_review']
            if view['package_sha256']!=expected_package_sha256:raise ValueError('workspace_delivery_package_changed')
            body=dict(schema='commerce-private-delivery-manifest-v1',review=view,
                      content=json.loads(self.business.export(view['draft_id'])['content']) if view['draft_id'] else None,
                      images=snapshot['artifacts']['images'],contains_private_business_data=True,
                      platform_submission='not_performed',external_execution_allowed=False)
        return dict(filename='delivery-'+case_id+'.json',content=json.dumps(body,ensure_ascii=False,indent=2),external_execution_allowed=False)
