"""Account selectors reuse owning login programs; never read credential files."""
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce

class Accounts(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name)
 def tearDown(self):self.app.agent_runtime.stop();self.app.platforms.stop();self.tmp.cleanup()
 def test_explicit_deepseek_selection_freezes_current_native_account_route(self):
  self.app.host_execution.register('dsh','deepseek-account','deepseek-flash')
  with self.app.core.db()as db:r=self.app.models.snapshot(db,model_id='account-deepseek')
  self.assertEqual(r['provider'],'host_native');self.assertEqual(r['native_provider'],'deepseek-account');self.assertEqual(r['host_id'],'dsh')
  self.app.host_execution.register('dsh','another-provider','another-model')
  with self.app.core.db()as db,self.assertRaisesRegex(ValueError,'model_not_ready'):self.app.models.snapshot(db,model_id='account-deepseek')
 def test_openai_account_reuses_codex_route_without_copying_auth(self):
  route={'provider':'codex','model':'synthetic-openai-model','profile_id':'project-default','profile_revision':'0','label':'项目默认'}
  with patch.object(self.app.models,'default_snapshot',return_value=route),self.app.core.db()as db:
   r=self.app.models.snapshot(db,model_id='account-openai')
  self.assertEqual(r['provider'],'codex');self.assertEqual(r['profile_id'],'account-openai');self.assertNotIn('api_key',r)
 def test_status_uses_cli_login_status_only_and_redacts_stdout(self):
  from model_accounts import status
  with patch('model_accounts.executable',return_value='/synthetic/codex'),patch('model_accounts.subprocess.run')as run:
   run.return_value.returncode=0;run.return_value.stdout='Logged in using ChatGPT';run.return_value.stderr='SYNTHETIC-PRIVATE-NOT-RETURNED'
   r=status(self.app.models)
  self.assertEqual(run.call_args.args[0],['/synthetic/codex','login','status']);self.assertEqual(r['accounts'][0]['status'],'authenticated');self.assertNotIn('SYNTHETIC-PRIVATE',str(r))

if __name__=='__main__':unittest.main()
