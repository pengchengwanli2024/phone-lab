"""Bounded CLI adapter checks, without a network request or a signed-in account."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_runtime import codex_provider as provider
try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


class CodexProvider(unittest.TestCase):
    @unittest.skipIf(Draft202012Validator is None, 'Optional JSON Schema validation dependency missing')
    def test_answer_schema_requires_current_evidence_even_for_missing_information(self):
        observations = [{'id': 'R1', 'data': {'items': []}}, {'id': 'R2', 'data': {'status': 'unknown'}}]
        answer = {'phase': 'answer', 'answer': '当前资料不足，请补充来源。', 'questions': ['有已核对的来源吗？'], 'evidence_refs': ['R1'], 'proposals': []}
        validator = Draft202012Validator(provider.schema(observations))
        self.assertTrue(validator.is_valid({'decision': answer}))
        for refs in ([], ['R3'], ['R1', 'R3']):
            with self.subTest(refs=refs):
                self.assertFalse(validator.is_valid({'decision': {**answer, 'evidence_refs': refs}}))
        empty = Draft202012Validator(provider.schema([]))
        self.assertTrue(empty.is_valid({'decision': {**answer, 'evidence_refs': []}}))
        self.assertFalse(empty.is_valid({'decision': answer}))

    def test_invocation_uses_the_current_observation_schema(self):
        answer = {'phase': 'answer', 'answer': '资料待补', 'questions': ['请提供来源'], 'evidence_refs': ['R2'], 'proposals': []}
        payload = {'observations': [{'id': 'R2', 'data': {'status': 'unknown'}}]}
        with patch.object(provider, 'invoke_json', return_value={'decision': answer}) as invoke:
            self.assertEqual(provider.invoke(payload, lambda: False, {'model': 'synthetic'})['decision'], answer)
        validator = invoke.call_args.args[3]['properties']['decision']['anyOf'][1]['properties']['evidence_refs']
        self.assertEqual(validator['items']['enum'], ['R2'])
        self.assertEqual(validator['minItems'], 1)

    def test_private_route_is_explicit_and_rejects_extra_capabilities(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(provider.route(root),{'provider':'hermes'})
            p=root/'agent-model.json'
            p.write_text(json.dumps({'provider':'codex','model':'gpt-6.1-sol'}))
            self.assertEqual(provider.route(root)['provider'],'codex')
            p.write_text(json.dumps({'provider':'codex','model':'x','command':'arbitrary'}))
            with self.assertRaisesRegex(ValueError,'model_route_invalid'):provider.route(root)

    def test_command_ignores_user_configuration_and_disables_external_tools(self):
        with patch.object(provider.shutil,'which',return_value='/synthetic/codex'):
            cmd=provider.command(Path('/synthetic/work'),{'model':'gpt-6.1-sol'})
        for flag in ['--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check']:
            self.assertIn(flag,cmd)
        self.assertEqual(cmd[cmd.index('--sandbox')+1],'read-only')
        for config in ['features.shell_tool=false','features.plugins=false','features.apps=false','web_search="disabled"','project_doc_max_bytes=0']:
            self.assertIn(config,cmd)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',cmd)

    def test_structured_transport_normalizes_only_the_valid_phase(self):
        inspect={'phase':'inspect','calls':[{'tool':'commerce_runtime_status','arguments_json':'{}'}]}
        self.assertEqual(provider.decode({'decision':inspect})['calls'][0]['arguments'],{})
        answer={'phase':'answer','answer':'需要资料','questions':['请给出成本'],'evidence_refs':[],'proposals':[]}
        self.assertEqual(provider.decode({'decision':answer}),answer)
        for bad in [{'decision':{'phase':'inspect','calls':[{'tool':'x','arguments_json':'[]'}]}},
                    {'decision':{'phase':'inspect','calls':[{'tool':'x','arguments_json':'broken'}]}},
                    {'decision':{**answer,'calls':[]}}]:
            with self.assertRaisesRegex(ValueError,'invalid_json|invalid_response'):provider.decode(bad)

    def test_cancel_before_launch_and_no_silent_provider_fallback(self):
        with patch.object(provider.subprocess,'Popen') as launch:
            with self.assertRaises(provider.Cancelled):provider.invoke({},lambda:True,{'model':'gpt-6.1-sol'})
            launch.assert_not_called()
        with patch.object(provider.shutil,'which',return_value=None),patch.object(provider,'KNOWN_BINARIES',()):
            with self.assertRaisesRegex(ValueError,'model_setup_required'):provider.command(Path('/tmp/test'),{'model':'gpt-6.1-sol'})

    def test_cli_event_guard_rejects_command_or_plugin_execution(self):
        provider.check_events('\n'.join(json.dumps(e) for e in [
            {'type':'thread.started'}, {'type':'item.completed','item':{'type':'agent_message','text':'ok'}},
            {'type':'turn.completed'}]))
        for kind in ['command_execution','mcp_tool_call','web_search','file_change']:
            with self.assertRaisesRegex(ValueError,'unexpected_tool'):
                provider.check_events(json.dumps({'type':'item.completed','item':{'type':kind}}))

    def fake_cli(self,root,body):
        script=root/'fake_codex.py'
        script.write_text('import pathlib,sys,json,time,os\n'+body)
        return [sys.executable,str(script)]

    def test_real_subprocess_output_and_private_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cmd=self.fake_cli(root,"assert 'COMMERCE_SECRET_SENTINEL' not in os.environ\nrequest=json.load(sys.stdin)\np=pathlib.Path.cwd()/'answer.json'\np.write_text(json.dumps({'decision':{'phase':'answer','answer':'合成回执','questions':['资料？'],'evidence_refs':[],'proposals':[]}}))\nprint(json.dumps({'type':'turn.completed'}))\n")
            with patch.object(provider,'command',return_value=cmd),patch.dict(provider.os.environ,{'COMMERCE_SECRET_SENTINEL':'must-not-forward'}):
                value=provider.invoke({'question':'synthetic'},lambda:False,{'model':'synthetic'})
            self.assertEqual(value['provider'],'codex_cli')
            self.assertEqual(value['decision']['questions'],['资料？'])

    def test_running_cancel_terminates_owned_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pidfile=root/'pid'
            cmd=self.fake_cli(root,'pathlib.Path('+repr(str(pidfile))+').write_text(str(os.getpid()))\ntime.sleep(20)\n')
            with patch.object(provider,'command',return_value=cmd):
                start=time.monotonic()
                with self.assertRaises(provider.Cancelled):provider.invoke({},lambda:pidfile.exists(),{'model':'synthetic'})
            self.assertLess(time.monotonic()-start,4)
            with self.assertRaises(ProcessLookupError):provider.os.kill(int(pidfile.read_text()),0)

    def test_cli_failures_do_not_echo_diagnostics_or_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd=self.fake_cli(Path(directory),"sys.stderr.write('SECRET_SENTINEL')\nsys.exit(1)\n")
            with patch.object(provider,'command',return_value=cmd) as launch:
                with self.assertRaisesRegex(ValueError,'agent_provider_failed_no_automatic_retry') as error:
                    provider.invoke({},lambda:False,{'model':'synthetic'})
            launch.assert_called_once();self.assertNotIn('SECRET_SENTINEL',str(error.exception))

    def test_cancel_kills_term_ignoring_child_after_leader_exits(self):
        import os,signal,subprocess
        with tempfile.TemporaryDirectory() as directory:
            pidfile=Path(directory)/'child'
            child='import signal,time,os,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path('+repr(str(pidfile))+').write_text(str(os.getpid()));time.sleep(30)'
            cmd=self.fake_cli(Path(directory),'import subprocess\nsubprocess.Popen([sys.executable,"-c",'+repr(child)+'])\ntime.sleep(30)\n')
            try:
                with patch.object(provider,'command',return_value=cmd):
                    with self.assertRaises(provider.Cancelled):provider.invoke({},lambda:pidfile.exists(),{'model':'synthetic'})
                pid=int(pidfile.read_text())
                # A reparented zombie has stopped; some CI init processes reap later.
                status=subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True).stdout.strip()
                self.assertTrue(not status or status.startswith('Z'),'owned child still running: '+status)
            finally:
                if pidfile.exists():
                    try:os.kill(int(pidfile.read_text()),signal.SIGKILL)
                    except ProcessLookupError:pass


if __name__=='__main__':unittest.main()
