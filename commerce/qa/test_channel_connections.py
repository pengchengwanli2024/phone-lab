"""Project channel plans are local; native Hermes diagnostics are read-only."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
import os
import subprocess
import threading
import urllib.error
import urllib.request
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from channel_connections import ChannelConnections


def diagnostic():
    return {'profile_available': True, 'shared_core_configured': True, 'platforms': {
        name: {'adapter_available': True, 'credentials_present': False,
               'missing_fields': ['EXAMPLE_APP_SECRET'], 'gateway_enabled': False,
               'runtime_status': 'not_running'}
        for name in ('feishu', 'wecom', 'wecom_callback', 'dingtalk', 'weixin')}}


class Channels(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)
        self.probe = patch('channel_connections.probe_profile', return_value=diagnostic())
        self.mock = self.probe.start()

    def tearDown(self):
        self.probe.stop(); self.temp.cleanup()

    def call(self, tool, args=None):
        return self.app.invoke('commerce_channel_' + tool, args or {}, 'test')

    def save(self, **kwargs):
        return self.call('configure', {'channel': 'feishu', 'mode': 'app', 'selected': True,
                                     'label': 'Synthetic test group', 'expected_revision': '0', **kwargs})

    def test_status_has_four_channels_without_creating_plans_or_starting_anything(self):
        status = self.call('status')
        self.assertEqual([row['id'] for row in status['channels']], ['feishu', 'wecom', 'wechat', 'dingtalk'])
        self.assertFalse(status['external_messages_sent'])
        self.assertEqual(status['profile'], 'commerce-bot')
        self.assertEqual(status['setup_command'], 'hermes -p commerce-bot gateway setup')
        self.assertEqual(status['channels'][2]['readiness'], 'account_type_required')
        self.assertTrue(all(not row['delivery_verified'] for row in status['channels']))
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM channel_bindings').fetchone()[0], 0)
        self.call('status'); self.mock.assert_called_once()

    def test_model_can_read_minimal_channel_status_but_cannot_configure_or_force_a_probe(self):
        from agent_runtime.policy import tool_menu, check_call, project
        scope = {'context': {'module': 'connections', 'demo': False}}
        self.assertIn('commerce_channel_status', [item['tool'] for item in tool_menu('workspace', scope)])
        self.assertIn('commerce_channel_status', [item['tool'] for item in tool_menu('runtime', {})])
        self.assertEqual(check_call('workspace', scope, {'tool':'commerce_channel_status','arguments':{}}, set()), ('commerce_channel_status', {}))
        for topic, parameters in (('workspace',scope),('runtime',{})):
            with self.assertRaises(ValueError): check_call(topic, parameters, {'tool':'commerce_channel_configure','arguments':{}}, set())
            with self.assertRaises(ValueError): check_call(topic, parameters, {'tool':'commerce_channel_status','arguments':{'refresh':True}}, set())
        raw = self.call('status'); raw['secret'] = 'PRIVATE_SENTINEL'
        raw['channels'][0]['binding']['label'] = 'PRIVATE_SENTINEL'
        raw['channels'][0]['token'] = 'PRIVATE_SENTINEL'
        projected = project('commerce_channel_status', raw)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(projected))
        self.assertFalse(projected['external_execution_allowed'])
        self.assertEqual(len(projected['channels']),4)

    def test_shared_copilot_reads_channel_diagnostics_without_changing_a_plan(self):
        thread = self.app.copilot.open({'module':'connections'},'synthetic-channel-chat')
        sent = self.app.copilot.send(thread['id'],'检查消息渠道',thread['context_sha256'],'synthetic-channel-send')
        decisions = [{'decision':{'phase':'inspect','calls':[{'tool':'commerce_channel_status','arguments':{}}]}},
                     {'decision':{'phase':'answer','answer':'渠道凭据尚未配置，需要在本机完成授权。','questions':['先接入哪个渠道？'],
                                  'evidence_refs':['R1'],'proposals':[]},'provider':'synthetic','model':'synthetic'}]
        with patch('agent_runtime.model.invoke',side_effect=decisions): self.app.agent_runtime.run_once()
        result = self.app.copilot.get(thread['id'])
        self.assertEqual(result['latest_run']['status'],'awaiting_input')
        self.assertEqual(result['latest_run']['result']['evidence_refs'],['R1'])
        self.assertEqual(result['latest_run']['result']['observations'][0]['tool'],'commerce_channel_status')
        self.assertTrue(result['surfaces'])
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM channel_bindings').fetchone()[0],0)

    def test_local_configuration_persists_with_revision_and_does_not_imply_authorization(self):
        self.save()
        restored = Commerce(self.temp.name).invoke('commerce_channel_status', {}, 'test')['channels'][0]
        self.assertEqual(restored['binding']['revision'], '1')
        self.assertEqual(restored['binding']['label'], 'Synthetic test group')
        self.assertEqual(restored['readiness'], 'authorization_required')
        self.assertFalse(restored['credentials_present'])
        with self.assertRaisesRegex(ValueError, 'channel_configuration_conflict'):
            self.save(label='Stale overwrite')
        self.save(selected=False, expected_revision='1')
        self.assertEqual(self.call('status')['channels'][0]['readiness'], 'not_selected')

    def test_credentials_and_connected_runtime_still_do_not_claim_scope_or_delivery_verified(self):
        data = diagnostic(); row = data['platforms']['feishu']
        row.update(credentials_present=True, missing_fields=[], gateway_enabled=True, runtime_status='connected_reported')
        self.mock.return_value = data
        self.save()
        current = self.call('status')['channels'][0]
        self.assertEqual(current['readiness'], 'scope_and_delivery_not_verified')
        self.assertFalse(current['delivery_verified'])
        row['runtime_status'] = 'stale'
        self.assertEqual(self.call('status', {'refresh': True})['channels'][0]['readiness'], 'gateway_not_running')

    def test_unsupported_wechat_modes_remain_explicit_and_configuration_is_not_messaging(self):
        self.save(channel='wechat', mode='official_account')
        row = self.call('status')['channels'][2]
        self.assertEqual(row['readiness'], 'unsupported_account_type')
        self.assertFalse(row['adapter_available'])
        for extra in ({'token':'must-not-save'}, {'webhook':'https://example.org'}, {'send':True}):
            with self.assertRaises(ValueError): self.save(**extra)
        for patch_args in ({'channel':'../default'}, {'mode':'stream'}, {'selected':'true'},
                           {'expected_revision':'-1'}, {'label':'Bearer synthetic-credential'}):
            with self.subTest(patch_args=patch_args), self.assertRaises(ValueError): self.save(**patch_args)

    def test_probe_failure_removes_previously_observed_connected_state_and_redacts_errors(self):
        self.call('status')
        self.mock.side_effect = RuntimeError('private-secret-that-must-not-escape')
        status = self.call('status', {'refresh': True})
        self.assertEqual(status['probe_status'], 'unavailable')
        self.assertNotIn('private-secret', json.dumps(status))
        self.assertTrue(all(row['runtime_status'] == 'unknown' and not row['credentials_present'] for row in status['channels']))

    def test_authenticated_http_and_actual_stdio_mcp_share_the_same_plan(self):
        import server
        class Handler(server.Handler): pass
        Handler.service = self.app; Handler.secret = 'synthetic-channel-only'
        (Path(self.temp.name) / 'auth.token').write_text(Handler.secret)
        http = server.CommerceHTTPServer(('127.0.0.1', 0), Handler)
        port = http.server_address[1]
        def call(auth=True, origin=None):
            headers = {'Content-Type':'application/json'}
            if auth: headers['Authorization'] = 'Bearer ' + Handler.secret
            if origin: headers['Origin'] = origin
            req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/invoke', data=json.dumps({'tool':'commerce_channel_status','arguments':{},'client':'test'}).encode(), headers=headers)
            with urllib.request.urlopen(req,timeout=5) as response: return json.load(response)
        with patch.object(server, 'PORT', port):
            thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
            try:
                with self.assertRaises(urllib.error.HTTPError) as missing: call(auth=False)
                self.assertEqual(missing.exception.code,401)
                missing.exception.close()
                with self.assertRaises(urllib.error.HTTPError) as foreign: call(origin='https://example.org')
                self.assertEqual(foreign.exception.code,403)
                foreign.exception.close()
                self.assertEqual(len(call()['channels']),4)
                messages = [
                    {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{}}},
                    {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                    {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'commerce_channel_configure','arguments':{'channel':'dingtalk','mode':'stream','selected':True,'label':'Synthetic target','expected_revision':'0'}}},
                ]
                done = subprocess.run([sys.executable,str(Path(server.__file__).with_name('mcp_server.py')),'test'],
                    env={**os.environ,'COMMERCE_STATE':self.temp.name,'COMMERCE_PORT':str(port)},
                    input=''.join(json.dumps(message)+'\n' for message in messages),text=True,capture_output=True,timeout=10)
                self.assertEqual(done.returncode,0,done.stderr)
                replies = {message['id']:message for message in map(json.loads,done.stdout.splitlines())}
                tools = {tool['name']:tool for tool in replies[2]['result']['tools']}
                self.assertTrue(tools['commerce_channel_status']['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_channel_configure']['annotations']['readOnlyHint'])
                self.assertFalse(replies[3]['result'].get('isError',False))
                self.assertEqual(call()['channels'][3]['binding']['revision'],'1')
                self.assertEqual(call()['channels'][3]['readiness'],'authorization_required')
            finally:
                http.shutdown(); http.server_close(); thread.join(timeout=5)


if __name__ == '__main__': unittest.main()
