"""A2A 0.3.0 JSON-RPC polling subset backed by the shared durable copilot.

Primary contract: https://a2a-protocol.org/v0.3.0/specification/
Transport MUST authenticate/authorize local-user requests before dispatch. No SDK,
process-local task registry, streaming, callbacks, file fetching or proposal apply.
Each explicit message creates a new run/task in its context. Same-task continuation
is explicitly unsupported; use contextId for conversational follow-up.
"""
import hashlib
import json
from urllib.parse import urlsplit
from . import a2ui

STATES={'queued':'submitted','running':'working','cancel_requested':'working',
        'awaiting_input':'input-required','awaiting_review':'input-required',
        'completed':'completed','cancelled':'canceled','failed':'failed',
        'interrupted':'failed','blocked':'failed'}
TERMINAL={'completed','canceled','failed','rejected'}
ERRORS={-32600:'Invalid JSON-RPC Request',-32601:'Method not found',-32602:'Invalid method parameters',
        -32603:'Internal server error',-32001:'Task not found',-32002:'Task cannot be canceled',
        -32003:'Push Notification is not supported',-32004:'This operation is not supported',
        -32005:'Incompatible content types',-32007:'Authenticated Extended Card not configured'}


class RPCError(Exception):
    def __init__(self,code): self.code=code


def require(condition,code=-32602):
    if not condition: raise RPCError(code)


def shape(value,required=(),optional=()):
    require(isinstance(value,dict) and set(required)<=set(value) and not set(value)-set(required)-set(optional))


def string(value,maximum=160):
    require(isinstance(value,str) and 0<len(value)<=maximum and bool(value.strip()))
    return value


def agent_card(origin):
    parsed=urlsplit(origin)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('a2a_invalid_origin')
    return {'protocolVersion':'0.3.0','name':'Commerce conversational workbench',
        'description':'Shared local contextual analysis and human-review proposals. Restricted JSON-RPC polling subset; use contextId for follow-up tasks. No same-task continuation, streaming, push, files or external writes.',
        'url':origin.rstrip('/')+'/a2a','preferredTransport':'JSONRPC','version':'1.0.0',
        'capabilities':{'streaming':False,'pushNotifications':False,'stateTransitionHistory':False},
        'securitySchemes':{'localBearer':{'type':'http','scheme':'bearer'}},'security':[{'localBearer':[]}],
        'defaultInputModes':['text/plain'],'defaultOutputModes':['text/plain','application/json'],
        'skills':[{'id':'commerce_contextual_analysis','name':'Contextual analysis','description':'Read shared business evidence and draft proposals for local human review. Explicit sends enqueue a bounded existing runner.','tags':['commerce','analysis','human-review']}],
        'supportsAuthenticatedExtendedCard':False}


def _invoke(service,name,args): return service.invoke('commerce_copilot_'+name,args,'local')


def _lookup(service,ident):
    try:thread=service.copilot.lookup_run(ident)
    except (ValueError,KeyError):raise RPCError(-32001) from None
    turn=next((t for t in thread['turns'] if t['run']['id']==ident),None)
    require(turn is not None,-32001)
    return thread,turn['run']


def _task(thread,run,history_length=0):
    state=STATES.get(run.get('status'),'failed');ident=run['id'];context=thread['id']
    task={'kind':'task','id':ident,'contextId':context,'status':{'state':state},
          'metadata':{'commerce':{'runStatus':run.get('status','unknown'),'reviewRequired':run.get('status')=='awaiting_review','externalWrites':False}}}
    result=run.get('result') or {}
    if result.get('answer'):
        task['artifacts']=[{'artifactId':ident+'-answer','name':'Analysis and local review surface','parts':[
            {'kind':'text','text':str(result['answer'])[:8000]},
            {'kind':'data','data':{'a2uiVersion':'0.8','messages':a2ui.surface(run,thread.get('context'))}}]}]
    if history_length:
        turn=next(t for t in thread['turns'] if t['run']['id']==ident)
        task['history']=[{'kind':'message','messageId':turn['id'],'role':'user','taskId':ident,'contextId':context,'parts':[{'kind':'text','text':turn['question']}]}][-history_length:]
    return task


