from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness_local_bundle import prepare, local_link_lock


class LocalBundleTests(unittest.TestCase):
    def test_private_patch_does_not_rewrite_shared_template(self):
        root = Path(__file__).resolve().parents[1]
        original = (root / 'harness/cordis.patch.yml').read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            bundle = prepare(root, folder, sys.executable)
            self.assertFalse((bundle / 'index.js').is_symlink())
            self.assertIn((root / 'harness/index.js').as_uri(), (bundle / 'index.js').read_text())
            self.assertNotIn('<COMMERCE_MCP_SERVER_PATH>', (bundle / 'cordis.patch.yml').read_text())
        self.assertEqual(original, (root / 'harness/cordis.patch.yml').read_bytes())

    def test_only_local_import_changes_and_retry_is_stable(self):
        old = "lockfileVersion: '9.0'\nimporters:\n  .:\n    dependencies:\n      'other':\n        specifier: 1.2.3\n        version: 1.2.3\n\npackages:\n  'other': {}\n"
        result = local_link_lock(old, '@local/dsh-commerce', '/private/bundle')
        self.assertEqual(local_link_lock(result, '@local/dsh-commerce', '/private/bundle'), result)
        self.assertEqual(result.replace("      '@local/dsh-commerce':\n        specifier: \"link:/private/bundle\"\n        version: \"link:/private/bundle\"\n", ''), old)
