"""Bounded public DNS over a caller-supplied, pinned TLS connection."""
import http.client
import ipaddress
import json
import ssl
from urllib.parse import quote


def resolve_public_ipv4(host, connection_factory, error_prefix):
    connection = connection_factory('cloudflare-dns.com', '1.1.1.1')
    invalid = error_prefix + '_dns_invalid'
    unavailable = error_prefix + '_dns_unavailable'
    try:
        connection.request('GET', '/dns-query?name=' + quote(host, safe='') + '&type=A',
                           headers={'Accept': 'application/dns-json'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(unavailable)
        raw = response.read(32769)
        if len(raw) > 32768:
            raise ValueError(invalid)
        payload = json.loads(raw)
        if type(payload) is not dict or type(payload.get('Status')) is not int or payload['Status'] != 0:
            raise ValueError(invalid)
        answers = payload.get('Answer')
        if type(answers) is not list or len(answers) > 100:
            raise ValueError(invalid)
        addresses = list(dict.fromkeys(row['data'] for row in answers
                                       if type(row) is dict and type(row.get('type')) is int and row['type'] == 1))
        if not addresses or any(not isinstance(value, str)
                                or not isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
                                or not ipaddress.ip_address(value).is_global
                                or ipaddress.ip_address(value).is_multicast for value in addresses):
            raise ValueError(invalid)
        return addresses
    except (OSError, ssl.SSLError, http.client.HTTPException):
        raise ValueError(unavailable) from None
    except (KeyError, TypeError, UnicodeError):
        raise ValueError(invalid) from None
    except ValueError as error:
        if str(error) in (invalid, unavailable):
            raise
        raise ValueError(invalid) from None
    finally:
        connection.close()
