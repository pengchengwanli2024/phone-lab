"""Two-phase private CSV intake; imported lines never impersonate platform sync."""
import csv
import hashlib
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
import io
import re
import time

from business_workflows.store import encoded, digest, text
from commerce_core import PLATFORMS

REQUIRED = {'order_id', 'sku', 'order_date', 'quantity', 'unit_price', 'currency'}
CURRENCIES = frozenset('CNY USD EUR GBP RUB MXN BRL JPY KRW CAD AUD HKD SGD INR AED PLN TRY CLP COP ARS PEN THB VND IDR MYR PHP TWD SAR ZAR'.split())
MAX_ROWS = 2000


def _scope(value):
    if type(value) is not dict or set(value) != {'platform', 'store_ref', 'market'}:
        raise ValueError('import_invalid_scope')
    if value['platform'] not in (*PLATFORMS, 'local'):
        raise ValueError('import_invalid_platform')
    for v in value.values():
        text(v, 100)
        if any(ord(c) < 32 for c in v):raise ValueError('import_invalid_scope')
    if not re.fullmatch('[A-Z]{2}', value['market']):raise ValueError('import_invalid_market')


def _row(row, indexes, mapping):
    def cell(field):
        index = indexes[mapping[field]]
        return row[index].strip() if index < len(row) else ''
    values = {k: cell(k) for k in mapping}
    for key in ('order_id', 'sku'):
        if not values[key] or len(values[key]) > 128 or any(ord(c) < 32 for c in values[key]):
            raise ValueError('INVALID_' + key.upper())
    if 'line_id' in values and (not values['line_id'] or len(values['line_id']) > 128 or any(ord(c) < 32 for c in values['line_id'])):
        raise ValueError('INVALID_LINE_ID')
    if not re.fullmatch(r'[1-9][0-9]{0,5}', values['quantity']) or int(values['quantity']) > 100000:
        raise ValueError('INVALID_QUANTITY')
    try:
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,8})?', values['unit_price']):raise InvalidOperation
        price = Decimal(values['unit_price'])
        if not price.is_finite() or not 0 <= price <= 10**9 or abs(price.as_tuple().exponent) > 8:
            raise InvalidOperation
    except InvalidOperation:
        raise ValueError('INVALID_UNIT_PRICE') from None
    try:
        raw = values['order_date']
        if len(raw) == 10:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):raise ValueError()
            date.fromisoformat(raw)
        else:
            if not re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}', raw):raise ValueError()
            stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if stamp.tzinfo is None:raise ValueError()
    except (ValueError, OverflowError):raise ValueError('INVALID_ORDER_DATE') from None
    currency = values['currency'].upper()
    if currency not in CURRENCIES:raise ValueError('MISSING_OR_UNSUPPORTED_CURRENCY')
    return {**values, 'currency': currency, 'quantity': int(values['quantity']),
            'unit_price': format(price, 'f'), 'line_id': values.get('line_id', values['sku'])}


