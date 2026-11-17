"""Feature recipes select bounded source and trusted checks without executing them."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from engineering import EngineeringTeam
from test_engineering_team import Models


class FeatureMapTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        base = Path(temp.name);self.source = base / 'source';self.source.mkdir()
        (self.source / 'calc.py').write_text('def add(a,b):\n    return a-b\n')
        (self.source / 'test_calc.py').write_text('import unittest\nfrom calc import add\nclass Addition(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2,3),5)\n')
        (self.source / 'AGENTS.md').write_text('Preserve the acceptance checks.\n')
        self.recipe = {'id': 'addition', 'title': 'Addition arithmetic',
            'files': ['calc.py', 'test_calc.py'], 'writable_paths': ['calc.py'],
            'checks': [{'kind': 'python_unittest', 'paths': ['test_calc.py']}]}
        self.map_path = self.source / 'commerce/engineering/features.json'
        self.map_path.parent.mkdir(parents=True)
        self.write_map()
        service = type('Service', (), {})();service.state = base / 'state';service.state.mkdir()
        service.core = Core(service.state / 'commerce.sqlite');service.models = Models()
        self.team = EngineeringTeam(service, project_root=self.source);self.addCleanup(self.team.stop)

    def write_map(self, recipes=None):
        self.map_path.write_text(json.dumps({'schema': 1, 'features': recipes if recipes is not None else [self.recipe]}))

    def prepare(self):
        return self.team.invoke('commerce_engineering_prepare', {'feature_id': 'addition',
            'goal': 'Fix addition.', 'idempotency_key': 'mapped-one'})

    def task_count(self):
        with self.team.core.db() as db: return db.execute('SELECT count(*) FROM tasks').fetchone()[0]

    def test_search_and_prepare_are_readonly_and_include_exact_snapshot(self):
        found = self.team.invoke('commerce_engineering_feature_list', {'query': 'ARITHMETIC'})
        self.assertEqual([r['id'] for r in found['items']], ['addition'])
        self.assertEqual(self.team.feature_list('missing')['items'], [])
        result = self.prepare();order = result['work_order']
        self.assertEqual(order['files'], ['calc.py', 'test_calc.py'])
        self.assertEqual(order['writable_paths'], ['calc.py'])
        self.assertEqual(order['checks'], [{'kind': 'python_unittest', 'paths': ['test_calc.py']}])
        self.assertIn('AGENTS.md', result['feature']['source_manifest'])
        self.assertEqual(order['feature_ref']['source_sha256'], result['feature']['source_sha256'])
        self.assertEqual(self.task_count(), 0)
        self.assertEqual(self.team.status()['daily_model_calls'], 0)

    def test_mapped_order_runs_existing_pipeline_and_pins_planner_context(self):
        order = self.prepare()['work_order'];run = self.team.create(**order);seen = []
        def reply(stage, payload, route, cancelled):
            seen.append(payload.get('feature'))
            if stage == 'plan': return {'summary': 'Correct subtraction.', 'acceptance': ['2+3=5']}
            if stage == 'build': return {'summary': 'Add values.', 'edits': [{'path': 'calc.py', 'content': 'def add(a,b):\n    return a+b\n'}]}
            return {'decision': 'approve', 'reason': 'Acceptance passed.'}
        self.team.configure(True)
        with patch.object(self.team, '_model', side_effect=reply): self.assertTrue(self.team.run_once())
        result = self.team.get(run['id'])
        self.assertEqual(result['status'], 'awaiting_review')
        self.assertEqual(result['request']['feature_ref'], order['feature_ref'])
        self.assertEqual([r['id'] for r in seen], ['addition'] * 3)
        self.assertEqual(result['verification']['candidate'][0]['status'], 'passed')
        self.assertIn('return a-b', (self.source / 'calc.py').read_text())

    def test_source_or_constraints_drift_rejects_prepared_order_before_task_creation(self):
        for filename in ('calc.py', 'AGENTS.md'):
            with self.subTest(filename=filename):
                original = (self.source / filename).read_text();order = self.prepare()['work_order']
                (self.source / filename).write_text(original + '\n')
                with self.assertRaisesRegex(ValueError, 'engineering_feature_source_changed'): self.team.create(**order)
                (self.source / filename).write_text(original)
        self.assertEqual(self.task_count(), 0)

    def test_recipe_drift_and_scope_tampering_rejected(self):
        order = self.prepare()['work_order'];self.recipe['title'] = 'Changed contract';self.write_map()
        with self.assertRaisesRegex(ValueError, 'engineering_feature_changed'): self.team.create(**order)
        order = self.prepare()['work_order'];order['writable_paths'].append('test_calc.py')
        with self.assertRaises(ValueError): self.team.create(**order)
        self.assertEqual(self.task_count(), 0)

    def test_mapping_cannot_be_forged_and_manual_orders_remain_supported(self):
        for value in ({}, {'id': 'addition'}, {'id': '../outside', 'recipe_sha256': '0' * 64, 'source_sha256': '0' * 64}):
            order = self.prepare()['work_order'];order['feature_ref'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): self.team.create(**order)
        order = self.prepare()['work_order'];del order['feature_ref'];run = self.team.create(**order)
        self.assertNotIn('feature_ref', run['request'])

    def test_duplicate_request_returns_original_after_source_changes(self):
        order = self.prepare()['work_order'];first = self.team.create(**order)
        (self.source / 'calc.py').write_text('def add(a,b):\n    return a+b\n')
        self.assertEqual(self.team.create(**order)['id'], first['id'])
        self.assertEqual(self.task_count(), 1)

    def test_recipe_changed_while_queued_stops_before_model_call(self):
        run = self.team.create(**self.prepare()['work_order'])
        self.recipe['title'] = 'Changed after queue';self.write_map();self.team.configure(True)
        with patch.object(self.team, '_model') as model:
            self.assertTrue(self.team.run_once());model.assert_not_called()
        result = self.team.get(run['id'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'engineering_feature_changed')
        self.assertEqual(self.team.status()['daily_model_calls'], 0)

    def test_invalid_catalog_shapes_reject_without_execution(self):
        malformed = [None, {'schema': True, 'features': [self.recipe]},
            {'schema': 1, 'features': [self.recipe, self.recipe]},
            {'schema': 1, 'features': [{**self.recipe, 'command': 'echo unsafe'}]},
            {'schema': 1, 'features': [{**self.recipe, 'files': 'calc.py'}]},
            {'schema': 1, 'features': [{**self.recipe, 'id': '../bad'}]}]
        for value in malformed:
            with self.subTest(value=value):
                self.map_path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): self.team.feature_list()
        self.assertEqual(self.task_count(), 0)

    def test_catalog_and_source_symlinks_or_private_paths_rejected(self):
        for recipe in ({**self.recipe, 'files': ['.local/private.py']},
                       {**self.recipe, 'writable_paths': ['test_calc.py']},
                       {**self.recipe, 'checks': [{'kind': 'shell', 'paths': ['calc.py']}]}):
            with self.subTest(recipe=recipe):
                self.write_map([recipe])
                with self.assertRaises(ValueError): self.team.feature_get('addition')
        self.write_map();original = self.map_path.read_text();outside = self.source / 'other.json';outside.write_text(original)
        self.map_path.unlink();self.map_path.symlink_to(outside)
        with self.assertRaises(ValueError): self.team.feature_list()

    def test_prepared_order_survives_restart_but_cannot_bypass_current_map(self):
        order = self.prepare()['work_order'];other = EngineeringTeam(self.team.service, project_root=self.source);self.addCleanup(other.stop)
        self.assertEqual(other.create(**order)['request']['feature_ref'], order['feature_ref'])
        with self.assertRaisesRegex(ValueError, 'engineering_feature_not_found'): other.feature_get('unknown')
        for query in (None, 12, 'x' * 101, '\x00'):
            with self.subTest(query=query), self.assertRaises(ValueError): other.feature_list(query)

    def test_service_schemas_and_annotations_expose_readonly_preparation(self):
        from service import Commerce, TOOLS
        import mcp_server
        import contextlib
        with tempfile.TemporaryDirectory() as temp:
            app = Commerce(temp)
            try:
                app.engineering.stop();app.engineering = self.team
                catalog = app.invoke('commerce_engineering_feature_list', {}, 'test')
                self.assertEqual(catalog['total'], 1)
                self.assertIn('commerce_engineering_prepare', {r[0] for r in TOOLS})
            finally:
                app.agent_runtime.stop();app.autonomy.stop()
        messages = b'{"id":1,"method":"initialize","params":{}}\n{"id":2,"method":"tools/list"}\n'
        out = io.StringIO();inp = type('Input', (), {'buffer': io.BytesIO(messages)})()
        with patch.object(mcp_server, 'ensure'), patch.object(sys, 'stdin', inp), patch.object(sys, 'argv', ['mcp', 'test']), contextlib.redirect_stdout(out): mcp_server.main()
        tools = {r['name']: r for r in json.loads(out.getvalue().splitlines()[1])['result']['tools']}
        for name in ('feature_list', 'feature_get', 'prepare'):
            self.assertTrue(tools['commerce_engineering_' + name]['annotations']['readOnlyHint'])


if __name__ == '__main__': unittest.main()
