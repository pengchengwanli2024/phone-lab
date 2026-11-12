"""Synthetic evidence contract checks; no account, phone or network access."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import package as p


def fixture(base):
    folder = base / 'evidence'
    folder.mkdir()
    (folder / 'synthetic.txt').write_text('Synthetic source excerpt. Not real data.')
    at = '2026-11-11T05:00:00+00:00'
    r = dict(record_id='synthetic-01', category='commerce', title_zh='合成阅读样本', summary_zh='只用于验收的合成观察。',
        source=dict(platform='tiktok', url='https://example.org/synthetic/1', kind='permalink', access='observed'),
        published=dict(display='合成时间', iso=at, precision='exact'), captured_at=at,
        original=dict(text='Synthetic source excerpt.', language='en', method='manual_excerpt', locator='合成文本第一行', evidence_id='asset-01'),
        translation=dict(zh='合成来源摘录。', method='manual', review_status='reviewed', original_sha256=p.digest('Synthetic source excerpt.')),
        metrics=[], verification='observed_not_verified', limitations=['合成资料，不可用于经营。'],
        ranking=dict(selected=True, rank=1, reason='合成 TOP 验收样本。', rule_version='manual-v1', basis_sha256=p.digest('synthetic basis')),
        next_action='无外部操作。', evidence_ids=['asset-01'])
    r['content_sha256'] = p.content_hash(r)
    r['record_sha256'] = p.record_hash(r)
    return dict(schema=p.VERSION, batch_id='synthetic-batch', created_at=at,
        scope=dict(categories=['commerce','ai','news'], top_per_category=3, queries=['synthetic'], ranking_version='manual-v1', limitations='合成验收资料。'),
        records=[r], record_versions=[], assets=[dict(evidence_id='asset-01', path='evidence/synthetic.txt', sha256=hashlib.sha256((folder/'synthetic.txt').read_bytes()).hexdigest(), media_type='text/plain', captured_at=at, locator='合成资料')],
        attempts=[dict(id='attempt-01',platform='tiktok',query='synthetic',started_at=at,ended_at=at,status='success',reason='合成尝试',evidence_ids=['asset-01'])],
        events=[dict(id='event-01',at=at,type='observed',record_id=r['record_id'],content_sha256=r['content_sha256'],record_sha256=r['record_sha256'],result='合成观察',evidence_ids=['asset-01'])])


class Contract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.b=fixture(self.base)
    def tearDown(self):self.temp.cleanup()
    def test_portable_package_and_stream_roundtrip(self):
        out=self.base/'export';p.export(self.b,self.base,out);p.validate(json.loads((out/'bundle.json').read_text()),out)
        rows=[json.loads(line) for line in (out/'exchange.jsonl').read_text().splitlines()]
        rebuilt={'schema':p.VERSION,'batch_id':rows[0]['batch_id'],**rows[0]['data']}
        for group in ('records','record_versions','assets','attempts','events'):rebuilt[group]=[r['data'] for r in rows if r['kind']==group]
        self.assertEqual(rebuilt,self.b)
    def test_tampered_evidence_rejected(self):
        (self.base/'evidence/synthetic.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'asset_hash_mismatch'):p.validate(self.b,self.base)
    def test_traversal_rejected(self):
        self.b['assets'][0]['path']='evidence/../../outside.txt'
        with self.assertRaisesRegex(ValueError,'unsafe_asset_path'):p.validate(self.b,self.base)
    def test_external_symlink_rejected(self):
        (self.base/'evidence/link').symlink_to('/etc/hosts');self.b['assets'][0]['path']='evidence/link'
        with self.assertRaisesRegex(ValueError,'asset_outside_package'):p.validate(self.b,self.base)
    def test_missing_permalink_cannot_enter_top(self):
        r=self.b['records'][0];r['source']['kind']='profile';r['content_sha256']=p.content_hash(r);r['record_sha256']=p.record_hash(r)
        with self.assertRaisesRegex(ValueError,'top_requires_observed'):p.validate(self.b,self.base)
    def test_metric_changes_preserve_content_and_bind_new_snapshot(self):
        old=copy.deepcopy(self.b['records'][0]);r=self.b['records'][0]
        r['metrics']=[dict(name='likes',display='1万',value=10000,approximate=True,observed_at=r['captured_at'],evidence_id='asset-01')]
        self.assertEqual(p.content_hash(r),old['content_sha256']);self.assertNotEqual(p.record_hash(r),old['record_sha256'])
        r['record_sha256']=p.record_hash(r);self.b['record_versions']=[old];p.validate(self.b,self.base)
        self.b['record_versions']=[]
        with self.assertRaisesRegex(ValueError,'event_version_mismatch'):p.validate(self.b,self.base)
    def test_changed_original_rejects_stale_translation(self):
        r=self.b['records'][0];r['original']['text']='different';r['content_sha256']=p.content_hash(r);r['record_sha256']=p.record_hash(r)
        with self.assertRaisesRegex(ValueError,'stale_translation'):p.validate(self.b,self.base)
    def test_timezone_and_extra_fields_rejected(self):
        self.b['created_at']='2026-11-11T05:00:00'
        with self.assertRaisesRegex(ValueError,'timezone_required'):p.validate(self.b,self.base)
        self.b['created_at']='2026-11-11T05:00:00Z';self.b['unexpected']='unsafe'
        with self.assertRaisesRegex(ValueError,'unknown_field'):p.validate(self.b,self.base)
    def test_script_and_formula_quarantined(self):
        r=self.b['records'][0];r['title_zh']='=1+1';r['summary_zh']='</script><script>window.injected=true</script>';r['record_sha256']=p.record_hash(r)
        self.b['events'][0]['record_sha256']=r['record_sha256']
        out=self.base/'output';p.export(self.b,self.base,out)
        self.assertNotIn('</script><script>window.injected', (out/'reader.html').read_text())
        self.assertIn("'=1+1",(out/'index.csv').read_text())


if __name__=='__main__':unittest.main()
