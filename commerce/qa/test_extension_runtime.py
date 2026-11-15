"""Real SQLite runtime behavior; no live model, cloud, or business writes."""
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from commerce_core import Core

class Service:
    def __init__(self,path):
        self.state=Path(path);self.core=Core(self.state/'test.sqlite');self.calls=[]
    def invoke(self,name,args,client='local'):
        self.calls.append((name,args))
        if name=='commerce_runtime_status':return {'mode':'unconfigured','source':'local'}
        if name=='commerce_unit_economics':return {'total':args['input']['price']*2}
        if name=='commerce_organization_board':return {'case_id':args['case_id'],'observed':True}
        raise ValueError('unexpected_test_tool')

class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('extension_runtime').loader,'extension runtime missing')
        from extension_runtime import ExtensionRuntime
        self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name);self.app=ExtensionRuntime(self.service)
    def tearDown(self):self.app.stop();self.temp.cleanup()
    def call(self,op,**args):return self.app.invoke('commerce_extension_'+op,args)
    def save(self,name='Read',**extra):
        value={'kind':'skill','name':name,'spec':{'steps':[{'id':'read','uses':{'builtin':'commerce_runtime_status'}}],'output':{'$ref':'steps.read'}},**extra}
        return self.call('save',definition=value)
    def drain(self,run):
        end=time.monotonic()+3
        while time.monotonic()<end:
            self.app.tick();value=self.call('run_get',run_id=run['id'])
            if value['status'] not in ('queued','running'):return value
            time.sleep(.01)
        self.fail('runtime did not settle')
    def ready(self,**extra):
        test_input=extra.pop('test_input',{});ext=self.save(**extra);test=self.call('test',extension_id=ext['id'],input=test_input,idempotency_key='test-'+ext['id']);self.assertEqual(self.drain(test)['status'],'succeeded')
        return self.call('enable',extension_id=ext['id'],expected_version=ext['version'],enabled=True)
class Runtime(RuntimeCase):
    def test_versioned_test_enable_run_and_core_task_identity(self):
        ext=self.ready();run=self.call('run',extension_id=ext['id'],idempotency_key='one');self.assertEqual(run['status'],'queued')
        result=self.drain(run);self.assertEqual(result['status'],'succeeded');self.assertEqual(result['output']['mode'],'unconfigured')
        self.assertEqual(self.service.core.invoke('commerce_task_get',{'task_id':result['task_id']})['status'],'completed')
        same=self.call('run',extension_id=ext['id'],idempotency_key='one');self.assertEqual(same['id'],run['id'])
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.call('run',extension_id=ext['id'],input={'changed':True},idempotency_key='one')
    def test_edit_preserves_versions_and_invalidates_enable_and_test(self):
        ext=self.ready();new=self.call('save',definition={**ext['definition'],'name':'Changed'},expected_version=ext['version'])
        self.assertEqual(new['version'],2);self.assertFalse(new['enabled']);self.assertEqual(self.call('get',extension_id=ext['id'],version=1)['definition']['name'],'Read')
        with self.assertRaisesRegex(ValueError,'not_tested'):self.call('enable',extension_id=ext['id'],expected_version=2,enabled=True)
        rolled=self.call('rollback',extension_id=ext['id'],expected_version=2,target_version=1);self.assertEqual(rolled['version'],3)
    def test_import_tracks_provenance_and_rejects_executable_or_secret_config(self):
        doc={'kind':'plugin','name':'Imported','spec':{'transport':'builtin','tool':'commerce_runtime_status','effect':'read'}}
        ext=self.call('import',document=json.dumps(doc),provenance={'source':'user_json','label':'Synthetic fixture'})
        self.assertEqual(ext['provenance']['source'],'user_json')
        for key,value in [('command','touch /tmp/x'),('api_key','never-store-me')]:
            with self.assertRaises(ValueError):self.call('save',definition={**doc,'spec':{**doc['spec'],key:value}})
    def test_arbitrary_builtin_and_cross_case_reads_rejected(self):
        with self.assertRaisesRegex(ValueError,'builtin_not_allowed'):self.save(spec={'steps':[{'id':'x','uses':{'builtin':'commerce_task_create'}}]})
        ext=self.save(spec={'steps':[{'id':'x','uses':{'builtin':'commerce_organization_board'},'input':{'case_id':'other'}}]})
        test=self.call('test',extension_id=ext['id'],scope={'case_id':'mine'},idempotency_key='scope')
        self.assertEqual(self.drain(test)['error'],'extension_scope_mismatch');self.assertEqual(self.service.calls,[])
    def test_mapping_conditions_and_schema_rejection(self):
        ext=self.ready(input_schema={'type':'object','properties':{'price':{'type':'number','minimum':1}},'required':['price'],'additionalProperties':False},spec={'steps':[{'id':'calc','uses':{'builtin':'commerce_unit_economics'},'input':{'input':{'price':{'$ref':'input.price'}}},'when':{'op':'gt','left':{'$ref':'input.price'},'right':2}}],'output':{'$ref':'steps.calc'}},test_input={'price':3})
        run=self.call('run',extension_id=ext['id'],input={'price':4},idempotency_key='mapping');self.assertEqual(self.drain(run)['output'],{'total':8})
        with self.assertRaisesRegex(ValueError,'schema'):self.call('run',extension_id=ext['id'],input={'price':0},idempotency_key='bad')
    def test_dependency_is_pinned_and_edits_revoke_existing_run(self):
        dep=self.ready();root=self.ready(name='Parent',spec={'steps':[{'id':'child','uses':{'extension_id':dep['id']}}],'output':{'$ref':'steps.child'}})
        run=self.call('run',extension_id=root['id'],idempotency_key='pin')
        self.call('save',definition={**dep['definition'],'name':'Changed dependency'},expected_version=1)
        result=self.drain(run);self.assertEqual(result['status'],'cancelled');self.assertEqual(result['error'],'extension_definition_revoked')
    def test_budget_is_reserved_before_work(self):
        ext=self.ready(spec={'steps':[{'id':'a','uses':{'builtin':'commerce_runtime_status'}},{'id':'b','uses':{'builtin':'commerce_runtime_status'}}]})
        self.service.calls.clear();run=self.call('run',extension_id=ext['id'],budget={'max_steps':1},idempotency_key='budget')
        result=self.drain(run);self.assertEqual(result['status'],'failed');self.assertEqual(result['error'],'extension_budget_exhausted');self.assertEqual(len(self.service.calls),1)
    def test_cancel_does_not_execute_queued_run(self):
        ext=self.ready();self.service.calls.clear();run=self.call('run',extension_id=ext['id'],idempotency_key='cancel')
        self.call('run_cancel',run_id=run['id']);self.app.tick();self.assertEqual(self.call('run_get',run_id=run['id'])['status'],'cancelled');self.assertEqual(self.service.calls,[])
    def test_interval_is_durable_deduplicated_and_nonblocking(self):
        ext=self.ready();schedule=self.call('schedule_save',schedule={'extension_id':ext['id'],'trigger':'interval','interval_seconds':60,'input':{},'scope':{}})
        self.call('schedule_enable',schedule_id=schedule['id'],expected_revision=schedule['revision'],enabled=True)
        self.app.tick(at=1000);self.app.tick(at=1000)
        runs=self.call('run_list',extension_id=ext['id'])['runs'];self.assertEqual(sum(r.get('schedule_id')==schedule['id'] for r in runs),1)
    def test_recover_marks_inflight_write_unknown_and_never_replays(self):
        ext=self.ready();run=self.call('run',extension_id=ext['id'],idempotency_key='crash')
        with self.service.core.db() as db:
            doc=json.loads(db.execute('SELECT document FROM extension_runs WHERE id=?',(run['id'],)).fetchone()[0]);doc['status']='running';doc['inflight']={'effect':'external_write','step_id':'x'}
            db.execute('UPDATE extension_runs SET status=?,document=? WHERE id=?',('running',json.dumps(doc),run['id']))
        self.app.recover();result=self.call('run_get',run_id=run['id']);self.assertEqual(result['status'],'unknown')
        with self.assertRaisesRegex(ValueError,'cannot_resume'):self.call('run_resume',run_id=run['id'])


