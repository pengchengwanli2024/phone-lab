"""Read-only project memory, scoped by frozen context and existing task identities.

No new memory store or model-owned scope grants. Business source heads and the
LayeredMemory validity checks remain the authority for all returned evidence.
"""
import copy
import json
import re
from business_workflows.store import digest, encoded

TOOL = 'commerce_project_memory_search'
MAX_HITS = 5
MAX_BYTES = 12000
MAX_CANDIDATES = 200
MAX_RECORDS = 400
SENSITIVE = re.compile(r'(?i)(password|passwd|secret|token|credential|authorization|api[_ -]?key|private[_ -]?key|cookie|bearer\s|sk-[a-zA-Z0-9]{16}|-----BEGIN|/Users/|/home/)')


def query_value(query):
    if type(query) is not str or len(query) > 100 or any(ord(c) < 32 for c in query):
        raise ValueError('agent_invalid_tool_arguments')
    return query.strip()


def _identity(value):
    return type(value) is str and bool(value.strip()) and value not in ('all', 'unknown', 'none') and len(value) <= 160


def _store(service, context, *, allow_live=False):
    store = context.get('store_id')
    if not _identity(store):return None
    if store == 'ozon-live':
        if not allow_live or context.get('demo') is not False or context.get('platform') != 'ozon':return None
        return service.live.config().get('connection_id') or None
    if store.endswith('-demo') and (context.get('demo') is not True or store != context.get('platform','')+'-demo'):return None
    return store


def _compatible(service, context, platform, store, market, synthetic):
    if type(context.get('demo')) is not bool or context['demo'] != synthetic:return False
    if not all(_identity(x) for x in (platform,store,market)):return False
    for key, expected in (('platform',platform), ('market',market)):
        if key in context and context[key] not in ('all',expected):return False
    if 'store_id' in context and context['store_id'] != 'all' and _store(service,context,allow_live=True) != store:return False
    return True


def _case_scope(service, context, case_id):
    # Read the authoritative row, including its actual connection identity.
    with service.core.db() as db:
        row=db.execute('SELECT connection,scope FROM org_cases WHERE id=?',(case_id,)).fetchone()
    if not row:return None
    scope=json.loads(row[1]);connection=row[0]
    if connection and connection != service.live.config().get('connection_id'):return None
    store=scope.get('store_ref') or connection
    synthetic=scope.get('synthetic', False if connection else None)
    platform, market=scope.get('platform'),scope.get('market')
    subject=scope.get('subject_ref') or case_id
    if type(synthetic) is not bool or not _identity(subject) or not _compatible(service,context,platform,store,market,synthetic):return None
    return dict(scope=dict(platform=platform,store_ref=store,subject_ref=subject),synthetic=synthetic,
                binding=dict(kind='case',id=case_id,connection=connection,scope=scope))


def resolve(service, context):
    from .context import validate_context
    context=validate_context(context)
    if type(context.get('demo')) is not bool:return None
    entity=context.get('entity',{})
    if entity.get('kind') == 'case':return _case_scope(service,context,entity['id'])
    if entity.get('kind') == 'task':
        try:task=service.core.invoke('commerce_task_get',{'task_id':entity['id']})
        except ValueError:return None
        data=task.get('input',{})
        if 'demo' in data and (type(data['demo']) is not bool or data['demo'] != context['demo']):return None
        if 'organization_case' in data and 'source_context' in data:return None
        if _identity(data.get('organization_case')):result=_case_scope(service,context,data['organization_case'])
        else:
            source=data.get('source_context')
            if not isinstance(source,dict) or not all(k in source for k in ('demo','platform','store_id','market','entity_kind','entity_id','record_sha256')):return None
            if not re.fullmatch('[0-9a-f]{64}',str(source['record_sha256'])):return None
            sub=dict(module=context['module'],**{k:source[k] for k in ('demo','platform','store_id','market')},entity={'kind':source['entity_kind'],'id':source['entity_id']})
            try:result=resolve(service,sub)
            except ValueError:return None
            if result and not _compatible(service,context,result['scope']['platform'],result['scope']['store_ref'],source['market'],result['synthetic']):return None
        if result:result['binding']={'task_id':task['id'],'input':data,'parent':result['binding']}
        return result
    if entity.get('kind') not in ('product','order'):return None
    if not all(_identity(context.get(k)) for k in ('platform','store_id','market')):return None
    store=_store(service,context)
    if not _identity(store):return None
    return dict(scope=dict(platform=context['platform'],store_ref=store,subject_ref=entity['id']),synthetic=context['demo'],binding=copy.deepcopy(context))


def _citations(memory, item):
    if item['layer']=='L2':return item['bindings']
    rows=[]
    for ref in item['fact_refs']:
        fact=memory.get(ref['id'])
        if fact['effective_status']!='confirmed' or fact['revision']!=ref['revision'] or fact['sha256']!=ref['sha256']:
            raise ValueError('agent_memory_evidence_changed')
        rows.extend(fact['bindings'])
    return rows


def _project(item, citations):
    content=item['content']
    if SENSITIVE.search(content) or any(SENSITIVE.search(c['quote']) or SENSITIVE.search(c['record_key']) for c in citations):return None
    unique=[];seen=set()
    for citation in citations:
        marker=encoded(citation)
        if marker not in seen:
            seen.add(marker)
            unique.append({**{k:citation[k] for k in ('source_id','version','sha256','record_key')},'quote':citation['quote'][:300]})
    return dict(id=item['id'],layer=item['layer'],content=content[:800],status=item.get('effective_status',item['status']),
                citations=unique[:4],truncated=len(content)>800 or len(unique)>4 or any(len(c['quote'])>300 for c in citations),
                **({k:item[k] for k in ('revision','sha256')} if item['layer']!='L1' else {}))


