"""Private form recovery never executes a business action or model."""
from pathlib import Path
import tempfile,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce

class FormDrafts(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.scope={'module':'research','form':'ozon','case_id':''}
    def tearDown(self):self.tmp.cleanup()
    def call(self,method,**args):return self.app.invoke('commerce_form_draft_'+method,args,'test')
    def test_recovery_scope_and_no_implicit_execution(self):
        self.assertEqual(self.call('get',scope=self.scope)['revision'],0)
        saved=self.call('save',scope=self.scope,payload={'raw':'未完成 <script>','value':0},expected_revision=0)
        self.assertEqual(saved['revision'],1)
        fresh=Commerce(self.tmp.name).invoke('commerce_form_draft_get',{'scope':self.scope},'test')
        self.assertEqual(fresh['payload']['value'],0)
        self.assertEqual(self.call('get',scope={**self.scope,'case_id':'other'})['revision'],0)
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])
    def test_stale_save_does_not_overwrite(self):
        self.call('save',scope=self.scope,payload={'value':'first'},expected_revision=0)
        with self.assertRaisesRegex(ValueError,'form_draft_conflict'):self.call('save',scope=self.scope,payload={'value':'late'},expected_revision=0)
        self.assertEqual(self.call('get',scope=self.scope)['payload']['value'],'first')
    def test_limits_and_prototype_keys(self):
        for scope in [{**self.scope,'module':'unknown'},{**self.scope,'path':'/tmp/private'},{**self.scope,'form':'../escape'}]:
            with self.assertRaises(ValueError):self.call('get',scope=scope)
        for payload in [{'__proto__':{}},{'x':'x'*100001},{'value':float('nan')}]:
            with self.assertRaises(ValueError):self.call('save',scope=self.scope,payload=payload,expected_revision=0)
    def test_save_response_is_own_revision_even_after_interleaved_writer(self):
        from form_drafts import FormDrafts
        from unittest.mock import patch
        a=self.app.form_drafts;b=FormDrafts(self.app.core);original=a.get;interleaved=[]
        def raced(scope):
            if not interleaved:interleaved.append(True);b.save(scope,{'value':'B'},1)
            return original(scope)
        with patch.object(a,'get',side_effect=raced):saved=a.save(self.scope,{'value':'A'},0)
        if not interleaved:b.save(self.scope,{'value':'B'},1)
        self.assertEqual(saved['revision'],1);self.assertEqual(saved['payload'],{'value':'A'})
        with self.assertRaisesRegex(ValueError,'form_draft_conflict'):a.save(self.scope,{'value':'old A'},saved['revision'])

    def test_runtime_status_separates_scheduler_from_conversation(self):
        result=self.app.autonomy.status()
        self.assertEqual(result['model_executor_scope'],'scheduled_local_tasks_only')

if __name__=='__main__':unittest.main()
