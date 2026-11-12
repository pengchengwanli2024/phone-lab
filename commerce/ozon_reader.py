"""Allowlisted read-only Seller API transport and strict projection of returned fields.

The live response is the schema check. Missing/changed fields stop publication;
fixtures do not establish compatibility with an actual account.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from sync_guard import assess_batch

HOST = 'https://api-seller.ozon.ru'
ENDPOINTS = {'FBS': '/v4/posting/fbs/list', 'realFBS': '/v4/posting/fbs/list',
             'OGL': '/v4/posting/fbs/list', 'FBO': '/v3/posting/fbo/list', 'stock': '/v4/product/info/stocks'}


class ConnectionIssue(ValueError):
    def __init__(self, code, http_status=None):
        self.code = code; self.http_status = http_status
        super().__init__(code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def stamp(): return datetime.now(timezone.utc).isoformat()


def pinned_hosts():
    """Optional egress override for networks where the default route cannot reach
    api-seller.ozon.ru. COMMERCE_OZON_IP holds one or more literal IPv4 addresses
    of the API host; absent or empty keeps the normal DNS + system route path."""
    raw = os.environ.get('COMMERCE_OZON_IP', '').strip()
    return [item.strip() for item in raw.split(',') if item.strip()]


def source_addresses():
    """Candidate source addresses for the pinned route. An explicit override wins;
    otherwise the host's own IPv4 addresses are tried, because on a host that also
    runs a transparent proxy the default route may not reach the API host."""
    explicit = os.environ.get('COMMERCE_OZON_SOURCE_IP', '').strip()
    if explicit: return [explicit]
    candidates = []
    try:
        listing = subprocess.run(['/sbin/ifconfig'], capture_output=True, text=True, timeout=3).stdout
        for match in re.finditer(r'inet (\d+\.\d+\.\d+\.\d+)', listing):
            address = match.group(1)
            if address.startswith('127.') or address.startswith('198.18.'): continue
            if address not in candidates: candidates.append(address)
    except (OSError, subprocess.SubprocessError):
        pass
    return candidates or [None]


class DirectConnection(http.client.HTTPSConnection):
    """HTTPS to a literal address while keeping Host/SNI and an optional bound
    source address, so only the transport route changes, not the request."""
    def __init__(self, ip, source, timeout):
        super().__init__('api-seller.ozon.ru', 443, timeout=timeout, context=ssl.create_default_context())
        self._ip, self._source = ip, source
    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout,
                                        source_address=(self._source, 0) if self._source else None)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _post_pinned(path, body, client_id, api_key, ips):
    data = json.dumps(body).encode()
    headers = {'Content-Type': 'application/json', 'Client-Id': client_id, 'Api-Key': api_key,
               'User-Agent': 'local-commerce-readonly/0.1'}
    sources = source_addresses()
    last = 'ozon_network_error'
    for ip in ips:
        for source in sources:
            connection = None
            try:
                connection = DirectConnection(ip, source, 8)
                connection.request('POST', path, body=data, headers=headers)
                response = connection.getresponse(); status = response.status
                raw = response.read(16*1024*1024+1)
            except (OSError, TimeoutError, ssl.SSLError):
                last = 'ozon_network_error'; continue
            finally:
                if connection is not None: connection.close()
            if status in (401, 403): raise ConnectionIssue('ozon_auth_or_permission', status)
            if status == 429: raise ConnectionIssue('ozon_rate_limited', status)
            if status != 200: raise ConnectionIssue('ozon_http_error', status)
            if len(raw) > 16*1024*1024: raise ConnectionIssue('response_too_large')
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, UnicodeError):
                raise ConnectionIssue('unexpected_response_schema') from None
            if not isinstance(payload, dict): raise ConnectionIssue('unexpected_response_schema')
            return payload, hashlib.sha256(raw).hexdigest()
    raise ConnectionIssue(last)



def post(path, body, client_id, api_key):
    if path not in ENDPOINTS.values(): raise ConnectionIssue('endpoint_not_allowed')
    pinned = pinned_hosts()
    if pinned: return _post_pinned(path, body, client_id, api_key, pinned)
    request = urllib.request.Request(HOST+path, data=json.dumps(body).encode(),
        headers={'Content-Type':'application/json','Client-Id':client_id,'Api-Key':api_key,
                 'User-Agent':'local-commerce-readonly/0.1'}, method='POST')
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(16*1024*1024+1)
            if len(raw)>16*1024*1024: raise ConnectionIssue('response_too_large')
            payload = json.loads(raw)
            if not isinstance(payload, dict): raise ConnectionIssue('unexpected_response_schema')
            return payload, hashlib.sha256(raw).hexdigest()
    except urllib.error.HTTPError as error:
        # Never echo upstream bodies, headers, account IDs or credential material.
        raise ConnectionIssue('ozon_auth_or_permission' if error.code in (401,403) else 'ozon_rate_limited' if error.code==429 else 'ozon_http_error', error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError): raise ConnectionIssue('ozon_network_error') from None
    except (json.JSONDecodeError, UnicodeError): raise ConnectionIssue('unexpected_response_schema') from None


def integer(value, field):
    if type(value) is not int or not 0 <= value <= 10**12: raise ConnectionIssue('invalid_numeric_'+field)
    return value


def identifier(value, field):
    if type(value) not in (str,int) or not str(value).strip() or len(str(value))>180:
        raise ConnectionIssue('missing_'+field)
    return str(value)


def moment(value, field, optional=False):
    if value is None and optional: return None
    if not isinstance(value,str): raise ConnectionIssue('missing_'+field)
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.utcoffset() is None: raise ValueError()
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError: raise ConnectionIssue('invalid_'+field) from None


def order_projection(row, mode):
    if not isinstance(row,dict): raise ConnectionIssue('unexpected_order_schema')
    posting=identifier(row.get('posting_number'),'posting_number')
    status=row.get('status')
    if not isinstance(status,str) or not status: raise ConnectionIssue('missing_order_status')
    products=row.get('products')
    if not isinstance(products,list): raise ConnectionIssue('missing_order_products')
    projected=[]
    for product in products:
        if not isinstance(product,dict): raise ConnectionIssue('unexpected_product_schema')
        sku=identifier(product.get('sku'),'sku'); qty=integer(product.get('quantity'),'quantity')
        offer=product.get('offer_id')
        if offer is not None and not isinstance(offer,str): raise ConnectionIssue('invalid_offer_id')
        name=product.get('name')
        projected.append({'sku':sku,'offer_id':offer,'quantity':qty,'name':name[:1000] if isinstance(name,str) else None})
    delivery=row.get('delivery_method') or {}
    if not isinstance(delivery,dict): raise ConnectionIssue('unexpected_delivery_schema')
    warehouse=delivery.get('warehouse_id')
    return dict(posting_number=posting, order_number=str(row.get('order_number') or ''),
                status=status, fulfillment=mode, fulfillment_origin='user_selected_mode_api_scope_requires_account_verification', products=projected,
                created_at=moment(row.get('in_process_at') or row.get('created_at'),'order_time',True),
                ship_by=moment(row.get('shipment_date'),'shipment_date',True),
                warehouse_id=str(warehouse) if type(warehouse) in (str,int) else None)


def stock_projection(row):
    if not isinstance(row,dict): raise ConnectionIssue('unexpected_stock_schema')
    product=identifier(row.get('product_id'),'product_id'); offer=row.get('offer_id')
    if offer is not None and not isinstance(offer,str): raise ConnectionIssue('invalid_offer_id')
    stocks=row.get('stocks')
    if not isinstance(stocks,list): raise ConnectionIssue('missing_stocks')
    output=[]
    for stock in stocks:
        if not isinstance(stock,dict) or not isinstance(stock.get('type'),str): raise ConnectionIssue('unexpected_stock_schema')
        present=integer(stock.get('present'),'present'); reserved=integer(stock.get('reserved'),'reserved')
        output.append(dict(type=stock['type'],present=present,reserved=reserved,
                           sku=str(stock['sku']) if type(stock.get('sku')) in (str,int) else None))
    return dict(product_id=product,offer_id=offer,stocks=output,warehouse_scope='fulfillment_aggregate_not_single_warehouse')


def fetch(config, kind, request=post, current=None):
    current=current or datetime.now(timezone.utc); start=time.monotonic()
    modes=config['fulfillment_modes'] if kind=='orders' else ['stock']
    # FBS and realFBS share one endpoint. The response must later be verified
    # against the selected account's actual shipping scheme; no double query/count.
    methods=[]
    for mode in modes:
        path=ENDPOINTS[mode]
        if path not in [p for _,p in methods]: methods.append((mode,path))
    records=[]; evidence=[]; normalized_pages=[]; seen=set()
    for mode,path in methods:
        cursor=''; pages=[]
        for index in range(100):
            if time.monotonic()-start>100: raise ConnectionIssue('sync_time_limit_partial')
            if kind=='orders':
                body={'filter':{'since':(current-timedelta(days=config['lookback_days'])).isoformat(), 'to':current.isoformat()},
                      'cursor':cursor,'limit':100,'sort_dir':'asc',
                      'with':{'analytics_data':False,'financial_data':False}}
            else:
                body={'filter':{'visibility':'ALL'},'cursor':cursor,'limit':1000}
            raw,sha=request(path,body,config['ozon_client_id'],config['ozon_api_key'])
            # Current order versions are top-level cursor envelopes. A result
            # wrapper or absent paging metadata requires inspection, never guessing.
            key='postings' if kind=='orders' else 'items'
            rows=raw.get(key)
            if not isinstance(rows,list): raise ConnectionIssue('unexpected_'+kind+'_schema')
            next_cursor=raw.get('cursor')
            if next_cursor is not None and not isinstance(next_cursor,str): raise ConnectionIssue('invalid_pagination_cursor')
            if kind=='orders':
                more=raw.get('has_next')
                if type(more) is not bool: raise ConnectionIssue('missing_pagination_flag')
            else:
                # Stocks use a continuation cursor; total is being replaced by
                # total_items and is deliberately not used as a completion signal.
                if 'cursor' not in raw: raise ConnectionIssue('missing_pagination_cursor')
                more=bool(next_cursor)
            page={'ok':True,'records':rows,'has_next':more,'cursor':next_cursor,'asof':stamp()}
            pages.append(page)
            evidence.append(dict(endpoint=path,page=index,request=body,response_sha256=sha,received_at=page['asof'],count=len(rows)))
            for row in rows:
                normalized=order_projection(row,mode) if kind=='orders' else stock_projection(row)
                identity=(path,normalized['posting_number'] if kind=='orders' else normalized['product_id'])
                if identity in seen: raise ConnectionIssue('duplicate_record_across_pages')
                seen.add(identity); records.append(normalized)
            if not more: break
            if not next_cursor or next_cursor==cursor: raise ConnectionIssue('pagination_not_progressing')
            cursor=next_cursor
        else: raise ConnectionIssue('pagination_limit_partial')
        assessment=assess_batch(pages,False,300,datetime.now(timezone.utc))
        if not assessment['accepted']: raise ConnectionIssue('pagination_or_freshness_incomplete')
        normalized_pages.extend(pages)
    return dict(kind=kind,records=records,evidence=evidence,observed_at=stamp(),complete=True,
                privacy='projected_fields_only_no_buyer_identity',
                coverage_days=config['lookback_days'] if kind=='orders' else None)
