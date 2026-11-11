"""Synthetic product contracts; public prices are never merchant costs."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'crawlers'))
from structured import products
from worker import parse_feed
from collect import fingerprint


class BusinessAdapters(unittest.TestCase):
    def setUp(self):
        self.node={'@type':'Product','sku':'SYN-1','name':'Synthetic &amp; product',
                   'offers':{'@type':'Offer','price':'12.50','priceCurrency':'USD','availability':'https://schema.org/InStock'}}
    def extract(self):return products([json.dumps({'@graph':[self.node]})],'https://example.org/product/1')
    def test_graph_explicit_offer_and_original_currency(self):
        row=self.extract()[0]
        self.assertEqual((row['title'],row['currency'],row['stock']),('Synthetic & product','USD','InStock'))
        self.assertEqual(row['url'],'https://example.org/product/1')
    def test_ambiguous_variants_never_pick_cheapest(self):
        self.node['offers']=[self.node['offers'],dict(self.node['offers'],price='3')]
        with self.assertRaisesRegex(ValueError,'ambiguous'):self.extract()
    def test_missing_currency_and_inventory_are_not_invented(self):
        del self.node['offers']['priceCurrency'];del self.node['offers']['availability']
        row=self.extract()[0]
        self.assertEqual((row['currency'],row['stock']),('',''))
        self.assertEqual(fingerprint({'status':'ok','rows':[row]},'product-schema',1)[1],'incomplete_fields')
    def test_atom_namespaces_and_missing_date(self):
        data=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>synthetic-1</id><title>Synthetic transport news</title><link href="/news/1"/></entry></feed>'
        row=parse_feed(data,'https://example.org/feed')[0]
        self.assertEqual(row['url'],'https://example.org/news/1');self.assertEqual(row['published'],'')


if __name__=='__main__':unittest.main()
