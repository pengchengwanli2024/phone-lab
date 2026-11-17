import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ui_source_guard_build',ROOT/'ui/build.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class UIBuildSourceGuard(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        for folder in ('web','ui'):
            shutil.copytree(ROOT/folder,self.root/folder)
        shutil.copyfile(ROOT/'creative_ui.js',self.root/'creative_ui.js')
        (self.root/'harness').mkdir()
        shutil.copyfile(ROOT/'harness/client.js',self.root/'harness/client.js')
        (self.root/'workbench/map/node_modules/esbuild').mkdir(parents=True)

    def build(self):
        with patch.object(builder,'ROOT',self.root),patch('sys.argv',['build.py']),patch.object(builder.subprocess,'run'):
            builder.main()

    def test_canonical_operations_change_is_built_and_handwritten_code_survives(self):
        app=self.root/'web/app.js'
        app.write_text(app.read_text()+'\n// preserve handwritten sentinel\n')
        ops=self.root/'web/ops-ui.js'
        ops.write_text(ops.read_text()+'\n// canonical operations regression\n')
        self.build()
        result=app.read_text()
        self.assertIn('// canonical operations regression',result)
        self.assertIn('// preserve handwritten sentinel',result)

    def test_real_concurrent_edit_is_still_blocked_without_overwrite(self):
        original=Path.read_text
        app=self.root/'web/app.js'
        changed=False
        def read(path,*args,**kwargs):
            nonlocal changed
            if path==self.root/'web/ops-ui.js' and not changed:
                changed=True
                app.write_text(original(app)+'\n// concurrent handwritten edit\n')
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read),self.assertRaisesRegex(SystemExit,'Concurrent UI edit'):
            self.build()
        self.assertIn('// concurrent handwritten edit',app.read_text())

    def test_check_detects_stale_operations_instead_of_comparing_two_transformed_copies(self):
        self.build()
        ops=self.root/'web/ops-ui.js'
        ops.write_text(ops.read_text()+'\n// stale operations regression\n')
        with patch.object(builder,'ROOT',self.root),patch('sys.argv',['build.py','--check']),patch.object(builder.subprocess,'run'):
            with self.assertRaisesRegex(SystemExit,'UI kit/tokens are stale'):
                builder.main()


if __name__=='__main__':unittest.main()
