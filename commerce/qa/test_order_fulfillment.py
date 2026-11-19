"""Isolated order fulfillment receipts. No warehouse, carrier, payment or shop writes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class OrderFulfillmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Commerce(self.tmp.name)
        self.fulfillment = self.app.order_fulfillment
        self.scope = {'platform': 'ozon', 'store_ref': 'synthetic-store', 'market': 'RU'}

    def confirm(self, rows, synthetic=True, key='preview', store='synthetic-store'):
        header = ['order_id', 'line_id', 'sku', 'order_date', 'quantity', 'unit_price', 'currency']
        content = ','.join(header) + '\n' + '\n'.join(rows) + '\n'
        batch = self.app.order_imports.preview(
            filename='synthetic.csv', content=content,
            scope={'platform': 'ozon', 'store_ref': store, 'market': 'RU'}, synthetic=synthetic,
            field_mapping={name: name for name in header}, idempotency_key=key)
        return self.app.order_imports.confirm(batch['id'], batch['sha256'], True, key + '-confirm')

    def expected(self, batch, order_id='SYN-1', synthetic=True):
        listed = self.app.order_imports.orders(batch['id'], {
            'demo': synthetic, 'platform': 'ozon', 'store_id': batch['scope']['store_ref'], 'market': 'RU'})
        return [{'line_id': row['line_id'], 'source_sha256': row['source_sha256']}
                for row in listed['orders'] if row['order_id'] == order_id]

    def carton(self, size=30):
        return {'id': 'box', 'name': 'box', 'inner_cm': [size, size, size],
                'outer_cm': [size + 1, size + 1, size + 1], 'tare_kg': 0.1,
                'max_weight_kg': 20, 'packaging_cost': '1.00'}

    def packing(self, skus, size=10, carton=30):
        return {'origin': 'synthetic-origin', 'destination': 'synthetic-destination', 'ship_date': '2026-11-19',
                'packaging_currency': 'CNY', 'cartons': [self.carton(carton)],
                'specs': {sku: {'length_cm': size, 'width_cm': size, 'height_cm': size, 'weight_kg': 0.2} for sku in skus}}

    def lot(self, lot_id='LOT-A', sku='SYN-A', quantity=5, revision=0, key='lot', store='synthetic-store', synthetic=True):
        return self.fulfillment.save_lot(
            {'platform': 'ozon', 'store_ref': store, 'market': 'RU'}, lot_id, sku, quantity,
            'synthetic-bin', revision, synthetic, key)

    def allocate(self, batch, order='SYN-1', skus=('SYN-A',), key='allocate', synthetic=True, packing=None):
        return self.fulfillment.allocate(
            batch['id'], order, self.expected(batch, order, synthetic), synthetic, key,
            self.packing(skus) if packing is None else packing)

    def assert_local(self, receipt):
        for field in ('external_execution', 'order_processed', 'payment_authorized', 'purchase_submitted',
                      'shipment_submitted', 'warehouse_connected'):
            self.assertFalse(receipt[field])
        self.assertIn('不是付款', receipt['notice'])

    def test_unconfirmed_or_unknown_order_does_not_reserve(self):
        header = ['order_id', 'line_id', 'sku', 'order_date', 'quantity', 'unit_price', 'currency']
        content = ','.join(header) + '\nSYN-1,1,SYN-A,2026-11-01,2,12.50,CNY\n'
        preview = self.app.order_imports.preview(
            filename='synthetic.csv', content=content, scope={**self.scope}, synthetic=True,
            field_mapping={name: name for name in header}, idempotency_key='preview-only')
        with self.assertRaisesRegex(ValueError, 'fulfillment_order_not_confirmed'):
            self.fulfillment.allocate(preview['id'], 'SYN-1', [{'line_id': '1', 'source_sha256': '0' * 64}], True, 'early', self.packing(['SYN-A']))
        batch = self.confirm(['SYN-1,1,SYN-A,2026-11-01,2,12.50,CNY'])
        with self.assertRaisesRegex(ValueError, 'fulfillment_order_not_found'):
            self.fulfillment.allocate(batch['id'], 'OTHER', self.expected(batch), True, 'missing', self.packing(['SYN-A']))
        changed = self.expected(batch)
        changed[0] = {**changed[0], 'source_sha256': '0' * 64}
        with self.assertRaisesRegex(ValueError, 'fulfillment_source_changed'):
            self.fulfillment.allocate(batch['id'], 'SYN-1', changed, True, 'stale', self.packing(['SYN-A']))
        self.assertEqual(self.fulfillment.listing(self.scope, True)['items'], [])

    def test_inventory_receipt_reuses_original_task_and_replays_without_double_hold(self):
        batch = self.confirm(['SYN-1,1,SYN-A,2026-11-01,2,12.50,CNY'])
        self.lot(quantity=5)
        receipt = self.allocate(batch)
        again = self.allocate(batch)
        self.assertEqual(again['id'], receipt['id'])
        self.assertEqual(again['allocations'], receipt['allocations'])
        self.assertEqual(receipt['branch'], 'inventory')
        self.assertEqual(receipt['status'], 'draft_ready')
        self.assertFalse(receipt['split'])
        self.assertEqual(receipt['hold'], 'active')
        self.assertEqual(sum(row['quantity'] for row in receipt['allocations']), 2)
        self.assertEqual(receipt['allocations'][0]['lot_id'], 'LOT-A')
        self.assert_local(receipt)
        task = self.app.core.invoke('commerce_task_get', {'task_id': receipt['task_id']})
        self.assertEqual(task['status'], 'queued')
        self.assertEqual(task['input']['origin'], 'order_fulfillment')
        self.assertEqual(task['input']['order_id'], 'SYN-1')
        plan = self.app.shipping.get_plan(receipt['packing']['plan_id'])
        self.assertEqual(plan['sha256'], receipt['packing']['plan_sha256'])
        self.assertFalse(plan['shipment_submitted'])
        self.assertTrue(plan['review_required'])
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 2)
        with self.assertRaisesRegex(ValueError, 'fulfillment_idempotency_conflict'):
            self.fulfillment.allocate(batch['id'], 'SYN-1', self.expected(batch), True, 'allocate',
                                      self.packing(['SYN-A'], size=8))
        with self.assertRaisesRegex(ValueError, 'fulfillment_line_already_held'):
            self.allocate(batch, key='second')
        shown = self.app.invoke('commerce_order_fulfillment_get', {'receipt_id': receipt['id']}, client='test')
        self.assertEqual(shown['id'], receipt['id'])
        self.assertFalse(shown['order_processed'])

    def test_stockout_shares_one_procurement_draft_and_mixed_lots_split_parcels(self):
        batch = self.confirm(['SYN-1,1,SYN-A,2026-11-01,2,12.50,CNY', 'SYN-2,1,SYN-A,2026-11-01,3,9.00,CNY'])
        first = self.allocate(batch, 'SYN-1', key='buy-1')
        second = self.allocate(batch, 'SYN-2', key='buy-2')
        self.assertEqual(first['branch'], 'procurement')
        self.assertEqual(first['hold'], 'active')
        self.assertEqual(first['allocations'][0]['batch_id'], second['allocations'][0]['batch_id'])
        draft = first['procurement_batches'][0]
        self.assertEqual(draft['status'], 'draft')
        self.assertFalse(draft['payment_authorized'])
        self.assertFalse(draft['purchase_submitted'])
        self.assertEqual(sum(line['quantity'] for line in draft['lines']), 2)
        self.assertEqual(sum(line['quantity'] for line in second['procurement_batches'][0]['lines']), 5)
        self.assertNotEqual(first['task_id'], second['task_id'])
        self.lot(lot_id='LOT-M', sku='SYN-M', quantity=1, key='short')
        mixed = self.confirm(['SYN-3,1,SYN-M,2026-11-01,4,4.00,CNY'], key='mixed')
        receipt = self.allocate(mixed, 'SYN-3', skus=('SYN-M',), key='mixed-allocate')
        self.assertEqual(receipt['branch'], 'mixed')
        self.assertTrue(receipt['split'])
        self.assertEqual(sum(row['quantity'] for row in receipt['allocations'] if row['kind'] == 'inventory'), 1)
        self.assertEqual(sum(row['quantity'] for row in receipt['allocations'] if row['kind'] == 'procurement'), 3)
        self.assertEqual({row['source'] for row in receipt['parcels']}, {'inventory', 'procurement'})
        self.lot(lot_id='LOT-F1', sku='SYN-F', quantity=1, key='fifo-a')
        self.lot(lot_id='LOT-F2', sku='SYN-F', quantity=5, key='fifo-b')
        fifo_batch = self.confirm(['SYN-4,1,SYN-F,2026-11-01,4,4.00,CNY'], key='fifo')
        fifo = self.allocate(fifo_batch, 'SYN-4', skus=('SYN-F',), key='fifo-allocate')
        taken = {row['lot_id']: row['quantity'] for row in fifo['allocations'] if row['kind'] == 'inventory'}
        self.assertEqual(taken, {'LOT-F1': 1, 'LOT-F2': 3})

    def test_open_procurement_blocks_repeat_until_cancel_voids_the_draft(self):
        batch = self.confirm(['SYN-1,1,SYN-A,2026-11-01,2,2.00,CNY', 'SYN-1,2,SYN-B,2026-11-01,1,3.00,CNY'])
        receipt = self.allocate(batch, skus=('SYN-A', 'SYN-B'))
        self.assertEqual(receipt['hold'], 'active')
        self.assertEqual(receipt['branch'], 'procurement')
        with self.assertRaisesRegex(ValueError, 'fulfillment_line_already_held'):
            self.allocate(batch, skus=('SYN-A', 'SYN-B'), key='again')
        self.lot(quantity=5)
        with self.assertRaisesRegex(ValueError, 'fulfillment_line_already_held'):
            self.allocate(batch, skus=('SYN-A', 'SYN-B'), key='after-stock')
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 0)
        source = next(row['source_sha256'] for row in receipt['lines'] if row['line_id'] == '1')
        released = self.fulfillment.cancel(batch['id'], 'SYN-1', '1', source, True, 'cancel-draft')
        self.assertEqual(released['released_receipt_ids'], [receipt['id']])
        current = self.fulfillment.get(receipt['id'])
        self.assertEqual(current['hold'], 'released')
        self.assertTrue(all(line['voided'] for batch_doc in current['procurement_batches'] for line in batch_doc['lines']))
        resumed = self.allocate(batch, skus=('SYN-B',), key='resumed-b')
        previous = self.fulfillment.get(receipt['id'])
        old_lines = [line for batch_doc in previous['procurement_batches'] for line in batch_doc['lines'] if line['receipt_id'] == receipt['id']]
        self.assertEqual(sorted(line['quantity'] for line in old_lines), [1, 2])
        self.assertTrue(all(line['voided'] for line in old_lines))
        new_lines = [line for batch_doc in resumed['procurement_batches'] for line in batch_doc['lines'] if line['receipt_id'] == resumed['id']]
        self.assertEqual([(line['line_id'], line['quantity'], line['voided']) for line in new_lines], [('2', 1, False)])
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 0)

    def test_same_sku_lines_and_tight_cartons_keep_line_and_parcel_totals(self):
        batch = self.confirm(['SYN-1,1,SYN-A,2026-11-01,1,2.00,CNY', 'SYN-1,2,SYN-A,2026-11-01,1,2.00,CNY'])
        self.lot(quantity=2)
        receipt = self.allocate(batch)
        self.assertEqual(len(receipt['allocations']), 2)
        self.assertEqual(sum(row['quantity'] for row in receipt['parcels']), 2)
        split = self.confirm(['SYN-9,1,SYN-A,2026-11-01,3,2.00,CNY'], key='split')
        packed = self.allocate(split, 'SYN-9', key='split-allocate', packing=self.packing(['SYN-A'], size=10, carton=10))
        self.assertTrue(packed['split'])
        self.assertEqual(packed['packing']['box_count'], 3)
        self.assertEqual(sum(row['quantity'] for row in packed['parcels']), 3)
        self.assertFalse(packed['shipment_submitted'])

    def test_cancel_rechecks_source_releases_hold_and_blocks_only_that_line(self):
        batch = self.confirm(['SYN-1,1,SYN-A,2026-11-01,2,2.00,CNY', 'SYN-1,2,SYN-B,2026-11-01,1,3.00,CNY',
                              'SYN-2,1,SYN-A,2026-11-01,2,2.00,CNY'])
        self.lot(quantity=2)
        self.lot(lot_id='LOT-B', sku='SYN-B', quantity=2, key='lot-b')
        early = self.expected(batch)[0]
        with self.assertRaisesRegex(ValueError, 'fulfillment_source_changed'):
            self.fulfillment.cancel(batch['id'], 'SYN-1', '1', '0' * 64, True, 'bad-cancel')
        self.fulfillment.cancel(batch['id'], 'SYN-1', '1', early['source_sha256'], True, 'cancel-early')
        stopped = self.allocate(batch, skus=('SYN-B',))
        self.assertEqual(stopped['branch'], 'inventory')
        self.assertTrue(stopped['lines'][0]['cancelled'])
        self.assertEqual(stopped['lines'][0]['allocated'], [])
        self.assertEqual(stopped['lines'][1]['sku'], 'SYN-B')
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 0)
        fresh = self.confirm(['SYN-3,1,SYN-A,2026-11-01,2,2.00,CNY', 'SYN-3,2,SYN-B,2026-11-01,1,3.00,CNY'], key='fresh')
        held = self.allocate(fresh, 'SYN-3', skus=('SYN-A', 'SYN-B'), key='held')
        source = next(row['source_sha256'] for row in held['lines'] if row['line_id'] == '1')
        released = self.fulfillment.cancel(fresh['id'], 'SYN-3', '1', source, True, 'cancel-held')
        self.assertEqual(released['released_receipt_ids'], [held['id']])
        self.assertFalse(released['platform_cancelled'])
        self.assertFalse(released['shipment_submitted'])
        current = self.fulfillment.get(held['id'])
        self.assertEqual(current['hold'], 'released')
        self.assertFalse(current['release']['platform_cancelled'])
        again = self.fulfillment.cancel(fresh['id'], 'SYN-3', '1', source, True, 'cancel-again')
        self.assertEqual(again['released_receipt_ids'], [])
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['available'], 2)
        resumed = self.allocate(fresh, 'SYN-3', skus=('SYN-B',), key='resumed')
        self.assertEqual([row['sku'] for row in resumed['lines'] if row['allocated']], ['SYN-B'])
        self.assertTrue(resumed['lines'][0]['cancelled'])
        other = self.allocate(batch, 'SYN-2', key='other')
        self.assertEqual(other['branch'], 'inventory')
        self.assertEqual(sum(row['quantity'] for row in other['allocations']), 2)

    def test_task_cancel_does_not_release_stock_and_blocks_another_receipt(self):
        batch = self.confirm(['SYN-1,1,SYN-A,2026-11-01,2,2.00,CNY'])
        self.lot(quantity=2)
        receipt = self.allocate(batch)
        self.app.core.invoke('commerce_task_cancel', {'task_id': receipt['task_id']})
        self.assertEqual(self.fulfillment.get(receipt['id'])['task']['status'], 'cancelled')
        self.assertEqual(self.fulfillment.get(receipt['id'])['hold'], 'active')
        source = receipt['lines'][0]['source_sha256']
        self.fulfillment.cancel(batch['id'], 'SYN-1', '1', source, True, 'release')
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 0)
        with self.assertRaisesRegex(ValueError, 'fulfillment_task_cancelled'):
            self.allocate(batch, key='after-task-cancel')
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 0)

    def test_concurrent_orders_cannot_oversell_one_lot_or_duplicate_one_order(self):
        batch = self.confirm(['SYN-1,1,SYN-A,2026-11-01,4,2.00,CNY', 'SYN-2,1,SYN-A,2026-11-01,4,2.00,CNY'])
        self.lot(quantity=5)
        barrier = Barrier(2)

        def work(order, key):
            barrier.wait()
            return self.fulfillment.allocate(batch['id'], order, self.expected(batch, order), True, key, self.packing(['SYN-A']))

        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda item: work(*item), (('SYN-1', 'race-1'), ('SYN-2', 'race-2'))))
        inventory = sum(row['quantity'] for receipt in receipts for row in receipt['allocations'] if row['kind'] == 'inventory')
        procurement = sum(row['quantity'] for receipt in receipts for row in receipt['allocations'] if row['kind'] == 'procurement')
        self.assertEqual(inventory, 5)
        self.assertEqual(procurement, 3)
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 5)
        same = self.confirm(['SYN-8,1,SYN-A,2026-11-01,1,2.00,CNY'], key='same')
        self.lot(quantity=9, revision=1, key='top-up')
        start = Barrier(2)
        outcome = []

        def once(key):
            start.wait()
            try:
                outcome.append(('ok', self.allocate(same, 'SYN-8', key=key)))
            except ValueError as exc:
                outcome.append(('error', str(exc)))

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(once, ('same-a', 'same-b')))
        self.assertEqual(sorted(kind for kind, _ in outcome), ['error', 'ok'])
        self.assertEqual(next(value for kind, value in outcome if kind == 'error'), 'fulfillment_line_already_held')
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 6)

    def test_store_and_synthetic_scopes_do_not_share_lots(self):
        self.lot(quantity=9, store='other-store', key='other')
        batch = self.confirm(['SYN-1,1,SYN-A,2026-11-01,2,2.00,CNY'])
        receipt = self.allocate(batch)
        self.assertEqual(receipt['branch'], 'procurement')
        self.assertEqual(self.fulfillment.lots({'platform': 'ozon', 'store_ref': 'other-store', 'market': 'RU'}, True)['lots'][0]['held'], 0)
        self.lot(quantity=9, synthetic=True, key='synthetic-lot')
        live = self.confirm(['SYN-1,1,SYN-A,2026-11-01,2,2.00,CNY'], synthetic=False, key='live')
        self.lot(quantity=4, synthetic=False, key='live-lot')
        saved = self.allocate(live, synthetic=False, key='live-allocate')
        self.assertFalse(saved['synthetic'])
        self.assertEqual(saved['branch'], 'inventory')
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 0)
        self.assertEqual(self.fulfillment.lots(self.scope, False)['lots'][0]['held'], 2)
        self.assertEqual(self.fulfillment.listing(self.scope, False)['items'][0]['id'], saved['id'])
        self.assertNotIn(saved['id'], [item['id'] for item in self.fulfillment.listing(self.scope, True)['items']])

    def test_failed_packing_and_lot_revisions_leave_prior_holds_unchanged(self):
        batch = self.confirm(['SYN-1,1,SYN-A,2026-11-01,2,2.00,CNY'])
        first = self.lot(quantity=5)
        replay = self.lot(quantity=5)
        self.assertEqual(replay, first)
        with self.assertRaisesRegex(ValueError, 'fulfillment_idempotency_conflict'):
            self.lot(quantity=6)
        with self.assertRaisesRegex(ValueError, 'fulfillment_lot_exists'):
            self.lot(quantity=5, key='other-create')
        with self.assertRaisesRegex(ValueError, 'fulfillment_revision_conflict'):
            self.lot(quantity=6, revision=2, key='stale-revision')
        with self.assertRaisesRegex(ValueError, 'fulfillment_lot_sku_conflict'):
            self.lot(sku='SYN-B', quantity=5, revision=1, key='rename')
        receipt = self.allocate(batch)
        with self.assertRaisesRegex(ValueError, 'fulfillment_lot_below_held'):
            self.lot(quantity=1, revision=1, key='shrink')
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['quantity'], 5)
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 2)
        before = len(self.app.core.invoke('commerce_task_list', {})['tasks'])
        overflow = self.confirm(['SYN-7,1,SYN-A,2026-11-01,1,2.00,CNY'], key='overflow')
        with self.assertRaisesRegex(ValueError, 'fulfillment_packing_incomplete'):
            self.allocate(overflow, 'SYN-7', key='overflow-allocate', packing=self.packing(['SYN-A'], size=80, carton=10))
        self.assertEqual(len(self.app.core.invoke('commerce_task_list', {})['tasks']), before)
        self.assertEqual(len(self.app.shipping.state()['plans']), 1)
        self.assertEqual(self.fulfillment.lots(self.scope, True)['lots'][0]['held'], 2)
        self.assertEqual(receipt['id'], self.allocate(batch)['id'])
        source = (Path(__file__).resolve().parents[1] / 'mcp_server.py').read_text()
        for name in ('commerce_order_fulfillment_get', 'commerce_order_fulfillment_list', 'commerce_order_fulfillment_lots'):
            self.assertIn("'" + name + "'", source)
        self.assertNotIn("'commerce_order_fulfillment_allocate'", source)
