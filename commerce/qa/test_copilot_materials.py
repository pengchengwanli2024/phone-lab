"""Selected local material bytes and scoped business references; no real services."""
import base64
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
import sys
import struct
import tempfile
import time
import unittest
import zlib
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class Materials(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('copilot.materials'), 'local materials module is missing')
        from copilot.materials import CopilotMaterials
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)
        self.materials = CopilotMaterials(self.app.copilot)
        self.thread = self.open()

    def tearDown(self):
        if hasattr(self, 'app'):
            self.app.agent_runtime.stop()
            self.tmp.cleanup()

    def open(self, context=None, key='open'):
        return self.app.copilot.open(context or {'module':'orders','demo':True,'platform':'ozon','store_id':'ozon-demo','market':'RU','entity':{'kind':'order','id':'SIM-1001'}}, key)

    def upload(self, text=b'local synthetic reference', **overrides):
        return self.materials.upload(**{**dict(thread_id=self.thread['id'], context_sha256=self.thread['context_sha256'], filename='notes.txt', mime_type='text/plain', content_base64=base64.b64encode(text).decode(), idempotency_key='upload'), **overrides})

    def resolve(self, ids, thread=None):
        with self.app.core.atomic() as db:
            return self.materials.resolve_for_send(db, self.app.copilot._thread(db, (thread or self.thread)['id']), ids)

    def reference(self, **overrides):
        return self.materials.reference(**{**dict(thread_id=self.thread['id'], context_sha256=self.thread['context_sha256'], kind='order', object_id='SIM-1001', idempotency_key='reference'), **overrides})

    def test_upload_is_persistent_local_only_before_explicit_send(self):
        with patch('agent_runtime.model.invoke', side_effect=AssertionError('model must not run')):
            item = self.upload()
            self.assertEqual(self.upload()['id'], item['id'])
            self.assertEqual(self.materials.get(self.thread['id'], item['id'])['text'], 'local synthetic reference')
            from copilot.materials import CopilotMaterials
            restored = CopilotMaterials(self.app.copilot)
            self.assertEqual(restored.list(self.thread['id'])['items'][0]['sha256'], hashlib.sha256(b'local synthetic reference').hexdigest())
        with self.app.core.db() as db:
            for table in ('agent_runs', 'copilot_turns', 'tasks'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
        self.assertNotIn('content_base64', json.dumps(self.materials.list(self.thread['id'])))
        self.assertNotIn('local synthetic reference', json.dumps(self.materials.list(self.thread['id'])))

    def test_rejects_paths_urls_unsafe_names_types_and_bad_base64(self):
        for fields in ({'filename':'../notes.txt'}, {'filename':'/tmp/notes.txt'}, {'filename':'x\\notes.txt'}, {'filename':'https://example.test/a.txt'}, {'filename':'a\n.txt'}, {'filename':'a\u202e.txt'}, {'filename':'.hidden.txt'}, {'filename':'x.exe'}, {'filename':'x.txt','mime_type':'text/html'}, {'content_base64':'%%%invalid'}, {'content_base64':'data:text/plain;base64,SGk='}, {'content_base64':True}, {'mime_type':[]}, {'filename':None}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.upload(**fields)
        with self.assertRaisesRegex(ValueError, 'invalid_arguments'):
            self.materials.invoke('commerce_copilot_material_upload', {'path':'/tmp/secret'})
        self.assertEqual(self.materials.list(self.thread['id'])['items'], [])

    def test_strict_utf8_and_content_limits_preserve_honest_truncation(self):
        for bad in (b'\xff', b'hello\x00there', b'MZ'+b'\x01'*20, b'x'*65537):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):self.upload(text=bad)
        item = self.upload(text=('合成资料'*2000).encode())
        detail = self.materials.get(self.thread['id'], item['id'])
        self.assertEqual(len(detail['text']), 4096)
        self.assertTrue(detail['text_truncated'])
        self.assertEqual(detail['text_characters'], 8000)
        frozen = self.resolve([item['id']])
        self.assertEqual(frozen['items'][0]['text'], detail['text'])
        self.assertTrue(frozen['instructions_are_untrusted_data'])
        self.assertFalse(frozen['external_execution_allowed'])

    def test_json_is_validated_and_text_mime_must_match_extension(self):
        self.assertEqual(self.upload(text=b'{"a":1}', filename='selected.json', mime_type='application/json')['mime_type'], 'application/json')
        for text, name, mime in ((b'{broken', 'x.json', 'application/json'), (b'a,b', 'x.csv', 'application/json'), (b'%PDF-x', 'x.txt', 'text/plain')):
            with self.subTest(name=name), self.assertRaises(ValueError):self.upload(text=text, filename=name, mime_type=mime, idempotency_key=name)

    def test_replay_cannot_replace_bytes_or_resurrect_removed_material(self):
        item=self.upload()
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):self.upload(text=b'different')
        with self.assertRaisesRegex(ValueError, 'material_changed'):
            self.materials.remove(self.thread['id'], item['id'], '0'*64)
        self.materials.remove(self.thread['id'], item['id'], item['sha256'])
        self.assertEqual(self.materials.list(self.thread['id'])['items'], [])
        with self.assertRaisesRegex(ValueError, 'material_removed'):self.upload()
        with self.assertRaisesRegex(ValueError, 'material_not_found'):self.resolve([item['id']])

    def test_upload_retry_reuses_receipt_without_running_local_extractor_again(self):
        item=self.upload()
        with patch('copilot.materials._extract',side_effect=AssertionError('duplicate extraction')):
            self.assertEqual(self.upload()['id'],item['id'])

    def test_scope_revision_change_during_extraction_rejects_the_old_upload(self):
        from copilot.materials import _extract
        def extracting(content,extension):
            changed=self.app.copilot.context(self.thread['id'],{'module':'products','demo':True},self.thread['context_sha256'])
            self.app.copilot.context(self.thread['id'],self.thread['context'],changed['context_sha256'])
            return _extract(content,extension)
        with patch('copilot.materials._extract',side_effect=extracting),self.assertRaisesRegex(ValueError,'material_scope_changed'):
            self.upload()
        self.assertEqual(self.materials.list(self.thread['id'])['items'],[])

    def test_metadata_and_text_read_do_not_read_the_uploaded_blob(self):
        item=self.upload()
        def authorize(action,table,column,db_name,trigger):
            return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_READ and table=='copilot_materials' and column=='content' else sqlite3.SQLITE_OK
        with self.app.core.atomic() as db:
            db.set_authorizer(authorize)
            try:
                self.assertEqual(self.materials.metadata(db,self.app.copilot._thread(db,self.thread['id']))[0]['id'],item['id'])
                self.assertEqual(self.materials.get(self.thread['id'],item['id'])['text'],'local synthetic reference')
            finally:db.set_authorizer(None)

    def test_material_ids_are_bound_to_thread_and_context_revision(self):
        item=self.upload()
        other=self.open(key='other')
        with self.assertRaisesRegex(ValueError, 'material_not_found'):self.resolve([item['id']], other)
        with self.assertRaisesRegex(ValueError, 'material_not_found'):self.materials.get(other['id'], item['id'])
        changed=self.app.copilot.context(self.thread['id'], {'module':'products','demo':True}, self.thread['context_sha256'])
        restored=self.app.copilot.context(self.thread['id'], self.thread['context'], changed['context_sha256'])
        self.assertTrue(self.materials.list(restored['id'])['items'][0]['stale'])
        with self.assertRaisesRegex(ValueError, 'material_scope_changed'):self.resolve([item['id']])
        with self.assertRaisesRegex(ValueError, 'context_changed'):self.upload(context_sha256='0'*64, idempotency_key='other')

    def test_selected_material_budget_and_duplicate_ids_are_enforced(self):
        ids=[self.upload(text=(str(i)*5000).encode(), idempotency_key=str(i))['id'] for i in range(5)]
        for bad in ([ids[0],ids[0]],ids,'not-list',[None]):
            with self.subTest(value=bad),self.assertRaises(ValueError):self.resolve(bad)
        frozen=self.resolve(ids[:4])
        self.assertLessEqual(sum(len(row['text']) for row in frozen['items']),8192)
        self.assertTrue(frozen['text_truncated'])
        self.assertFalse(frozen['items'][-1]['model_usable'])
        self.assertEqual(self.resolve([])['items'], [])

    def test_current_order_reference_uses_filtered_actual_row_and_no_customer_fields(self):
        item=self.reference()
        frozen=self.resolve([item['id']])['items'][0]
        self.assertIn('SIM-1001', frozen['text'])
        self.assertIn('宠物梳理套装', frozen['text'])
        self.assertNotIn('示例店铺', frozen['text'])
        self.assertEqual(frozen['object'], {'kind':'order','id':'SIM-1001'})
        self.assertEqual(item['sha256'], frozen['sha256'])
        for fields in ({'object_id':'SIM-1002'}, {'kind':'product','object_id':'PET-021'}):
            with self.assertRaisesRegex(ValueError, 'reference_outside_scope'):self.reference(**fields)

    def test_changed_live_record_and_connection_reject_the_saved_reference(self):
        from test_live_connections import batch, SECRET
        self.app.live.configure({'ozon_client_id':'123456','ozon_api_key':SECRET})
        config=self.app.live.config()
        self.app.live._publish(config['connection_id'],'orders',batch('orders'),config,False)
        row=self.app.live.workbench('commerce_orders_list',{})['orders'][0]
        self.thread=self.open({'module':'orders','demo':False,'platform':'ozon','store_id':'ozon-live','market':'RU','entity':{'kind':'order','id':row['id']}},'live')
        item=self.reference(object_id=row['id'])
        self.assertIn(row['id'],self.resolve([item['id']])['items'][0]['text'])
        current=batch('orders');current['records'][0]['status']='cancelled'
        self.app.live._publish(config['connection_id'],'orders',current,config,False)
        with self.assertRaisesRegex(ValueError, 'reference_changed'):self.resolve([item['id']])
        with self.assertRaisesRegex(ValueError, 'reference_changed'):self.reference(object_id=row['id'])

    def test_reference_requires_concrete_business_scope(self):
        for update in ({'demo':False}, {'market':'US'}, {'store_id':'amazon-demo'}, {'market':'all'}, {'platform':'all'}):
            self.thread=self.open({**self.thread['context'],**update}, 'scope-'+json.dumps(update))
            with self.subTest(update=update),self.assertRaises(ValueError):self.reference()

    def test_intel_reference_rereads_current_public_record(self):
        row=dict(id='a'*24,source='wto',source_key='synthetic',title='Synthetic public bulletin',url='https://example.test/bulletin',published=1700000000,category='trade',country=None,country_code=None,location=None,publisher_alert=None,collected_at='2026-11-16T00:00:00Z',source_payload_sha256='b'*64)
        def publish():
            with self.app.core.db() as db:
                db.execute('INSERT OR REPLACE INTO intel_items VALUES(?,?,?)',(row['id'],'wto',json.dumps(row)))
                self.app.intelligence.store.archive(db,row,time.time())
        publish()
        self.thread=self.open({'module':'intelligence','demo':False,'entity':{'kind':'intel','id':row['id']}},'intel')
        item=self.reference(kind='intel',object_id=row['id'])
        self.assertIn('Synthetic public bulletin',self.resolve([item['id']])['items'][0]['text'])
        row['title']='Changed bulletin';publish()
        with self.assertRaisesRegex(ValueError, 'reference_changed'):self.resolve([item['id']])

    def test_images_never_claim_visual_understanding_and_preview_is_separate(self):
        def chunk(kind,data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
        # A tiny synthetic bitmap font keeps this real OCR check dependency-free.
        font={'L':['10000']*6+['11111'],'O':['01110']+['10001']*5+['01110'],
              'C':['01111']+['10000']*5+['01111'],'A':['01110','10001','10001','11111','10001','10001','10001'],
              'T':['11111']+['00100']*6,'E':['11111','10000','10000','11110','10000','10000','11111'],
              'X':['10001','10001','01010','00100','01010','10001','10001'],' ':['00000']*7}
        rows=[]
        for y in range(112):
            row=bytearray([0])
            for x in range(520):
                xx,yy=x-20,y-24;black=False
                if xx>=0 and 0<=yy<56:
                    letter,column=divmod(xx,48)
                    if letter<10 and column<40:black=font['LOCAL TEXT'[letter]][yy//8][column//8]=='1'
                row.extend(b'\x00\x00\x00' if black else b'\xff\xff\xff')
            rows.append(row)
        image=(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',520,112,8,2,0,0,0))
               +chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b''))
        if not self.materials.capabilities()['image_ocr_available']:self.skipTest('local image extractor unavailable')
        item=self.upload(text=image,filename='selected.png',mime_type='image/png')
        detail=self.materials.get(self.thread['id'],item['id'])
        self.assertFalse(detail['visual_understanding'])
        self.assertEqual(detail['extraction_status'],'completed')
        self.assertIn('TEXT',detail['text'])
        self.assertNotIn('content_base64',detail)
        preview=self.materials.preview(self.thread['id'],item['id'])
        self.assertEqual(base64.b64decode(preview['content_base64']),image)
        self.assertFalse(self.resolve([item['id']])['items'][0]['visual_understanding'])
        with self.assertRaises(ValueError):self.upload(text=b'\x89PNG\r\n\x1a\ninvalid',filename='broken.png',mime_type='image/png',idempotency_key='broken')

    def test_pdf_extracts_actual_document_text_without_reading_another_file(self):
        if not self.materials.capabilities()['pdf_text_available']:self.skipTest('local PDF text extractor unavailable')
        content=b'BT /F1 16 Tf 20 80 Td (LOCAL SYNTHETIC MATERIAL) Tj ET'
        objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 120] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream']
        data=b'%PDF-1.4\n';offsets=[0]
        for number,obj in enumerate(objects,1):
            offsets.append(len(data));data+=str(number).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
        xref=len(data)
        data+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(('%010d 00000 n \n'%offset).encode() for offset in offsets[1:])
        data+=b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF'
        item=self.upload(text=data,filename='synthetic.pdf',mime_type='application/pdf')
        detail=self.materials.get(self.thread['id'],item['id'])
        self.assertIn('LOCAL SYNTHETIC MATERIAL',detail['text'])
        self.assertTrue(detail['extraction_partial'])
        self.assertEqual(detail['extraction'],'pdf_text_first_20_pages')

    def test_case_reference_revalidates_actual_authoritative_scope_and_source(self):
        from test_organization import OrganizationTests
        fixture=OrganizationTests();fixture.setUp()
        try:
            app=fixture.app
            with app.core.db() as db:
                connection,scope=db.execute('SELECT connection,scope FROM org_cases WHERE id=?',(fixture.cid,)).fetchone()
                scope=json.loads(scope)
                scope.update(synthetic=True,store_ref='ozon-demo',subject_ref=fixture.cid)
                db.execute('UPDATE org_cases SET scope=? WHERE id=?',(json.dumps(scope),fixture.cid))
            from copilot.materials import CopilotMaterials
            materials=CopilotMaterials(app.copilot)
            thread=app.copilot.open({'module':'organization','demo':True,'platform':'ozon','store_id':'ozon-demo','market':'RU','entity':{'kind':'case','id':fixture.cid}},'case-thread')
            item=materials.reference(thread['id'],thread['context_sha256'],'case',fixture.cid,'case-ref')
            with app.core.atomic() as db:
                frozen=materials.resolve_for_send(db,app.copilot._thread(db,thread['id']),[item['id']])
            self.assertIn(fixture.cid,frozen['items'][0]['text'])
            with app.core.db() as db:
                scope['store_ref']='other-store'
                db.execute('UPDATE org_cases SET scope=? WHERE id=?',(json.dumps(scope),fixture.cid))
            with app.core.atomic() as db,self.assertRaisesRegex(ValueError,'reference_changed'):
                materials.resolve_for_send(db,app.copilot._thread(db,thread['id']),[item['id']])
        finally:fixture.tearDown()

    def test_extractor_unavailable_and_timeout_fail_honestly(self):
        with patch('copilot.materials.shutil.which',return_value=None):
            with self.assertRaisesRegex(ValueError,'extraction_unavailable'):self.upload(text=b'%PDF-1.4\n%%EOF',filename='x.pdf',mime_type='application/pdf')
        import subprocess
        with patch('copilot.materials.subprocess.run',side_effect=subprocess.TimeoutExpired('extract',8)):
            with self.assertRaisesRegex(ValueError,'extraction_timeout'):self.upload(text=b'%PDF-1.4\n%%EOF',filename='x.pdf',mime_type='application/pdf')

    def test_send_rechecks_blob_integrity_and_metadata_never_exports_private_paths(self):
        item=self.upload()
        with self.app.core.db() as db:db.execute('UPDATE copilot_materials SET content=? WHERE id=?',(b'changed',item['id']))
        with self.assertRaisesRegex(ValueError,'material_changed'):self.resolve([item['id']])
        self.assertNotIn(self.tmp.name,json.dumps(self.materials.capabilities()))


if __name__=='__main__':unittest.main()
