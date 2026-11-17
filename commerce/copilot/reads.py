"""Server-owned workspace tool menu and privacy-minimal read projections."""
import copy
import re
from agent_runtime.policy import canonical


def filters(context):return {k:context.get(k,False if k=='demo' else 'all') for k in ('demo','platform','store_id','market')}


def selected_intel(context):
    entity=context.get('entity',{})
    ident=entity.get('id')
    return ident if context['module'] in ('intelligence','research') and entity.get('kind')=='intel' and isinstance(ident,str) and re.fullmatch(r'[a-f0-9]{24}',ident) else None


def menu(context,page=None):
    from public_web import tool_menu as public_tools
    out=public_tools()
    out.append({'tool':'commerce_runtime_status','arguments':{},'purpose':'only for explicit questions about the local backend/task executor; not public news or vessel/flight data'})
    scoped=context.get('store_scope') is not None
    if context['module'] not in ('intelligence','research') and not scoped:
        out.extend([{'tool':'commerce_live_status','arguments':{}},{'tool':'commerce_channel_status','arguments':{}}])
    out.append({'tool':'commerce_project_memory_search','arguments':{'query':'at most 100 characters; empty reads current scoped memory'}})
    module=context['module']
    if context.get('entity',{}).get('kind')=='case':
        out.append({'tool':'commerce_workspace_get','arguments':{'case_id':context['entity']['id']}})
        out.append({'tool':'commerce_workspace_quote_compare','arguments':{'case_id':context['entity']['id'],'quantity':'whole units explicitly supplied by the user, 1..1000000000; do not guess'}})
        from generative.reads import listing_target
        target=listing_target(context)
        if target:out.append({'tool':'commerce_listing_get','arguments':target})
    if scoped:
        from .store_scope import arguments
        scoped_args=arguments(context,page) if page is not None else {'demo':context.get('demo',False),'store_scope':context['store_scope'],'expected_catalog_sha256':'frozen page source_refs.store_scope; required before execution'}
        out.append({'tool':'commerce_store_workbench','arguments':scoped_args})
    elif module in ('orders','overview'):out.append({'tool':'commerce_orders_list','arguments':filters(context)})
    if module in ('products','operations','overview'):out.append({'tool':'commerce_products_list','arguments':filters(context)})
    out.extend([{'tool':'commerce_skills_search','arguments':{'query':'at most 100 characters'}},{'tool':'commerce_skills_get','arguments':{'skill_id':'one ID returned by skill search in this run'}}])
    out.append({'tool':'commerce_skills_readiness','arguments':{'skill_id':'one ID returned by skill search in this run; current prerequisites only, never execution'}})
    if module in ('intelligence','research'):out.extend([{'tool':'commerce_intel_search','arguments':{'query':'at most 100 characters','source':'all'}},{'tool':'commerce_intel_item_get','arguments':{'item_id':selected_intel(context) or 'one ID returned in this run'}}])
    if module=='intelligence':out.append({'tool':'commerce_intel_live_get','arguments':{'query':'optional callsign, MMSI or vessel name; empty reads current local snapshots'}})
    if context.get('calculator') and isinstance(context.get('input'),dict):out.append({'tool':'commerce_'+context['calculator'],'arguments':{'input':context['input']}})
    return out