class OrderImports:
    def __init__(self, service):
        self.service, self.core = service, service.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS order_import_batches(id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,document TEXT NOT NULL,status TEXT NOT NULL,receipt TEXT,created REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS order_import_lines(scope_key TEXT NOT NULL,line_key TEXT NOT NULL,batch_id TEXT NOT NULL,document TEXT NOT NULL,PRIMARY KEY(scope_key,line_key))')
            db.execute('CREATE TABLE IF NOT EXISTS order_import_requests(key TEXT PRIMARY KEY,sha256 TEXT NOT NULL,batch_id TEXT NOT NULL)')

    def _once(self, db, key, body, make):
        text(key);fingerprint = digest(body)
        old = db.execute('SELECT sha256,batch_id FROM order_import_requests WHERE key=?', (key,)).fetchone()
        if old:
            if old[0] != fingerprint:raise ValueError('import_idempotency_conflict')
            return old[1]
        ident = make()
        db.execute('INSERT INTO order_import_requests VALUES (?,?,?)', (key, fingerprint, ident))
        return ident

    def preview(self, filename, content, scope, synthetic, field_mapping, idempotency_key):
        if type(synthetic) is not bool:raise ValueError('import_invalid_mode')
        _scope(scope);text(filename, 160)
        if not filename.lower().endswith('.csv') or '/' in filename or '\\' in filename:raise ValueError('import_csv_filename_required')
        if type(content) is not str or not 0 < len(content.encode('utf-8')) <= 512000:raise ValueError('import_file_limit')
        if type(field_mapping) is not dict or not REQUIRED <= set(field_mapping) or set(field_mapping) - REQUIRED - {'line_id'}:
            raise ValueError('import_invalid_mapping')
        for value in field_mapping.values():text(value, 128)
        if len(set(field_mapping.values())) != len(field_mapping):raise ValueError('import_invalid_mapping')
        try:
            rows = list(csv.reader(io.StringIO(content.removeprefix('\ufeff'), newline=''), strict=True))
        except (csv.Error, UnicodeError):raise ValueError('import_csv_invalid') from None
        if not rows or not rows[0] or len(rows) - 1 > MAX_ROWS:raise ValueError('import_row_limit')
        header = rows[0]
        if len(set(header)) != len(header) or not set(field_mapping.values()) <= set(header):raise ValueError('import_invalid_mapping')
        indexes = {name: i for i, name in enumerate(header)}
        body = {'filename': filename, 'content_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(), 'scope': scope,
                'synthetic': synthetic, 'field_mapping': field_mapping}
        sha = digest(body);ident = 'import_' + sha[:24]
        with self.core.atomic() as db:
            def make():
                parsed, errors, grouped = [], [], {}
                for i, row in enumerate(rows[1:], 2):
                    try:
                        if len(row) != len(header):raise ValueError('COLUMN_COUNT_MISMATCH')
                        record = _row(row, indexes, field_mapping)
                    except ValueError as exc:
                        errors.append({'row': i, 'code': str(exc)})
                        continue
                    entry = {'row': i, 'record': record}
                    parsed.append(entry);grouped.setdefault((record['order_id'], record['line_id']), []).append(entry)
                valid, duplicates = [], 0
                for entries in grouped.values():
                    if len({encoded(e['record']) for e in entries}) > 1:
                        errors.extend({'row': e['row'], 'code': 'LINE_IDENTITY_CONFLICT'} for e in entries)
                    else:
                        valid.append(entries[0]);duplicates += len(entries) - 1
                document = {**body, 'row_count': len(rows) - 1, 'valid': valid, 'errors': sorted(errors, key=lambda e: e['row']),
                            'preview_duplicates': duplicates}
                db.execute('INSERT OR IGNORE INTO order_import_batches VALUES (?,?,?,?,NULL,?)',
                           (ident, sha, encoded(document), 'preview', time.time()))
                return ident
            result = self._once(db, idempotency_key, {'action': 'preview', **body}, make)
        return self.get(result)

    def _load(self, ident):
        text(ident)
        with self.core.db() as db:row = db.execute('SELECT * FROM order_import_batches WHERE id=?', (ident,)).fetchone()
        if row is None:raise ValueError('import_batch_not_found')
        return row, json_load(row[2])

    def get(self, batch_id):
        row, doc = self._load(batch_id)
        receipt = json_load(row[4]) if row[4] else {}
        return {'id': row[0], 'sha256': row[1], 'status': row[3],
                **{k: doc[k] for k in ('scope', 'synthetic', 'filename', 'row_count', 'content_sha256')},
                'valid_count': len(doc['valid']), 'quarantined_count': len(doc['errors']),
                'preview': doc['valid'][:50], 'quarantined': doc['errors'][:50],
                'preview_truncated': len(doc['valid']) > 50 or len(doc['errors']) > 50,
                'accepted_count': 0, 'duplicate_count': doc['preview_duplicates'],
                'sales_by_currency': [], **receipt, 'data_source': 'operator_csv_import_unverified',
                'external_execution_allowed': False}

    def listing(self, synthetic):
        if type(synthetic) is not bool:raise ValueError('import_invalid_mode')
        with self.core.db() as db:ids = [r[0] for r in db.execute('SELECT id FROM order_import_batches ORDER BY created DESC LIMIT 501')]
        items = [self.get(i) for i in ids]
        return {'items': [{k: v for k, v in item.items() if k not in ('preview', 'quarantined')}
                          for item in items if item['synthetic'] == synthetic][:500], 'truncated': len(ids) > 500}

    def confirm(self, batch_id, expected_sha256, confirmed, idempotency_key):
        if confirmed is not True:raise ValueError('import_explicit_confirmation_required')
        with self.core.atomic() as db:
            def make():
                row, doc = self._load(batch_id)
                if row[1] != expected_sha256:raise ValueError('import_source_changed')
                if row[3] != 'preview':return batch_id
                scope_key = digest([doc['scope'], doc['synthetic']])
                accepted, duplicates, errors = [], doc['preview_duplicates'], list(doc['errors'])
                for entry in doc['valid']:
                    record = entry['record'];line_key = digest([record['order_id'], record['line_id']])
                    old = db.execute('SELECT document FROM order_import_lines WHERE scope_key=? AND line_key=?', (scope_key, line_key)).fetchone()
                    if old:
                        if json_load(old[0]) == record:duplicates += 1
                        else:errors.append({'row': entry['row'], 'code': 'EXISTING_LINE_CONFLICT'})
                        continue
                    db.execute('INSERT INTO order_import_lines VALUES (?,?,?,?)', (scope_key, line_key, batch_id, encoded(record)))
                    accepted.append(record)
                totals = {}
                for record in accepted:
                    bucket = totals.setdefault(record['currency'], {'orders': set(), 'line_count': 0, 'unit_count': 0, 'gross_sales': Decimal(0)})
                    bucket['orders'].add(record['order_id']);bucket['line_count'] += 1
                    bucket['unit_count'] += record['quantity'];bucket['gross_sales'] += Decimal(record['unit_price']) * record['quantity']
                receipt = {'accepted_count': len(accepted), 'duplicate_count': duplicates, 'quarantined_count': len(errors),
                           'quarantined': errors[:50], 'preview_truncated': len(doc['valid']) > 50 or len(errors) > 50,
                           'sales_by_currency': [{'currency': k, 'order_count': len(v['orders']), 'line_count': v['line_count'],
                                                  'unit_count': v['unit_count'], 'gross_sales': format(v['gross_sales'], 'f')}
                                                 for k, v in sorted(totals.items())]}
                status = 'partial' if errors and accepted else 'rejected' if errors and not accepted else 'confirmed'
                db.execute('UPDATE order_import_batches SET status=?,receipt=? WHERE id=?', (status, encoded(receipt), batch_id))
                return batch_id
            ident = self._once(db, idempotency_key, {'action': 'confirm', 'id': batch_id, 'sha256': expected_sha256}, make)
        return self.get(ident)

    def orders(self, batch_id, args):
        _, doc = self._load(batch_id)
        if args.get('demo', False) != doc['synthetic']:raise ValueError('import_mode_mismatch')
        scope = doc['scope']
        if any(args.get(k, 'all') not in ('all', scope[s]) for k, s in [('platform', 'platform'), ('store_id', 'store_ref'), ('market', 'market')]):
            raise ValueError('import_scope_mismatch')
        with self.core.db() as db:rows = db.execute('SELECT document FROM order_import_lines WHERE batch_id=? ORDER BY rowid', (batch_id,)).fetchall()
        records = [json_load(row[0]) for row in rows]
        query = args.get('query', '').casefold()
        records = [r for r in records if query in encoded(r).casefold() and args.get('status', '') in ('', 'imported')]
        return {'orders': [{**r, 'id': r['order_id'] + ':' + r['line_id'], 'status': 'imported',
                            'platform': scope['platform'], 'store_id': scope['store_ref'], 'market': scope['market'],
                            'amount': format(Decimal(r['unit_price']) * r['quantity'], 'f'), 'batch_id': batch_id,
                            'source_sha256': digest(r)} for r in records], 'total': len(records),
                'mode': 'demo' if doc['synthetic'] else 'local_import', 'data_source': 'operator_csv_import_unverified'}

    def invoke(self, name, args):
        action = name.removeprefix('commerce_order_import_')
        return {'preview': self.preview, 'get': self.get, 'list': self.listing, 'confirm': self.confirm}[action](**args)


def json_load(raw):
    import json
    return json.loads(raw)


def definitions(schema):
    s = {'type': 'string', 'minLength': 1, 'maxLength': 160}
    return [
        ('commerce_order_import_preview', '预览本机CSV订单行，隔离缺失币种、无效日期和冲突；不写入订单或同步店铺。', schema({
            'filename': s, 'content': {'type': 'string', 'minLength': 1, 'maxLength': 512000}, 'scope': {'type': 'object'},
            'synthetic': {'type': 'boolean'}, 'field_mapping': {'type': 'object'}, 'idempotency_key': s},
            ['filename', 'content', 'scope', 'synthetic', 'field_mapping', 'idempotency_key'])),
        ('commerce_order_import_get', '读取CSV导入预览、隔离原因、确认回执及按币种汇总。', schema({'batch_id': s}, ['batch_id'])),
        ('commerce_order_import_list', '读取本机CSV导入批次；不读取平台。', schema({'synthetic': {'type': 'boolean'}}, ['synthetic'])),
        ('commerce_order_import_confirm', '明确确认准确哈希的本机订单导入；原子去重，不改库存或平台。', schema({
            'batch_id': s, 'expected_sha256': s, 'confirmed': {'type': 'boolean'}, 'idempotency_key': s},
            ['batch_id', 'expected_sha256', 'confirmed', 'idempotency_key'])),
    ]
