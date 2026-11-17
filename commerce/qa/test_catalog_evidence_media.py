"""Real temporary-domain evidence images remain references through catalog reads."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from service import Commerce
from organization_candidates import create_candidate
from product_evidence import SOURCE_FIELDS
from research import canonical, digest
from test_live_connections import batch
import catalog_media

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII=')
# A real, ffprobe-readable 1x1 WebP, not a RIFF prefix pretending to be an image.
WEBP = base64.b64decode('UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEAAUAmJaQAA3AA/v89WAAAAA==')


class CatalogEvidenceMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.app = Commerce(self.tmp.name); self.sequence = 0
        self.app.ozon_accounts.configure(dict(ozon_client_id='111111', ozon_api_key='synthetic-evidence-account', store_label='Synthetic shop'))
        config = self.app.live.config()
        self.app.live._publish(config['connection_id'], 'stock', batch('stock'), config, False)
        self.anchor = self.app.organization.import_inventory()['cases'][0]['id']
        self.cid = self.candidate('a')

    def tearDown(self):
        self.app.catalog_sync.stop(); self.app.agent_runtime.stop(); self.app.autonomy.stop(); self.tmp.cleanup()

    def candidate(self, suffix):
        context = self.app.organization.exchange.context(self.anchor)
        return create_candidate(self.root/'commerce.sqlite', context, key='test-evidence-'+suffix,
            name='Synthetic research '+suffix, source_ref='https://example.com/product/'+suffix)['case']['id']

    def source(self, *, cid=None, kind='competitor', role='original', raw=WEBP, count=1, image_url=None):
        cid = cid or self.cid; self.sequence += 1; key = str(self.sequence)
        dossier = self.app.product_evidence
        payload = dict(kind=kind, platform='other', label='Synthetic '+kind, url='https://example.com/source/'+key,
            model='', variant='', observed_at=datetime.now(timezone.utc).isoformat(), valid_until='',
            review_state='unreviewed', verification_note='', rights_status='reference_only', rights_evidence='',
            notes='', quote_ids=[], images=[], metrics={}, archived=False)
        source = dossier.source_save(cid, '', payload, 0, dossier.get(cid)['dossier_sha256'], 'source-'+key, 'synthetic')['entry']
        for index in range(count):
            begin = dossier.media.upload_begin(cid, source['id'], source['sha256'], 'source.webp' if raw == WEBP else 'source.png',
                len(raw), hashlib.sha256(raw).hexdigest(), image_url or 'https://example.com/image/'+key+'/'+str(index)+'.jpg', role, 'synthetic')
            dossier.media.upload_chunk(cid, begin['upload_id'], 0, base64.b64encode(raw).decode())
            finish = dossier.media.upload_finish(cid, begin['upload_id'])
            source = dossier.source_get(cid, source['id'], finish['entry_revision'])['entry']
        return source

    def update(self, source, **changes):
        dossier = self.app.product_evidence; payload = {k: source[k] for k in SOURCE_FIELDS}; payload.update(changes)
        self.sequence += 1
        return dossier.source_save(self.cid, source['id'], payload, source['revision'], dossier.get(self.cid)['dossier_sha256'],
            'update-'+str(self.sequence), 'synthetic')['entry']

    def detail(self): return self.app.invoke('commerce_catalog_get', {'case_id': self.cid}, 'test')

    def read(self, detail, index=0, image_id=True):
        args = dict(case_id=self.cid, expected_source_sha256=detail['source_sha256'], index=index)
        if image_id: args['image_id'] = detail['images'][index]['id']
        return self.app.invoke('commerce_catalog_image', args, 'test')

    def test_candidate_get_projects_registered_original_with_exact_reference_binding(self):
        before = self.detail(); source = self.source(); detail = self.detail()
        self.assertEqual(detail['source_sha256'], before['source_sha256'])
        self.assertEqual(detail['fields'], before['fields']); self.assertEqual(detail['source_facts'], before['source_facts'])
        self.assertEqual(detail['kind'], 'candidate'); self.assertEqual(len(detail['images']), 1)
        ref = detail['images'][0]
        for key, expected in {'origin':'product_evidence', 'case_id':self.cid, 'entry_id':source['id'], 'entry_sha256':source['sha256'],
                'entry_revision':source['revision'], 'image_index':0, 'media_id':source['images'][0]['media_id'],
                'source_kind':'competitor', 'role':'original', 'sha256':hashlib.sha256(WEBP).hexdigest(), 'width':1, 'height':1}.items():
            self.assertEqual(ref[key], expected, key)
        self.assertTrue(ref['reference_only']); self.assertFalse(ref['publication_approved'])
        self.assertFalse(ref['product_fact']); self.assertFalse(ref['use_for_image_generation'])
        self.assertEqual(ref['id'], digest(canonical({k:v for k,v in ref.items() if k != 'id'})))

    def test_real_webp_and_original_png_are_read_from_registered_bytes_without_network_or_cache(self):
        self.source(); self.source(kind='supplier', raw=PNG)
        detail = self.detail(); seen = set()
        with patch.object(catalog_media, 'fetch', side_effect=AssertionError('No remote read')), patch.object(self.app.product_evidence.media, 'image_capture', side_effect=AssertionError('No capture')):
            for index, ref in enumerate(detail['images']):
                value = self.read(detail, index); raw = base64.b64decode(value['content_base64'])
                seen.add(value['mime']); self.assertEqual(raw, PNG if value['mime']=='image/png' else WEBP)
                self.assertEqual(value['sha256'], ref['sha256']); self.assertTrue(value['reference_only'])
        self.assertEqual(seen, {'image/webp', 'image/png'}); self.assertFalse((self.root/'catalog-images').exists())

    def test_old_image_id_rejected_after_source_note_revision_while_workspace_sha_stays_equal(self):
        source = self.source(); old = self.detail(); old_id = old['images'][0]['id']
        self.update(source, notes='New source revision'); current = self.detail()
        self.assertEqual(old['source_sha256'], current['source_sha256']); self.assertNotEqual(old_id, current['images'][0]['id'])
        with self.assertRaisesRegex(ValueError, 'catalog_image_not_found'): self.read(old)
        self.assertEqual(base64.b64decode(self.read(current)['content_base64']), WEBP)

    def test_evidence_reference_requires_image_id_but_existing_product_images_keep_index_reads(self):
        self.source(); detail = self.detail()
        with self.assertRaisesRegex(ValueError, 'catalog_evidence_image_id_required'): self.read(detail, image_id=False)
        legacy = self.app.catalog.get(self.anchor); project = self.app.catalog.creative(self.anchor, legacy['source_sha256'], 'legacy-project')
        file = self.root/'legacy.png'; file.write_bytes(PNG)
        self.app.creative.register(project['id'], 'product_image', file, dict(source_ref='synthetic:legacy', media=dict(width=1,height=1)))
        legacy = self.app.catalog.get(self.anchor)
        value = self.app.catalog.image(self.anchor, legacy['source_sha256'], 0)
        self.assertEqual(base64.b64decode(value['content_base64']), PNG)

    def test_cross_case_reference_and_forged_entry_index_media_or_sha_fail_closed(self):
        self.source(); detail = self.detail(); ref = detail['images'][0]; other = self.candidate('b'); other_detail = self.app.catalog.get(other)
        with self.assertRaisesRegex(ValueError, 'catalog_image_not_found'):
            self.app.catalog.image(other, other_detail['source_sha256'], 0, ref['id'])
        for field, value in [('case_id',other), ('entry_id','ev_'+'a'*32), ('entry_sha256','0'*64), ('entry_revision',999),
                ('image_index',1), ('media_id','peimg_'+'a'*32), ('sha256','0'*64), ('raw_sha256','0'*64), ('role','generated'),
                ('source_kind','supplier'), ('width',999), ('url','https://example.com/another.png')]:
            forged={**ref,field:value};forged['id']=digest(canonical({k:v for k,v in forged.items() if k!='id'}))
            with self.subTest(field=field), self.assertRaises(ValueError):
                catalog_media.preview(self.app, forged, detail['source_sha256'])

    def test_source_archive_or_original_role_removal_rejects_old_ids_without_fetch(self):
        source = self.source(); old = self.detail(); self.update(source, archived=True)
        self.assertEqual(self.detail()['images'], [])
        with patch.object(catalog_media, 'fetch', side_effect=AssertionError('No fallback')):
            with self.assertRaisesRegex(ValueError,'catalog_image_not_found'): self.read(old)

    def test_local_file_missing_or_tampered_never_falls_back_to_public_url(self):
        source = self.source(); detail = self.detail()
        file, _ = self.app.product_evidence.media.asset(self.cid, source['id'], source['images'][0]['media_id'])
        for change in ('tamper','missing'):
            if change=='tamper': file.write_bytes(WEBP+b'changed')
            else: file.unlink()
            with self.subTest(change=change), patch.object(catalog_media,'fetch',side_effect=AssertionError('No fallback')):
                with self.assertRaisesRegex(ValueError,'evidence_image_changed'): self.read(detail)

    def test_projection_ignores_generated_link_only_archived_and_wrong_registry_scope(self):
        self.source(role='generated'); self.source(role='document'); archived = self.source(kind='supplier')
        self.update(archived, archived=True)
        source = self.source(kind='supplier'); doc_id = source['images'][0]['media_id']
        with self.app.core.db() as db:
            raw = json.loads(db.execute('SELECT document FROM product_evidence_images WHERE id=?',(doc_id,)).fetchone()[0])
            raw['case_id'] = self.anchor; raw['document_sha256'] = digest(canonical({k:v for k,v in raw.items() if k!='document_sha256'}))
            db.execute('UPDATE product_evidence_images SET document=? WHERE id=?',(canonical(raw),doc_id))
        self.assertEqual(self.detail()['images'], [])

    def test_bounded_twenty_images_preserve_existing_product_image_priority(self):
        detail = self.detail(); project = self.app.catalog.creative(self.cid, detail['source_sha256'], 'own-original')
        file = self.root/'product.png'; file.write_bytes(PNG)
        own = self.app.creative.register(project['id'], 'product_image', file, dict(source_ref='synthetic:product'))
        self.source(count=12); self.source(kind='supplier',count=12)
        detail = self.detail(); self.assertEqual(len(detail['images']),20)
        self.assertEqual(detail['images'][0]['asset_id'],own['id']); self.assertEqual(detail['images'][0]['origin'],'product_image')
        self.assertEqual(sum(r['origin']=='product_evidence' for r in detail['images']),19)

    def test_current_source_is_rechecked_if_it_changes_during_asset_read(self):
        source = self.source(); detail = self.detail(); original = self.app.product_evidence.media.asset; once = [True]
        def race(*args,**kwargs):
            if once[0]: once[0]=False; self.update(source, notes='Changed during preview')
            return original(*args,**kwargs)
        with patch.object(self.app.product_evidence.media,'asset',side_effect=race):
            with self.assertRaisesRegex(ValueError,'evidence_source_changed'): self.read(detail)

    def test_get_list_and_preview_do_not_change_business_rows_source_hash_or_approval(self):
        self.source(); detail = self.detail()
        tables=('org_cases','org_artifacts','form_drafts','tasks','creative_projects','creative_assets','product_evidence_versions','product_evidence_images','product_evidence_reviews')
        def state():
            with self.app.core.db() as db:return {t:list(db.execute('SELECT * FROM '+t+' ORDER BY rowid')) for t in tables}
        before=state(); self.detail(); self.app.catalog.listing(); self.read(detail); workspace=self.app.product_workspace.get(self.cid)
        self.assertEqual(state(),before); self.assertEqual(workspace['source_sha256'],detail['source_sha256'])
        self.assertFalse(workspace['facts_independently_verified']); self.assertFalse(workspace['external_execution_allowed'])

    def test_reference_only_import_rejection_does_not_create_assets_or_fact_records(self):
        self.source(); detail = self.detail(); project = self.app.catalog.creative(self.cid,detail['source_sha256'],'import-target')
        def state():
            with self.app.core.db() as db:return {t:list(db.execute('SELECT * FROM '+t+' ORDER BY rowid')) for t in ('creative_projects','creative_assets','org_artifacts','product_evidence_versions','product_evidence_reviews')}
        before=state()
        for kind in ('product_image','reference_image'):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError,'catalog_evidence_reference_only'):
                self.app.catalog.image_import(self.cid,project['id'],detail['source_sha256'],0,kind,detail['images'][0]['id'])
        self.assertEqual(state(),before)

    def test_evidence_public_projection_does_not_echo_private_path_in_origin_query(self):
        private_path='/Users/synthetic-only/private-reference.png'
        self.source(image_url='https://example.com/image.png?location='+private_path)
        detail=self.detail();self.assertNotIn(private_path,json.dumps(detail['images']))
        self.assertIsNone(detail['images'][0]['url'])
        value=self.read(detail);self.assertNotIn(private_path,json.dumps(value))
        self.assertEqual(base64.b64decode(value['content_base64']),WEBP)

    def test_evidence_media_does_not_change_existing_listing_payload_or_preview_hash(self):
        target=dict(case_id=self.cid,platform='ozon',store_ref='synthetic-store',market='RU')
        before=self.app.invoke('commerce_listing_get',target,'test')
        source=self.source();self.update(source,notes='Reference revision only')
        after=self.app.invoke('commerce_listing_get',target,'test')
        self.assertEqual(after['preview_sha256'],before['preview_sha256'])
        self.assertEqual(after['payload'],before['payload'])
        self.assertEqual(after['source_sha256'],before['source_sha256'])
        self.assertEqual(after['payload']['fields']['image_refs'],[])

    def test_real_registered_jpeg_keeps_existing_mime_and_bytes(self):
        png=self.root/'jpeg-fixture-input.png';jpg=self.root/'jpeg-fixture-output.jpg';png.write_bytes(PNG)
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(png),'-frames:v','1',str(jpg)],check=True,capture_output=True)
        raw=jpg.read_bytes();self.assertTrue(raw.startswith(b'\xff\xd8\xff'))
        self.source(raw=raw);value=self.read(self.detail())
        self.assertEqual(value['mime'],'image/jpeg');self.assertEqual(base64.b64decode(value['content_base64']),raw)


if __name__ == '__main__': unittest.main()
