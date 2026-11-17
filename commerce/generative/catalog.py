"""Models select presentation by reference; all facts/actions stay host-owned."""
from pathlib import Path
import copy
import hashlib
import json
import re

CATALOG=json.loads(Path(__file__).with_name('catalog.json').read_text())
COMPONENTS=CATALOG['components']
COST_FIELDS=json.loads(Path(__file__).resolve().parents[1].joinpath('a2ui/contract.json').read_text())['fields']

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def menu(observations):
    candidates=[]
    for component,spec in COMPONENTS.items():
        if 'slot' in spec:candidates.append({'component':component,'reference':spec['slot']});continue
        for obs in observations:
            if supports(component,obs):candidates.append({'component':component,'reference':obs['id']})
    return {'schema':CATALOG['schema'],'choices':candidates,'max_components':12,
        'instructions':'Optionally choose and order ui entries from these exact pairs. Never add data, HTML, actions, URLs or inferred facts. Omit irrelevant or empty slots. Reference snapshots are unverified; presentation does not authorize execution.'}

def supports(component,obs):
    spec=COMPONENTS[component];data=obs.get('data',{})
    if 'slot' in spec:return False
    if '*' not in spec['tools'] and obs.get('tool') not in spec['tools']:return False
    if component=='DeliveryReview':return isinstance(data.get('delivery_review'),dict)
    if component=='QuoteComparison':return obs.get('tool')=='commerce_workspace_quote_compare' or isinstance(data.get('quotes'),dict)
    if component=='CostSummary':return obs.get('tool')=='commerce_unit_economics' or isinstance(data.get('calculation'),dict)
    if component=='FieldDiff':return bool(data.get('ui_input') or data.get('ui_errors'))
    return True

def select(entries,observations):
    if not isinstance(entries,list) or len(entries)>12:raise ValueError('agent_ui_invalid_layout')
    known={o['id']:o for o in observations};seen=set();result=[]
    for item in entries:
        if type(item)is not dict or set(item)!={'component','reference'}:raise ValueError('agent_ui_invalid_layout')
        kind,ref=item['component'],item['reference']
        if not isinstance(kind,str) or kind not in COMPONENTS or not isinstance(ref,str):raise ValueError('agent_ui_invalid_component')
        spec=COMPONENTS[kind];key=(kind,ref)
        if key in seen:raise ValueError('agent_ui_duplicate_component')
        seen.add(key)
        if 'slot' in spec:
            if ref!=spec['slot']:raise ValueError('agent_ui_reference_mismatch')
        elif ref not in known or not supports(kind,known[ref]):raise ValueError('agent_ui_reference_mismatch')
        result.append(dict(item))
    return result

def fallback(result):
    out=[]
    for obs in result.get('observations',[]):
        preferred=next((k for k in ('ListingReview','QuoteComparison','DeliveryReview','SkillReadiness','CostSummary','FieldDiff') if supports(k,obs)), 'Evidence')
        out.append({'component':preferred,'reference':obs['id']})
        if preferred=='QuoteComparison' and supports('DeliveryReview',obs):out.append({'component':'DeliveryReview','reference':obs['id']})
    return out[:12]

def present(run):
    result=run.get('result')or {};observations=result.get('observations')or []
    requested=result.get('ui');status=result.get('ui_status','legacy_fallback')
    try:entries=select(requested,observations) if requested is not None else fallback(result)
    except ValueError:entries=fallback(result);status='fallback'
    components=[];known={o['id']:o for o in observations}
    for item in entries:
        kind,ref=item['component'],item['reference'];spec=COMPONENTS[kind];obs=known.get(ref)
        if ref=='questions':data={'items':result.get('questions',[])}
        elif ref=='proposals':data={'items':result.get('proposals',[]),'actions':run.get('actions',[])}
        elif ref=='receipt':data={'items':run.get('actions',[])}
        else:data=copy.deepcopy(obs['data'])
        if kind=='CostSummary':data['cost_field_labels']={field['key']:field['label']for field in COST_FIELDS}
        binding={'run_id':run['id'],'reference':ref,'observation_sha256':obs.get('sha256') if obs else None,
                 'result_sha256':run.get('result_sha256'),'source_sha256':data.get('source_sha256')}
        ident=spec['field_prefix']+'-'+digest({'run':run['id'],'kind':kind,'reference':ref})[:16]
        components.append({'id':ident,'component':kind,'label':spec['label'],'binding':binding,'data':data,
                           'observation':copy.deepcopy(obs) if kind=='Evidence' else None})
        if kind=='Evidence':components[-1]['data']={}
    value={'schema':'commerce-generative-surface-v1','catalog_version':1,'run_id':run['id'],
           'layout_status':status,'components':components,'external_execution_allowed':False,
           'provisional':False,'source_policy':'frozen_observations_not_independent_verification'}
    value['sha256']=digest(value)
    return value

def selection_schema():
    return {'type':'array','items':{'type':'object','properties':{
        'component':{'type':'string','enum':list(COMPONENTS)},'reference':{'type':'string'}},
        'required':['component','reference'],'additionalProperties':False}}
