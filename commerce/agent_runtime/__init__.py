"""Explicit, durable role requests with bounded reads and reviewed local work."""
from contextlib import nullcontext
from pathlib import Path
import hashlib
import json
import re
import threading
import time
import uuid
from . import model
from .policy import TOPICS,canonical,tool_menu,check_call,project
from .cases import CaseAdapter

ROOT=Path(__file__).resolve().parents[1]
FINAL=('completed','awaiting_input','awaiting_review','failed','unknown','cancelled','interrupted')


def sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def definitions(schema, string):
    return [
        ('commerce_agent_status','查看模型角色运行器、范围和当前岗位；配置不代表已执行',schema()),
        ('commerce_agent_cases','只读列出当前连接已有工作项；不自动导入或触发模型',schema()),
        ('commerce_agent_case_check','重新读取某条已审阅岗位建议的当前门禁与任务；不把任务完成当作业务闭环',schema({'run_id':string,'proposal_id':string},['run_id','proposal_id'])),
        ('commerce_agent_start','明确请求一次有界模型分析；仅使用所选范围的只读工具，建议待人工审阅',schema({'question':{'type':'string','minLength':1,'maxLength':2000},'role':string,'topic':{'type':'string','enum':list(TOPICS)},'parameters':{'type':'object'},'parent_id':string,'idempotency_key':string},['question','role','topic','idempotency_key'])),
        ('commerce_agent_get','读取模型请求、工具回执、追问、建议与已提交本地任务',schema({'run_id':string},['run_id'])),
        ('commerce_agent_list','读取最近20次共享模型请求；不触发新分析',schema()),
        ('commerce_agent_cancel','取消排队或请求停止正在运行的模型分析；不撤销已提交的本地任务',schema({'run_id':string},['run_id'])),
        ('commerce_agent_apply','人工审阅后按结果哈希提交一个本地建议；只支持模板、测算或证据整理，不操作店铺',schema({'run_id':string,'proposal_id':string,'result_sha256':string},['run_id','proposal_id','result_sha256'])),
    ]


