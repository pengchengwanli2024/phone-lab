"""Synthetic immutable article, redirect and translation binding checks."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'commerce'),str(ROOT/'crawlers')]
from article import allowed, body
from article_binding import bind,text_hash
from service import Commerce
from translation import validate_response


class ArticleWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=Commerce(self.temp.name)
        row=dict(id='1' * 24,source='fed',source_key='synthetic-fed',title='Synthetic policy statement',
                 url='https://www.federalreserve.gov/newsevents/pressreleases/synthetic.htm',published=1700000000,
                 category='macro',country=None,country_code=None,location=None,publisher_alert=None,collected_at='2026-01-01T00:00:00Z')
        with self.service.core.db() as db:self.service.intelligence.store.archive(db,row,time.time())
        self.item=self.service.intelligence.store.item('1' * 24)
        self.text='Synthetic cargo 25 USD. '*20
        self.service.articles.fetcher=lambda doc:dict(text=self.text,content_sha256=text_hash(self.text),
            source_url=doc['url'],captured_at='2026-01-01T00:00:00Z',routes=['urllib','native-curl'])

    def tearDown(self):self.temp.cleanup()
    def wait(self,doc,field='status',active=('queued','running')):
        end=time.monotonic()+8
        while doc[field] in active and time.monotonic()<end:
            time.sleep(.02);doc=self.service.articles.get(doc['id'])
        self.assertNotIn(doc[field],active)
        return doc
    def start(self):
        return self.wait(self.service.articles.start(self.item['id'],self.item['record_sha256'],'synthetic-capture'))

    def test_capture_idempotent_original_revision_and_immutable_translation(self):
        doc=self.start();self.assertEqual(doc['status'],'ready')
        self.assertEqual(doc['id'],self.service.articles.start(self.item['id'],self.item['record_sha256'],'synthetic-capture')['id'])
        frozen=deepcopy(doc['article'])
        def model(data):return validate_response(data,dict(translations=[{'id':i['id'],'zh':'合成货物 25 USD。'} for i in data['items']],provider='synthetic',model='synthetic',tools_enabled=False))
        with patch('translation.run_model',model):
            translated=self.wait(self.service.articles.translate(doc['id']),'translation_status',('running',))
        self.assertEqual(translated['translation_status'],'pending_review')
        self.assertEqual(translated['article']['text'],frozen['text'])
        self.assertEqual(translated['article']['translation']['original_sha256'],frozen['content_sha256'])
        bad=deepcopy(translated['article']['translation']);bad['original_sha256']='0'*64
        with self.assertRaises(ValueError):bind(frozen,bad)

    def test_changed_source_revision_rejects_translation_and_keeps_original(self):
        doc=self.start()
        with self.service.core.db() as db:self.service.intelligence.store.archive(db,dict(self.item,title='Changed synthetic title'),time.time())
        self.assertTrue(self.service.articles.get(doc['id'])['source_record_changed'])
        with self.assertRaisesRegex(ValueError,'intel_record_changed'):self.service.articles.translate(doc['id'])

    def test_long_translation_covers_all_chunks_with_model_receipts(self):
        self.text='Synthetic cargo 25 USD. '*900
        doc=self.start()
        calls=[]
        def model(data):
            calls.extend(data['items'])
            return validate_response(data,dict(translations=[{'id':i['id'],'zh':'中文 '+i['text']} for i in data['items']],provider='synthetic',model='synthetic',tools_enabled=False))
        with patch('translation.run_model',model):
            translated=self.wait(self.service.articles.translate(doc['id']),'translation_status',('running',))
        self.assertEqual(''.join(item['text'] for item in calls),self.text)
        self.assertEqual(len(translated['article']['translation']['model_receipts']),2)

    def test_interrupted_work_is_not_silently_replayed(self):
        doc=self.start();doc.update(translation_status='running');self.service.articles.save(doc)
        self.service.articles.recover()
        self.assertEqual(self.service.articles.get(doc['id'])['translation_status'],'interrupted')

    def test_hash_mismatch_is_failure(self):
        fetch=self.service.articles.fetcher
        self.service.articles.fetcher=lambda doc:dict(fetch(doc),content_sha256='0'*64)
        self.assertEqual(self.start()['status'],'failed')

    def test_public_publisher_allowlist_and_private_dns(self):
        good=self.item['url']
        for url in ['https://127.0.0.1/private','http://www.federalreserve.gov/newsevents/a','https://www.federalreserve.gov.evil.test/newsevents/a','https://www.federalreserve.gov:443/newsevents/a','https://user:pass@www.federalreserve.gov/newsevents/a']:
            with self.assertRaises(ValueError):allowed('fed',url,resolve=False)
        with patch('article.environment',return_value={}), patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaisesRegex(ValueError,'address_rejected'):allowed('fed',good)

    def test_body_excludes_active_content_and_never_truncates(self):
        html=('<html><div id="article"><script>DO NOT EXECUTE</script><p>'+('Synthetic cargo 25 USD. '*20)+'</p></div></html>').encode()
        text,locator=body('fed',html)
        self.assertNotIn('EXECUTE',text);self.assertEqual(locator,'#article')
        with self.assertRaisesRegex(ValueError,'text_too_large'):body('fed',b'<div id="article"><p>'+b'x'*30001+b'</p></div>')


if __name__=='__main__':unittest.main()
