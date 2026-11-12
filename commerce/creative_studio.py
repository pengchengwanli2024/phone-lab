"""Private, bounded creative projects and real local media job receipts."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import uuid

from creative_plan import plan
from creative_render import layout_svg, panel_svg, render_svg
from creative_tools import command as local_command, environment as local_environment, NAMES as MEDIA_TOOLS

ROOT = Path(__file__).resolve().parent
CHUNK = 48 * 1024
MAX_ASSET = 32 * 1024 * 1024
_slots = threading.BoundedSemaphore(2)


def stamp(): return datetime.now(timezone.utc).isoformat()
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
def digest(value): return hashlib.sha256(value).hexdigest()
def ident(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('creative_invalid_id')
    return value


def tool_definitions(schema, string):
    obj = {'type': 'object'}
    definitions = [
        ('create', '创建文案、图片和视频共用的私有创意项目；资料缺失保持待补充', {'brief': obj, 'idempotency_key': string}, ['brief','idempotency_key']),
        ('list', '列出本机创意项目；不读取其它目录', {}, []),
        ('get', '读取创意项目、三类草稿、素材和真实处理回执', {'project_id': string}, ['project_id']),
        ('save', '按版本保存产品依据与参考文案；不把参考片主张当成产品事实', {'project_id': string,'brief': obj,'revision': string}, ['project_id','brief','revision']),
        ('upload_begin', '开始有界私有素材上传，不抓取任意网址', {'project_id':string,'filename':string,'kind':{'type':'string','enum':['reference_video','product_image','audio','captions','generated_image','generated_video']},'size':string,'sha256':string,'source_ref':{'type':'string','maxLength':1000}}, ['project_id','filename','kind','size','sha256']),
        ('upload_chunk', '上传一个有序分片；重传相同分片不重复写入', {'upload_id':string,'index':string,'content_base64':{'type':'string','minLength':1,'maxLength':66000}}, ['upload_id','index','content_base64']),
        ('upload_finish', '校验上传哈希和实际媒体格式后登记素材', {'upload_id':string}, ['upload_id']),
        ('asset_read', '分片读取本项目登记的私有素材，不接受文件路径', {'project_id':string,'asset_id':string,'offset':string}, ['project_id','asset_id']),
        ('analyze', '本机读取视频元信息、关键帧、OCR与已提供字幕；不下载语音模型', {'project_id':string,'asset_id':string,'idempotency_key':string}, ['project_id','asset_id','idempotency_key']),
        ('review_transcript', '校对指定分析任务的口播并回填参考文案，按版本保存；不变成商品事实', {'project_id':string,'job_id':string,'revision':string,'text':{'type':'string','minLength':1,'maxLength':6000}}, ['project_id','job_id','revision','text']),
        ('render', '将所选素材与有依据文案渲染为图文视频草稿，可使用已导入音轨；不是实拍UGC或效果验证', {'project_id':string,'asset_id':string,'idempotency_key':string,'audio_asset_id':string,'variant':{'type':'string','enum':['0','1','2']}}, ['project_id','asset_id','idempotency_key']),
        ('refine', '将产品事实和所填参考文案提交给既有模型升级文案；不上传原视频，结果待审阅', {'project_id':string,'idempotency_key':string}, ['project_id','idempotency_key']),
        ('approve_script', '按项目版本采用明确审阅的AI文案作为制作稿；保留模型与主张依据', {'project_id':string,'job_id':string,'angle':{'type':'string','enum':['detail','selection','demonstration']},'revision':string}, ['project_id','job_id','angle','revision']),
        ('image_layout', '保留商品原图，生成三种可编辑模板排版；不执行自动主体分割', {'project_id':string,'asset_id':string,'idempotency_key':string}, ['project_id','asset_id','idempotency_key']),
        ('job_get', '查询实际创意执行阶段、结果、失败或中断，不自动重发', {'job_id':string}, ['job_id']),
        ('job_cancel', '请求在本地处理检查点取消；已产生的素材保留', {'job_id':string}, ['job_id']),
        ('export', '导出文案、分镜、分析回执和来源，支持JSON或Markdown制作清单', {'project_id':string,'format':{'type':'string','enum':['json','markdown']}}, ['project_id']),
    ]
    return [('commerce_creative_'+name, desc, schema(props, required)) for name, desc, props, required in definitions]


def normalize_brief(brief, allow_reviewed=False):
    if not isinstance(brief,dict) or len(canonical(brief))>20000:
        raise ValueError('creative_brief_too_large')
    if 'reviewed_script' in brief and not allow_reviewed:raise ValueError('creative_use_review_action_for_model_script')
    product=brief.get('product') or {}
    if not isinstance(product,dict): raise ValueError('creative_invalid_product')
    facts=product.get('verified_facts',[])
    if not isinstance(facts,list) or len(facts)>20: raise ValueError('creative_invalid_facts')
    for fact in facts:
        if not isinstance(fact,dict) or not all(isinstance(fact.get(k),str) for k in ('id','text','evidence_ref')):
            raise ValueError('creative_fact_source_required')
    reference=brief.get('reference') or {}
    target=brief.get('target') or {}
    if not isinstance(reference,dict) or not isinstance(target,dict): raise ValueError('creative_invalid_brief')
    if not isinstance(reference.get('transcript',''),str) or len(reference.get('transcript',''))>6000:
        raise ValueError('creative_transcript_too_large')
    plan(brief)
    return json.loads(canonical(brief))


class CreativeStudio:
    def __init__(self, core, state):
        self.core=core
        self.root=Path(state).resolve()/'creative'
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.root.is_symlink(): raise ValueError('creative_unsafe_storage')
        os.chmod(self.root,0o700)
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS creative_projects (id TEXT PRIMARY KEY, idem TEXT UNIQUE, brief TEXT, revision INTEGER, created TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS creative_assets (id TEXT PRIMARY KEY, project TEXT, kind TEXT, metadata TEXT, filename TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS creative_uploads (id TEXT PRIMARY KEY, project TEXT, spec TEXT, next_index INTEGER, received INTEGER, asset TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS creative_jobs (id TEXT PRIMARY KEY, idem TEXT UNIQUE, project TEXT, input TEXT, status TEXT, stage TEXT, result TEXT, created TEXT, cancel INTEGER)')
            for old in db.execute("SELECT id,input,status FROM creative_jobs WHERE status IN ('queued','running')").fetchall():
                unknown=json.loads(old[1]).get('kind')=='refine' and old[2]=='running'
                status='unknown' if unknown else 'interrupted'
                db.execute('UPDATE creative_jobs SET status=?,stage=?,result=? WHERE id=?',(status,status,canonical({'error':'creative_model_outcome_unknown_no_automatic_resubmit' if unknown else 'creative_worker_interrupted_no_automatic_retry'}),old[0]))

    def folder(self, project):
        path=self.root/ident(project)
        if path.is_symlink(): raise ValueError('creative_unsafe_storage')
        path.mkdir(mode=0o700,exist_ok=True)
        return path

    def asset(self, project, asset):
        with self.core.db() as db:
            row=db.execute('SELECT kind,metadata,filename FROM creative_assets WHERE id=? AND project=?',(ident(asset),ident(project))).fetchone()
        if not row: raise ValueError('creative_asset_not_found')
        path=self.folder(project)/row[2]
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(self.root):
            raise ValueError('creative_asset_unavailable')
        return path, json.loads(row[1]), row[0]

    def get(self, project):
        with self.core.db() as db:
            row=db.execute('SELECT brief,revision,created FROM creative_projects WHERE id=?',(ident(project),)).fetchone()
            if not row: raise ValueError('creative_project_not_found')
            assets=[dict(id=r[0],kind=r[1],**json.loads(r[2])) for r in db.execute('SELECT id,kind,metadata FROM creative_assets WHERE project=? ORDER BY rowid',(project,))]
            jobs=[dict(id=r[0],status=r[1],stage=r[2],created_at=r[3],kind=json.loads(r[4])['kind']) for r in db.execute('SELECT id,status,stage,created,input FROM creative_jobs WHERE project=? ORDER BY rowid DESC LIMIT 30',(project,))]
        brief=json.loads(row[0])
        return dict(id=project,brief=brief,revision=str(row[1]),created_at=row[2],plan=plan(brief),assets=assets,jobs=jobs,external_generation_submitted=False,creative_studio_version='0.2.0')

    def create(self, brief, key):
        brief=normalize_brief(brief)
        if not key.strip(): raise ValueError('invalid_idempotency_key')
        frozen=canonical(brief)
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT id,brief FROM creative_projects WHERE idem=?',(key,)).fetchone()
            if row:
                if row[1]!=frozen: raise ValueError('idempotency_conflict')
                project=row[0]
            else:
                if db.execute('SELECT count(*) FROM creative_projects').fetchone()[0]>=100:raise ValueError('creative_project_limit')
                project=uuid.uuid4().hex
                db.execute('INSERT INTO creative_projects VALUES (?,?,?,?,?)',(project,key,frozen,1,stamp()))
        return self.get(project)

    def save(self, project, brief, revision, allow_reviewed=False):
        brief=normalize_brief(brief,allow_reviewed)
        with self.core.db() as db:
            cursor=db.execute('UPDATE creative_projects SET brief=?,revision=revision+1 WHERE id=? AND revision=?',(canonical(brief),ident(project),revision))
            if cursor.rowcount!=1: raise ValueError('creative_revision_conflict_refresh_first')
        return self.get(project)

    def begin(self, args):
        self.get(args['project_id'])
        try: size=int(args['size'])
        except (TypeError,ValueError): raise ValueError('creative_invalid_size') from None
        if not 0<size<=MAX_ASSET or not re.fullmatch('[a-f0-9]{64}',args['sha256']): raise ValueError('creative_invalid_upload')
        name=args['filename']
        if Path(name).name!=name or any(c in name for c in '/\\\0') or name in ('.','..'): raise ValueError('creative_invalid_filename')
        spec={k:args[k] for k in ['filename','kind','sha256']}
        spec.update(size=size,source_ref=args.get('source_ref','user_provided_unverified'))
        frozen=canonical(spec)
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT id,next_index,asset FROM creative_uploads WHERE project=? AND spec=?',(args['project_id'],frozen)).fetchone()
            if old:return dict(upload_id=old[0],next_index=old[1],asset_id=old[2],chunk_bytes=CHUNK)
            reserved=db.execute('SELECT spec FROM creative_uploads WHERE project=?',(args['project_id'],)).fetchall()
            if len(reserved)>=100 or sum(json.loads(r[0])['size'] for r in reserved)+size>256*1024*1024: raise ValueError('creative_project_storage_limit')
            upload=uuid.uuid4().hex
            db.execute('INSERT INTO creative_uploads VALUES (?,?,?,?,?,NULL)',(upload,args['project_id'],frozen,0,0))
        return dict(upload_id=upload,next_index=0,asset_id=None,chunk_bytes=CHUNK)

    def chunk(self, upload, index, content):
        try:
            index=int(index);data=base64.b64decode(content,validate=True)
        except (ValueError,TypeError): raise ValueError('creative_invalid_chunk') from None
        if not 0<len(data)<=CHUNK or not 0<=index<math.ceil(MAX_ASSET/CHUNK): raise ValueError('creative_invalid_chunk')
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT project,spec,next_index,received,asset FROM creative_uploads WHERE id=?',(ident(upload),)).fetchone()
            if not row or row[4]: raise ValueError('creative_upload_closed')
            target=self.folder(row[0])/(upload+'.part')
            if target.is_symlink(): raise ValueError('creative_unsafe_storage')
            if index<row[2]:
                expected=min(CHUNK,json.loads(row[1])['size']-index*CHUNK)
                if len(data)!=expected:raise ValueError('creative_chunk_conflict')
                with target.open('rb') as f:f.seek(index*CHUNK);old=f.read(len(data))
                if old!=data: raise ValueError('creative_chunk_conflict')
                return dict(next_index=row[2],received=row[3],duplicate=True)
            spec=json.loads(row[1])
            expected=min(CHUNK,spec['size']-row[3])
            if index!=row[2] or len(data)!=expected: raise ValueError('creative_chunk_out_of_order')
            with target.open('r+b' if target.exists() else 'w+b') as f:
                f.truncate(row[3]);f.seek(row[3]);f.write(data);f.flush();os.fsync(f.fileno())
            os.chmod(target,0o600)
            db.execute('UPDATE creative_uploads SET next_index=?,received=? WHERE id=?',(index+1,row[3]+len(data),upload))
        return dict(next_index=index+1,received=row[3]+len(data),duplicate=False)

    def run(self, argv, timeout=40):
        argv=[str(a) for a in argv]
        if argv[0] in MEDIA_TOOLS:argv[0]=local_command(argv[0])
        try:r=subprocess.run(argv,capture_output=True,timeout=timeout,env=local_environment())
        except FileNotFoundError: raise ValueError('creative_local_tool_unavailable') from None
        except subprocess.TimeoutExpired: raise ValueError('creative_processing_timeout') from None
        if r.returncode: raise ValueError('creative_media_processing_failed')
        return r

    def probe(self, path):
        r=self.run(['ffprobe','-v','error','-show_entries','format=duration,format_name:stream=codec_type,width,height','-of','json',path],15)
        try:
            d=json.loads(r.stdout);streams=d.get('streams',[]);video=next((s for s in streams if s.get('codec_type')=='video'),{})
            duration=float(d.get('format',{}).get('duration',0));width=int(video.get('width',0));height=int(video.get('height',0))
        except (ValueError,TypeError,OverflowError): raise ValueError('creative_invalid_media') from None
        if not math.isfinite(duration) or duration>120 or width*height>16777216 or len(streams)>12:
            raise ValueError('creative_media_limits_exceeded')
        return dict(duration_seconds=duration,width=width,height=height,has_audio=any(s.get('codec_type')=='audio' for s in streams),format=d.get('format',{}).get('format_name',''))

    def register(self, project, kind, path, metadata):
        asset=uuid.uuid4().hex
        destination=self.folder(project)/(asset+path.suffix.lower())
        metadata={**metadata,'size':path.stat().st_size,'sha256':digest(path.read_bytes()),'created_at':stamp()}
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            records=db.execute('SELECT metadata FROM creative_assets WHERE project=?',(project,)).fetchall()
            if len(records)>=500 or sum(json.loads(x[0])['size'] for x in records)+metadata['size']>512*1024*1024:raise ValueError('creative_project_storage_limit')
            path.replace(destination);os.chmod(destination,0o600)
            db.execute('INSERT INTO creative_assets VALUES (?,?,?,?,?)',(asset,project,kind,canonical(metadata),destination.name))
        return dict(id=asset,kind=kind,**metadata)

    def finish(self, upload):
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT project,spec,received,asset FROM creative_uploads WHERE id=?',(ident(upload),)).fetchone()
            if not row: raise ValueError('creative_upload_not_found')
            if row[3]:return dict(asset_id=row[3],duplicate=True)
            spec=json.loads(row[1]);source=self.folder(row[0])/(upload+'.part')
            if row[2]!=spec['size'] or source.is_symlink() or not source.is_file() or digest(source.read_bytes())!=spec['sha256']:
                raise ValueError('creative_upload_hash_or_size_mismatch')
            head=source.read_bytes()[:16];kind=spec['kind']
            if kind in ['product_image','generated_image']:
                if head.startswith(b'\x89PNG\r\n\x1a\n'):suffix='.png'
                elif head.startswith(b'\xff\xd8\xff'):suffix='.jpg'
                else:raise ValueError('creative_image_requires_png_or_jpeg')
            elif kind=='captions':
                if spec['size']>50000:raise ValueError('creative_captions_too_large')
                try:source.read_text(encoding='utf-8-sig')
                except UnicodeError:raise ValueError('creative_captions_utf8_required') from None
                suffix='.srt'
            elif head[4:8]==b'ftyp':suffix='.mp4'
            elif head.startswith(b'\x1aE\xdf\xa3'):suffix='.webm'
            elif head.startswith(b'RIFF'):suffix='.wav'
            else:raise ValueError('creative_unsupported_media')
            metadata={'display_name':spec['filename'],'source_ref':spec['source_ref'],'origin':'user_upload','usage_scope':'not_independently_verified'}
            if kind!='captions':
                metadata['media']=self.probe(source)
                media=metadata['media']
                if kind in ['reference_video','generated_video'] and (media['width']==0 or media['duration_seconds']<=0): raise ValueError('creative_video_required')
                if kind in ['product_image','generated_image'] and media['width']==0:raise ValueError('creative_image_required')
                if kind=='audio' and not media['has_audio']:raise ValueError('creative_audio_required')
            asset=uuid.uuid4().hex;dest=self.folder(row[0])/(asset+suffix)
            source.replace(dest);os.chmod(dest,0o600)
            metadata.update(size=spec['size'],sha256=spec['sha256'],created_at=stamp())
            db.execute('INSERT INTO creative_assets VALUES (?,?,?,?,?)',(asset,row[0],kind,canonical(metadata),dest.name))
            db.execute('UPDATE creative_uploads SET asset=? WHERE id=?',(asset,upload))
        return dict(asset_id=asset,duplicate=False)

    def read_asset(self, project, asset, offset='0'):
        path,meta,kind=self.asset(project,asset)
        try: offset=int(offset)
        except ValueError:raise ValueError('creative_invalid_offset') from None
        if offset<0 or offset>meta['size']:raise ValueError('creative_invalid_offset')
        with path.open('rb') as f:f.seek(offset);data=f.read(CHUNK)
        mime={'.png':'image/png','.jpg':'image/jpeg','.mp4':'video/mp4','.webm':'video/webm','.wav':'audio/wav','.srt':'text/plain; charset=utf-8','.json':'application/json'}.get(path.suffix,'application/octet-stream')
        return dict(content_base64=base64.b64encode(data).decode(),next_offset=str(offset+len(data)),size=meta['size'],mime=mime,extension=path.suffix,sha256=meta['sha256'],done=offset+len(data)>=meta['size'])

    def job_get(self, job):
        with self.core.db() as db:row=db.execute('SELECT id,project,input,status,stage,result,created,cancel FROM creative_jobs WHERE id=?',(ident(job),)).fetchone()
        if not row:raise ValueError('creative_job_not_found')
        return dict(id=row[0],project_id=row[1],input=json.loads(row[2]),status=row[3],stage=row[4],result=json.loads(row[5]) if row[5] else None,created_at=row[6],cancel_requested=bool(row[7]))

    def start(self, kind, args):
        project=self.get(args['project_id']);asset_kind=None
        if kind!='refine':path,meta,asset_kind=self.asset(project['id'],args['asset_id'])
        elif project['plan']['status']!='draft_ready':raise ValueError('creative_product_facts_required')
        if kind=='analyze' and asset_kind!='reference_video':raise ValueError('creative_reference_video_required')
        if kind=='render' and (asset_kind not in ['product_image','generated_image','generated_video'] or project['plan']['status']!='draft_ready'):
            raise ValueError('creative_render_requires_product_asset_and_facts')
        if kind=='image_layout' and asset_kind not in ['product_image','generated_image']:
            raise ValueError('creative_product_image_required')
        if args.get('audio_asset_id') and self.asset(project['id'],args['audio_asset_id'])[2]!='audio':raise ValueError('creative_audio_required')
        data=dict(kind=kind,project_id=project['id'],asset_id=args.get('asset_id'),audio_asset_id=args.get('audio_asset_id'),revision=project['revision'],brief=project['brief'],variant=args.get('variant','0'))
        frozen=canonical(data);key=args['idempotency_key']
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT id,input FROM creative_jobs WHERE idem=?',(key,)).fetchone()
            if old:
                if old[1]!=frozen:raise ValueError('idempotency_conflict')
                return self.job_get(old[0])
            if db.execute("SELECT 1 FROM creative_jobs WHERE project=? AND status IN ('queued','running')",(project['id'],)).fetchone():raise ValueError('creative_project_busy')
            if db.execute('SELECT count(*) FROM creative_jobs WHERE project=?',(project['id'],)).fetchone()[0]>=100:raise ValueError('creative_project_job_limit')
            if not _slots.acquire(blocking=False):raise ValueError('creative_workers_busy_try_later')
            job=uuid.uuid4().hex
            try:db.execute('INSERT INTO creative_jobs VALUES (?,?,?,?,?,?,?,?,0)',(job,key,project['id'],frozen,'queued','queued',None,stamp()))
            except Exception:_slots.release();raise
        threading.Thread(target=self.work,args=(job,data),daemon=True).start()
        return self.job_get(job)

    def stage(self, job, stage):
        with self.core.db() as db:
            if db.execute('SELECT cancel FROM creative_jobs WHERE id=?',(job,)).fetchone()[0]:raise ValueError('creative_cancelled')
            db.execute("UPDATE creative_jobs SET status='running',stage=? WHERE id=?",(stage,job))

    def work(self, job, data):
        try:
            result={'analyze':self.analyze,'render':self.render,'image_layout':self.image_layout,'refine':self.refine}[data['kind']](job,data)
            self.stage(job,'finished')
            status='completed' if not result.get('missing') else 'partial'
        except Exception as error:
            code=str(error) if isinstance(error,ValueError) else 'creative_processing_failed'
            with self.core.db() as db:failed_stage=db.execute('SELECT stage FROM creative_jobs WHERE id=?',(job,)).fetchone()[0]
            result={'error':code,'failed_stage':failed_stage};status='cancelled' if code=='creative_cancelled' else 'unknown' if 'outcome_unknown' in code else 'failed'
        finally:_slots.release()
        with self.core.db() as db:db.execute('UPDATE creative_jobs SET status=?,stage=?,result=? WHERE id=?',(status,status,canonical(result),job))

    def analyze(self, job, data):
        from creative_analysis import detect_shots
        from creative_budget import OCRBudget
        ocr_budget=OCRBudget()
        project=data['project_id'];path,meta,_=self.asset(project,data['asset_id']);self.stage(job,'probe')
        media=self.probe(path);duration=media['duration_seconds'];frames=[];ocr=[];missing=[]
        self.stage(job,'visual_cut_detection')
        try:shots=detect_shots(self,path,duration)
        except ValueError:
            shots={'method':'unavailable_uniform_samples','keyframe_times':[round(duration*i/4,3) for i in range(4)],'segments':[]}
            missing.append('visual_cut_detection_unavailable')
        self.stage(job,'keyframes')
        for i,requested in enumerate(shots['keyframe_times']):
            self.stage(job,'keyframe_'+str(i+1));at=requested
            temp=self.folder(project)/(job+'-'+str(i)+'.png')
            self.run(['ffmpeg','-nostdin','-v','error','-y','-ss',str(at),'-i',path,'-frames:v','1','-vf','scale=720:-2','-update','1',temp])
            fallback=False
            if not temp.is_file():
                at=0;fallback=True
                self.run(['ffmpeg','-nostdin','-v','error','-y','-i',path,'-frames:v','1','-vf','scale=720:-2','-update','1',temp])
            frame=self.register(project,'keyframe',temp,{'display_name':'关键帧 '+str(i+1),'origin':'derived','parent_asset_id':data['asset_id'],'job_id':job,'requested_timestamp_seconds':requested,'extracted_timestamp_seconds':at,'fallback_to_first_frame':fallback,'source_revision':data['revision']})
            frames.append(frame)
            helper=ROOT.parent/'bin/ocr'
            if helper.is_file():
                self.stage(job,'ocr_'+str(i+1))
                receipt=ocr_budget.read(self.run,[helper,self.asset(project,frame['id'])[0]])
                ocr.append(dict(asset_id=frame['id'],requested_timestamp_seconds=at,**receipt))
        self.stage(job,'transcript')
        supplied=data['brief'].get('reference',{}).get('transcript','')
        if not supplied:
            with self.core.db() as db:row=db.execute("SELECT id FROM creative_assets WHERE project=? AND kind='captions' ORDER BY rowid DESC LIMIT 1",(project,)).fetchone()
            if row:supplied=self.asset(project,row[0])[0].read_text(encoding='utf-8-sig')[:6000]
        transcript={'text':supplied,'source':'user_provided_not_independently_verified' if supplied else 'not_available'}
        if not supplied and media['has_audio']:
            from creative_asr import available,transcribe
            if available():
                self.stage(job,'local_asr');audio=self.folder(project)/(job+'-audio.wav')
                self.run(['ffmpeg','-nostdin','-v','error','-y','-i',path,'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',audio])
                audio.chmod(0o600)
                try:transcript=transcribe(audio,self.folder(project)/(job+'-asr'),duration)
                except ValueError as error:missing.append(str(error))
            else:missing.append('local_asr_model_not_configured_import_captions_or_transcript')
        if not transcript.get('text'):missing.append('spoken_transcript_not_available_import_captions_or_transcript')
        if len(ocr)<len(frames) or any(x.get('status') in ('unavailable','skipped') for x in ocr):missing.append('keyframe_ocr_incomplete')
        return dict(project_revision=data['revision'],source_asset_id=data['asset_id'],media=media,keyframes=frames,ocr=ocr,transcript=transcript,shot_detection=shots['method'],shot_analysis=shots,semantic_analysis='not_performed',missing=missing)

    def review_transcript(self, project, job, text, revision):
        p=self.get(project);j=self.job_get(job)
        if j['project_id']!=project or j['input']['kind']!='analyze' or j['status'] not in ['completed','partial']:
            raise ValueError('creative_analysis_required')
        if not isinstance(text,str) or not text.strip() or len(text)>6000:
            raise ValueError('creative_transcript_review_text_required')
        asset=j['result']['source_asset_id'];_,meta,_=self.asset(project,asset)
        brief=p['brief'];reference=brief.get('reference') or {};brief['reference']=reference
        if p['revision']!=revision:raise ValueError('creative_revision_conflict_refresh_first')
        existing=reference.get('transcript_review',{})
        if existing.get('source_job_id')==job and reference.get('transcript')==text.strip():return p
        reference['transcript']=text.strip()
        reference['transcript_review']={'source_job_id':job,'source_asset_id':asset,'source_sha256':meta['sha256'],
            'status':'caller_reviewed_not_independently_verified','reviewed_at':stamp()}
        # A changed model input requires the production script to be reviewed again.
        brief.pop('reviewed_script',None)
        return self.save(project,brief,revision)

    def export_project(self, project, format='json'):
        p=self.get(project)
        with self.core.db() as db:
            ids=[r[0] for r in db.execute('SELECT id FROM creative_jobs WHERE project=? ORDER BY rowid',(project,))]
        receipts=[self.job_get(j) for j in ids]
        p['analysis_receipts']=[j for j in receipts if j['input']['kind']=='analyze']
        p['model_receipts']=[j for j in receipts if j['input']['kind']=='refine']
        p['export_kind']='private_creative_project_draft';p['source_sha256']=digest(canonical(p['brief']).encode())
        if format=='markdown':
            from creative_analysis import production_markdown
            return {'export_kind':p['export_kind'],'format':'markdown','content':production_markdown(p),'source_sha256':p['source_sha256']}
        if format!='json':raise ValueError('creative_export_format_invalid')
        return p

    def render(self, job, data):
        self.stage(job,'prepare_render');project=data['project_id'];path,meta,kind=self.asset(project,data['asset_id']);draft=plan(data['brief']);script=draft['scripts'][int(data['variant'])]
        reviewed=data['brief'].get('reviewed_script')
        if reviewed:
            if reviewed.get('review_status')!='caller_reviewed_not_independently_verified':raise ValueError('creative_script_not_reviewed')
            script=reviewed
        folder=self.folder(project);captions=folder/(job+'.ass')
        def safe(text):return text.replace('\\','＼').replace('{','（').replace('}','）').replace('\n',' ')
        body=script['body'];lines=[script['hook'],body,script['cta']]
        max_body=100 if len(re.findall('[\u3400-\u9fff]',body))>len(body)*.2 else 320
        if len(lines[0])>100 or len(lines[1])>max_body or len(lines[2])>100:raise ValueError('creative_caption_too_long_shorten_product_facts')
        def wrap(text):return '\\N'.join(safe(text)[i:i+20] for i in range(0,len(safe(text)),20))
        chunks=[body[i:i+80] for i in range(0,len(body),80)] or ['']
        scenes=[(0,3,lines[0])]+[(3+21*i/len(chunks),3+21*(i+1)/len(chunks),s) for i,s in enumerate(chunks)]+[(24,30,lines[2])]
        def ass_time(value):
            centis=round(value*100);return f'{centis//360000}:{centis//6000%60:02}:{centis//100%60:02}.{centis%100:02}'
        events=[]
        for start,end,text in scenes:
            events.append(f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{wrap(text)}')
        captions.write_text('[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial Unicode MS,32,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,120,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'+'\n'.join(events)+'\n')
        os.chmod(captions,0o600)
        output=folder/(job+'.mp4');self.stage(job,'rendering')
        # This host's FFmpeg lacks libass/drawtext. Render original caption panels
        # locally with SVG/Pango, then overlay them; preserve editable ASS as well.
        panels=[]
        for i,(_,_,text) in enumerate(scenes):
            _,png=render_svg(self,folder,job+'-caption-'+str(i),panel_svg(text));panels.append(png)
        filters='[0:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[base]'
        previous='base'
        for i,(start,end,_) in enumerate(scenes):
            target='out' if i==len(scenes)-1 else 'panel'+str(i)
            filters+=f';[{previous}][{i+1}:v]overlay=0:0:enable=\'between(t,{start},{end})\'[{target}]';previous=target
        argv=['ffmpeg','-nostdin','-v','error','-y']+(['-loop','1'] if kind in ['product_image','generated_image'] else ['-stream_loop','-1'])+['-i',path]
        for png in panels:argv+=['-loop','1','-i',png]
        audio_source=None
        if data.get('audio_asset_id'):
            audio_path,_,_=self.asset(project,data['audio_asset_id']);argv+=['-i',audio_path];audio_source=str(len(panels)+1)+':a:0'
        elif kind=='generated_video' and meta.get('media',{}).get('has_audio'):audio_source='0:a:0'
        argv+=['-t','30','-filter_complex_threads','1','-filter_complex',filters,'-map','[out]','-r','24']
        argv+=['-map',audio_source,'-c:a','aac'] if audio_source else ['-an']
        argv+=['-c:v','libx264','-threads','2','-preset','veryfast','-crf','28','-pix_fmt','yuv420p','-movflags','+faststart',output]
        try:
            argv[0]=local_command('ffmpeg')
            r=subprocess.run([str(x) for x in argv],cwd=folder,capture_output=True,timeout=100,env=local_environment())
            if r.returncode:raise ValueError('creative_render_failed')
        except subprocess.TimeoutExpired:raise ValueError('creative_render_timeout') from None
        self.stage(job,'verify_output');media=self.probe(output)
        asset=self.register(project,'video_draft',output,{'display_name':'图文视频草稿 · '+script['angle'],'origin':'derived','parent_asset_id':data['asset_id'],'audio_parent_asset_id':data.get('audio_asset_id'),'job_id':job,'source_revision':data['revision'],'media':media,'generator':'local_ffmpeg_captioned_draft','generated_actor_in_this_job':False,'voiceover_generated_in_this_job':False,'provided_audio_used':bool(audio_source)})
        caption_asset=self.register(project,'subtitle_file',captions,{'display_name':'可编辑字幕 ASS','origin':'derived','job_id':job,'source_revision':data['revision']})
        return dict(project_revision=data['revision'],assets=[asset,caption_asset],script=script,output_kind='captioned_product_video_draft_not_live_action_ugc',missing=[],limitations=['This job does not synthesize an actor or voiceover; imported audio/visuals retain their source origin.','Automatic product-object segmentation and generative images remain external authoring steps.'])

    def image_layout(self,job,data):
        project=data['project_id'];path,meta,kind=self.asset(project,data['asset_id']);draft=plan(data['brief'])
        title=data['brief'].get('product',{}).get('name') or '商品图片'
        fact=draft['facts'][0]['text'] if draft['facts'] else '商品资料待补充'
        assets=[]
        for layout in ['product_main','usage_scene','advertisement']:
            self.stage(job,'layout_'+layout)
            svg,png=render_svg(self,self.folder(project),job+'-'+layout,layout_svg(path,title,fact,layout))
            metadata={'origin':'derived','parent_asset_id':data['asset_id'],'job_id':job,'source_revision':data['revision'],'layout':layout,'generator':'local_svg_layout','automatic_object_segmentation':False}
            assets.append(self.register(project,'image_layout_draft',png,dict(metadata,display_name=layout+' · 模板排版')))
            assets.append(self.register(project,'editable_layout',svg,dict(metadata,display_name=layout+' · 可编辑 SVG')))
        return dict(project_revision=data['revision'],assets=assets,output_kind='original_image_preserved_template_layouts',missing=[],limitations=['Original image background is retained; no automatic object segmentation or generated real scene.'])

    def refine(self,job,data):
        from creative_model import refine
        from agent_runtime.codex_provider import route
        self.stage(job,'model_rewrite')
        selected=route(self.root.parent)
        def cancelled():
            with self.core.db() as db:return bool(db.execute('SELECT cancel FROM creative_jobs WHERE id=?',(job,)).fetchone()[0])
        result=refine(data['brief'],route=selected,cancelled=cancelled) if selected['provider']=='codex' else refine(data['brief'])
        return dict(result,project_revision=data['revision'],missing=[],external_text_model_requested=True,original_media_uploaded=False)

    def approve(self,project,job,angle,revision):
        p=self.get(project);j=self.job_get(job)
        current_source={k:v for k,v in p['brief'].items() if k!='reviewed_script'}
        job_source={k:v for k,v in j['input']['brief'].items() if k!='reviewed_script'}
        if j['project_id']!=project or j['input']['kind']!='refine' or j['status']!='completed' or p['revision']!=revision or canonical(current_source)!=canonical(job_source):
            raise ValueError('creative_script_version_conflict')
        selected=next((s for s in j['result']['scripts'] if s['angle']==angle),None)
        if selected is None:raise ValueError('creative_script_not_found')
        updated=p['brief'];updated['reviewed_script']={**selected,'source_job_id':job,'generator':'configured_model','review_status':'caller_reviewed_not_independently_verified'}
        return self.save(project,updated,revision,allow_reviewed=True)

    def invoke(self, name, args):
        action=name.removeprefix('commerce_creative_')
        if action=='create':return self.create(args['brief'],args['idempotency_key'])
        if action=='list':
            with self.core.db() as db:rows=db.execute('SELECT id,brief,revision,created FROM creative_projects ORDER BY rowid DESC LIMIT 50').fetchall()
            return {'creative_studio_version':'0.2.0','projects':[dict(id=r[0],name=json.loads(r[1]).get('product',{}).get('name') or '未命名项目',revision=str(r[2]),created_at=r[3],synthetic=bool(json.loads(r[1]).get('synthetic'))) for r in rows]}
        if action=='get':return self.get(args['project_id'])
        if action=='save':return self.save(args['project_id'],args['brief'],args['revision'])
        if action=='upload_begin':return self.begin(args)
        if action=='upload_chunk':return self.chunk(args['upload_id'],args['index'],args['content_base64'])
        if action=='upload_finish':return self.finish(args['upload_id'])
        if action=='asset_read':return self.read_asset(args['project_id'],args['asset_id'],args.get('offset','0'))
        if action in ['analyze','render','image_layout','refine']:return self.start(action,args)
        if action=='approve_script':return self.approve(args['project_id'],args['job_id'],args['angle'],args['revision'])
        if action=='review_transcript':return self.review_transcript(args['project_id'],args['job_id'],args['text'],args['revision'])
        if action=='job_get':return self.job_get(args['job_id'])
        if action=='job_cancel':
            self.job_get(args['job_id'])
            with self.core.db() as db:db.execute("UPDATE creative_jobs SET cancel=1 WHERE id=? AND status IN ('queued','running')",(args['job_id'],))
            return self.job_get(args['job_id'])
        if action=='export':return self.export_project(args['project_id'],args.get('format','json'))
        raise ValueError('creative_unknown_tool')