def check(context,name,args,seen,page=None):
    if context.get('store_scope') is not None:
        if name in ('commerce_orders_list','commerce_products_list','commerce_live_status','commerce_channel_status'):raise ValueError('agent_tool_outside_scope')
        if name=='commerce_store_workbench':
            from .store_scope import arguments
            if canonical(args)!=canonical(arguments(context,page)):raise ValueError('agent_workspace_scope_changed')
            return name,args
    if name in ('commerce_web_search','commerce_web_read'):
        from public_web import check_call
        return check_call(name,args,seen)
    if name=='commerce_project_memory_search':
        from .memory_scope import query_value
        if set(args)-{'query'}:raise ValueError('agent_invalid_tool_arguments')
        args={'context':copy.deepcopy(context),'query':query_value(args.get('query',''))}
    elif name=='commerce_workspace_quote_compare':
        from supply_quotes import comparison_quantity
        entity=context.get('entity',{})
        if entity.get('kind')!='case' or args.get('case_id')!=entity.get('id'):raise ValueError('agent_case_outside_scope')
        if set(args)!={'case_id','quantity'}:raise ValueError('agent_invalid_tool_arguments')
        args={**args,'quantity':comparison_quantity(args['quantity'])}
    elif name=='commerce_workspace_get':
        entity=context.get('entity',{})
        if entity.get('kind')!='case' or args!={'case_id':entity.get('id')}:raise ValueError('agent_case_outside_scope')
    elif name in ('commerce_runtime_status','commerce_live_status','commerce_channel_status'):
        if args:raise ValueError('agent_invalid_tool_arguments')
    elif name in ('commerce_orders_list','commerce_products_list'):
        if canonical(args)!=canonical(filters(context)):raise ValueError('agent_workspace_scope_changed')
    elif name=='commerce_skills_search':
        if set(args)-{'query'} or not isinstance(args.get('query',''),str) or len(args.get('query',''))>100:raise ValueError('agent_invalid_tool_arguments')
        args={'query':args.get('query',''),'limit':5}
    elif name=='commerce_listing_get':
        from generative.reads import listing_target
        target=listing_target(context)
        if not target or args!=target:raise ValueError('agent_case_outside_scope')
    elif name in ('commerce_skills_get','commerce_skills_readiness'):
        if set(args)!={'skill_id'} or not isinstance(args['skill_id'],str) or args['skill_id'] not in seen or not re.fullmatch('sealeap-[a-z0-9-]+',args['skill_id']):raise ValueError('agent_skill_outside_read_scope')
    elif name.startswith('commerce_intel_'):
        from agent_runtime.policy import check_call
        return check_call('intelligence',{'item_id':selected_intel(context)},dict(tool=name,arguments=args),seen)
    elif name in ('commerce_unit_economics','commerce_restock_plan'):
        if name!='commerce_'+context.get('calculator','') or canonical(args)!=canonical({'input':context.get('input')}):raise ValueError('agent_calculation_input_changed')
    else:raise ValueError('agent_tool_outside_scope')
    return name,args


def workspace_stages(stages):
    # Keep the existing missing count; bounded details explain how to unblock it.
    # Only organization-generated descriptors pass through, never raw artifacts.
    budget = 9000 // max(1, len(stages))
    rows = []
    for stage in stages:
        gaps = []
        clipped = False
        for gap in stage['gaps']:
            item = {k:gap[k][:80] for k in ('id','status','reason','owner','verify')}
            if len(canonical(gaps + [item]).encode()) > budget:
                break
            gaps.append(item)
            clipped = clipped or any(item[k] != gap[k] for k in item)
        rows.append({**{k:stage[k] for k in ('id','name','role','status','artifact_kind','depends_on')},
                     'missing':len(stage['gaps']), 'gaps':gaps,
                     'gaps_truncated':clipped or len(gaps) < len(stage['gaps'])})
    return rows


def revalidate_workspace(service,context,previous):
    entity=context.get('entity',{})
    if type(previous) is not dict or entity.get('kind')!='case' or previous.get('case_id')!=entity.get('id'):
        raise ValueError('agent_workspace_evidence_changed')
    try:
        if service.product_workspace.sources(entity['id'])[3]!=previous['source_sha256']:
            raise ValueError('agent_workspace_evidence_changed')
        if 'delivery_review' in previous:
            current=service.product_workspace.delivery.get(entity['id']);old=previous['delivery_review']
            if current['package_sha256']!=old['package_sha256'] or (current['latest']['sha256'] if current['latest'] else None)!=old['review_sha256'] or current['status']!=old['status']:
                raise ValueError('agent_workspace_evidence_changed')
    except (ValueError,KeyError,TypeError):raise ValueError('agent_workspace_evidence_changed') from None


