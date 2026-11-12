"""A native client must not race an installed matching LaunchAgent at login."""
import plistlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime


class SupervisedStartup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.state = self.home / 'state'
        self.agent = self.home / 'Library/LaunchAgents/local.phone-lab.commerce.plist'
        self.agent.parent.mkdir(parents=True)
        self.agent.write_bytes(plistlib.dumps({'Label':'local.phone-lab.commerce', 'ProgramArguments':['python3',str(runtime.ROOT/'server.py')], 'EnvironmentVariables':{'COMMERCE_STATE':str(self.state),'COMMERCE_PORT':'51234'}}))
        for target, value in [('STATE', self.state), ('PORT', 51234)]:
            p = patch.object(runtime, target, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(runtime.sys, 'platform', 'darwin'); p.start(); self.addCleanup(p.stop)
        p = patch.object(Path, 'home', return_value=self.home); p.start(); self.addCleanup(p.stop)

    def test_matching_loaded_supervisor_starts_without_detached_client_process(self):
        with patch.object(runtime, 'health', side_effect=[OSError('starting'), {'status':'ready'}]), patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('client raced matching supervisor')) as spawn:
            runtime.ensure()
            spawn.assert_not_called()

    def test_unhealthy_matching_supervisor_reports_failure_without_competing_process(self):
        with patch.object(runtime, 'health', side_effect=OSError('not yet ready')), patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('client raced matching supervisor')) as spawn, patch.object(runtime.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'commerce_service_unavailable'):
                runtime.ensure()
            spawn.assert_not_called()

    def test_other_state_keeps_standalone_start_without_touching_supervisor(self):
        value = plistlib.loads(self.agent.read_bytes())
        value['EnvironmentVariables']['COMMERCE_STATE'] = str(self.home/'different-state')
        self.agent.write_bytes(plistlib.dumps(value))
        with patch.object(runtime, 'health', side_effect=[OSError('not ready'), {'status':'ready'}]), patch.object(runtime.subprocess, 'run') as inspect, patch.object(runtime.subprocess, 'Popen') as spawn:
            runtime.ensure()
            spawn.assert_called_once()
            inspect.assert_not_called()


if __name__ == '__main__': unittest.main()
