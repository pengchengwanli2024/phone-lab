"""No executable expressions: bounded JSON schemas, mappings and conditions only."""
import hashlib
import json
import math
import re
from urllib.parse import urlsplit
from .contracts import KINDS,SAFE_BUILTINS,PROTECTED_BUILTINS,DEFAULT_LIMITS,HARD_LIMITS

SECRET=re.compile(r'(api.?key|password|secret|authorization|credential|access.?token|refresh.?token)',re.I)
ID=re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,79}$')
SCHEMA_KEYS={'type','properties','required','additionalProperties','items','enum','minimum','maximum','minLength','maxLength','minItems','maxItems','description'}

def encoded(value,limit=128000):
    try:raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    except (TypeError,ValueError,RecursionError):raise ValueError('extension_invalid_json') from None
    if len(raw.encode())>limit:raise ValueError('extension_data_too_large')
    return raw

def sha(value):return hashlib.sha256(encoded(value).encode()).hexdigest()

def object_keys(value,required=(),optional=()):
    if not isinstance(value,dict) or set(required)-set(value) or set(value)-set(required)-set(optional):raise ValueError('extension_invalid_definition')

def text(value,maximum=160):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError('extension_invalid_text')
    return value

def no_secrets(value,depth=0):
    if depth>20:raise ValueError('extension_definition_too_deep')
    if isinstance(value,dict):
        for k,v in value.items():
            if SECRET.search(str(k)):raise ValueError('extension_credentials_private_setup_only')
            no_secrets(v,depth+1)
    elif isinstance(value,list):
        for v in value:no_secrets(v,depth+1)
    elif isinstance(value,str) and re.search(r'(Bearer\s+\S+|sk-[A-Za-z0-9_-]{16,}|https?://[^/\s]*@)',value,re.I):raise ValueError('extension_credentials_private_setup_only')

def redact(value,secrets=(),depth=0):
    if depth>24:return '[bounded]'
    if isinstance(value,dict):return {str(k):('[redacted]' if SECRET.search(str(k)) else redact(v,secrets,depth+1)) for k,v in value.items()}
    if isinstance(value,list):return [redact(v,secrets,depth+1) for v in value[:200]]
    if isinstance(value,str):
        for secret in secrets:
            if secret:value=value.replace(secret,'[redacted]')
        value=re.sub(r'Bearer\s+[^\s"\']+','Bearer [redacted]',value,flags=re.I)
        value=re.sub(r'sk-[A-Za-z0-9_-]{16,}','[redacted]',value)
        return value
    return value

def schema_check(schema,depth=0):
    if depth>12 or not isinstance(schema,dict) or set(schema)-SCHEMA_KEYS:raise ValueError('extension_unsupported_schema')
    typ=schema.get('type')
    if typ is not None and typ not in ('object','array','string','number','integer','boolean','null'):raise ValueError('extension_unsupported_schema')
    if 'properties' in schema:
        if typ!='object' or not isinstance(schema['properties'],dict) or len(schema['properties'])>64:raise ValueError('extension_unsupported_schema')
        for rule in schema['properties'].values():schema_check(rule,depth+1)
    if 'required' in schema and (not isinstance(schema['required'],list) or any(not isinstance(k,str) for k in schema['required']) or len(set(schema['required']))!=len(schema['required']) or set(schema['required'])-set(schema.get('properties',{}))):raise ValueError('extension_unsupported_schema')
    if 'additionalProperties' in schema and type(schema['additionalProperties']) is not bool:raise ValueError('extension_unsupported_schema')
    if 'items' in schema:
        if typ!='array':raise ValueError('extension_unsupported_schema')
        schema_check(schema['items'],depth+1)
    if 'enum' in schema and (not isinstance(schema['enum'],list) or not 1<=len(schema['enum'])<=100):raise ValueError('extension_unsupported_schema')
    for key in ('minimum','maximum','minLength','maxLength','minItems','maxItems'):
        if key in schema and (type(schema[key]) not in (float,int) or not math.isfinite(schema[key]) or ('Length' in key or 'Items' in key) and (type(schema[key]) is not int or not 0<=schema[key]<=128000)):raise ValueError('extension_unsupported_schema')
    for low,high in (('minimum','maximum'),('minLength','maxLength'),('minItems','maxItems')):
        if low in schema and high in schema and schema[low]>schema[high]:raise ValueError('extension_unsupported_schema')

