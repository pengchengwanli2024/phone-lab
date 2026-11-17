"""Private, bounded source-image uploads. Raw bytes and origin are preserved."""
import base64, hashlib, json, math, os, re, threading, uuid
from pathlib import Path
from research import canonical, digest
from product_evidence import text, url
CHUNK=48*1024
MAX_IMAGE=5*1024*1024
_slots=threading.BoundedSemaphore(3)

def definitions(schema,string):
    case={'case_id':string};source={**case,'entry_id':string,'expected_entry_sha256':string}
    return [
      ('commerce_product_evidence_upload_begin','开始同商品同来源原图上传；保留原始文件，不认定商用权或实物身份',schema({**source,'filename':string,'size':{'type':'integer','minimum':1,'maximum':MAX_IMAGE},'sha256':string,'source_url':{'type':'string','maxLength':2000},'role':{'type':'string','enum':['original','generated','document']},'actor':string},[*source,'filename','size','sha256','source_url','role','actor'])),
      ('commerce_product_evidence_upload_chunk','上传一个有序私有图片分片；相同分片重传不重复写入',schema({**case,'upload_id':string,'index':{'type':'integer','minimum':0},'content_base64':{'type':'string','maxLength':66000}},[*case,'upload_id','index','content_base64'])),
      ('commerce_product_evidence_upload_finish','核对图片格式和哈希，生成来源新版本；不覆盖旧原图，不批准发布',schema({**case,'upload_id':string},[*case,'upload_id'])),
      ('commerce_product_evidence_image','按来源版本分片读取已登记原图；不携带平台凭据',schema({**source,'index':{'type':'integer','minimum':0,'maximum':11},'offset':{'type':'integer','minimum':0}},[*source,'index'])),
      ('commerce_product_evidence_image_capture','读取所选来源已登记的公开HTTPS图片并保存原图版本；不登录、不采购、不跟随跳转',schema({**source,'index':{'type':'integer','minimum':0,'maximum':11},'actor':string},[*source,'index','actor'])),
    ]

