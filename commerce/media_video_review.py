"""Immutable operator-reviewed video content; no uploads or generation calls."""
from copy import deepcopy
import time
import uuid

from research import canonical,digest

BLOCKER='person_script_storyboard_approval_required'


def definitions(schema,string):
    text={'type':'string','maxLength':3000}
    content=schema({'presenter_mode':{'type':'string','enum':['faceless','fictional_adult']},
        'presenter_description':{'type':'string','maxLength':800},'use_scene':{'type':'string','minLength':1,'maxLength':1200},
        'speech_mode':{'type':'string','enum':['voiceover','none']},'script_text':text,
        'shots':{'type':'array','minItems':1,'maxItems':31,'items':schema({'index':{'type':'integer','minimum':0,'maximum':30},
            'framing':{'type':'string','minLength':1,'maxLength':400},'action':{'type':'string','minLength':1,'maxLength':1200}},['index','framing','action'])},
        'claims_confirmed':{'type':'boolean'}},['presenter_mode','presenter_description','use_scene','speech_mode','script_text','shots','claims_confirmed'])
    return [('commerce_media_plugin_plan_review_video','按原方案哈希确认视频人物、场景、台词和分镜，保存新方案；不替代登录、付费执行批准或商品事实核验',
             schema({'plan_id':string,'expected_plan_sha256':string,'content':content,'idempotency_key':string},['plan_id','expected_plan_sha256','content','idempotency_key']))]


def _text(value,maximum,empty=False):
    if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 and c not in '\n\r\t' for c in value) or (not empty and not value.strip()):
        raise ValueError('media_video_review_invalid_text')
    return value.strip()


def validate(content,plan):
    required={'presenter_mode','presenter_description','use_scene','speech_mode','script_text','shots','claims_confirmed'}
    if not isinstance(content,dict) or set(content)!=required:raise ValueError('media_video_review_fields_required')
    if content['claims_confirmed'] is not True:raise ValueError('media_video_review_claims_confirmation_required')
    mode=content['presenter_mode'];speech=content['speech_mode']
    if mode not in ('faceless','fictional_adult') or speech not in ('voiceover','none'):raise ValueError('media_video_review_invalid_mode')
    person=_text(content['presenter_description'],800,empty=mode=='faceless')
    if mode=='faceless' and person:raise ValueError('media_video_review_faceless_person_conflict')
    script=_text(content['script_text'],3000,empty=speech=='none')
    if speech=='none' and script:raise ValueError('media_video_review_silent_script_conflict')
    scene=_text(content['use_scene'],1200)
    spec=plan['source_request']['spec'];scope=[plan['shot_index']] if plan['shot_index'] is not None else list(range(len(spec['shots'])))
    shots=content['shots']
    if not isinstance(shots,list) or len(shots)!=len(scope):raise ValueError('media_video_review_shot_scope_required')
    result=[]
    for item,index in zip(shots,scope):
        if not isinstance(item,dict) or set(item)!={'index','framing','action'} or type(item.get('index')) is not int or item['index']!=index:
            raise ValueError('media_video_review_shot_scope_required')
        original=spec['shots'][index]
        result.append({'index':index,'start_ms':original['start_ms'],'end_ms':original['end_ms'],'role':original['role'],
            'fact_ids':list(original['fact_ids']),'framing':_text(item['framing'],400),'action':_text(item['action'],1200)})
    return {'presenter_mode':mode,'presenter_description':person,'use_scene':scene,'speech_mode':speech,'script_text':script,
            'shots':result,'claims_confirmed':True}


