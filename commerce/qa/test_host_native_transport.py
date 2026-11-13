"""Subprocess host boundaries do not inherit unrelated application credentials."""
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import json
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class NativeHostTransport(unittest.TestCase):
    def test_worker_environment_drops_unrelated_tokens_and_disables_customizations(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('host_native'), 'Native host transport is missing')
        from host_native import environment
        with patch.dict(os.environ, {'COMMERCE_TOKEN': 'synthetic-private',
                                     'OPENAI_API_KEY': 'synthetic-private',
                                     'HERMES_KANBAN_TASK': 'unrelated-worker'}):
            env = environment()
        self.assertNotIn('COMMERCE_TOKEN', env)
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('HERMES_KANBAN_TASK', env)
        self.assertEqual(env['HERMES_SAFE_MODE'], '1')
        self.assertEqual(env['HERMES_IGNORE_RULES'], '1')

    def test_managed_launcher_bootstrap_is_kept_when_selecting_native_worker(self):
        import host_native
        self.assertTrue(hasattr(host_native, 'hermes_command'), 'Managed Hermes launcher is unsupported')
        entry="runpy.run_module('runpy', run_name='__main__', alter_sys=True)"
        resolved=['/synthetic/runtime/python','-I','-c','import hermes_bootstrap; import sys,runpy; '+entry]
        with tempfile.NamedTemporaryFile() as executable:
            with patch('host_native.shutil.which',return_value=executable.name),patch('host_native.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(resolved))):
                command=host_native.hermes_command()
        self.assertEqual(command[:3],resolved[:3])
        self.assertIn('hermes_bootstrap',command[3])
        self.assertTrue(command[-1].endswith('hermes_host_worker.py'))
        self.assertNotIn('run_module',command[3])


if __name__ == '__main__':
    unittest.main()