class RecoverySafety(RuntimeCase):
    def test_aggregate_output_budget_fails_without_stranding_running_task(self):
        ext=self.ready(spec={'steps':[{'id':'a','uses':{'builtin':'commerce_runtime_status'}},{'id':'b','uses':{'builtin':'commerce_runtime_status'}},{'id':'c','uses':{'builtin':'commerce_runtime_status'}}]})
        run=self.call('run',extension_id=ext['id'],budget={'max_output_bytes':80},idempotency_key='output-budget');result=self.drain(run)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error'],'extension_output_budget_exhausted')
    def test_recovery_resumes_only_safe_checkpoint_without_repeating_read(self):
        ext=self.ready(spec={'steps':[{'id':'a','uses':{'builtin':'commerce_runtime_status'}},{'id':'b','uses':{'builtin':'commerce_runtime_status'}}]})
        run=self.call('run',extension_id=ext['id'],idempotency_key='resume');self.service.calls.clear();self.app._process(run['id'])
        self.assertEqual(len(self.service.calls),1)
        with self.service.core.db() as db:
            doc=json.loads(db.execute('SELECT document FROM extension_runs WHERE id=?',(run['id'],)).fetchone()[0]);doc['status']='running'
            db.execute('UPDATE extension_runs SET status=?,document=? WHERE id=?',('running',json.dumps(doc),run['id']))
        self.app.recover();self.call('run_resume',run_id=run['id']);result=self.drain(run)
        self.assertEqual(result['status'],'succeeded');self.assertEqual(len(self.service.calls),2)
    def test_schedule_preserves_readable_name(self):
        ext=self.ready();value=self.call('schedule_save',schedule={'extension_id':ext['id'],'trigger':'manual','name':'Read local status'})
        self.assertEqual(value['name'],'Read local status')
    def test_shared_task_cancel_stops_extension_before_dispatch(self):
        ext=self.ready();run=self.call('run',extension_id=ext['id'],idempotency_key='shared-cancel');self.service.calls.clear()
        self.service.core.invoke('commerce_task_cancel',{'task_id':run['task_id']});result=self.drain(run)
        self.assertEqual(result['status'],'cancelled');self.assertEqual(self.service.calls,[])
    def test_non_tool_alias_cannot_bypass_public_contract(self):
        with self.assertRaises(ValueError):self.app.invoke('save',{'definition':{'kind':'plugin','name':'Bypass','spec':{'transport':'builtin','tool':'commerce_runtime_status','effect':'read'}}})

if __name__=='__main__':unittest.main()
