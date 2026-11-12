"""Server-owned workspace tool menu and privacy-minimal read projections."""
import re
from agent_runtime.policy import canonical


def filters(context):return {k:context.get(k,False if k=='demo' else 'all') for k in ('demo','platform','store_id','market')}


def menu(context):
    out=[{'tool':'commerce_runtime_status','arguments':{}},{'tool':'commerce_live_status','arguments':{}},{'tool':'commerce_channel_status','arguments':{}}]
    module=context['module']
    if context.get('entity',{}).get('kind')=='case':
        out.append({'tool':'commerce_workspace_get','arguments':{'case_id':context['entity']['id']}})
    if module in ('orders','overview'):out.append({'tool':'commerce_orders_list','arguments':filters(context)})
    if module in ('products','operations','overview'):out.append({'tool':'commerce_products_list','arguments':filters(context)})
    out.extend([{'tool':'commerce_skills_search','arguments':{'query':'at most 100 characters'}},{'tool':'commerce_skills_get','arguments':{'skill_id':'one ID returned by skill search in this run'}}])
    if module in ('intelligence','research'):out.extend([{'tool':'commerce_intel_search','arguments':{'query':'at most 100 characters','source':'all'}},{'tool':'commerce_intel_item_get','arguments':{'item_id':'one ID returned in this run'}}])
    if context.get('calculator') and isinstance(context.get('input'),dict):out.append({'tool':'commerce_'+context['calculator'],'arguments':{'input':context['input']}})
    return out


def check(context,name,args,seen):
    if name=='commerce_workspace_get':
        entity=context.get('entity',{})
        if entity.get('kind')!='case' or args!={'case_id':entity.get('id')}:raise ValueError('agent_case_outside_scope')
    elif name in ('commerce_runtime_status','commerce_live_status','commerce_channel_status'):
        if args:raise ValueError('agent_invalid_tool_arguments')
    elif name in ('commerce_orders_list','commerce_products_list'):
        if canonical(args)!=canonical(filters(context)):raise ValueError('agent_workspace_scope_changed')
    elif name=='commerce_skills_search':
        if set(args)-{'query'} or not isinstance(args.get('query',''),str) or len(args.get('query',''))>100:raise ValueError('agent_invalid_tool_arguments')
        args={'query':args.get('query',''),'limit':5}
    elif name=='commerce_skills_get':
        if set(args)!={'skill_id'} or not isinstance(args['skill_id'],str) or args['skill_id'] not in seen or not re.fullmatch('sealeap-[a-z0-9-]+',args['skill_id']):raise ValueError('agent_skill_outside_read_scope')
    elif name.startswith('commerce_intel_'):
        from agent_runtime.policy import check_call
        return check_call('intelligence',{},dict(tool=name,arguments=args),seen)
    elif name in ('commerce_unit_economics','commerce_restock_plan'):
        if name!='commerce_'+context.get('calculator','') or canonical(args)!=canonical({'input':context.get('input')}):raise ValueError('agent_calculation_input_changed')
    else:raise ValueError('agent_tool_outside_scope')
    return name,args


def projection(name,value):
    if name=='commerce_workspace_get':
        case=value['case'];scope=case['scope']
        return {'case_id':case['id'],'name':value['name'],
                'scope':{k:scope.get(k) for k in ('platform','market','origin','inventory_type')},
                'source_sha256':value['source_sha256'],'entity_details_available':True,
                'artifacts':{k:{'available':bool(v),'sha256':v['sha256'] if v else None,'intact':v['intact'] if v else None} for k,v in value['artifacts'].items()},
                'calculation':value['calculation'],
                'stages':[{'id':s['id'],'status':s['status'],'missing':len(s['gaps'])} for s in value['stages']],
                'facts_independently_verified':False,'external_execution_allowed':False}
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
