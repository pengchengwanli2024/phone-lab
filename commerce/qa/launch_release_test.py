"""Rollback rehearsal uses disposable code files, never the running workspace."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_release import FILES,snapshot,rollback

class Release(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'source';self.state=Path(self.temp.name)/'state'
        for name in FILES:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('original synthetic UI');p.chmod(0o644)
        self.peer=self.root/'commerce/web/peer.js';self.peer.write_text('peer baseline');self.a=snapshot(self.root,self.state)['release_id']
        (self.root/FILES[1]).write_text('approved synthetic UI');self.b=snapshot(self.root,self.state)['release_id']
    def tearDown(self):self.temp.cleanup()
    def test_actual_isolated_restore_and_dry_run(self):
        self.assertTrue(rollback(self.root,self.state,self.a,self.b)['dry_run']);self.assertEqual((self.root/FILES[1]).read_text(),'approved synthetic UI')
        self.assertEqual(rollback(self.root,self.state,self.a,self.b,True)['status'],'restored');self.assertTrue(all((self.root/p).read_text()=='original synthetic UI'for p in FILES));self.assertEqual(self.peer.read_text(),'peer baseline')
    def test_concurrent_owned_change_refused(self):
        (self.root/FILES[1]).write_text('new peer increment')
        with self.assertRaisesRegex(ValueError,'current_source_changed'):rollback(self.root,self.state,self.a,self.b,True)
        self.assertEqual((self.root/FILES[1]).read_text(),'new peer increment')
    def test_peer_change_refused(self):
        self.peer.write_text('new independent module')
        with self.assertRaisesRegex(ValueError,'peer_context_changed'):rollback(self.root,self.state,self.a,self.b,True)
        self.assertEqual(self.peer.read_text(),'new independent module')
    def test_backend_change_refused(self):
        (self.root/'commerce/service.py').write_text('new backend contract')
        with self.assertRaisesRegex(ValueError,'peer_context_changed'):rollback(self.root,self.state,self.a,self.b,True)
    def test_archive_tamper_refused(self):
        (self.state/'ui-releases'/self.a/FILES[0]).write_text('tampered')
        with self.assertRaisesRegex(ValueError,'archive_changed'):rollback(self.root,self.state,self.a,self.b,True)
    def test_symlink_refused(self):
        p=self.root/FILES[1];p.unlink();p.symlink_to(self.peer)
        with self.assertRaisesRegex(ValueError,'symlink_rejected'):rollback(self.root,self.state,self.a,self.b,True)
    def test_path_traversal_refused(self):
        with self.assertRaisesRegex(ValueError,'id_invalid'):rollback(self.root,self.state,'../outside',self.b,True)
if __name__=='__main__':unittest.main(verbosity=2)
