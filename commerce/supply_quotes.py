"""Local quotation versions over the existing organization artifact ledger."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import json
import re
import time
from operations_analysis import number
from research import canonical, digest

FIELDS = ('supplier','currency','purchase_cost','lead_time_days','moq','source_ref','valid_until','packaging')
PACKAGING = ('length_cm','width_cm','height_cm','weight_kg','units_per_pack')


def comparison_quantity(value):
    return int(number(value,'quantity',minimum=1,maximum=10**9,integer=True))


def deadline(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.utcoffset() is None:raise ValueError()
        return dt.timestamp()
    except (ValueError,TypeError,AttributeError,OverflowError):
        raise ValueError('workspace_quote_invalid_valid_until') from None


def validate(data):
    if type(data) is not dict or set(data)-set(FIELDS):raise ValueError('workspace_quote_invalid_fields')
    for key in ('supplier','source_ref'):
        if key in data and (type(data[key]) is not str or not data[key].strip() or len(data[key])>500):
            raise ValueError('workspace_quote_invalid_'+key)
    if 'currency' in data and (type(data['currency']) is not str or not re.fullmatch('[A-Z]{3}',data['currency'])):
        raise ValueError('workspace_quote_invalid_currency')
    for key in ('purchase_cost','lead_time_days','moq'):
        if key in data:number(data[key],key,minimum=1 if key=='moq' else 0,integer=key!='purchase_cost')
    if 'valid_until' in data:deadline(data['valid_until'])
    if 'packaging' in data:
        pack=data['packaging']
        if type(pack) is not dict or set(pack)-set(PACKAGING):raise ValueError('workspace_quote_invalid_packaging')
        for key,value in pack.items():number(value,key,minimum=1 if key=='units_per_pack' else .000001,integer=key=='units_per_pack')


def case_binding(case):return digest(canonical({'id':case['id'],'scope':case['scope']}))


def selection_issues(org, case, supply):
    ref=(supply or {}).get('payload',{}).get('quote_ref')
    if not ref:return []  # Historical five-field supply records keep their contract.
    quote=org.artifact(case['id'],'supply_quote:'+ref['quote_id'])
    if not quote or not quote['intact'] or quote['id']!=ref['artifact_id'] or quote['sha256']!=ref['sha256']:
        return ['所选报价版本已变化或不可用，请重新核对并明确选择']
    data=quote['payload'];fields=data.get('fields',{})
    try:validate(fields)
    except ValueError:return ['所选报价内容无效，请核对原始报价']
    if any(k not in fields for k in FIELDS) or any(k not in fields.get('packaging',{}) for k in PACKAGING):return ['所选报价资料不完整']
    if any(fields[k]!=supply['payload'].get(k) for k in ('supplier','currency','purchase_cost','lead_time_days','source_ref')):
        return ['供应产物与所选报价内容不一致，请重新核对选择']
    if data['case_binding']!=case_binding(case):return ['报价对象或履约范围已变化']
    if deadline(data['fields']['valid_until'])<=time.time():return ['所选报价已过有效期，请补充当前报价']
    if data['fields']['currency']!=case['currency']:return ['所选报价与当前工作项币种不同']
    return []


class SupplyQuotes:
    def __init__(self, workspace):
        self.workspace=workspace;self.org=workspace.org;self.core=workspace.core

    def _kind(self, quote_id):
        if type(quote_id) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,60}',quote_id):raise ValueError('workspace_quote_invalid_id')
        return 'supply_quote:'+quote_id

    def _view(self, artifact, case):
        data=artifact['payload'];fields=data['fields']
        missing=[k for k in FIELDS if k not in fields]
        missing.extend('packaging.'+k for k in PACKAGING if k not in fields.get('packaging',{}))
        current_scope=data['case_binding']==case_binding(case)
        expired='valid_until' in fields and deadline(fields['valid_until'])<=time.time()
        mismatch=bool(fields.get('currency') and case['currency'] and fields['currency']!=case['currency'])
        state='HOLD' if missing or not case['currency'] else 'STALE' if not current_scope or not artifact['intact'] else 'EXPIRED' if expired else 'CURRENCY_MISMATCH' if mismatch else 'READY_FOR_SELECTION'
        return dict(quote_id=data['quote_id'],revision=data['revision'],fields=fields,
                    artifact_id=artifact['id'],sha256=artifact['sha256'],created_at=artifact['created_at'],
                    status=state,missing=missing,scope_current=current_scope,intact=artifact['intact'],
                    independently_verified=False,external_execution_allowed=False)

    def listing(self, case_id):
        case=self.org.case(case_id)
        with self.core.db() as db:
            kinds=[r[0] for r in db.execute("SELECT DISTINCT kind FROM org_artifacts WHERE case_id=? AND kind GLOB 'supply_quote:*' ORDER BY kind",(case_id,))]
            items=[]
            for kind in kinds:
                current=self._view(self.org.artifact(case_id,kind),case)
                rows=db.execute('SELECT id,payload,sha,created FROM org_artifacts WHERE case_id=? AND kind=? ORDER BY created DESC,id DESC LIMIT 20',(case_id,kind)).fetchall()
                current['history']=[dict(artifact_id=r[0],revision=json.loads(r[1])['revision'],fields=json.loads(r[1])['fields'],sha256=r[2],created_at=r[3]) for r in rows]
                current['history_truncated']=current['revision']>len(rows)
                items.append(current)
        return dict(items=items,case_id=case_id,external_execution_allowed=False)

    def heads(self,case_id):
        return [{k:r[k] for k in ('quote_id','artifact_id','sha256','status')} for r in self.listing(case_id)['items']]

    def compare(self,case_id,quantity):
        requested=comparison_quantity(quantity)
        # Reuse the domain transaction so all quotation versions and the case
        # binding come from one snapshot; comparison never writes the ledger.
        with self.core.atomic(reuse=True):
            case=self.org.case(case_id);items=[]
            selected=(self.org.artifact(case_id,'supply') or {}).get('payload',{}).get('quote_ref',{})
            for row in self.listing(case_id)['items']:
                fields=row['fields'];pack=fields.get('packaging',{})
                result={k:row[k] for k in ('quote_id','revision','artifact_id','sha256','status','missing')}
                result.update(supplier=fields.get('supplier'),currency=fields.get('currency'),
                    source_ref=fields.get('source_ref'),valid_until=fields.get('valid_until'),
                    lead_time_days=fields.get('lead_time_days'),moq=fields.get('moq'),
                    units_per_pack=pack.get('units_per_pack'),unit_price=None,
                    order_units=None,extra_units=None,packages=None,goods_subtotal=None)
                result['selected']=row['quote_id']==selected.get('quote_id') and row['sha256']==selected.get('sha256')
                if 'purchase_cost' in fields and row['intact']:
                    result['unit_price']=format(number(fields['purchase_cost'],'purchase_cost'),'f')
                if row['status']=='READY_FOR_SELECTION':
                    validate(fields)
                    unit=number(fields['purchase_cost'],'purchase_cost')
                    minimum=max(requested,fields['moq'])
                    pack_units=int(number(pack['units_per_pack'],'units_per_pack',minimum=1,integer=True))
                    count=(number(minimum,'minimum')/pack_units).to_integral_value(rounding=ROUND_CEILING)
                    units=int(count)*pack_units
                    result.update(packages=int(count),order_units=units,extra_units=units-requested,
                        goods_subtotal=format((unit*units).quantize(Decimal('.01'),rounding=ROUND_HALF_UP),'f'))
                items.append(result)
            value=dict(case_id=case_id,source_sha256=self.workspace.sources(case_id)[3],
                quantity=requested,currency=case['currency'],items=items,
                comparable_count=sum(r['goods_subtotal'] is not None for r in items),
                quantity_basis='minimum_whole_packages_at_or_above_demand_and_moq',
                subtotal_basis='quoted_goods_only',excluded_costs=['shipping','packaging_fees','taxes','platform_fees','fx'],
                independently_verified=False,external_execution_allowed=False)
            value['comparison_sha256']=digest(canonical(value))
            value['generated_at']=datetime.now(timezone.utc).isoformat()
            return value

    def save(self,case_id,quote_id,payload,expected_revision,expected_source_sha256,idempotency_key):
        kind=self._kind(quote_id);validate(payload)
        if type(expected_revision) is not int or expected_revision<0:raise ValueError('workspace_quote_invalid_revision')
        if type(idempotency_key) is not str or not 1<=len(idempotency_key)<=160:raise ValueError('invalid_idempotency_key')
        request_sha=digest(canonical([payload,expected_revision,expected_source_sha256]))
        with self.core.atomic() as db:
            case=self.org.case(case_id)
            prior=db.execute('SELECT id,payload,sha,created FROM org_artifacts WHERE case_id=? AND kind=? AND idem=?',(case_id,kind,idempotency_key)).fetchone()
            if prior:
                old=json.loads(prior[1])
                if old['request_sha256']!=request_sha:raise ValueError('organization_idempotency_conflict')
                return self._view(dict(id=prior[0],payload=old,sha256=prior[2],created_at=prior[3],intact=digest(canonical(old))==prior[2]),case)
            self.workspace.guard(case_id,expected_source_sha256)
            head=self.org.artifact(case_id,kind)
            if (head['payload']['revision'] if head else 0)!=expected_revision:raise ValueError('workspace_quote_conflict')
            if head and not head['intact']:raise ValueError('workspace_artifact_changed')
            if expected_revision>=100 or (not head and len(self.listing(case_id)['items'])>=20):raise ValueError('workspace_quote_capacity')
            data=dict(quote_id=quote_id,revision=expected_revision+1,fields=payload,case_binding=case_binding(case),request_sha256=request_sha)
            self.org._store(case_id,kind,data,idempotency_key,_expected_head=head['id'] if head else None)
            return self._view(self.org.artifact(case_id,kind),case)

    def select(self,case_id,quote_id,expected_quote_sha256,expected_source_sha256,idempotency_key):
        kind=self._kind(quote_id)
        with self.core.atomic() as db:
            case=self.org.case(case_id)
            prior=db.execute("SELECT payload,id,sha FROM org_artifacts WHERE case_id=? AND kind='supply' AND idem=?",(case_id,idempotency_key)).fetchone()
            if prior:
                ref=json.loads(prior[0]).get('quote_ref',{})
                if ref.get('quote_id')!=quote_id or ref.get('sha256')!=expected_quote_sha256:raise ValueError('organization_idempotency_conflict')
                return {'id':prior[1],'sha256':prior[2],'reused':True,'external_execution_allowed':False}
            self.workspace.guard(case_id,expected_source_sha256)
            artifact=self.org.artifact(case_id,kind)
            if not artifact or artifact['sha256']!=expected_quote_sha256:raise ValueError('workspace_quote_conflict')
            row=self._view(artifact,case)
            if row['status']=='CURRENCY_MISMATCH':raise ValueError('workspace_quote_currency_mismatch')
            if row['status']!='READY_FOR_SELECTION':raise ValueError('workspace_quote_not_ready')
            fields=row['fields'];data={k:fields[k] for k in ('supplier','currency','purchase_cost','lead_time_days','source_ref')}
            data['quote_ref']={'quote_id':quote_id,'artifact_id':row['artifact_id'],'sha256':row['sha256']}
            result=self.org.record(case_id,'supply',data,idempotency_key)
            return {**result,'reused':False,'external_execution_allowed':False}
