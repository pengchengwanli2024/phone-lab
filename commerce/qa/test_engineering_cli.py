"""CLI input limits must apply before reading the complete work order."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
import json
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engineering_cli


class BoundedReader(io.StringIO):
    def read(self, size=-1):
        if not 0 < size <= 12001:
            raise AssertionError('Work-order file must be read with an explicit upper bound')
        return super().read(size)


class WorkOrderInput(unittest.TestCase):
    def submit(self, content, *, bounded=False):
        stream = BoundedReader(content) if bounded else io.StringIO(content)
        with patch.object(sys, 'argv', ['engineering_cli', 'submit', 'fixture.json']), \
                patch.object(Path, 'open', return_value=stream), \
                patch.object(engineering_cli, 'request', return_value={'accepted': True}) as request, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            engineering_cli.main()
            return request.call_args

    def test_oversized_file_rejected_before_full_read(self):
        with self.assertRaises(SystemExit) as failure: self.submit('x' * 13000, bounded=True)
        self.assertEqual(failure.exception.code, 2)

    def test_valid_object_preserves_existing_submit_contract(self):
        call = self.submit('{"goal":"source task"}')
        self.assertEqual(call.args, ('commerce_engineering_create', {'goal': 'source task'}, 'codex'))

    def test_non_object_rejected(self):
        with self.assertRaises(SystemExit): self.submit('[]')


class FeatureCommands(unittest.TestCase):
    def command(self, args, result):
        out = io.StringIO()
        with patch.object(sys, 'argv', ['engineering_cli', *args]), \
                patch.object(engineering_cli, 'request', return_value=result) as request, \
                contextlib.redirect_stdout(out):
            engineering_cli.main()
        return request.call_args.args, json.loads(out.getvalue())

    def test_feature_search_and_get_keep_explicit_selection(self):
        call, result = self.command(['features', 'CLI'], {'items': []})
        self.assertEqual(call, ('commerce_engineering_feature_list', {'query': 'CLI'}, 'codex'))
        self.assertEqual(result, {'items': []})
        call, _ = self.command(['feature', 'engineering-cli'], {'id': 'engineering-cli'})
        self.assertEqual(call, ('commerce_engineering_feature_get', {'feature_id': 'engineering-cli'}, 'codex'))

    def test_prepare_prints_only_submit_compatible_order_and_does_not_submit(self):
        order = {'goal': 'Improve bounded input.', 'feature_ref': {'id': 'engineering-cli'}}
        call, result = self.command(['prepare', 'engineering-cli', '--goal', order['goal'], '--key', 'one'],
            {'work_order': order, 'queued': False})
        self.assertEqual(call, ('commerce_engineering_prepare', {'feature_id': 'engineering-cli',
            'goal': order['goal'], 'idempotency_key': 'one', 'kind': 'bugfix'}, 'codex'))
        self.assertEqual(result, order)


if __name__ == '__main__': unittest.main()
