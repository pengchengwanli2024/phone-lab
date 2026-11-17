"""Opt-in local delivery commitments and hash-bound sample approval.

Uses the existing immutable request/review ledger. Approval unlocks only the
paired local render; it never approves the full output or external execution.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import time
import uuid

import creative_tools
from creative_preflight import captions, inspect
from research import canonical, digest


def renderer_sha256():
    root=Path(__file__).resolve().parent
    names=('creative_story_render.py','creative_render.py','creative_preflight.py','creative_delivery.py')
    hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest()for name in names}
    for name in ('ffmpeg','ffprobe','rsvg-convert'):
        h=hashlib.sha256()
        with open(creative_tools.command(name),'rb')as file:
            while block:=file.read(1024*1024):h.update(block)
        hashes[name]=h.hexdigest()
    return digest(canonical(hashes))


def validate_requirements(value,duration):
    if (type(value)is not dict or set(value)!={'source_policy','audio_policy','allow_looping','sample_duration_ms'}
            or value['source_policy']not in ('allow_stills','video_only')
            or value['audio_policy']not in ('optional','audible_required','no_audio')
            or type(value['allow_looping'])is not bool or type(value['sample_duration_ms'])is not int
            or not 1000<=value['sample_duration_ms']<=min(5000,duration)):
        raise ValueError('creative_delivery_requirements_invalid')
    return copy.deepcopy(value)


def validate_frozen(d):
    c=d['spec']['delivery_commitment']
    if (digest(canonical({k:d[k]for k in ('project_id','revision','spec')}))!=d['request_sha256']
            or digest(canonical({k:v for k,v in c.items()if k!='sha256'}))!=c['sha256']
            or d['id']!=c[d['spec']['delivery_role']+'_request_id']):
        raise ValueError('creative_request_changed')
    return c


def preflight_check(spec,report):
    c=spec.get('delivery_commitment')
    if not c:return report
    r=c['requirements'];errors=report['errors'];summary=report['summary']
    def fail(code):errors.append({'code':code})
    if r['source_policy']=='video_only' and summary['still_duration_ms']:fail('creative_delivery_video_required')
    if not r['allow_looping']and summary['looped_shot_indexes']:fail('creative_delivery_looping_forbidden')
    if r['audio_policy']=='audible_required'and (not summary['output_has_audio']or any(x['code']=='silent_output_audio'for x in report['warnings'])):fail('creative_delivery_audio_required')
    if r['audio_policy']=='no_audio'and summary['output_has_audio']:fail('creative_delivery_audio_forbidden')
    expected={aid:c['source_assets'][aid]for aid in report['source_assets']if aid in c['source_assets']}
    if expected!=report['source_assets']:fail('creative_asset_changed')
    report['can_render']=not errors
    return report


def prepare(workflow,request_id,expected_request_sha256,asset_ids,requirements,idempotency_key,audio_asset_id=None):
    if not isinstance(idempotency_key,str)or not 1<=len(idempotency_key)<=160:raise ValueError('invalid_idempotency_key')
    with workflow.core.atomic()as db:
        parent=workflow.request_get(request_id);p=workflow._current(parent)
        if parent['spec'].get('delivery_commitment'):raise ValueError('creative_delivery_immutable')
        if not parent['spec']['format'].endswith('_video'):raise ValueError('creative_edit_video_required')
        if parent['request_sha256']!=expected_request_sha256 or digest(canonical({k:parent[k]for k in ('project_id','revision','spec')}))!=expected_request_sha256:raise ValueError('creative_request_changed')
        r=validate_requirements(requirements,parent['spec']['duration_ms'])
        signature=digest(canonical([request_id,expected_request_sha256,asset_ids,audio_asset_id,r]))
        key=digest(canonical([p['id'],'delivery:'+idempotency_key]))
        old=db.execute('SELECT document FROM creative_requests WHERE idem=?',(key,)).fetchone()
        if old:
            full=json.loads(old[0])
            if full.get('delivery_input_sha256')!=signature:raise ValueError('idempotency_conflict')
            return {'full':workflow.request_get(full['id']),'sample':workflow.request_get(full['spec']['delivery_commitment']['sample_request_id'])}
        if db.execute('SELECT count(*)FROM creative_requests WHERE project=?',(p['id'],)).fetchone()[0]>98:raise ValueError('creative_request_limit')
        report=inspect(workflow.studio,p['id'],parent['spec'],asset_ids,audio_asset_id)
        base=copy.deepcopy(parent['spec'])
        if not base.get('editing'):base['delivery_captions']=[t or p['brief']['product']['name']for t in captions(base)]
        full_id=uuid.uuid4().hex;sample_id=uuid.uuid4().hex
        c={'schema':'commerce-local-delivery-v1','renderer':'local_storyboard_edit','renderer_sha256':renderer_sha256(),
           'source_request_id':request_id,'full_request_id':full_id,'sample_request_id':sample_id,
           'full_spec_sha256':digest(canonical(base)),'duration_ms':base['duration_ms'],'width':base['width'],'height':base['height'],
           'container':'mp4','asset_ids':list(asset_ids),'audio_asset_id':audio_asset_id,'source_assets':report['source_assets'],'requirements':r}
        c['sha256']=digest(canonical(c))
        preflight_check({'delivery_commitment':c},report)
        if not report['can_render']:raise ValueError(report['errors'][0]['code'])
        sample=copy.deepcopy(base);sample['duration_ms']=r['sample_duration_ms'];sample['shots']=[];remaining=r['sample_duration_ms']
        for shot in base['shots']:
            row=copy.deepcopy(shot);row['end_ms']=row['start_ms']+min(remaining,shot['end_ms']-shot['start_ms']);sample['shots'].append(row)
            remaining-=row['end_ms']-row['start_ms']
            if not remaining:break
        count=len(sample['shots'])
        if sample.get('editing'):
            sample['editing']['shots']=sample['editing']['shots'][:count]
            sample['editing']['shots'][-1]['duration_ms']=sample['shots'][-1]['end_ms']-sample['shots'][-1]['start_ms']
        else:sample['delivery_captions']=sample['delivery_captions'][:count]
        # Check the actual sample as well: e.g. source audio may only occur later.
        sample_report=preflight_check({'delivery_commitment':c},inspect(workflow.studio,p['id'],sample,asset_ids[:count],audio_asset_id))
        if not sample_report['can_render']:raise ValueError(sample_report['errors'][0]['code'])
        for role,spec,rid in [('full',base,full_id),('sample',sample,sample_id)]:
            spec.update(delivery_commitment=c,delivery_role=role)
            frozen={'project_id':p['id'],'revision':p['revision'],'spec':spec}
            doc={'id':rid,**frozen,'request_sha256':digest(canonical(frozen)),'input_sha256':parent['input_sha256'],
                 'direction_sha256':parent['direction_sha256'],'status':'awaiting_media','created_at':time.time(),
                 'external_generation_submitted':False,'job_id':None,'assets':[],'result_sha256':None,'review':None,
                 'parent_request_id':request_id,'delivery_input_sha256':signature}
            db.execute('INSERT INTO creative_requests VALUES(?,?,?,?)',(rid,p['id'],key if role=='full'else digest(canonical([key,'sample'])),canonical(doc)))
        return {'full':workflow.request_get(full_id),'sample':workflow.request_get(sample_id)}


def _approved_sample(full,sample):
    c=full['spec']['delivery_commitment'];review=sample.get('review')or{};ack=review.get('sample_review')or{}
    return (sample['id']==c['sample_request_id']and sample['spec'].get('delivery_role')=='sample'
            and sample['spec'].get('delivery_commitment')==c and not sample.get('stale')
            and review.get('decision')=='approved' and ack=={'watched':True,'matches_commitment':True,'commitment_sha256':c['sha256']}
            and review.get('request_sha256')==sample['request_sha256']and review.get('result_sha256')==sample['result_sha256']
            and (sample.get('quality_report')or{}).get('delivery_commitment_check',{}).get('status')=='passed')


def projection(workflow,d):
    c=d['spec'].get('delivery_commitment')
    if not c:return None
    sample_role=d['spec']['delivery_role']=='sample';gate='sample_review'if sample_role else'sample_required'
    if not sample_role:
        sample=workflow.request_get(c['sample_request_id'])
        if _approved_sample(d,sample):gate='ready'
        elif (sample.get('review')or{}).get('decision')=='rejected':gate='sample_rejected'
    return {'role':d['spec']['delivery_role'],'commitment_sha256':c['sha256'],'gate':gate,
            'asset_ids':c['asset_ids'][:len(d['spec']['shots'])],'audio_asset_id':c['audio_asset_id'],
            'sample_request_id':c['sample_request_id'],'full_request_id':c['full_request_id'],'source_request_id':c['source_request_id']}


def before_execute(workflow,d,asset_ids,audio_asset_id,*,approval=True):
    if not d['spec'].get('delivery_commitment'):return
    c=validate_frozen(d)
    if asset_ids!=c['asset_ids'][:len(d['spec']['shots'])]or audio_asset_id!=c['audio_asset_id']:raise ValueError('creative_delivery_selection_changed')
    if renderer_sha256()!=c['renderer_sha256']:raise ValueError('creative_delivery_renderer_changed')
    if approval and d['spec']['delivery_role']=='full':
        sample=workflow.request_get(c['sample_request_id']);validate_frozen(sample)
        if not _approved_sample(d,sample):raise ValueError('creative_sample_approval_required')
        workflow._current(sample);workflow._assets(sample,[a['id']for a in sample['assets']])


def output_check(spec,media,observations):
    c=spec['delivery_commitment'];policy=c['requirements']['audio_policy']
    audio=observations.get('audio')or{};peak=audio.get('peak_dbfs')
    audible=(observations.get('status')=='completed'and audio.get('status')=='analyzed'
             and type(peak)in (int,float)and math.isfinite(peak)and peak>-50)
    checks={'duration':abs(media['duration_seconds']-spec['duration_ms']/1000)<=.2,
            'dimensions':(media['width'],media['height'])==(spec['width'],spec['height']),
            'container':'mp4'in media['format'].split(','),
            'audio_policy':policy=='optional'or policy=='no_audio'and not media['has_audio']or policy=='audible_required'and media['has_audio']and audible}
    return {'schema':'commerce-delivery-check-v1','commitment_sha256':c['sha256'],'role':spec['delivery_role'],
            'checks':checks,'status':'passed'if all(checks.values())else'failed','human_review_required':True}


def review_guard(workflow,d,decision,sample_review):
    c=d['spec'].get('delivery_commitment')
    if not c:
        if sample_review is not None:raise ValueError('creative_sample_review_invalid')
        return {}
    if decision!='approved':return {}
    before_execute(workflow,d,c['asset_ids'][:len(d['spec']['shots'])],c['audio_asset_id'])
    quality=d.get('quality_report')or{};check=quality.get('delivery_commitment_check')or{}
    if quality.get('technical_status')!='passed'or check.get('status')!='passed'or check.get('commitment_sha256')!=c['sha256']:raise ValueError('creative_delivery_requirements_unmet')
    if d['spec']['delivery_role']=='sample':
        expected={'watched':True,'matches_commitment':True,'commitment_sha256':c['sha256']}
        if sample_review!=expected:raise ValueError('creative_sample_review_required')
        return {'sample_review':copy.deepcopy(sample_review),'request_sha256':d['request_sha256'],'result_sha256':d['result_sha256']}
    if sample_review is not None:raise ValueError('creative_sample_review_invalid')
    return {'request_sha256':d['request_sha256'],'result_sha256':d['result_sha256']}


def worker_guard(studio,data):
    spec=data['production_spec'];c=spec.get('delivery_commitment')
    if not c:return None
    if renderer_sha256()!=c['renderer_sha256']:raise ValueError('creative_delivery_renderer_changed')
    with studio.core.db()as db:
        row=db.execute('SELECT document FROM creative_requests WHERE id=?',(data['request_id'],)).fetchone()
        d=json.loads(row[0])if row else None
        if not d or d['spec']!=spec:raise ValueError('creative_request_changed')
        validate_frozen(d)
        if spec['delivery_role']=='sample':return None
        sample=json.loads(db.execute('SELECT document FROM creative_requests WHERE id=?',(c['sample_request_id'],)).fetchone()[0])
    validate_frozen(sample)
    # Approved reviews persist the exact job-derived assets/report in the ledger.
    if not _approved_sample(d,sample):raise ValueError('creative_sample_approval_required')
    for asset in sample['assets']:
        path,meta,_=studio.asset(d['project_id'],asset['id'])
        if asset['sha256']!=meta['sha256']or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha256']:raise ValueError('creative_asset_changed')
    return {'request_id':sample['id'],'request_sha256':sample['request_sha256'],'result_sha256':sample['result_sha256'],'review':sample['review']}