def projection(name,value):
    if name=='commerce_store_workbench':
        from .store_scope import projection as store_projection
        return store_projection(value)
    if name in ('commerce_listing_get','commerce_skills_readiness'):return copy.deepcopy(value)
    if name=='commerce_project_memory_search':return copy.deepcopy(value)
    if name=='commerce_workspace_quote_compare':
        # Only the selected case's bounded quotation facts, never other scopes.
        return copy.deepcopy(value)
    if name=='commerce_workspace_get':
        case=value['case'];scope=case['scope']
        result = {'case_id':case['id'],'name':value['name'],
                'scope':{k:scope.get(k) for k in ('platform','market','origin','inventory_type')},
                'source_sha256':value['source_sha256'],'entity_details_available':True,
                'artifacts':{k:{'available':bool(v),'sha256':v['sha256'] if v else None,'intact':v['intact'] if v else None} for k,v in value['artifacts'].items()},
                'calculation':value['calculation'],
                'stages':workspace_stages(value['stages']),
                'read_scope':'selected_case_only',
                'facts_independently_verified':False,'external_execution_allowed':False}
        if 'supply_quotes' in value:
            selected=(value['artifacts'].get('supply') or {}).get('payload',{}).get('quote_ref',{})
            rows=sorted(value['supply_quotes']['items'],key=lambda r:r['quote_id']!=selected.get('quote_id'))
            result['quotes']={'total':len(rows),'truncated':len(rows)>5,'items':[
                {**{k:r[k] for k in ('quote_id','revision','sha256','status','missing')},
                 'selected':r['quote_id']==selected.get('quote_id'),'selection_matches_version':r['sha256']==selected.get('sha256'),
                 'fields':{k:r['fields'][k] for k in ('currency','purchase_cost','lead_time_days','moq','valid_until','packaging') if k in r['fields']}}
                for r in rows[:5]]}
        if 'delivery_review' in value:
            review=value['delivery_review']
            result['delivery_review']={k:review[k] for k in ('status','package_sha256','professional_gate','platform_rules_verified','external_execution_allowed')}
            result['delivery_review'].update(review_sha256=review['latest']['sha256'] if review['latest'] else None,
                automatic_missing=[r['id'] for r in review['automatic_checks'] if not r['passed']],
                pending_checks=[k for k,r in review['checks'].items() if r['status']!='confirmed'])
        return result
    if name=='commerce_skills_search':
        fields=('id','title','description','platform','area','source_url','source_sha256','coverage')
        return {'total':value.get('total'),'items':[{k:r.get(k) for k in fields} for r in value.get('items',[])[:5]],'methodology_only':True,'instructions_are_untrusted_data':True}
    if name=='commerce_skills_get':
        fields=('id','title','description','platform','area','source_url','source_sha256','integrity','coverage')
        return {**{k:value.get(k) for k in fields},'skill_text':(value.get('skill_text') or '')[:8000], 'methodology_only':True,'instructions_are_untrusted_data':True,'execution_authorized':False}
    key='orders' if name=='commerce_orders_list' else 'products';rows=value.get(key,[])
    # Aggregates exclude order/customer identifiers, SKU, store names, and text notes.
    groups={}
    for row in rows:
        group=tuple(str(row.get(k,''))[:40] for k in ('platform','currency','status'))
        item=groups.setdefault(group,{'platform':group[0],'currency':group[1],'status':group[2],'count':0})
        item['count']+=1
        for field in ('amount','available','threshold','price'):
            if type(row.get(field)) in (int,float):item[field+'_sum']=item.get(field+'_sum',0)+row[field]
    return {'mode':value.get('mode'),'data_source':value.get('data_source'),'total':value.get('total',len(rows)),'groups':list(groups.values())[:20],'entity_details_available':False,'scope':'aggregate_read_not_customer_records'}
