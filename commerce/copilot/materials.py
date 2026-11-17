"""Explicit local attachments and exact-current-object reference snapshots.

Nothing here calls a model, fetches a URL, opens a caller-supplied path, or grants
an additional business read. A send freezes bounded text inside its transaction;
uploaded bytes stay in the existing private SQLite database.
"""
import base64
import binascii
import hashlib
from inspect import signature
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import uuid

from agent_runtime import sha
from agent_runtime.policy import canonical, project
from .reads import check, filters, menu, projection

MAX_FILE_BYTES = 64 * 1024  # Base64 plus envelope fits the existing 128 KiB HTTP limit.
MAX_BASE64 = 4 * ((MAX_FILE_BYTES + 2) // 3)
MAX_MATERIALS = 4
MAX_TEXT = 4096
MAX_TOTAL_TEXT = 8192
MAX_SAVED = 32
TEXT_TYPES = {'.txt':'text/plain', '.md':'text/markdown', '.csv':'text/csv', '.json':'application/json'}
BINARY_TYPES = {'.pdf':'application/pdf', '.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg'}
OCR = Path(__file__).resolve().parents[2] / 'bin' / 'ocr'
TRUST = dict(source_trust='untrusted_reference_data', instructions_are_untrusted_data=True,
             facts_independently_verified=False, external_execution_allowed=False)


def definitions(schema, string):
    from .material_uploads import definitions as upload_definitions
    thread = {'thread_id':string}
    selected = {**thread, 'material_id':string}
    bound = {**thread, 'context_sha256':string, 'idempotency_key':string}
    specs = [
        ('capabilities', '读取本机附件类型、文字提取能力与限制；不读取文件', {}, []),
        ('upload', '保存显式选择的有界文件字节并本机提取文字；不会发送模型或上传外部服务',
         {**bound, 'filename':{'type':'string','minLength':1,'maxLength':120}, 'mime_type':{'type':'string','enum':sorted(set(TEXT_TYPES.values()) | set(BINARY_TYPES.values()))},
          'content_base64':{'type':'string','minLength':1,'maxLength':MAX_BASE64}},
         [*bound,'filename','mime_type','content_base64']),
        ('reference', '引用当前会话绑定的当前业务对象；重读原有只读接口并冻结版本',
         {**bound, 'kind':{'type':'string','enum':['case','product','order','intel']}, 'object_id':string}, [*bound,'kind','object_id']),
        ('list', '列出本会话本地资料元信息，不返回附件字节或正文', thread, ['thread_id']),
        ('get', '读取本会话单份资料的有界提取文字及版本', selected, ['thread_id','material_id']),
        ('preview', '显式读取本会话已选图片的本机预览字节，不提交模型', selected, ['thread_id','material_id']),
        ('remove', '从可选资料中撤下指定哈希版本；保留已发送快照',
         {**selected,'expected_sha256':string}, ['thread_id','material_id','expected_sha256']),
    ]
    return [('commerce_copilot_material_'+name, description, schema(properties, required))
            for name, description, properties, required in specs]+upload_definitions(schema,string)


def _ident(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('copilot_invalid_material_id')
    return value


def _safe_name(filename, mime_type):
    if (not isinstance(filename,str) or not 1 <= len(filename) <= 120 or filename != filename.strip()
            or filename.startswith('.') or any(char in filename for char in '/\\:')
            or any(unicodedata.category(char).startswith('C') for char in filename)):
        raise ValueError('copilot_invalid_material_filename')
    extension = Path(filename).suffix.lower()
    if not isinstance(mime_type,str) or {**TEXT_TYPES, **BINARY_TYPES}.get(extension) != mime_type:
        raise ValueError('copilot_unsupported_material_type')
    return extension


def _decode(content_base64):
    if not isinstance(content_base64,str) or not 0 < len(content_base64) <= MAX_BASE64:
        raise ValueError('copilot_material_size_or_encoding')
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('copilot_material_size_or_encoding') from None
    if not 0 < len(content) <= MAX_FILE_BYTES or base64.b64encode(content).decode() != content_base64:
        raise ValueError('copilot_material_size_or_encoding')
    return content


def _text(content):
    try:text = content.decode('utf-8-sig')
    except UnicodeError:raise ValueError('copilot_material_requires_utf8') from None
    if any(ord(char) < 32 and char not in '\t\r\n' or ord(char) == 127 for char in text):
        raise ValueError('copilot_material_binary_content')
    return text


def _run(argv, output):
    try:
        with open(output, 'wb') as stream:
            os.chmod(output, 0o600)
            result = subprocess.run([str(part) for part in argv], stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.DEVNULL, timeout=8, check=False)
        if result.returncode:raise ValueError('copilot_material_extraction_failed')
        with open(output, 'rb') as stream:content=stream.read(MAX_FILE_BYTES+1)
        return content[:MAX_FILE_BYTES], len(content) > MAX_FILE_BYTES
    except subprocess.TimeoutExpired:raise ValueError('copilot_material_extraction_timeout') from None
    except OSError:raise ValueError('copilot_material_extraction_failed') from None


def _extract(content, extension):
    if extension in TEXT_TYPES:
        if content.startswith((b'%PDF-', b'\x89PNG', b'\xff\xd8\xff')):
            raise ValueError('copilot_material_binary_content')
        text = _text(content)
        if extension == '.json':
            try:json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, RecursionError):raise ValueError('copilot_invalid_material_json') from None
        return dict(text=text[:MAX_TEXT], text_characters=len(text), text_truncated=len(text)>MAX_TEXT,
                    extraction='utf8', extraction_status='completed' if text.strip() else 'no_text', visual_understanding=False)
    pdf = extension == '.pdf'
    tool = shutil.which('pdftotext') if pdf else shutil.which('sips')
    if not tool or not pdf and not (OCR.is_file() and os.access(OCR, os.X_OK)):
        raise ValueError('copilot_material_extraction_unavailable')
    if pdf and not content.startswith(b'%PDF-') or extension == '.png' and not content.startswith(b'\x89PNG\r\n\x1a\n') or extension in ('.jpg','.jpeg') and not content.startswith(b'\xff\xd8\xff'):
        raise ValueError('copilot_material_content_mismatch')
    with tempfile.TemporaryDirectory(prefix='copilot-material-') as folder:
        path=Path(folder)/('selected'+extension);path.write_bytes(content);path.chmod(0o600)
        output=Path(folder)/'extract.txt'
        if pdf:
            raw, clipped = _run([tool,'-f','1','-l','20','-layout','-nopgbrk','-enc','UTF-8','-q',path,'-'],output)
            # Poppler can split a UTF-8 sequence at the output byte budget.
            text=raw.decode('utf-8',errors='ignore');method='pdf_text_first_20_pages'
        else:
            dimensions,_=_run([tool,'-g','pixelWidth','-g','pixelHeight',path],output)
            sizes=re.findall(rb'pixel(?:Width|Height):\s*(\d+)', dimensions)
            if len(sizes)!=2 or any(not 0 < int(size) <= 8192 for size in sizes) or int(sizes[0])*int(sizes[1]) > 16000000:
                raise ValueError('copilot_material_invalid_image')
            raw,clipped=_run([OCR,path],output)
            lines=[]
            for line in raw.decode('utf-8',errors='replace').splitlines():
                parts=line.split('\t',5)
                if len(parts)!=6:raise ValueError('copilot_material_extraction_failed')
                try:values=[float(part) for part in parts[:5]]
                except ValueError:raise ValueError('copilot_material_extraction_failed') from None
                if not all(math.isfinite(value) for value in values) or not 0 <= values[4] <= 1:
                    raise ValueError('copilot_material_extraction_failed')
                lines.append(parts[5])
            text='\n'.join(lines);method='image_text_ocr'
    # Binary extraction is explicitly a partial text view, never image semantics
    # or a claim that all pages of a document were read.
    return dict(text=text[:MAX_TEXT],text_characters=None if clipped else len(text),
                text_truncated=clipped or len(text)>MAX_TEXT, extraction=method,
                extraction_status='completed' if text.strip() else 'no_text',
                extraction_partial=True, visual_understanding=False)


def _attachment(content,filename,mime_type):
    extension=_safe_name(filename,mime_type);digest=hashlib.sha256(content).hexdigest()
    extracted=_extract(content,extension);text=extracted.pop('text')
    metadata=dict(kind='attachment',filename=filename,mime_type=mime_type,size_bytes=len(content),sha256=digest,
                  source_sha256=digest,version=digest,model_usable=bool(text.strip()),**extracted)
    return metadata,text


class CopilotMaterials:
    def __init__(self, copilot):
        self.copilot=copilot;self.service=copilot.service;self.core=copilot.core
        with self.core.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS copilot_materials (
                id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, context_sha TEXT NOT NULL,
                context_revision INTEGER NOT NULL, idem TEXT NOT NULL, request_sha TEXT NOT NULL,
                metadata TEXT NOT NULL, text TEXT NOT NULL, content BLOB, removed INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL, UNIQUE(thread_id,idem))''')
            db.execute('CREATE INDEX IF NOT EXISTS copilot_material_thread ON copilot_materials(thread_id,created)')
        from .material_uploads import MaterialUploads
        self.uploads=MaterialUploads(self)

    def invoke(self, name, args):
        prefix='commerce_copilot_material_'
        methods={key:getattr(self,key) for key in ('capabilities','preflight','upload','reference','list','get','preview','remove')}
        methods.update({key:getattr(self.uploads,key)for key in ('upload_begin','upload_chunk','upload_finish','upload_cancel')})
        fn=methods.get(name.removeprefix(prefix)) if isinstance(name,str) and name.startswith(prefix) else None
        if fn is None:raise ValueError('unknown_tool')
        if not isinstance(args,dict):raise ValueError('copilot_invalid_arguments')
        try:signature(fn).bind(**args)
        except TypeError:raise ValueError('copilot_invalid_arguments') from None
        return fn(**args)

    def capabilities(self):
        from .material_uploads import MAX_UPLOAD_BYTES,CHUNK_BYTES,EXPIRES_SECONDS
        pdf=bool(shutil.which('pdftotext'));image=bool(shutil.which('sips') and OCR.is_file() and os.access(OCR,os.X_OK))
        return dict(max_file_bytes=MAX_FILE_BYTES,max_chunked_file_bytes=MAX_UPLOAD_BYTES,chunk_bytes=CHUNK_BYTES,upload_expires_seconds=EXPIRES_SECONDS,chunked_upload_available=True,max_selected=MAX_MATERIALS,max_text_characters=MAX_TEXT,
                    max_total_text_characters=MAX_TOTAL_TEXT,max_saved_per_thread=MAX_SAVED,text_mime_types=list(TEXT_TYPES.values()),
                    pdf_text_available=pdf,pdf_page_limit=20,image_ocr_available=image,
                    supported_mime_types=list(TEXT_TYPES.values())+(['application/pdf'] if pdf else [])+(['image/png','image/jpeg'] if image else []),
                    image_capability='图片文字' if image else 'unavailable',visual_understanding=False,
                    local_only=True,**TRUST)

    def preflight(self,filename,mime_type,size_bytes):
        from .material_uploads import MAX_UPLOAD_BYTES
        extension=_safe_name(filename,mime_type)
        if type(size_bytes)is not int or not 0<size_bytes<=MAX_UPLOAD_BYTES:raise ValueError('copilot_material_size_or_encoding')
        caps=self.capabilities()
        if mime_type not in caps['supported_mime_types']:raise ValueError('copilot_material_extraction_unavailable')
        return dict(allowed=True,filename=filename,mime_type=mime_type,size_bytes=size_bytes,
                    transfer='single'if size_bytes<=MAX_FILE_BYTES else'chunked',max_text_characters=MAX_TEXT,
                    extraction='utf8'if extension in TEXT_TYPES else'pdf_text_first_20_pages'if extension=='.pdf'else'image_text_ocr',
                    extraction_partial=extension in BINARY_TYPES,pdf_page_limit=20 if extension=='.pdf'else None,
                    local_only=True,visual_understanding=False,**TRUST)

    def _bound(self, db, thread_id, context_sha256):
        thread=self.copilot._thread(db,_ident(thread_id))
        if context_sha256 != thread['context_sha256']:raise ValueError('copilot_context_changed')
        return thread

    def _row(self, db, thread, material_id, *, include_content=False):
        blob='content' if include_content else 'NULL'
        row=db.execute('SELECT metadata,text,'+blob+',context_sha,context_revision,removed FROM copilot_materials WHERE id=? AND thread_id=?',(_ident(material_id),thread['id'])).fetchone()
        if not row or row[5]:raise ValueError('copilot_material_not_found')
        metadata=json.loads(row[0]);metadata['stale']=(row[3],row[4]) != (thread['context_sha256'],thread['revision'])
        return metadata,row[1],row[2]

    def metadata(self, db, thread):
        rows=db.execute('SELECT id FROM copilot_materials WHERE thread_id=? AND removed=0 ORDER BY created DESC,id LIMIT ?',(thread['id'],MAX_SAVED)).fetchall()
        return [self._row(db,thread,row[0])[0] for row in rows]

    def list(self, thread_id):
        with self.core.db() as db:
            thread=self.copilot._thread(db,_ident(thread_id))
            return {'items':self.metadata(db,thread),'context_sha256':thread['context_sha256'],'max_selected':MAX_MATERIALS}

    def get(self, thread_id, material_id):
        with self.core.db() as db:
            thread=self.copilot._thread(db,_ident(thread_id));metadata,text,_=self._row(db,thread,material_id)
            return {**metadata,'text':text}

    def preview(self, thread_id, material_id):
        with self.core.db() as db:
            thread=self.copilot._thread(db,_ident(thread_id));metadata,_,content=self._row(db,thread,material_id,include_content=True)
            if metadata['stale']:raise ValueError('copilot_material_scope_changed')
            if metadata.get('mime_type') not in ('image/png','image/jpeg'):raise ValueError('copilot_material_preview_unavailable')
            if not content or hashlib.sha256(content).hexdigest()!=metadata['sha256']:raise ValueError('copilot_material_changed')
            return {'id':material_id,'mime_type':metadata['mime_type'],'sha256':metadata['sha256'],'content_base64':base64.b64encode(content).decode()}

    def _save(self, db, thread, metadata, text, content, idempotency_key, request_sha):
        old=db.execute('SELECT id,request_sha,removed FROM copilot_materials WHERE thread_id=? AND idem=?',(thread['id'],idempotency_key)).fetchone()
        if old:
            if old[1]!=request_sha:raise ValueError('idempotency_conflict')
            if old[2]:raise ValueError('copilot_material_removed')
            previous=self._row(db,thread,old[0])[0]
            if previous['stale']:raise ValueError('copilot_material_scope_changed')
            if previous['sha256']!=metadata['sha256']:raise ValueError('copilot_reference_changed')
            return previous
        if db.execute('SELECT count(*) FROM copilot_materials WHERE thread_id=?',(thread['id'],)).fetchone()[0]>=MAX_SAVED:
            raise ValueError('copilot_material_storage_limit')
        ident=uuid.uuid4().hex;created=time.time()
        metadata.update(id=ident,thread_id=thread['id'],context_sha256=thread['context_sha256'],context_revision=thread['revision'],created=created,**TRUST)
        db.execute('INSERT INTO copilot_materials VALUES(?,?,?,?,?,?,?,?,?,0,?)',(ident,thread['id'],thread['context_sha256'],thread['revision'],idempotency_key,request_sha,canonical(metadata),text,content,created))
        return {**metadata,'stale':False}

    def upload(self, thread_id, context_sha256, filename, mime_type, content_base64, idempotency_key):
        self.copilot.key(idempotency_key);extension=_safe_name(filename,mime_type);content=_decode(content_base64)
        digest=hashlib.sha256(content).hexdigest()
        request_sha=sha(dict(filename=filename,mime_type=mime_type,sha256=digest,context_sha256=context_sha256))
        # Reject a stale target before starting any local parser.
        with self.core.db() as db:
            thread=self._bound(db,thread_id,context_sha256)
            old=db.execute('SELECT id,request_sha,removed FROM copilot_materials WHERE thread_id=? AND idem=?',(thread_id,idempotency_key)).fetchone()
            if old:
                if old[1]!=request_sha:raise ValueError('idempotency_conflict')
                if old[2]:raise ValueError('copilot_material_removed')
                previous=self._row(db,thread,old[0])[0]
                if previous['stale']:raise ValueError('copilot_material_scope_changed')
                return previous
        metadata,text=_attachment(content,filename,mime_type)
        initial_revision=thread['revision']
        with self.core.atomic(reuse=True) as db:
            thread=self._bound(db,thread_id,context_sha256)
            if thread['revision']!=initial_revision:raise ValueError('copilot_material_scope_changed')
            return self._save(db,thread,metadata,text,content,idempotency_key,request_sha)

    def _reference_source(self, thread, kind, object_id):
        context=thread['context']
        if kind not in ('case','product','order','intel') or context.get('entity')!={'kind':kind,'id':object_id}:
            raise ValueError('copilot_reference_outside_scope')
        tools={'case':'commerce_workspace_get','product':'commerce_products_list','order':'commerce_orders_list','intel':'commerce_intel_item_get'}
        name=tools[kind]
        if name not in {entry['tool'] for entry in menu(context)}:raise ValueError('copilot_reference_outside_scope')
        binding={'context':context}
        if kind in ('product','order','case'):
            from .memory_scope import resolve, _store
            selected=resolve(self.service,context)
            if kind=='case':
                if selected is None:raise ValueError('copilot_reference_outside_scope')
                binding=selected
            else:
                if type(context.get('demo')) is not bool or any(not context.get(key) or context[key]=='all' for key in ('platform','store_id','market')):
                    raise ValueError('copilot_reference_outside_scope')
                store=_store(self.service,context,allow_live=True)
                if not store:raise ValueError('copilot_reference_outside_scope')
                binding={'context':context,'store_binding':store}
        args=({'case_id':object_id} if kind=='case' else {'item_id':object_id} if kind=='intel' else filters(context))
        name,args=check(context,name,args,set())
        data=self.service.invoke(name,args,'local')
        if data.get('stale') is True:raise ValueError('copilot_reference_changed')
        if kind in ('product','order'):
            rows=data.get('products' if kind=='product' else 'orders',[])
            rows=[row for row in rows if object_id in [str(row.get(key,'')) for key in (('id','sku','stock_row_key') if kind=='product' else ('id',))]]
            if len(rows)!=1:raise ValueError('copilot_reference_outside_scope')
            row=rows[0]
            if row.get('stale') is True:raise ValueError('copilot_reference_changed')
            fields=('id','sku','stock_row_key','name','product','platform','market','amount','currency','status','available','threshold','price','scope','observed_at','source_sha256','stale','data_source')
            view={key:row[key] for key in fields if key in row}
            source=row.get('source_sha256') or sha(view)
        else:
            view=projection(name,data) if kind=='case' else project(name,data)
            source=data.get('source_sha256' if kind=='case' else 'record_sha256')
            if not isinstance(source,str) or not re.fullmatch('[a-f0-9]{64}',source):raise ValueError('copilot_reference_changed')
        fingerprint=sha({'view':view,'binding':binding,'source_sha256':source})
        raw=canonical(view)
        return dict(kind='reference',object={'kind':kind,'id':object_id},sha256=fingerprint,source_sha256=source,
                    version=source,scope_binding_sha256=sha(binding),size_bytes=len(raw.encode()),text_characters=len(raw),
                    text_truncated=len(raw)>MAX_TEXT,extraction='scoped_business_read',extraction_status='completed',model_usable=True,
                    visual_understanding=False),raw[:MAX_TEXT]

    def reference(self, thread_id, context_sha256, kind, object_id, idempotency_key):
        self.copilot.key(idempotency_key)
        with self.core.atomic(reuse=True) as db:
            thread=self._bound(db,thread_id,context_sha256)
            metadata,text=self._reference_source(thread,kind,object_id)
            request_sha=sha(dict(kind=kind,object_id=object_id,context_sha256=context_sha256))
            return self._save(db,thread,metadata,text,None,idempotency_key,request_sha)

    def remove(self, thread_id, material_id, expected_sha256):
        with self.core.atomic(reuse=True) as db:
            thread=self.copilot._thread(db,_ident(thread_id));metadata,_,_=self._row(db,thread,material_id)
            if expected_sha256!=metadata['sha256']:raise ValueError('copilot_material_changed')
            db.execute('UPDATE copilot_materials SET removed=1 WHERE id=? AND thread_id=?',(material_id,thread_id))
            return {'id':material_id,'removed':True,'sha256':metadata['sha256']}

    def resolve_for_send(self, db, thread, material_ids):
        """Freeze inside Core.atomic(), shared with the human turn/run transaction."""
        if not isinstance(material_ids,list) or len(material_ids)>MAX_MATERIALS:
            raise ValueError('copilot_invalid_material_selection')
        for ident in material_ids:_ident(ident)
        if len(set(material_ids))!=len(material_ids):raise ValueError('copilot_invalid_material_selection')
        result=dict(items=[],text_truncated=False,**TRUST);remaining=MAX_TOTAL_TEXT
        for ident in material_ids:
            metadata,text,content=self._row(db,thread,ident,include_content=True)
            if metadata['stale']:raise ValueError('copilot_material_scope_changed')
            if metadata['kind']=='attachment':
                if content is None or hashlib.sha256(content).hexdigest()!=metadata['sha256']:raise ValueError('copilot_material_changed')
            else:
                try:current,current_text=self._reference_source(thread,metadata['object']['kind'],metadata['object']['id'])
                except ValueError:raise ValueError('copilot_reference_changed') from None
                if current['sha256']!=metadata['sha256'] or current_text!=text:raise ValueError('copilot_reference_changed')
            selected={**metadata,'text':text[:remaining]}
            selected['text_truncated']=metadata['text_truncated'] or len(text)>remaining
            selected['model_usable']=bool(selected['text'].strip())
            remaining-=len(selected['text']);result['items'].append(selected)
            result['text_truncated']=result['text_truncated'] or selected['text_truncated']
        result['sha256']=sha(result)
        return result
