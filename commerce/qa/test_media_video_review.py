"""Operator-reviewed video plans, isolated from real plugins and daily state."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_media_plugin_connections as fixtures


class VideoReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PluginConnections();self.fixture.setUp();self.app=self.fixture.app
        self.app.media_plugins=self.fixture.plugins
        self.fixture.bind('heygen',connection_status='available_to_host')
        self.request=self.fixture.fixture.request('ugc_video');self.project=self.app.creative.get(self.request['project_id'])
        self.plan=self.app.media_plugins.prepare(self.request['id'],self.project['revision'],'heygen',[self.fixture.fixture.asset['id']],1,'video')
        self.content={'presenter_mode':'fictional_adult','presenter_description':'虚构成年厨房用品讲解员，普通居家服装',
            'use_scene':'厨房水槽旁的日常收纳场景','speech_mode':'voiceover','script_text':'查看产品规格和细节，按实际用途使用。',
            'shots':[{'index':i,'framing':s['framing'],'action':s['action']} for i,s in enumerate(self.request['spec']['shots'])],
            'claims_confirmed':True}

    def tearDown(self):self.fixture.tearDown()

    def review(self,**changes):
        self.assertTrue(callable(getattr(self.app.media_plugins,'review_video',None)),'Video content review must be reachable before execution approval')
        args={'plan_id':self.plan['id'],'expected_plan_sha256':self.plan['plan_sha256'],'content':self.content,'idempotency_key':'review',**changes}
        return self.app.invoke('commerce_media_plugin_plan_review_video',args)

    def test_review_creates_immutable_hashed_plan_and_can_reach_final_approval(self):
        reviewed=self.review()
        self.assertNotEqual(reviewed['id'],self.plan['id']);self.assertNotEqual(reviewed['plan_sha256'],self.plan['plan_sha256'])
        self.assertEqual(reviewed['source_plan_id'],self.plan['id']);self.assertEqual(reviewed['blockers'],[])
        self.assertIn('person_script_storyboard_approval_required',self.app.media_plugins.get(self.plan['id'])['blockers'])
        self.assertFalse(reviewed['external_generation_submitted']);self.assertTrue(reviewed['video_review']['operator_reviewed'])
        self.assertIn(self.content['script_text'],reviewed['tool_call']['arguments']['prompt'])
        self.assertIn(self.content['use_scene'],reviewed['tool_call']['arguments']['prompt'])
        self.assertEqual(reviewed['sources'],self.plan['sources'])
        self.assertTrue(self.app.media_plugins.validate(reviewed['id'],reviewed['plan_sha256'])['current'])
        x=self.app.media_plugin_execution.start(reviewed['id'],reviewed['plan_sha256'],'reviewed-execution')
        self.assertEqual(x['status'],'awaiting_approval')
        x=self.app.media_plugin_execution.approve(x['id'],reviewed['plan_sha256'],'approve')
        self.assertEqual(x['status'],'awaiting_host');self.assertFalse(x['external_generation_submitted'])

    def test_review_is_idempotent_but_changed_content_conflicts(self):
        one=self.review();self.assertEqual(one['id'],self.review()['id'])
        changed=deepcopy(self.content);changed['script_text']='另一版需要重新确认的台词。'
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.review(content=changed)
        revised=self.review(content=changed,idempotency_key='review-2')
        self.assertNotEqual(revised['plan_sha256'],one['plan_sha256'])

    def test_reauthentication_remains_blocked_after_content_review(self):
        self.fixture.bind('heygen',expected_revision=1,connection_status='needs_reauthentication')
        self.plan=self.app.media_plugins.prepare(self.request['id'],self.project['revision'],'heygen',[self.fixture.fixture.asset['id']],2,'reauth')
        reviewed=self.review();self.assertEqual(reviewed['blockers'],['needs_reauthentication'])
        with self.assertRaisesRegex(ValueError,'connection_requires_attention'):self.app.media_plugins.validate(reviewed['id'],reviewed['plan_sha256'])

    def test_missing_scene_unconfirmed_claims_or_incomplete_shots_are_rejected(self):
        for changes in ({'use_scene':''},{'claims_confirmed':False},{'shots':self.content['shots'][:-1]},
                        {'presenter_mode':'real_person_clone'},{'speech_mode':'none'},
                        {'shots':[self.content['shots'][0]]*5},{'presenter_description':''}):
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'media_video_review_'):
                self.review(content={**self.content,**changes})

    def test_faceless_silent_showcase_is_explicit_and_does_not_keep_old_narration(self):
        content={**self.content,'presenter_mode':'faceless','presenter_description':'','speech_mode':'none','script_text':''}
        reviewed=self.review(content=content)
        prompt=reviewed['tool_call']['arguments']['prompt'];self.assertIn('不出现人物',prompt);self.assertIn('不生成口播',prompt)
        self.assertNotIn('目标：自然的人物表达',prompt)
        old=self.request['spec']['script'];self.assertNotIn('制作文案：'+old['hook']+' '+old['body']+' '+old['cta'],prompt)

    def test_shot_review_requires_only_the_selected_scope_and_uses_actual_times(self):
        self.plan=self.app.media_plugins.prepare(self.request['id'],self.project['revision'],'heygen',[self.fixture.fixture.asset['id']],1,'shot',shot_index=1)
        content={**self.content,'shots':[self.content['shots'][1]]}
        reviewed=self.review(content=content);self.assertEqual(reviewed['tool_call']['arguments']['duration'],6)
        self.assertEqual(reviewed['video_review']['content']['shots'][0]['start_ms'],4000)
        with self.assertRaisesRegex(ValueError,'media_video_review_'):self.review()

    def test_source_or_account_changes_cannot_be_reviewed_under_old_hash(self):
        self.fixture.bind('heygen',expected_revision=1,connection_status='available_to_host')
        with self.assertRaisesRegex(ValueError,'connection_changed'):self.review()

    def test_reviewed_content_edit_requires_a_new_execution_approval(self):
        first=self.review();old=self.app.media_plugin_execution.start(first['id'],first['plan_sha256'],'first')
        self.app.media_plugin_execution.approve(old['id'],first['plan_sha256'],'approve')
        self.plan=first;content={**self.content,'use_scene':'另一个经核对的收纳台面场景'}
        second=self.review(content=content,idempotency_key='second')
        new=self.app.media_plugin_execution.start(second['id'],second['plan_sha256'],'second')
        self.assertEqual(new['status'],'awaiting_approval')
        self.assertEqual(self.app.media_plugin_execution.get(old['id'])['plan_sha256'],first['plan_sha256'])
        self.assertNotIn('claim_token',json.dumps(second))

    def test_multiline_draft_dialogue_is_fully_replaced_and_shot_time_starts_at_zero(self):
        from media_video_review import _prompt,validate
        plan=deepcopy(self.plan);spec=plan['source_request']['spec']
        old=spec['script'];previous='制作文案：'+old['hook']+' '+old['body']+' '+old['cta']
        spec['script']={'hook':'旧的开头','body':'旧的第一段\n旧的第二段','cta':'旧的收尾'}
        spec['prompt']=spec['prompt'].replace(previous,'制作文案：旧的开头 旧的第一段\n旧的第二段 旧的收尾')
        plan['shot_index']=1;content={**self.content,'shots':[self.content['shots'][1]]}
        prompt=_prompt(plan,validate(content,plan))
        self.assertNotIn('旧的第二段',prompt)
        self.assertIn('"start_ms":0',prompt);self.assertIn('"end_ms":6000',prompt)


if __name__=='__main__':unittest.main()
