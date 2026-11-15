"""Recover known CDN fake-IP reads without widening media network authority."""
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media_providers import transport as net


class OutputNetwork(unittest.TestCase):
    config = {'provider': 'lovart', 'base_url': 'https://lovart.ai'}
    url = 'https://a.lovart.ai/artifacts/generator/synthetic.png'

    def addresses(self, *values):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (value, 443)) for value in values]

    def connection(self, status=200):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = status
        response.getheader.return_value = None
        response.read1.side_effect = [b'synthetic-result', b'']
        return connection

    def test_known_lovart_generated_file_get_recovers_fake_ip_with_pinned_tls(self):
        connection = self.connection()
        with patch.object(net.socket, 'getaddrinfo', return_value=self.addresses('198.18.0.5')), \
                patch.object(net, 'public_dns_addresses', return_value=['1.1.1.1'], create=True) as dns, \
                patch.object(net, '_HTTPS', return_value=connection) as https:
            self.assertEqual(net.request(self.config, 'GET', url=self.url), b'synthetic-result')
        dns.assert_called_once_with('a.lovart.ai')
        https.assert_called_once_with('a.lovart.ai', 443, '1.1.1.1', 12)
        headers = connection.request.call_args.kwargs['headers']
        self.assertFalse(set(key.lower() for key in headers) & {'authorization', 'cookie', 'api-key'})

    def test_public_local_dns_answer_does_not_use_public_resolver(self):
        with patch.object(net.socket, 'getaddrinfo', return_value=self.addresses('1.1.1.1')), \
                patch.object(net, 'public_dns_addresses', create=True) as dns, \
                patch.object(net, '_HTTPS', return_value=self.connection()):
            self.assertEqual(net.request(self.config, 'GET', url=self.url), b'synthetic-result')
        dns.assert_not_called()

    def test_fallback_is_not_available_to_other_origins_methods_paths_or_credentials(self):
        cases = [
            ({'provider': 'local', 'base_url': 'https://lovart.ai'}, 'GET', self.url, {}),
            ({'provider': 'lovart', 'base_url': 'https://other.example'}, 'GET', self.url, {}),
            (self.config, 'POST', self.url, {}),
            (self.config, 'GET', 'https://evil.lovart.ai/artifacts/generator/x.png', {}),
            (self.config, 'GET', 'https://a.lovart.ai.attacker.example/artifacts/generator/x.png', {}),
            (self.config, 'GET', 'https://a.lovart.ai:444/artifacts/generator/x.png', {}),
            (self.config, 'GET', 'https://a.lovart.ai/private/x.png', {}),
            (self.config, 'GET', self.url, {'api_key': 'synthetic-only'}),
            ({**self.config, '_headers': {'X-Api-Key': 'synthetic-only'}}, 'GET', self.url, {}),
        ]
        for config, method, url, arguments in cases:
            with self.subTest(config=config, method=method, url=url), \
                    patch.object(net.socket, 'getaddrinfo', return_value=self.addresses('198.18.0.5')), \
                    patch.object(net, 'public_dns_addresses', create=True) as dns, \
                    patch.object(net, '_HTTPS') as https:
                with self.assertRaisesRegex(net.TransportError, 'address_rejected'):
                    net.request(config, method, url=url, **arguments)
                dns.assert_not_called()
                https.assert_not_called()

    def test_private_or_mixed_local_answers_are_never_recovered(self):
        for values in [('127.0.0.1',), ('10.0.0.1',), ('169.254.169.254',),
                       ('1.1.1.1', '198.18.0.5'), ('198.18.0.5', '127.0.0.1')]:
            with self.subTest(values=values), \
                    patch.object(net.socket, 'getaddrinfo', return_value=self.addresses(*values)), \
                    patch.object(net, 'public_dns_addresses', create=True) as dns:
                with self.assertRaisesRegex(net.TransportError, 'address_rejected'):
                    net.request(self.config, 'GET', url=self.url)
                dns.assert_not_called()

    def test_resolver_result_is_revalidated_before_any_connection(self):
        for values in [[], ['127.0.0.1'], ['1.1.1.1', '10.0.0.1']]:
            with self.subTest(values=values), \
                    patch.object(net.socket, 'getaddrinfo', return_value=self.addresses('198.18.0.5')), \
                    patch.object(net, 'public_dns_addresses', return_value=values, create=True) as dns, \
                    patch.object(net, '_HTTPS') as https:
                with self.assertRaisesRegex(net.TransportError, 'address_rejected'):
                    net.request(self.config, 'GET', url=self.url)
                dns.assert_called_once()
                https.assert_not_called()

    def test_cdn_redirect_is_rejected_instead_of_followed(self):
        connection = self.connection(status=302)
        with patch.object(net.socket, 'getaddrinfo', return_value=self.addresses('198.18.0.5')), \
                patch.object(net, 'public_dns_addresses', return_value=['1.1.1.1'], create=True), \
                patch.object(net, '_HTTPS', return_value=connection):
            with self.assertRaisesRegex(net.TransportError, 'http_302'):
                net.request(self.config, 'GET', url=self.url)
        self.assertEqual(connection.request.call_count, 1)
        connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
