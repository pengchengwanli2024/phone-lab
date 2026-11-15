"""The shared composition must preserve the original inline module styles."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UIBundleIntegrity(unittest.TestCase):
    def test_existing_workspace_module_and_new_composition_are_both_present(self):
        artifact = (ROOT / 'web/style.css').read_text()
        for name in ('web/workspace-ui.css', 'ui/workspace.css'):
            with self.subTest(source=name):
                source = (ROOT / name).read_text().rstrip()
                self.assertEqual(artifact.count(source), 1, 'Each original module and the composition must be retained exactly once')

    def test_product_bundle_retains_its_editor_and_shared_composition(self):
        artifact = (ROOT / 'web/product-workspace.bundle.css').read_text()
        for name in ('web/product-workspace-ui.css', 'ui/workspace.css'):
            with self.subTest(source=name):
                self.assertTrue((ROOT / name).read_text().rstrip() in artifact, 'Product editor styles must remain integrated')
