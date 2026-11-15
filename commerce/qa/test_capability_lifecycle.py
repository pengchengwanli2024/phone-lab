"""Capability background I/O must not block the existing business timer."""
import sys
from pathlib import Path
import threading
import unittest
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from capability_lifecycle import CapabilityLifecycle


class LifecycleTests(unittest.TestCase):
    def test_slow_provider_io_is_owned_and_does_not_block_or_duplicate_tick(self):
        started=threading.Event();finish=threading.Event();done=threading.Event();calls=[]
        def tick(at=None):
            calls.append(at);started.set();finish.wait(2);done.set()
        state=[]
        service=SimpleNamespace(media_providers=SimpleNamespace(tick=tick,stop=lambda:finish.set(),recover=lambda:None),
            extensions=SimpleNamespace(tick=lambda at=None:state.append(at),stop=lambda:None,recover=lambda:None))
        lifecycle=CapabilityLifecycle(service)
        try:
            lifecycle.tick(at=1);self.assertTrue(started.wait(1));self.assertFalse(done.is_set())
            lifecycle.tick(at=2);self.assertEqual(calls,[1]);self.assertEqual(state,[1,2])
        finally:lifecycle.stop()
        self.assertTrue(done.wait(1));self.assertTrue(lifecycle.status()['stopped'])

    def test_extension_error_is_observable_and_does_not_skip_media_dispatch(self):
        done=threading.Event()
        def broken(at=None):raise RuntimeError('private diagnostic must not be exposed')
        service=SimpleNamespace(media_providers=SimpleNamespace(tick=lambda at=None:done.set(),stop=lambda:None,recover=lambda:None),
            extensions=SimpleNamespace(tick=broken,stop=lambda:None,recover=lambda:None))
        lifecycle=CapabilityLifecycle(service)
        try:
            lifecycle.tick();self.assertTrue(done.wait(1));self.assertEqual(lifecycle.status()['extension_error'],'extension_background_tick_failed')
            self.assertNotIn('private diagnostic',str(lifecycle.status()))
        finally:lifecycle.stop()

if __name__=='__main__':unittest.main()
