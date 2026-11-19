"""Local inventory, procurement and packing receipts for one confirmed order.

The receipt continues the original order task. It reserves registered local
lots, opens a procurement draft for the shortfall, and stores an existing
shipping plan when the units fit. Nothing here pays a supplier, books a
carrier, cancels a marketplace order, or marks the order processed.
"""
import json
import re
from collections import Counter
from datetime import date, datetime, timezone

from business_workflows.store import digest, encoded
from commerce_core import PLATFORMS

READ_ONLY = frozenset({
    'commerce_order_fulfillment_get',
    'commerce_order_fulfillment_list',
    'commerce_order_fulfillment_lots',
})
MAX_LOTS = 50
MAX_UNITS = 500
_PACKING = frozenset({'origin', 'destination', 'ship_date', 'packaging_currency', 'cartons', 'specs'})
_SPEC = frozenset({'length_cm', 'width_cm', 'height_cm', 'weight_kg', 'rotation_allowed', 'no_stack'})
_NOTICE = '本机隔离回执。库存预留、采购草稿和装箱草稿都不是付款、供应商下单、到货、揽收或订单已处理。'
_LOT_NOTICE = '本地库存批次。数量是本机登记，不是仓库实盘或平台可售库存。'
_CANCEL_NOTICE = '只记录本机取消并释放本地预留。没有取消平台订单，也没有撤回外部发货。'


def _text(value, field, limit):
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('fulfillment_invalid_' + field)
    return value


def _key(value):
    return _text(value, 'idempotency_key', 160)


def _scope(value):
    if type(value) is not dict or set(value) != {'platform', 'store_ref', 'market'}:
        raise ValueError('fulfillment_invalid_scope')
    if value['platform'] not in (*PLATFORMS, 'local'):
        raise ValueError('fulfillment_invalid_platform')
    if value['store_ref'] == 'all':
        raise ValueError('fulfillment_invalid_store_ref')
    _text(value['store_ref'], 'store_ref', 100)
    if type(value['market']) is not str or not re.fullmatch(r'[A-Z]{2}', value['market']):
        raise ValueError('fulfillment_invalid_market')
    return {'platform': value['platform'], 'store_ref': value['store_ref'], 'market': value['market']}


def _bool(value, field):
    if type(value) is not bool:
        raise ValueError('fulfillment_invalid_' + field)
    return value


def _quantity(value):
    if type(value) is not int or not 0 <= value <= 100000:
        raise ValueError('fulfillment_invalid_quantity')
    return value


def _revision(value):
    if type(value) is not int or not 0 <= value <= 1000000:
        raise ValueError('fulfillment_invalid_revision')
    return value


def _sha(value):
    if type(value) is not str or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('fulfillment_invalid_source_sha256')
    return value


def _scope_key(scope, synthetic):
    return digest({**scope, 'synthetic': synthetic})


def _line_key(order_id, line_id):
    return digest([order_id, line_id])


def _expected(value):
    if type(value) is not list or not 1 <= len(value) <= 100:
        raise ValueError('fulfillment_invalid_expected_lines')
    rows, seen = [], set()
    for row in value:
        if type(row) is not dict or set(row) != {'line_id', 'source_sha256'}:
            raise ValueError('fulfillment_invalid_expected_lines')
        line_id = _text(row['line_id'], 'line_id', 128)
        if line_id in seen:
            raise ValueError('fulfillment_duplicate_line')
        seen.add(line_id)
        rows.append({'line_id': line_id, 'source_sha256': _sha(row['source_sha256'])})
    return sorted(rows, key=lambda item: item['line_id'])


def _number(value, field, positive):
    if type(value) is bool or type(value) not in (int, float):
        raise ValueError('fulfillment_invalid_' + field)
    if value != value or value in (float('inf'), float('-inf')) or (positive and value <= 0) or value < 0 or value > 1000000:
        raise ValueError('fulfillment_invalid_' + field)
    return value


