"""Bounded cost contract generation and stable wire identities, synthetic data only."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a2ui import cost
from operations_analysis import UNIT_FIELDS

ROOT = Path(__file__).resolve().parents[1]


class ComponentContractTests(unittest.TestCase):
    def test_contract_is_the_source_of_server_field_labels_and_bounds(self):
        path = ROOT / 'a2ui' / 'contract.json'
        self.assertTrue(path.exists(), 'canonical cost contract must exist')
        contract = json.loads(path.read_text())
        self.assertEqual(tuple(field['key'] for field in contract['fields']), UNIT_FIELDS)
        changed = copy.deepcopy(contract)
        changed['fields'].reverse()
        next(f for f in changed['fields'] if f['key'] == 'commission_rate')['label'] = '测试佣金'
        nodes = cost.field_nodes(changed['fields'])
        rate = next(n for n in nodes if n['id'] == 'field_commission_rate')
        self.assertEqual(rate, {'id': 'field_commission_rate', 'component': 'NumberField', 'label': '测试佣金', 'value': {'@path': '/input/commission_rate'}, 'minimum': 0, 'maximum': 1, 'unit': 'fraction'})
        self.assertEqual(nodes[0]['id'], 'field_ad_rate')

    def test_generator_checks_each_artifact_and_derives_changed_labels(self):
        generator = ROOT / 'a2ui' / 'build_contract.py'
        self.assertTrue(generator.exists(), 'deterministic contract generator must exist')
        spec = importlib.util.spec_from_file_location('build_cost_contract', generator)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        contract = json.loads((ROOT / 'a2ui' / 'contract.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            outputs = module.render(contract)
            for name, text in outputs.items():
                target = Path(tmp) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
            self.assertEqual(module.synchronize(contract, Path(tmp), check=True), [])
            (Path(tmp) / 'a2ui/catalog.json').write_text('{}')
            self.assertEqual(module.synchronize(contract, Path(tmp), check=True), ['a2ui/catalog.json'])
            self.assertEqual((Path(tmp) / 'a2ui/catalog.json').read_text(), '{}')
            self.assertEqual(module.synchronize(contract, Path(tmp), check=False), ['a2ui/catalog.json'])
            changed = copy.deepcopy(contract)
            changed['fields'][1]['label'] = '售价新名称'
            rendered = module.render(changed)
            self.assertIn('售价新名称', rendered['workbench/src/cost-contract.ts'])
            self.assertEqual(json.loads(rendered['a2ui/catalog.json']), cost.CATALOG)

    def test_existing_wire_stays_valid_without_new_field_props(self):
        payload = cost.messages('cost_' + 'a' * 32, {'commission_rate': .073}, None)
        original = copy.deepcopy(payload)
        nodes = payload[0]['createSurface']['components']
        for node in nodes:
            if node['component'] in ('CurrencyField', 'NumberField'):
                node['label'] = '任意展示名称'
                self.assertNotIn('fieldKey', node)
        next(n for n in nodes if n['id'] == 'fields')['children'].reverse()
        self.assertTrue(cost.validate_surface(payload))
        self.assertEqual(original[0]['createSurface']['dataModel']['input']['commission_rate'], .073)
        for path in ('/__proto__/bad', '/input/unknown', '/display/status'):
            bad = copy.deepcopy(payload)
            next(n for n in bad[0]['createSurface']['components'] if n['id'] == 'field_price')['value']['@path'] = path
            with self.assertRaises(ValueError):
                cost.validate_surface(bad)


if __name__ == '__main__':
    unittest.main()
