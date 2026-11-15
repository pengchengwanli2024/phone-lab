"""Explicit, resumable queues over original article captures; never translate."""
import json
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from article_binding import bind
from research import canonical,digest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'crawlers')not in sys.path:sys.path.insert(0,str(ROOT/'crawlers'))
from article import PUBLISHERS,allowed

ACTIVE=('queued','running','cancel_requested')


def definitions(schema,string):
    plan={'filters':{'type':'object'},'limit':{'type':'integer','minimum':1,'maximum':30}}
    return [
        ('commerce_intel_article_plan','预览当前筛选内缺失正文，按支持来源均衡选择最多30条；不启动采集',schema(plan,list(plan))),
        ('commerce_intel_article_batch_start','按准确预览启动有界串行正文采集；保留逐条失败，不自动翻译',schema({**plan,'expected_plan_sha256':string,'idempotency_key':string},[*plan,'expected_plan_sha256','idempotency_key'])),
        ('commerce_intel_article_batch_get','读取同一正文批次逐条回执与当前版本覆盖，不重发',schema({'batch_id':string},['batch_id'])),
        ('commerce_intel_article_batch_list','读取最近正文批次；不启动或自动恢复采集',schema()),
        ('commerce_intel_article_batch_cancel','停止批次剩余采集；已经发出的单条最多等待原45秒边界',schema({'batch_id':string},['batch_id'])),
        ('commerce_intel_article_batch_resume','明确恢复原批次，按需重试失败；可仅选择失败条目，不重抓已成功条目',schema({'batch_id':string,'expected_revision':{'type':'integer','minimum':0},'retry_failed':{'type':'boolean'},'retry_item_ids':{'type':'array','items':string,'maxItems':30}},['batch_id','expected_revision','retry_failed'])),
    ]


