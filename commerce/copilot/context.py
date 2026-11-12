"""Small explicit business scope, never an import of a host chat or credentials."""
import copy
import re
from agent_runtime.policy import canonical

MODULES=('overview','orders','products','operations','alerts','support','insights','research','intelligence','creative','pilots','agent','exposure','organization','tasks','platforms','live','skills','connections')
FIELDS={'module','demo','platform','store_id','market','entity','calculator','input'}
CONTEXT_SCHEMA={'type':'object','properties':{'module':{'type':'string','enum':list(MODULES)},'demo':{'type':'boolean'},**{k:{'type':'string','maxLength':160} for k in ('platform','store_id','market')},'entity':{'type':'object','properties':{'kind':{'type':'string','maxLength':40},'id':{'type':'string','maxLength':160}},'required':['kind','id'],'additionalProperties':False},'calculator':{'type':'string','enum':['unit_economics','restock_plan']},'input':{'type':'object'}},'required':['module'],'additionalProperties':False}
FORBIDDEN=re.compile(r'(password|passwd|secret|token|credential|authorization|api.?key|chat_history|messages|private.?key|cookie)',re.I)


def validate_context(value):
    try:size=len(canonical(value).encode())
    except (ValueError,TypeError,RecursionError):raise ValueError('copilot_invalid_context') from None
    if not isinstance(value,dict) or set(value)-FIELDS or size>8000 or value.get('module') not in MODULES:raise ValueError('copilot_invalid_context')
    if 'demo' in value and type(value['demo']) is not bool:raise ValueError('copilot_invalid_context')
    for key in ('platform','store_id','market'):
        if key in value and (not isinstance(value[key],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',value[key])):raise ValueError('copilot_invalid_context')
    if 'entity' in value:
        entity=value['entity']
        if not isinstance(entity,dict) or set(entity)!={'kind','id'} or any(not isinstance(entity[k],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',entity[k]) for k in entity):raise ValueError('copilot_invalid_context')
        if len(entity['kind'])>40:raise ValueError('copilot_invalid_context')
    if ('calculator' in value and value['calculator'] not in ('unit_economics','restock_plan')) or ('input' in value and ('calculator' not in value or not isinstance(value['input'],dict))):raise ValueError('copilot_invalid_context')
    def walk(item,depth=0):
        if depth>8:raise ValueError('copilot_invalid_context')
        if isinstance(item,dict):
            for k,v in item.items():
                if not isinstance(k,str) or FORBIDDEN.search(k):raise ValueError('copilot_invalid_context')
                walk(v,depth+1)
        elif isinstance(item,list):
            if len(item)>100:raise ValueError('copilot_invalid_context')
            for v in item:walk(v,depth+1)
        elif not isinstance(item,(str,int,float,bool,type(None))):raise ValueError('copilot_invalid_context')
        elif isinstance(item,str) and (len(item)>1000 or re.search(r'(?i)(bearer\s|sk-[a-zA-Z0-9]{16}|-----BEGIN .*PRIVATE KEY|/Users/|/home/)',item)):raise ValueError('copilot_invalid_context')
    walk(value)
    return copy.deepcopy(value)


def route(context):
    # All modules share this scope policy: exact context parameters, bounded reads.
    return 'workspace',{'context':copy.deepcopy(context)}