def _send(service,params):
    shape(params,['message'],['configuration'])
    config=params.get('configuration',{});shape(config,[],['blocking','acceptedOutputModes','historyLength'])
    require(config.get('blocking',False) is False,-32004)
    modes=config.get('acceptedOutputModes',['text/plain','application/json'])
    require(isinstance(modes,list) and len(modes)<=8 and all(isinstance(m,str) for m in modes))
    require(bool(set(modes)&{'text/plain','application/json'}),-32005)
    history=config.get('historyLength',0);require(type(history) is int and 0<=history<=20)
    message=params['message'];shape(message,['kind','role','messageId','parts'],['contextId','taskId','metadata'])
    require(message['kind']=='message' and message['role']=='user')
    message_id=string(message['messageId']);parts=message['parts'];require(isinstance(parts,list) and 1<=len(parts)<=8)
    text=[]
    for part in parts:
        require(isinstance(part,dict) and part.get('kind')=='text',-32005);shape(part,['kind','text']);text.append(string(part['text'],2000))
    text='\n'.join(text);require(len(text)<=2000)
    metadata=message.get('metadata',{});shape(metadata,[],['commerce'])
    explicit_context=metadata.get('commerce');require(explicit_context is None or isinstance(explicit_context,dict))
    key='a2a:'+hashlib.sha256(message_id.encode()).hexdigest()
    context_id=message.get('contextId')
    if 'taskId' in message:
        thread,run=_lookup(service,string(message['taskId']))
        require(context_id is None or context_id==thread['id'])
        # A task/run is immutable identity. Never silently replace its ID with a new run.
        raise RPCError(-32004)
    existing=service.copilot.lookup_message(key)
    if existing is not None:
        require(context_id is None or context_id==existing['id'])
        original=next((t for t in existing['turns'] if t.get('idempotency_key')==key or t['id']==key),None)
        require(original is not None,-32603)
        # Replays bind to the original turn, never the thread's mutable scope.
        # Durable lookup includes the exact turn even outside the recent page.
        frozen_context=original.get('context') or original['run'].get('parameters',{}).get('context') or existing['context']
        require(explicit_context is None or explicit_context==frozen_context)
        require(text.strip()==original['question'])
        return _task(existing,original['run'],history)
    elif context_id is not None:
        thread=_invoke(service,'get',{'thread_id':string(context_id)})
        require(explicit_context is None or explicit_context==thread['context'])
    else:
        thread=_invoke(service,'open',{'context':explicit_context or {'module':'agent','demo':False},'idempotency_key':key})
    # The backend's transactional idempotency rejects changes to text/scope.
    thread=_invoke(service,'send',{'thread_id':thread['id'],'message':text,'context_sha256':thread['context_sha256'],'idempotency_key':key})
    turn=next((t for t in thread['turns'] if t.get('idempotency_key')==key or t['id']==key),None)
    require(turn is not None,-32603)
    return _task(thread,turn['run'],history)


def dispatch(service,request):
    """Return a JSON-RPC response; caller owns HTTP auth and bounded JSON parsing."""
    ident=None
    try:
        require(isinstance(request,dict),-32600)
        candidate=request.get('id');require(candidate is None or type(candidate) in (str,int),-32600);ident=candidate
        require(set(request)<= {'jsonrpc','id','method','params'} and request.get('jsonrpc')=='2.0' and 'id' in request and isinstance(request.get('method'),str),-32600)
        try:require(len(json.dumps(request,allow_nan=False).encode())<=32768,-32600)
        except (ValueError,TypeError,RecursionError):raise RPCError(-32600) from None
        method=request['method'];params=request.get('params',{})
        if method=='message/send':result=_send(service,params)
        elif method in ('tasks/get','tasks/cancel'):
            shape(params,['id'],['historyLength'] if method=='tasks/get' else [])
            history=params.get('historyLength',0);require(type(history) is int and 0<=history<=20)
            thread,run=_lookup(service,string(params['id']))
            if method=='tasks/cancel':
                require(run['status'] in ('queued','running','cancel_requested'),-32002)
                _invoke(service,'cancel',{'thread_id':thread['id'],'run_id':run['id']});thread,run=_lookup(service,run['id'])
            result=_task(thread,run,history)
        elif method.startswith('tasks/pushNotificationConfig/'):
            raise RPCError(-32003)
        elif method in ('message/stream','tasks/resubscribe'):raise RPCError(-32004)
        elif method=='agent/getAuthenticatedExtendedCard':raise RPCError(-32007)
        else:raise RPCError(-32601)
        return {'jsonrpc':'2.0','id':ident,'result':result}
    except RPCError as error:code=error.code
    except (ValueError,KeyError,TypeError):code=-32602
    except Exception:code=-32603
    # Do not leak database, provider, paths, context or exception contents.
    return {'jsonrpc':'2.0','id':ident,'error':{'code':code,'message':ERRORS.get(code,'Internal server error')}}
