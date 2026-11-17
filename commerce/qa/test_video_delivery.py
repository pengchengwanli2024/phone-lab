"""Versioned edits and actual local MP4/subtitle/cover delivery, synthetic only."""
from copy import deepcopy
from pathlib import Path
import json,sys,time,unittest,zipfile,subprocess,threading
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_product_media as fixtures

class VideoDelivery(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.ProductMediaTests();self.fixture.setUp();self.app=self.fixture.app;self.p=self.fixture.direction();self.pid=self.p['id']
  self.original=self.app.media.request_create(self.pid,self.p['revision'],'showcase_video','original')
 def tearDown(self):self.app.autonomy.stop();self.fixture.tearDown()
 def editing(self):return {'aspect_ratio':'16:9','keep_source_audio':True,'shots':[{'source_index':i,'source_start_ms':0,'duration_ms':500,'caption':'合成验收镜头 '+str(i+1)}for i in range(5)]}
 def edit(self,key='edit'):
  return self.app.invoke('commerce_media_request_edit',{'request_id':self.original['id'],'expected_request_sha256':self.original['request_sha256'],'editing':self.editing(),'idempotency_key':key})
 def test_edits_create_replayable_new_version_without_changing_original(self):
  r=self.edit();self.assertNotEqual(r['id'],self.original['id']);self.assertEqual(r['spec']['duration_ms'],2500);self.assertEqual(r['spec']['width'],1280)
  self.assertEqual(self.edit()['id'],r['id']);self.assertEqual(self.app.media.request_get(self.original['id'])['request_sha256'],self.original['request_sha256'])
  bad=self.editing();bad['shots'][0]['duration_ms']=-1
  with self.assertRaises(ValueError):self.app.invoke('commerce_media_request_edit',{'request_id':self.original['id'],'expected_request_sha256':self.original['request_sha256'],'editing':bad,'idempotency_key':'bad'})
 def test_actual_render_produces_video_cover_subtitles_and_verified_package(self):
  r=self.edit();out=self.app.media.request_execute(r['id'],self.p['revision'],[self.fixture.asset['id']]*5)
  deadline=time.monotonic()+90
  while time.monotonic()<deadline:
   out=self.app.media.request_get(r['id'])
   if out['status']not in ('queued','running'):break
   time.sleep(.1)
  self.assertEqual(out['status'],'awaiting_review',out)
  self.assertEqual(out['quality_report']['technical_status'],'passed')
  self.assertTrue(out['quality_report']['checks']['decode'])
  self.assertTrue(out['quality_report']['human_review_required'])
  self.assertIsNone(out['quality_report']['semantic_motion_verified'])
  media=self.app.creative.asset(self.pid,out['assets'][0]['id'])[1]['media']
  self.assertEqual((media['width'],media['height']),(1280,720));self.assertAlmostEqual(media['duration_seconds'],2.5,delta=.15)
  delivery=out['delivery_assets'];self.assertTrue({'video_cover','captions','production_manifest','delivery_package'}<={a['kind']for a in delivery})
  package=next(a for a in delivery if a['kind']=='delivery_package');path,_,_=self.app.creative.asset(self.pid,package['id'])
  with zipfile.ZipFile(path)as z:
   self.assertEqual(set(z.namelist()),{'video.mp4','cover.png','captions.srt','manifest.json','quality-report.json','review-frames.png','review-frames.json'});manifest=json.loads(z.read('manifest.json'))
   quality=json.loads(z.read('quality-report.json'));self.assertEqual(quality['video_sha256'],manifest['video_sha256']);self.assertEqual(quality,out['quality_report'])
   self.assertEqual(manifest['production_request_id'],r['id']);self.assertFalse(manifest['publication_executed']);self.assertEqual(len(manifest['shots']),5)
 def test_imported_video_trim_preserves_audio_and_rejects_out_of_range(self):
  source=Path(self.fixture.tmp.name)/'synthetic-footage.mp4'
  subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=c=blue:s=320x240:r=24','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
  a=self.app.creative.register(self.pid,'product_video',source,{'source_ref':'synthetic:footage','media':self.app.creative.probe(source)})
  editing=self.editing()
  for shot in editing['shots']:shot.update(source_start_ms=500,caption='')
  r=self.app.media.request_edit(request_id=self.original['id'],expected_request_sha256=self.original['request_sha256'],editing=editing,idempotency_key='actual-audio')
  self.app.media.request_execute(r['id'],self.p['revision'],[a['id']]*5)
  for _ in range(200):
   out=self.app.media.request_get(r['id'])
   if out['status']not in ('queued','running'):break
   time.sleep(.05)
  self.assertEqual(out['status'],'awaiting_review',out);self.assertTrue(self.app.creative.asset(self.pid,out['assets'][0]['id'])[1]['media']['has_audio'])
  subtitle=next(x for x in out['delivery_assets']if x['kind']=='captions');self.assertEqual(self.app.creative.asset(self.pid,subtitle['id'])[0].read_text(),'')
  editing['shots'][0]['source_start_ms']=2000
  bad=self.app.media.request_edit(request_id=self.original['id'],expected_request_sha256=self.original['request_sha256'],editing=editing,idempotency_key='outside')
  with self.assertRaisesRegex(ValueError,'creative_clip_range_exceeded'):
   self.app.media.request_execute(bad['id'],self.p['revision'],[a['id']]*5)
  self.assertIsNone(self.app.media.request_get(bad['id'])['job_id'])
 def test_metrics_cannot_claim_an_unproduced_media_version(self):
  with self.assertRaisesRegex(ValueError,'creative_metrics_media_not_produced'):
   self.app.media.performance_save(self.pid,{'period_start':'2026-11-01T00:00:00Z','period_end':'2026-11-02T00:00:00Z','source_ref':'synthetic:report','request_id':self.original['id'],'impressions':1000},'unproduced')

 def test_manual_result_does_not_inherit_another_files_local_report_or_package(self):
  source=Path(self.fixture.tmp.name)/'manual-result.mp4'
  subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=c=red:s=160x120:r=24','-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True)
  manual=self.app.creative.register(self.pid,'generated_video',source,{'source_ref':'synthetic:manual','media':self.app.creative.probe(source)})
  entered=threading.Event();release=threading.Event();render=self.app.creative.story_render
  def paused(*args):
   entered.set();release.wait(10);return render(*args)
  r=self.edit('manual-result')
  try:
   with patch.object(self.app.creative,'story_render',side_effect=paused):
    self.app.media.request_execute(r['id'],self.p['revision'],[self.fixture.asset['id']]*5)
    self.assertTrue(entered.wait(3))
    self.app.media.request_attach(r['id'],self.p['revision'],[manual['id']])
    release.set()
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
     out=self.app.media.request_get(r['id'])
     if out['job_status']not in ('queued','running'):break
     time.sleep(.05)
    self.assertEqual(out['job_status'],'completed',out)
    self.assertEqual(out['assets'][0]['sha256'],manual['sha256'])
    self.assertIsNone(out['quality_report']);self.assertEqual(out['delivery_assets'],[])
  finally:release.set()

if __name__=='__main__':unittest.main()
