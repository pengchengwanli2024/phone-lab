"""Source-bound operating statistics; no FX assumptions or execution approvals."""
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, InvalidOperation

STOCK_DEFINITION = 'https://dev.ozon.ru/start/257-Seller-API-FAQ-spravochnik-oshibok-i-sposobov-ikh-resheniia'
SALES_DEFINITION = 'https://dev.ozon.ru/news/252-Izmeneniia-v-rabote-metoda-v1-analytics-data/'


def sales_window(config, current=None):
    current = current or datetime.now(timezone.utc)
    end = current.astimezone(timezone(timedelta(hours=3))).date() - timedelta(days=1)
    return end - timedelta(days=config['lookback_days'] - 1), end


def decimal_value(value):
    from ozon_reader import ConnectionIssue
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConnectionIssue('invalid_sales_amount')
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ConnectionIssue('invalid_sales_amount') from None
    if not number.is_finite() or not 0 <= number <= 10**15:
        raise ConnectionIssue('invalid_sales_amount')
    return number


def fetch_sales(config, request, current=None):
    from ozon_reader import ConnectionIssue, ENDPOINTS, stamp
    start, end = sales_window(config, current)
    # At most 90 distinct daily rows fit in one 1000-row response. Require the
    # complete day set and reconciled totals; missing dates never become zeros.
    body = dict(date_from=start.isoformat(), date_to=end.isoformat(), metrics=['revenue', 'ordered_units'],
                dimension=['day'], filters=[], sort=[], limit=1000, offset=0)
    raw, sha = request(ENDPOINTS['sales'], body, config['ozon_client_id'], config['ozon_api_key'])
    result = raw.get('result')
    if not isinstance(result, dict) or not isinstance(result.get('data'), list):
        raise ConnectionIssue('unexpected_sales_schema')
    records = []; seen = set()
    for row in result['data']:
        if not isinstance(row, dict): raise ConnectionIssue('unexpected_sales_schema')
        dims, metrics = row.get('dimensions'), row.get('metrics')
        if not isinstance(dims, list) or len(dims) != 1 or not isinstance(dims[0], dict):
            raise ConnectionIssue('unexpected_sales_dimensions')
        day = dims[0].get('id')
        try:
            parsed = date.fromisoformat(day)
            if parsed.isoformat() != day or not start <= parsed <= end or day in seen: raise ValueError()
        except (TypeError, ValueError): raise ConnectionIssue('invalid_or_duplicate_sales_day') from None
        if not isinstance(metrics, list) or len(metrics) != 2: raise ConnectionIssue('unexpected_sales_metrics')
        amount, units = map(decimal_value, metrics)
        if units != units.to_integral_value(): raise ConnectionIssue('invalid_ordered_units')
        records.append(dict(day=day, amount=str(amount), ordered_units=int(units))); seen.add(day)
    expected = {(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)}
    if seen != expected: raise ConnectionIssue('incomplete_sales_days')
    totals = result.get('totals')
    if not isinstance(totals, list) or len(totals) != 2: raise ConnectionIssue('missing_sales_totals')
    amount, units = map(decimal_value, totals)
    if amount != sum(Decimal(row['amount']) for row in records) or units != sum(row['ordered_units'] for row in records):
        raise ConnectionIssue('sales_totals_mismatch')
    at = stamp()
    return dict(kind='sales', records=sorted(records, key=lambda row: row['day']), amount=str(amount), ordered_units=int(units),
                currency=None, currency_status='not_returned_by_analytics_api', metric='revenue', metric_label='下单金额（平台口径）',
                definition_url=SALES_DEFINITION, date_from=start.isoformat(), date_to=end.isoformat(), day_basis='Ozon day dimension',
                upstream_timestamp=raw.get('timestamp') if isinstance(raw.get('timestamp'), str) else None,
                observed_at=at, coverage_days=config['lookback_days'], complete=True,
                evidence=[dict(endpoint=ENDPOINTS['sales'], request=body, response_sha256=sha, received_at=at, count=len(records))])


def inventory_summary(snapshot, fresh):
    if not snapshot: return None
    groups = {}; skus = set()
    for product in snapshot['data']['records']:
        skus.add(product['product_id'])
        for stock in product['stocks']:
            group = groups.setdefault(stock['type'], dict(type=stock['type'], rows=0, present=0, reserved=0, orderable_api=0, inconsistent_rows=0))
            group['rows'] += 1; group['present'] += stock['present']; group['reserved'] += stock['reserved']
            if stock['reserved'] > stock['present']: group['inconsistent_rows'] += 1
    for group in groups.values():
        group['orderable_api'] = None if group['inconsistent_rows'] else group['present'] - group['reserved']
    return dict(sku_count=len(skus), groups=list(groups.values()), stale=not fresh, observed_at=snapshot['observed_at'],
                source_sha256=snapshot['sha256'], scope='按履约方式汇总，非单仓',
                orderable_basis='present - reserved（Ozon API 定义）', definition_url=STOCK_DEFINITION)
