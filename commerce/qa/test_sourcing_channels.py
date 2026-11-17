"""Meaningful multi-channel acquisition boundaries; no real network or orders."""
from pathlib import Path
import json, sys, unittest
from unittest.mock import Mock, patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import test_organization as fixtures
from sourcing_extract import html_product, imported
from public_web import parse_page

class SourcingTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OrganizationTests();self.f.setUp();self.app=self.f.app;self.cid=self.f.cid
        self.s=self.app.product_evidence.sourcing
        self.doc={'title':'合成桌面架','model':'TEST','images':['https://img.example.com/original.jpg'],
                  'offers':[{'price':'21.85','currency':'CNY','variant':'普通款','moq':2}]}
    def tearDown(self):self.f.tearDown()
    def preview(self,**kw):
        args={'case_id':self.cid,'platform':'jd','url':'https://item.jd.com/123.html','mode':'import',
              'content':json.dumps(self.doc),'format':'json','idempotency_key':'p'};args.update(kw)
        return self.s.preview(**args)
    def test_import_preview_preserves_prices_images_and_never_creates_quote_or_source(self):
        before=self.app.product_evidence.get(self.cid)
        r=self.preview();self.assertEqual(r['status'],'preview_ready')
        self.assertEqual(r['product']['offers'][0]['price'],'21.85')
        self.assertEqual(r['product']['offers'][0]['currency'],'CNY')
        self.assertEqual(r['draft']['images'][0]['url'],self.doc['images'][0])
        after=self.app.product_evidence.get(self.cid)
        self.assertEqual(before['sources'],after['sources']);self.assertEqual(before['quotes'],after['quotes'])
        self.assertIn('非本次原站实时采集',r['draft']['notes'])
    def test_idempotent_receipt_conflict_and_case_scope(self):
        a=self.preview();b=self.preview();self.assertEqual(a['id'],b['id'])
        with self.assertRaisesRegex(ValueError,'conflict'):self.preview(content=json.dumps({'title':'改了'}))
        with self.assertRaises(ValueError):self.s.history('other-case')
    def test_known_restricted_channel_does_not_call_network(self):
        self.app.public_web=Mock()
        r=self.preview(platform='1688',url='https://detail.1688.com/offer/123.html',mode='public')
        self.assertEqual(r['status'],'export_required');self.app.public_web.read.assert_not_called()
        r=self.s.search(self.cid,'1688','水槽架','blocked-search')
        self.assertEqual(r['status'],'export_required');self.app.public_web.search.assert_not_called()
        r=self.preview(platform='1688',url='https://detail.1688.com/offer/123.html',idempotency_key='import')
        self.assertEqual(r['status'],'preview_ready')
    def test_url_scope_and_credential_rejection(self):
        for link in ['https://evil.example.com/p','https://item.jd.com.evil.example.com/p','https://item.jd.com/p?access_token=secret','https://127.0.0.1/p']:
            with self.subTest(link=link),self.assertRaises(ValueError):self.preview(url=link)
    def test_public_page_requires_same_platform_final_url_and_exact_product(self):
        self.app.public_web=Mock()
        self.app.public_web.read.return_value={'items':[{'status':'ready','url':'https://evil.example.com/p','title':'商品','source_sha256':'a'*64,'product_metadata':self.doc}]}
        r=self.preview(mode='public');self.assertEqual(r['status'],'needs_export')
        self.app.public_web.read.return_value={'items':[{'status':'ready','url':'https://item.jd.com/123.html','title':'安全验证','source_sha256':'a'*64}]}
        r=self.preview(mode='public',idempotency_key='challenge');self.assertEqual(r['error'],'sourcing_login_or_challenge')
        self.assertIsNone(r['draft'])
    def test_search_filters_foreign_links_and_preserves_lead_level(self):
        self.app.public_web=Mock()
        self.app.public_web.search.return_value={'status':'ready','groups':[{'items':[{'url':'https://item.jd.com/123.html','title':'架','summary':'页面待读'},{'url':'https://other.example.com/p','title':'外部'}]}]}
        r=self.s.search(self.cid,'jd','水槽架','search');self.assertEqual(len(r['items']),1)
        self.assertEqual(r['items'][0]['evidence_level'],'search_lead_not_read');self.assertEqual(r['items'][0]['snippet'],'页面待读')
    def test_all_channels_can_import_but_do_not_claim_authorized_api(self):
        d=self.s.channels(self.cid);self.assertEqual(len(d['items']),16)
        self.assertTrue(all(r['import_supported'] and not r['authorized_api_connected'] for r in d['items']))
        self.assertTrue({'taobao','jd','pdd','1688','yiwugo'}.issubset({r['id'] for r in d['items']}))
    def test_json_ld_ranges_multiple_products_and_article_compatibility(self):
        product={'@type':'Product','name':'架','image':['https://img.example.com/a.jpg'],
                 'offers':{'@type':'AggregateOffer','lowPrice':'3','highPrice':'30','priceCurrency':'CNY'}}
        html='<title>商品</title><main>结构和价格待核对</main><script type="application/ld+json">'+json.dumps(product)+'</script>'
        r=parse_page(html,'https://item.jd.com/123.html')['product_metadata']
        self.assertIsNone(r['offers'][0]['price']);self.assertEqual(r['offers'][0]['low_price'],'3')
        both=html_product('<script type="application/ld+json">'+json.dumps([product,product])+'</script>','https://item.jd.com/123.html')
        self.assertTrue(both['multiple_products'])
        with self.assertRaisesRegex(ValueError,'exact_product'):imported(json.dumps([product,product]),'json','https://item.jd.com/123.html')
        self.assertNotIn('product_metadata',parse_page('<title>文章</title><article>新闻正文</article>','https://example.com/news/1'))
    def test_exact_product_metadata_is_partial_and_never_fills_prices_from_recommendations(self):
        html='<title>合成架-京东</title><meta property="og:image" content="https://img.example.com/a.jpg"><main>推荐商品 ¥3；本款价格登录后可见</main>'
        r=parse_page(html,'https://item.jd.com/123.html')['product_metadata']
        self.assertTrue(r['needs_variant_confirmation']);self.assertEqual(r['offers'],[])
        self.assertNotIn('product_metadata',parse_page(html,'https://www.jd.com/brand/123.html'))
    def image_source(self):
        p=self.preview()['draft'];d=self.app.product_evidence.get(self.cid)
        return self.app.product_evidence.source_save(self.cid,'',p,0,d['dossier_sha256'],'image-source','合成测试')['entry']
    def test_source_image_fake_dns_resolves_to_public_address_before_pinned_tls_connection(self):
        source=self.image_source();raw=b'\x89PNG\r\n\x1a\n'+b'synthetic-image'
        with patch('public_web_transport.socket.getaddrinfo',return_value=[(2,1,6,'',('198.18.0.3',443))]),patch('public_web_transport.resolve_public_ipv4',return_value=['93.184.216.34']) as resolver,patch('catalog_media.PublicImageConnection') as connection,patch.object(self.app.creative,'probe',return_value={'width':1,'height':1,'duration_seconds':0,'has_audio':False}):
            response=connection.return_value.getresponse.return_value;response.status=200;response.read.return_value=raw
            r=self.app.product_evidence.media.image_capture(self.cid,source['id'],source['sha256'],0,'合成测试')
            resolver.assert_called_once();connection.assert_called_once_with('img.example.com','93.184.216.34')
            self.assertTrue(r['media_id'])
            latest=self.app.product_evidence.get(self.cid)['sources'][0]
            self.assertEqual(latest['images'][0]['media_id'],r['media_id'])
    def test_source_image_private_dns_remains_rejected_without_connection(self):
        source=self.image_source()
        with patch('public_web_transport.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('catalog_media.PublicImageConnection') as connection:
            with self.assertRaisesRegex(ValueError,'private_address'):self.app.product_evidence.media.image_capture(self.cid,source['id'],source['sha256'],0,'合成测试')
            connection.assert_not_called()

if __name__=='__main__':unittest.main()
