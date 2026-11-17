"""Optional local supervisor: only synthetic executable/model fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class LocalSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('local_model_supervisor'), 'optional local model supervisor is not implemented')
        import local_model_supervisor as module
        self.module = module
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        executable = self.root / 'llama-server';executable.write_bytes(b'SYNTHETIC_EXECUTABLE_NOT_RUN');executable.chmod(0o700)
        model = self.root / 'synthetic.gguf';model.write_bytes(b'GGUFsynthetic model, not inference data')
        self.config = self.root / 'approved.json'
        self.value = {'enabled': True, 'argv': [str(executable), '--host', '127.0.0.1', '--port', '38741', '--model', str(model), '--alias', 'synthetic-local', '--ctx-size', '4096'],
                      'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                      'startup_timeout_seconds': 1, 'cooldown_seconds': 30, 'max_starts_per_day': 2}
        self.save()

    def save(self):
        self.config.write_text(json.dumps(self.value));self.config.chmod(0o600)

    def supervisor(self):return self.module.LocalModelSupervisor(self.config)

    def test_default_disabled_and_status_never_launch(self):
        self.value.pop('enabled');self.save()
        with patch.object(self.module.subprocess, 'Popen') as launch:
            self.assertEqual(self.supervisor().ensure()['status'], 'disabled')
            self.assertFalse(launch.called)
        self.value['enabled'] = True;self.save()
        with patch.object(self.module, 'healthy', return_value=False), patch.object(self.module, 'occupied', return_value=False), patch.object(self.module.subprocess, 'Popen') as launch:
            self.assertEqual(self.supervisor().status()['status'], 'unavailable')
            self.assertFalse(launch.called)

    def test_existing_healthy_endpoint_is_reused_without_adopting_or_stopping_process(self):
        with patch.object(self.module, 'healthy', return_value=True), patch.object(self.module.subprocess, 'Popen') as launch:
            result = self.supervisor().ensure()
        self.assertEqual(result['status'], 'ready_reused')
        self.assertFalse(result['inference_verified']);self.assertFalse(result['process_adopted'])
        self.assertFalse(launch.called)

    def test_bad_endpoint_flags_paths_and_changed_binary_are_rejected_before_spawn(self):
        original = json.loads(json.dumps(self.value))
        variants = [
            lambda v: v['argv'].__setitem__(2, '0.0.0.0'),
            lambda v: v['argv'].extend(['--hf-repo', 'remote/model']),
            lambda v: v['argv'].__setitem__(6, str(self.root / 'missing.gguf')),
            lambda v: v.__setitem__('executable_sha256', '0' * 64),
            lambda v: v['argv'].extend(['--port', '38742']),
        ]
        for change in variants:
            self.value = json.loads(json.dumps(original));change(self.value);self.save()
            with self.subTest(argv=self.value['argv']), patch.object(self.module.subprocess, 'Popen') as launch:
                with self.assertRaises(ValueError):self.supervisor().ensure()
                self.assertFalse(launch.called)

    def test_unhealthy_occupied_port_never_launches_or_signals_external_process(self):
        with patch.object(self.module, 'healthy', return_value=False), patch.object(self.module, 'occupied', return_value=True), patch.object(self.module.subprocess, 'Popen') as launch:
            result = self.supervisor().ensure()
        self.assertEqual(result['status'], 'port_occupied_unhealthy');self.assertFalse(launch.called)

    def test_timeout_persists_unknown_and_config_change_cannot_start_second_copy(self):
        clock = [1000.0]
        def wait(seconds):clock[0] += seconds
        process = SimpleNamespace(pid=99999999)
        with patch.object(self.module, 'healthy', return_value=False), patch.object(self.module, 'occupied', return_value=False), patch.object(self.module, 'process_alive', return_value=True), patch.object(self.module.time, 'time', side_effect=lambda: clock[0]), patch.object(self.module.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(self.module.time, 'sleep', side_effect=wait), patch.object(self.module.subprocess, 'Popen', return_value=process) as launch:
            supervisor = self.supervisor();first = supervisor.ensure()
            self.assertEqual(first['status'], 'unknown')
            self.value['argv'][-1] = '8192';self.save()
            clock[0] += 300
            second = self.supervisor().ensure()
            self.assertEqual(second['status'], 'unknown');self.assertEqual(launch.call_count, 1)
            alias_parent = self.root / 'path-alias';alias_parent.mkdir()
            alias = alias_parent / '..' / self.config.name
            self.assertEqual(self.module.LocalModelSupervisor(alias).ensure()['status'], 'unknown')
            self.assertEqual(launch.call_count, 1)
            self.assertNotIn('OPENAI_API_KEY', launch.call_args.kwargs['env'])
            self.assertTrue(launch.call_args.kwargs['start_new_session'])

    def test_concurrent_ensure_starts_once_and_never_terminates_owned_or_foreign_process(self):
        entered = threading.Event();release = threading.Event();ready = threading.Event();calls = []
        def launch(*args, **kwargs):
            calls.append((args, kwargs));entered.set();release.wait(2);ready.set();return SimpleNamespace(pid=99999999)
        with patch.object(self.module, 'healthy', side_effect=lambda port: ready.is_set()), patch.object(self.module, 'occupied', return_value=False), patch.object(self.module.subprocess, 'Popen', side_effect=launch):
            first = []
            thread = threading.Thread(target=lambda: first.append(self.supervisor().ensure()));thread.start()
            self.assertTrue(entered.wait(2));second = self.supervisor().ensure();release.set();thread.join(3)
        self.assertEqual(second['status'], 'locked')
        self.assertEqual(len(calls), 1);self.assertEqual(first[0]['status'], 'ready_started')
        self.assertEqual(calls[0][0][0], self.value['argv'])

    def test_dead_owned_process_retry_respects_backoff_and_daily_start_cap(self):
        clock = [1000.0]
        def wait(seconds):clock[0] += seconds
        with patch.object(self.module, 'healthy', return_value=False), patch.object(self.module, 'occupied', return_value=False), patch.object(self.module, 'process_alive', return_value=False), patch.object(self.module.time, 'time', side_effect=lambda: clock[0]), patch.object(self.module.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(self.module.time, 'sleep', side_effect=wait), patch.object(self.module.subprocess, 'Popen', return_value=SimpleNamespace(pid=99999999)) as launch:
            self.assertEqual(self.supervisor().ensure()['status'], 'unknown')
            self.assertEqual(self.supervisor().ensure()['status'], 'backoff')
            clock[0] += 40;self.assertEqual(self.supervisor().ensure()['status'], 'unknown')
            clock[0] += 40;self.assertEqual(self.supervisor().ensure()['status'], 'daily_start_limit')
            self.assertEqual(launch.call_count, 2)

    def test_fixed_health_endpoint_rejects_redirect_without_inference_or_proxy_use(self):
        paths = [];redirect = [False]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):pass
            def do_GET(self):
                paths.append(self.path)
                if redirect[0]:
                    self.send_response(302);self.send_header('Location', 'https://example.invalid/not-requested');self.end_headers();return
                body = b'{"status":"ok"}';self.send_response(200);self.send_header('Content-Length', str(len(body)));self.end_headers();self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True);worker.start()
        try:
            with patch.dict('os.environ', {'HTTP_PROXY': 'http://127.0.0.1:1', 'HTTPS_PROXY': 'http://127.0.0.1:1'}):
                self.assertTrue(self.module.healthy(server.server_port));redirect[0] = True
                self.assertFalse(self.module.healthy(server.server_port))
        finally:server.shutdown();server.server_close();worker.join(2)
        self.assertEqual(paths, ['/health', '/health'])

    def test_private_config_permissions_symlinks_and_unapproved_download_flags_are_rejected(self):
        self.config.chmod(0o644)
        with self.assertRaises(ValueError):self.supervisor().ensure()
        self.config.chmod(0o600)
        alias = self.root / 'alias.json';alias.symlink_to(self.config)
        with self.assertRaises(ValueError):self.module.LocalModelSupervisor(alias).ensure()
        self.value['argv'].extend(['--model-url', 'https://example.invalid/synthetic.gguf']);self.save()
        with self.assertRaises(ValueError):self.supervisor().ensure()

    def test_existing_gguf_cache_blob_needs_correct_magic_without_filename_suffix(self):
        blob = self.root / 'synthetic-cache-blob'
        Path(self.value['argv'][6]).rename(blob);self.value['argv'][6] = str(blob);self.save()
        with patch.object(self.module, 'healthy', return_value=True), patch.object(self.module.subprocess, 'Popen') as launch:
            self.assertEqual(self.supervisor().ensure()['status'], 'ready_reused');self.assertFalse(launch.called)
        blob.write_bytes(b'NOT_A_GGUF_MODEL')
        with self.assertRaises(ValueError):self.supervisor().ensure()


if __name__ == '__main__':unittest.main()
