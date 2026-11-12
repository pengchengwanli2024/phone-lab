"""Model-visible work-item scope and reviewed reuse of organization handoffs.

The organization module owns stage checks and task contracts. This adapter
projects its reads, pins their evidence, and calls its existing handoff method
inside one shared-core transaction; it never writes organization artifacts.
"""
import hashlib
import time
from .policy import canonical
from research import canonical as org_canonical, digest as org_digest


def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def binding(case):return digest(case)


def fingerprint(brief):
    return org_digest(org_canonical({'case':brief['case'],'stage':brief['stage'],'contract':brief['source_contract_sha256']}))


def public_case(case):
    scope=case['scope']
    return {'id':case['id'],'currency':case['currency'],
            'scope':{k:scope.get(k) for k in ('platform','market','fulfillment','sku','inventory_type','origin')},
            'binding_sha256':binding(case)}


def public_stage(stage):
    return {k:stage[k] for k in ('id','name','role','status','passed','total','gaps','artifact_kind','depends_on')}


def project_case_read(name, value):
    if name=='commerce_organization_board':
        return {'case':public_case(value['case']),'contract_sha256':value['contract_sha256'],
                'stages':[public_stage(s) for s in value['stages']],
                'gate_pass_rate':value['gate_pass_rate'],'notice':value['notice'],
                'external_execution':False}
    return {'case':public_case(value['case']),'stage':public_stage(value['stage']),
            'role':{k:value['role'][k] for k in ('id','name')},
            'expected_artifact':value['expected_artifact'],'source_contract_sha256':value['source_contract_sha256'],
            'evidence_fingerprint':fingerprint(value),'authority':value['authority']}


class CaseAdapter:
    def __init__(self, service):self.service=service;self.core=service.core

    def listing(self):
        cases=self.service.organization.cases()
        return {'cases':[public_case(c) for c in cases[:200]],'total':len(cases),'truncated':len(cases)>200,
                'source':'existing_organization_work_items','automatic_import':False}

    def validate_scope(self, parameters):
        if set(parameters)-{'case_id','stage_id'} or not isinstance(parameters.get('case_id'),str) or not 1<=len(parameters['case_id'])<=160:
            raise ValueError('agent_explicit_case_required')
        if 'stage_id' in parameters and (not isinstance(parameters['stage_id'],str) or parameters['stage_id'] not in self.stage_ids()):
            raise ValueError('agent_invalid_case_stage')
        try:return binding(self.service.organization.case(parameters['case_id']))
        except ValueError:raise ValueError('agent_case_unavailable') from None

    def stage_ids(self):return {s['id'] for s in self.service.organization.contract['stages']}

    def check_binding(self, payload):
        if self.validate_scope(payload['parameters'])!=payload['case_binding']:
            raise ValueError('agent_case_scope_changed')

    def prepare(self, proposal, payload, known):
        receipt=known.get(proposal.get('evidence_ref'))
        if payload['topic']!='organization_case' or not receipt or receipt['tool']!='commerce_organization_brief':
            raise ValueError('agent_case_brief_required')
        data=receipt['data'];params=payload['parameters']
        if data['case']['id']!=params['case_id'] or data['case']['binding_sha256']!=payload['case_binding']:
            raise ValueError('agent_case_scope_changed')
        if params.get('stage_id') and data['stage']['id']!=params['stage_id']:
            raise ValueError('agent_case_stage_outside_scope')
        if data['stage']['status']=='PASS':raise ValueError('agent_case_stage_already_passed')
        return {'kind':'analysis','input':{'case':data['case'],'stage_id':data['stage']['id'],
                'owner':data['role'],'gaps':data['stage']['gaps'],'expected_artifact':data['expected_artifact'],
                'evidence_fingerprint':data['evidence_fingerprint']}}

    def apply(self, run, proposal):
        expected=proposal['input'];cid=expected['case']['id'];sid=expected['stage_id']
        # Live configuration uses this same lock before any database writes.
        # Bind nested public domain calls to the existing shared task ledger.
        with self.service.live.config_lock,self.core.atomic() as db:
            prior=db.execute('SELECT task_id FROM agent_actions WHERE run_id=? AND proposal_id=?',(run['id'],proposal['id'])).fetchone()
            if prior:
                task=self.core.invoke('commerce_task_get',{'task_id':prior[0]})
                return {'task':task,'execution':None,'reused':True,'gate_closed':False,'external_operations_executed':False,'approval_scope':'single_organization_handoff'}
            try:brief=self.service.organization.brief(cid,sid)
            except ValueError:raise ValueError('agent_case_unavailable') from None
            if binding(brief['case'])!=expected['case']['binding_sha256'] or fingerprint(brief)!=expected['evidence_fingerprint']:
                raise ValueError('agent_case_evidence_changed')
            handoff=self.service.invoke('commerce_organization_handoff',{'case_id':cid,'stage_id':sid},'local')
            task=handoff.get('task')
            if not task or task['input'].get('evidence_fingerprint')!=expected['evidence_fingerprint'] or task['input'].get('organization_case')!=cid or task['input'].get('organization_stage')!=sid:
                # Includes freshness changes between two domain evaluations;
                # rollback any task/audit created by the nested handoff.
                raise ValueError('agent_case_evidence_changed')
            db.execute('INSERT INTO agent_actions VALUES (?,?,?,?)',(run['id'],proposal['id'],task['id'],time.time()))
            return {'task':task,'execution':None,'reused':False,'gate_closed':False,'external_operations_executed':False,'approval_scope':'single_organization_handoff'}

    def check(self, run, proposal):
        expected=proposal['input'];cid=expected['case']['id'];sid=expected['stage_id']
        task=next((a for a in run['actions'] if a['proposal_id']==proposal['id']),None)
        task=self.core.invoke('commerce_task_get',{'task_id':task['task_id']}) if task else None
        try:brief=self.service.organization.brief(cid,sid)
        except ValueError:
            return {'case_id':cid,'stage_id':sid,'case_available':False,'task':task,'gate_status':'UNKNOWN','gate_passed':False,'business_closed':False,'checked_at':time.time()}
        return {'case_id':cid,'stage_id':sid,'case_available':True,'task':task,
                'current':project_case_read('commerce_organization_brief',brief),
                'evidence_changed':fingerprint(brief)!=expected['evidence_fingerprint'],
                'gate_status':brief['stage']['status'],'gate_passed':brief['stage']['status']=='PASS',
                'business_closed':False,'checked_at':time.time(),'notice':'重新读取既有岗位门禁；任务完成不代表资料齐全或经营操作已完成。'}
