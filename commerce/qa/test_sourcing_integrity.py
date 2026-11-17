"""Product identity and redirect boundaries with synthetic responses only."""
from pathlib import Path
import io
import json
import sys
import unittest
from email.message import Message
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import test_organization as fixtures
from public_web import PublicWeb, parse_page
from sourcing_extract import html_product, imported


def product(sku='222', **extra):
    return {'@type': 'Product', 'name': 'Synthetic rack ' + sku, 'sku': sku,
            'url': 'https://item.jd.com/' + sku + '.html',
            'image': 'https://img.example.com/' + sku + '.png',
            'offers': {'@type': 'Offer', 'price': '88', 'priceCurrency': 'CNY'}, **extra}


def page(data):
    return '<title>Synthetic product</title><main>Synthetic readable body.</main><script type="application/ld+json">' + json.dumps(data) + '</script>'


class Response:
    def __init__(self, status=200, body=b'', location=None):
        self.status = status
        self.body = io.BytesIO(body)
        self.headers = Message()
        self.headers['Content-Type'] = 'text/html'
        if location:
            self.headers['Location'] = location

    def getheader(self, name):
        return self.headers.get(name)

    def read1(self, size):
        return self.body.read1(size)


class SourcingIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests()
        self.fixture.setUp()
        self.app = self.fixture.app
        self.sourcing = self.app.product_evidence.sourcing
        self.case_id = self.fixture.cid

    def tearDown(self):
        self.fixture.tearDown()

    def preview(self, key='read'):
        return self.sourcing.preview(self.case_id, 'jd', 'https://item.jd.com/111.html', 'public', key)

    def test_redirect_uses_resolved_source_and_retains_requested_url(self):
        self.app.public_web = PublicWeb(self.app.state, reader=lambda *_: parse_page(page(product()), 'https://item.jd.com/222.html'))
        result = self.preview()
        self.assertEqual(result['draft']['url'], 'https://item.jd.com/222.html')
        self.assertIn('https://item.jd.com/111.html', result['draft']['notes'])
        self.assertIn('https://item.jd.com/222.html', result['draft']['notes'])
        self.assertEqual(result['status'], 'preview_partial')

    def test_cross_platform_redirect_is_rejected_before_connection(self):
        calls = []
        class Connection:
            def __init__(self, host, address):
                self.host = host
                calls.append(host)
            def request(self, *args, **kwargs):
                pass
            def getresponse(self):
                if self.host == 'item.jd.com':
                    return Response(302, location='https://detail.1688.com/offer/222.html')
                return Response(body=page(product()).encode())
            def close(self):
                pass
        self.app.public_web = PublicWeb(self.app.state)
        with patch('public_web_transport.addresses', return_value=['93.184.216.34']) as resolver, patch('public_web_transport.PublicConnection', Connection):
            result = self.preview()
        self.assertEqual(result['status'], 'needs_export')
        self.assertIsNone(result['draft'])
        self.assertEqual(calls, ['item.jd.com'])
        resolver.assert_called_once_with('item.jd.com')

    def test_single_recommendation_cannot_supply_primary_product_facts(self):
        self.assertIsNone(html_product(page(product()), 'https://item.jd.com/111.html'))

    def test_import_conflicting_product_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'product_url_mismatch'):
            imported(json.dumps(product()), 'json', 'https://item.jd.com/111.html')

    def test_same_product_fragment_and_tracking_do_not_change_identity(self):
        value = product('111', url='https://item.jd.com/111.html?utm_source=synthetic#product')
        result = html_product(page(value), 'https://item.jd.com/111.html')
        self.assertEqual(result['model'], '111')

    def test_legacy_single_product_export_without_url_still_imports(self):
        value = product('111')
        value.pop('url')
        self.assertEqual(imported(json.dumps(value), 'json', 'https://item.jd.com/111.html')['model'], '111')

    def test_item_offered_variant_and_sku_remain_attached_to_their_price(self):
        value = product('111', offers=[
            {'@type': 'Offer', 'price': '8', 'priceCurrency': 'CNY', 'itemOffered': {'@type': 'Product', 'sku': 'SMALL', 'name': 'Small rack'}},
            {'@type': 'Offer', 'price': '88', 'priceCurrency': 'CNY', 'itemOffered': {'@type': 'Product', 'sku': 'LARGE', 'name': 'Large rack'}}])
        result = imported(json.dumps(value), 'json', 'https://item.jd.com/111.html')
        self.assertEqual([(r['price'], r['variant']) for r in result['offers']], [('8', 'Small rack'), ('88', 'Large rack')])
        self.assertEqual([r['sku'] for r in result['offers']], ['SMALL', 'LARGE'])
        self.assertEqual(result['variant'], '', 'Family is not silently assigned the cheapest variant')

    def test_primary_matching_product_is_selected_instead_of_recommendation(self):
        result = html_product(page([product('222'), product('111')]), 'https://item.jd.com/111.html')
        self.assertEqual(result['model'], '111')


if __name__ == '__main__':
    unittest.main()
