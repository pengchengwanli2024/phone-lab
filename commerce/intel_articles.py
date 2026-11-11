"""Private article snapshots and translations bound to captured source revisions."""
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid
from article_binding import bind, text_hash
from research import canonical, drift

ROOT=Path(__file__).resolve().parents[1]


class Articles:
    def __init__(self, core, state, intelligence, translations, fetcher=None):
        self.core,self.intelligence,self.translations=core,intelligence,translations
        self.directory=Path(state)/'articles';self.directory.mkdir(exist_ok=True,mode=0o700)
        self.slots=threading.BoundedSemaphore(1);self.fetcher=fetcher or self.capture
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS intel_articles (id TEXT PRIMARY KEY, idem TEXT UNIQUE, item_id TEXT, record_sha TEXT, doc TEXT)')

    def recover(self):
        with self.core.db() as db:
            for ident,document in db.execute('SELECT id,doc FROM intel_articles').fetchall():
                doc=json.loads(document)
                if doc['status'] in ('queued','running'):doc.update(status='interrupted',error='article_interrupted_no_automatic_retry')
                if doc.get('translation_status')=='running':doc.update(translation_status='interrupted',error='translation_interrupted_no_automatic_retry')
                db.execute('UPDATE intel_articles SET doc=? WHERE id=?',(canonical(doc),ident))

    def save(self, doc):
        with self.core.db() as db:db.execute('UPDATE intel_articles SET doc=? WHERE id=?',(canonical(doc),doc['id']))

    def get(self, article_id):
        with self.core.db() as db:row=db.execute('SELECT doc FROM intel_articles WHERE id=?',(article_id,)).fetchone()
        if not row:raise ValueError('article_not_found')
        doc=json.loads(row[0])
        try:doc['source_record_changed']=self.intelligence.store.item(doc['item_id'])['record_sha256']!=doc['record_sha256']
        except ValueError:doc['source_record_changed']=True
        return doc

    def for_item(self,item_id):
        with self.core.db() as db:ids=[r[0] for r in db.execute('SELECT id FROM intel_articles WHERE item_id=? ORDER BY rowid DESC LIMIT 5',(item_id,))]
        return {'articles':[self.get(ident) for ident in ids]}

    def start(self,item_id,record_sha256,idempotency_key):
        if not isinstance(idempotency_key,str) or not idempotency_key.strip() or len(idempotency_key)>160:raise ValueError('invalid_idempotency_key')
        with self.core.db() as db:old=db.execute('SELECT id,item_id,record_sha FROM intel_articles WHERE idem=?',(idempotency_key,)).fetchone()
        if old:
            if old[1:]!=(item_id,record_sha256):raise ValueError('idempotency_conflict')
            return self.get(old[0])
        item=self.intelligence.store.item(item_id)
        if item['record_sha256']!=record_sha256:raise ValueError('intel_record_changed')
        # Validate the publisher before queueing. Imports are local, not module execution.
        import sys
        if str(ROOT/'crawlers') not in sys.path:sys.path.insert(0,str(ROOT/'crawlers'))
        from article import allowed
        allowed(item['source'],item['url'],resolve=False)
        if not self.slots.acquire(blocking=False):raise ValueError('article_worker_busy')
        doc=dict(id=uuid.uuid4().hex,item_id=item_id,record_sha256=record_sha256,status='queued',
                 source=item['source'],url=item['url'],created_at=time.time(),error=None,translation_status='not_requested')
        try:
            with self.core.db() as db:db.execute('INSERT INTO intel_articles VALUES (?,?,?,?,?)',(doc['id'],idempotency_key,item_id,record_sha256,canonical(doc)))
        except Exception:self.slots.release();raise
        threading.Thread(target=self._capture,args=(doc,),daemon=True).start()
        return self.get(doc['id'])

    def capture(self,doc):
        from collection_jobs import terminate
        from setup import environment
        folder=self.directory/doc['id'];folder.mkdir(mode=0o700)
        output=folder/'capture.json'
        command=[str(ROOT/'.local/crawlers/venv/bin/python'),str(ROOT/'crawlers/route_worker.py'),'--article',
                 '--source',doc['source'],'--url',doc['url'],'--output',str(output)]
        with (folder/'worker.log').open('w') as log:
            child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=environment(),start_new_session=True)
            from resource_limits import group_rss_kib
            deadline=time.monotonic()+45
            try:
                while child.poll() is None:
                    if time.monotonic()>deadline:raise ValueError('article_timeout')
                    if group_rss_kib(child.pid)>1024*1024:raise ValueError('article_memory_limit')
                    time.sleep(1)
            finally:
                if child.poll() is None:terminate(child)
        if child.returncode or not output.is_file():raise ValueError('article_capture_failed_check_private_receipt')
        if output.stat().st_size>2_000_000:raise ValueError('article_payload_too_large')
        return json.loads(output.read_text())

    def _capture(self,doc):
        try:
            doc['status']='running';self.save(doc)
            article=self.fetcher(doc);article['record_sha256']=doc['record_sha256']
            doc.update(article=bind(article),status='ready')
        except Exception as error:
            doc.update(status='failed',error=str(error) if isinstance(error,ValueError) and str(error).startswith('article_') else 'article_capture_failed')
        finally:self.save(doc);self.slots.release()

    def translate(self,article_id):
        doc=self.get(article_id)
        if doc['status']!='ready':raise ValueError('article_not_ready')
        if doc['source_record_changed']:raise ValueError('intel_record_changed')
        if doc.get('translation_status') in ('running','pending_review'):return doc
        if not self.slots.acquire(blocking=False):raise ValueError('article_worker_busy')
        doc.update(translation_status='running',error=None);self.save(doc)
        threading.Thread(target=self._translate,args=(doc,),daemon=True).start()
        return self.get(article_id)

    def _translate(self,doc):
        try:
            text=doc['article']['text'];translated=[];receipts=[]
            chunks=[{'id':str(i),'text':text[start:start+5500]} for i,start in enumerate(range(0,len(text),5500))]
            for start in range(0,len(chunks),2):
                batch=chunks[start:start+2]
                job=self.translations.start({'language':'auto','items':batch},'article:'+doc['id']+':'+str(start)+':'+str(time.time_ns()))
                end=time.monotonic()+110
                while job['status'] in ('queued','running') and time.monotonic()<end:
                    time.sleep(.2);job=self.translations.get(job['id'])
                if job['status']!='completed':raise ValueError('article_translation_failed')
                result=job['result'];by_id={row['id']:row for row in result['translations']}
                for chunk in batch:
                    row=by_id[chunk['id']]
                    if row['original_sha256']!=text_hash(chunk['text']):raise ValueError('article_translation_binding_mismatch')
                    translated.append(row['zh'])
                receipts.append({k:result.get(k) for k in ('provider','model','translated_at','prompt_version','tools_enabled')})
            zh='\n\n'.join(translated)
            value=dict(zh=zh,original_sha256=doc['article']['content_sha256'],zh_sha256=text_hash(zh),
                       warnings=drift(text,zh),model_receipts=receipts)
            doc.update(article=bind(doc['article'],value),translation_status='pending_review')
        except Exception:
            doc.update(translation_status='failed',error='article_translation_failed')
        finally:self.save(doc);self.slots.release()
