"""Bounded, resumable local byte intake; completion writes the original material."""
import hashlib
import re
import time
import uuid
from agent_runtime import sha

MAX_UPLOAD_BYTES=2*1024*1024
CHUNK_BYTES=48*1024
EXPIRES_SECONDS=1800
MAX_ACTIVE_THREAD=2
MAX_ACTIVE=8
MAX_STORAGE_BYTES=64*1024*1024
COLS='id,thread_id,context_sha,context_revision,idem,request_sha,filename,mime_type,size,sha,status,material_id,received,created,updated'

def definitions(schema,string):
    bound=dict(thread_id=string,context_sha256=string)
    selected={**bound,'upload_id':string}
    file=dict(filename={'type':'string','minLength':1,'maxLength':120},mime_type=string,size_bytes={'type':'integer','minimum':1,'maximum':MAX_UPLOAD_BYTES})
    specs=[('preflight','读取显式选择文件的大小、类型和本机提取限制；不读取文件字节',file,list(file)),
           ('upload_begin','建立有界本地分片上传；不会提交模型',dict(**bound,**file,content_sha256={'type':'string','pattern':'^[a-f0-9]{64}$'},idempotency_key=string),[*bound,*file,'content_sha256','idempotency_key']),
           ('upload_chunk','按顺序保存本会话选中文件的单个分片；同片重传须完全一致',{**selected,'index':{'type':'integer','minimum':0,'maximum':42},'content_base64':{'type':'string','minLength':1,'maxLength':4*((CHUNK_BYTES+2)//3)}},[*selected,'index','content_base64']),
           ('upload_finish','核对完整文件哈希并本机提取有界文字，复用原附件账本',selected,list(selected)),
           ('upload_cancel','撤销未完成的本地上传并清除分片，不撤销已保存的资料',selected,list(selected))]
    return [('commerce_copilot_material_'+name,description,schema(properties,required))for name,description,properties,required in specs]

class MaterialUploads:
    def __init__(self,materials):
        self.materials=materials;self.core=materials.core
        with self.core.db()as db:
            db.execute('''CREATE TABLE IF NOT EXISTS copilot_material_uploads (
                id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, context_sha TEXT NOT NULL,
                context_revision INTEGER NOT NULL, idem TEXT NOT NULL, request_sha TEXT NOT NULL,
                filename TEXT NOT NULL, mime_type TEXT NOT NULL, size INTEGER NOT NULL, sha TEXT NOT NULL,
                status TEXT NOT NULL, material_id TEXT, received INTEGER NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL, UNIQUE(thread_id,idem))''')
            db.execute('''CREATE TABLE IF NOT EXISTS copilot_material_chunks (
                upload_id TEXT NOT NULL, chunk_index INTEGER NOT NULL, sha TEXT NOT NULL, content BLOB NOT NULL,
                PRIMARY KEY(upload_id,chunk_index))''')
            db.execute('CREATE INDEX IF NOT EXISTS copilot_material_upload_scope ON copilot_material_uploads(thread_id,status)')

    @staticmethod
    def _view(row):
        return dict(id=row['id'],status=row['status'],received_bytes=row['received'],size_bytes=row['size'],
                    next_index=(row['received']+CHUNK_BYTES-1)//CHUNK_BYTES,chunk_bytes=CHUNK_BYTES,
                    content_sha256=row['sha'],expires_at=row['created']+EXPIRES_SECONDS,material_id=row['material_id'],
                    local_only=True,external_execution_allowed=False)

    def _row(self,db,thread,upload_id,*,allow_expired=False):
        from .materials import _ident
        raw=db.execute('SELECT '+COLS+' FROM copilot_material_uploads WHERE id=? AND thread_id=?',(_ident(upload_id),thread['id'])).fetchone()
        if not raw:raise ValueError('copilot_upload_not_found')
        row=dict(zip(COLS.split(','),raw))
        if (row['context_sha'],row['context_revision'])!=(thread['context_sha256'],thread['revision']):raise ValueError('copilot_material_scope_changed')
        if not allow_expired and row['status']=='uploading'and time.time()>row['created']+EXPIRES_SECONDS:raise ValueError('copilot_upload_expired')
        return row

    def upload_begin(self,thread_id,context_sha256,filename,mime_type,size_bytes,content_sha256,idempotency_key):
        self.materials.copilot.key(idempotency_key)
        self.materials.preflight(filename,mime_type,size_bytes)
        if not isinstance(content_sha256,str)or not re.fullmatch('[a-f0-9]{64}',content_sha256):raise ValueError('copilot_upload_invalid_hash')
        request=sha(dict(filename=filename,mime_type=mime_type,size=size_bytes,sha=content_sha256,context_sha=context_sha256))
        with self.core.atomic(reuse=True)as db:
            thread=self.materials._bound(db,thread_id,context_sha256)
            old=db.execute('SELECT id,request_sha FROM copilot_material_uploads WHERE thread_id=? AND idem=?',(thread_id,idempotency_key)).fetchone()
            if old:
                if old[1]!=request:raise ValueError('idempotency_conflict')
                return self._view(self._row(db,thread,old[0]))
            expired=[r[0]for r in db.execute("SELECT id FROM copilot_material_uploads WHERE status='uploading' AND created<?",(time.time()-EXPIRES_SECONDS,))]
            for ident in expired:
                db.execute("UPDATE copilot_material_uploads SET status='expired' WHERE id=?",(ident,));db.execute('DELETE FROM copilot_material_chunks WHERE upload_id=?',(ident,))
            if db.execute('SELECT count(*) FROM copilot_material_uploads WHERE thread_id=?',(thread_id,)).fetchone()[0]>=128 or db.execute('SELECT count(*) FROM copilot_material_uploads').fetchone()[0]>=4096:raise ValueError('copilot_upload_storage_limit')
            if db.execute("SELECT count(*) FROM copilot_material_uploads WHERE status='uploading' AND thread_id=?",(thread_id,)).fetchone()[0]>=MAX_ACTIVE_THREAD or db.execute("SELECT count(*) FROM copilot_material_uploads WHERE status='uploading'").fetchone()[0]>=MAX_ACTIVE:raise ValueError('copilot_upload_active_limit')
            ident=uuid.uuid4().hex;now=time.time()
            db.execute('INSERT INTO copilot_material_uploads VALUES(?,?,?,?,?,?,?,?,?,?,\'uploading\',NULL,0,?,?)',(ident,thread_id,context_sha256,thread['revision'],idempotency_key,request,filename,mime_type,size_bytes,content_sha256,now,now))
            return self._view(self._row(db,thread,ident))

    def upload_chunk(self,thread_id,context_sha256,upload_id,index,content_base64):
        from .materials import _decode
        if type(index)is not int or not 0<=index<=42:raise ValueError('copilot_upload_chunk_order')
        content=_decode(content_base64)
        if len(content)>CHUNK_BYTES:raise ValueError('copilot_upload_chunk_size')
        digest=hashlib.sha256(content).hexdigest()
        with self.core.atomic(reuse=True)as db:
            thread=self.materials._bound(db,thread_id,context_sha256);row=self._row(db,thread,upload_id)
            if row['status']!='uploading':raise ValueError('copilot_upload_not_active')
            previous=db.execute('SELECT sha,content FROM copilot_material_chunks WHERE upload_id=? AND chunk_index=?',(upload_id,index)).fetchone()
            if previous:
                if previous!=(digest,content):raise ValueError('copilot_upload_chunk_conflict')
                return self._view(row)
            if index!=row['received']//CHUNK_BYTES:raise ValueError('copilot_upload_chunk_order')
            if len(content)!=min(CHUNK_BYTES,row['size']-row['received']):raise ValueError('copilot_upload_chunk_size')
            db.execute('INSERT INTO copilot_material_chunks VALUES(?,?,?,?)',(upload_id,index,digest,content))
            db.execute('UPDATE copilot_material_uploads SET received=received+?,updated=? WHERE id=?',(len(content),time.time(),upload_id))
            return self._view(self._row(db,thread,upload_id))

    def upload_finish(self,thread_id,context_sha256,upload_id):
        from .materials import _attachment
        with self.core.db()as db:
            thread=self.materials._bound(db,thread_id,context_sha256);row=self._row(db,thread,upload_id)
            if row['status']=='completed':return self.materials._row(db,thread,row['material_id'])[0]
            if row['status']!='uploading':raise ValueError('copilot_upload_not_active')
            if row['received']!=row['size']:raise ValueError('copilot_upload_incomplete')
            chunks=db.execute('SELECT chunk_index,sha,content FROM copilot_material_chunks WHERE upload_id=? ORDER BY chunk_index',(upload_id,)).fetchall()
            if any(index!=i or hashlib.sha256(content).hexdigest()!=digest for i,(index,digest,content)in enumerate(chunks)):raise ValueError('copilot_upload_hash_mismatch')
            content=b''.join(chunk[2]for chunk in chunks)
        if len(content)!=row['size']or hashlib.sha256(content).hexdigest()!=row['sha']:raise ValueError('copilot_upload_hash_mismatch')
        metadata,text=_attachment(content,row['filename'],row['mime_type'])
        request=sha(dict(filename=row['filename'],mime_type=row['mime_type'],sha256=row['sha'],context_sha256=context_sha256))
        with self.core.atomic(reuse=True)as db:
            thread=self.materials._bound(db,thread_id,context_sha256);current=self._row(db,thread,upload_id)
            if current['status']=='completed':return self.materials._row(db,thread,current['material_id'])[0]
            if current['status']!='uploading':raise ValueError('copilot_upload_not_active')
            stored=db.execute('SELECT COALESCE(sum(length(content)),0) FROM copilot_materials').fetchone()[0]
            if stored+len(content)>MAX_STORAGE_BYTES:raise ValueError('copilot_material_storage_limit')
            item=self.materials._save(db,thread,metadata,text,content,row['idem'],request)
            db.execute("UPDATE copilot_material_uploads SET status='completed',material_id=?,updated=? WHERE id=?",(item['id'],time.time(),upload_id))
            db.execute('DELETE FROM copilot_material_chunks WHERE upload_id=?',(upload_id,))
            return item

    def upload_cancel(self,thread_id,context_sha256,upload_id):
        with self.core.atomic(reuse=True)as db:
            thread=self.materials._bound(db,thread_id,context_sha256);row=self._row(db,thread,upload_id,allow_expired=True)
            if row['status']=='completed':raise ValueError('copilot_upload_already_completed')
            db.execute("UPDATE copilot_material_uploads SET status='cancelled',updated=? WHERE id=?",(time.time(),upload_id))
            db.execute('DELETE FROM copilot_material_chunks WHERE upload_id=?',(upload_id,))
            return self._view(self._row(db,thread,upload_id))
