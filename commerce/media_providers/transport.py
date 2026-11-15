"""Bounded, DNS-pinned HTTP without redirects, proxies or ambient credentials."""
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlsplit, urlunsplit
from public_media_dns import resolve_public_ipv4


class TransportError(ValueError):
    def __init__(self, code, *, ambiguous=False):
        super().__init__(code)
        self.ambiguous = ambiguous


def _local(address):
    address = ipaddress.ip_address(address)
    return address.is_loopback or (address.is_private and not (address.is_link_local or address.is_reserved or address.is_unspecified or address.is_multicast))


def endpoint(value, local=False):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 2000 or any(ord(c) < 33 for c in value): raise ValueError()
        p = urlsplit(value)
        if not p.hostname or p.username is not None or p.password is not None or p.query or p.fragment: raise ValueError()
        if p.scheme not in ('http', 'https') or (p.scheme == 'http' and not local): raise ValueError()
        if p.port is not None and not 1 <= p.port <= 65535: raise ValueError()
        if any(x in p.path for x in ('..', '%', '\\')): raise ValueError()
        try:
            ip = ipaddress.ip_address(p.hostname)
        except ValueError:
            ip = None
        if ip and not (_local(str(ip)) if local else ip.is_global): raise ValueError()
        return urlunsplit((p.scheme, p.netloc, p.path.rstrip('/'), '', ''))
    except (ValueError, TypeError):
        raise ValueError('media_provider_invalid_endpoint') from None


def origin(url):
    p = urlsplit(url)
    return p.scheme, p.hostname, p.port or (443 if p.scheme == 'https' else 80)


def relative(base, path):
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or any(x in path for x in ('\\', '\r', '\n', '..')):
        raise ValueError('media_provider_invalid_relative_path')
    # Appending preserves explicitly configured gateway path prefixes.
    url = base.rstrip('/') + path
    if origin(url) != origin(base) or urlsplit(url).fragment:
        raise ValueError('media_provider_invalid_relative_path')
    return url


class _HTTP(http.client.HTTPConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class _HTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def public_dns_addresses(host):
    return resolve_public_ipv4(host, lambda name, address: _HTTPS(name, 443, address, 8), 'media_provider')


def request(config, method, path=None, *, data=None, content_type=None, url=None, limit=2 * 1024 * 1024, api_key='', timeout=12):
    base = config['base_url']
    url = url or relative(base, path)
    p = urlsplit(url)
    same_origin = origin(url) == origin(base)
    local = config['provider'] == 'local' and same_origin
    if not p.hostname or p.username is not None or p.password is not None or p.fragment or p.scheme not in ('http', 'https') or (p.scheme != 'https' and not local):
        raise TransportError('media_provider_result_url_rejected')
    port = p.port or (443 if p.scheme == 'https' else 80)
    try:
        addresses = list(dict.fromkeys(r[4][0] for r in socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)))
        # Only an already-created Lovart artifact may recover this known local
        # proxy DNS condition. API submissions and arbitrary URLs stay closed.
        fake = ipaddress.ip_network('198.18.0.0/15')
        if (not local and method == 'GET' and path is None and data is None
                and config['provider'] == 'lovart' and origin(base) == ('https', 'lovart.ai', 443)
                and p.scheme == 'https' and p.hostname == 'a.lovart.ai' and port == 443
                and p.path.startswith('/artifacts/generator/') and not api_key and not config.get('_headers')
                and addresses and all(ipaddress.ip_address(address) in fake for address in addresses)):
            try:
                addresses = public_dns_addresses(p.hostname)
            except ValueError as error:
                raise TransportError('media_provider_dns_invalid' if str(error).endswith('_dns_invalid')
                                     else 'media_provider_dns_unavailable') from None
        if not addresses or any(not (_local(a) if local else ipaddress.ip_address(a).is_global) for a in addresses):
            raise TransportError('media_provider_address_rejected')
    except (OSError, ValueError) as error:
        if isinstance(error, TransportError): raise
        raise TransportError('media_provider_dns_unavailable') from None
    headers = {'Accept': 'application/json' if url is None else '*/*', 'User-Agent': 'commerce-media/1.0'}
    if data is not None:
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            content_type = 'application/json'
        headers['Content-Type'] = content_type or 'application/octet-stream'
    # Foreign public result hosts never receive the configured credential.
    if same_origin and api_key:
        headers[config.get('auth_header', 'Authorization')] = ('Bearer ' if config.get('auth_scheme', 'Bearer') == 'Bearer' else '') + api_key
    headers.update(config.get('_headers', {}) if same_origin else {})
    connection = (_HTTPS if p.scheme == 'https' else _HTTP)(p.hostname, port, addresses[0], timeout)
    sent = False
    try:
        sent = True
        connection.request(method, p.path or '/' if not p.query else (p.path or '/') + '?' + p.query, body=data, headers=headers)
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            raise TransportError('media_provider_http_' + str(response.status), ambiguous=method != 'GET' and (response.status >= 500 or response.status == 408))
        size = response.getheader('Content-Length')
        if size and (not size.isdigit() or int(size) > limit): raise TransportError('media_provider_response_too_large', ambiguous=method != 'GET')
        chunks = []; received = 0; deadline = time.monotonic() + 40
        read = getattr(response, 'read1', response.read)
        while True:
            if time.monotonic() >= deadline: raise TransportError('media_provider_response_timeout', ambiguous=method != 'GET')
            chunk = read(min(65536, limit + 1 - received))
            if not chunk: break
            received += len(chunk)
            if received > limit: raise TransportError('media_provider_response_too_large', ambiguous=method != 'GET')
            chunks.append(chunk)
        return b''.join(chunks)
    except (OSError, ssl.SSLError, http.client.HTTPException):
        raise TransportError('media_provider_transport_unavailable', ambiguous=sent and method != 'GET') from None
    finally:
        connection.close()


def json_request(config, method, path, **kwargs):
    raw = request(config, method, path, **kwargs)
    try:
        value = json.loads(raw)
        if not isinstance(value, dict): raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise TransportError('media_provider_invalid_response', ambiguous=method != 'GET') from None
