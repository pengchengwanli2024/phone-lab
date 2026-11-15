"""Read-only preparation checks; they never authorize or submit generation."""
import hashlib
import time

from creative_direction import FORMATS,input_sha,specification
from creative_studio import MAX_ASSET

AUDIT_LIMIT=8


def _audit(studio,project,items,expected=None):
    selected=items[:AUDIT_LIMIT];valid=[];issues=[]
    for item in selected:
        try:
            folder=studio.root/project['id']
            if folder.is_symlink() or not folder.is_dir():raise ValueError('creative_asset_unavailable')
            path,meta,_=studio.asset(project['id'],item['id']);before=path.stat()
            if before.st_size!=meta['size'] or not 0<before.st_size<=MAX_ASSET:raise ValueError('creative_asset_changed')
            hasher=hashlib.sha256();total=0
            with path.open('rb') as file:
                while chunk:=file.read(1024*1024):
                    total+=len(chunk)
                    if total>MAX_ASSET:raise ValueError('creative_asset_changed')
                    hasher.update(chunk)
            after=path.stat()
            if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) or hasher.hexdigest()!=meta['sha256'] or expected and expected.get(item['id'],meta['sha256'])!=meta['sha256']:
                raise ValueError('creative_asset_changed')
            valid.append(item['id'])
        except (ValueError,OSError,KeyError,TypeError) as error:
            code=str(error) if isinstance(error,ValueError) and str(error) in ('creative_asset_unavailable','creative_asset_changed','creative_asset_not_found') else 'creative_asset_unavailable'
            issues.append({'asset_id':item['id'],'error_code':code})
    return {'asset_ids':valid,'checked_count':len(selected),'unchecked_count':max(0,len(items)-len(selected)),'issues':issues}


def evaluate(studio,project,*,binding_current=True):
    brief=project['brief'];product=brief.get('product') or {};direction=brief.get('design_direction');checks=[]
    def add(key,label,status,action,*,stage='planning',**extra):
        checks.append({'key':key,'label':label,'status':status,'stage':stage,'action':action,**extra})
    add('product_name','商品名称','ready' if product.get('name','').strip() else 'missing',{'tab':'brief','focus':'creative-name'})
    add('product_facts','卖点与资料依据','ready' if project['plan']['facts'] else 'missing',{'tab':'brief','focus':'creative-facts'},count=len(project['plan']['facts']))
    products=[a for a in reversed(project['assets']) if a['kind']=='product_image'];audit=_audit(studio,project,products)
    status='ready' if audit['asset_ids'] else 'missing' if not products else 'unchecked' if audit['unchecked_count'] else 'unavailable'
    add('product_image','产品原图',status,{'tab':'brief','focus':'creative-file','asset_kind':'product_image'},stage='plugin_inputs',**audit)
    references=[a for a in reversed(project['assets']) if a['kind'] in ('reference_image','reference_video','keyframe')]
    expected={r['asset_id']:r['sha256'] for r in (direction or {}).get('references',[])}
    if expected:
        by_id={a['id']:a for a in references};references=[by_id.get(ident,{'id':ident}) for ident in expected]
    audit=_audit(studio,project,references,expected)
    status='ready' if audit['asset_ids'] and not audit['issues'] else 'missing' if not references else 'unchecked' if audit['unchecked_count'] else 'unavailable'
    add('reference_media','参考图或参考视频',status,{'tab':'brief','focus':'creative-file','asset_kind':'reference_image'},stage='design_inputs',**audit)
    references_current=not expected or len(audit['asset_ids'])==len(expected) and not audit['issues'] and not audit['unchecked_count']
    reference_error=audit['issues'][0]['error_code'] if audit['issues'] else 'creative_reference_media_not_verified'
    current=bool(direction and direction.get('input_sha256')==input_sha(brief))
    add('design_direction','参考拆解与设计方向','ready' if current and references_current else 'stale' if direction else 'missing',{'tab':'direction','focus':'media-analysis-layout'})
    linked=bool(brief.get('product_binding'))
    add('product_source','关联商品来源','ready' if linked and binding_current else 'stale' if linked else 'not_applicable',
        {'tab':'catalog','focus':''},stage='planning' if linked else 'context')
    target=brief.get('target') or {}
    add('target_scene','人群与具体使用场景','ready' if target.get('audience','').strip() and target.get('use_scene','').strip() else 'missing',
        {'tab':'brief','focus':'creative-audience' if not target.get('audience','').strip() else 'creative-useScene'},stage='recommended')
    formats={}
    for kind in FORMATS:
        try:
            if not binding_current:raise ValueError('workspace_source_changed')
            specification(project,kind)
            if not references_current:raise ValueError(reference_error)
            formats[kind]={'can_create_request':True,'error_code':None}
        except ValueError as error:formats[kind]={'can_create_request':False,'error_code':str(error)}
    originals=next(c for c in checks if c['key']=='product_image')
    return {'schema':'commerce-creative-readiness-v1','project_id':project['id'],'project_revision':project['revision'],'checked_at':time.time(),
        'checks':checks,'formats':formats,'plugin_inputs_ready':bool(originals['asset_ids'] and all(v['can_create_request'] for v in formats.values())),
        'generation_authorized':False,'fact_verification':'operator_provided_not_independently_verified',
        'asset_verification':'bounded_registered_file_hash_check_not_product_identity_or_reference_truth_verification',
        'asset_audit_limit_per_group':AUDIT_LIMIT,'connection_and_execution_approval':'must_revalidate_separately_for_exact_plan'}
