"""The shared composition must preserve the original inline module styles."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UIBundleIntegrity(unittest.TestCase):
    def test_assistant_reading_and_generative_helpers_reach_every_shared_surface(self):
        names = ('copilot-evidence.js', 'copilot-interactions.js', 'generative-ui.js', 'copilot-ui.js')
        for bundle in ('app.js', 'product-workspace.bundle.js'):
            artifact = (ROOT / 'web' / bundle).read_text()
            offsets = []
            for name in names:
                source = (ROOT / 'web' / name).read_text().rstrip()
                self.assertEqual(artifact.count(source), 1, bundle + ': ' + name)
                offsets.append(artifact.index(source))
            self.assertEqual(offsets, sorted(offsets), 'Helpers must precede the composer')
        imports = (ROOT / 'workbench/src/assistant.tsx').read_text()
        self.assertEqual([imports.index('../../web/' + name) for name in names], sorted(imports.index('../../web/' + name) for name in names))
        manifest = json.loads((ROOT / 'web/workbench.sources.json').read_text())
        self.assertIn('web/copilot-interactions.js', manifest['sources'])

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