def validate(value,schema,depth=0):
    if depth>20:raise ValueError('extension_schema_depth')
    typ=schema.get('type');valid={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),'number':type(value) in (int,float),'integer':type(value) is int,'boolean':type(value) is bool,'null':value is None}
    if typ and not valid.get(typ,False):raise ValueError('extension_schema_type')
    if 'enum' in schema and not any(type(value) is type(v) and value==v for v in schema['enum']):raise ValueError('extension_schema_enum')
    if isinstance(value,dict):
        props=schema.get('properties',{})
        if set(schema.get('required',[]))-set(value) or schema.get('additionalProperties') is False and set(value)-set(props):raise ValueError('extension_schema_fields')
        for key,v in value.items():
            if key in props:validate(v,props[key],depth+1)
    if isinstance(value,list):
        if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',1000):raise ValueError('extension_schema_items')
        for v in value:validate(v,schema.get('items',{}),depth+1)
    if isinstance(value,str) and not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',128000):raise ValueError('extension_schema_length')
    if type(value) in (int,float) and (not math.isfinite(value) or value<schema.get('minimum',-math.inf) or value>schema.get('maximum',math.inf)):raise ValueError('extension_schema_number')

def limits(value=None,base=None):
    if value is None:value={}
    if not isinstance(value,dict) or set(value)-set(DEFAULT_LIMITS):raise ValueError('extension_invalid_budget')
    result={**DEFAULT_LIMITS,**(base or {})}
    for k,v in value.items():
        if type(v) is not int or not (0 if k=='max_model_calls' else 1)<=v<=HARD_LIMITS[k]:raise ValueError('extension_invalid_budget')
        result[k]=min(v,result[k]) if base else v
    return result

def scope_check(value):
    object_keys(value,(),('case_id','project_id','platform','store_id','market'))
    for v in value.values():text(v)
    return value

def endpoint(value):
    text(value,1000)
    try:
        p=urlsplit(value);port=p.port
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment or p.hostname.lower()=='metadata.google.internal' or any(x in p.path for x in ('..','%','\\')):raise ValueError()
        if p.scheme=='http' and p.hostname not in ('localhost','127.0.0.1','::1'):raise ValueError()
        if port is not None and not 1<=port<=65535:raise ValueError()
    except ValueError:raise ValueError('extension_invalid_endpoint') from None
    return value

def mapping_check(value,depth=0):
    if depth>16:raise ValueError('extension_mapping_depth')
    if isinstance(value,dict):
        if '$ref' in value:
            if set(value)!={'$ref'} or not isinstance(value['$ref'],str) or not re.fullmatch(r'(input|scope|steps|output)(\.[A-Za-z0-9_-]+)*',value['$ref']):raise ValueError('extension_invalid_reference')
        else:
            for v in value.values():mapping_check(v,depth+1)
    elif isinstance(value,list):
        for v in value:mapping_check(v,depth+1)

def mapping(value,context):
    if isinstance(value,dict):
        if '$ref' in value:
            current=context
            for k in value['$ref'].split('.'):
                if isinstance(current,dict) and k in current:current=current[k]
                elif isinstance(current,list) and k.isdigit() and int(k)<len(current):current=current[int(k)]
                else:raise ValueError('extension_reference_missing')
            return current
        return {k:mapping(v,context) for k,v in value.items()}
    if isinstance(value,list):return [mapping(v,context) for v in value]
    return value

def condition_check(value,depth=0):
    if depth>8:raise ValueError('extension_condition_depth')
    if not isinstance(value,dict) or value.get('op') not in ('eq','ne','gt','gte','lt','lte','contains','exists','and','or','not'):raise ValueError('extension_invalid_condition')
    op=value['op']
    if op in ('and','or'):
        object_keys(value,('op','conditions'))
        if not isinstance(value['conditions'],list) or not 1<=len(value['conditions'])<=8:raise ValueError('extension_invalid_condition')
        for c in value['conditions']:condition_check(c,depth+1)
    elif op=='not':object_keys(value,('op','condition'));condition_check(value['condition'],depth+1)
    else:object_keys(value,('op','left'),('right',));mapping_check(value['left']);mapping_check(value.get('right'))

