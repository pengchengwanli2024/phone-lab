"""Minimal listing facts; images remain explicit version-checked host reads."""
import copy

def listing_target(context):
    entity=context.get('entity',{})
    if entity.get('kind')!='case' or any(context.get(k,'all') in ('','all',None) for k in ('platform','store_id','market')):return None
    return {'case_id':entity['id'],'platform':context['platform'],'store_ref':context['store_id'],'market':context['market']}

def listing(service,args):
    value=service.listings.get(**args)
    owner=service.owner_reviews.state(value['target'])
    fields=value['payload']['fields']
    data={k:copy.deepcopy(value[k]) for k in ('target','revision','source_sha256','preview_sha256','stale','checks','missing','delivery_status')}
    # No image URLs, raw customer facts, signer identity or hidden platform state
    # enter the model prompt. Actual media uses the existing guarded image API.
    data['product']={k:copy.deepcopy(fields[k]) for k in ('sku','title','description','category_id','price','currency','quantity')}
    data['product']['description_truncated']=len(data['product']['description'])>4000
    data['product']['description']=data['product']['description'][:4000]
    data['product'].update(language=value['payload']['language'],image_count=len(fields['image_refs']))
    data['product']['attributes']=copy.deepcopy(value['payload']['attributes'][:12])
    data['product']['publication']=copy.deepcopy(value['payload'].get('ozon',{}).get('publication'))
    data['image_binding']=({'target':value['target'],'expected_binding_sha256':owner['binding_sha256'],
        'count':len(fields['image_refs'])} if value['revision']>0 and not value['stale'] and owner['supported'] and owner['product']==value['payload'] else None)
    data['external_execution_allowed']=False;data['rules_independently_verified']=False
    return data

def revalidate(service,observation):
    data=observation['data'];name=observation['tool']
    if name=='commerce_listing_get':
        current=listing(service,data['target'])
        if current['preview_sha256']!=data['preview_sha256'] or current['image_binding']!=data['image_binding']:
            raise ValueError('agent_workspace_evidence_changed')
    elif name=='commerce_skills_readiness':
        current=service.skills.readiness(data['skill_id'])
        if current!=data:raise ValueError('agent_workspace_evidence_changed')
