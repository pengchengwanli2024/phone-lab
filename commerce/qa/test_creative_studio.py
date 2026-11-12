"""Behavior and real synthetic-media acceptance for the private creative studio."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from creative_studio import CreativeStudio, CHUNK
from creative_model import validate_draft


BRIEF={'synthetic':True,'product':{'name':'合成收纳盒','verified_facts':[{'id':'f1','text':'合成示例：容量为500毫升','evidence_ref':'synthetic:spec-1'}]},'target':{'language':'zh','country':'示例市场'},'reference':{'transcript':'这是合成参考文案，不代表真实产品体验。'}}


class CreativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.service=Commerce(self.path/'state');self.studio=self.service.creative
        self.project=self.call('create',brief=BRIEF,idempotency_key='synthetic-project')

    def tearDown(self):
        deadline=time.time()+10
        while time.time()<deadline:
            with self.service.core.db() as db:
                active=db.execute("SELECT count(*) FROM creative_jobs WHERE status IN ('queued','running')").fetchone()[0]
            if not active:break
            time.sleep(.1)
        self.tmp.cleanup()

    def call(self,action,**args):return self.service.invoke('commerce_creative_'+action,args,'test')

    def upload(self,path,kind,project=None,source_ref='synthetic:generated-fixture'):
        data=path.read_bytes();pid=project or self.project['id']
        started=self.call('upload_begin',project_id=pid,filename=path.name,kind=kind,size=str(len(data)),sha256=hashlib.sha256(data).hexdigest(),source_ref=source_ref)
        if not started['asset_id']:
            for i in range(started['next_index'],(len(data)+CHUNK-1)//CHUNK):
                self.call('upload_chunk',upload_id=started['upload_id'],index=str(i),content_base64=base64.b64encode(data[i*CHUNK:(i+1)*CHUNK]).decode())
        return self.call('upload_finish',upload_id=started['upload_id'])['asset_id']

    def wait(self,job,seconds=60):
        deadline=time.time()+seconds
        while time.time()<deadline:
            result=self.call('job_get',job_id=job['id'])
            if result['status'] not in ['queued','running']:return result
            time.sleep(.1)
        self.fail('bounded job did not finish')

    def fixture(self,name,kind):
        if not shutil.which('ffmpeg'):self.skipTest('ffmpeg unavailable')
        target=self.path/name
        argv=['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x240:rate=8']
        argv+=['-frames:v','1','-update','1',str(target)] if kind=='image' else ['-t','2','-c:v','libx264','-pix_fmt','yuv420p',str(target)]
        done=subprocess.run(argv,capture_output=True,timeout=20)
        self.assertEqual(done.returncode,0)
        return target

    def test_idempotence_and_version_conflict(self):
        self.assertEqual(self.project['id'],self.call('create',brief=BRIEF,idempotency_key='synthetic-project')['id'])
        changed={**BRIEF,'synthetic':False}
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.call('create',brief=changed,idempotency_key='synthetic-project')
        updated=self.call('save',project_id=self.project['id'],brief=changed,revision='1')
        self.assertEqual(updated['revision'],'2')
        with self.assertRaisesRegex(ValueError,'revision_conflict'):self.call('save',project_id=self.project['id'],brief=BRIEF,revision='1')

    def test_grounded_three_families_and_no_generation_claim(self):
        p=self.project['plan'];self.assertEqual(len(p['scripts']),3);self.assertEqual(len(p['image_plans']),3)
        self.assertEqual(p['video_plan']['status'],'not_rendered')
        self.assertFalse(self.project['external_generation_submitted'])
        self.assertNotIn('真实产品体验',p['scripts'][0]['body'])
        empty=self.call('create',brief={'product':{'name':'合成商品','verified_facts':[]}},idempotency_key='empty')
        self.assertEqual(empty['plan']['scripts'],[])

    def test_upload_path_checksum_and_chunk_replay(self):
        pid=self.project['id'];raw=b'not media';checksum=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(ValueError,'filename'):self.call('upload_begin',project_id=pid,filename='../escape.png',kind='product_image',size='9',sha256=checksum)
        u=self.call('upload_begin',project_id=pid,filename='sample.srt',kind='captions',size=str(len(raw)),sha256=checksum)
        args=dict(upload_id=u['upload_id'],index='0',content_base64=base64.b64encode(raw).decode())
        self.call('upload_chunk',**args);self.assertTrue(self.call('upload_chunk',**args)['duplicate'])
        with self.assertRaisesRegex(ValueError,'chunk_conflict'):self.call('upload_chunk',**{**args,'content_base64':base64.b64encode(raw[:1]).decode()})
        result=self.call('upload_finish',upload_id=u['upload_id']);self.assertEqual(result['asset_id'],self.call('upload_finish',upload_id=u['upload_id'])['asset_id'])
        other=self.call('create',brief=BRIEF,idempotency_key='other')
        with self.assertRaisesRegex(ValueError,'not_found'):self.call('asset_read',project_id=other['id'],asset_id=result['asset_id'])
        data=self.call('asset_read',project_id=pid,asset_id=result['asset_id']);self.assertEqual(base64.b64decode(data['content_base64']),raw)

    def test_hash_mismatch_and_fake_image_not_registered(self):
        raw=b'not a real png';pid=self.project['id']
        u=self.call('upload_begin',project_id=pid,filename='fake.png',kind='product_image',size=str(len(raw)),sha256='0'*64)
        self.call('upload_chunk',upload_id=u['upload_id'],index='0',content_base64=base64.b64encode(raw).decode())
        with self.assertRaisesRegex(ValueError,'hash_or_size'):self.call('upload_finish',upload_id=u['upload_id'])
        self.assertEqual(self.call('get',project_id=pid)['assets'],[])

    def test_real_synthetic_analysis(self):
        asset=self.upload(self.fixture('reference.mp4','video'),'reference_video')
        args=dict(project_id=self.project['id'],asset_id=asset,idempotency_key='analyze')
        job=self.call('analyze',**args);result=self.wait(job)
        self.assertIn(result['status'],['completed','partial'],result.get('result'));self.assertEqual(len(result['result']['keyframes']),4)
        self.assertEqual(result['result']['media']['width'],320)
        self.assertEqual(result['result']['transcript']['text'],BRIEF['reference']['transcript'])
        self.assertEqual(result['id'],self.call('analyze',**args)['id'])
        self.assertEqual(result['result']['shot_detection'],'ffmpeg_visual_difference_candidates')
        self.assertEqual(result['result']['semantic_analysis'],'not_performed')

    def test_actual_hard_cuts_and_static_no_cut(self):
        video=self.path/'three-shots.mp4'
        command=['ffmpeg','-nostdin','-v','error','-y']
        for color in ['red','blue','yellow']:command+=['-f','lavfi','-i',f'color={color}:size=128x128:rate=20:duration=1']
        command+=['-filter_complex','[0:v][1:v][2:v]concat=n=3:v=1:a=0','-c:v','libx264',str(video)]
        self.assertEqual(subprocess.run(command,capture_output=True,timeout=20).returncode,0)
        asset=self.upload(video,'reference_video');r=self.wait(self.call('analyze',project_id=self.project['id'],asset_id=asset,idempotency_key='cuts'))
        self.assertIn(r['status'],['completed','partial'],r.get('result'))
        shots=r['result']['shot_analysis'];self.assertEqual(shots['detected_cut_count'],2)
        for actual,expected in zip(shots['cuts_seconds'],[1,2]):self.assertAlmostEqual(actual,expected,delta=.11)
        self.assertEqual(len(shots['segments']),3);self.assertEqual(len(r['result']['keyframes']),3)
        self.assertEqual(shots['semantic_labels'],'not_performed')

    def test_transcript_review_cas_isolation_and_export(self):
        asset=self.upload(self.fixture('review.mp4','video'),'reference_video')
        done=self.wait(self.call('analyze',project_id=self.project['id'],asset_id=asset,idempotency_key='review'))
        text='人工校对的合成口播，仍不是商品事实。'
        args=dict(project_id=self.project['id'],job_id=done['id'],revision='1',text=text)
        other=self.call('create',brief=BRIEF,idempotency_key='different')
        with self.assertRaisesRegex(ValueError,'analysis_required'):self.call('review_transcript',**{**args,'project_id':other['id']})
        with self.assertRaisesRegex(ValueError,'text_required'):self.call('review_transcript',**{**args,'text':' '})
        updated=self.call('review_transcript',**args)
        self.assertEqual(updated['revision'],'2');self.assertEqual(updated['brief']['reference']['transcript'],text)
        self.assertEqual(updated['brief']['product'],self.project['brief']['product'])
        self.assertEqual(updated['brief']['reference']['transcript_review']['source_asset_id'],asset)
        with self.assertRaisesRegex(ValueError,'revision_conflict'):self.call('review_transcript',**args)
        self.assertEqual(self.call('review_transcript',**{**args,'revision':'2'})['revision'],'2')
        exported=self.call('export',project_id=self.project['id'])
        self.assertEqual(exported['analysis_receipts'][0]['result']['source_asset_id'],asset)
        pack=self.call('export',project_id=self.project['id'],format='markdown')
        self.assertIn(text,pack['content']);self.assertIn('商品依据',pack['content']);self.assertNotIn(str(self.path),pack['content'])
        self.assertNotIn(text,exported['plan']['scripts'][0]['body'])

    def test_cut_detection_failure_keeps_keyframes_and_clear_partial(self):
        asset=self.upload(self.fixture('fallback.mp4','video'),'reference_video')
        with patch('creative_analysis.detect_shots',side_effect=ValueError('creative_media_processing_failed')):
            result=self.wait(self.call('analyze',project_id=self.project['id'],asset_id=asset,idempotency_key='fallback'))
        self.assertEqual(result['status'],'partial');self.assertEqual(len(result['result']['keyframes']),4)
        self.assertIn('visual_cut_detection_unavailable',result['result']['missing'])

    def test_reviewed_transcript_invalidates_old_model_script(self):
        scripts=[dict(angle=a,hook='合成开头',body='容量为500毫升',cta='查看规格',fact_ids=['f1']) for a in ['detail','selection','demonstration']]
        result=validate_draft(BRIEF,{'draft':{'scripts':scripts}})
        with patch('creative_model.refine',return_value=result):
            model=self.wait(self.call('refine',project_id=self.project['id'],idempotency_key='review-model'))
        self.call('approve_script',project_id=self.project['id'],job_id=model['id'],angle='detail',revision='1')
        asset=self.upload(self.fixture('post-model.mp4','video'),'reference_video')
        done=self.wait(self.call('analyze',project_id=self.project['id'],asset_id=asset,idempotency_key='post-model'))
        updated=self.call('review_transcript',project_id=self.project['id'],job_id=done['id'],revision='2',text='新校对的合成参考口播。')
        self.assertNotIn('reviewed_script',updated['brief'])

    def test_real_synthetic_layout_and_video(self):
        if not shutil.which('rsvg-convert'):self.skipTest('rsvg-convert unavailable')
        asset=self.upload(self.fixture('product.png','image'),'product_image')
        args=dict(project_id=self.project['id'],asset_id=asset,idempotency_key='layout')
        result=self.wait(self.call('image_layout',**args));self.assertEqual(result['status'],'completed',result.get('result'))
        self.assertEqual(len(result['result']['assets']),6)
        self.assertTrue(all(x['sha256'] for x in result['result']['assets']))
        result=self.wait(self.call('render',project_id=self.project['id'],asset_id=asset,idempotency_key='render',variant='0'),100)
        self.assertEqual(result['status'],'completed',result.get('result'))
        self.assertEqual(result['result']['assets'][0]['media']['width'],720)
        self.assertAlmostEqual(result['result']['assets'][0]['media']['duration_seconds'],30,delta=.2)
        self.assertFalse(result['result']['assets'][0]['generated_actor_in_this_job'])

    def test_uploaded_audio_is_used_in_video(self):
        if not shutil.which('rsvg-convert'):self.skipTest('rsvg-convert unavailable')
        asset=self.upload(self.fixture('audio-product.png','image'),'product_image')
        sound=self.path/'synthetic-tone.wav';r=subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','2',str(sound)],capture_output=True,timeout=15);self.assertEqual(r.returncode,0)
        audio=self.upload(sound,'audio');result=self.wait(self.call('render',project_id=self.project['id'],asset_id=asset,audio_asset_id=audio,idempotency_key='with-audio'),100)
        self.assertEqual(result['status'],'completed',result.get('result'));out=result['result']['assets'][0]
        self.assertTrue(out['media']['has_audio']);self.assertTrue(out['provided_audio_used']);self.assertEqual(out['audio_parent_asset_id'],audio)

    def test_cancel_checkpoint_and_interruption_receipt(self):
        asset=self.upload(self.fixture('cancel.mp4','video'),'reference_video')
        entered=threading.Event();release=threading.Event()
        def blocked(job,data):
            entered.set();release.wait(3);self.studio.stage(job,'cancel_checkpoint');return {'missing':[]}
        with patch.object(self.studio,'analyze',side_effect=blocked):
            job=self.call('analyze',project_id=self.project['id'],asset_id=asset,idempotency_key='cancel')
            self.assertTrue(entered.wait(2));self.call('job_cancel',job_id=job['id']);release.set()
            result=self.wait(job);self.assertEqual(result['status'],'cancelled')
        with self.service.core.db() as db:db.execute("UPDATE creative_jobs SET status='running' WHERE id=?",(job['id'],))
        CreativeStudio(self.service.core,self.path/'state')
        self.assertEqual(self.call('job_get',job_id=job['id'])['status'],'interrupted')

    def test_model_citations_review_and_revision(self):
        scripts=[dict(angle=a,hook='合成开头',body='容量为500毫升',cta='查看规格',fact_ids=['f1']) for a in ['detail','selection','demonstration']]
        result=validate_draft(BRIEF,{'draft':{'scripts':scripts},'provider':'synthetic','model':'synthetic'})
        self.assertEqual(result['review_status'],'pending_review')
        invalid=json.loads(json.dumps(scripts));invalid[0]['fact_ids']=['unknown']
        with self.assertRaisesRegex(ValueError,'unknown_fact'):validate_draft(BRIEF,{'draft':{'scripts':invalid}})
        scripts[0]['body']='容量为999毫升'
        self.assertIn('new_numbers_not_in_product_facts',validate_draft(BRIEF,{'draft':{'scripts':scripts}})['scripts'][0]['warnings'])
        with patch('creative_model.refine',return_value=result):
            job=self.call('refine',project_id=self.project['id'],idempotency_key='synthetic-model')
            done=self.wait(job)
        self.assertEqual(done['status'],'completed')
        approved=self.call('approve_script',project_id=self.project['id'],job_id=job['id'],angle='detail',revision='1')
        self.assertEqual(approved['brief']['reviewed_script']['source_job_id'],job['id'])
        second=self.call('approve_script',project_id=self.project['id'],job_id=job['id'],angle='selection',revision=approved['revision'])
        changed=json.loads(json.dumps(BRIEF));changed['product']['verified_facts'][0]['text']='已改变的合成资料'
        self.call('save',project_id=self.project['id'],brief=changed,revision=second['revision'])
        with self.assertRaisesRegex(ValueError,'version_conflict'):self.call('approve_script',project_id=self.project['id'],job_id=job['id'],angle='detail',revision='4')

    def test_model_timeout_preserves_unknown(self):
        with patch('creative_model.refine',side_effect=ValueError('creative_model_outcome_unknown_no_automatic_resubmit')):
            args=dict(project_id=self.project['id'],idempotency_key='synthetic-model-timeout')
            job=self.call('refine',**args);result=self.wait(job)
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(self.call('refine',**args)['id'],job['id'])
        with self.service.core.db() as db:db.execute("UPDATE creative_jobs SET status='running' WHERE id=?",(job['id'],))
        CreativeStudio(self.service.core,self.path/'state')
        self.assertEqual(self.call('job_get',job_id=job['id'])['status'],'unknown')

    def test_one_frame_reference_samples_do_not_fail_at_end(self):
        if not shutil.which('ffmpeg'):self.skipTest('ffmpeg unavailable')
        target=self.path/'one-frame.mp4'
        r=subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=blue:size=64x64:rate=1','-t','1','-c:v','libx264',str(target)],capture_output=True,timeout=15)
        self.assertEqual(r.returncode,0)
        asset=self.upload(target,'reference_video');result=self.wait(self.call('analyze',project_id=self.project['id'],asset_id=asset,idempotency_key='one-frame'))
        self.assertIn(result['status'],['completed','partial'],result.get('result'));self.assertEqual(len(result['result']['keyframes']),4)

    def test_public_speech_sample_with_synthetic_video_local_asr(self):
        from creative_asr import available
        speech=Path(__file__).resolve().parents[2]/'.local/creative-acceptance/public-asr-sample.wav'
        if not available() or not speech.is_file():self.skipTest('local ASR sample/cache not provisioned')
        p=self.call('create',brief={**BRIEF,'reference':{}},idempotency_key='public-asr-test')
        video=self.path/'public-speech-with-synthetic-video.mp4'
        r=subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x120:rate=4','-i',str(speech),'-shortest','-c:v','libx264','-c:a','aac',str(video)],capture_output=True,timeout=20)
        self.assertEqual(r.returncode,0)
        asset=self.upload(video,'reference_video',p['id'],source_ref='public:whisper_cpp_sample_plus_synthetic_video')
        result=self.wait(self.call('analyze',project_id=p['id'],asset_id=asset,idempotency_key='public-asr-analysis'),100)
        self.assertIn(result['status'],['completed','partial'],result.get('result'))
        transcript=result['result']['transcript'];self.assertEqual(transcript['source'],'local_whisper_tiny');self.assertTrue(transcript['text'].strip());self.assertEqual(transcript['review_status'],'machine_generated_pending_review')

    def test_media_commands_work_with_minimal_service_path(self):
        image=self.fixture('minimal-path.png','image')
        with patch.dict(os.environ,{'PATH':'/usr/bin:/bin'}):
            media=self.studio.probe(image)
            self.assertEqual(media['width'],320)
            from creative_tools import command
            self.assertTrue(Path(command('ffprobe')).is_absolute())


if __name__=='__main__':unittest.main()