def _packing(value):
    if value is None:
        return None
    if type(value) is not dict or set(value) != _PACKING:
        raise ValueError('fulfillment_invalid_packing')
    origin = _text(value['origin'], 'origin', 100)
    destination = _text(value['destination'], 'destination', 100)
    ship_date = value['ship_date']
    if type(ship_date) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', ship_date):
        raise ValueError('fulfillment_invalid_ship_date')
    date.fromisoformat(ship_date)
    currency = value['packaging_currency']
    if type(currency) is not str or not re.fullmatch(r'[A-Z]{3}', currency):
        raise ValueError('fulfillment_invalid_currency')
    cartons = value['cartons']
    if type(cartons) is not list or not 1 <= len(cartons) <= 12 or any(type(row) is not dict for row in cartons):
        raise ValueError('fulfillment_invalid_cartons')
    specs_in = value['specs']
    if type(specs_in) is not dict or not specs_in or len(specs_in) > 100:
        raise ValueError('fulfillment_invalid_specs')
    specs = {}
    for sku, spec in specs_in.items():
        sku = _text(sku, 'sku', 128)
        if type(spec) is not dict or not {'length_cm', 'width_cm', 'height_cm', 'weight_kg'} <= set(spec) or set(spec) - _SPEC:
            raise ValueError('fulfillment_invalid_spec')
        normalized = {field: _number(spec[field], field, field != 'weight_kg') for field in ('length_cm', 'width_cm', 'height_cm', 'weight_kg')}
        for field in ('rotation_allowed', 'no_stack'):
            if field in spec:
                normalized[field] = _bool(spec[field], field)
        specs[sku] = normalized
    return {'origin': origin, 'destination': destination, 'ship_date': ship_date,
            'packaging_currency': currency, 'cartons': cartons, 'specs': specs}


