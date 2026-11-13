"""Automatic host choice is an explicit model option, never a silent fallback."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce


class AutoModelCatalog(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name)
        self.thread=self.app.copilot.open({'module':'overview','demo':False},'auto-catalog')
        self.item={'id':'project-auto','label':'智能选择','engine':'builtin','provider':'host_auto',
                   'model':'按任务选择','revision':'synthetic-policy-v1','enabled':True,
                   'selectable':True,'test_status':'host_readiness'}
        self.automatic=patch.object(self.app.host_execution,'auto_profile',return_value=self.item,create=True)
        self.automatic.start()

    def tearDown(self):
        self.automatic.stop();self.app.agent_runtime.stop();self.temp.cleanup()

    def selection(self):
        with self.app.core.db() as db:return self.app.models.selection(db,self.thread['id'])

    def test_enabled_automatic_option_is_visible_and_unbound_default(self):
        self.assertEqual(self.app.models.catalog()['default_model_id'],'project-auto')
        catalog=self.app.models.catalog()['models']
        self.assertEqual(catalog[0],self.item)
        self.assertEqual(self.selection()['model_id'],'project-auto')
        self.assertEqual(self.selection()['model'],'按任务选择')
        with self.app.core.db() as db:
            snapshot=self.app.models.snapshot(db,thread_id=self.thread['id'])
        self.assertEqual(snapshot,{'provider':'host_auto','model':'auto','profile_id':'project-auto',
            'profile_revision':'synthetic-policy-v1','label':'智能选择'})
        self.assertNotEqual(self.app.models.default_snapshot()['provider'],'host_auto')

    def test_explicit_fixed_model_remains_fixed_when_auto_is_enabled(self):
        selected=self.app.models.select(self.thread['id'],'project-default','0')
        self.assertEqual(selected['model_selection']['model_id'],'project-default')
        with self.app.core.db() as db:
            self.assertNotEqual(self.app.models.snapshot(db,thread_id=self.thread['id'])['provider'],'host_auto')

    def test_explicit_local_profile_is_not_replaced_by_auto(self):
        profile=self.app.models.configure({'label':'Synthetic local','engine':'llama_cpp',
            'base_url':'http://127.0.0.1:1/v1','model':'synthetic-local'})
        with self.app.core.db() as db:
            db.execute("UPDATE model_profiles SET enabled=1,test_status='passed',tested_revision=revision WHERE id=?",(profile['id'],))
        self.app.models.select(self.thread['id'],profile['id'],'0')
        self.assertEqual(self.selection()['model_id'],profile['id'])
        with self.app.core.db() as db:
            self.assertEqual(self.app.models.snapshot(db,thread_id=self.thread['id'])['provider'],'compatible')

    def test_disabled_auto_is_unavailable_for_existing_selection_without_fallback(self):
        self.app.models.select(self.thread['id'],'project-auto','0')
        self.app.host_execution.auto_profile.return_value=None
        self.assertEqual(self.app.models.catalog()['default_model_id'],'project-default')
        self.assertEqual(self.selection()['model_id'],'project-auto')
        self.assertFalse(self.selection()['available'])
        with self.app.core.db() as db:
            with self.assertRaisesRegex(ValueError,'model_not_ready'):
                self.app.models.snapshot(db,thread_id=self.thread['id'])

    def test_changed_policy_invalidates_old_selection_pin(self):
        before=self.selection()['sha256'];self.item['revision']='synthetic-policy-v2'
        with self.app.core.db() as db:
            with self.assertRaisesRegex(ValueError,'copilot_model_changed'):
                self.app.models.snapshot(db,thread_id=self.thread['id'],expected_sha256=before)

    def test_unavailable_auto_does_not_silently_choose_fixed_model(self):
        self.item.update(enabled=False,selectable=False,test_status='invalid_configuration')
        selected=self.selection()
        self.assertEqual(selected['model_id'],'project-auto')
        self.assertFalse(selected['available'])
        with self.app.core.db() as db:
            with self.assertRaisesRegex(ValueError,'model_not_ready'):
                self.app.models.snapshot(db,thread_id=self.thread['id'])

    def test_native_task_model_conflict_preserves_existing_selection(self):
        before=self.selection()
        with patch.object(self.app.host_execution,'guard_model_selection',side_effect=ValueError('host_plan_model_conflict')) as guard:
            with self.assertRaisesRegex(ValueError,'host_plan_model_conflict'):
                self.app.models.select(self.thread['id'],'project-default','0')
        self.assertEqual(guard.call_count,1)
        self.assertEqual(self.selection(),before)
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM copilot_models').fetchone()[0],0)

    def test_actual_route_metadata_is_public_but_private_fields_stay_private(self):
        public=self.app.models.public_snapshot({'profile_id':'project-auto','provider':'host_auto',
            'host_id':'dsh','native_provider':'synthetic-native','model':'synthetic-model',
            'routing_reason':'可用的主执行端','api_key':'SYNTHETIC_PRIVATE_SENTINEL','credential_ref':'private'})
        self.assertEqual(public['host_id'],'dsh')
        self.assertEqual(public['native_provider'],'synthetic-native')
        self.assertEqual(public['routing_reason'],'可用的主执行端')
        self.assertNotIn('api_key',public);self.assertNotIn('credential_ref',public)


class LocalConversationSchema(unittest.TestCase):
    def schema_for(self,**payload):
        from model_providers.inference import invoke
        answer={'phase':'answer','answer':'2','questions':[],'evidence_refs':[],'proposals':[]}
        result={'decision':{'decision':answer},'provider':'synthetic','model':'synthetic-local'}
        with patch('model_providers.inference.invoke_json',return_value=result) as request:
            invoke({'observations':[],'tools':[],**payload},lambda:False,
                {'engine':'llama_cpp','json_mode':True,'model':'synthetic-local'})
        return request.call_args.kwargs['output_schema'],{'decision':answer}

    def test_general_conversation_can_finish_without_unnecessary_question_or_read(self):
        import jsonschema
        schema,value=self.schema_for(evidence_required=False)
        jsonschema.validate(value,schema)

    def test_business_scope_keeps_existing_evidence_boundary(self):
        import jsonschema
        for payload in ({},{'evidence_required':True}):
            schema,value=self.schema_for(**payload)
            with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(value,schema)


if __name__=='__main__':unittest.main()
