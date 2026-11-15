import hashlib,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from state_recovery import verify_state_recovery,private_copy

class StateRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name)
        p=self.state/'creative'/'synthetic-project';p.mkdir(parents=True);(p/'asset.bin').write_bytes(b'synthetic-real-bytes')
        self.key=self.state/'config.json';self.key.write_text('{"key":"synthetic-private-canary"}')
        with sqlite3.connect(self.state/'commerce.sqlite')as db:
            db.execute('CREATE TABLE creative_assets(project TEXT,filename TEXT,metadata TEXT)')
            db.execute('INSERT INTO creative_assets VALUES (?,?,?)',('synthetic-project','asset.bin',json.dumps({'sha256':hashlib.sha256((p/'asset.bin').read_bytes()).hexdigest()})))
    def tearDown(self):self.tmp.cleanup()
    def test_all_files_and_registered_assets_restore_to_an_isolated_copy(self):
        result=verify_state_recovery(self.state);self.assertEqual(result['status'],'passed')
        d=result['details'];self.assertEqual(d['registered_assets_checked'],1);self.assertEqual(d['file_count'],2)
        restored=result['report'].parent/'restored-state'
        self.assertEqual((restored/'config.json').read_bytes(),self.key.read_bytes())
        for p in restored.rglob('*'):
            if p.is_file():self.assertEqual(p.stat().st_mode&0o777,0o600)
        self.assertNotIn('synthetic-private-canary',result['report'].read_text());self.assertFalse(d['live_files_restored'])
    def test_missing_registered_asset_cannot_pass(self):
        (self.state/'creative'/'synthetic-project'/'asset.bin').unlink()
        result=verify_state_recovery(self.state);self.assertEqual(result['status'],'failed')
        self.assertEqual(result['details']['code'],'state_recovery_registered_asset_missing')
    def test_executable_asset_retains_owner_execute_without_public_permissions(self):
        tool=self.state/'local-tool';tool.write_bytes(b'synthetic-executable');tool.chmod(0o755)
        result=verify_state_recovery(self.state);self.assertEqual(result['status'],'passed')
        restored=result['report'].parent/'restored-state'/'local-tool'
        self.assertEqual(restored.stat().st_mode&0o777,0o700)
    def test_symlinks_and_live_mutation_are_not_silently_skipped(self):
        (self.state/'link').symlink_to(self.key)
        with self.assertRaisesRegex(ValueError,'state_recovery_unsafe_file'):verify_state_recovery(self.state)
        (self.state/'link').unlink()
        def mutate(source,target):
            private_copy(source,target)
            if source.name=='config.json':self.key.write_text('changed')
        with patch('state_recovery.private_copy',side_effect=mutate):result=verify_state_recovery(self.state)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['details']['code'],'state_recovery_source_changed')

if __name__=='__main__':unittest.main()
