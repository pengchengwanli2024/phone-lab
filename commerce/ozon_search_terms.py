"""Bounded current-store search-query reads, private provenance and daily claims.

No arbitrary SKU/date/credentials from callers and no marketplace writes.
Rows, nulls and currency codes remain as returned; GMV never supplies orders.
"""
from datetime import datetime, timezone, timedelta
import json
import math
import re
import threading
import time
import unicodedata
import uuid

from research import canonical, digest
import ozon_reader

PATHS = {'products': '/v1/analytics/product-queries', 'details': '/v1/analytics/product-queries/details'}
SOURCE = 'own_store_product_queries_not_global_hotterms'
READ_ONLY = {'commerce_ozon_search_terms_status', 'commerce_ozon_search_terms_search'}
MAX_PRODUCTS, PAGE_SIZE, MAX_PAGES = 100, 100, 5


def definitions(schema, string):
    return [
        ('commerce_ozon_search_terms_status', '读取当前Ozon连接的搜索词日任务和完整快照状态；不访问平台', schema()),
        ('commerce_ozon_search_terms_refresh', '按当前店铺新鲜库存身份排队一次当日有界搜索词读取；排队不是完成，不改平台', schema({'expected_connection_sha256': {'type':'string','pattern':'^[a-f0-9]{64}$'}})),
        ('commerce_ozon_search_terms_search', '检索当前Ozon本店商品的原始中文/俄文搜索词与来源；不是全平台热搜，不换算币种或推算订单',
         schema({'query': {'type': 'string', 'maxLength': 100}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}})),
    ]


def instant(at=None):return datetime.fromtimestamp(time.time() if at is None else at, timezone.utc)
def stamp():return instant().isoformat()


def period(at=None):
    end = instant(at).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=3)
    return {'date_from': (end - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'date_to': end.strftime('%Y-%m-%dT%H:%M:%SZ')}


def parsed_time(value):
    if type(value) is not str or len(value) > 60:raise ValueError('ozon_query_period_schema')
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4} UTC', value):
            result = datetime.strptime(value, '%Y-%m-%d %H:%M:%S %z UTC')
        else:result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:raise ValueError()
        return result.astimezone(timezone.utc)
    except ValueError:raise ValueError('ozon_query_period_schema') from None


def identifier(value):
    if type(value) not in (str, int) or not re.fullmatch('[1-9][0-9]{0,29}', str(value)):
        raise ValueError('ozon_query_inventory_identity')
    return str(value)


def store_identity(connection, label=None):
    if type(label) is not str or not label.strip() or len(label) > 100 or any(ord(c) < 32 for c in label):
        label = '当前Ozon店铺'
    return {'platform': 'ozon', 'market': 'RU', 'connection_sha256': connection, 'label': label}


