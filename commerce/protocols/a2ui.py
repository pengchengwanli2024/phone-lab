"""A2UI 0.8 standard-catalog subset; no model-authored HTML or executable actions.

Source: https://github.com/google/A2UI/tree/main/specification/v0_8/json
Only self-contained snapshots are accepted (not arbitrary incremental streams).
Text remains plain data; clients MUST escape it, including source evidence.
"""
import hashlib
import json
import re

VERSION = '0.8'
CATALOG = 'https://a2ui.org/specification/v0_8/standard_catalog_definition.json'
# SHA-256 of the official pinned-version schema bytes inspected at implementation.
SERVER_SCHEMA_SHA256 = '77babf290fcbf0a1ba1574dca2a3d17effc5f67ab78a7c68d7690cf0c7f1d43e'
CATALOG_SCHEMA_SHA256 = '1639716885e588f9e0d54f4b34304989dd4e6be01e18d8374741f1d2e6a08a2e'
ACTION = 'commerce.review_proposal'
_ID = re.compile(r'^[A-Za-z0-9_-]{1,160}$')
_KEY = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,79}$')


def _check(condition):
    if not condition: raise ValueError('a2ui_invalid_surface')


def _shape(value, required, optional=()):
    _check(isinstance(value, dict) and set(required)<=set(value) and not set(value)-set(required)-set(optional))


def _string(value, maximum=8000):
    _check(isinstance(value,str) and len(value)<=maximum)


def validate_surface(messages):
    """Raise ValueError for unsupported, ambiguous, oversized or unsafe trees."""
    try: encoded=json.dumps(messages,allow_nan=False).encode()
    except (TypeError,ValueError,RecursionError): raise ValueError('a2ui_invalid_surface') from None
    _check(len(encoded)<=65536 and isinstance(messages,list) and len(messages)==3)
    names=('surfaceUpdate','dataModelUpdate','beginRendering')
    for message,name in zip(messages,names): _shape(message,[name])
    update,data,begin=(m[n] for m,n in zip(messages,names))
    _shape(update,['surfaceId','components']);_shape(data,['surfaceId','contents'],['path']);_shape(begin,['surfaceId','root'],['catalogId'])
    sid=update['surfaceId'];_check(isinstance(sid,str) and bool(_ID.fullmatch(sid)))
    _check(data['surfaceId']==sid==begin['surfaceId'] and begin.get('catalogId',CATALOG)==CATALOG and data.get('path','/')=='/')
    contents=data['contents'];_check(isinstance(contents,list) and len(contents)<=32)
    model={}
    for entry in contents:
        _shape(entry,['key','valueString']);key=entry['key']
        _check(isinstance(key,str) and bool(_KEY.fullmatch(key)) and key not in model);_string(entry['valueString']);model[key]=entry['valueString']
    def bound(value, literal_only=False):
        _check(isinstance(value,dict) and len(value)==1)
        if 'literalString' in value: _string(value['literalString'])
        else:
            path=value.get('path');_check(not literal_only and isinstance(path,str) and path.startswith('/') and path[1:] in model)
    nodes=update['components'];_check(isinstance(nodes,list) and 1<=len(nodes)<=64)
    graph={}
    for node in nodes:
        _shape(node,['id','component']);ident=node['id'];_check(isinstance(ident,str) and bool(_ID.fullmatch(ident)) and ident not in graph)
        component=node['component'];_check(isinstance(component,dict) and len(component)==1)
        kind,props=next(iter(component.items()));children=[]
        if kind=='Text':
            _shape(props,['text'],['usageHint']);bound(props['text']);_check(props.get('usageHint','body') in ('h1','h2','h3','h4','h5','caption','body'))
        elif kind in ('Column','Row'):
            _shape(props,['children']);_shape(props['children'],['explicitList']);children=props['children']['explicitList'];_check(isinstance(children,list) and len(children)<=64)
        elif kind=='TextField':
            _shape(props,['label','text'],['textFieldType']);bound(props['label']);bound(props['text']);_check(props.get('textFieldType','shortText') in ('shortText','longText','number','date'))
        elif kind=='Button':
            _shape(props,['child','action']);children=[props['child']];action=props['action'];_shape(action,['name','context']);_check(action['name']==ACTION)
            ctx=action['context'];_check(isinstance(ctx,list) and len(ctx)==3);keys=set()
            for entry in ctx:
                _shape(entry,['key','value']);_check(isinstance(entry['key'],str) and entry['key'] not in keys);keys.add(entry['key']);bound(entry['value'],True)
            _check(keys=={'run_id','proposal_id','result_sha256'})
        else: raise ValueError('a2ui_unsupported_component')
        _check(all(isinstance(c,str) and bool(_ID.fullmatch(c)) for c in children));graph[ident]=children
    root=begin['root'];_check(isinstance(root,str) and root in graph)
    seen=set();active=set()
    def visit(ident,depth):
        _check(depth<=16 and ident in graph and ident not in active and ident not in seen)
        active.add(ident)
        for child in graph[ident]:visit(child,depth+1)
        active.remove(ident);seen.add(ident)
    visit(root,0);_check(len(seen)==len(graph))
    return True


def surface(run, context=None):
    """Project trusted runtime result fields into bounded standard components."""
    result=run.get('result') or {};sid='run-'+hashlib.sha256(str(run.get('id','')).encode()).hexdigest()[:24]
    nodes=[{'id':'root','component':{'Column':{'children':{'explicitList':[]}}}}];children=nodes[0]['component']['Column']['children']['explicitList'];data=[]
    def text(ident,value,hint=None):
        props={'text':{'literalString':str(value)[:8000]}}
        if hint: props['usageHint']=hint
        nodes.append({'id':ident,'component':{'Text':props}});children.append(ident)
    text('answer',result.get('answer') or '当前状态：'+str(run.get('status','unknown')))
    refs=result.get('evidence_refs') or []
    text('evidence','证据引用：'+('、'.join(str(r)[:200] for r in refs[:12]) if refs else '暂无已核实引用')+'。当前输出未经独立核实。','caption')
    for index,question in enumerate((result.get('questions') or [])[:3]):
        key='question_'+str(index);data.append({'key':key,'valueString':''});ident='input_'+str(index)
        nodes.append({'id':ident,'component':{'TextField':{'label':{'literalString':str(question)[:400]},'text':{'path':'/'+key},'textFieldType':'longText'}}});children.append(ident)
    digest=run.get('result_sha256')
    if isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest):
        for index,proposal in enumerate((result.get('proposals') or [])[:3]):
            label='label_'+str(index);button='review_'+str(index)
            nodes.append({'id':label,'component':{'Text':{'text':{'literalString':'审阅建议：'+str(proposal.get('reason',''))[:500]}}}})
            ctx=[{'key':k,'value':{'literalString':str(v)}} for k,v in [('run_id',run['id']),('proposal_id',proposal['id']),('result_sha256',digest)]]
            nodes.append({'id':button,'component':{'Button':{'child':label,'action':{'name':ACTION,'context':ctx}}}});children.append(button)
    messages=[{'surfaceUpdate':{'surfaceId':sid,'components':nodes}},{'dataModelUpdate':{'surfaceId':sid,'path':'/','contents':data}},{'beginRendering':{'surfaceId':sid,'root':'root','catalogId':CATALOG}}]
    validate_surface(messages)
    return messages
