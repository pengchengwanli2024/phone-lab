"""Single-call deadlines stop cooperative work and preserve ambiguous receipts."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_extension_runtime import RuntimeCase
from test_extension_runtime_agents import Models

class Deadlines(RuntimeCase):
    def previous_usage(self,run,seconds):
        with self.service.core.db() as db:
            value=self.app._load(db,run['id']);value['usage']['seconds']=seconds;self.app._store(db,value)
    def test_blocking_model_observes_remaining_budget_in_cancel_callback(self):
        self.service.models=Models();ext=self.ready(kind='agent',spec={'instructions':'Synthetic only.','tools':[]})
        run=self.call('run',extension_id=ext['id'],budget={'allow_model_calls':True,'max_seconds':1},idempotency_key='blocking-model');self.previous_usage(run,.8)
        def blocking(payload,cancelled,*args):
            end=time.monotonic()+1.2
            while time.monotonic()<end:
                if cancelled():raise ValueError('agent_model_cancelled')
                time.sleep(.005)
            return {'action':'finish','output':{'late':True}}
        started=time.monotonic()
        with patch.object(self.app,'_model',side_effect=blocking):result=self.drain(run)
        self.assertLess(time.monotonic()-started,.8);self.assertEqual(result['status'],'unknown');self.assertEqual(result['error'],'extension_budget_exhausted');self.assertGreaterEqual(result['usage']['seconds'],1)
        with self.assertRaisesRegex(ValueError,'cannot_resume'):self.call('run_resume',run_id=run['id'])
    def write_plugin(self):
        return self.ready(kind='plugin',spec={'transport':'http','tool':'synthetic_write','endpoint':'http://127.0.0.1:1/write','effect':'external_write'})
    def approved_write(self,ext,key):
        run=self.call('run',extension_id=ext['id'],input={'operation':'synthetic'},budget={'max_seconds':1},idempotency_key=key);pending=self.drain(run);a=pending['approval']
        self.call('run_approve',run_id=run['id'],step_id=a['step_id'],input_sha256=a['input_sha256'],decision='approve');self.previous_usage(run,.8)
        return run
    def test_late_external_write_keeps_real_receipt_unknown_and_cannot_replay(self):
        ext=self.write_plugin();run=self.approved_write(ext,'late-write')
        def late(*args):time.sleep(.25);return {'receipt':'synthetic-confirmation','accepted':True}
        with patch('extension_runtime.transport.invoke',side_effect=late) as transport:result=self.drain(run)
        self.assertEqual(result['status'],'unknown');self.assertEqual(result['error'],'extension_budget_exhausted');self.assertEqual(result['steps'][0]['output']['receipt'],'synthetic-confirmation');self.assertEqual(transport.call_count,1)
        with self.assertRaisesRegex(ValueError,'cannot_resume'):self.call('run_resume',run_id=run['id'])
        self.app.tick();self.assertEqual(self.call('run_get',run_id=run['id'])['status'],'unknown')
        with self.service.core.db() as db:
            stored=self.app._load(db,run['id']);self.assertTrue(stored['inflight']['receipt_received']);self.assertIn('input_sha256',stored['inflight'])
    def test_blocking_external_write_observes_budget_and_keeps_dispatch_evidence(self):
        ext=self.write_plugin();run=self.approved_write(ext,'blocking-write')
        def blocking(spec,args,headers,cancelled):
            end=time.monotonic()+1.2
            while time.monotonic()<end:
                if cancelled():
                    from extension_runtime.transport import OutcomeUnknown
                    raise OutcomeUnknown('extension_external_outcome_unknown')
                time.sleep(.005)
            return {'receipt':'too-late'}
        started=time.monotonic()
        with patch('extension_runtime.transport.invoke',side_effect=blocking):result=self.drain(run)
        self.assertLess(time.monotonic()-started,.8);self.assertEqual(result['status'],'unknown');self.assertEqual(result['error'],'extension_budget_exhausted')
        with self.service.core.db() as db:self.assertIn('input_sha256',self.app._load(db,run['id'])['inflight'])
    def test_late_read_keeps_observed_result_but_does_not_report_budget_success(self):
        ext=self.ready();run=self.call('run',extension_id=ext['id'],budget={'max_seconds':1},idempotency_key='late-read');self.previous_usage(run,.8)
        def late(*args):time.sleep(.25);return {'observed':'synthetic-read'}
        with patch.object(self.service,'invoke',side_effect=late):result=self.drain(run)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error'],'extension_budget_exhausted');self.assertEqual(result['steps'][0]['output'],{'observed':'synthetic-read'})

if __name__=='__main__':unittest.main()
