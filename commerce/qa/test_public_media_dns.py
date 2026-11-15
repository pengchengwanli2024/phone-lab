"""Public resolver responses remain bounded, unicast-only and credential-free."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_media_dns import resolve_public_ipv4


class PublicMediaDNS(unittest.TestCase):
    def connection(self, payload, status=200):
        connection = MagicMock()
        connection.getresponse.return_value.status = status
        connection.getresponse.return_value.read.return_value = json.dumps(payload).encode()
        return connection

    def test_global_ipv4_only_and_fixed_tls_resolver(self):
        connection = self.connection({'Status': 0, 'Answer': [
            {'type': 5, 'data': 'cdn.example'}, {'type': 1, 'data': '1.1.1.1'}, {'type': 1, 'data': '1.1.1.1'}]})
        factory = MagicMock(return_value=connection)
        self.assertEqual(resolve_public_ipv4('a.lovart.ai', factory, 'media_provider'), ['1.1.1.1'])
        factory.assert_called_once_with('cloudflare-dns.com', '1.1.1.1')
        self.assertEqual(connection.request.call_args.args[:2], ('GET', '/dns-query?name=a.lovart.ai&type=A'))
        self.assertEqual(connection.request.call_args.kwargs['headers'], {'Accept': 'application/dns-json'})
        connection.close.assert_called_once()

    def test_private_reserved_multicast_ipv6_and_mixed_answers_are_rejected(self):
        for values in [['127.0.0.1'], ['10.0.0.1'], ['169.254.169.254'], ['198.18.0.5'],
                       ['224.0.0.1'], ['2606:4700:4700::1111'], ['1.1.1.1', '127.0.0.1']]:
            connection = self.connection({'Status': 0, 'Answer': [{'type': 1, 'data': value} for value in values]})
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, 'media_provider_dns_invalid'):
                resolve_public_ipv4('a.lovart.ai', lambda *args: connection, 'media_provider')
            connection.close.assert_called_once()

    def test_redirects_oversized_and_malformed_responses_are_rejected(self):
        for payload, status in [({}, 302), ({'Status': False, 'Answer': []}, 200),
                                ({'Status': 0, 'Answer': [{}] * 101}, 200),
                                ({'Status': 0, 'Answer': []}, 200), ({'Status': 2}, 200)]:
            connection = self.connection(payload, status)
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'catalog_image_dns_'):
                resolve_public_ipv4('ir-20.ozonstatic.cn', lambda *args: connection, 'catalog_image')
            self.assertEqual(connection.request.call_count, 1)
            connection.close.assert_called_once()
        connection = self.connection({})
        connection.getresponse.return_value.read.return_value = b'x' * 32769
        with self.assertRaisesRegex(ValueError, 'media_provider_dns_invalid'):
            resolve_public_ipv4('a.lovart.ai', lambda *args: connection, 'media_provider')
        connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