def condition(value,context):
    op=value['op']
    if op=='and':return all(condition(c,context) for c in value['conditions'])
    if op=='or':return any(condition(c,context) for c in value['conditions'])
    if op=='not':return not condition(value['condition'],context)
    try:left=mapping(value['left'],context)
    except ValueError:
        if op=='exists':return False
        raise
    if op=='exists':return left is not None
    right=mapping(value.get('right'),context)
    if op in ('eq','ne'):
        equal=type(left) is type(right) and left==right
        return equal if op=='eq' else not equal
    if op=='contains':return isinstance(left,(str,list,dict)) and right in left
    if type(left) not in (int,float) or type(right) not in (int,float):raise ValueError('extension_condition_types')
    return {'gt':left>right,'gte':left>=right,'lt':left<right,'lte':left<=right}[op]

def definition(value):
    encoded(value,64000);no_secrets(value)
    object_keys(value,('kind','name','spec'),('id','description','input_schema','output_schema','limits'))
    value=json.loads(encoded(value));text(value['name'],120)
    if value['kind'] not in KINDS:raise ValueError('extension_invalid_kind')
    if 'id' in value and not re.fullmatch('ext_[a-f0-9]{20}',value['id']):raise ValueError('extension_invalid_id')
    if 'description' in value:text(value['description'],3000)
    for k in ('input_schema','output_schema'):schema_check(value.get(k,{}))
    value['limits']=limits(value.get('limits'));spec=value['spec']
    if value['kind'] in ('skill','workflow'):
        object_keys(spec,('steps',),('output','instructions'))
        if 'instructions' in spec:text(spec['instructions'],12000)
        if not isinstance(spec['steps'],list) or not 1<=len(spec['steps'])<=32:raise ValueError('extension_invalid_steps')
        ids=set()
        for step in spec['steps']:
            object_keys(step,('id','uses'),('input','when'))
            if not isinstance(step['id'],str) or not ID.fullmatch(step['id']) or step['id'] in ids:raise ValueError('extension_invalid_step_id')
            ids.add(step['id']);uses=step['uses'];object_keys(uses,(),('builtin','extension_id','version'))
            if ('builtin' in uses)==('extension_id' in uses):raise ValueError('extension_invalid_step')
            if 'builtin' in uses and uses['builtin'] not in SAFE_BUILTINS:raise ValueError('extension_builtin_not_allowed')
            if 'extension_id' in uses and (not isinstance(uses['extension_id'],str) or not re.fullmatch('ext_[a-f0-9]{20}',uses['extension_id'])):raise ValueError('extension_invalid_dependency')
            if 'version' in uses and (type(uses['version']) is not int or uses['version']<1):raise ValueError('extension_invalid_version')
            mapping_check(step.get('input',{}))
            if 'when' in step:condition_check(step['when'])
        mapping_check(spec.get('output',{}))
    elif value['kind']=='plugin':
        object_keys(spec,('transport','tool','effect'),('endpoint','method'))
        if spec['effect'] not in ('read','external_write'):raise ValueError('extension_invalid_effect')
        text(spec['tool'])
        if spec['transport']=='builtin':
            if spec['tool'] not in SAFE_BUILTINS:raise ValueError('extension_builtin_not_allowed')
            if spec['effect']!=('external_write' if spec['tool'] in PROTECTED_BUILTINS else 'read'):raise ValueError('extension_builtin_effect_mismatch')
            if set(spec)-{'transport','tool','effect'}:raise ValueError('extension_invalid_plugin')
        elif spec['transport'] in ('http','mcp_http'):
            endpoint(spec.get('endpoint'));method=spec.get('method','GET' if spec['effect']=='read' else 'POST')
            if method not in ('GET','POST') or spec['transport']=='http' and spec['effect']=='read' and method!='GET':raise ValueError('extension_read_plugin_requires_get')
            spec['method']='POST' if spec['transport']=='mcp_http' else method
        else:raise ValueError('extension_invalid_transport')
    else:
        object_keys(spec,('instructions','tools'),('model_id','max_turns'))
        text(spec['instructions'],12000);text(spec.get('model_id','project-default'))
        if not isinstance(spec['tools'],list) or len(spec['tools'])>12 or any(not isinstance(v,str) or not re.fullmatch('ext_[a-f0-9]{20}',v) for v in spec['tools']) or len(set(spec['tools']))!=len(spec['tools']):raise ValueError('extension_invalid_agent_tools')
        if type(spec.get('max_turns',4)) is not int or not 1<=spec.get('max_turns',4)<=20:raise ValueError('extension_invalid_agent_turns')
    return value