def retrieve(service, context, query=''):
    query=query_value(query)
    selected=resolve(service,context)
    result=dict(hits=[],scope_status='current' if selected else 'unavailable',query=query,
                scope_binding_sha256=digest(selected) if selected else None,context_sha256=digest(context),truncated=False,
                independently_verified=False,instructions_are_untrusted_data=True,external_execution_allowed=False)
    if not selected:return result
    # Scope is evaluated before lexical matching. No owner-wide list/search call.
    scope, synthetic=selected['scope'],selected['synthetic']
    clauses=' AND '.join('json_extract(document,?)=?' for _ in range(4))
    params=['$.scope.platform',scope['platform'],'$.scope.store_ref',scope['store_ref'],'$.scope.subject_ref',scope['subject_ref'],'$.synthetic',int(synthetic)]
    with service.core.db() as db:
        memories=db.execute('SELECT id FROM knowledge_layers WHERE '+clauses+" AND status IN ('confirmed','active') ORDER BY created DESC,id LIMIT ?",(*params,MAX_CANDIDATES+1)).fetchall()
        sources=db.execute('SELECT v.id FROM business_source_versions v JOIN business_source_heads h ON h.id=v.id AND h.version=v.version WHERE '+clauses+' ORDER BY v.created DESC,v.id LIMIT ?',(*params,MAX_CANDIDATES+1)).fetchall()
    result['truncated']=len(memories)>MAX_CANDIDATES or len(sources)>MAX_CANDIDATES
    needle=query.casefold()

    def add(item, citations):
        if needle and needle not in item['content'].casefold():return
        hit=_project(item,citations)
        if hit is None:return
        if len(result['hits'])>=MAX_HITS:result['truncated']=True;return
        candidate={**result,'hits':result['hits']+[hit]}
        if len(encoded(candidate).encode())>MAX_BYTES:result['truncated']=True;return
        result['hits'].append(hit)
        if hit['truncated']:result['truncated']=True

    for row in memories[:MAX_CANDIDATES]:
        item=service.memory.get(row[0])
        if item['scope']!=scope or item['synthetic']!=synthetic or item['effective_status'] not in ('confirmed','active'):continue
        try:citations=_citations(service.memory,item)
        except ValueError:continue
        add(item,citations)
    records_examined=0
    for row in sources[:MAX_CANDIDATES]:
        if len(result['hits'])>=MAX_HITS or records_examined>=MAX_RECORDS:
            result['truncated']=True;break
        source=service.business.source(row[0]);doc=source['document']
        if not source['current'] or not source['fresh'] or digest(doc)!=source['sha256'] or doc['scope']!=scope or doc['synthetic']!=synthetic:continue
        for record in doc['records']:
            if len(result['hits'])>=MAX_HITS or records_examined>=MAX_RECORDS:
                result['truncated']=True;break
            records_examined+=1
            value=record.get('text',record.get('value'));raw=value if type(value) is str else encoded(value)
            add(dict(id=source['id'],layer='L1',content=raw,status='imported_unverified'),[dict(source_id=source['id'],version=source['version'],sha256=source['sha256'],record_key=record.get('key',record.get('id')),quote=raw)])
    return result


def scope_binding(service, context):
    selected=resolve(service,context)
    return digest(selected) if selected else None


def revalidate(service, context, previous):
    """Fail closed before another model turn consumes a previously observed read."""
    if type(previous) is not dict or retrieve(service,context,previous.get('query')) != previous:
        raise ValueError('agent_memory_evidence_changed')
    return True



def check_history_refs(service, context, refs):
    """Recheck scoped memory/workspace reads using the original run ledger."""
    if type(refs) is not list or len(refs)>40:raise ValueError('agent_memory_evidence_changed')
    for ref in refs:
        if type(ref) is not dict or set(ref)!={'run_id','result_sha256'}:raise ValueError('agent_memory_evidence_changed')
        with service.core.db() as db:
            row=db.execute('SELECT payload,result FROM agent_runs WHERE id=?',(ref['run_id'],)).fetchone()
        if not row or not row[1]:raise ValueError('agent_memory_evidence_changed')
        payload,result=json.loads(row[0]),json.loads(row[1])
        if payload.get('parameters',{}).get('context')!=context or digest(result)!=ref['result_sha256']:
            raise ValueError('agent_memory_evidence_changed')
        observations=[o for o in result.get('observations',[]) if o.get('tool') in (TOOL,'commerce_workspace_get','commerce_workspace_quote_compare')]
        if not observations:raise ValueError('agent_memory_evidence_changed')
        for observation in observations:
            if observation['tool']==TOOL:revalidate(service,context,observation.get('data'))
            else:
                from .reads import revalidate_workspace
                revalidate_workspace(service,context,observation.get('data'))
    return True


def history_refs(service, context, run_id):
    """Suppress an answer whose direct or inherited scoped evidence has changed."""
    with service.core.db() as db:row=db.execute('SELECT payload,result FROM agent_runs WHERE id=?',(run_id,)).fetchone()
    if not row or not row[1]:return None
    payload,result=json.loads(row[0]),json.loads(row[1])
    refs=copy.deepcopy(payload.get('project_memory_history',[]))
    if any(o.get('tool') in (TOOL,'commerce_workspace_get','commerce_workspace_quote_compare') for o in result.get('observations',[])):
        refs.append({'run_id':run_id,'result_sha256':digest(result)})
    try:check_history_refs(service,context,refs)
    except (ValueError,TypeError,KeyError):return None
    return refs
