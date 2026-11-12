"""Release preparation must not write the public checkout or capture state."""
from pathlib import Path
import tempfile,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from release_preflight import report


class ReleasePreflight(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'source';self.base=Path(self.temp.name)/'public'
  for p in (self.root/'commerce',self.base/'commerce'):p.mkdir(parents=True)
 def tearDown(self):self.temp.cleanup()
 def write(self,name,body):p=self.root/'commerce'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body);return p
 def test_transitive_missing_imports_block_release_without_copying(self):
  self.write('entry.py','from child import useful\n');self.write('child.py','import nested\nuseful=1\n');self.write('nested.py','value=1\n')
  r=report(self.root,self.base,['commerce/entry.py']);self.assertEqual(r['missing_base_dependencies_outside_owned_scope'],['commerce/child.py','commerce/nested.py']);self.assertFalse(r['publish_ready']);self.assertEqual(list((self.base/'commerce').iterdir()),[])
 def test_relative_package_and_cycle_resolve_once(self):
  self.write('entry.py','from pack import value\n');self.write('pack/__init__.py','from .child import value\n');self.write('pack/child.py','import entry\nvalue=1\n')
  r=report(self.root,self.base,['commerce/entry.py']);self.assertEqual(r['transitive_python_files_checked'],3)
 def test_present_dependencies_do_not_imply_privacy_or_install_acceptance(self):
  entry=self.write('entry.py','value=1\n');(self.base/'commerce/entry.py').write_bytes(entry.read_bytes());r=report(self.root,self.base,['commerce/entry.py'])
  self.assertEqual(r['status'],'needs_privacy_license_and_install_validation');self.assertFalse(r['publish_ready']);self.assertFalse(r['clean_install_verified']);self.assertEqual(r['planned_owned_files'],[])
 def test_private_state_and_escape_are_never_selected(self):
  for entry in ('../private.json','.commerce-state/config.json','/tmp/data.json'):
   with self.assertRaises(ValueError):report(self.root,self.base,[entry])
 def test_symlink_source_is_not_followed_into_private_data(self):
  secret=Path(self.temp.name)/'private.py';secret.write_text('private_fixture=True');(self.root/'commerce/entry.py').symlink_to(secret)
  with self.assertRaisesRegex(ValueError,'symlink_rejected'):report(self.root,self.base,['commerce/entry.py'])


if __name__=='__main__':unittest.main()
