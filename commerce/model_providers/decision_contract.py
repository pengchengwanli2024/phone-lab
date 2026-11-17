"""Typed local-model decisions; parent scope and execution checks stay authoritative."""
import copy
import re


def object_schema(properties,required=None):
    return {'type':'object','properties':properties,'required':list(properties)if required is None else required,'additionalProperties':False}


def context(payload):
    parameters=payload.get('parameters')or{}
    return parameters.get('context',parameters)


def required_read(payload,public_analysis):
    if public_analysis or payload.get('evidence_required')is False:return None
    ctx=context(payload);calculator=ctx.get('calculator')
    if calculator in('unit_economics','restock_plan')and isinstance(ctx.get('input'),dict):name='commerce_'+calculator
    elif ctx.get('entity',{}).get('kind')=='case':name='commerce_workspace_get'
    else:return None
    return name if not any(o.get('tool')==name for o in payload.get('observations',[]))else None


def requested_period(payload):
    question=payload.get('question','')
    if re.search(r'(?:24|二十四)\s*小时',question):return '24h'
    if re.search(r'今日|今天|today',question,re.I):return 'today'
    if re.search(r'(?:7|七)\s*(?:天|日)',question):return '7d'
    return None


def arguments_schema(call,payload):
    name=call['tool'];arguments=call.get('arguments',{})
    string={'type':'string'}
    if name in('commerce_web_search','commerce_web_read'):
        from public_web import definitions,explicit_urls,result_urls
        schemas={name:spec for name,_,spec in definitions(object_schema,string)}
        spec=schemas[name]
        period=requested_period(payload)
        if period:
            spec['properties']['period']={'type':'string','enum':[period]}
            if 'period'not in spec['required']:spec['required'].append('period')
        if name=='commerce_web_search':
            from public_web import REGIONS
            regions=[key for key,(_,aliases)in REGIONS.items()if any(alias in payload.get('question','').lower()for alias in aliases)][:3]
            if regions:
                spec['properties']['regions']={'type':'array','enum':[regions]}
                if 'regions'not in spec['required']:spec['required'].append('regions')
        if name=='commerce_web_read':
            urls=set(explicit_urls(payload.get('question','')))
            for observation in payload.get('observations',[]):urls.update(result_urls(observation.get('data',{})))
            if not urls:return None
            spec['properties']['urls']['items']['enum']=sorted(urls)
        return spec
    if name in('commerce_skills_search','commerce_project_memory_search'):
        return object_schema({'query':{'type':'string','maxLength':100}},[])
    if name=='commerce_intel_live_get':return object_schema({'query':{'type':'string','maxLength':64}},[])
    if name=='commerce_intel_search':
        from agent_runtime.policy import source_ids
        return object_schema({'query':{'type':'string','maxLength':100},'source':{'type':'string','enum':list(source_ids())}},[])
    if name in('commerce_skills_get','commerce_skills_readiness','commerce_intel_item_get'):
        field='item_id'if name=='commerce_intel_item_get'else'skill_id'
        literal=arguments.get(field)
        ids=[literal]if isinstance(literal,str)and re.fullmatch('[a-f0-9]{24}',literal)else[]
        source_tool='commerce_intel_search'if field=='item_id'else'commerce_skills_search'
        for observation in payload.get('observations',[]):
            if observation.get('tool')==source_tool:ids.extend(row['id']for row in observation.get('data',{}).get('items',[])if isinstance(row,dict)and isinstance(row.get('id'),str))
        return object_schema({field:{'type':'string','enum':list(dict.fromkeys(ids))}})if ids else None
    if name=='commerce_workspace_quote_compare':
        return object_schema({'case_id':{'type':'string','enum':[arguments['case_id']]},'quantity':{'type':'integer','minimum':1,'maximum':1000000000}})
    # These menus already carry exact server-owned scope arguments and inputs.
    if not any(word in str(arguments)for word in('at most','one ID','one id','optional','whole units')):
        return {'type':'object','enum':[copy.deepcopy(arguments)]}
    return None


def restrict_proposals(answer,payload,public_analysis):
    ctx=context(payload);observations=payload.get('observations',[])
    tools={o['tool']for o in observations};question=payload.get('question','')
    readonly=public_analysis or payload.get('evidence_required')is False or re.search(r'只读|只核对|(?:不要|不)(?:创建|生成).{0,6}(?:任务|交接)|仅分析|不执行',question)
    allowed=[]
    if not readonly:
        calculator=ctx.get('calculator')
        if calculator in('unit_economics','restock_plan')and 'commerce_'+calculator in tools:
            data=next(o['data']for o in observations if o['tool']=='commerce_'+calculator)
            if data.get('status')!='HOLD':allowed.append(calculator)
        if 'commerce_organization_brief'in tools:allowed.append('organization_handoff')
        if 'commerce_exposure_get'in tools:allowed.append('exposure_review')
        if 'commerce_intel_item_get'in tools:allowed.append('intel_review')
        if not ctx.get('calculator')and not ctx.get('entity')and all(ctx.get(key,'all')=='all'for key in('platform','store_id','market')):allowed.append('report')
    # Every proposal must cite a retained observation. An empty enum is also
    # rejected by local JSON-grammar compilers, even inside an unused branch.
    if not observations:allowed=[]
    proposal=answer['properties']['proposals'];proposal['maxItems']=min(3,len(allowed))
    if allowed:
        proposal['items']['properties']['operation']['enum']=allowed
        proposal['items']['properties']['evidence_ref']={'type':'string','enum':[o['id']for o in observations]}
        if ctx.get('calculator')in allowed and re.search(r'提出|生成|创建|建立|保存',question)and re.search(r'任务|待审阅',question):proposal['minItems']=1
    for observation in observations:
        if observation['tool']in('commerce_unit_economics','commerce_restock_plan'):
            if observation['data'].get('status')=='HOLD':
                answer['properties']['questions']['minItems']=1
                proposal['maxItems']=0
                proposal.pop('minItems',None)
            else:answer['properties']['questions']['maxItems']=0


def decode(value):
    from agent_runtime.codex_provider import decode as legacy_decode
    decision=value.get('decision')if isinstance(value,dict)else None
    if not isinstance(decision,dict)or decision.get('phase')!='inspect':return legacy_decode(value)
    calls=decision.get('calls')
    if set(value)!={'decision'}or set(decision)!={'phase','calls'}or not isinstance(calls,list)or not 1<=len(calls)<=2:raise ValueError('agent_model_invalid_response')
    if all(isinstance(call,dict)and set(call)=={'tool','arguments_json'}for call in calls):return legacy_decode(value)
    if any(not isinstance(call,dict)or set(call)!={'tool','arguments'}or not isinstance(call['tool'],str)or not isinstance(call['arguments'],dict)for call in calls):raise ValueError('agent_model_invalid_response')
    return decision
