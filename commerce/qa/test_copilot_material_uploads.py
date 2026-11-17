"""Chunked local intake reuses the exact original material/scope ledger."""
import base64
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce

class ChunkedMaterials(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name)
        self.thread=self.app.copilot.open({'module':'overview','demo':True},'synthetic-open')
        self.bound=dict(thread_id=self.thread['id'],context_sha256=self.thread['context_sha256'])
        self.content=('合成参考，未独立核实。\n'*5000).encode()
    def tearDown(self):self.app.agent_runtime.stop();self.tmp.cleanup()
    def call(self,op,**args):return self.app.invoke('commerce_copilot_material_'+op,args,'test')
    def begin(self,**overrides):return self.call('upload_begin',**{**self.bound,'filename':'reference.txt','mime_type':'text/plain','size_bytes':len(self.content),'content_sha256':hashlib.sha256(self.content).hexdigest(),'idempotency_key':'synthetic-upload',**overrides})
    def chunk(self,upload,index,content):return self.call('upload_chunk',**self.bound,upload_id=upload['id'],index=index,content_base64=base64.b64encode(content).decode())
    def fill(self,upload):
        size=upload['chunk_bytes']
        for i,start in enumerate(range(0,len(self.content),size)):self.chunk(upload,i,self.content[start:start+size])
    def finish(self,upload):return self.call('upload_finish',**self.bound,upload_id=upload['id'])
    def test_large_selected_file_is_one_original_material_with_bounded_text_and_no_model(self):
        with patch('agent_runtime.model.invoke',side_effect=AssertionError('no model')):
            upload=self.begin();self.fill(upload);item=self.finish(upload)
            self.assertEqual(item['sha256'],hashlib.sha256(self.content).hexdigest());self.assertEqual(item['size_bytes'],len(self.content))
            detail=self.app.copilot.materials.get(self.thread['id'],item['id']);self.assertEqual(len(detail['text']),4096);self.assertTrue(detail['text_truncated']);self.assertFalse(detail['visual_understanding'])
            with patch('copilot.materials._extract',side_effect=AssertionError('no duplicate extraction')):self.assertEqual(self.finish(upload)['id'],item['id'])
            self.assertEqual(self.begin()['status'],'completed')
        with self.app.core.db()as db:
            self.assertEqual(db.execute('SELECT count(*) FROM copilot_materials').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM copilot_material_chunks').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0],0)
    def test_chunks_require_order_exact_bytes_and_consistent_retry(self):
        upload=self.begin();part=self.content[:upload['chunk_bytes']]
        with self.assertRaisesRegex(ValueError,'chunk_order'):self.chunk(upload,1,part)
        first=self.chunk(upload,0,part);again=self.chunk(upload,0,part);self.assertEqual(first['received_bytes'],again['received_bytes'])
        with self.assertRaisesRegex(ValueError,'chunk_conflict'):self.chunk(upload,0,b'x'*len(part))
        with self.assertRaisesRegex(ValueError,'incomplete'):self.finish(upload)
        with self.assertRaisesRegex(ValueError,'chunk_size|invalid_content_base64'):self.chunk(upload,1,b'x'*(upload['chunk_bytes']+1))
    def test_whole_file_hash_failure_does_not_create_material(self):
        upload=self.begin(content_sha256='0'*64);self.fill(upload)
        with self.assertRaisesRegex(ValueError,'hash_mismatch'):self.finish(upload)
        self.assertEqual(self.app.copilot.materials.list(self.thread['id'])['items'],[])
    def test_cancel_is_idempotent_purges_chunks_and_cannot_complete(self):
        upload=self.begin();self.chunk(upload,0,self.content[:upload['chunk_bytes']])
        args={**self.bound,'upload_id':upload['id']};self.assertEqual(self.call('upload_cancel',**args)['status'],'cancelled');self.assertEqual(self.call('upload_cancel',**args)['status'],'cancelled')
        with self.assertRaisesRegex(ValueError,'not_active'):self.finish(upload)
        with self.app.core.db()as db:self.assertEqual(db.execute('SELECT count(*) FROM copilot_material_chunks').fetchone()[0],0)
    def test_cross_thread_context_revision_and_expired_session_are_rejected(self):
        upload=self.begin();other=self.app.copilot.open({'module':'orders','demo':True},'other')
        with self.assertRaisesRegex(ValueError,'not_found'):self.call('upload_finish',thread_id=other['id'],context_sha256=other['context_sha256'],upload_id=upload['id'])
        with self.app.core.db()as db:db.execute('UPDATE copilot_threads SET revision=revision+1 WHERE id=?',(self.thread['id'],))
        with self.assertRaisesRegex(ValueError,'scope_changed'):self.chunk(upload,0,self.content[:upload['chunk_bytes']])
        self.thread=self.app.copilot.open({'module':'tasks','demo':True},'expires');self.bound=dict(thread_id=self.thread['id'],context_sha256=self.thread['context_sha256']);upload=self.begin(idempotency_key='expires')
        with patch('copilot.material_uploads.time.time',return_value=upload['expires_at']+1):
            with self.assertRaisesRegex(ValueError,'expired'):self.finish(upload)
    def test_idempotency_limits_and_preflight_are_explicit(self):
        first=self.begin();self.assertEqual(self.begin()['id'],first['id'])
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.begin(filename='other.txt')
        for changes in ({'size_bytes':True},{'size_bytes':2*1024*1024+1},{'content_sha256':'bad'},{'filename':'../secret.txt'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.begin(idempotency_key='invalid',**changes)
        self.begin(idempotency_key='second')
        with self.assertRaisesRegex(ValueError,'active_limit'):self.begin(idempotency_key='third')
        caps=self.call('capabilities');self.assertEqual(caps['max_chunked_file_bytes'],2*1024*1024);self.assertEqual(caps['max_text_characters'],4096)
        preflight=self.call('preflight',filename='reference.txt',mime_type='text/plain',size_bytes=len(self.content));self.assertTrue(preflight['allowed']);self.assertFalse(preflight['visual_understanding']);self.assertTrue(preflight['local_only'])
    def test_scope_change_during_extraction_cannot_save_or_rebind_bytes(self):
        upload=self.begin();self.fill(upload)
        from copilot.materials import _extract
        def changed(*args):
            result=_extract(*args)
            with self.app.core.db()as db:db.execute('UPDATE copilot_threads SET revision=revision+1 WHERE id=?',(self.thread['id'],))
            return result
        with patch('copilot.materials._extract',side_effect=changed),self.assertRaisesRegex(ValueError,'scope_changed'):self.finish(upload)
        self.assertEqual(self.app.copilot.materials.list(self.thread['id'])['items'],[])

if __name__=='__main__':unittest.main()
