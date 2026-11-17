"""Public retrieval contracts; synthetic upstream data, no ambient credentials."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from email.message import Message
from unittest.mock import patch
import io
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from public_web import PublicWeb, public_url, time_window, parse_page

NOW=datetime(2026,11,16,1,0,tzinfo=timezone.utc).timestamp()


class PublicRetrieval(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):self.tmp.cleanup()

    def service(self,runner=None,reader=None):
        def upstream(action,query,cancelled):
            return {'query':query,'results':[{'title':'Indonesia shipping update','url':'https://example.com/news/1','description':'Public source summary','source':'example.com','engine':'duckduckgo'},
                {'title':'Unsafe','url':'http://127.0.0.1/private','description':'must not survive'}]}
        return PublicWeb(self.tmp.name,runner=runner or upstream,reader=reader,clock=lambda:NOW)

    def test_today_uses_beijing_calendar_boundaries_not_rolling_24_hours(self):
        value=time_window('today',NOW)
        self.assertEqual(value['from_utc'],'2026-11-15T16:00:00+00:00')
        self.assertEqual(value['to_utc'],'2026-11-16T16:00:00+00:00')
        self.assertEqual(value['date_beijing'],'2026-11-16')
        self.assertEqual(time_window('24h',NOW)['from_utc'],'2026-11-15T01:00:00+00:00')

    def test_regions_are_separate_queries_with_explicit_unconfirmed_publication(self):
        service=self.service();result=service.search('东南亚、俄罗斯以及中东今日要闻')
        self.assertEqual([g['region']for g in result['groups']],['southeast_asia','russia','middle_east'])
        self.assertEqual(result['window']['period'],'today')
        self.assertIn('东南亚',result['groups'][0]['query'])
        self.assertNotIn('俄罗斯',result['groups'][0]['query'])
        self.assertEqual(len(result['groups'][0]['items']),1)
        item=result['groups'][0]['items'][0]
        self.assertEqual(item['publication_status'],'unconfirmed')
        self.assertFalse(item['independently_verified'])
        self.assertEqual(len(item['source_sha256']),64)

    def test_region_failure_keeps_other_results_and_cache_is_not_fresh_retrieval(self):
        def upstream(action,query,cancelled):
            if '俄罗斯'in query:raise ValueError('web_provider_timeout')
            return {'results':[{'title':'Public','url':'https://example.com/a','description':'Source'}]}
        service=self.service(upstream);value=service.search('今日要闻',regions=['southeast_asia','russia'])
        self.assertEqual(value['status'],'partial')
        self.assertEqual(value['groups'][1]['status'],'failed')
        self.assertEqual(value['groups'][1]['error'],'web_provider_timeout')
        cached=service.search('今日要闻',regions=['southeast_asia','russia'])
        self.assertTrue(cached['cached']);self.assertEqual(cached['retrieved_at'],NOW)

    def test_public_reader_preserves_one_failed_source_and_exact_date_window(self):
        def reader(url,cancelled):
            if url.endswith('bad'):raise ValueError('web_http_403')
            return parse_page('<html><head><title>Public headline</title><meta property="article:published_time" content="2026-11-16T00:30:00Z"></head><body><article><p>Public source body.</p></article><script>PRIVATE_SENTINEL</script></body></html>',url)
        value=self.service(reader=reader).read(['https://example.com/a','https://example.com/bad'],period='today')
        self.assertEqual(value['status'],'partial');self.assertEqual(value['items'][0]['publication_status'],'within_window')
        self.assertEqual(value['items'][0]['published_beijing'],'2026-11-16 08:30:00 +08:00')
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(value));self.assertEqual(value['items'][1]['status'],'failed')

    def test_old_article_cannot_become_todays_news_from_retrieval_time(self):
        value=self.service(reader=lambda url,cancelled:parse_page('<title>Old</title><meta name="pubdate" content="2026-11-10T10:00:00Z"><article>Historical source</article>',url)).read(['https://example.com/2026/11/16/a'],period='today')
        self.assertEqual(value['items'][0]['publication_status'],'outside_window')

    def test_private_and_credential_urls_are_rejected_before_reader(self):
        for url in ['file:///tmp/a','http://localhost/a','https://127.0.0.1/a','https://[::1]/a','https://169.254.169.254/a','https://user:pass@example.com/a','https://host.local/a','https://example.com:8443/a','https://2130706433/a','https://0x7f000001/a']:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):public_url(url)
        self.assertEqual(public_url('https://example.com/news?q=public'),'https://example.com/news?q=public')

    def test_query_limits_and_unknown_regions_do_not_start_network_work(self):
        service=self.service()
        for args in [{'query':'x'*241},{'query':'abc','regions':['made_up']},{'query':'abc','limit':100},{'query':'abc','period':'future'}]:
            with self.assertRaises(ValueError):service.search(**args)

    def test_regional_query_keeps_the_users_actual_subject(self):
        value=self.service().search('请查询东南亚和中东的海运运价新闻',regions=['southeast_asia','middle_east'])
        self.assertIn('海运运价',value['groups'][0]['query'])
        self.assertNotIn('中东',value['groups'][0]['query'])

    def test_jsonld_publication_is_read_as_data_without_script_execution(self):
        value=parse_page('<title>Headline</title><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-11-16T02:00:00+08:00"}</script><article>Public body</article>','https://example.com/a')
        self.assertEqual(value['published_at'],1794765600)
        self.assertEqual(value['text'],'Public body')

    def test_region_aliases_find_existing_local_country_records(self):
        from intel_store import IntelligenceStore
        rows=[dict(id='1',title='Indonesia earthquake',country=None,country_code=None,source='usgs',category='earthquake',url='https://example.com/1',published=NOW,is_viewed=False,is_bookmarked=False),
              dict(id='2',title='Flood in Iran',country='Iran',country_code='IRN',source='gdacs',category='disaster',url='https://example.com/2',published=NOW,is_viewed=False,is_bookmarked=False)]
        self.assertEqual([r['id']for r in IntelligenceStore.matches(rows,IntelligenceStore.filters(query='东南亚'))],['1'])
        self.assertEqual([r['id']for r in IntelligenceStore.matches(rows,IntelligenceStore.filters(query='中东'))],['2'])

    def test_cancelled_search_is_not_cached_as_success(self):
        from public_web import RetrievalCancelled
        service=self.service()
        with self.assertRaises(RetrievalCancelled):service.search('public query',cancelled=lambda:True)
        self.assertFalse(service.search('public query')['cached'])

    def test_future_publication_is_not_current_news(self):
        value=self.service(reader=lambda url,cancelled:parse_page('<meta name="pubdate" content="2026-11-16T20:30:00+08:00"><article>Scheduled</article>',url)).read(['https://example.com/a'],period='today')
        self.assertEqual(value['items'][0]['publication_status'],'future_timestamp')

    def test_search_invalid_response_is_one_failed_group_not_a_crash(self):
        value=self.service(runner=lambda *args:{'results':[None,{'url':'https://example.com/a','title':'Valid'}]}).search('public query')
        self.assertEqual(value['groups'][0]['items'][0]['title'],'Valid')

    def test_mixed_private_dns_cannot_fall_back_to_public_resolver(self):
        from unittest.mock import patch
        from public_web_transport import addresses
        with patch('public_web_transport.socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('127.0.0.1',443))]),patch('public_web_transport.resolve_public_ipv4')as fallback:
            with self.assertRaisesRegex(ValueError,'private_address'):addresses('example.com')
            fallback.assert_not_called()

    def test_article_body_div_is_preferred_over_header_and_subscription_forms(self):
        page=parse_page('<title>Live report</title><div>Subscribe navigation</div><div id="live-page-body"><p>Actual source report</p></div><div>Footer</div>','https://example.com/a')
        self.assertEqual(page['text'],'Actual source report')

    def test_index_returns_bounded_real_article_links_without_reading_or_executing_them(self):
        from public_web import result_urls
        links=''.join('<a href="/news/20261116/article-'+str(i)+'">Actual article headline '+str(i)+'</a>'for i in range(15))
        html='<title>News index</title><nav><a href="/private-nav">Long navigation title</a></nav><main>'+links+'<a href="http://127.0.0.1/private">Private address rejected</a><a href="javascript:alert(1)">Script must never execute</a></main>'
        page=parse_page(html,'https://example.com/news')
        self.assertEqual(len(page['article_candidates']),8)
        self.assertEqual(page['article_candidates'][0]['url'],'https://example.com/news/20261116/article-0')
        self.assertNotIn('https://example.com/private-nav',result_urls(page))
        self.assertFalse(any('127.0.0.1'in url for url in result_urls(page)))
        self.assertTrue(all(row['content_status']=='link_not_read'for row in page['article_candidates']))

    def test_tag_index_is_not_an_article_even_if_cms_sets_article_metadata(self):
        page=parse_page('<meta property="og:type" content="article"><article>Rolling headlines</article><a href="/2026/story-1.html">Original detailed article</a>',
                        'https://example.com/tags-middle-east/')
        self.assertEqual(page['page_kind'],'index_or_page')
        self.assertEqual(len(page['article_candidates']),1)

    def test_explicit_refresh_bypasses_cache_without_hiding_partial_results(self):
        calls=[]
        def upstream(*args):calls.append(1);return {'results':[{'title':'Public','url':'https://example.com/a'}]}
        service=self.service(runner=upstream);service.search('public query');self.assertTrue(service.search('public query')['cached'])
        self.assertFalse(service.search('public query',refresh=True)['cached']);self.assertEqual(len(calls),2)

    def test_shared_http_timeouts_cover_bounded_public_tools_only(self):
        from unittest.mock import patch
        import io
        from runtime import request
        for name,timeout in [('commerce_web_search',35),('commerce_web_read',95),('commerce_status',15)]:
            with patch('runtime.token',return_value='synthetic-only'),patch('runtime.urllib.request.urlopen',return_value=io.BytesIO(b'{}'))as opened:
                request(name,{});self.assertEqual(opened.call_args.kwargs['timeout'],timeout)

    def read_response(self,body,content_type='application/json',url='https://example.com/public-data'):
        from public_web_transport import fetch_page
        headers=Message();headers['Content-Type']=content_type
        class Response:
            status=200
            def __init__(self):self.headers=headers;self.body=io.BytesIO(body)
            def getheader(self,name):return headers.get(name)
            def read1(self,size):return self.body.read1(size)
        with patch('public_web_transport.addresses',return_value=['93.184.216.34']),patch('public_web_transport.PublicConnection')as connection:
            connection.return_value.getresponse.return_value=Response()
            return fetch_page(url,lambda:False)

    def test_official_json_facts_survive_long_excerpt_and_are_bound_into_source_hash(self):
        from commerce.qa.test_public_data_facts import event,URL
        from public_web import digest
        data=event();data['properties']['products']={'large':['history '*800]}
        page=self.read_response(json.dumps(data).encode(),url=URL)
        self.assertTrue(page['text_truncated'])
        self.assertEqual(page['structured_facts']['items'][0]['depth_km'],5.0)
        value=self.service(reader=lambda *args:page).read([URL])
        item=value['items'][0];original=item.pop('source_sha256')
        self.assertEqual(digest(item),original)
        item['structured_facts']['items'][0]['magnitude']=9
        self.assertNotEqual(digest(item),original)
        self.assertIsNone(item['published_at'])
        self.assertEqual(item['retrieved_beijing'],'2026-11-16 09:00:00 +08:00')

    def test_public_json_data_is_read_without_inventing_article_publication(self):
        data={'type':'Feature','properties':{'mag':2,'time':1794828776195,'status':'automatic'},'geometry':{'coordinates':[-154.237,61.328,5]}}
        page=self.read_response(json.dumps(data).encode(),'application/geo+json; charset=utf-8')
        self.assertEqual(json.loads(page['text']),data)
        self.assertIsNone(page['published_at'])
        result=self.service(reader=lambda *_:page).read(['https://example.com/public-data'])
        self.assertEqual(result['items'][0]['content_status'],'json_data')
        self.assertEqual(result['items'][0]['publication_status'],'unconfirmed')
        self.assertEqual(result['items'][0]['retrieved_beijing'],'2026-11-16 09:00:00 +08:00')
        self.assertEqual(result['retrieved_beijing'],'2026-11-16 09:00:00 +08:00')

    def test_invalid_json_or_scalar_is_not_reported_as_a_read_page(self):
        for raw in [b'{"cut":',b'null',b'"not a document"',b'{"not_finite":NaN}']:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError,'web_page_invalid_json'):self.read_response(raw)

    def test_long_public_data_is_explicitly_marked_as_a_partial_excerpt(self):
        page=self.read_response(json.dumps({'rows':['public data']*1000}).encode())
        result=self.service(reader=lambda *_:page).read(['https://example.com/public-data'])
        item=result['items'][0]
        self.assertTrue(item['text_truncated'])
        self.assertLessEqual(len(item['text']),3200)

    def test_large_nested_products_do_not_hide_top_level_event_coordinates(self):
        data={'type':'Feature','properties':{'mag':2,'products':{'origin':[{'text':'detail'*3000}]}},'geometry':{'type':'Point','coordinates':[-154.237,61.328,5]}}
        page=self.read_response(json.dumps(data).encode(),'application/geo+json')
        item=self.service(reader=lambda *_:page).read(['https://example.com/public-data'])['items'][0]
        self.assertIn('coordinates',item['text'])
        self.assertIn('-154.237',item['text'])
        self.assertIn('"/properties/mag": 2',item['text'])
        self.assertTrue(item['text_truncated'])

    def test_binary_types_remain_unsupported_by_public_reader(self):
        with self.assertRaisesRegex(ValueError,'web_page_format_unsupported'):self.read_response(b'not a page','application/octet-stream')


if __name__=='__main__':unittest.main()
