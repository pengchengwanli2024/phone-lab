"""Synthetic contracts for source amounts, complete daily windows and raw stock."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from copy import deepcopy
from decimal import Decimal
import sys
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import operating_statistics as stats
import ozon_reader
from commerce_core import Core
from live_connections import LiveConnections


class Statistics(unittest.TestCase):
    def setUp(self):
        self.config = dict(lookback_days=3, fulfillment_modes=['OGL'], ozon_client_id='123', ozon_api_key='synthetic')
        self.current = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
        self.raw = dict(result=dict(data=[dict(dimensions=[dict(id=day)], metrics=metrics) for day, metrics in [
            ('2026-11-13', [0.1, 1]), ('2026-11-14', [0.2, 2]), ('2026-11-15', [0, 0])]], totals=[0.3, 3]), timestamp='platform-local-time')

    def fetch(self, raw=None):
        def request(path, body, client, key):
            self.assertEqual(path, '/v1/analytics/data')
            self.assertEqual(body['metrics'], ['revenue', 'ordered_units'])
            self.assertEqual(body['dimension'], ['day'])
            self.assertEqual(body['sort'], [])
            return raw or self.raw, 'a'*64
        return stats.fetch_sales(self.config, request, self.current)

    def test_source_decimal_totals_zero_days_currency_and_evidence(self):
        result = self.fetch()
        self.assertEqual(Decimal(result['amount']), Decimal('0.3'))
        self.assertEqual(result['ordered_units'], 3)
        self.assertEqual(result['records'][2]['amount'], '0')
        self.assertIsNone(result['currency'])
        self.assertEqual(result['date_to'], '2026-11-15')
        self.assertEqual(result['evidence'][0]['response_sha256'], 'a'*64)

    def test_incomplete_duplicate_or_mismatched_source_never_gets_zero_filled(self):
        for change in ('missing', 'duplicate', 'total', 'fractional_units', 'nan'):
            raw = deepcopy(self.raw)
            if change == 'missing':raw['result']['data'].pop()
            if change == 'duplicate':raw['result']['data'][1]['dimensions'][0]['id'] = '2026-11-13'
            if change == 'total':raw['result']['totals'][0] = 0.4
            if change == 'fractional_units':raw['result']['data'][0]['metrics'][1] = 0.5
            if change == 'nan':raw['result']['data'][0]['metrics'][0] = float('nan')
            with self.subTest(change=change), self.assertRaises(ozon_reader.ConnectionIssue):self.fetch(raw)

    def test_dashboard_scope_staleness_and_failed_sync_preserve_last_valid_sales(self):
        with tempfile.TemporaryDirectory() as directory:
            app=LiveConnections(Core(Path(directory)/'db.sqlite'),directory)
            app.configure(dict(ozon_client_id='123',ozon_api_key='synthetic-key',lookback_days=3))
            config=app.config();batch=self.fetch()
            app._publish(config['connection_id'],'sales',batch,config,False)
            report=app.workbench('commerce_dashboard',{})
            self.assertEqual(report['sales'],0.3)
            self.assertEqual(report['currency'],'')
            self.assertEqual(len(report['sales_summary']['records']),3)
            self.assertIsNone(app.workbench('commerce_dashboard',dict(platform='amazon'))['sales'])
            before=app.snapshot(config['connection_id'],'sales')['sha256']
            with patch('ozon_reader.fetch',side_effect=ozon_reader.ConnectionIssue('ozon_rate_limited',429)):
                app.lock.acquire();app._sync('synthetic-job',config)
            self.assertEqual(app.snapshot(config['connection_id'],'sales')['sha256'],before)
            self.assertFalse(app.status()['sync_enabled'])

    def test_inconsistent_stock_does_not_hide_negative_availability_by_clamping(self):
        snapshot=dict(data=dict(records=[dict(product_id='one',stocks=[dict(type='fbs',present=2,reserved=3)])]),observed_at='source-time',sha256='a'*64)
        inventory=stats.inventory_summary(snapshot,False)
        self.assertIsNone(inventory['groups'][0]['orderable_api'])
        self.assertEqual(inventory['groups'][0]['inconsistent_rows'],1)
        self.assertTrue(inventory['stale'])
