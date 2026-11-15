"""Versioned production requests and evidence-based periodic creative review.

Reuses creative jobs and assets. Scheduling only creates local review reports;
generative tool handoffs remain awaiting media until actual files are attached.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import time
import uuid
from research import canonical, digest
from creative_direction import DIRECTION_FIELDS, FORMATS, input_sha, production_sha, specification, validate_analysis
from creative_readiness import evaluate as evaluate_readiness
from creative_image_profiles import catalog as image_profiles, normalize_options, apply_options


def definitions(schema,string):
    project={'project_id':string};revision={'expected_revision':string}
    asset_ids={'type':'array','items':string,'minItems':1,'maxItems':8}
    return [
        ('commerce_media_overview','读取商品统一创意方案、素材版本、效果记录与复查计划',schema(project,['project_id'])),
        ('commerce_media_readiness','只读检查当前商品的卖点、原图、参考与设计方向，区分制作清单和生成输入；不授权生成',schema(project,['project_id'])),
        ('commerce_media_direction_save','按资料版本保存人工核对的参考视觉拆解；不改变产品事实',schema({**project,**revision,'analysis':{'type':'object'},'reference_asset_ids':asset_ids,'analysis_job_id':string},['project_id','expected_revision','analysis','reference_asset_ids'])),
        ('commerce_media_request_create','创建绑定产品、卖点与设计方向的图片或视频制作清单；图片可指定平台、套图计划张数和本张重点，尚未生成媒体',schema({**project,**revision,'kind':{'type':'string','enum':list(FORMATS)},'idempotency_key':string,'review_id':string,'recommendation_index':{'type':'integer','minimum':0,'maximum':7},'image_options':{'type':'object','additionalProperties':False,'properties':{'profile_id':string,'set_size':{'type':'integer','minimum':5,'maximum':10},'aspect_ratio':{'type':'string','enum':['1:1','3:4','4:3']},'label':{'type':'string','maxLength':120},'focus':{'type':'string','maxLength':1000}},'required':['profile_id']}},['project_id','expected_revision','kind','idempotency_key'])),
        ('commerce_media_request_get','读取制作清单、真实文件和审阅状态；不重复执行生成',schema({'request_id':string},['request_id'])),
        ('commerce_media_request_execute','使用已选实物素材执行本机排版或多镜头剪辑；不合成人物或虚构场景',schema({'request_id':string,**revision,'asset_ids':asset_ids,'audio_asset_id':string},['request_id','expected_revision','asset_ids'])),
        ('commerce_media_request_attach','将实际制作并导入的同项目文件绑定到制作版本；结果仍待审阅',schema({'request_id':string,**revision,'asset_ids':asset_ids},['request_id','expected_revision','asset_ids'])),
        ('commerce_media_request_review','按文件哈希记录当前版本的素材审核，不发布商品或投放',schema({'request_id':string,'expected_result_sha256':string,'decision':{'type':'string','enum':['approved','rejected']},'note':{'type':'string','minLength':1,'maxLength':1200}},['request_id','expected_result_sha256','decision','note'])),
        ('commerce_media_performance_save','保存有来源、时间范围与可选素材版本的实际效果数据；不推断因果',schema({**project,'payload':{'type':'object'},'idempotency_key':string},['project_id','payload','idempotency_key'])),
        ('commerce_media_policy_save','保存商品图片视频的本地定期复查周期；只形成设计建议，不自动付费生成或发布',schema({**project,'expected_revision':{'type':'integer','minimum':0},'enabled':{'type':'boolean'},'interval_days':{'type':'integer','minimum':1,'maximum':90}},['project_id','expected_revision','enabled','interval_days'])),
        ('commerce_media_review_now','按已有销售与内容表现生成一次可追溯的本地调整建议',schema({**project,'idempotency_key':string},['project_id','idempotency_key'])),
    ]


def instant(value):
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.utcoffset() is None:raise ValueError()
        return dt.timestamp()
    except (ValueError,TypeError,AttributeError,OverflowError):raise ValueError('creative_metrics_invalid_period') from None


class CreativeWorkflow:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.studio=service.creative
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS creative_requests(id TEXT PRIMARY KEY,project TEXT NOT NULL,idem TEXT UNIQUE NOT NULL,document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS creative_performance(id TEXT PRIMARY KEY,project TEXT NOT NULL,idem TEXT UNIQUE NOT NULL,document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS creative_review_policies(project TEXT PRIMARY KEY,revision INTEGER NOT NULL,enabled INTEGER NOT NULL,interval_days INTEGER NOT NULL,next_due REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS creative_reviews(id TEXT PRIMARY KEY,project TEXT NOT NULL,slot TEXT NOT NULL,document TEXT NOT NULL,UNIQUE(project,slot))')

    def project(self,project_id,*,guard=False):
        p=self.studio.get(project_id);b=p['brief'].get('product_binding')
        if b:
            self.service.organization.case(b['case_id'])
            if guard:self.service.product_workspace.guard(b['case_id'],b['source_sha256'])
        return p

    def overview(self,project_id):
        p=self.project(project_id)
        with self.core.db() as db:
            ids=[r[0] for r in db.execute('SELECT id FROM creative_requests WHERE project=? ORDER BY rowid DESC LIMIT 100',(project_id,))]
            performance=[json.loads(r[0]) for r in db.execute('SELECT document FROM creative_performance WHERE project=? ORDER BY rowid DESC LIMIT 100',(project_id,))]
            reviews=[json.loads(r[0]) for r in db.execute('SELECT document FROM creative_reviews WHERE project=? ORDER BY rowid DESC LIMIT 30',(project_id,))]
            row=db.execute('SELECT revision,enabled,interval_days,next_due FROM creative_review_policies WHERE project=?',(project_id,)).fetchone()
        d=p['brief'].get('design_direction');binding=p['brief'].get('product_binding')
        current=not binding or self.service.product_workspace.sources(binding['case_id'])[3]==binding['source_sha256']
        scope=self.service.organization.case(binding['case_id'])['scope'] if binding else {}
        default_profile={'ozon':'ozon_ru','amazon':'amazon_us','tiktok':'tiktok_us','mercado':'mercado_mx'}.get(scope.get('platform'),'unverified')
        expected_market={'ozon_ru':'RU','amazon_us':'US','tiktok_us':'US','mercado_mx':'MX'}.get(default_profile)
        if expected_market and scope.get('market')!=expected_market:default_profile='unverified'
        return {'project_id':project_id,'project_revision':p['revision'],'binding_current':current,'direction':d,'sales_context':self.sales_context(p),
                'image_planning':image_profiles(default_profile),
                'direction_current':bool(d and d.get('input_sha256')==input_sha(p['brief'])),'readiness':evaluate_readiness(self.studio,p,binding_current=current),
                'formats':FORMATS,'direction_fields':DIRECTION_FIELDS,'requests':[self.request_get(r) for r in ids],
                'performance':performance,'reviews':reviews,'policy':dict(revision=row[0],enabled=bool(row[1]),interval_days=row[2],next_due=row[3]) if row else {'revision':0,'enabled':False,'interval_days':7,'next_due':None}}

    def sales_context(self,project):
        missing={'status':'not_linked_to_sales','postings':None,'units':None,'revenue':None,'conversion_rate':None,'sales_attribution_established':False}
        binding=project['brief'].get('product_binding')
        if not binding:return missing
        case=self.service.organization.case(binding['case_id']);scope=case['scope']
        if scope.get('platform')!='ozon' or scope.get('origin')=='research_candidate_not_inventory':return missing
        config=self.service.live.config();snapshot=self.service.live.snapshot(config.get('connection_id',''),'orders')
        if not snapshot:return {**missing,'status':'snapshot_unavailable'}
        if digest(canonical(snapshot['data']))!=snapshot['sha256']:return {**missing,'status':'snapshot_changed'}
        statuses={};postings=set();units=0
        for row in snapshot['data']['records']:
            if row.get('fulfillment') not in scope.get('fulfillment',[]):continue
            selected=[r for r in row['products'] if scope.get('sku') and scope['sku']==(r.get('offer_id') or r.get('sku'))]
            if not selected:continue
            key=(row['posting_number'],row.get('fulfillment'))
            if key in postings:continue
            postings.add(key);quantity=sum(r['quantity'] for r in selected);units+=quantity
            statuses[row['status']]=statuses.get(row['status'],0)+quantity
        return {**missing,'status':'saved_order_snapshot','postings':len(postings),'units':units,'units_by_raw_status':statuses,
                'fresh':self.service.live._fresh(snapshot,config),'scope_confirmed':config['orders_scope_confirmed'],
                'observed_at':snapshot['observed_at'],'source_sha256':snapshot['sha256'],
                'scope':'matching_product_and_fulfillment_only_not_settled_sales','lookback_days':config['lookback_days']}

    def readiness(self,project_id):
        p=self.project(project_id);binding=p['brief'].get('product_binding')
        current=not binding or self.service.product_workspace.sources(binding['case_id'])[3]==binding['source_sha256']
        return evaluate_readiness(self.studio,p,binding_current=current)

    def direction_save(self,project_id,expected_revision,analysis,reference_asset_ids,analysis_job_id=None):
        analysis=validate_analysis(analysis)
        with self.core.atomic():
            p=self.project(project_id,guard=True)
            if p['revision']!=expected_revision:raise ValueError('creative_revision_conflict_refresh_first')
            if not isinstance(reference_asset_ids,list) or not 1<=len(reference_asset_ids)<=8 or len(set(reference_asset_ids))!=len(reference_asset_ids):raise ValueError('creative_reference_media_required')
            refs=[]
            for aid in reference_asset_ids:
                path,meta,kind=self.studio.asset(project_id,aid)
                if kind not in ('reference_image','reference_video','keyframe'):raise ValueError('creative_reference_media_required')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('creative_asset_changed')
                refs.append({'asset_id':aid,'sha256':meta['sha256']})
            if analysis_job_id:
                job=self.studio.job_get(analysis_job_id)
                if job['project_id']!=project_id or job['status']!='completed' or job['input']['kind']!='design_analyze' or job['result'].get('input_sha256')!=input_sha(p['brief']):raise ValueError('creative_design_analysis_stale')
            b=p['brief'];b['design_direction']={'analysis':analysis,'references':refs,'input_sha256':input_sha(b),'status':'operator_reviewed','analysis_job_id':analysis_job_id,'reviewed_at':time.time()}
            b.pop('reviewed_script',None)
            return self.studio.save(project_id,b,expected_revision,allow_direction=True)

    def request_create(self,project_id,expected_revision,kind,idempotency_key,review_id=None,recommendation_index=None,image_options=None):
        options=normalize_options(image_options)
        with self.core.atomic() as db:
            p=self.project(project_id,guard=True)
            if p['revision']!=expected_revision:raise ValueError('creative_revision_conflict_refresh_first')
            spec=apply_options(specification(p,kind),options);d=p['brief']['design_direction']
            if review_id is not None:
                row=db.execute('SELECT document FROM creative_reviews WHERE id=? AND project=?',(review_id,project_id)).fetchone()
                if not row:raise ValueError('creative_review_outside_scope')
                review=json.loads(row[0])
                if review.get('project_input_sha256')!=input_sha(p['brief']):raise ValueError('creative_review_stale')
                if type(recommendation_index) is not int or not 0<=recommendation_index<len(review['recommendations']):raise ValueError('creative_invalid_recommendation')
                proposal=review['recommendations'][recommendation_index]
                if proposal['kind']!=kind or review['status']!='ready_for_review':raise ValueError('creative_invalid_recommendation')
                spec['iteration']={'review_id':review_id,'recommendation_index':recommendation_index,'reason':proposal['reason'],'performance_ids':review['performance_ids']}
                spec['prompt']+='\n本轮调整依据与目标：'+proposal['reason']+'\n效果数据只用于设计判断，不写入产品事实、促销文案或效果承诺。'
            elif recommendation_index is not None:raise ValueError('creative_invalid_recommendation')
            for ref in d['references']:
                path,meta,_=self.studio.asset(project_id,ref['asset_id'])
                if meta['sha256']!=ref['sha256'] or hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('creative_asset_changed')
            frozen={'project_id':project_id,'revision':expected_revision,'spec':spec}
            key=digest(canonical([project_id,idempotency_key]));old=db.execute('SELECT id,document FROM creative_requests WHERE idem=?',(key,)).fetchone()
            if old:
                previous=json.loads(old[1]);saved={k:previous[k] for k in ('project_id','revision','spec')}
                # A retry keeps its original immutable template, even after a
                # software upgrade. Compare the caller's inputs and source pins.
                if (previous['request_sha256']!=digest(canonical(saved))
                        or previous['project_id']!=project_id or previous['revision']!=expected_revision
                        or previous['spec']['format']!=kind
                        or previous['spec'].get('image_options')!=options
                        or previous['spec'].get('iteration')!=spec.get('iteration')
                        or previous['input_sha256']!=production_sha(p['brief'],kind)
                        or previous['direction_sha256']!=digest(canonical(d))):raise ValueError('idempotency_conflict')
                return self.request_get(old[0])
            if db.execute('SELECT count(*) FROM creative_requests WHERE project=?',(project_id,)).fetchone()[0]>=100:raise ValueError('creative_request_limit')
            doc={'id':uuid.uuid4().hex,**frozen,'input_sha256':production_sha(p['brief'],kind),'direction_sha256':digest(canonical(d)),
                 'request_sha256':digest(canonical(frozen)),'status':'awaiting_media','created_at':time.time(),
                 'external_generation_submitted':False,'job_id':None,'assets':[],'result_sha256':None,'review':None}
            db.execute('INSERT INTO creative_requests VALUES (?,?,?,?)',(doc['id'],project_id,key,canonical(doc)))
            return doc

    def _request(self,request_id):
        with self.core.db() as db:row=db.execute('SELECT document FROM creative_requests WHERE id=?',(request_id,)).fetchone()
        if not row:raise ValueError('creative_request_not_found')
        return json.loads(row[0])

    def request_get(self,request_id):
        d=self._request(request_id);p=self.project(d['project_id']);direction=p['brief'].get('design_direction')
        binding=p['brief'].get('product_binding')
        binding_changed=bool(binding and self.service.product_workspace.sources(binding['case_id'])[3]!=binding['source_sha256'])
        d['stale']=binding_changed or d['input_sha256']!=production_sha(p['brief'],d['spec']['format']) or d['direction_sha256']!=digest(canonical(direction))
        if d['job_id']:
            job=self.studio.job_get(d['job_id']);d['job_status']=job['status'];d['job_stage']=job['stage']
            if not d['assets']:
                if job['status']=='completed':
                    d['assets']=[{'id':a['id'],'sha256':a['sha256'],'kind':a['kind']} for a in job['result']['assets'] if a['kind'] in ('image_layout_draft','video_draft')]
                    d['result_sha256']=digest(canonical(d['assets']));d['status']='awaiting_review'
                elif job['status'] in ('queued','running'):d['status']=job['status']
                else:d['status']=job['status']
        # Derive external submission from durable provider receipts, including
        # shot jobs that deliberately do not attach a complete request output.
        with self.core.db() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_provider_jobs'").fetchone():
                jobs=[json.loads(row[0]) for row in db.execute("SELECT document FROM media_provider_jobs WHERE json_extract(document,'$.request_id')=? ORDER BY rowid",(request_id,))]
                d['external_generation_submitted']=bool(d.get('external_generation_submitted')) or any(job.get('external_generation_submitted') for job in jobs)
                d['provider_jobs']=[{k:job.get(k) for k in ('id','status','stage','remote_task_id','shot_index','external_generation_submitted')} for job in jobs]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_plugin_executions'").fetchone():
                executions=[json.loads(row[0]) for row in db.execute('SELECT document FROM media_plugin_executions WHERE request_id=?',(request_id,))]
                d['external_generation_submitted']=bool(d.get('external_generation_submitted')) or any(e.get('external_generation_submitted') for e in executions)
                d['plugin_executions']=[{k:e.get(k) for k in ('id','status','task_id','provider','provider_status','provider_terminal','external_generation_submitted','actual_bytes_verified','review_status')} for e in executions]
        return d

    def _current(self,d,revision=None):
        p=self.project(d['project_id'],guard=True)
        if (d['input_sha256']!=production_sha(p['brief'],d['spec']['format']) or d['direction_sha256']!=digest(canonical(p['brief'].get('design_direction'))) or (revision is not None and p['revision']!=revision)):
            raise ValueError('creative_request_stale')
        for ref in p['brief'].get('design_direction',{}).get('references',[]):
            path,meta,_=self.studio.asset(d['project_id'],ref['asset_id'])
            if meta['sha256']!=ref['sha256'] or hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('creative_asset_changed')
        return p

    def _assets(self,d,asset_ids):
        if not isinstance(asset_ids,list) or not 1<=len(asset_ids)<=8 or len(set(asset_ids))!=len(asset_ids):raise ValueError('creative_invalid_asset_selection')
        result=[];video=d['spec']['format'].endswith('_video')
        for aid in asset_ids:
            path,meta,kind=self.studio.asset(d['project_id'],aid)
            if kind not in (('generated_video','video_draft') if video else ('product_image','generated_image','image_layout_draft')):raise ValueError('creative_output_media_required')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('creative_asset_changed')
            result.append({'id':aid,'sha256':meta['sha256'],'kind':kind})
        return result

    def request_attach(self,request_id,expected_revision,asset_ids,*,_reuse=False):
        with self.core.atomic(reuse=_reuse) as db:
            d=self.request_get(request_id);self._current(d,expected_revision)
            assets=self._assets(d,asset_ids);sha=digest(canonical(assets))
            if d['result_sha256'] and d['result_sha256']!=sha:raise ValueError('creative_result_immutable_create_new_version')
            d.update(assets=assets,result_sha256=sha,status='awaiting_review' if not d['review'] else d['status'])
            db.execute('UPDATE creative_requests SET document=? WHERE id=?',(canonical(d),request_id))
        return self.request_get(request_id)

    def request_execute(self,request_id,expected_revision,asset_ids,audio_asset_id=None):
        with self.core.atomic():
            return self._execute(request_id,expected_revision,asset_ids,audio_asset_id)

    def _execute(self,request_id,expected_revision,asset_ids,audio_asset_id=None):
        d=self.request_get(request_id);self._current(d,expected_revision)
        if d['result_sha256']:raise ValueError('creative_result_immutable_create_new_version')
        if not isinstance(asset_ids,list) or not 1<=len(asset_ids)<=8:raise ValueError('creative_invalid_asset_selection')
        video=d['spec']['format'].endswith('_video')
        if video and len(asset_ids)!=len(d['spec']['shots']):raise ValueError('creative_shot_assets_required')
        if not video and len(asset_ids)!=1:raise ValueError('creative_one_product_image_required')
        for aid in asset_ids:
            path,meta,kind=self.studio.asset(d['project_id'],aid)
            if kind not in ('product_image','generated_image','generated_video') or (not video and kind=='generated_video'):raise ValueError('creative_product_media_required')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('creative_asset_changed')
        args={'project_id':d['project_id'],'asset_id':asset_ids[0],'idempotency_key':'production:'+request_id,
              '_production_spec':d['spec'],'_shot_assets':asset_ids if video else [],'_request_id':request_id,'_expected_revision':expected_revision,'_source_assets':{aid:self.studio.asset(d['project_id'],aid)[1]['sha256'] for aid in asset_ids}}
        if audio_asset_id:
            args['audio_asset_id']=audio_asset_id;args['_source_assets'][audio_asset_id]=self.studio.asset(d['project_id'],audio_asset_id)[1]['sha256']
        job=self.studio.start('story_render' if video else 'image_layout',args)
        with self.core.db() as db:
            d['job_id']=job['id'];d['status']=job['status'];db.execute('UPDATE creative_requests SET document=? WHERE id=?',(canonical(d),request_id))
        return self.request_get(request_id)

    def request_review(self,request_id,expected_result_sha256,decision,note):
        if decision not in ('approved','rejected') or not isinstance(note,str) or not 1<=len(note.strip())<=1200:raise ValueError('creative_review_note_required')
        with self.core.atomic() as db:
            d=self.request_get(request_id);self._current(d)
            if not d['assets'] or expected_result_sha256!=d['result_sha256']:raise ValueError('creative_result_changed')
            self._assets(d,[a['id'] for a in d['assets']])
            if d['review'] and (d['review']['decision']!=decision or d['review']['note']!=note.strip()):raise ValueError('creative_review_record_immutable')
            d.update(status=decision,review=d['review'] or {'decision':decision,'note':note.strip(),'at':time.time(),'independently_verified':False})
            db.execute('UPDATE creative_requests SET document=? WHERE id=?',(canonical(d),request_id))
        return d

    def performance_save(self,project_id,payload,idempotency_key):
        self.project(project_id)
        counts=('impressions','clicks','orders','returns','video_views','completed_views')
        if not isinstance(payload,dict) or set(payload)-set(counts)-{'period_start','period_end','source_ref','request_id','feedback'}:raise ValueError('creative_metrics_invalid_fields')
        start=instant(payload.get('period_start'));end=instant(payload.get('period_end'))
        if end<=start or end>time.time()+300:raise ValueError('creative_metrics_invalid_period')
        if not isinstance(payload.get('source_ref'),str) or not 1<=len(payload['source_ref'].strip())<=1000:raise ValueError('creative_metrics_source_required')
        if not any(k in payload for k in counts):raise ValueError('creative_metrics_counts_required')
        if not isinstance(payload.get('feedback',''),str) or len(payload.get('feedback',''))>2000:raise ValueError('creative_metrics_invalid_feedback')
        for k in counts:
            if k in payload and (type(payload[k]) is not int or not 0<=payload[k]<=10**12):raise ValueError('creative_metrics_invalid_count')
        for small,large in [('clicks','impressions'),('completed_views','video_views'),('returns','orders')]:
            if small in payload and large in payload and payload[small]>payload[large]:raise ValueError('creative_metrics_count_conflict')
        result_sha=None
        if payload.get('request_id'):
            req=self.request_get(payload['request_id'])
            if req['project_id']!=project_id:raise ValueError('creative_metrics_request_outside_scope')
            result_sha=req['result_sha256']
        def ratio(a,b):return payload[a]/payload[b] if a in payload and b in payload and payload[b]>0 else None
        metrics={'ctr':ratio('clicks','impressions'),'conversion_rate':ratio('orders','clicks'),'return_rate':ratio('returns','orders'),'completion_rate':ratio('completed_views','video_views')}
        key=digest(canonical([project_id,idempotency_key]));sha=digest(canonical(payload))
        with self.core.atomic() as db:
            row=db.execute('SELECT document FROM creative_performance WHERE idem=?',(key,)).fetchone()
            if row:
                old=json.loads(row[0])
                if old['input_sha256']!=sha:raise ValueError('idempotency_conflict')
                return old
            if db.execute('SELECT count(*) FROM creative_performance WHERE project=?',(project_id,)).fetchone()[0]>=1000:raise ValueError('creative_performance_limit')
            d={'id':uuid.uuid4().hex,'project_id':project_id,'payload':payload,'metrics':metrics,'input_sha256':sha,'result_sha256':result_sha,'created_at':time.time(),'causal_attribution':'not_established'}
            db.execute('INSERT INTO creative_performance VALUES (?,?,?,?)',(d['id'],project_id,key,canonical(d)))
        return d

    def policy_save(self,project_id,expected_revision,enabled,interval_days):
        self.project(project_id)
        if type(expected_revision) is not int or type(enabled) is not bool or type(interval_days) is not int or not 1<=interval_days<=90:raise ValueError('creative_policy_invalid')
        with self.core.atomic() as db:
            row=db.execute('SELECT revision,next_due FROM creative_review_policies WHERE project=?',(project_id,)).fetchone()
            if (row[0] if row else 0)!=expected_revision:raise ValueError('creative_policy_conflict')
            due=time.time()+interval_days*86400
            db.execute('INSERT INTO creative_review_policies VALUES (?,?,?,?,?) ON CONFLICT(project) DO UPDATE SET revision=excluded.revision,enabled=excluded.enabled,interval_days=excluded.interval_days,next_due=excluded.next_due',(project_id,expected_revision+1,int(enabled),interval_days,due))
        return self.overview(project_id)['policy']

    def _review(self,project_id,slot,at):
        with self.core.db() as db:
            old=db.execute('SELECT document FROM creative_reviews WHERE project=? AND slot=?',(project_id,slot)).fetchone()
            if old:return json.loads(old[0])
        overview=self.overview(project_id);records=overview['performance'];recommendations=[]
        # Preserve missing denominators. A report is an observation, never proof
        # that a particular image or video caused the observed sales change.
        if not records:
            status='needs_data';reason=('已有对应商品的发货单快照；它不能替代销售额、曝光、点击与素材归属，请补充相同统计窗口的数据。' if overview['sales_context']['status']=='saved_order_snapshot' else '尚无可用于本次判断的销售或内容表现数据，请补充有来源和时间范围的数据。')
        elif not overview['binding_current']:status='needs_source_review';reason='商品资料已有变化，先核对当前产品与素材版本。'
        else:
            status='ready_for_review';reason='根据已提供样本形成设计试验建议；尚未建立素材与销量变化的因果关系。'
            latest=max(records,key=lambda r:instant(r['payload']['period_end']));m=latest['metrics'];v=latest['payload']
            if v.get('impressions',0)<200 and v.get('video_views',0)<100:
                status='insufficient_sample';recommendations.append({'kind':'product_main','reason':'当前样本较少，先补充曝光或观看数据，再判断素材优劣。'})
            else:
                if m['ctr'] is not None:recommendations.append({'kind':'product_main','reason':f"本期点击率 {m['ctr']:.2%}。可设计核心卖点与主体构图的对照版本，保持价格和投放条件可比。"})
                if m['conversion_rate'] is not None:recommendations.append({'kind':'product_detail','reason':f"本期点击后订单比率 {m['conversion_rate']:.2%}。结合商品信息与购买疑问补充细节、规格和使用过程。"})
                if m['completion_rate'] is not None:recommendations.append({'kind':'ugc_video','reason':f"本期完播比率 {m['completion_rate']:.2%}。可测试开场使用情境、特写出现顺序与演示节奏。"})
                if v.get('feedback'):recommendations.append({'kind':'usage_scene','reason':'结合已记录反馈核对场景适配与预期表达：'+v['feedback'][:500]})
            if not recommendations:recommendations.append({'kind':'showcase_video','reason':'现有记录不足以判断具体素材，补充素材版本归属、观看和反馈数据。'})
        project=self.project(project_id)
        for proposal in recommendations:
            if status=='ready_for_review' and overview['direction_current']:
                proposal['proposed_spec']=specification(project,proposal['kind'])
                proposal['proposed_spec']['prompt']+='\n本轮调整目标：'+proposal['reason']+'\n效果数据只用于设计判断，不作为产品卖点或促销承诺。'
        d={'id':uuid.uuid4().hex,'project_id':project_id,'slot':slot,'created_at':at,'status':status,'reason':reason,'project_input_sha256':input_sha(project['brief']),
           'performance_ids':[r['id'] for r in records],'sales_context':overview['sales_context'],'recommendations':recommendations,'generation_submitted':False,'publication_executed':False,'sample_thresholds':{'impressions':200,'video_views':100}}
        with self.core.db() as db:
            db.execute('INSERT OR IGNORE INTO creative_reviews VALUES (?,?,?,?)',(d['id'],project_id,slot,canonical(d)))
            return json.loads(db.execute('SELECT document FROM creative_reviews WHERE project=? AND slot=?',(project_id,slot)).fetchone()[0])

    def review_now(self,project_id,idempotency_key):
        self.project(project_id)
        return self._review(project_id,'manual:'+idempotency_key,time.time())

    def tick(self,at=None):
        at=time.time() if at is None else at
        with self.core.db() as db:rows=db.execute('SELECT project,revision,interval_days,next_due FROM creative_review_policies WHERE enabled=1 AND next_due<=? ORDER BY next_due LIMIT 8',(at,)).fetchall()
        for pid,revision,days,due in rows:
            try:
                with self.core.atomic() as db:
                    current=db.execute('SELECT revision,next_due,enabled FROM creative_review_policies WHERE project=?',(pid,)).fetchone()
                    if current!=(revision,due,1):continue
                    self._review(pid,'scheduled:'+str(due),at)
                    db.execute('UPDATE creative_review_policies SET next_due=? WHERE project=?',(at+days*86400,pid))
            except ValueError:
                # Revoked product scope must never be bypassed by a background task.
                continue

    def invoke(self,name,args):
        return getattr(self,name.removeprefix('commerce_media_'))(**args)
