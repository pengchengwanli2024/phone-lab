"""Catch credential leakage, corrupt releases and unsafe archive extraction."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
import zipfile


SCRIPTS = Path(__file__).resolve().parents[1] / 'windows'


def load(name):
    path = SCRIPTS / (name + '.py')
    if not path.exists():
        raise AssertionError('Windows deployment tool is missing: ' + name)
    spec = importlib.util.spec_from_file_location('windows_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'source'
        self.root.mkdir()
        self.output = self.root.parent / 'deploy.zip'
        self.target = self.root.parent / 'target'
        for name, value in {
            'commerce/server.py': 'print("synthetic")\n',
            'commerce/runtime.py': '# synthetic runtime\n',
            'commerce/requirements.txt': '',
            'commerce/web/workbench.bundle.js': 'console.log("synthetic")',
            'commerce/web/workbench.bundle.css': 'body{}',
            'commerce/web/workbench.html': '<html></html>',
            'commerce/ui/tokens.json': '{}',
            'crawlers/sources.json': '{"sources": []}',
            'scripts/windows/smoke.py': '# synthetic smoke\n',
            'scripts/windows/install_wsl.py': '# synthetic installer\n',
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)

    def build(self):
        return load('bundle').build(self.root, self.output)

    def rewrite(self, replacements):
        with zipfile.ZipFile(self.output) as archive:
            entries = {i.filename: archive.read(i) for i in archive.infolist()}
        entries.update(replacements)
        with zipfile.ZipFile(self.output, 'w') as archive:
            for name, raw in entries.items():
                archive.writestr(name, raw)

    def test_bundle_omits_credentials_private_state_and_qa_outputs(self):
        for name in ['commerce/.local/token.py', 'commerce/.env', 'commerce/auth.token',
                     'commerce/qa/result.json', 'commerce/integrations/mcp.json',
                     'commerce/workbench/node_modules/dependency/index.js',
                     '.commerce-state/commerce.sqlite', 'Seller API.env.rtf']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('PRIVATE-SENTINEL')
        manifest = self.build()
        with zipfile.ZipFile(self.output) as archive:
            self.assertTrue(all(b'PRIVATE-SENTINEL' not in archive.read(i) for i in archive.infolist()))
            self.assertIn('phone-lab/commerce/server.py', archive.namelist())
            self.assertIn('phone-lab/crawlers/sources.json', archive.namelist())
        self.assertGreater(len(manifest['files']), 0)

    def test_selected_symlink_is_rejected(self):
        external = self.root.parent / 'private.py'
        external.write_text('PRIVATE-SENTINEL')
        (self.root / 'commerce/linked.py').symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_verified_unpack_retains_bytes_and_uses_versioned_release(self):
        self.build()
        release = load('install_wsl').unpack(self.output, self.target)
        self.assertEqual((release / 'commerce/server.py').read_text(), 'print("synthetic")\n')
        self.assertEqual(release.parent, self.target / 'releases')
        self.assertEqual(load('install_wsl').unpack(self.output, self.target), release)

    def test_tampering_is_rejected_before_creating_a_release(self):
        self.build()
        self.rewrite({'phone-lab/commerce/server.py': b'changed'})
        with self.assertRaisesRegex(ValueError, 'hash'):
            load('install_wsl').unpack(self.output, self.target)
        self.assertFalse(self.target.exists())

    def test_unmanifested_traversal_is_rejected_without_writing_outside(self):
        self.build()
        self.rewrite({'../escape.py': b'bad'})
        with self.assertRaises(ValueError):
            load('install_wsl').unpack(self.output, self.target)
        self.assertFalse((self.root.parent / 'escape.py').exists())
        self.assertFalse(self.target.exists())

    def test_existing_release_edit_is_rejected_without_overwrite(self):
        self.build()
        installer = load('install_wsl')
        release = installer.unpack(self.output, self.target)
        path = release / 'commerce/server.py'
        path.write_text('local edit')
        with self.assertRaisesRegex(ValueError, 'existing_release'):
            installer.unpack(self.output, self.target)
        self.assertEqual(path.read_text(), 'local edit')

    def test_destination_symlink_is_rejected(self):
        self.build()
        outside = self.root.parent / 'outside'
        outside.mkdir()
        self.target.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            load('install_wsl').unpack(self.output, self.target)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
