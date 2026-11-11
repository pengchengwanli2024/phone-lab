"""No network: feed integrity, retrieval boundaries, failure retention and MCP surface."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce, TOOLS
from intelligence import parse, safe_url, FixedRedirect


def quake():
    return json.dumps({'type': 'FeatureCollection', 'features': [
        {'id': 'synthetic-eq', 'properties': {'title': 'Synthetic earthquake 4.8', 'url': 'https://example.org/eq', 'time': 1700000000000}, 'geometry': {'coordinates': [110, 30, 10]}}
    ]}).encode()


RSS = b'''<rss xmlns:g="http://www.gdacs.org" xmlns:geo="http://www.georss.org/georss"><channel><item>
<title>Synthetic flood in Mexico</title><link>https://example.org/flood</link>
<pubDate>Tue, 14 Nov 2023 22:13:20 GMT</pubDate><g:eventid>1</g:eventid>
<g:country>Mexico</g:country><g:iso3>MEX</g:iso3><g:alertlevel>Orange</g:alertlevel>
<geo:point>19 -99</geo:point></item></channel></rss>'''


class FeedIntegrity(unittest.TestCase):
    def test_metadata_identity_and_coordinates(self):
        rows = parse('usgs', quake())
        self.assertEqual(rows[0]['location'], {'lon': 110.0, 'lat': 30.0})
        self.assertIsNone(rows[0]['country'])
        self.assertEqual(rows[0]['published'], 1700000000)
        flood = parse('gdacs', RSS)[0]
        self.assertEqual(flood['country_code'], 'MEX')
        self.assertEqual(flood['location']['lon'], -99)

    def test_untrusted_url_and_xml_are_rejected(self):
        for value in ['javascript:alert(1)', 'file:///private/data', 'https://name:pass@example.org', '//example.org']:
            self.assertIsNone(safe_url(value))
        with self.assertRaises(ValueError):
            parse('gdacs', b'<!DOCTYPE rss [<!ENTITY a "x">]><rss/>')
        with self.assertRaises(ValueError):
            parse('wto', b'<html><body>not a feed</body></html>')
        from urllib.request import Request
        with self.assertRaises(ValueError):
            FixedRedirect().redirect_request(Request('https://www.gdacs.org/xml/rss.xml'), None, 302, '', {}, 'http://127.0.0.1/private')

    def test_ids_do_not_merge_unrelated_gdacs_event_types(self):
        data = RSS.replace(b'</channel>', b'<item><title>Synthetic cyclone</title><link>https://example.org/cyclone</link><g:eventid>1</g:eventid></item></channel>')
        self.assertEqual(len(parse('gdacs', data)), 2)


class SharedIntelligence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, args=None, client='test'):
        return self.app.invoke('commerce_' + name, args or {}, client)

    def test_cold_start_is_unknown_and_does_not_fetch(self):
        with patch('intelligence.fetch') as network:
            states = self.call('intel_sources')['sources']
            self.assertTrue(all(s['freshness'] == 'never_collected' for s in states))
            self.assertEqual(self.call('intel_search')['total'], 0)
            self.assertFalse(self.call('worldmonitor_status')['data_calls_made'])
            network.assert_not_called()

    def test_refresh_shared_search_and_cooldown(self):
        with patch('intelligence.fetch', return_value=RSS) as network:
            first = self.call('intel_refresh', {'source': 'gdacs'}, 'hermes')
            second = self.call('intel_refresh', {'source': 'gdacs'}, 'codex')
            self.assertEqual(first['status'], 'completed')
            self.assertEqual(second['status'], 'cooldown')
            self.assertEqual(network.call_count, 1)
        result = self.call('intel_search', {'query': '洪水', 'country': 'MEX'}, 'harness')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['store_impact'], 'not_assessed')
        self.assertEqual(len(result['items'][0]['source_payload_sha256']), 64)
        self.assertEqual(Commerce(self.tmp.name).intelligence.search()['total'], 1)
        self.assertEqual(self.call('intel_search', {'country': 'RUS'})['total'], 0)
        with self.assertRaises(ValueError):
            self.call('intel_refresh', {'source': 'https://127.0.0.1'})

    def test_failure_retains_old_snapshot_and_success_time(self):
        with patch('intelligence.fetch', return_value=quake()), patch('intelligence.time.time', return_value=1700000100):
            self.call('intel_refresh', {'source': 'usgs'})
        with patch('intelligence.fetch', side_effect=TimeoutError()), patch('intelligence.time.time', return_value=1700030100):
            result = self.call('intel_refresh', {'source': 'usgs'})
            source = next(s for s in result['sources'] if s['id'] == 'usgs')
            self.assertEqual(source['status'], 'failed')
            self.assertEqual(source['last_success'], 1700000100)
            self.assertEqual(source['freshness'], 'stale')
            self.assertEqual(source['error'], 'source_unavailable')
            self.assertEqual(self.call('intel_search')['total'], 1)
            self.assertEqual(self.call('intel_search', {'hours': '24'})['total'], 1)

    def test_duplicate_refresh_and_quotes_do_not_corrupt_or_expand_search(self):
        with patch('intelligence.fetch', return_value=RSS), patch('intelligence.time.time', return_value=1700000100):
            self.call('intel_refresh', {'source': 'gdacs'})
        with patch('intelligence.fetch', return_value=RSS), patch('intelligence.time.time', return_value=1700000300):
            self.call('intel_refresh', {'source': 'gdacs'})
        self.assertEqual(self.call('intel_search')['total'], 1)
        self.assertEqual(self.call('intel_search', {'query': "' OR 1=1 --"})['total'], 0)

    def test_worldmonitor_discovery_is_not_data_authentication(self):
        payload = {'jsonrpc': '2.0', 'id': 1, 'result': {'tools': [{'name': 'get_news_clusters'}]}}
        with patch('intelligence.fetch', return_value=json.dumps(payload).encode()) as network:
            result = self.call('worldmonitor_status', {'discover': True})
            self.assertEqual(result['discovery']['tool_count'], 1)
            self.assertFalse(result['data_calls_made'])
            self.assertEqual(network.call_args.args[1]['method'], 'tools/list')
        self.assertTrue({'commerce_intel_search', 'commerce_intel_refresh', 'commerce_intel_sources', 'commerce_worldmonitor_status'} <= {x[0] for x in TOOLS})


if __name__ == '__main__':
    unittest.main()