class ArticleBatches:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.articles=service.articles;self.store=service.intelligence.store
        self.stopping=threading.Event();self.threads={};self.lock=threading.Lock()
        with self.core.db()as db:
            db.execute('CREATE TABLE IF NOT EXISTS intel_article_batches(id TEXT PRIMARY KEY,idem TEXT UNIQUE,request_sha TEXT,status TEXT,document TEXT)')

    def invoke(self,name,args):
        methods={'plan':self.plan,'batch_start':self.start,'batch_get':self.get,'batch_list':self.listing,'batch_cancel':self.cancel,'batch_resume':self.resume}
        return methods[name.removeprefix('commerce_intel_article_')](**args)

    def latest(self):
        with self.core.db()as db:
            return {item_id:json.loads(raw)for item_id,raw in db.execute('SELECT a.item_id,a.doc FROM intel_articles a WHERE a.rowid=(SELECT MAX(n.rowid)FROM intel_articles n WHERE n.item_id=a.item_id)')}

    @staticmethod
    def ready(doc,row):
        if not doc or doc.get('status')!='ready' or doc.get('record_sha256')!=row['record_sha256']:return False
        try:
            article=bind(doc['article'])
            return article['record_sha256']==row['record_sha256']and article['source_url']==row['url']
        except (ValueError,KeyError,TypeError):return False

    def plan(self,filters,limit=20):
        if type(filters)is not dict or set(filters)-{'query','source','category','country','hours','scope','view'}or type(limit)is not int or not 1<=limit<=30:raise ValueError('article_batch_invalid_plan')
        filters=self.store.filters(**filters)
        rows=self.store.matches(self.store.rows(filters['scope']),filters,self.core);latest=self.latest()
        groups={source:[]for source in PUBLISHERS};counts={'matched':len(rows),'current_ready':0,'unsupported':0,'invalid_url':0,'missing_supported':0}
        for row in rows:
            if row['source']not in PUBLISHERS:counts['unsupported']+=1;continue
            try:allowed(row['source'],row['url'],resolve=False)
            except ValueError:counts['invalid_url']+=1;continue
            if self.ready(latest.get(row['id']),row):counts['current_ready']+=1;continue
            counts['missing_supported']+=1
            groups[row['source']].append({k:row[k]for k in ('source','title','url','record_sha256')}|{'item_id':row['id']})
        records=[]
        while len(records)<limit and any(groups.values()):
            for group in groups.values():
                if group and len(records)<limit:records.append(group.pop(0))
        selection=dict(filters=filters,limit=limit,records=records)
        return {**selection,'sha256':digest(canonical(selection)),'coverage':counts,'supported_sources':list(PUBLISHERS),
                'fetch_started':False,'translation_started':False,'scope':'locally_collected_publisher_pages_only'}

    def _get(self,db,batch_id):
        if not isinstance(batch_id,str)or not re.fullmatch('[a-f0-9]{32}',batch_id):raise ValueError('article_batch_invalid_id')
        row=db.execute('SELECT document FROM intel_article_batches WHERE id=?',(batch_id,)).fetchone()
        if not row:raise ValueError('article_batch_not_found')
        return json.loads(row[0])

    def save(self,db,doc):
        doc['revision']+=1;doc['updated_at']=time.time()
        db.execute('UPDATE intel_article_batches SET status=?,document=?WHERE id=?',(doc['status'],canonical(doc),doc['id']))

    def get(self,batch_id):
        with self.core.db()as db:
            doc=self._get(db,batch_id)
            ids=[r['article_id']for r in doc['records']if r['article_id']]
            children={r[0]:json.loads(r[1])for r in db.execute('SELECT id,doc FROM intel_articles WHERE id IN ('+','.join('?'for _ in ids)+')',ids)}if ids else{}
        rows={r['id']:r for r in self.store.rows('archive')};counts={k:0 for k in ('captured','current_ready','failed','pending','superseded')}
        for entry in doc['records']:
            row=rows.get(entry['item_id']);entry['source_record_changed']=not row or row['record_sha256']!=entry['record_sha256']
            if entry['status']=='ready':
                counts['captured']+=1
                current=children.get(entry['article_id'])
                if row and self.ready(current,row):counts['current_ready']+=1
            elif entry['status']=='failed':counts['failed']+=1
            elif entry['status']=='superseded':counts['superseded']+=1
            else:counts['pending']+=1
        return {**doc,'counts':counts,'translation_started':False,'independently_verified':False}

    def listing(self):
        with self.core.db()as db:ids=[r[0]for r in db.execute('SELECT id FROM intel_article_batches ORDER BY rowid DESC LIMIT 8')]
        return {'batches':[self.get(i)for i in ids],'automatic_resume':False}

    def start(self,filters,limit,expected_plan_sha256,idempotency_key):
        if not isinstance(idempotency_key,str)or not 1<=len(idempotency_key)<=160:raise ValueError('invalid_idempotency_key')
        request_sha=digest(canonical([filters,limit,expected_plan_sha256]))
        with self.core.db()as db:old=db.execute('SELECT id,request_sha FROM intel_article_batches WHERE idem=?',(idempotency_key,)).fetchone()
        if old:
            if old[1]!=request_sha:raise ValueError('idempotency_conflict')
            return self.get(old[0])
        plan=self.plan(filters,limit)
        if plan['sha256']!=expected_plan_sha256:raise ValueError('article_batch_plan_changed')
        if not plan['records']:raise ValueError('article_batch_no_missing_records')
        doc=dict(id=uuid.uuid4().hex,status='queued',revision=0,created_at=time.time(),updated_at=time.time(),
            filters=plan['filters'],limit=limit,plan_sha256=plan['sha256'],error=None,
            records=[dict(r,status='pending',attempt=0,article_id=None,error=None)for r in plan['records']])
        with self.core.atomic()as db:
            old=db.execute('SELECT id,request_sha FROM intel_article_batches WHERE idem=?',(idempotency_key,)).fetchone()
            if old:
                if old[1]!=request_sha:raise ValueError('idempotency_conflict')
                return self.get(old[0])
            if db.execute("SELECT 1 FROM intel_article_batches WHERE status IN ('queued','running','cancel_requested')").fetchone():raise ValueError('article_batch_busy')
            db.execute('INSERT INTO intel_article_batches VALUES (?,?,?,?,?)',(doc['id'],idempotency_key,request_sha,doc['status'],canonical(doc)))
        self.launch(doc['id']);return self.get(doc['id'])

    def launch(self,ident):
        with self.lock:
            if self.stopping.is_set():raise ValueError('article_batch_stopping')
            thread=threading.Thread(target=self.run,args=(ident,),daemon=True,name='article-batch-'+ident[:8]);self.threads[ident]=thread;thread.start()

    def run(self,ident):
        try:
            with self.core.atomic()as db:
                doc=self._get(db,ident)
                if doc['status']!='queued':return
                doc['status']='running';self.save(db,doc)
            deadline=time.monotonic()+30*60
            for index in range(len(doc['records'])):
                with self.core.db()as db:doc=self._get(db,ident)
                if self.stopping.is_set()or doc['status']=='cancel_requested':break
                entry=doc['records'][index]
                if entry['status']!='pending':continue
                try:
                    busy_deadline=min(deadline,time.monotonic()+120)
                    while True:
                        if self.stopping.is_set():raise ValueError('article_batch_interrupted')
                        with self.core.db()as db:current=self._get(db,ident)
                        if current['status']=='cancel_requested':break
                        try:
                            child=self.articles.start(entry['item_id'],entry['record_sha256'],f"article-batch:{ident}:{index}:{entry['attempt']}");break
                        except ValueError as error:
                            if str(error)!='article_worker_busy':raise
                            if time.monotonic()>=busy_deadline:raise ValueError('article_batch_worker_busy_timeout')
                            self.stopping.wait(.1)
                    if current['status']=='cancel_requested':break
                    with self.core.atomic()as db:
                        current=self._get(db,ident);current['records'][index]['article_id']=child['id'];self.save(db,current)
                    while child['status']in ('queued','running'):
                        if time.monotonic()>=deadline:raise ValueError('article_batch_deadline')
                        if self.stopping.wait(.1):raise ValueError('article_batch_interrupted')
                        child=self.articles.get(child['id'])
                    status='ready'if child['status']=='ready'else'failed';error=child.get('error')
                except ValueError as exc:
                    code=str(exc);status='superseded'if code=='intel_record_changed'else'failed'
                    error=code if code.startswith(('article_','intel_'))else'article_batch_capture_failed'
                with self.core.atomic()as db:
                    current=self._get(db,ident);current['records'][index].update(status=status,error=error);self.save(db,current)
            with self.core.atomic()as db:
                current=self._get(db,ident);states=[r['status']for r in current['records']]
                current['status']='interrupted'if self.stopping.is_set()else'cancelled'if current['status']=='cancel_requested'else'partial'if any(s!='ready'for s in states)else'completed'
                self.save(db,current)
        except Exception:
            with self.core.atomic()as db:
                current=self._get(db,ident);current.update(status='interrupted',error='article_batch_interrupted_check_receipts');self.save(db,current)
        finally:
            with self.lock:
                if self.threads.get(ident)is threading.current_thread():self.threads.pop(ident,None)

    def cancel(self,batch_id):
        with self.core.atomic()as db:
            doc=self._get(db,batch_id)
            if doc['status']in ACTIVE:
                doc['status']='cancelled'if doc['status']=='queued'else'cancel_requested';self.save(db,doc)
        return self.get(batch_id)

    def resume(self,batch_id,expected_revision,retry_failed,retry_item_ids=None):
        if type(expected_revision)is not int or type(retry_failed)is not bool:raise ValueError('article_batch_invalid_resume')
        with self.core.atomic()as db:
            doc=self._get(db,batch_id)
            if doc['revision']!=expected_revision:raise ValueError('article_batch_changed')
            if doc['status']not in ('cancelled','interrupted','partial'):raise ValueError('article_batch_not_resumable')
            if retry_item_ids is not None:
                failed={r['item_id']for r in doc['records']if r['status']=='failed'}
                if (not retry_failed or type(retry_item_ids)is not list or not 1<=len(retry_item_ids)<=30
                    or any(not isinstance(i,str)for i in retry_item_ids)or len(set(retry_item_ids))!=len(retry_item_ids)or not set(retry_item_ids)<=failed):raise ValueError('article_batch_invalid_retry_selection')
            if db.execute("SELECT 1 FROM intel_article_batches WHERE status IN ('queued','running','cancel_requested')").fetchone():raise ValueError('article_batch_busy')
            for entry in doc['records']:
                if entry['article_id']and entry['status']in ('pending','failed'):
                    child=self.articles.get(entry['article_id'])
                    if child['status']=='ready':entry.update(status='ready',error=None)
                    elif child['status']in ('queued','running'):entry.update(status='pending')
                    elif child['status']in ('failed','interrupted'):entry.update(status='failed',error=child.get('error')or'article_interrupted')
                if entry['status']=='failed'and retry_failed and(retry_item_ids is None or entry['item_id']in retry_item_ids):entry.update(status='pending',attempt=entry['attempt']+1,error=None,article_id=None)
            if all(r['status']=='ready'for r in doc['records']):
                doc.update(status='completed',error=None);self.save(db,doc);return self.get(batch_id)
            if not any(r['status']=='pending'for r in doc['records']):raise ValueError('article_batch_no_remaining_records')
            doc.update(status='queued',error=None);self.save(db,doc)
        self.launch(batch_id);return self.get(batch_id)

    def recover(self):
        with self.core.atomic()as db:
            for ident, in db.execute("SELECT id FROM intel_article_batches WHERE status IN ('queued','running','cancel_requested')").fetchall():
                doc=self._get(db,ident);doc.update(status='interrupted',error='article_batch_restart_requires_resume');self.save(db,doc)

    def stop(self):
        self.stopping.set()
        for thread in list(self.threads.values()):thread.join(timeout=2)
