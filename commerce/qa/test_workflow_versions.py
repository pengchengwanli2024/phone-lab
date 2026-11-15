import copy,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from fixture_product_workspace import seed

class WorkflowVersionTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.cid=seed(self.app)
    def tearDown(self):self.app.agent_runtime.stop();self.tmp.cleanup()
    def test_legacy_and_graph_edits_share_immutable_typed_versions_without_task_replay(self):
        get=lambda:self.app.invoke('commerce_workflow_plan_get',{'case_id':self.cid})
        first=get();self.assertEqual(len(first.get('versions',[])),1)
        tasks=self.app.core.invoke('commerce_task_list',{})['tasks'];plan=copy.deepcopy(first['payload']);plan['goal']='Synthetic revised goal'
        second=self.app.invoke('commerce_workflow_plan_save',dict(case_id=self.cid,payload=plan,expected_revision=first['revision'],expected_source_sha256=first['source_sha256']))
        self.assertEqual(len(second['versions']),2);self.assertEqual(second['versions'][1]['payload'],first['payload'])
        self.assertTrue(all('graph'in v['payload']for v in second['versions']))
        restored=self.app.invoke('commerce_workflow_plan_save',dict(case_id=self.cid,payload=second['versions'][1]['payload'],expected_revision=second['revision'],expected_source_sha256=second['source_sha256']))
        self.assertEqual(restored['payload'],first['payload']);self.assertEqual(len(restored['versions']),3)
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],tasks)
    def test_conflict_or_invalid_dag_leaves_history_unchanged(self):
        get=lambda:self.app.invoke('commerce_workflow_plan_get',{'case_id':self.cid})
        first=get();plan=copy.deepcopy(first['payload']);ident=plan['steps'][0]['id'];plan['graph']['edges']=[{'from':ident,'to':ident}]
        args=dict(case_id=self.cid,payload=plan,expected_revision=first['revision'],expected_source_sha256=first['source_sha256'])
        with self.assertRaises(ValueError):self.app.invoke('commerce_workflow_plan_save',args)
        self.assertEqual(get(),first)
        with self.app.core.db()as db:db.execute("UPDATE org_artifacts SET sha='invalid'WHERE kind='workflow_plan_version'")
        with self.assertRaisesRegex(ValueError,'workspace_plan_version_integrity'):get()

if __name__=='__main__':unittest.main()
