"""Pure job lifecycle; actual ownership and process signalling live in the runner."""
import re

STATES = frozenset(('queued','running','cancelling','cancelled','succeeded','failed','interrupted'))
RELATION = {
    'start': {'queued':'running'},
    'cancel': {'queued':'cancelled','running':'cancelling'},
    'finish_ok': {'running':'succeeded','cancelling':'cancelled'},
    'finish_error': {'running':'failed','cancelling':'cancelled'},
    'interrupt': {'running':'interrupted','cancelling':'cancelled'},
    'retry': {'failed':'queued','interrupted':'queued','cancelled':'queued'},
}
WORKER_EVENTS = frozenset(('start','finish_ok','finish_error','interrupt'))

def create(source,key,at):
    if not isinstance(source,str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',source):
        raise ValueError('invalid_collection_source')
    if not isinstance(key,str) or not key.strip() or len(key)>160:
        raise ValueError('invalid_idempotency_key')
    return {'source':source,'idempotency_key':key,'status':'queued','attempt':1,
            'created_at':at,'updated_at':at,'error':None}

def evolve(job,event,at,attempt=None,error=None):
    state=job.get('status')
    if state not in STATES or event not in RELATION:
        raise ValueError('invalid_collection_transition')
    result=dict(job)
    if event in WORKER_EVENTS and attempt is not None and attempt!=job['attempt']:
        return result
    if state not in RELATION[event] and event not in ('cancel','interrupt'):
        raise ValueError('invalid_collection_transition')
    target=RELATION[event].get(state,state)
    result.update(status=target,updated_at=max(at,job['updated_at']))
    if event=='retry':
        result.update(attempt=job['attempt']+1,error=None)
    elif event=='interrupt' and target=='interrupted':
        result['error']='worker_interrupted'
    elif event in ('finish_ok','finish_error'):
        valid=isinstance(error,str) and re.fullmatch('[a-z0-9_]{1,80}',error)
        result['error']=(error if valid else 'collection_failed') if target=='failed' else None
    elif event=='interrupt' and target=='cancelled':
        result['error']=None
    return result
