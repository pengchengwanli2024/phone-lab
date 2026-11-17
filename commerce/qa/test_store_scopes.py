"""Store grouping uses explicit identities, never names or external operations."""
from contextlib import nullcontext
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from service import Commerce
from live_connections import DEFAULTS
from test_ops_alerts import observation
from store_scopes import source_id


class StoreScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)
        self.app.live._save({**DEFAULTS, 'connection_id': 'fixture-account', 'store_label': '同名店铺'})
        self.app.operations.record(observation(store_id='同名店铺'), demo=False)

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.tmp.cleanup()

    def catalog(self, **args):
        return self.app.invoke('commerce_store_scope_list', args, 'test')

    def link(self, source, target, key='fixture-link', catalog=None):
        value = catalog or self.catalog()
        current = next(item for item in value['sources'] if item['id'] == source)
        return self.app.invoke('commerce_store_scope_link', dict(source_id=source, store_scope=target,
            expected_catalog_sha256=value['sha256'], expected_revision=current['revision'],
            confirmed=True, idempotency_key=key), 'test')

    def test_names_never_merge_and_read_has_no_business_writes(self):
        with self.app.core.db() as db:
            before = list(db.execute('SELECT * FROM store_scope_links'))
            tasks = list(db.execute('SELECT * FROM tasks'))
        value = self.catalog()
        self.assertEqual(len(value['stores']), 2)
        self.assertEqual({row['label'] for row in value['stores']}, {'同名店铺'})
        self.assertEqual(len(set(row['id'] for row in value['stores'])), 2)
        self.assertNotIn('ozon_api_key', json.dumps(value))
        with self.app.core.db() as db:
            self.assertEqual(before, list(db.execute('SELECT * FROM store_scope_links')))
            self.assertEqual(tasks, list(db.execute('SELECT * FROM tasks')))

    def test_explicit_link_unlink_and_idempotency_preserve_original_rows(self):
        manual = source_id('manual', 'ozon', 'RU', '同名店铺')
        live = source_id('live', 'ozon', 'RU', 'fixture-account')
        original = self.catalog()
        linked = self.link(manual, live, catalog=original)
        self.assertEqual(linked['mapping'][manual], live)
        self.assertEqual(len(linked['stores']), 1)
        self.assertEqual(self.link(manual, live, catalog=original)['mapping'], linked['mapping'])
        separate = self.link(manual, manual, key='fixture-unlink')
        self.assertEqual(len(separate['stores']), 2)
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ops_events').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM store_scope_events').fetchone()[0], 2)
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.link(manual, manual, catalog=original)

    def test_cross_market_demo_and_stale_catalog_rejected(self):
        old = self.catalog()
        self.app.operations.record(observation(event_id='other', store_id='同名店铺', market='KZ'))
        manual = source_id('manual', 'ozon', 'RU', '同名店铺')
        foreign = source_id('manual', 'ozon', 'KZ', '同名店铺')
        with self.assertRaisesRegex(ValueError, 'catalog_changed'):
            self.link(manual, manual, catalog=old)
        with self.assertRaisesRegex(ValueError, 'boundary_mismatch'):
            self.link(manual, foreign)
        self.assertEqual(self.catalog(demo=True)['sources'], [])
        with self.assertRaisesRegex(ValueError, 'store_scope_not_found'):
            self.app.invoke('commerce_store_workbench', {'demo': True, 'store_scope': manual}, 'test')

    def test_filtered_workbench_is_exact_and_keeps_global_attention_explicit(self):
        live = source_id('live', 'ozon', 'RU', 'fixture-account')
        manual = source_id('manual', 'ozon', 'RU', '同名店铺')
        with patch.object(self.app.live, 'alerts', return_value={'alerts': [dict(id='live', platform='ozon', market='RU', store_id='同名店铺')]}):
            view = self.app.invoke('commerce_store_workbench', {'store_scope': live}, 'test')
            self.assertEqual(view['imported_alerts']['alerts'], [])
            self.assertEqual(len(view['live_alerts']['alerts']), 1)
            self.link(manual, live)
            joined = self.app.invoke('commerce_store_workbench', {'store_scope': live}, 'test')
            self.assertEqual(len(joined['imported_alerts']['alerts']), 1)
            self.assertEqual(len(joined['live_alerts']['alerts']), 1)
            self.assertTrue(all(row['store_scope'] == live for row in joined['imported_alerts']['alerts']))

    def test_changed_account_never_inherits_prior_name_binding(self):
        live = source_id('live', 'ozon', 'RU', 'fixture-account')
        manual = source_id('manual', 'ozon', 'RU', '同名店铺')
        self.link(manual, live)
        self.app.live._save({**DEFAULTS, 'connection_id': 'different-account', 'store_label': '同名店铺'})
        current = self.catalog()
        item = next(row for row in current['sources'] if row['id'] == manual)
        self.assertFalse(item['link_current'])
        self.assertEqual(current['mapping'][manual], manual)

    def test_platform_revision_change_invalidates_explicit_alias(self):
        entry = dict(store_id='fixture-platform', platform='ozon', market='RU', label='店铺', revision='one')
        manual = source_id('manual', 'ozon', 'RU', '同名店铺')
        target = source_id('platform', 'ozon', 'RU', entry['store_id'])
        with patch.object(self.app.platforms, 'configs', side_effect=lambda: nullcontext({'x': entry})):
            self.link(manual, target)
            entry['revision'] = 'two'
            value = self.catalog()
        self.assertEqual(value['mapping'][manual], manual)
        self.assertFalse(next(row for row in value['sources'] if row['id'] == manual)['link_current'])
