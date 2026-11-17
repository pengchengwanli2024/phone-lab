"""Verifier behavior tests: failures must survive orchestration and cleanup."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'verify.py'


def verifier():
    assert SCRIPT.is_file(), 'A runnable verification entry point is required'
    spec = importlib.util.spec_from_file_location('phone_lab_verify', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifierTests(unittest.TestCase):
    def test_nonzero_command_keeps_exit_code_and_failure_log(self):
        v = verifier()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = v.run_command('fails', [sys.executable, '-c', 'print("retained failure");raise SystemExit(7)'], root, dict(os.environ), root / 'failure.log', 10)
            self.assertEqual(result['exit_code'], 7)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('retained failure', (root / 'failure.log').read_text())
            self.assertGreaterEqual(result['duration_seconds'], 0)

    def test_timeout_is_failed_and_has_a_log(self):
        v = verifier()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = v.run_command('slow', [sys.executable, '-c', 'import time;time.sleep(30)'], root, dict(os.environ), root / 'timeout.log', .1)
            self.assertEqual(result['status'], 'timed_out')
            self.assertEqual(result['exit_code'], 124)
            self.assertIn('timeout', (root / 'timeout.log').read_text().lower())

    def test_missing_executable_is_not_a_success(self):
        v = verifier()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = v.run_command('missing', [str(root / 'missing')], root, dict(os.environ), root / 'missing.log', 1)
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['exit_code'], 127)

    def test_changed_added_and_removed_sources_are_reported(self):
        v = verifier()
        self.assertEqual(v.changed_files({'a':'old','b':'gone'}, {'a':'new','c':'added'}), ['a', 'b', 'c'])

    def test_snapshot_copies_source_but_not_local_state_or_dependencies(self):
        v = verifier()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'project'
            for name, data in {'commerce/service.py':'VALUE = 1', 'commerce/.local/config.json':'private', 'commerce/qa/result.json':'private', 'commerce/workbench/node_modules/x/index.js':'dependency', 'commerce/ui/tokens.json':'{}'}.items():
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(data)
            dest = Path(folder) / 'snapshot'
            manifest = v.copy_sources(root, dest)
            self.assertEqual(set(manifest), {'commerce/service.py', 'commerce/ui/tokens.json'})
            self.assertEqual((dest / 'commerce/service.py').read_text(), 'VALUE = 1')
            self.assertFalse((dest / 'commerce/.local').exists())

    def test_snapshot_rejects_source_symlink(self):
        v = verifier()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'project'; (root / 'commerce').mkdir(parents=True)
            (Path(folder) / 'secret.py').write_text('secret')
            (root / 'commerce/service.py').symlink_to(Path(folder) / 'secret.py')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                v.copy_sources(root, Path(folder) / 'snapshot')

    def test_snapshot_excludes_generated_host_connections_but_keeps_integration_code(self):
        v = verifier()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'project'
            integration = root / 'commerce/integrations'
            integration.mkdir(parents=True)
            for name in ('mcp.json', 'hermes.json', 'codex.toml'):
                (integration / name).write_text('PRIVATE_CONNECTION_SENTINEL')
            (integration / 'adapter.py').write_text('VALUE = 1')
            (integration / 'provider').mkdir()
            (integration / 'provider/mcp.json').write_text('PUBLIC_SCHEMA')
            dest = Path(folder) / 'snapshot'
            manifest = v.copy_sources(root, dest)
            self.assertEqual(set(manifest), {'commerce/integrations/adapter.py', 'commerce/integrations/provider/mcp.json'})
            self.assertNotIn('PRIVATE_CONNECTION_SENTINEL', ''.join(p.read_text() for p in dest.rglob('*') if p.is_file()))

    def test_snapshot_includes_service_public_source_registry(self):
        v = verifier()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'project'; (root / 'crawlers').mkdir(parents=True)
            (root / 'crawlers/sources.json').write_text('{"sources":[]}')
            manifest = v.copy_sources(root, Path(folder) / 'snapshot')
            self.assertIn('crawlers/sources.json', manifest)

    def test_skipped_required_unittest_is_not_a_success(self):
        verifier()
        gate = SCRIPT.parent / 'verification/unittest_gate.py'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'test_skips.py').write_text('import unittest\nclass T(unittest.TestCase):\n @unittest.skip("missing critical dependency")\n def test_required(self): pass\n')
            result = subprocess.run([sys.executable, str(gate), '--output', str(root / 'result.json'), 'test_skips'], cwd=root, env={**os.environ, 'PYTHONPATH':str(root)}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            receipt = json.loads((root / 'result.json').read_text())
            self.assertEqual(receipt['skipped_count'], 1)
            self.assertEqual(receipt['status'], 'failed')

    def test_all_profiles_require_browser_interaction(self):
        v = verifier()
        for profile in ('fast', 'full'):
            with self.subTest(profile=profile):
                self.assertIn('browser-interaction', v.required_gate_ids(profile))

    def test_full_profile_requires_real_operating_control_interaction(self):
        v = verifier()
        self.assertIn('operating-control-browser', v.required_gate_ids('full'))
        self.assertNotIn('operating-control-browser', v.required_gate_ids('fast'))
        names = ['scope_and_budget', 'original_task_write_and_readback', 'refresh_preserves_original_task',
                 'viewport_1440_light', 'viewport_390_dark', 'synthetic_does_not_leak_into_live',
                 'ozon_account_save_and_switch', 'ozon_accounts_credentials_hidden', 'multi_platform_bind_and_readback']
        valid = {'completed': True, 'sourceStable': True, 'errors': [], 'external': [],
                 'sourceSha256': 'expected', 'checks': [{'name': name, 'passed': True} for name in names]}
        v.validate_control_report(valid, 'expected')
        for changes in ({'checks': []}, {'completed': False}, {'sourceSha256': 'other'},
                        {'errors': ['render error']}, {'fatal': 'failed'}, {'checks': [{'name': names[0], 'passed': False}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                v.validate_control_report({**valid, **changes}, 'expected')

    def test_catalog_browser_rejects_preparation_only_and_changed_or_unexpected_execution(self):
        v = verifier()
        expected = {key: 'sha' for key in ('commerce/web/workbench.bundle.js',
            'commerce/web/product-workspace.bundle.js', 'commerce/web/catalog-ui.js',
            'commerce/web/catalog-presentation.js', 'commerce/web/media-library-ui.js')}
        report = dict(status='passed', phase='browser', ui_verified=True, synthetic_fixture=True,
                      errors=[], external=[], unexpectedWrites=[], checks=['catalog', 'library', 'download', 'scope'],
                      startHashes=expected, endHashes=expected)
        v.validate_catalog_report(report, expected)
        for changes in ({'phase': 'fixture_prepare'}, {'ui_verified': False}, {'errors': ['CSP']},
                        {'unexpectedWrites': ['publish']}, {'checks': []}, {'endHashes': {}},
                        {'startHashes': {**expected, 'extra': 'sha'}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                v.validate_catalog_report({**report, **changes}, expected)
        with self.assertRaises(ValueError):
            v.validate_catalog_report(report, {**expected, 'commerce/web/catalog-ui.js': 'changed'})

    def test_python3_on_child_path_preserves_selected_venv(self):
        v = verifier()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(root / 'venv')], check=True, capture_output=True)
            env = v.isolated_environment(root, root, str(root / 'venv/bin/python'), 'node', '', '')
            env.pop('NODE_OPTIONS')
            result = subprocess.run(['python3', '-c', 'import sys;print(sys.prefix)'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()).resolve(), (root / 'venv').resolve())

    def test_child_environment_discards_provider_secrets_and_shared_state(self):
        v = verifier()
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'OPENAI_API_KEY':'synthetic-private-sentinel', 'COMMERCE_STATE':'/synthetic/shared', 'HTTPS_PROXY':'https://synthetic.invalid', 'QA_INTEL_ONLY':'1'}):
            root = Path(folder)
            env = v.isolated_environment(root, root, sys.executable, 'node', '', '')
            for name in ('OPENAI_API_KEY', 'HTTPS_PROXY', 'QA_INTEL_ONLY'):
                self.assertNotIn(name, env)
            self.assertEqual(env['COMMERCE_STATE'], str(root / 'state'))

    def test_incomplete_or_wrong_candidate_browser_receipt_is_rejected(self):
        v = verifier()
        valid = {'completed':True,'sourceStable':True,'errors':[],'external':[], 'checks':[{'kind':'actual-interaction'}],
                 'requirements':[{'name':'interaction', 'passed':True}], 'startHashes':{'commerce/web/workbench.sources.json':'expected'}}
        v.validate_browser_report(valid, 'expected')
        for changes in ({'completed':False}, {'errors':['render error']}, {'external':['unexpected']}, {'checks':[]}, {'requirements':[{'passed':False}]}, {'startHashes':{}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                v.validate_browser_report({**valid, **changes}, 'expected')

    def test_skipped_node_tests_are_not_success(self):
        v = verifier()
        valid = 'ℹ tests 3\nℹ pass 3\nℹ fail 0\nℹ cancelled 0\nℹ skipped 0\nℹ todo 0\n'
        self.assertEqual(v.node_test_summary(valid)['tests'], 3)
        for output in ('', valid.replace('skipped 0','skipped 1'), valid.replace('tests 3','tests 0')):
            with self.subTest(output=output), self.assertRaises(ValueError):
                v.node_test_summary(output)

    def test_python_guard_denies_external_and_unregistered_local_connections(self):
        verifier()
        guard = SCRIPT.parent / 'verification'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = {**os.environ, 'PYTHONPATH':str(guard), 'VERIFY_PORTS_FILE':str(root / 'ports'), 'VERIFY_DENIALS_FILE':str(root / 'denials')}
            code = 'import socket\nfor address in [("203.0.113.1",443),("127.0.0.1",1)]:\n try: socket.socket().connect(address)\n except PermissionError: pass\n else: raise AssertionError("connection escaped guard")\n'
            result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len((root / 'denials').read_text().splitlines()), 2)

    def test_python_guard_allows_own_fixture_loopback(self):
        verifier()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = {**os.environ, 'PYTHONPATH':str(SCRIPT.parent / 'verification'), 'VERIFY_PORTS_FILE':str(root / 'ports'), 'VERIFY_DENIALS_FILE':str(root / 'denials')}
            code = 'import socket\ns=socket.socket();s.bind(("127.0.0.1",0));s.listen(1)\nc=socket.create_connection(s.getsockname());peer,_=s.accept();peer.sendall(b"fixture");assert c.recv(7)==b"fixture"\n'
            result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / 'denials').exists())

    def test_node_guard_denies_external_and_unregistered_local_connections(self):
        verifier()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = {**os.environ, 'NODE_OPTIONS':'--require=' + str(SCRIPT.parent / 'verification/network_guard.cjs'), 'VERIFY_PORTS_FILE':str(root / 'ports'), 'VERIFY_DENIALS_FILE':str(root / 'denials')}
            code = 'const net=require("node:net");for(const host of ["203.0.113.1","127.0.0.1"]){let denied=false;try{net.connect(1,host)}catch(e){denied=e.message==="verification_network_denied"}if(!denied)process.exit(1)}'
            result = subprocess.run(['node', '-e', code], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len((root / 'denials').read_text().splitlines()), 2)


if __name__ == '__main__':
    unittest.main()