def mime(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png','.png'
    if raw.startswith(b'\xff\xd8\xff'):return 'image/jpeg','.jpg'
    if raw.startswith(b'RIFF')and raw[8:12]==b'WEBP':return 'image/webp','.webp'
    raise ValueError('evidence_image_format_unsupported')

class EvidenceMedia:
    def __init__(self,dossier):
        self.dossier=dossier;self.service=dossier.service;self.core=dossier.core
        self.root=self.service.state/'product-evidence-media'
        if self.root.is_symlink():raise ValueError('evidence_image_unsafe_storage')
        self.root.mkdir(mode=0o700,exist_ok=True)
        with self.core.db()as db:
            db.execute('CREATE TABLE IF NOT EXISTS product_evidence_uploads(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,spec TEXT NOT NULL,next_index INTEGER NOT NULL,received INTEGER NOT NULL,result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS product_evidence_images(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,entry_id TEXT NOT NULL,document TEXT NOT NULL)')
    def source(self,case_id,entry_id,expected,allow_history=False):
        versions=self.dossier._versions(case_id).get(entry_id)
        if not versions:raise ValueError('evidence_source_not_found')
        if allow_history:
            found=next((r for r in versions if r['sha256']==expected),None)
            if not found:raise ValueError('evidence_source_changed')
            versions=[found]
        source=self.dossier._view(versions)
        if source['sha256']!=expected:raise ValueError('evidence_source_changed')
        return source
    def asset(self,case_id,entry_id,media_id):
        self.dossier.case(case_id)
        if not isinstance(media_id,str)or not re.fullmatch('peimg_[a-f0-9]{32}',media_id):raise ValueError('evidence_image_not_found')
        with self.core.db()as db:row=db.execute('SELECT document FROM product_evidence_images WHERE id=? AND case_id=? AND entry_id=?',(media_id,case_id,entry_id)).fetchone()
        if not row:raise ValueError('evidence_image_reference_outside_scope')
        doc=json.loads(row[0])
        if doc['document_sha256']!=digest(canonical({k:v for k,v in doc.items()if k!='document_sha256'})):raise ValueError('evidence_image_changed')
        path=self.root/doc['filename']
        if path.is_symlink()or not path.is_file()or hashlib.sha256(path.read_bytes()).hexdigest()!=doc['sha256']:raise ValueError('evidence_image_changed')
        return path,doc
    def upload_begin(self,case_id,entry_id,expected_entry_sha256,filename,size,sha256,source_url,role,actor):
        self.dossier.case(case_id)
        if type(size)is not int or not 0<size<=MAX_IMAGE or not re.fullmatch('[a-f0-9]{64}',sha256):raise ValueError('evidence_invalid_image_upload')
        filename=text(filename,200,True)
        if Path(filename).name!=filename or any(c in filename for c in '/\\\0'):raise ValueError('evidence_invalid_image_upload')
        source_url=url(source_url,optional=True);actor=text(actor,120,True)
        if role not in ('original','generated','document'):raise ValueError('evidence_invalid_image_role')
        spec=canonical(dict(entry_id=entry_id,entry_sha256=expected_entry_sha256,filename=filename,size=size,sha256=sha256,source_url=source_url,role=role,actor=actor))
        with self.core.atomic()as db:
            self.source(case_id,entry_id,expected_entry_sha256)
            old=db.execute('SELECT id,next_index,result FROM product_evidence_uploads WHERE case_id=? AND spec=?',(case_id,spec)).fetchone()
            if old:return {'upload_id':old[0],'next_index':old[1],'chunk_bytes':CHUNK,'result':json.loads(old[2])if old[2]else None}
            reserved=db.execute('SELECT spec FROM product_evidence_uploads WHERE case_id=?',(case_id,)).fetchall()
            if len(reserved)>=256 or sum(json.loads(r[0])['size']for r in reserved)+size>256*1024*1024:raise ValueError('evidence_image_capacity_reached')
            ident='peup_'+uuid.uuid4().hex
            db.execute('INSERT INTO product_evidence_uploads VALUES(?,?,?,?,?,NULL)',(ident,case_id,spec,0,0))
            return {'upload_id':ident,'next_index':0,'chunk_bytes':CHUNK,'result':None}
    def _upload(self,db,case_id,upload_id):
        self.dossier.case(case_id)
        if not re.fullmatch('peup_[a-f0-9]{32}',upload_id):raise ValueError('evidence_upload_not_found')
        row=db.execute('SELECT spec,next_index,received,result FROM product_evidence_uploads WHERE id=? AND case_id=?',(upload_id,case_id)).fetchone()
        if not row:raise ValueError('evidence_upload_not_found')
        return row,json.loads(row[0]),self.root/(upload_id+'.part')
    def upload_chunk(self,case_id,upload_id,index,content_base64):
        try:raw=base64.b64decode(content_base64,validate=True)
        except (ValueError,TypeError):raise ValueError('evidence_invalid_image_chunk')from None
        if type(index)is not int or index<0 or not 0<len(raw)<=CHUNK:raise ValueError('evidence_invalid_image_chunk')
        with self.core.atomic()as db:
            row,spec,path=self._upload(db,case_id,upload_id)
            if row[3]:raise ValueError('evidence_upload_closed')
            if path.is_symlink():raise ValueError('evidence_image_unsafe_storage')
            if index<row[1]:
                expected=min(CHUNK,spec['size']-index*CHUNK)
                with path.open('rb')as f:f.seek(index*CHUNK);previous=f.read(expected)
                if previous!=raw:raise ValueError('evidence_image_chunk_conflict')
                return {'next_index':row[1],'duplicate':True}
            if index!=row[1]or len(raw)!=min(CHUNK,spec['size']-row[2]):raise ValueError('evidence_image_chunk_out_of_order')
            with path.open('r+b'if path.exists()else'w+b')as f:
                f.truncate(row[2]);f.seek(row[2]);f.write(raw);f.flush();os.fsync(f.fileno())
            path.chmod(0o600)
            db.execute('UPDATE product_evidence_uploads SET next_index=?,received=? WHERE id=?',(index+1,row[2]+len(raw),upload_id))
            return {'next_index':index+1,'duplicate':False}
    def upload_finish(self,case_id,upload_id):
        with self.core.atomic()as db:
            row,spec,path=self._upload(db,case_id,upload_id)
            if row[3]:return {**json.loads(row[3]),'reused':True}
            source=self.source(case_id,spec['entry_id'],spec['entry_sha256'])
            if row[2]!=spec['size']or path.is_symlink()or not path.is_file():raise ValueError('evidence_image_incomplete')
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=spec['sha256']:raise ValueError('evidence_image_hash_mismatch')
            content_type,suffix=mime(raw)
            media=self.service.creative.probe(path)
            if media['width']<=0 or media['height']<=0 or media.get('duration_seconds',0)>0:raise ValueError('evidence_image_required')
            asset='peimg_'+uuid.uuid4().hex;filename=asset+suffix
            replacement=next((n for n,r in enumerate(source['images'])if spec['source_url']and r['url']==spec['source_url']and not r['media_id']and r['role']==spec['role']),None)
            if replacement is None and len(source['images'])>=12:raise ValueError('evidence_invalid_images')
            doc={'id':asset,'case_id':case_id,'entry_id':spec['entry_id'],'filename':filename,'display_name':spec['filename'],'mime':content_type,'sha256':spec['sha256'],'size':len(raw),'source_url':spec['source_url'],'role':spec['role'],'media':media,'independently_verified':False}
            doc['document_sha256']=digest(canonical(doc))
            destination=self.root/filename
            # Keep upload bytes until the DB commit succeeds; retries can finish.
            import shutil
            shutil.copyfile(path,destination);destination.chmod(0o600)
            db.execute('INSERT INTO product_evidence_images VALUES(?,?,?,?)',(asset,case_id,spec['entry_id'],canonical(doc)))
            payload={k:source[k]for k in __import__('product_evidence').SOURCE_FIELDS}
            ref={'url':spec['source_url'],'media_id':asset,'label':spec['filename'],'role':spec['role']}
            if replacement is None:payload['images']=[*payload['images'],ref]
            else:payload['images'][replacement]=ref
            self.dossier.validate_source(case_id,payload,spec['entry_id'])
            current=self.dossier._projection(case_id)['dossier_sha256']
            self.dossier._write(case_id,spec['entry_id'],payload,source['revision'],current,'image:'+upload_id,spec['actor'],{'upload_id':upload_id,'sha256':spec['sha256']})
            result={'media_id':asset,'entry_id':spec['entry_id'],'entry_revision':source['revision']+1,'sha256':spec['sha256'],'mime':content_type,'role':spec['role'],'reused':False,'external_execution_allowed':False}
            db.execute('UPDATE product_evidence_uploads SET result=? WHERE id=?',(canonical(result),upload_id))
            return result
    def image(self,case_id,entry_id,expected_entry_sha256,index,offset=0):
        source=self.source(case_id,entry_id,expected_entry_sha256,allow_history=True)
        if type(index)is not int or not 0<=index<len(source['images']):raise ValueError('evidence_image_not_found')
        ref=source['images'][index]
        if not ref['media_id']:return {'status':'not_archived','url':ref['url'],'role':ref['role'],'independently_verified':False}
        path,doc=self.asset(case_id,entry_id,ref['media_id'])
        if type(offset)is not int or offset<0 or offset%CHUNK or offset>=doc['size']:raise ValueError('evidence_invalid_image_offset')
        raw=path.read_bytes();part=raw[offset:offset+CHUNK]
        return {'status':'archived','content_base64':base64.b64encode(part).decode(),'next_offset':offset+len(part)if offset+len(part)<len(raw)else None,
            'size':len(raw),'mime':doc['mime'],'sha256':doc['sha256'],'source_url':doc['source_url'],'role':doc['role'],'independently_verified':False}
    def image_capture(self,case_id,entry_id,expected_entry_sha256,index,actor):
        source=self.source(case_id,entry_id,expected_entry_sha256)
        if type(index)is not int or not 0<=index<len(source['images']):raise ValueError('evidence_image_not_found')
        ref=source['images'][index]
        if ref['media_id']:return {'media_id':ref['media_id'],'reused':True,'external_execution_allowed':False}
        if not _slots.acquire(blocking=False):raise ValueError('evidence_image_busy')
        try:
            from catalog_media import PublicImageConnection
            from public_web_transport import addresses as image_addresses
            from urllib.parse import urlsplit
            p=urlsplit(url(ref['url']));connection=PublicImageConnection(p.hostname,image_addresses(p.hostname)[0])
            try:
                connection.request('GET',p.path+('?' +p.query if p.query else''),headers={'Accept':'image/png,image/jpeg,image/webp','User-Agent':'commerce-source-evidence/1.0'})
                response=connection.getresponse()
                if response.status!=200:raise ValueError('evidence_image_unavailable')
                raw=response.read(MAX_IMAGE+1)
                if len(raw)>MAX_IMAGE:raise ValueError('evidence_image_too_large')
                _,suffix=mime(raw)
            finally:connection.close()
            begin=self.upload_begin(case_id,entry_id,expected_entry_sha256,'source-image'+suffix,len(raw),hashlib.sha256(raw).hexdigest(),ref['url'],ref['role'],actor)
            for n in range(begin['next_index'],math.ceil(len(raw)/CHUNK)):
                self.upload_chunk(case_id,begin['upload_id'],n,base64.b64encode(raw[n*CHUNK:(n+1)*CHUNK]).decode())
            result=self.upload_finish(case_id,begin['upload_id'])
            return result
        except (OSError,TimeoutError):raise ValueError('evidence_image_unavailable')from None
        finally:_slots.release()
    def invoke(self,operation,args):
        return {'upload_begin':self.upload_begin,'upload_chunk':self.upload_chunk,'upload_finish':self.upload_finish,'image':self.image,'image_capture':self.image_capture}[operation](**args)
