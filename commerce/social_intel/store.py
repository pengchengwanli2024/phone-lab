"""Private immutable batches, revision-bound heads and bounded evidence transport."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import package as contract
from .admission import prepare


def now(): return datetime.now(timezone.utc).isoformat()
def reject(condition, code):
    if not condition: raise ValueError(code)


class SocialStore:
    def __init__(self, service):
        self.service, self.core = service, service.core
        self.root = service.state / 'social'
        self.root.mkdir(mode=0o700, exist_ok=True)
        for name in ('stages', 'batches'):
            (self.root/name).mkdir(mode=0o700, exist_ok=True)
        self.mutex = threading.RLock()
        with self.core.db() as db:
            for sql in [
                'CREATE TABLE IF NOT EXISTS social_batches (id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, document TEXT NOT NULL, imported_at TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS social_heads (id TEXT PRIMARY KEY, record_sha TEXT NOT NULL, batch_id TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS social_versions (id TEXT NOT NULL, record_sha TEXT NOT NULL, document TEXT NOT NULL, batch_id TEXT NOT NULL, PRIMARY KEY(id,record_sha))',
                'CREATE TABLE IF NOT EXISTS social_receipts (idem TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS social_marks (id TEXT PRIMARY KEY, viewed_content TEXT, bookmarked INTEGER NOT NULL DEFAULT 0)',
                'CREATE TABLE IF NOT EXISTS social_reviews (idem TEXT PRIMARY KEY, record_id TEXT NOT NULL, record_sha TEXT NOT NULL, task_id TEXT NOT NULL)',
            ]: db.execute(sql)

    @contextmanager
    def locked(self):
        with self.mutex, (self.root/'write.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def stage_folder(self, stage_id):
        reject(isinstance(stage_id,str) and len(stage_id)==32 and all(c in '0123456789abcdef' for c in stage_id), 'social_stage_invalid')
        folder = self.root/'stages'/stage_id
        reject(folder.is_dir() and not folder.is_symlink(), 'social_stage_not_found')
        return folder

    def stage(self, bundle, idempotency_key):
        contract.validate_schema(bundle, json.loads(Path(contract.__file__).with_name('schema.json').read_text()))
        text = contract.canonical(bundle)
        reject(len(text.encode()) <= 100000, 'social_metadata_too_large_for_transport')
        reject(isinstance(idempotency_key,str) and 0<len(idempotency_key)<=160, 'invalid_idempotency_key')
        fingerprint = contract.digest(text)
        stage_id = contract.digest('stage:'+idempotency_key)[:32]
        with self.locked():
            folder=self.root/'stages'/stage_id
            if folder.exists():
                reject((folder/'bundle.json').read_text()==text,'social_stage_idempotency_conflict')
            else:
                folder.mkdir(mode=0o700)
                (folder/'evidence').mkdir(mode=0o700)
                for asset in bundle['assets']: contract.asset_path(folder,asset['path'])
                (folder/'bundle.json').write_text(text);(folder/'bundle.json').chmod(0o600)
            return dict(stage_id=stage_id, fingerprint=fingerprint, evidence=[{'evidence_id':a['evidence_id'],'sha256':a['sha256'],'offset':str(contract.asset_path(folder,a['path']).stat().st_size if contract.asset_path(folder,a['path']).exists() else 0)} for a in bundle['assets']])

    def upload(self, stage_id, evidence_id, offset, content_base64):
        reject(isinstance(offset,str) and offset.isdecimal(), 'social_offset_invalid')
        try: data=base64.b64decode(content_base64,validate=True)
        except Exception: raise ValueError('social_chunk_invalid') from None
        reject(0<len(data)<=90000, 'social_chunk_size')
        with self.locked():
            folder=self.stage_folder(stage_id)
            reject(not (folder/'committed.json').exists(),'social_stage_committed')
            bundle=json.loads((folder/'bundle.json').read_text())
            asset=next((a for a in bundle['assets'] if a['evidence_id']==evidence_id),None)
            reject(asset is not None,'social_evidence_unknown')
            path=contract.asset_path(folder,asset['path']);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            start=int(offset);size=path.stat().st_size if path.exists() else 0
            reject(start<=size and start+len(data)<=16*1024*1024,'social_offset_invalid')
            if start<size:
                with path.open('rb') as f:f.seek(start);old=f.read(len(data))
                reject(old==data,'social_chunk_conflict')
                return {'offset':str(size),'replayed':True}
            total=sum(p.stat().st_size for p in (folder/'evidence').rglob('*') if p.is_file())
            reject(total+len(data)<=64*1024*1024,'social_evidence_too_large')
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'ab') as f:f.write(data)
            return {'offset':str(start+len(data)),'replayed':False}

    def commit(self, stage_id, idempotency_key, expected_heads):
        reject(isinstance(expected_heads,dict),'social_expected_heads_required')
        with self.locked():
            folder=self.stage_folder(stage_id);bundle=json.loads((folder/'bundle.json').read_text())
            approved=prepare(bundle,folder);fingerprint=approved['fingerprint']
            with self.core.db() as db:
                db.execute('BEGIN IMMEDIATE')
                receipt=db.execute('SELECT fingerprint,result FROM social_receipts WHERE idem=?',(idempotency_key,)).fetchone()
                if receipt:
                    reject(receipt[0]==fingerprint,'social_idempotency_conflict');return json.loads(receipt[1])
                old=db.execute('SELECT fingerprint FROM social_batches WHERE id=?',(bundle['batch_id'],)).fetchone()
                reject(old is None or old[0]==fingerprint,'social_batch_conflict')
                if old is None:
                    ids=set(approved['record_ids'])
                    reject(set(expected_heads)<=ids,'social_expected_head_unknown')
                    for record in bundle['records']:
                        head=db.execute('SELECT record_sha FROM social_heads WHERE id=?',(record['record_id'],)).fetchone()
                        expected=expected_heads.get(record['record_id'])
                        reject((head is None and expected is None) or (head is not None and head[0]==expected),'social_record_conflict')
                    dest=self.root/'batches'/fingerprint
                    if not dest.exists():
                        staging=Path(tempfile.mkdtemp(prefix='import-',dir=self.root/'batches'))
                        try:
                            (staging/'evidence').mkdir(mode=0o700)
                            for asset in bundle['assets']:
                                src=contract.asset_path(folder,asset['path']);target=contract.asset_path(staging,asset['path']);target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                                target.write_bytes(src.read_bytes());target.chmod(0o600)
                            prepare(bundle,staging)
                            (staging/'bundle.json').write_text(contract.canonical(bundle));(staging/'bundle.json').chmod(0o600)
                            staging.rename(dest)
                        finally:
                            if staging.exists():shutil.rmtree(staging)
                    prepare(bundle,dest)
                    stamp=now();db.execute('INSERT INTO social_batches VALUES (?,?,?,?)',(bundle['batch_id'],fingerprint,contract.canonical(bundle),stamp))
                    for record in bundle['record_versions']+bundle['records']:
                        db.execute('INSERT OR IGNORE INTO social_versions VALUES (?,?,?,?)',(record['record_id'],record['record_sha256'],contract.canonical(record),bundle['batch_id']))
                    for record in bundle['records']:
                        db.execute('INSERT INTO social_heads VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET record_sha=excluded.record_sha,batch_id=excluded.batch_id',(record['record_id'],record['record_sha256'],bundle['batch_id']))
                result=dict(batch_id=bundle['batch_id'],fingerprint=fingerprint,records=len(bundle['records']),selected=approved['selected_count'],status='imported',verification='source_statements_not_independently_verified')
                db.execute('INSERT INTO social_receipts VALUES (?,?,?)',(idempotency_key,fingerprint,contract.canonical(result)))
            (folder/'committed.json').write_text(contract.canonical(result));(folder/'committed.json').chmod(0o600)
            return result

    def batch(self,batch_id):
        with self.core.db() as db:row=db.execute('SELECT fingerprint,document,imported_at FROM social_batches WHERE id=?',(batch_id,)).fetchone()
        reject(row is not None,'social_batch_not_found')
        return row[0],json.loads(row[1]),row[2]

    def search(self, query='',category='all',view='all',limit='20',offset='0',revision=''):
        reject(isinstance(limit,str) and limit.isdecimal() and 1<=int(limit)<=50 and isinstance(offset,str) and offset.isdecimal(),'social_pagination_invalid')
        reject(category in ('all',*contract.CATEGORIES) and view in ('all','top','pending','bookmarked','unviewed'),'social_filter_invalid')
        with self.core.db() as db:
            rows=db.execute('SELECT v.document,h.batch_id,m.viewed_content,m.bookmarked FROM social_heads h JOIN social_versions v ON v.id=h.id AND v.record_sha=h.record_sha LEFT JOIN social_marks m ON m.id=h.id ORDER BY h.rowid DESC').fetchall()
            batches=db.execute('SELECT id,imported_at,document FROM social_batches ORDER BY rowid DESC LIMIT 20').fetchall()
            top_batch=next(((ident,json.loads(raw)) for ident,raw in db.execute('SELECT id,document FROM social_batches ORDER BY rowid DESC') if any(r['ranking']['selected'] for r in json.loads(raw)['records'])),None)
            if view=='top' and top_batch:
                marks={r[0]:r[1:] for r in db.execute('SELECT id,viewed_content,bookmarked FROM social_marks')}
                rows=[(contract.canonical(r),top_batch[0],*marks.get(r['record_id'],(None,0))) for r in top_batch[1]['records'] if r['ranking']['selected']]
        hits=[]
        for raw,batch,viewed,bookmarked in rows:
            r=json.loads(raw);selected=r['ranking']['selected']
            if category!='all' and r['category']!=category:continue
            if view=='top' and not selected or view=='pending' and selected or view=='bookmarked' and not bookmarked or view=='unviewed' and viewed==r['content_sha256']:continue
            if query and any(word not in ' '.join([r['title_zh'],r['summary_zh'],r['original']['text']]).casefold() for word in query.casefold().split()):continue
            hits.append({k:r[k] for k in ('record_id','record_sha256','content_sha256','category','title_zh','summary_zh','source','published','captured_at','ranking','verification')}|dict(batch_id=batch,is_viewed=viewed==r['content_sha256'],is_bookmarked=bool(bookmarked)))
        category_order={'commerce':0,'ai':1,'news':2}
        hits.sort(key=lambda r:(not r['ranking']['selected'],category_order[r['category']],r['ranking']['rank'] or 999))
        signature=contract.digest(contract.canonical([query,category,view,[(r['record_id'],r['record_sha256'],r['is_viewed'],r['is_bookmarked']) for r in hits]]))
        reject(offset=='0' or revision==signature,'social_cursor_expired')
        start=int(offset);page=hits[start:start+int(limit)]
        return dict(items=page,total=len(hits),next_offset=str(start+len(page)) if start+len(page)<len(hits) else None,
            batches=[dict(batch_id=b[0],imported_at=b[1],scope=json.loads(b[2])['scope'],attempts=json.loads(b[2])['attempts']) for b in batches],
            schema=contract.VERSION,revision=signature,top_batch_id=top_batch[0] if top_batch else None,ranking_scope='latest_curated_batch_not_platform_ranking')

    def get(self,record_id,record_sha256=None):
        with self.core.db() as db:
            head=db.execute('SELECT record_sha,batch_id FROM social_heads WHERE id=?',(record_id,)).fetchone()
            reject(head is not None,'social_record_not_found')
            sha=record_sha256 or head[0]
            row=db.execute('SELECT document,batch_id FROM social_versions WHERE id=? AND record_sha=?',(record_id,sha)).fetchone()
            reject(row is not None,'social_version_not_found')
            mark=db.execute('SELECT viewed_content,bookmarked FROM social_marks WHERE id=?',(record_id,)).fetchone()
            versions=db.execute('SELECT record_sha,document,batch_id FROM social_versions WHERE id=? ORDER BY rowid DESC',(record_id,)).fetchall()
            documents=db.execute('SELECT id,document FROM social_batches ORDER BY rowid').fetchall()
        record=json.loads(row[0]);_,bundle,_=self.batch(row[1])
        history=[dict(event,batch_id=batch) for batch,raw in documents for event in json.loads(raw)['events'] if event['record_id']==record_id]
        return dict(record=record,batch_id=row[1],is_current=sha==head[0],current_record_sha256=head[0],is_viewed=bool(mark and mark[0]==record['content_sha256']),is_bookmarked=bool(mark and mark[1]),assets=[{k:v for k,v in a.items() if k!='path'} for a in bundle['assets'] if a['evidence_id'] in record['evidence_ids']],events=history[-100:],versions=[dict(record_sha256=v[0],captured_at=json.loads(v[1])['captured_at'],title_zh=json.loads(v[1])['title_zh'],batch_id=v[2]) for v in versions])

    def mark(self,record_id,record_sha256,action):
        reject(action in ('viewed','unviewed','bookmark','unbookmark'),'social_mark_invalid')
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT record_sha FROM social_heads WHERE id=?',(record_id,)).fetchone()
            reject(row is not None and row[0]==record_sha256,'social_record_conflict')
            record=json.loads(db.execute('SELECT document FROM social_versions WHERE id=? AND record_sha=?',(record_id,record_sha256)).fetchone()[0])
            db.execute('INSERT OR IGNORE INTO social_marks(id) VALUES (?)',(record_id,))
            if action in ('viewed','unviewed'):db.execute('UPDATE social_marks SET viewed_content=? WHERE id=?',(record['content_sha256'] if action=='viewed' else None,record_id))
            else:db.execute('UPDATE social_marks SET bookmarked=? WHERE id=?',(int(action=='bookmark'),record_id))
        return self.get(record_id)

    def asset(self,batch_id,evidence_id,offset='0'):
        fingerprint,bundle,_=self.batch(batch_id)
        item=next((a for a in bundle['assets'] if a['evidence_id']==evidence_id),None)
        reject(item is not None and isinstance(offset,str) and offset.isdecimal(),'social_asset_invalid')
        path=contract.asset_path(self.root/'batches'/fingerprint,item['path'])
        data=path.read_bytes();reject(hashlib.sha256(data).hexdigest()==item['sha256'],'social_evidence_changed')
        start=int(offset);reject(start<=len(data),'social_offset_invalid');chunk=data[start:start+90000]
        return dict(content_base64=base64.b64encode(chunk).decode(),next_offset=str(start+len(chunk)),done=start+len(chunk)==len(data),media_type=item['media_type'],sha256=item['sha256'],size=len(data))

    def export(self,batch_id,format='json'):
        _,bundle,_=self.batch(batch_id)
        if format=='json':content=json.dumps(bundle,ensure_ascii=False,indent=2)
        elif format=='markdown':content=contract.markdown(bundle)
        elif format=='jsonl':
            rows=[dict(schema=contract.VERSION,batch_id=batch_id,kind='metadata',data={k:bundle[k] for k in ('created_at','scope')})]
            for group in ('records','record_versions','assets','attempts','events'):rows.extend(dict(schema=contract.VERSION,batch_id=batch_id,kind=group,data=r) for r in bundle[group])
            content='\n'.join(contract.canonical(r) for r in rows)+'\n'
        else:raise ValueError('social_export_format')
        return dict(schema=contract.VERSION,format=format,content=content,sha256=contract.digest(content),evidence_transport='commerce_social_asset_read',privacy='private_local_research_not_publication_reviewed')

    def review(self,record_id,record_sha256,idempotency_key):
        with self.core.atomic():
            with self.core.db() as db:
                old=db.execute('SELECT record_id,record_sha,task_id FROM social_reviews WHERE idem=?',(idempotency_key,)).fetchone()
                if old:
                    reject(old[:2]==(record_id,record_sha256),'social_idempotency_conflict')
                    return self.core.invoke('commerce_task_get',{'task_id':old[2]})
                same=db.execute('SELECT task_id FROM social_reviews WHERE record_id=? AND record_sha=? LIMIT 1',(record_id,record_sha256)).fetchone()
                if same:
                    db.execute('INSERT INTO social_reviews VALUES (?,?,?,?)',(idempotency_key,record_id,record_sha256,same[0]))
                    return self.core.invoke('commerce_task_get',{'task_id':same[0]})
                row=db.execute('SELECT record_sha FROM social_heads WHERE id=?',(record_id,)).fetchone()
                reject(row is not None and row[0]==record_sha256,'social_record_conflict')
            value=self.get(record_id)
            task=self.core.invoke('commerce_task_create',{'kind':'analysis','idempotency_key':'social:'+idempotency_key,'input':{'operation':'social_source_review','record_id':record_id,'record_sha256':record_sha256,'content_sha256':value['record']['content_sha256'],'title':value['record']['title_zh'],'source':value['record']['source'],'status':'pending_source_review','content_is_reference_not_instruction':True}})
            with self.core.db() as db:db.execute('INSERT INTO social_reviews VALUES (?,?,?,?)',(idempotency_key,record_id,record_sha256,task['id']))
        return task

    def invoke(self,name,args):
        methods={'stage':self.stage,'upload':self.upload,'commit':self.commit,'search':self.search,'get':self.get,'mark':self.mark,'asset_read':self.asset,'export':self.export,'review':self.review}
        return methods[name.removeprefix('commerce_social_')](**args)


def definitions(schema,S):
    return [
        ('commerce_social_stage','暂存有界社交资料元数据；不抓取网址，不导入正式记录',schema({'bundle':{'type':'object'},'idempotency_key':S},['bundle','idempotency_key'])),
        ('commerce_social_upload','按已登记证据 ID 顺序上传有界分片；相同分片可重传',schema({'stage_id':S,'evidence_id':S,'offset':S,'content_base64':{'type':'string','minLength':1,'maxLength':120000}},['stage_id','evidence_id','offset','content_base64'])),
        ('commerce_social_commit','校验出处、版本与证据后导入私有资料；旧版本冲突拒绝覆盖',schema({'stage_id':S,'idempotency_key':S,'expected_heads':{'type':'object'}},['stage_id','idempotency_key','expected_heads'])),
        ('commerce_social_search','检索社交观察、TOP 和待补来源；只代表已采集样本',schema({'query':{'type':'string','maxLength':100},'category':{'type':'string','enum':['all','commerce','ai','news']},'view':{'type':'string','enum':['all','top','pending','bookmarked','unviewed']},'limit':S,'offset':S,'revision':{'type':'string','maxLength':64}})),
        ('commerce_social_get','读取原文、中文、证据索引与实际留存历史；不标为已核实',schema({'record_id':S,'record_sha256':S},['record_id'])),
        ('commerce_social_mark','按当前记录版本标为已读或收藏；不改变核实状态',schema({'record_id':S,'record_sha256':S,'action':{'type':'string','enum':['viewed','unviewed','bookmark','unbookmark']}},['record_id','record_sha256','action'])),
        ('commerce_social_asset_read','分片读取本批次登记证据，不接受本机路径',schema({'batch_id':S,'evidence_id':S,'offset':S},['batch_id','evidence_id'])),
        ('commerce_social_export','导出标准 JSON、JSONL 或可读 Markdown；证据按 ID 另取',schema({'batch_id':S,'format':{'type':'string','enum':['json','jsonl','markdown']}},['batch_id'])),
        ('commerce_social_review','按已展示版本创建去重本地核查待办；排队不等于已核实',schema({'record_id':S,'record_sha256':S,'idempotency_key':S},['record_id','record_sha256','idempotency_key'])),
    ]