def _prompt(plan,content):
    # Replace the original generated narration and fixed camera directions, so
    # the new prompt cannot ask for both the draft and the reviewed dialogue.
    spec=plan['source_request']['spec'];old=spec['script']
    source=spec['prompt'].replace('制作文案：'+old['hook']+' '+old['body']+' '+old['cta'],'')
    lines=[line for line in source.splitlines() if not line.startswith(('制作文案：','镜头：'))]
    if content['presenter_mode']=='faceless':
        lines=['目标：按产品真实用途展示商品全貌、场景与细节，不出现人物。' if line.startswith('目标：') else line for line in lines]
    person='不出现人物；仅展示商品、环境和操作所需的产品细节。' if content['presenter_mode']=='faceless' else '明确使用虚构成年角色：'+content['presenter_description']+'；不模仿真实人物或克隆真实声音，不冒充真实买家体验。'
    speech='不生成口播；仅使用场景环境声，不添加未提供的台词。' if content['speech_mode']=='none' else '仅使用以下已审阅台词，不增加体验背书或产品主张：\n'+content['script_text']
    offset=content['shots'][0]['start_ms']
    timeline=[{**shot,'source_start_ms':shot['start_ms'],'source_end_ms':shot['end_ms'],
        'start_ms':shot['start_ms']-offset,'end_ms':shot['end_ms']-offset} for shot in content['shots']]
    lines+=['以下已审阅内容替代初稿中的人物、场景、声音与镜头建议，产品事实及外观约束保持。',
            '本次已审阅的具体使用场景：'+content['use_scene'],'人物方式：'+person,'声音安排：'+speech,
            '本次仅制作以下已审阅镜头（start_ms/end_ms从本片段零秒起算，source为原完整分镜位置）：'+canonical(timeline),
            '台词与动作已由操作人对照商品资料核对；这不代表独立事实认证。保留上方产品事实及外观约束，不增加未提供的产品效果。']
    return '\n'.join(lines)


def review(plugins,plan_id,expected_plan_sha256,content,idempotency_key):
    _text(idempotency_key,160);plan=plugins._plan(plan_id)
    if plan['plan_sha256']!=expected_plan_sha256:raise ValueError('media_plugin_plan_changed')
    if plan['provider']!='heygen' or not plan['source_request']['spec']['format'].endswith('_video'):raise ValueError('media_video_review_video_plan_required')
    checked=validate(content,plan);call=deepcopy(plan['tool_call']);call['arguments']['prompt']=_prompt(plan,checked)
    if len(call['arguments']['prompt'])>16000:raise ValueError('media_video_review_prompt_too_long')
    frozen={key:deepcopy(plan[key]) for key in ('request_id','request_sha256','project_revision','connection_revision','provider','account_link_id','sources','shot_index','transfer')}
    frozen.update(tool_call=call,video_content=checked,source_plan_id=plan_id)
    fingerprint=digest(canonical(frozen));idem=digest(canonical([plan['request_id'],'video-review',idempotency_key]))
    with plugins.core.atomic() as db:
        plugins._guard(plan)
        old=db.execute('SELECT document FROM media_plugin_plans WHERE idem=?',(idem,)).fetchone()
        if old:
            import json
            previous=json.loads(old[0])
            if previous['plan_sha256']!=fingerprint:raise ValueError('media_plugin_idempotency_conflict')
            return plugins.get(previous['id'])
        if db.execute('SELECT count(*) FROM media_plugin_plans WHERE request_id=?',(plan['request_id'],)).fetchone()[0]>=100:raise ValueError('media_plugin_plan_limit')
        reviewed=deepcopy(plan);reviewed.update(tool_call=call,id='pluginplan_'+uuid.uuid4().hex[:20],plan_sha256=fingerprint,
            source_plan_id=plan_id,created_at=time.time(),blockers=[v for v in plan['blockers'] if v!=BLOCKER],
            video_review={'content':checked,'content_sha256':digest(canonical(checked)),'reviewed_at':time.time(),'operator_reviewed':True,
                          'independently_verified':False,'generation_approved':False})
        db.execute('INSERT INTO media_plugin_plans VALUES(?,?,?,?)',(reviewed['id'],idem,reviewed['request_id'],canonical(reviewed)))
    return plugins.get(reviewed['id'])
