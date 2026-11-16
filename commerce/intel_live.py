"""Public transport observations and indicative market snapshots.

Provider selection and bounded, seed-first delivery follow mechanisms studied in
World Monitor. This is an independent implementation for our SQLite/HTTP host.
Reads never contact a provider. Refreshes are shared, rate limited, and retain
last-good evidence. Credentials are never returned to clients.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import math
import os
from pathlib import Path
from random import uniform
import re
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen, getproxies, proxy_bypass
from intel_map import country_name, in_bounds, validate_bounds

SOURCES = {
    'flights': dict(name='航空器位置', provider='OpenSky Network', url='https://opensky-network.org/', interval=900, max_age=1800),
    'vessels': dict(name='船舶位置', provider='AISStream', url='https://aisstream.io/', interval=60, max_age=600),
    'markets': dict(name='全球行情', provider='Yahoo Finance / CoinPaprika', url='https://finance.yahoo.com/', interval=300, max_age=1800),
}
SYMBOLS = [('^GSPC', '标普500'), ('^IXIC', '纳斯达克'), ('^HSI', '恒生指数'),
           ('000001.SS', '上证指数'), ('GC=F', '黄金期货'), ('BZ=F', '布伦特原油'), ('CNY=X', '美元/人民币')]
AIS_ERRORS = ('ais_no_positions', 'ais_subscription_rejected', 'ais_client_unavailable',
              'ais_proxy_dependency_missing', 'ais_stream_disconnected', 'ais_connection_failed')


def ais_proxy():
    # websockets prefers macOS SOCKS over HTTPS. Reuse the working HTTP tunnel
    # without requiring python-socks; preserve explicit WSS and bypass choices.
    if proxy_bypass('stream.aisstream.io:443'):
        return None
    proxies = getproxies()
    if proxies.get('wss'):
        return proxies['wss']
    https = proxies.get('https')
    return https if https and urlsplit(https).scheme in ('http', 'https') else True


def number(v, minimum=-math.inf, maximum=math.inf):
    return type(v) in (float, int) and math.isfinite(v) and minimum <= v <= maximum


def stamp(value):
    if number(value, 0):
        return int(value)
    try:
        text = str(value).replace('Z', '+00:00').replace(' UTC', '').strip()
        # AISStream metadata also uses Go's "... +0000 UTC" time format.
        text = re.sub(r'\s([+-][0-9]{4})$', r'\1', text)
        return int(datetime.fromisoformat(text).timestamp())
    except (ValueError, TypeError, OverflowError):
        return None


def fetch_json(url, headers=None, form=None):
    # Fixed provider URLs only; no user-controlled hosts, proxy or redirect input.
    data = urlencode(form).encode() if form else None
    request = Request(url, data=data, headers={'User-Agent': 'PhoneLab-Intelligence/1.0', 'Accept': 'application/json', **(headers or {})})
    try:
        with urlopen(request, timeout=9) as response:
            raw = response.read(12_000_001)
        if len(raw) > 12_000_000:
            raise ValueError('upstream_response_too_large')
        return json.loads(raw)
    except HTTPError as error:
        # Do not echo response bodies, URLs or authentication values.
        raise ValueError('upstream_http_' + str(error.code)) from None
    except (OSError, json.JSONDecodeError):
        raise ValueError('upstream_connection_or_format_error') from None


def parse_flights(data):
    if not isinstance(data, dict) or not number(data.get('time'), 1) or not isinstance(data.get('states'), (list, type(None))):
        raise ValueError('invalid_opensky_response')
    found = {}
    for v in (data['states'] or [])[:30000]:
        if (not isinstance(v, list) or len(v) < 11 or not isinstance(v[0], str) or not re.fullmatch('[a-f0-9]{6}', v[0])
                or not number(v[5], -180, 180) or not number(v[6], -90, 90) or not number(v[3], 1)):
            continue
        found[v[0]] = dict(id='flight-' + v[0], kind='flight', callsign=str(v[1] or '').strip()[:24], icao24=v[0],
                          country=country_name(v[2]), location={'lon': v[5], 'lat': v[6]}, observed_at=int(v[3]),
                          altitude_m=round(v[7]) if number(v[7]) else None,
                          speed_kmh=round(v[9] * 3.6, 1) if number(v[9], 0, 500) else None,
                          heading=v[10] if number(v[10], 0, 359.999) else None, on_ground=v[8] is True,
                          source='OpenSky Network', source_url='https://opensky-network.org/')
    return list(found.values())


def parse_vessel(data):
    if not isinstance(data, dict) or data.get('MessageType') not in ('PositionReport', 'StandardClassBPositionReport'):
        return None
    meta, message = data.get('MetaData'), data.get('Message')
    if not isinstance(meta, dict) or not isinstance(message, dict) or not isinstance(message.get(data['MessageType']), dict):
        return None
    v = message[data['MessageType']]
    lon, lat = v.get('Longitude'), v.get('Latitude')
    mmsi = str(meta.get('MMSI', ''))
    observed = stamp(meta.get('time_utc'))
    if not re.fullmatch('[0-9]{9}', mmsi) or not number(lon, -180, 180) or not number(lat, -90, 90) or not observed:
        return None
    heading = v.get('TrueHeading')
    if not number(heading, 0, 359):
        heading = v.get('Cog')
    return dict(id='vessel-' + mmsi, kind='vessel', mmsi=mmsi, name=str(meta.get('ShipName') or mmsi).strip()[:100],
                location={'lon': lon, 'lat': lat}, observed_at=observed,
                speed_kmh=round(v['Sog'] * 1.852, 2) if number(v.get('Sog'), 0, 102.1) else None,
                heading=heading if number(heading, 0, 359.999) else None,
                source='AISStream', source_url='https://aisstream.io/')


def parse_quote(data, symbol, name):
    try:
        chart = data['chart']['result'][0]
        meta = chart['meta']
        price, observed = meta['regularMarketPrice'], meta['regularMarketTime']
        if not number(price, 0.000001) or not number(observed, 1):
            raise ValueError()
        series = [round(v, 5) for v in chart.get('indicators', {}).get('quote', [{}])[0].get('close', []) if number(v, 0.000001)][-40:]
        change = meta.get('regularMarketChangePercent', meta.get('fulldayChangePercent'))
        # chartPreviousClose is the START of the requested range, not yesterday.
        # Only use an explicit day change or a demonstrable previous daily bar.
        if not number(change):
            prev = meta.get('previousClose')
            if not number(prev, 0.000001) and len(series) > 1 and abs(series[-1] - price) < max(price * .00001, .0001):
                prev = series[-2]
            change = (price / prev - 1) * 100 if number(prev, 0.000001) else None
        return dict(id=symbol, name=name, symbol=symbol, price=price, change_percent=change, currency=str(meta.get('currency') or '')[:12],
                    observed_at=int(observed), series=series, source='Yahoo Finance', source_url='https://finance.yahoo.com/quote/' + quote(symbol, safe=''),
                    timeliness='provider_delayed_or_last_session', change_basis='较上个交易日')
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError('invalid_quote_response') from None


def definitions(schema, string):
    return [
        ('commerce_intel_live_get', '只读共享航空器、船舶与行情快照，含观测时间、陈旧/失败/缺少密钥状态；不发起采集',
         schema({'bounds': {'type': 'object'}, 'query': {'type': 'string', 'maxLength': 64}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10000}})),
        ('commerce_intel_live_refresh', '明确刷新公开位置和行情；后台有界执行、跨客户端共用限频，旧观测不冒充实时结果',
         schema({'source': {'type': 'string', 'enum': ['all', *SOURCES]}, 'evaluation': {'type': 'boolean'},
                 'evaluation_session': {'type': 'string', 'enum': ['start', 'stop']},
                 'minutes': {'type': 'integer', 'minimum': 5, 'maximum': 60}})),
    ]


class IntelLive:
    def __init__(self, core, state):
        self.core, self.state = core, Path(state)
        self.lock = threading.RLock()
        self.running = set()
        self.token = None
        self.token_until = 0
        # Development sessions deliberately do not survive service restarts.
        self._evaluation_until = 0
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS intel_live_snapshots (source TEXT PRIMARY KEY, document TEXT NOT NULL)')

    def _config(self):
        try:
            raw = json.loads((self.state / 'intel-live.json').read_text())
        except (OSError, ValueError):
            raw = {}
        values = {k: os.environ.get(k) or (raw.get(k) if isinstance(raw, dict) else None) for k in ('AISSTREAM_API_KEY', 'OPENSKY_CLIENT_ID', 'OPENSKY_CLIENT_SECRET', 'OPENSKY_LICENSE_CONFIRMED', 'OPENSKY_USE_CASE')}
        values['OPENSKY_LICENSE_CONFIRMED'] = values['OPENSKY_LICENSE_CONFIRMED'] is True or values['OPENSKY_LICENSE_CONFIRMED'] in ('1', 'true')
        return values

    def _load(self, source):
        with self.core.db() as db:
            row = db.execute('SELECT document FROM intel_live_snapshots WHERE source=?', (source,)).fetchone()
        return json.loads(row[0]) if row else {}

    def _save(self, source, value):
        with self.core.db() as db:
            db.execute('INSERT OR REPLACE INTO intel_live_snapshots VALUES (?,?)', (source, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def get(self, bounds=None, query='', limit=600):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError('invalid_intel_live_limit')
        bounds = validate_bounds(bounds)
        if not isinstance(query, str) or len(query) > 64:
            raise ValueError('invalid_intel_live_query')
        query = query.strip().casefold()
        now, result, config = time.time(), {}, self._config()
        with self.lock:
            for key, spec in SOURCES.items():
                raw = self._load(key)
                rows = raw.get('items', [])
                fresh = rows if key == 'markets' else [r for r in rows if 0 <= now - r.get('observed_at', 0) <= spec['max_age']]
                items = [r for r in fresh if key == 'markets' or (in_bounds(r['location'], bounds)
                         and (not query or query in ' '.join(str(r.get(k, '')) for k in ('callsign', 'icao24', 'name', 'mmsi', 'country')).casefold()))]
                if key != 'markets':
                    items.sort(key=lambda r: r['observed_at'], reverse=True)
                status = 'failed' if raw.get('error') else 'ready' if raw.get('last_success') else 'idle'
                if status == 'ready' and now - raw['last_success'] > spec['max_age']:
                    status = 'stale'
                if key != 'markets' and rows and not items and all(now - r.get('observed_at', 0) > spec['max_age'] for r in rows):
                    status = 'stale'
                if key == 'vessels' and not config['AISSTREAM_API_KEY']:
                    status = 'requires_config'
                    items = []
                if key == 'flights' and not config['OPENSKY_LICENSE_CONFIRMED']:
                    status = ('failed' if raw.get('error') else 'evaluation') if config['OPENSKY_USE_CASE'] == 'local_development' else 'requires_authorization'
                availability = ('available' if items else 'outside_filter' if fresh else 'expired' if rows
                                else 'empty' if raw.get('last_success') else 'never_received')
                result[key] = dict(name=spec['name'], provider=spec['provider'], source_url=spec['url'], status=status,
                                   availability=availability, fresh_count=len(fresh), expired_count=len(rows)-len(fresh),
                                   items=items[:limit], matched=len(items), truncated=len(items) > limit, observed_at=raw.get('observed_at'),
                                   last_success=raw.get('last_success'), last_attempt=raw.get('last_attempt'), error=raw.get('error'),
                                   unavailable=raw.get('unavailable', []), next_refresh=raw.get('next_refresh', 0),
                                   partial=raw.get('partial', False),
                                   refresh_status='running' if key in self.running else 'idle',
                                   mode=('local_evaluation' if config['OPENSKY_USE_CASE'] == 'local_development' else 'evaluation_snapshot') if key == 'flights' and not config['OPENSKY_LICENSE_CONFIRMED'] else 'provider_snapshot',
                                   interval_seconds=120 if key == 'flights' and config['OPENSKY_CLIENT_ID'] and config['OPENSKY_CLIENT_SECRET'] else spec['interval'])
                if key == 'flights':
                    active = config['OPENSKY_USE_CASE'] == 'local_development' and not config['OPENSKY_LICENSE_CONFIRMED'] and now < self._evaluation_until
                    result[key]['evaluation_session'] = dict(active=active, until=self._evaluation_until or None,
                                                            ended=bool(self._evaluation_until and now >= self._evaluation_until))
        return dict(sources=result, generated_at=int(now), position_capacity=10000, position_limit=limit, coverage='接收站覆盖范围；位置不代表航线、目的地或运营异常',
                    attribution='航空器：The OpenSky Network；船舶：AISStream；行情：Yahoo Finance / CoinPaprika')

    def refresh(self, source='all', evaluation=False, evaluation_session=None, minutes=60):
        if source not in ('all', *SOURCES):
            raise ValueError('invalid_intel_live_source')
        if type(evaluation) is not bool or (evaluation and source != 'flights'):
            raise ValueError('invalid_intel_live_evaluation')
        if evaluation_session is not None and (source != 'flights' or evaluation_session not in ('start', 'stop') or evaluation):
            raise ValueError('invalid_intel_live_session')
        if type(minutes) is not int or not 5 <= minutes <= 60:
            raise ValueError('invalid_intel_live_session_minutes')
        with self.lock:
            config = self._config()
            if evaluation_session == 'stop':
                self._evaluation_until = 0
                return self.get()
            if evaluation_session == 'start':
                if config['OPENSKY_USE_CASE'] != 'local_development' or config['OPENSKY_LICENSE_CONFIRMED']:
                    raise ValueError('local_development_session_required')
                # Retrying the same start cannot silently extend an active session.
                if time.time() >= self._evaluation_until:
                    self._evaluation_until = time.time() + minutes * 60
            for key in SOURCES if source == 'all' else [source]:
                session_active = key == 'flights' and time.time() < self._evaluation_until
                local_sample = (evaluation or session_active) and config['OPENSKY_USE_CASE'] == 'local_development'
                if key in self.running or (key == 'vessels' and not config['AISSTREAM_API_KEY']) or (key == 'flights' and not config['OPENSKY_LICENSE_CONFIRMED'] and not local_sample):
                    continue
                raw = self._load(key)
                if time.time() < raw.get('next_refresh', 0):
                    continue
                interval = 120 if key == 'flights' and config['OPENSKY_CLIENT_ID'] and config['OPENSKY_CLIENT_SECRET'] else SOURCES[key]['interval']
                raw.update(last_attempt=time.time(), next_refresh=time.time() + interval)
                self._save(key, raw)
                self.running.add(key)
                kwargs = {'evaluation_deadline': self._evaluation_until} if session_active else {}
                threading.Thread(target=self._run, args=(key, bool(local_sample)), kwargs=kwargs, daemon=True, name='intel-live-' + key).start()
        return self.get()

    def _run(self, source, evaluation=False, evaluation_deadline=None):
        spec, now, config = SOURCES[source], time.time(), self._config()
        raw = self._load(source)
        interval = 120 if source == 'flights' and config['OPENSKY_CLIENT_ID'] and config['OPENSKY_CLIENT_SECRET'] else spec['interval']
        raw.update(last_attempt=now, next_refresh=now + interval)
        try:
            if source == 'flights':
                if evaluation_deadline is not None and (time.time() >= evaluation_deadline or self._evaluation_until != evaluation_deadline):
                    return
                if not config['OPENSKY_LICENSE_CONFIRMED'] and not (evaluation and config['OPENSKY_USE_CASE'] == 'local_development'):
                    raise ValueError('opensky_license_required')
                headers = {}
                if config['OPENSKY_CLIENT_ID'] and config['OPENSKY_CLIENT_SECRET']:
                    if not self.token or time.time() > self.token_until:
                        auth = fetch_json('https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token', form={
                            'grant_type': 'client_credentials', 'client_id': config['OPENSKY_CLIENT_ID'], 'client_secret': config['OPENSKY_CLIENT_SECRET']})
                        self.token, self.token_until = auth['access_token'], time.time() + min(int(auth['expires_in']), 3600) - 30
                    headers['Authorization'] = 'Bearer ' + self.token
                data = fetch_json('https://opensky-network.org/api/states/all', headers=headers)
                value = dict(items=parse_flights(data), observed_at=data['time'])
            elif source == 'vessels':
                value = self._vessels(config['AISSTREAM_API_KEY'])
                kept = {r['id']: r for r in raw.get('items', []) if 0 <= time.time()-r.get('observed_at', 0) <= spec['max_age']}
                kept.update({r['id']: r for r in value['items']})
                value['items'] = sorted(kept.values(), key=lambda r: r['observed_at'], reverse=True)[:5000]
            else:
                value = self._markets()
            raw.update(value, last_success=time.time(), error=None, consecutive_failures=0)
        except Exception as error:
            code = str(error)
            # Only fixed safe diagnostic codes are exposed; provider strings and
            # exceptions may carry credentials, request URLs or response bodies.
            raw['error'] = code if code in AIS_ERRORS or re.fullmatch(r'(upstream_http_[0-9]{3}|upstream_connection_or_format_error|invalid_opensky_response|opensky_license_required|market_sources_unavailable|ais_http_[0-9]{3})', code) else 'upstream_unavailable'
            if code == 'upstream_http_429':
                raw['next_refresh'] = now + max(interval, 3600)
            if source == 'vessels':
                failures = min(5, raw.get('consecutive_failures', 0) + 1)
                raw.update(consecutive_failures=failures,
                           next_refresh=now + max(interval, min(900, interval * 2 ** failures) * uniform(.9, 1.1)))
            if code in ('upstream_http_401', 'upstream_http_403'):
                self.token = None
        finally:
            with self.lock:
                try:
                    self._save(source, raw)
                finally:
                    self.running.discard(source)

    def _vessels(self, key):
        try:
            from websockets.sync.client import connect
        except ImportError:
            # The stdlib-only daily service reuses the existing project crawler
            # environment. Secrets travel through stdin, never process arguments.
            python = Path(__file__).resolve().parents[1] / '.local/crawlers/venv/bin/python'
            if os.environ.get('COMMERCE_INTEL_AIS_WORKER') == '1' or not python.is_file():
                raise ValueError('ais_client_unavailable') from None
            result = subprocess.run([str(python), str(Path(__file__).resolve()), '--ais-worker'], input=json.dumps({'key': key}),
                                    text=True, capture_output=True, timeout=30,
                                    env={**os.environ, 'COMMERCE_INTEL_AIS_WORKER': '1'})
            if result.returncode:
                raise ValueError('ais_client_unavailable') from None
            value = json.loads(result.stdout)
            if value.get('error'):
                raise ValueError(value['error'])
            return value
        from websockets.exceptions import ConnectionClosed, InvalidStatus
        found, deadline, partial = {}, time.monotonic() + 18, False
        try:
            with connect('wss://stream.aisstream.io/v0/stream', proxy=ais_proxy(), open_timeout=8, close_timeout=1, max_size=1_000_000) as socket:
                socket.send(json.dumps({'APIKey': key, 'BoundingBoxes': [[[-90, -180], [90, 180]]],
                                        'FilterMessageTypes': ['PositionReport', 'StandardClassBPositionReport']}))
                while time.monotonic() < deadline and len(found) < 5000:
                    try:
                        data = json.loads(socket.recv(timeout=min(2, max(.01, deadline-time.monotonic()))))
                    except TimeoutError:
                        continue
                    except (ValueError, UnicodeError):
                        continue
                    if not isinstance(data, dict):
                        continue
                    if data.get('error') or data.get('Error'):
                        raise ValueError('ais_subscription_rejected')
                    row = parse_vessel(data)
                    if row:
                        found[row['id']] = row
        except ImportError:
            raise ValueError('ais_proxy_dependency_missing') from None
        except ConnectionClosed:
            if not found:
                raise ValueError('ais_stream_disconnected') from None
            partial = True
        except InvalidStatus as error:
            raise ValueError('ais_http_' + str(error.response.status_code)) from None
        except (OSError, TimeoutError):
            raise ValueError('ais_connection_failed') from None
        if not found:
            raise ValueError('ais_no_positions')
        return dict(items=list(found.values()), observed_at=max(r['observed_at'] for r in found.values()), partial=partial)

    def _markets(self):
        def get(spec):
            symbol, name = spec
            try:
                if symbol in ('BTC', 'ETH'):
                    ticker = fetch_json('https://api.coinpaprika.com/v1/tickers/' + ('btc-bitcoin' if symbol == 'BTC' else 'eth-ethereum'))
                    q = ticker['quotes']['USD']
                    if not number(q['price'], .000001) or not stamp(ticker['last_updated']):
                        raise ValueError()
                    return dict(id=symbol, name=name, symbol=symbol, currency='USD', price=q['price'], change_percent=q.get('percent_change_24h') if number(q.get('percent_change_24h')) else None,
                                observed_at=stamp(ticker['last_updated']), series=[], source='CoinPaprika', source_url='https://coinpaprika.com/',
                                timeliness='provider_snapshot', change_basis='24小时')
                data = fetch_json('https://query1.finance.yahoo.com/v8/finance/chart/' + quote(symbol, safe='') + '?interval=1d&range=1mo')
                return parse_quote(data, symbol, name)
            except Exception:
                return {'id': symbol, 'unavailable': True, 'reason': 'provider_unavailable'}
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(get, [*SYMBOLS, ('BTC', '比特币'), ('ETH', '以太坊')]))
        good = [v for v in values if not v.get('unavailable')]
        if not good:
            raise ValueError('market_sources_unavailable')
        return dict(items=good, unavailable=[v for v in values if v.get('unavailable')], observed_at=max(v['observed_at'] for v in good))


if __name__ == '__main__':
    if sys.argv[1:] == ['--ais-client-check']:
        try:
            from websockets.sync.client import connect
            print(json.dumps({'client_available': True}))
        except ImportError:
            python = Path(__file__).resolve().parents[1] / '.local/crawlers/venv/bin/python'
            if os.environ.get('COMMERCE_INTEL_AIS_WORKER') == '1' or not python.is_file():
                print(json.dumps({'client_available': False}))
            else:
                result = subprocess.run([str(python), str(Path(__file__).resolve()), '--ais-client-check'], text=True, capture_output=True, timeout=5,
                                        env={**os.environ, 'COMMERCE_INTEL_AIS_WORKER': '1'})
                print(result.stdout.strip() if result.returncode == 0 else json.dumps({'client_available': False}))
    elif sys.argv[1:] == ['--ais-worker'] and os.environ.get('COMMERCE_INTEL_AIS_WORKER') == '1':
        try:
            secret = json.loads(sys.stdin.read(8192))['key']
            if not isinstance(secret, str) or not 1 <= len(secret) <= 4096:
                raise ValueError()
            print(json.dumps(IntelLive._vessels(None, secret), allow_nan=False))
        except Exception as error:
            code = str(error)
            print(json.dumps({'error': code if code in AIS_ERRORS or re.fullmatch('ais_http_[0-9]{3}', code) else 'upstream_unavailable'}))