class AgentRuntime:
    def __init__(self, service):
        self.service=service;self.core=service.core;self.owner=uuid.uuid4().hex
        self.cases=CaseAdapter(service)
        self.stop_event=threading.Event();self.thread=None
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS agent_runs(id TEXT PRIMARY KEY,idem TEXT UNIQUE,request TEXT,payload TEXT,status TEXT,created REAL,updated REAL,owner TEXT,expires REAL,result TEXT,trace TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS agent_actions(run_id TEXT,proposal_id TEXT,task_id TEXT,created REAL,PRIMARY KEY(run_id,proposal_id))')

    def roles(self):
        return json.loads((ROOT/'agents/roles.json').read_text())['roles']

    def status(self):
        with self.core.db() as db:counts=dict(db.execute('SELECT status,count(*) FROM agent_runs GROUP BY status'))
        from .codex_provider import route
        try:provider=route(self.service.state);provider_route='signed_in_codex_cli' if provider['provider']=='codex' else 'existing_commerce_hermes_profile'
        except ValueError:provider={};provider_route='invalid_private_configuration'
        return {'worker':'running' if self.thread and self.thread.is_alive() else 'not_started',
                'roles':[{'id':r['id'],'name':r['name'],'responsibility':r['responsibility']} for r in self.roles()],
                'topics':list(TOPICS),'states':counts,'limits':{'model_turns':3,'read_calls':4,'simultaneous_runs':1},
                'case_stages':[{k:s[k] for k in ('id','name','role')} for s in self.service.organization.contract['stages']],
                'provider_route':provider_route,'provider_readiness':'checked_on_request','configured_model':provider.get('model'),
                'model_calls_require_explicit_request':True,'marketplace_writes':False,'mobile_gateway':'not_managed',
                'history':'shared_local_requests_not_host_chat_history'}

    def invoke(self, name, args):
        if name=='commerce_agent_status':return self.status()
        if name=='commerce_agent_cases':return self.cases.listing()
        if name=='commerce_agent_case_check':
            run=self.get(args['run_id']);proposal=next((p for p in (run.get('result') or {}).get('proposals',[]) if p['id']==args['proposal_id'] and p['operation']=='organization_handoff'),None)
            if not proposal:raise ValueError('agent_case_proposal_not_found')
            return self.cases.check(run,proposal)
        if name=='commerce_agent_start':return self.create(**args)
        if name=='commerce_agent_get':return self.get(**args)
        if name=='commerce_agent_list':
            with self.core.db() as db:ids=[r[0] for r in db.execute('SELECT id FROM agent_runs ORDER BY created DESC LIMIT 20')]
            return {'runs':[self.get(i,brief=True) for i in ids]}
        if name=='commerce_agent_cancel':return self.cancel(**args)
        if name=='commerce_agent_apply':return self.apply(**args)
        raise ValueError('unknown_tool')

    def create(self, question, role, topic, idempotency_key, parameters=None, parent_id=None):
        return self._create(question,role,topic,idempotency_key,parameters,parent_id)

    def _create(self, question, role, topic, idempotency_key, parameters=None, parent_id=None, _db=None, _conversation=None, _model_route=None):
        parameters={} if parameters is None else parameters
        if not isinstance(question,str) or not question.strip() or len(question)>2000 or topic not in TOPICS:raise ValueError('agent_invalid_request')
        if not isinstance(idempotency_key,str) or not idempotency_key.strip() or len(idempotency_key)>160:raise ValueError('invalid_idempotency_key')
        if not isinstance(parameters,dict) or len(canonical(parameters))>8000 or set(parameters)-{'calculator','input','item_id','demo','case_id','stage_id','assessment_id','context'}:raise ValueError('agent_invalid_parameters')
        if topic=='workspace':
            from copilot.context import validate_context
            if set(parameters)!={'context'}:raise ValueError('agent_invalid_parameters')
            parameters={'context':validate_context(parameters['context'])}
        elif 'context' in parameters:raise ValueError('agent_invalid_parameters')
        if topic!='organization_case' and set(parameters)&{'case_id','stage_id'}:raise ValueError('agent_case_topic_required')
        if topic=='business_exposure':
            if set(parameters)!={'assessment_id'} or not isinstance(parameters['assessment_id'],str) or not re.fullmatch('[a-f0-9]{64}',parameters['assessment_id']):raise ValueError('agent_exposure_assessment_required')
        elif 'assessment_id' in parameters:raise ValueError('agent_exposure_topic_required')
        if 'demo' in parameters and type(parameters['demo']) is not bool:raise ValueError('agent_invalid_parameters')
        if 'item_id' in parameters and (not isinstance(parameters['item_id'],str) or not re.fullmatch('[a-f0-9]{24}',parameters['item_id'])):raise ValueError('agent_invalid_parameters')
        if 'input' in parameters and not isinstance(parameters['input'],dict):raise ValueError('agent_invalid_parameters')
        if 'calculator' in parameters and parameters['calculator'] not in ('unit_economics','restock_plan'):raise ValueError('agent_invalid_parameters')
        request=dict(question=question.strip(),role=role,topic=topic,parameters=parameters,parent_id=parent_id)
        encoded=canonical(request)
        with (nullcontext(_db) if _db is not None else self.core.db()) as db:old=db.execute('SELECT id,request FROM agent_runs WHERE idem=?',(idempotency_key,)).fetchone()
        if old:
            if old[1]!=encoded:raise ValueError('idempotency_conflict')
            return self._get(old[0],_db=_db)
        role_spec=next((r for r in self.roles() if role==r['id'] or role in r.get('legacy_ids',[])),None)
        if not role_spec:raise ValueError('unknown_agent_role')
        payload={**request,'role':{k:role_spec[k] for k in ('id','name','responsibility')},'role_contract_sha256':sha(role_spec)}
        from conversation_policy import requires_evidence
        payload['evidence_required']=requires_evidence(question,topic)
        if _conversation is not None:payload['conversation']=_conversation
        payload['model_route']=_model_route if _model_route is not None else self.service.models.default_snapshot()
        if topic=='organization_case':payload['case_binding']=self.cases.validate_scope(parameters)
        if topic=='business_exposure' and self.service.exposure.current(parameters['assessment_id'])!='current':raise ValueError('agent_exposure_evidence_changed')
        if parent_id:
            parent=self._get(parent_id,_db=_db)
            if parent['status'] not in ('awaiting_input','awaiting_review','completed') or parent['role']['id']!=role_spec['id'] or parent['topic']!=topic:raise ValueError('agent_parent_not_replyable')
            if topic=='organization_case' and any(parent['parameters'].get(k)!=parameters.get(k) for k in ('case_id','stage_id')):raise ValueError('agent_case_reply_scope_changed')
            if topic=='business_exposure' and parent['parameters']!=parameters:raise ValueError('agent_exposure_reply_scope_changed')
            if topic=='workspace' and parent['parameters']!=parameters:raise ValueError('agent_workspace_reply_scope_changed')
            payload['previous']={'question':parent['question'],'answer':parent['result']['answer'],'questions':parent['result']['questions'],'result_sha256':parent['result_sha256']}
        at=time.time();ident=uuid.uuid4().hex
        with (nullcontext(_db) if _db is not None else self.core.db()) as db:
            if _db is None:db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT id,request FROM agent_runs WHERE idem=?',(idempotency_key,)).fetchone()
            if old:
                if old[1]!=encoded:raise ValueError('idempotency_conflict')
                ident=old[0]
            else:
                count=db.execute("SELECT count(*) FROM agent_runs WHERE status IN ('queued','running','cancel_requested')").fetchone()[0]
                if count>=8:raise ValueError('agent_queue_full')
                db.execute('INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL,?)',(ident,idempotency_key,encoded,canonical(payload),'queued',at,at,'[]'))
        return self._get(ident,_db=_db)

    def get(self, run_id, brief=False):
        return self._get(run_id,brief)

    def _get(self, run_id, brief=False, _db=None):
        with (nullcontext(_db) if _db is not None else self.core.db()) as db:
            row=db.execute('SELECT payload,status,created,updated,result,trace FROM agent_runs WHERE id=?',(run_id,)).fetchone()
            actions=[{'proposal_id':r[0],'task_id':r[1]} for r in db.execute('SELECT proposal_id,task_id FROM agent_actions WHERE run_id=?',(run_id,))]
        if not row:raise ValueError('agent_run_not_found')
        payload=json.loads(row[0]);result=json.loads(row[4]) if row[4] else None
        value={'id':run_id,'role':payload['role'],'question':payload['question'],'topic':payload['topic'],'parameters':payload['parameters'],
               'parent_id':payload.get('parent_id'),'status':row[1],'created':row[2],'updated':row[3],
               'result':result,'result_sha256':sha(result) if result else None,'actions':actions,
               'marketplace_writes':False,'independently_verified':False}
        value['model_choice']=self.service.models.public_snapshot(payload.get('model_route',{}))
        if payload.get('model_route',{}).get('provider')=='host_native':
            value['routing_mode']='automatic_single_host'
            value['execution_hosts']=self.service.host_execution.plan_for_payload(payload)
            value['host_attempts']=self.service.host_execution.for_run(run_id)
        if payload.get('execution_hosts'):
            value['execution_hosts']=payload['execution_hosts']
            value['model_choice']={'profile_id':'host-plan','profile_revision':sha(payload['execution_hosts']),
                'label':'宿主执行计划','provider':'host_plan',
                'model':' → '.join(r['host_id']+' / '+r['model'] for r in payload['execution_hosts'])}
        value['research_job']=self.service.market_research.for_run(run_id, _db)
        if brief:
            value.pop('result');value.pop('parameters')
        else:value['trace']=json.loads(row[5])
        return value

    def cancel(self, run_id):
        research=self.service.market_research.for_run(run_id)
        if research and research['run_id']==run_id:
            self.service.market_research.cancel(research['task_id'])
            return self.get(run_id)
        with self.core.db() as db:
            db.execute("UPDATE agent_runs SET status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'cancel_requested' END,updated=? WHERE id=? AND status IN ('queued','running')",(time.time(),run_id))
        return self.get(run_id)

    def cancelled(self, ident):
        with self.core.db() as db:row=db.execute('SELECT status FROM agent_runs WHERE id=?',(ident,)).fetchone()
        return self.stop_event.is_set() or not row or row[0]!='running'

    def finish(self, ident, status, result, trace):
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status FROM agent_runs WHERE id=?',(ident,)).fetchone()
            if row and row[0]=='cancel_requested':status,result='cancelled',{'error':'agent_cancelled_generation_may_have_started'}
            db.execute("UPDATE agent_runs SET status=?,updated=?,expires=0,result=?,trace=? WHERE id=? AND owner=? AND expires>? AND status IN ('running','cancel_requested')",(status,time.time(),canonical(result),canonical(trace),ident,self.owner,time.time()))

    def step(self, result, payload, observations):
        decision=result.get('decision') if isinstance(result,dict) else None
        if not isinstance(decision,dict):raise ValueError('agent_model_invalid_response')
        if decision.get('phase')=='inspect':
            if payload.get('evidence_required',True) is False:raise ValueError('agent_tool_outside_scope')
            calls=decision.get('calls')
            if set(decision)!={'phase','calls'} or not isinstance(calls,list) or not 1<=len(calls)<=2:raise ValueError('agent_model_invalid_response')
            return calls,None
        if decision.get('phase')!='answer' or set(decision)!={'phase','answer','questions','evidence_refs','proposals'}:raise ValueError('agent_model_invalid_response')
        if not isinstance(decision['answer'],str) or not 1<=len(decision['answer'])<=5000:raise ValueError('agent_model_invalid_response')
        questions=decision['questions'];refs=decision['evidence_refs'];proposals=decision['proposals']
        if not isinstance(questions,list) or len(questions)>3 or any(not isinstance(q,str) or not 1<=len(q)<=400 for q in questions):raise ValueError('agent_model_invalid_response')
        known={r['id']:r for r in observations}
        if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in known for ref in refs):raise ValueError('agent_unknown_evidence_reference')
        if observations and not refs:raise ValueError('agent_evidence_reference_required')
        if not observations and not questions and payload.get('evidence_required',True) and payload['topic'] in ('runtime','intelligence','organization_case','business_exposure','workspace'):raise ValueError('agent_current_evidence_required')
        if not isinstance(proposals,list) or len(proposals)>3:raise ValueError('agent_model_invalid_response')
        if payload.get('evidence_required',True) is False and proposals:raise ValueError('agent_invalid_proposal')
        reviewed=[]
        for i,p in enumerate(proposals):
            if not isinstance(p,dict) or set(p)-{'operation','reason','evidence_ref'} or not isinstance(p.get('reason'),str) or not 1<=len(p['reason'])<=500:raise ValueError('agent_invalid_proposal')
            op=p.get('operation');data=payload['parameters'];task_input={'title':'AI 建议 · '+p['reason'][:100],'agent_role':payload['role']['id']}
            if payload['topic']=='organization_case' and op!='organization_handoff':raise ValueError('agent_case_proposal_requires_handoff')
            if payload['topic']=='business_exposure':
                receipt=known.get(p.get('evidence_ref'))
                if op!='exposure_review' or not receipt or receipt['tool']!='commerce_exposure_get' or receipt['data']['id']!=data['assessment_id']:raise ValueError('agent_exposure_assessment_required')
                reviewed.append({'id':'P'+str(i+1),'operation':op,'reason':p['reason'],'kind':'analysis','input':{'assessment':receipt['data']},'requires_human_review':True})
                continue
            if op=='organization_handoff':
                prepared=self.cases.prepare(p,payload,known)
                reviewed.append({'id':'P'+str(i+1),'operation':op,'reason':p['reason'],**prepared,'requires_human_review':True})
                continue
            if payload['topic']=='workspace' and op=='report' and (data['context'].get('entity') or any(data['context'].get(k,'all')!='all' for k in ('platform','store_id','market'))):raise ValueError('agent_report_scope_not_supported')
            if payload['topic']=='workspace':data=data['context']
            if op=='report':task_input['demo']=data.get('demo',False);kind='report'
            elif op in ('unit_economics','restock_plan') and data.get('calculator')==op and isinstance(data.get('input'),dict):task_input['parameters']=data['input'];kind='analysis'
            elif op=='intel_review':
                receipt=known.get(p.get('evidence_ref'))
                if not receipt or receipt['tool']!='commerce_intel_item_get':raise ValueError('agent_proposal_requires_frozen_item')
                task_input.update(mode='public_source',evidence=receipt['data'],store_impact='unknown');kind='analysis'
            else:raise ValueError('agent_proposal_outside_scope')
            self.service.autonomy.validate_operation({'kind':kind,'input':task_input},op)
            reviewed.append({'id':'P'+str(i+1),'operation':op,'reason':p['reason'],'kind':kind,'input':task_input,'requires_human_review':True})
        return None,{'answer':decision['answer'],'questions':questions,'evidence_refs':refs,'proposals':reviewed,
                     'generator':'configured_model','provider':str(result.get('provider','unknown'))[:100],'model':str(result.get('model','unknown'))[:160],
                     'review_status':'pending_review','independently_verified':False,'observations':observations}

    def run_once(self):
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT count(*) FROM agent_runs WHERE status IN ('running','cancel_requested') AND expires>?",(time.time(),)).fetchone()[0]:return False
            row=db.execute("SELECT id,payload FROM agent_runs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:return False
            ident,payload=row[0],json.loads(row[1])
            db.execute("UPDATE agent_runs SET status='running',owner=?,expires=?,updated=? WHERE id=?",(self.owner,time.time()+360,time.time(),ident))
        trace=[];observations=[];seen=set();calls_used=0
        try:
            research=self.service.market_research.execute(ident,payload,lambda:self.cancelled(ident))
            if research is not None:
                job=self.service.market_research.for_run(ident)
                state=job['status']
                status='completed' if state in ('completed','partial') else state
                self.finish(ident,status,research,[{'event':'market_research','task_id':job['task_id'],'status':state}])
                return True
            for turn in range(3):
                if self.cancelled(ident):raise model.Cancelled()
                if payload['topic']=='organization_case':self.cases.check_binding(payload)
                if payload['topic']=='business_exposure' and self.service.exposure.current(payload['parameters']['assessment_id'])!='current':raise ValueError('agent_exposure_evidence_changed')
                context={'role':payload['role'],'question':payload['question'],'parameters':payload['parameters'],'previous':payload.get('previous'),'conversation':payload.get('conversation',[]),
                         'tools':tool_menu(payload['topic'],payload['parameters']) if turn<2 and payload.get('evidence_required',True) else [],'observations':observations,
                         'evidence_required':payload.get('evidence_required',True),
                         'turn':turn+1,'final_turn':turn==2,'read_calls_remaining':4-calls_used if payload.get('evidence_required',True) else 0}
                if payload['topic']=='workspace':
                    from copilot.methods import guidance_for
                    context['reviewed_workflow_guidance']=guidance_for(payload['parameters']['context'])
                    if payload.get('current_research') is not None:
                        context['current_research']=payload['current_research']
                from .codex_provider import route
                # New requests freeze their profile at enqueue; historical requests
                # keep the legacy default route. Never switch a running model turn.
                provider=self.service.models.runtime_route(payload.get('model_route') or route(self.service.state))
                if provider['provider']=='host_native':result=self.service.host_execution.invoke_run(ident,turn+1,context,lambda:self.cancelled(ident))
                elif provider['provider'] in ('codex','compatible'):result=model.invoke(context,lambda:self.cancelled(ident),route=provider)
                else:result=model.invoke(context,lambda:self.cancelled(ident))
                if payload['topic']=='business_exposure' and self.service.exposure.current(payload['parameters']['assessment_id'])!='current':raise ValueError('agent_exposure_evidence_changed')
                calls,answer=self.step(result,payload,observations)
                trace.append({'event':'model_turn','turn':turn+1,'provider':str(result.get('provider','unknown'))[:100],'model':str(result.get('model','unknown'))[:160]})
                if answer is not None:
                    status='awaiting_input' if answer['questions'] else 'awaiting_review' if answer['proposals'] else 'completed'
                    self.finish(ident,status,answer,trace);return True
                if turn==2 or calls_used+len(calls)>4:raise ValueError('agent_budget_exhausted')
                for call in calls:
                    if self.cancelled(ident):raise model.Cancelled()
                    name,args=check_call(payload['topic'],payload['parameters'],call,seen)
                    if payload['topic']=='organization_case':self.cases.check_binding(payload)
                    if payload['topic']=='business_exposure' and self.service.exposure.current(payload['parameters']['assessment_id'])!='current':raise ValueError('agent_exposure_evidence_changed')
                    calls_used+=1
                    raw=self.service.invoke(name,args,'local');data=project(name,raw)
                    if len(canonical(data))>16000:raise ValueError('agent_tool_result_too_large')
                    if name in ('commerce_intel_search','commerce_skills_search'):seen.update(r['id'] for r in data['items'])
                    observation={'id':'R'+str(calls_used),'tool':name,'data':data,'sha256':sha(data),'observed_at':time.time()}
                    observations.append(observation)
                    trace.append({'event':'read_tool','tool':name,'reference':observation['id'],'sha256':observation['sha256']})
            raise ValueError('agent_budget_exhausted')
        except model.Cancelled:
            stopping=self.stop_event.is_set()
            self.finish(ident,'interrupted' if stopping else 'cancelled',{'error':'agent_interrupted_no_automatic_resubmit' if stopping else 'agent_cancelled_generation_may_have_started'},trace)
        except Exception as error:
            code=str(error) if isinstance(error,ValueError) and str(error).startswith('agent_') else 'agent_request_failed'
            self.finish(ident,'unknown' if 'outcome_unknown' in code else 'failed',{'error':code,'automatic_retry':False},trace)
        return True

    def apply(self, run_id, proposal_id, result_sha256):
        # A shared runtime tool must not bypass dialogue context review bindings.
        with self.core.db() as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='copilot_turns'").fetchone()
            binding=db.execute('SELECT t.thread_id,t.context_sha,t.revision,c.context_sha,c.revision,c.approving FROM copilot_turns t JOIN copilot_threads c ON c.id=t.thread_id WHERE t.run_id=?',(run_id,)).fetchone() if exists else None
        if binding:
            if binding[1:3]!=binding[3:5]:raise ValueError('copilot_context_changed')
            if binding[5]!=run_id+':'+proposal_id:
                from copilot import Copilot
                return Copilot(self.service).apply(binding[0],run_id,proposal_id,result_sha256,binding[3])
        run=self.get(run_id)
        if not run['result'] or run['result_sha256']!=result_sha256:raise ValueError('agent_result_changed')
        if run['status'] not in ('awaiting_review','awaiting_input','completed'):raise ValueError('agent_result_not_reviewable')
        proposal=next((p for p in run['result'].get('proposals',[]) if p['id']==proposal_id),None)
        if not proposal:raise ValueError('agent_proposal_not_found')
        if proposal['operation']=='organization_handoff':return self.cases.apply(run,proposal)
        if proposal['operation']=='exposure_review':return self.service.exposure.apply_agent(run,proposal)
        task=self.service.invoke('commerce_task_create',{'kind':proposal['kind'],'input':proposal['input'],'idempotency_key':'agent:'+run_id+':'+proposal_id},'local')
        result=self.service.autonomy.request(task['id'],proposal['operation'])
        with self.core.db() as db:db.execute('INSERT OR IGNORE INTO agent_actions VALUES (?,?,?,?)',(run_id,proposal_id,task['id'],time.time()))
        return {'task':result['task'],'execution':result['execution'],'external_operations_executed':False,'approval_scope':'single_local_proposal'}

    def start(self, recover=False):
        if self.thread and self.thread.is_alive():return
        if recover:
            self.service.market_research.recover()
            with self.core.db() as db:
                self.service.host_execution.recover_dialogues(db)
                db.execute("UPDATE agent_runs SET status='interrupted',expires=0,updated=?,result=? WHERE status IN ('running','cancel_requested')",(time.time(),canonical({'error':'agent_interrupted_no_automatic_resubmit'})))
        def loop():
            while not self.stop_event.is_set():
                try:
                    if self.run_once():continue
                except Exception:pass
                self.stop_event.wait(1)
        self.thread=threading.Thread(target=loop,name='commerce-role-runner',daemon=True);self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)
