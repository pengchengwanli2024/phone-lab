import tempfile
import unittest
from public_web import parse_page, PublicWeb


class PublicPageBodyQuality(unittest.TestCase):
    def test_application_shell_and_empty_page_do_not_count_as_read_article(self):
        shells=['<title>Latest Earthquakes</title><main>The Latest Earthquakes application supports most recent browsers, <a>view supported browsers</a>.</main>',
                '<title>News</title><main>Please enable JavaScript to view this page.</main>',
                '<title>News</title><div id="root"></div><script>renderArticle()</script>']
        with tempfile.TemporaryDirectory() as state:
            for html in shells:
                with self.subTest(html=html):
                    service=PublicWeb(state,reader=lambda url,cancelled:parse_page(html,url))
                    result=service.read(['https://example.com/news'])
                    self.assertEqual(result['status'],'failed')
                    self.assertEqual(result['items'][0]['error'],'web_page_body_unavailable')

    def test_short_meaningful_alerts_remain_readable(self):
        result=parse_page('<title>Earthquake alert</title><article>M5.1 earthquake near the coast. Updated 09:00 UTC.</article>','https://example.com/news')
        self.assertIn('M5.1',result['text'])


if __name__=='__main__':unittest.main()