class OzonSearchTerms:
    def __init__(self, service, reader=None):
        self.service, self.core, self.live = service, service.core, service.live
        self.reader = reader or ozon_reader.post
        self.owner = uuid.uuid4().hex;self.closing = threading.Event();self.thread = None
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS ozon_query_jobs(id TEXT PRIMARY KEY,connection TEXT NOT NULL,slot TEXT NOT NULL,status TEXT NOT NULL,document TEXT NOT NULL,created REAL NOT NULL,UNIQUE(connection,slot))')
            db.execute('CREATE TABLE IF NOT EXISTS ozon_query_snapshots(id TEXT PRIMARY KEY,connection TEXT NOT NULL,document TEXT NOT NULL,sha256 TEXT NOT NULL,observed TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS ozon_query_latest(connection TEXT PRIMARY KEY,snapshot_id TEXT NOT NULL)')
        # The server's per-state lifecycle lock must exclude a prior instance.
        self.recover()

    @staticmethod
    def connection(config):
        return digest(canonical([config.get('connection_id'), config.get('ozon_client_id'), config.get('ozon_api_key')]))

    def _scope(self, config):
        if not config.get('connection_id') or not config.get('ozon_client_id') or not config.get('ozon_api_key'):
            raise ValueError('ozon_query_configure_store_first')
        stock = self.live.snapshot(config['connection_id'], 'stock')
        if not stock or not self.live._fresh(stock, config):raise ValueError('ozon_query_fresh_stock_required')
        payload = stock['data']
        if digest(canonical(payload)) != stock['sha256'] or payload.get('complete') is not True:
            raise ValueError('ozon_query_stock_integrity')
        records = payload.get('records')
        if type(records) is not list or not 1 <= len(records) <= MAX_PRODUCTS:
            raise ValueError('ozon_query_inventory_limit')
        identities = {}
        for row in records:
            if type(row) is not dict:raise ValueError('ozon_query_inventory_identity')
            product = identifier(row.get('product_id'));offer = row.get('offer_id')
            if offer is not None and (type(offer) is not str or len(offer) > 180):raise ValueError('ozon_query_inventory_identity')
            stocks = row.get('stocks')
            if type(stocks) is not list:raise ValueError('ozon_query_inventory_identity')
            found = False
            for entry in stocks:
                if type(entry) is not dict:raise ValueError('ozon_query_inventory_identity')
                if entry.get('sku') is None:continue
                sku = identifier(entry['sku']);identity = {'product_id': product, 'offer_id': offer}
                if sku in identities and identities[sku] != identity:raise ValueError('ozon_query_inventory_ambiguous')
                identities[sku] = identity;found = True
            if not found:raise ValueError('ozon_query_platform_sku_required')
        if not 1 <= len(identities) <= MAX_PRODUCTS:raise ValueError('ozon_query_inventory_limit')
        return {'stock_sha256': stock['sha256'], 'sku_bindings': dict(sorted(identities.items())),
                'product_count': len({r['product_id'] for r in identities.values()}), 'sku_count': len(identities),
                'scope_sha256': digest(canonical(identities))}

    def _check(self, config, scope):
        if self.closing.is_set():raise ValueError('ozon_query_closed')
        current = self.live.config()
        if self.connection(current) != self.connection(config):raise ValueError('ozon_query_connection_changed')
        if self._scope(current)['scope_sha256'] != scope['scope_sha256']:raise ValueError('ozon_query_scope_changed')

    @staticmethod
    def _public(job):
        keep = ('id', 'status', 'slot', 'period', 'scope_sha256', 'stock_sha256', 'product_count', 'sku_count',
                'created_at', 'finished_at', 'error', 'http_status', 'snapshot_id', 'snapshot_sha256')
        return {**{key: job[key] for key in keep if key in job}, 'source': SOURCE,
                'connection_sha256': job['connection'], 'store_identity': store_identity(job['connection'], job.get('store_label')),
                'external_execution_allowed': False, 'queue_is_not_completion': True}

    def _job(self, db, ident):
        row = db.execute('SELECT document FROM ozon_query_jobs WHERE id=?', (ident,)).fetchone()
        if row is None:raise ValueError('ozon_query_job_missing')
        return json.loads(row[0])

    @staticmethod
    def _save(db, job):
        db.execute('UPDATE ozon_query_jobs SET status=?,document=? WHERE id=?', (job['status'], canonical(job), job['id']))

    def recover(self):
        with self.core.atomic(reuse=True) as db:
            for raw, in db.execute("SELECT document FROM ozon_query_jobs WHERE status IN ('queued','running')").fetchall():
                job = json.loads(raw);job.update(status='unknown', error='ozon_query_interrupted_unknown', finished_at=stamp())
                self._save(db, job)

    def refresh(self, expected_connection_sha256=None):
        if self.closing.is_set():raise ValueError('ozon_query_closed')
        with self.live.config_lock, self.core.atomic(reuse=True) as db:
            config = self.live.config();connection = self.connection(config);slot = instant().date().isoformat()
            if expected_connection_sha256 is not None and (type(expected_connection_sha256) is not str or not re.fullmatch('[a-f0-9]{64}',expected_connection_sha256) or expected_connection_sha256!=connection):
                raise ValueError('ozon_query_connection_changed')
            old = db.execute('SELECT document FROM ozon_query_jobs WHERE connection=? AND slot=?', (connection, slot)).fetchone()
            if old:return self._public(json.loads(old[0]))
            if db.execute("SELECT 1 FROM ozon_query_jobs WHERE status IN ('queued','running')").fetchone():
                raise ValueError('ozon_query_read_active')
            scope = self._scope(config)
            job = {'id': uuid.uuid4().hex, 'connection': connection, 'slot': slot, 'owner': self.owner,
                   'store_label': store_identity(connection, config.get('store_label'))['label'],
                   'status': 'queued', 'period': period(), 'scope_sha256': scope['scope_sha256'],
                   'stock_sha256': scope['stock_sha256'], 'product_count': scope['product_count'], 'sku_count': scope['sku_count'],
                   'created_at': stamp(), 'responses': [], 'inflight': None, 'error': None}
            db.execute('INSERT INTO ozon_query_jobs VALUES (?,?,?,?,?,?)',
                (job['id'], connection, slot, job['status'], canonical(job), time.time()))
        self.thread = threading.Thread(target=self._run, args=(job['id'], config, scope), daemon=True, name='ozon-search-terms')
        try:self.thread.start()
        except Exception:
            self._finish(job['id'], 'failed', 'ozon_query_worker_start_failed');raise ValueError('ozon_query_worker_start_failed') from None
        return self._public(job)

    def _finish(self, ident, status, error, http_status=None):
        with self.core.atomic(reuse=True) as db:
            job = self._job(db, ident)
            if job['status'] not in ('queued', 'running'):return
            job.update(status=status, error=error, http_status=http_status, finished_at=stamp());self._save(db, job)

    def _read(self, ident, config, scope, resource, body):
        self._check(config, scope)
        with self.core.atomic(reuse=True) as db:
            job = self._job(db, ident)
            if job['status'] != 'running' or job['owner'] != self.owner:raise ValueError('ozon_query_claim_changed')
            job['inflight'] = {'endpoint': PATHS[resource], 'request_sha256': digest(canonical(body)), 'page': body['page'], 'started_at': stamp()}
            self._save(db, job)
        raw, response_sha = self.reader(PATHS[resource], body, config['ozon_client_id'], config['ozon_api_key'])
        encoded = canonical(raw)
        if len(encoded.encode()) > 2000000 or type(response_sha) is not str or not re.fullmatch('[a-f0-9]{64}', response_sha):
            raise ValueError('ozon_query_response_bounds')
        receipt = {'endpoint': PATHS[resource], 'request': body, 'response_sha256': response_sha,
                   'payload_sha256': digest(encoded), 'payload': raw, 'received_at': stamp()}
        with self.core.atomic(reuse=True) as db:
            job = self._job(db, ident)
            if job['status'] != 'running' or job['owner'] != self.owner:raise ValueError('ozon_query_claim_changed')
            job['responses'].append(receipt);job['inflight'] = None;self._save(db, job)
        self._check(config, scope)
        return raw, receipt

    @staticmethod
    def _page(raw, resource, expected_period, expected_skus):
        key = 'queries' if resource == 'details' else 'items'
        if type(raw) is not dict or type(raw.get(key)) is not list or len(raw[key]) > PAGE_SIZE:
            raise ValueError('ozon_query_response_schema')
        total, count = raw.get('total'), raw.get('page_count')
        if type(total) is not int or type(count) is not int or total < 0 or not 0 <= count <= MAX_PAGES:
            raise ValueError('ozon_query_pagination_bounds')
        if count != (total + PAGE_SIZE - 1) // PAGE_SIZE and not (total == 0 and count == 1):
            raise ValueError('ozon_query_pagination_schema')
        returned_period = raw.get('analytics_period')
        if type(returned_period) is not dict or any(parsed_time(returned_period.get(k)) != parsed_time(v) for k, v in expected_period.items()):
            raise ValueError('ozon_query_period_changed')
        for row in raw[key]:
            if type(row) is not dict or identifier(row.get('sku')) not in expected_skus:raise ValueError('ozon_query_response_scope')
            if resource == 'details' and (type(row.get('query')) is not str or not 0 < len(row['query']) <= 6000):
                raise ValueError('ozon_query_response_schema')
            for field in ('unique_search_users', 'unique_view_users', 'position', 'view_conversion', 'gmv', 'order_count', 'query_index'):
                value = row.get(field)
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                    raise ValueError('ozon_query_response_metric')
            if 'currency' in row and row['currency'] is not None and type(row['currency']) is not str:
                raise ValueError('ozon_query_response_currency')
        return raw[key], total, count

    def _run(self, ident, config, scope):
        try:
            with self.core.atomic(reuse=True) as db:
                job = self._job(db, ident)
                if job['status'] != 'queued':return
                job['status'] = 'running';self._save(db, job)
            all_rows = {};periods = {}
            for resource in PATHS:
                collected = [];seen = set();metadata = None
                for page in range(MAX_PAGES):
                    body = {**job['period'], 'page': page, 'page_size': PAGE_SIZE, 'skus': list(scope['sku_bindings']),
                            'sort_by': 'BY_SEARCHES', 'sort_dir': 'DESCENDING'}
                    if resource == 'details':body['limit_by_sku'] = 15
                    raw, receipt = self._read(ident, config, scope, resource, body)
                    rows, total, page_count = self._page(raw, resource, job['period'], scope['sku_bindings'])
                    if metadata is not None and metadata != (total, page_count):raise ValueError('ozon_query_pagination_changed')
                    metadata = (total, page_count)
                    if page + 1 < page_count and len(rows) != PAGE_SIZE:raise ValueError('ozon_query_pagination_incomplete')
                    for row in rows:
                        identity = (identifier(row['sku']), row['query']) if resource == 'details' else identifier(row['sku'])
                        if identity in seen:raise ValueError('ozon_query_duplicate_row')
                        seen.add(identity);collected.append(row)
                    if page + 1 >= page_count:
                        if len(collected) != total:raise ValueError('ozon_query_pagination_incomplete')
                        break
                else:raise ValueError('ozon_query_pagination_limit')
                all_rows[resource] = collected;periods[resource] = raw['analytics_period']
            with self.live.config_lock, self.core.atomic(reuse=True) as db:
                self._check(config, scope);current = self._job(db, ident)
                if current['status'] != 'running' or current['owner'] != self.owner:raise ValueError('ozon_query_claim_changed')
                doc = {'schema': 'ozon-own-store-search-terms-v1', 'source': SOURCE, 'connection_sha256': job['connection'],
                       'period': job['period'], 'analytics_period': periods, 'scope': scope, 'products': all_rows['products'],
                       'queries': all_rows['details'], 'responses': current['responses'], 'observed_at': stamp(),
                       'raw_fields_preserved': True, 'currency_interpretation': 'raw_platform_code_not_inferred',
                       'empty_result_is_not_zero_demand': True, 'external_execution_allowed': False}
                payload = canonical(doc);source_sha = digest(payload);snapshot = uuid.uuid4().hex
                db.execute('INSERT INTO ozon_query_snapshots VALUES (?,?,?,?,?)', (snapshot, job['connection'], payload, source_sha, doc['observed_at']))
                db.execute('INSERT OR REPLACE INTO ozon_query_latest VALUES (?,?)', (job['connection'], snapshot))
                current.update(status='succeeded', snapshot_id=snapshot, snapshot_sha256=source_sha, finished_at=stamp(), inflight=None)
                self._save(db, current)
        except Exception as error:
            if isinstance(error, ozon_reader.ConnectionIssue):
                status = 'failed' if error.http_status is not None or error.code in ('endpoint_not_allowed', 'unexpected_response_schema', 'response_too_large') else 'unknown'
                code = error.code if re.fullmatch('[a-z0-9_]+', error.code) else 'ozon_query_read_failed'
                self._finish(ident, status, code, error.http_status)
            elif isinstance(error, (TimeoutError, OSError)):
                self._finish(ident, 'unknown', 'ozon_query_transport_unknown')
            else:
                code = str(error) if isinstance(error, ValueError) and re.fullmatch('ozon_query_[a-z0-9_]+', str(error)) else 'ozon_query_read_failed'
                self._finish(ident, 'failed', code)

    def _snapshot(self, connection):
        with self.core.db() as db:
            row = db.execute('SELECT s.id,s.document,s.sha256 FROM ozon_query_latest l JOIN ozon_query_snapshots s ON s.id=l.snapshot_id WHERE l.connection=?', (connection,)).fetchone()
        if not row:return None
        if digest(row[1]) != row[2]:raise ValueError('ozon_query_snapshot_integrity')
        doc = json.loads(row[1])
        if doc['connection_sha256'] != connection:raise ValueError('ozon_query_snapshot_connection')
        return {'id': row[0], 'doc': doc, 'sha256': row[2]}

    def status(self):
        with self.live.config_lock:return self._status()

    def _status(self):
        config = self.live.config();connection = self.connection(config)
        try:scope = self._scope(config);scope_status = 'ready';scope_error = None
        except ValueError as error:scope = None;scope_status = 'stock_pending';scope_error = str(error)
        snapshot = self._snapshot(connection)
        with self.core.db() as db:
            history = [self._public(json.loads(raw)) for raw, in db.execute('SELECT document FROM ozon_query_jobs WHERE connection=? ORDER BY created DESC,rowid DESC LIMIT 10', (connection,))]
        return {'source': SOURCE, 'configured': bool(config.get('ozon_client_id') and config.get('ozon_api_key')),
                'connection_sha256': connection, 'store_identity': store_identity(connection, config.get('store_label')),
                'scope_status': scope_status, 'scope_error': scope_error,
                'scope_sha256': scope['scope_sha256'] if scope else None, 'product_count': scope['product_count'] if scope else None,
                'sku_count': scope['sku_count'] if scope else None,
                'max_products': MAX_PRODUCTS, 'period': period(), 'refresh': history[0] if history else None, 'history': history,
                'snapshot': {'id': snapshot['id'], 'sha256': snapshot['sha256'], 'period': snapshot['doc']['period'],
                    'observed_at': snapshot['doc']['observed_at'], 'fresh_period': snapshot['doc']['period'] == period(),
                    'scope_current': bool(scope and snapshot['doc']['scope']['scope_sha256'] == scope['scope_sha256'])} if snapshot else None,
                'external_execution_allowed': False, 'not_global_hot_terms': True}

    def search(self, query='', limit=20):
        with self.live.config_lock:return self._search(query, limit)

    def _search(self, query='', limit=20):
        if type(query) is not str or len(query) > 100 or any(ord(c) < 32 for c in query) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('ozon_query_invalid_search')
        status = self.status();snapshot = self._snapshot(status['connection_sha256'])
        if not snapshot:
            return {'source': SOURCE, 'availability': 'not_collected', 'scope_status': status['scope_status'], 'items': [],
                    'connection_sha256': status['connection_sha256'], 'store_identity': status['store_identity'],
                    'scope_sha256': status['scope_sha256'], 'not_global_hot_terms': True,
                    'products': [], 'total': None, 'snapshot_sha256': None, 'refresh': status['refresh'], 'external_execution_allowed': False}
        doc = snapshot['doc'];needle = unicodedata.normalize('NFKC', query).casefold().strip()
        products = {identifier(r['sku']): r for r in doc['products']}
        matches = []
        for row in doc['queries']:
            product = products.get(identifier(row['sku']), {})
            text = ' '.join(str(v) for v in [row.get('query', ''), product.get('name', ''), product.get('offer_id', ''), row['sku']])
            if not needle or needle in unicodedata.normalize('NFKC', text).casefold():matches.append(row)
        return {'source': SOURCE, 'availability': 'snapshot' if status['snapshot']['fresh_period'] else 'stale_snapshot',
                'connection_sha256': status['connection_sha256'], 'store_identity': status['store_identity'],
                'scope_sha256': status['scope_sha256'],
                'scope_status': status['scope_status'], 'scope_current': status['snapshot']['scope_current'],
                'items': matches[:limit], 'products': doc['products'], 'total': len(matches), 'returned': min(limit, len(matches)),
                'snapshot_id': snapshot['id'], 'snapshot_sha256': snapshot['sha256'], 'period': doc['period'],
                'analytics_period': doc['analytics_period'], 'observed_at': doc['observed_at'], 'refresh': status['refresh'],
                'raw_fields_preserved': True, 'currency_interpretation': 'raw_platform_code_not_inferred',
                'empty_result_is_not_zero_demand': True, 'unique_users_not_summed': True, 'gmv_not_used_to_infer_orders': True,
                'external_execution_allowed': False, 'not_global_hot_terms': True}

    def invoke(self, name, args):
        return {'commerce_ozon_search_terms_status': self.status, 'commerce_ozon_search_terms_refresh': self.refresh,
                'commerce_ozon_search_terms_search': self.search}[name](**args)

    def close(self):
        self.closing.set()
        with self.core.atomic(reuse=True) as db:
            for raw, in db.execute("SELECT document FROM ozon_query_jobs WHERE status IN ('queued','running')").fetchall():
                job = json.loads(raw)
                if job.get('owner') == self.owner:
                    job.update(status='unknown', error='ozon_query_closed_unknown', finished_at=stamp());self._save(db, job)
        if self.thread and self.thread.is_alive():self.thread.join(timeout=1)