class OrderFulfillment:
    def __init__(self, service):
        self.service, self.core = service, service.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS order_fulfillment_lots(scope_key TEXT NOT NULL, lot_id TEXT NOT NULL, document TEXT NOT NULL, PRIMARY KEY(scope_key, lot_id))')
            db.execute('CREATE TABLE IF NOT EXISTS order_fulfillment_requests(key TEXT PRIMARY KEY, sha256 TEXT NOT NULL, result TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS order_fulfillment_receipts(id TEXT PRIMARY KEY, scope_key TEXT NOT NULL, sha256 TEXT NOT NULL, document TEXT NOT NULL, hold TEXT NOT NULL, release_json TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS order_fulfillment_cancels(scope_key TEXT NOT NULL, line_key TEXT NOT NULL, source_sha256 TEXT NOT NULL, PRIMARY KEY(scope_key, line_key))')
            db.execute('CREATE TABLE IF NOT EXISTS order_fulfillment_procurement(id TEXT PRIMARY KEY, scope_key TEXT NOT NULL, sku TEXT NOT NULL, document TEXT NOT NULL)')

    def invoke(self, name, args):
        return {'lot_save': self.save_lot, 'allocate': self.allocate, 'cancel': self.cancel, 'get': self.get,
                'list': self.listing, 'lots': self.lots}[name.removeprefix('commerce_order_fulfillment_')](**args)

    def _once(self, db, key, body, make):
        fingerprint = digest(body)
        old = db.execute('SELECT sha256, result FROM order_fulfillment_requests WHERE key=?', (_key(key),)).fetchone()
        if old:
            if old[0] != fingerprint:
                raise ValueError('fulfillment_idempotency_conflict')
            return json.loads(old[1])
        result = make()
        db.execute('INSERT INTO order_fulfillment_requests VALUES (?,?,?)', (key, fingerprint, encoded(result)))
        return result

    def _held(self, db, scope_key):
        totals = Counter()
        for (raw,) in db.execute("SELECT document FROM order_fulfillment_receipts WHERE scope_key=? AND hold='active'", (scope_key,)):
            for row in json.loads(raw)['allocations']:
                if row['kind'] == 'inventory':
                    totals[row['lot_id']] += row['quantity']
        return totals

    def _lots(self, db, scope_key):
        held = self._held(db, scope_key)
        lots = []
        for lot_id, raw in db.execute('SELECT lot_id, document FROM order_fulfillment_lots WHERE scope_key=? ORDER BY lot_id', (scope_key,)):
            doc = json.loads(raw)
            if held[lot_id] > doc['quantity']:
                raise ValueError('fulfillment_hold_inconsistent')
            lots.append({**doc, 'held': held[lot_id], 'available': doc['quantity'] - held[lot_id]})
        return lots

    def save_lot(self, scope, lot_id, sku, quantity, location_ref, expected_revision, synthetic, idempotency_key):
        scope = _scope(scope)
        body = {'action': 'lot_save', 'scope': scope, 'lot_id': _text(lot_id, 'lot_id', 64), 'sku': _text(sku, 'sku', 128),
                'quantity': _quantity(quantity), 'location_ref': _text(location_ref, 'location_ref', 80),
                'expected_revision': _revision(expected_revision), 'synthetic': _bool(synthetic, 'synthetic')}
        with self.core.atomic() as db:
            return self._once(db, idempotency_key, body, lambda: self._save_lot(db, body))

    def _save_lot(self, db, body):
        scope_key = _scope_key(body['scope'], body['synthetic'])
        current = db.execute('SELECT document FROM order_fulfillment_lots WHERE scope_key=? AND lot_id=?', (scope_key, body['lot_id'])).fetchone()
        previous = json.loads(current[0]) if current else None
        if body['expected_revision'] == 0:
            if previous:
                raise ValueError('fulfillment_lot_exists')
            if db.execute('SELECT COUNT(*) FROM order_fulfillment_lots WHERE scope_key=?', (scope_key,)).fetchone()[0] >= MAX_LOTS:
                raise ValueError('fulfillment_lot_limit')
            revision = 1
        else:
            if previous is None or previous['revision'] != body['expected_revision']:
                raise ValueError('fulfillment_revision_conflict')
            if previous['sku'] != body['sku']:
                raise ValueError('fulfillment_lot_sku_conflict')
            revision = body['expected_revision'] + 1
        held = self._held(db, scope_key)[body['lot_id']]
        if body['quantity'] < held:
            raise ValueError('fulfillment_lot_below_held')
        doc = {'lot_id': body['lot_id'], 'sku': body['sku'], 'quantity': body['quantity'], 'location_ref': body['location_ref'],
               'revision': revision, 'synthetic': body['synthetic']}
        if current:
            db.execute('UPDATE order_fulfillment_lots SET document=? WHERE scope_key=? AND lot_id=?', (encoded(doc), scope_key, body['lot_id']))
        else:
            db.execute('INSERT INTO order_fulfillment_lots VALUES (?,?,?)', (scope_key, body['lot_id'], encoded(doc)))
        return {'schema': 'commerce-order-fulfillment-lot-v1', **doc, 'held': held, 'available': body['quantity'] - held,
                'scope': body['scope'], 'external_execution': False, 'warehouse_connected': False, 'notice': _LOT_NOTICE}

    def lots(self, scope, synthetic):
        scope = _scope(scope)
        _bool(synthetic, 'synthetic')
        with self.core.db() as db:
            rows = self._lots(db, _scope_key(scope, synthetic))
        return {'lots': rows, 'scope': scope, 'synthetic': synthetic, 'external_execution': False,
                'warehouse_connected': False, 'notice': _LOT_NOTICE}

    def _order_lines(self, batch_id, order_id, synthetic):
        batch = self.service.order_imports.get(batch_id)
        if batch['status'] not in ('confirmed', 'partial'):
            raise ValueError('fulfillment_order_not_confirmed')
        if batch['synthetic'] is not synthetic:
            raise ValueError('fulfillment_scope_mismatch')
        scope = _scope({'platform': batch['scope']['platform'], 'store_ref': batch['scope']['store_ref'], 'market': batch['scope']['market']})
        if batch['scope'] != scope:
            raise ValueError('fulfillment_scope_mismatch')
        listed = self.service.order_imports.orders(batch_id, {'demo': synthetic, 'platform': scope['platform'], 'store_id': scope['store_ref'], 'market': scope['market']})
        lines = [row for row in listed['orders'] if row['order_id'] == order_id]
        if not lines:
            raise ValueError('fulfillment_order_not_found')
        return batch, scope, sorted(lines, key=lambda row: row['line_id'])

    def allocate(self, import_batch_id, order_id, expected_lines, synthetic, idempotency_key, packing=None):
        body = {'action': 'allocate', 'import_batch_id': _text(import_batch_id, 'import_batch_id', 80),
                'order_id': _text(order_id, 'order_id', 128), 'expected_lines': _expected(expected_lines),
                'synthetic': _bool(synthetic, 'synthetic'), 'packing': _packing(packing)}
        with self.core.atomic() as db:
            receipt_id = self._once(db, idempotency_key, body, lambda: self._allocate(db, body, idempotency_key))
        return self.get(receipt_id)

    def _task(self, batch, scope, order_id, lines):
        data = {'origin': 'order_fulfillment', 'demo': batch['synthetic'], 'platform': scope['platform'],
                'store_ref': scope['store_ref'], 'market': scope['market'], 'order_id': order_id,
                'import_batch_id': batch['id'], 'batch_sha256': batch['sha256'],
                'line_ids': [row['line_id'] for row in lines]}
        task = self.core.invoke('commerce_task_create', {'kind': 'draft', 'input': data,
                                                          'idempotency_key': 'order-fulfillment-' + digest(data)[:48]})
        if task['status'] != 'queued':
            raise ValueError('fulfillment_task_cancelled' if task['status'] == 'cancelled' else 'fulfillment_task_unavailable')
        return task, data

    def _active_holds(self, db, scope_key, order_id, line_ids):
        wanted = set(line_ids)
        for (raw,) in db.execute("SELECT document FROM order_fulfillment_receipts WHERE scope_key=? AND hold='active'", (scope_key,)):
            doc = json.loads(raw)
            if doc['order_id'] == order_id and wanted & {row['line_id'] for row in doc['lines'] if not row['cancelled']}:
                raise ValueError('fulfillment_line_already_held')

    def _allocate(self, db, body, key):
        batch, scope, lines = self._order_lines(body['import_batch_id'], body['order_id'], body['synthetic'])
        actual = [{'line_id': row['line_id'], 'source_sha256': row['source_sha256']} for row in lines]
        if actual != body['expected_lines']:
            raise ValueError('fulfillment_source_changed')
        scope_key = _scope_key(scope, body['synthetic'])
        cancelled = set()
        for row in lines:
            marker = db.execute('SELECT source_sha256 FROM order_fulfillment_cancels WHERE scope_key=? AND line_key=?',
                                (scope_key, _line_key(body['order_id'], row['line_id']))).fetchone()
            if marker:
                if marker[0] != row['source_sha256']:
                    raise ValueError('fulfillment_source_changed')
                cancelled.add(row['line_id'])
        active = [row for row in lines if row['line_id'] not in cancelled]
        self._active_holds(db, scope_key, body['order_id'], [row['line_id'] for row in active])
        allocations, parcels, plan = [], [], None
        branch = 'cancelled'
        if active:
            packing = body['packing']
            if packing is None:
                raise ValueError('fulfillment_packing_required')
            skus = {row['sku'] for row in active}
            if set(packing['specs']) != skus:
                raise ValueError('fulfillment_packing_spec_mismatch')
            if sum(row['quantity'] for row in active) > MAX_UNITS or len(skus) > 100:
                raise ValueError('fulfillment_unit_limit')
        task, _ = self._task(batch, scope, body['order_id'], lines)
        if active:
            available = {lot['lot_id']: lot for lot in self._lots(db, scope_key)}
            ordered = [lot for lot in available.values() if lot['available'] > 0]
            shortfalls = []
            for line in active:
                remaining = line['quantity']
                for lot in ordered:
                    if lot['sku'] != line['sku'] or lot['available'] <= 0 or remaining <= 0:
                        continue
                    take = min(lot['available'], remaining)
                    lot['available'] -= take
                    remaining -= take
                    allocations.append({'kind': 'inventory', 'lot_id': lot['lot_id'], 'sku': line['sku'],
                                        'order_id': body['order_id'], 'line_id': line['line_id'], 'quantity': take})
                if remaining:
                    shortfalls.append((line, remaining))
            receipt_id = 'fulfill_' + digest(['allocate', key, body])[:24]
            groups = {}
            stock_counts, buy_counts = Counter(), Counter()
            for row in allocations:
                stock_counts[row['sku']] += row['quantity']
            procurement = {}
            for line, remaining in shortfalls:
                buy_counts[line['sku']] += remaining
                batch_id = 'procure_' + digest([scope_key, line['sku']])[:24]
                procurement.setdefault(batch_id, {'sku': line['sku'], 'lines': []})
                procurement[batch_id]['lines'].append({'receipt_id': receipt_id, 'order_id': body['order_id'], 'line_id': line['line_id'], 'quantity': remaining, 'voided': False})
                allocations.append({'kind': 'procurement', 'batch_id': batch_id, 'sku': line['sku'],
                                    'order_id': body['order_id'], 'line_id': line['line_id'], 'quantity': remaining})
            for source, counts in (('inventory', stock_counts), ('procurement', buy_counts)):
                for sku, quantity in sorted(counts.items()):
                    spec = packing['specs'][sku]
                    groups.setdefault(source, {'recipient_ref': body['order_id'], 'items': []})
                    groups[source]['items'].append({'group_id': source, 'recipient_ref': body['order_id'], 'sku': sku, 'quantity': quantity, **spec})
            shipping_input = {'mode': 'buyer', 'origin': packing['origin'], 'destination': packing['destination'],
                              'ship_date': packing['ship_date'], 'packaging_currency': packing['packaging_currency'],
                              'items': [item for source in ('inventory', 'procurement') for item in groups.get(source, {}).get('items', [])],
                              'cartons': packing['cartons'], 'synthetic': body['synthetic']}
            plan = self.service.shipping.compute_plan(shipping_input, persist=True)
            chosen = plan['variants'].get('space')
            if not chosen or not chosen['complete'] or plan.get('shipment_submitted') or plan.get('review_required') is not True:
                raise ValueError('fulfillment_packing_incomplete' if not chosen or not chosen['complete'] else 'fulfillment_packing_not_a_draft')
            for group in chosen['groups']:
                if group['group_id'] not in ('inventory', 'procurement'):
                    raise ValueError('fulfillment_packing_incomplete')
                for box_index, box in enumerate(group['boxes'], 1):
                    counts = Counter(item['sku'] for item in box['items'])
                    for sku, quantity in sorted(counts.items()):
                        parcels.append({'parcel_index': len(parcels) + 1, 'group_id': group['group_id'], 'box_index': box_index,
                                        'sku': sku, 'quantity': quantity, 'source': group['group_id'], 'carton_id': box['carton_id']})
            self._check_balance(active, allocations, parcels)
            for batch_id, entry in procurement.items():
                self._append_procurement(db, scope_key, batch_id, entry)
            kinds = {row['kind'] for row in allocations}
            branch = 'mixed' if len(kinds) > 1 else kinds.pop()
        else:
            receipt_id = 'fulfill_' + digest(['allocate', key, body])[:24]
        shown_lines = []
        for line in lines:
            shown_lines.append({'line_id': line['line_id'], 'sku': line['sku'], 'quantity': line['quantity'],
                                'source_sha256': line['source_sha256'], 'cancelled': line['line_id'] in cancelled,
                                'allocated': [row for row in allocations if row['line_id'] == line['line_id']]})
        document = {'schema': 'commerce-order-fulfillment-receipt-v1', 'status': 'cancelled' if branch == 'cancelled' else 'draft_ready',
                    'branch': branch, 'split': len({(row['group_id'], row['box_index']) for row in parcels}) > 1,
                    'order_id': body['order_id'], 'import_batch_id': batch['id'], 'batch_sha256': batch['sha256'],
                    'scope': scope, 'synthetic': body['synthetic'], 'lines': shown_lines, 'allocations': allocations,
                    'parcels': parcels, 'task_id': task['id'],
                    'task': {'id': task['id'], 'status': task['status'], 'kind': task['kind']},
                    'packing': None if plan is None else {'plan_id': plan['id'], 'plan_sha256': plan['sha256'], 'variant': 'space',
                                                           'complete': True, 'box_count': plan['variants']['space']['box_count'],
                                                           'shipment_submitted': False},
                    'request_sha256': digest(body), 'external_execution': False, 'order_processed': False,
                    'payment_authorized': False, 'purchase_submitted': False, 'shipment_submitted': False,
                    'warehouse_connected': False, 'notice': _NOTICE,
                    'created_at': datetime.now(timezone.utc).isoformat()}
        # Procurement-only receipts still commit the order line. Leaving them
        # closed would allow a second draft, and a later lot could reserve the
        # same units. Inventory holds are counted separately from this flag.
        hold = 'active' if allocations else 'closed'
        db.execute('INSERT INTO order_fulfillment_receipts VALUES (?,?,?,?,?,NULL)',
                   (receipt_id, scope_key, digest(document), encoded(document), hold))
        return receipt_id

    @staticmethod
    def _check_balance(active, allocations, parcels):
        per_line = Counter()
        for row in allocations:
            per_line[row['line_id']] += row['quantity']
        if any(per_line[row['line_id']] != row['quantity'] for row in active):
            raise ValueError('fulfillment_allocation_invariant')
        expected, actual = Counter(), Counter()
        for row in allocations:
            expected[(row['kind'], row['sku'])] += row['quantity']
        for row in parcels:
            actual[(row['source'], row['sku'])] += row['quantity']
        if expected != actual:
            raise ValueError('fulfillment_allocation_invariant')

    def _append_procurement(self, db, scope_key, batch_id, entry):
        row = db.execute('SELECT document FROM order_fulfillment_procurement WHERE id=?', (batch_id,)).fetchone()
        if row:
            doc = json.loads(row[0])
            if doc['scope_key'] != scope_key or doc['sku'] != entry['sku'] or doc['status'] != 'draft':
                raise ValueError('fulfillment_procurement_conflict')
            doc['lines'].extend(entry['lines'])
            db.execute('UPDATE order_fulfillment_procurement SET document=? WHERE id=?', (encoded(doc), batch_id))
            return
        doc = {'schema': 'commerce-order-fulfillment-procurement-v1', 'id': batch_id, 'scope_key': scope_key,
               'sku': entry['sku'], 'status': 'draft', 'lines': entry['lines'], 'payment_authorized': False,
               'purchase_submitted': False, 'warehouse_connected': False,
               'notice': '本地采购草稿。未提交供应商，未付款，未形成到货。同一草稿可被多笔订单引用。'}
        db.execute('INSERT INTO order_fulfillment_procurement VALUES (?,?,?,?)', (batch_id, scope_key, entry['sku'], encoded(doc)))

    def cancel(self, import_batch_id, order_id, line_id, expected_source_sha256, synthetic, idempotency_key):
        body = {'action': 'cancel', 'import_batch_id': _text(import_batch_id, 'import_batch_id', 80),
                'order_id': _text(order_id, 'order_id', 128), 'line_id': _text(line_id, 'line_id', 128),
                'expected_source_sha256': _sha(expected_source_sha256), 'synthetic': _bool(synthetic, 'synthetic')}
        with self.core.atomic() as db:
            return self._once(db, idempotency_key, body, lambda: self._cancel(db, body))

    def _cancel(self, db, body):
        _, scope, lines = self._order_lines(body['import_batch_id'], body['order_id'], body['synthetic'])
        match = next((row for row in lines if row['line_id'] == body['line_id']), None)
        if match is None:
            raise ValueError('fulfillment_order_not_found')
        if match['source_sha256'] != body['expected_source_sha256']:
            raise ValueError('fulfillment_source_changed')
        scope_key = _scope_key(scope, body['synthetic'])
        line_key = _line_key(body['order_id'], body['line_id'])
        marker = db.execute('SELECT source_sha256 FROM order_fulfillment_cancels WHERE scope_key=? AND line_key=?', (scope_key, line_key)).fetchone()
        if marker and marker[0] != match['source_sha256']:
            raise ValueError('fulfillment_source_changed')
        if marker is None:
            db.execute('INSERT INTO order_fulfillment_cancels VALUES (?,?,?)', (scope_key, line_key, match['source_sha256']))
        released = []
        rows = db.execute("SELECT id, document FROM order_fulfillment_receipts WHERE scope_key=? AND hold='active'", (scope_key,)).fetchall()
        for receipt_id, raw in rows:
            doc = json.loads(raw)
            if doc['order_id'] != body['order_id']:
                continue
            if not any(row['line_id'] == body['line_id'] and not row['cancelled'] for row in doc['lines']):
                continue
            release = {'reason': 'local_cancel', 'line_id': body['line_id'], 'at': datetime.now(timezone.utc).isoformat(),
                       'platform_cancelled': False}
            db.execute("UPDATE order_fulfillment_receipts SET hold='released', release_json=? WHERE id=? AND hold='active'",
                       (encoded(release), receipt_id))
            self._void_procurement(db, scope_key, receipt_id)
            released.append(receipt_id)
        return {'schema': 'commerce-order-fulfillment-cancel-v1', 'order_id': body['order_id'], 'line_id': body['line_id'],
                'source_sha256': match['source_sha256'], 'released_receipt_ids': released, 'platform_cancelled': False,
                'external_execution': False, 'purchase_submitted': False, 'shipment_submitted': False,
                'payment_authorized': False, 'notice': _CANCEL_NOTICE}

    def _void_procurement(self, db, scope_key, receipt_id):
        for batch_id, raw in db.execute('SELECT id, document FROM order_fulfillment_procurement WHERE scope_key=?', (scope_key,)):
            doc = json.loads(raw)
            changed = False
            for line in doc['lines']:
                if line['receipt_id'] == receipt_id and not line['voided']:
                    line['voided'] = True
                    changed = True
            if changed:
                db.execute('UPDATE order_fulfillment_procurement SET document=? WHERE id=?', (encoded(doc), batch_id))

    def _task_status(self, task_id):
        try:
            return self.core.invoke('commerce_task_get', {'task_id': task_id})['status']
        except ValueError:
            return 'missing'

    def _procurement(self, db, ids):
        found = []
        for ident in sorted(set(ids)):
            row = db.execute('SELECT document FROM order_fulfillment_procurement WHERE id=?', (ident,)).fetchone()
            if row:
                found.append(json.loads(row[0]))
        return found

    def get(self, receipt_id):
        _text(receipt_id, 'receipt_id', 80)
        with self.core.db() as db:
            row = db.execute('SELECT document, hold, release_json FROM order_fulfillment_receipts WHERE id=?', (receipt_id,)).fetchone()
            if row is None:
                raise ValueError('fulfillment_receipt_not_found')
            document = json.loads(row[0])
            batches = self._procurement(db, [item['batch_id'] for item in document['allocations'] if item['kind'] == 'procurement'])
        shown = dict(document)
        shown.update(id=receipt_id, hold=row[1], release=json.loads(row[2]) if row[2] else None, procurement_batches=batches)
        shown['task'] = {**document['task'], 'status': self._task_status(document['task_id'])}
        return shown

    def listing(self, scope, synthetic):
        scope = _scope(scope)
        _bool(synthetic, 'synthetic')
        scope_key = _scope_key(scope, synthetic)
        with self.core.db() as db:
            rows = db.execute('SELECT id, document, hold FROM order_fulfillment_receipts WHERE scope_key=? ORDER BY rowid DESC LIMIT 101', (scope_key,)).fetchall()
        items = []
        for ident, raw, hold in rows[:100]:
            doc = json.loads(raw)
            items.append({'id': ident, 'order_id': doc['order_id'], 'status': doc['status'], 'branch': doc['branch'],
                          'hold': hold, 'split': doc['split'], 'import_batch_id': doc['import_batch_id'],
                          'external_execution': False, 'order_processed': False, 'shipment_submitted': False})
        return {'items': items, 'truncated': len(rows) > 100, 'scope': scope, 'synthetic': synthetic, 'notice': _NOTICE}


