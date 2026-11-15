"""Read-only, exact-reference history projected from the existing local ledgers."""
from datetime import datetime
import hashlib
import json
import math
import re

from agent_runtime.policy import canonical
from attention import object_json,text


def definitions(schema,string):
    return [('commerce_task_timeline_get','分页读取原任务、模型链或复查的统一时间线；缺失历史保持未知，不执行或恢复',schema({
        'kind':{'type':'string','enum':['task','run','followup']},'id':string,
        'limit':{'type':'integer','minimum':1,'maximum':100},'cursor':string},['kind','id']))]


def timestamp(value):
    if isinstance(value,str):
        try:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            value=parsed.timestamp() if parsed.tzinfo else None
        except (ValueError,OverflowError):return None
    return value if type(value) in (int,float) and math.isfinite(value) else None


class TaskTimeline:
    def __init__(self,service):self.service,self.core=service,service.core

    @staticmethod
    def _run_mode(db,payload):
        parameters=payload.get('parameters',{});context=parameters.get('context',parameters)
        if not isinstance(context,dict):raise ValueError('timeline_source_unavailable')
        if 'demo' in context:return context['demo'] is True
        case_id=parameters.get('case_id')
        if payload.get('topic')=='business_exposure':
            assessment=db.execute('SELECT case_id FROM exposure_assessments WHERE id=?',(parameters.get('assessment_id'),)).fetchone()
            if not assessment:return None
            case_id=assessment[0]
        if case_id:
            case=db.execute('SELECT scope FROM org_cases WHERE id=?',(case_id,)).fetchone()
            return object_json(case[0]).get('synthetic') is True if case else None
        return False

    def get(self,kind,id,limit=30,cursor=None):
        if kind not in ('task','run','followup') or not isinstance(id,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,160}',id):raise ValueError('timeline_invalid_reference')
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('timeline_invalid_query')
        if cursor is not None and (not isinstance(cursor,str) or not re.fullmatch('[a-f0-9]{64}:timeline_[a-f0-9]{64}',cursor)):raise ValueError('timeline_invalid_cursor')
        events=[];errors=set();runs=set();tasks=set();followups=set();demo=None;scope_current=True;source_modes={}
        def event(source,source_id,name,at,status=None,detail=None,index=''):
            identity=hashlib.sha256(canonical([source,source_id,name,index]).encode()).hexdigest()
            events.append({'id':'timeline_'+identity,'event':name,'source':source,'source_id':source_id,
                'at':timestamp(at),'status':text(status,64),'detail':detail or {},'demo':source_modes.get((source,source_id))})
        with self.core.db() as db:
            if not db.in_transaction:db.execute('BEGIN')
            if kind=='task':tasks.add(id)
            elif kind=='run':runs.add(id)
            else:
                row=self.service.followups._load(db,id);frozen=object_json(row['target']);followups.add(id);demo=bool(row['demo'])
                try:scope_current=self.service.followups._scope_current(db,frozen)
                except (ValueError,KeyError,TypeError):scope_current=False
                action=frozen['action'] or {};binding=frozen['binding']
                if action.get('type') in ('research','tasks'):tasks.add(action['id'])
                elif action.get('type')=='agent':runs.add(action['id'])
                elif action.get('type')=='thread':
                    runs.update(r[0]for r in db.execute('SELECT run_id FROM copilot_turns WHERE thread_id=? AND revision=?',(binding['thread_id'],binding['thread_revision'])))
            # A run entry also leads to its reviewed original tasks, without a
            # title match or an unrelated global task-list fallback.
            pending=list(runs);linked=set()
            while pending:
                run_id=pending.pop()
                if run_id in linked:continue
                if len(linked)>=1000:errors.add('run_limit');break
                linked.add(run_id)
                row=db.execute('SELECT payload FROM agent_runs WHERE id=?',(run_id,)).fetchone()
                if not row:raise ValueError('agent_run_not_found')
                payload=object_json(row[0]);parent=payload.get('parent_id')
                if kind=='run' and run_id==id:demo=self._run_mode(db,payload)
                if parent:pending.append(parent)
                tasks.update(r[0]for r in db.execute('SELECT task_id FROM agent_actions WHERE run_id=?',(run_id,)))
                tasks.update(r[0]for r in db.execute('SELECT task_id FROM market_research_runs WHERE run_id=?',(run_id,)))
            runs.update(linked)
            for task_id in list(tasks):
                row=db.execute('SELECT payload,status FROM tasks WHERE id=?',(task_id,)).fetchone()
                if not row:raise ValueError('task_not_found')
                payload=object_json(row[0]);data=payload.get('input',{})
                if not isinstance(data,dict):raise ValueError('timeline_source_unavailable')
                research=db.execute('SELECT document FROM market_research_jobs WHERE task_id=?',(task_id,)).fetchone()
                research=object_json(research[0]) if research else None
                mode=data.get('demo') is True
                if data.get('organization_case') and 'demo' not in data:
                    case=db.execute('SELECT scope FROM org_cases WHERE id=?',(data['organization_case'],)).fetchone()
                    mode=object_json(case[0]).get('synthetic') is True if case else None
                if research:mode=research['_context'].get('demo') is True
                if kind=='task' and task_id==id:demo=mode
                source_modes['task',task_id]=mode
                event('task',task_id,'task_current',None,row[1],{'kind':text(payload.get('kind'),40),'payload_sha256':hashlib.sha256(canonical(payload).encode()).hexdigest()})
                execution=db.execute('SELECT operation,requested,started,finished,error,attempt FROM task_runs WHERE task_id=?',(task_id,)).fetchone()
                if execution:
                    operation,requested,started,finished,error,attempt=execution
                    detail={'operation':text(operation,40),'attempt':attempt}
                    event('task',task_id,'local_execution_requested',requested,detail=detail)
                    if started is not None:event('task',task_id,'local_execution_started',started,detail=detail)
                    if finished is not None:event('task',task_id,'local_execution_finished',finished,'failed' if error else 'completed',detail)
                runs.update(r[0]for r in db.execute('SELECT run_id FROM agent_actions WHERE task_id=?',(task_id,)))
                runs.update(r[0]for r in db.execute('SELECT run_id FROM market_research_runs WHERE task_id=?',(task_id,)))
                job=research
                if job:
                    source_modes['research',task_id]=job['_context'].get('demo') is True
                    if kind=='task' and task_id==id:demo=source_modes['research',task_id]
                    if kind=='task':
                        bound=db.execute('SELECT revision,context_sha FROM copilot_threads WHERE id=?',(job['thread_id'],)).fetchone()
                        origin=db.execute('SELECT t.revision,t.context_sha FROM copilot_turns t JOIN market_research_runs m ON m.run_id=t.run_id WHERE m.task_id=? ORDER BY t.rowid DESC LIMIT 1',(task_id,)).fetchone()
                        if not bound or not origin or tuple(bound)!=tuple(origin):scope_current=False
                    event('research',task_id,'research_current',job.get('updated_at'),job['status'],{'phase':job['phase'],'revision':job['revision'],'sources':job['source_count'],'candidates':job['candidate_count']})
            pending=list(runs);visited=set()
            while pending:
                run_id=pending.pop()
                if run_id in visited:continue
                if len(visited)>=1000:errors.add('run_limit');break
                visited.add(run_id)
                row=db.execute('SELECT payload,status,created,updated,trace,idem,result FROM agent_runs WHERE id=?',(run_id,)).fetchone()
                if not row:raise ValueError('agent_run_not_found')
                payload=object_json(row[0]);parent=payload.get('parent_id')
                if parent:pending.append(parent)
                mode=self._run_mode(db,payload);source_modes['run',run_id]=mode;source_modes['budget',run_id]=mode
                binding=db.execute('SELECT t.revision,t.context_sha,c.revision,c.context_sha FROM copilot_turns t JOIN copilot_threads c ON c.id=t.thread_id WHERE t.run_id=?',(run_id,)).fetchone()
                if kind=='run' and run_id==id and binding and binding[:2]!=binding[2:]:scope_current=False
                detail={'parent_id':parent,'request_summary':text(payload.get('question'),160),'request_sha256':hashlib.sha256(canonical(payload.get('question')).encode()).hexdigest()}
                if binding:detail.update(context_revision=binding[0],context_sha256=binding[1])
                event('run',run_id,'run_recovery_created' if row[5].startswith('research-resume:') else 'human_request',row[2],detail=detail)
                event('run',run_id,'run_current',row[3],row[1])
                for proposal_id,task_id,created in db.execute('SELECT proposal_id,task_id,created FROM agent_actions WHERE run_id=?',(run_id,)):
                    event('run',run_id,'proposal_submitted',created,detail={'proposal_id':proposal_id,'task_id':task_id},index=proposal_id)
                for attempt,phase,generation,host,status,created,updated in db.execute('SELECT id,phase,generation,host_id,status,created,updated FROM agent_host_attempts WHERE run_id=?',(run_id,)):
                    source_modes['host',attempt]=mode
                    event('host',attempt,'host_attempt_current',updated,status,{'phase':phase,'generation':generation,'host':host})
                steps=db.execute('SELECT step,kind,status,started,finished,seconds FROM chain_steps WHERE run_id=?',(run_id,)).fetchall()
                for step,category,status,started,finished,seconds in steps:
                    event('budget',run_id,'model_step' if category=='model' else 'read_step',started,status,{'step':step,'seconds':seconds,'finished_at':timestamp(finished)},index=step)
                trace=json.loads(row[4]);result=object_json(row[6]) if row[6] else {}
                if not isinstance(trace,list):raise ValueError('timeline_source_unavailable')
                observations=result.get('observations',[])
                observed={value.get('id'):value.get('observed_at')for value in observations if isinstance(value,dict)} if isinstance(observations,list) else {}
                for index,record in enumerate(trace):
                    if not isinstance(record,dict):errors.add('trace');continue
                    if record.get('event')=='model_turn' and not any(step[0]=='dialogue:'+str(record.get('turn'))for step in steps):
                        event('run',run_id,'model_step_legacy',None,detail={'turn':record.get('turn')},index=index)
                    if record.get('event')=='read_tool':
                        event('run',run_id,'read_evidence',observed.get(record.get('reference')),detail={'tool':text(record.get('tool'),100),'reference':record.get('reference'),'source_sha256':record.get('sha256')},index=index)
            runs=visited
            budgets=self.service.chain_budget.summaries(db,runs)
            # Each original follow-up stays in history, even when its notice is merged.
            for raw in db.execute('SELECT id,kind,ref,demo,revision,state,due,created,updated,target FROM followups'):
                followup_id,target_kind,ref,mode,revision,state,due,created,updated,target=raw;target=object_json(target)
                action=target.get('action') or {};binding=target['binding']
                related=followup_id in followups or target_kind=='task_result' and ref in tasks or action.get('type')=='agent' and action.get('id') in runs
                if not related and action.get('type')=='thread' and runs:
                    related=bool(db.execute('SELECT 1 FROM copilot_turns WHERE thread_id=? AND revision=? AND run_id IN ('+','.join('?'for _ in runs)+') LIMIT 1',(binding['thread_id'],binding['thread_revision'],*sorted(runs))).fetchone())
                if not related:continue
                source_modes['followup',followup_id]=bool(mode)
                event('followup',followup_id,'followup_created',created,detail={'kind':target_kind,'ref':ref,'source_version_sha256':target['version_sha256']})
                event('followup',followup_id,'followup_current',updated,state,{'due_at':due,'revision':revision})
                for checked_revision,checked_at,receipt in db.execute('SELECT revision,checked_at,receipt FROM followup_checks WHERE followup_id=?',(followup_id,)):
                    receipt=object_json(receipt)
                    event('followup',followup_id,'followup_checked',checked_at,receipt['condition'],{'revision':checked_revision,'observed':receipt['observed']},index=checked_revision)
        events.sort(key=lambda value:(value['at'] if value['at'] is not None else -math.inf,value['id']),reverse=True)
        fingerprint=hashlib.sha256(canonical(events).encode()).hexdigest();start=0
        if cursor:
            version,boundary=cursor.split(':',1)
            if version!=fingerprint:raise ValueError('timeline_changed')
            indices=[index for index,value in enumerate(events)if value['id']==boundary]
            if not indices:raise ValueError('timeline_invalid_cursor')
            start=indices[0]+1
        page=events[start:start+limit];more=start+limit<len(events)
        return {'kind':kind,'id':id,'demo':demo,'scope_current':scope_current,'read_only':True,'events':page,
            'mixed_modes':len({value['demo']for value in events if value['demo'] is not None})>1,
            'run_ids':sorted(runs),'budgets':budgets,'has_more':more,
            'next_cursor':fingerprint+':'+page[-1]['id'] if more else None,'complete':not errors,'source_errors':sorted(errors),
            'historical_transitions_complete':False,'missing_times':sum(value['at'] is None for value in events)}
