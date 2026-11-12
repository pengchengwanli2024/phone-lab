"""Scope and projection for model-visible shared tools. No model-owned grants."""
import copy
import json

TOPICS = ('runtime', 'intelligence', 'calculation', 'organization_case', 'business_exposure', 'workspace')
ITEM_FIELDS = ('id','source','source_key','title','url','published','category','country','country_code','location','publisher_alert','collected_at','record_sha256','source_payload_sha256','verification')


def source_ids():
    from intelligence import SOURCES
    return ('all',*SOURCES)


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def tool_menu(topic, parameters):
    if topic == 'workspace':
        from copilot.reads import menu
        return menu(parameters['context'])
    if topic == 'runtime':
        return [{'tool':'commerce_runtime_status','arguments':{}}, {'tool':'commerce_live_status','arguments':{}}, {'tool':'commerce_channel_status','arguments':{}}]
    if topic == 'intelligence':
        return [{'tool':'commerce_intel_search','arguments':{'query':'at most 100 characters','source':list(source_ids())}},
                {'tool':'commerce_intel_item_get','arguments':{'item_id':'ID returned in this request, or explicitly supplied by user'}}]
    if topic == 'organization_case':
        return [{'tool':'commerce_organization_board','arguments':{'case_id':parameters['case_id']}},
                {'tool':'commerce_organization_brief','arguments':{'case_id':parameters['case_id'],
                 'stage_id':parameters.get('stage_id') or 'one ID from the returned board stages'}}]
    if topic == 'business_exposure':
        return [{'tool':'commerce_exposure_get','arguments':{'assessment_id':parameters['assessment_id']}}]
    calculator=parameters.get('calculator')
    return [{'tool':'commerce_'+calculator,'arguments':{'input':parameters['input']}}] if calculator in ('unit_economics','restock_plan') and isinstance(parameters.get('input'),dict) else []


def check_call(topic, parameters, call, seen):
    if not isinstance(call,dict) or set(call)!={'tool','arguments'} or not isinstance(call['arguments'],dict):
        raise ValueError('agent_invalid_tool_call')
    name,args=call['tool'],copy.deepcopy(call['arguments'])
    allowed={t['tool'] for t in tool_menu(topic,parameters)}
    if name not in allowed:raise ValueError('agent_tool_outside_scope')
    if topic=='workspace':
        from copilot.reads import check
        return check(parameters['context'],name,args,seen)
    if name=='commerce_exposure_get':
        if args!={'assessment_id':parameters['assessment_id']}:raise ValueError('agent_exposure_outside_scope')
    elif name in ('commerce_runtime_status','commerce_live_status','commerce_channel_status'):
        if args:raise ValueError('agent_invalid_tool_arguments')
    elif name=='commerce_intel_search':
        if set(args)-{'query','source','country','hours','category'}:raise ValueError('agent_invalid_tool_arguments')
        if any(not isinstance(v,str) for v in args.values()):raise ValueError('agent_invalid_tool_arguments')
        if len(args.get('query',''))>100 or len(args.get('country',''))>80 or args.get('source','all') not in source_ids():raise ValueError('agent_invalid_tool_arguments')
        args.update(limit='20',include_map=False,scope='latest',view='all')
    elif name=='commerce_intel_item_get':
        if set(args)!={'item_id'} or args['item_id'] not in seen | {parameters.get('item_id')}:
            raise ValueError('agent_item_outside_read_scope')
    elif name in ('commerce_organization_board','commerce_organization_brief'):
        required={'case_id'} if name.endswith('_board') else {'case_id','stage_id'}
        if set(args)!=required or args['case_id']!=parameters['case_id']:raise ValueError('agent_case_outside_scope')
        if name.endswith('_brief'):
            if not isinstance(args['stage_id'],str) or (parameters.get('stage_id') and args['stage_id']!=parameters['stage_id']):
                raise ValueError('agent_case_stage_outside_scope')
    else:
        if canonical(args)!=canonical({'input':parameters.get('input')}):raise ValueError('agent_calculation_input_changed')
    return name,args


def project(name, value):
    """No keys, local paths, store labels, transaction identifiers or full notes."""
    if name=='commerce_channel_status':
        fields=('id','adapter_available','credentials_present','gateway_enabled','runtime_status','readiness','delivery_verified')
        return {'probe_status':value['probe_status'],'profile_available':value['profile_available'],
                'shared_core_configured':value['shared_core_configured'],
                'channels':[{**{key:row[key] for key in fields},'selected':row['binding']['selected'],
                             'mode':row['binding']['mode']} for row in value['channels']],
                'configuration_is_not_authorization':True,'external_execution_allowed':False}
    if name in ('commerce_workspace_get','commerce_orders_list','commerce_products_list','commerce_skills_search','commerce_skills_get'):
        from copilot.reads import projection
        return projection(name,value)
    if name=='commerce_live_status':
        return {'configured':value['configured'],'orders_scope_confirmed':value['orders_scope_confirmed'],
                'orders':{k:value['orders'].get(k) for k in ('available','fresh','count','observed_at')},
                'stock':{k:value['stock'].get(k) for k in ('available','fresh','count','observed_at')},
                'notifications_enabled':value['notifications_enabled']}
    if name in ('commerce_organization_board','commerce_organization_brief'):
        from .cases import project_case_read
        return project_case_read(name,value)
    if name=='commerce_exposure_get':
        from exposure import Exposure
        return Exposure.projection(value)
    if name=='commerce_runtime_status':
        return {k:value.get(k) for k in ('worker','public_collection','requested_local_work','availability','marketplace_writes','model_executor','model_executor_scope','conversational_model_readiness')}
    if name=='commerce_intel_search':
        return {'total':value['total'],'shown_to_model':min(5,len(value['items'])),
                'items':[{k:r.get(k) for k in ITEM_FIELDS} for r in value['items'][:5]],
                'scope':'latest_collected_metadata_not_whole_web','independently_verified':False}
    if name=='commerce_intel_item_get':
        return {k:value.get(k) for k in ITEM_FIELDS}
    return copy.deepcopy(value)
