"""Local readiness must not expose private metadata or restart a shared service."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import manage
from platform_connections import PlatformConnections
from platform_connections.diagnostics import summarize


def store():
 return {'platform':'amazon','label':'SYNTHETIC_PRIVATE_LABEL','store_id':'SYNTHETIC_PRIVATE_ID',
         'access_token':'SYNTHETIC_PRIVATE_SECRET','enabled':True,'configured':True,'scope_reviewed':True,
         'snapshots':{'orders':{'available':True,'fresh':True,'document':{'private':'SYNTHETIC_PRIVATE_RECORD'}},
                      'stock':{'available':True,'fresh':False}},'last_job':{'status':'failed','error':'SYNTHETIC_PRIVATE_ERROR'}}


class Diagnostics(unittest.TestCase):
 def test_empty_unconfigured_is_current_local_without_business_acceptance(self):
  value=summarize(PlatformConnections.catalog(),{'stores':[]})
  self.assertTrue(value['running_version_current']);self.assertEqual(value['stores'],0)
  self.assertFalse(value['business_acceptance']);self.assertFalse(value['automatic_sync'])

 def test_only_counts_are_exposed_and_fresh_snapshot_does_not_hide_last_failure(self):
  entry=store();second=store();second.update(enabled=False,scope_reviewed=False,last_job=None)
  second['snapshots']={'orders':{'available':False,'fresh':False},'stock':{'available':True,'fresh':False}}
  value=summarize(PlatformConnections.catalog(),{'stores':[entry,second]});counts=value['by_platform']['amazon']
  self.assertEqual(counts,dict(stores=2,enabled_stores=1,configured_stores=2,scope_reviewed_stores=1,fresh_resources=1,stale_resources=2,missing_resources=1,last_read_errors=1,active_reads=0))
  self.assertNotIn('SYNTHETIC_PRIVATE',json.dumps(value))

 def test_old_running_capabilities_are_update_pending(self):
  catalog=PlatformConnections.catalog();catalog.pop('limits')
  value=summarize(catalog,{'stores':[]});self.assertEqual(value['status'],'update_pending');self.assertFalse(value['running_version_current'])

 def test_partial_or_invalid_metadata_cannot_claim_current(self):
  for listing in ({'stores':None},{'stores':[{'platform':'SYNTHETIC_PRIVATE'}]}):
   with self.assertRaisesRegex(ValueError,'^platform_diagnostic_metadata_invalid$'):summarize(PlatformConnections.catalog(),listing)
  value=store();value['snapshots']['orders'].update(available=False,fresh=True)
  with self.assertRaises(ValueError):summarize(PlatformConnections.catalog(),{'stores':[value]})

 def test_active_jobs_and_unknown_receipts_are_separate_counts(self):
  active=store();active['last_job']={'status':'running'}
  unknown=store();unknown['last_job']={'status':'unknown'}
  value=summarize(PlatformConnections.catalog(),{'stores':[active,unknown]})['by_platform']['amazon']
  self.assertEqual(value['active_reads'],1);self.assertEqual(value['last_read_errors'],1)

 def rpc(self,catalog=None,fail=False):
  def request(name,args):
   if name=='commerce_runtime_status':return {'worker':'running'}
   if name=='commerce_live_status':return {'configured':False,'orders':{'available':False},'stock':{'available':False},'credentials_present':{'feishu_webhook':False},'notifications_enabled':False}
   if fail:raise RuntimeError('SYNTHETIC_PRIVATE_EXCEPTION')
   if name=='commerce_platform_catalog':return catalog if catalog is not None else PlatformConnections.catalog()
   if name=='commerce_platform_list':return {'stores':[]}
   self.fail('unexpected local request')
  return request

 def test_doctor_is_ready_without_real_authorization_or_any_restart(self):
  with patch('manage.health',return_value={'status':'ready'}),patch('manage.request',side_effect=self.rpc()),patch('manage.ensure')as start,patch('manage.backup')as backup:
   result=manage.doctor();self.assertEqual(result['status'],'ready_local');self.assertFalse(result['full_business_acceptance']);start.assert_not_called();backup.assert_not_called()

 def test_doctor_retains_old_running_version_and_returns_update_pending(self):
  catalog=PlatformConnections.catalog();catalog.pop('limits')
  with patch('manage.health',return_value={'status':'ready'}),patch('manage.request',side_effect=self.rpc(catalog)),patch('manage.ensure')as start:
   value=manage.doctor();self.assertEqual(value['status'],'degraded');self.assertEqual(value['checks']['read_connectors']['status'],'update_pending');start.assert_not_called()

 def test_doctor_metadata_failure_is_unknown_without_raw_exception(self):
  with patch('manage.health',return_value={'status':'ready'}),patch('manage.request',side_effect=self.rpc(fail=True)):
   value=manage.doctor();self.assertEqual(value['status'],'degraded');self.assertEqual(value['checks']['read_connectors']['status'],'unknown');self.assertNotIn('SYNTHETIC_PRIVATE',json.dumps(value))


if __name__=='__main__':unittest.main()