def definitions(schema):
    text = {'type': 'string', 'minLength': 1, 'maxLength': 160}
    scope = {'type': 'object'}
    flag = {'type': 'boolean'}
    return [
        ('commerce_order_fulfillment_lot_save', '登记或按修订更新本机库存批次；不连接仓库，也不改平台可售库存。',
         schema({'scope': scope, 'lot_id': text, 'sku': text, 'quantity': {'type': 'integer'}, 'location_ref': text,
                 'expected_revision': {'type': 'integer'}, 'synthetic': flag, 'idempotency_key': text},
                ['scope', 'lot_id', 'sku', 'quantity', 'location_ref', 'expected_revision', 'synthetic', 'idempotency_key'])),
        ('commerce_order_fulfillment_lots', '读取本机库存批次及尚未释放的预留；不是仓库实盘。',
         schema({'scope': scope, 'synthetic': flag}, ['scope', 'synthetic'])),
        ('commerce_order_fulfillment_allocate', '沿原订单任务把已确认订单行分成库存预留或采购草稿，并保存装箱草稿；不付款、不采购、不发货。',
         schema({'import_batch_id': text, 'order_id': text, 'expected_lines': {'type': 'array'}, 'packing': {'type': 'object'},
                 'synthetic': flag, 'idempotency_key': text},
                ['import_batch_id', 'order_id', 'expected_lines', 'synthetic', 'idempotency_key'])),
        ('commerce_order_fulfillment_cancel', '重核订单行来源后记录本机取消，并释放该行所在回执的本地预留；不取消平台订单。',
         schema({'import_batch_id': text, 'order_id': text, 'line_id': text, 'expected_source_sha256': text,
                 'synthetic': flag, 'idempotency_key': text},
                ['import_batch_id', 'order_id', 'line_id', 'expected_source_sha256', 'synthetic', 'idempotency_key'])),
        ('commerce_order_fulfillment_get', '读取隔离履约回执、当前预留和采购草稿；不表示外部履约成功。',
         schema({'receipt_id': text}, ['receipt_id'])),
        ('commerce_order_fulfillment_list', '按店铺范围列出隔离履约回执；不读取平台。',
         schema({'scope': scope, 'synthetic': flag}, ['scope', 'synthetic'])),
    ]
