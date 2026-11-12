"""Private, verified ZIP archival of old successful attempts only."""
from collections import defaultdict
import fcntl,hashlib,json,os
from pathlib import Path
import shutil,tempfile,time,uuid,zipfile
from research import canonical

def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

class EvidenceCapacity:
    def __init__(self,core,state,limit=200_000_000,min_age=3600,keep=2):
        self.core=core;self.state=Path(state);self.live=self.state/'collection-jobs';self.archives=self.state/'collection-archives'
        self.limit,self.min_age,self.keep=limit,min_age,keep
        if self.archives.is_symlink() or self.live.is_symlink():raise ValueError('evidence_directory_rejected')
        self.archives.mkdir(exist_ok=True,mode=0o700);self.archives.chmod(0o700)
        with core.db() as db:db.execute('CREATE TABLE IF NOT EXISTS collection_archives (id TEXT PRIMARY KEY,job_id TEXT,attempt INTEGER,status TEXT,document TEXT,UNIQUE(job_id,attempt))')

    def status(self):
        total=0;unsafe=False
        for folder in (self.live,self.archives):
            if folder.is_symlink():unsafe=True;continue
            for path in folder.rglob('*'):
                if path.is_symlink():unsafe=True
                elif path.is_file():
                    try:total+=path.stat().st_size
                    except FileNotFoundError:pass  # Concurrent verified cleanup.
        with self.core.db() as db:counts=dict(db.execute('SELECT status,count(*) FROM collection_archives GROUP BY status'))
        return {'used_bytes':total,'limit_bytes':self.limit,'warning_bytes':int(self.limit*.8),
                'status':'blocked' if unsafe or total>=self.limit else 'warning' if total>=self.limit*.8 else 'ok',
                'unsafe_symlink':unsafe,'archives':counts,'policy':{'minimum_age_seconds':self.min_age,'keep_newest_successes_per_source':self.keep,'failure_evidence_retained':True}}

    def alerts(self,status):
        active=status['status'] in ('warning','blocked')
        with self.core.db() as db:
            if active:
                ident=hashlib.sha256(b'collection-storage-warning').hexdigest()[:32]
                db.execute("INSERT INTO collection_alerts VALUES (?,?,0,'collection_storage_warning','open',?) ON CONFLICT(job_id,attempt,code) DO UPDATE SET status=CASE WHEN collection_alerts.status='resolved' THEN 'open' ELSE collection_alerts.status END",(ident,'storage',time.time()))
            else:db.execute("UPDATE collection_alerts SET status='resolved' WHERE job_id='storage' AND status IN ('open','acknowledged')")

    def eligible(self):
        with self.core.db() as db:
            jobs=[json.loads(r[0]) for r in db.execute("SELECT document FROM collection_jobs WHERE status='succeeded' ORDER BY rowid DESC")]
        seen=defaultdict(int);result=[]
        for job in jobs:
            seen[job['source']]+=1
            if seen[job['source']]<=self.keep or not job.get('finished_at') or time.time()-job['finished_at']<self.min_age:continue
            folder=self.live/job['id']/str(job['attempt'])
            if folder.is_dir():result.append((job,folder))
        return result

    def verify_path(self,path,expected_manifest=None):
        with zipfile.ZipFile(path) as archive:
            info=archive.getinfo('manifest.json')
            if info.file_size>1_000_000:raise ValueError('evidence_archive_invalid')
            raw=archive.read(info);manifest=json.loads(raw)
            digest=hashlib.sha256(raw).hexdigest()
            if expected_manifest and digest!=expected_manifest:raise ValueError('evidence_archive_invalid')
            files=manifest['files']
            if len(files)>1000 or set(archive.namelist())!=set(files)|{'manifest.json'} or len(archive.namelist())!=len(files)+1:raise ValueError('evidence_archive_invalid')
            total=0
            for name,meta in files.items():
                if name.startswith('/') or '..' in Path(name).parts or archive.getinfo(name).file_size>8*1024*1024:raise ValueError('evidence_archive_invalid')
                total+=archive.getinfo(name).file_size
                if total>200_000_000:raise ValueError('evidence_archive_invalid')
                h=hashlib.sha256()
                with archive.open(name) as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
                if h.hexdigest()!=meta['sha256'] or archive.getinfo(name).file_size!=meta['bytes']:raise ValueError('evidence_archive_invalid')
        return manifest,digest

    def archive_one(self,job,folder):
        ident=hashlib.sha256((job['id']+':'+str(job['attempt'])).encode()).hexdigest()[:32]
        target=self.archives/(ident+'.zip')
        with self.core.db() as db:old=db.execute('SELECT document FROM collection_archives WHERE id=?',(ident,)).fetchone()
        previous=json.loads(old[0]) if old else None
        if target.exists():
            manifest,manifest_hash=self.verify_path(target,previous.get('manifest_sha256') if previous else None)
        else:
            if folder.is_symlink() or folder.parent.is_symlink():raise ValueError('evidence_directory_rejected')
            manifest={'schema':'collection-evidence-archive-v1','job_id':job['id'],'attempt':job['attempt'],'files':{}}
            fd,temporary=tempfile.mkstemp(prefix='.pending-',suffix='.zip',dir=self.archives)
            with os.fdopen(fd,'w+b') as stream:
                with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(folder.rglob('*')):
                        if path.is_symlink():raise ValueError('evidence_directory_rejected')
                        if not path.is_file():continue
                        name=str(path.relative_to(folder))
                        if name=='manifest.json' or path.stat().st_size>8*1024*1024:raise ValueError('evidence_artifact_too_large')
                        archive.write(path,name);manifest['files'][name]={'bytes':path.stat().st_size,'sha256':digest_file(path)}
                    raw=canonical(manifest).encode();archive.writestr('manifest.json',raw)
                stream.flush();os.fsync(stream.fileno())
            manifest,manifest_hash=self.verify_path(Path(temporary),hashlib.sha256(raw).hexdigest())
            os.replace(temporary,target)
        receipt=dict(id=ident,job_id=job['id'],attempt=job['attempt'],status='ready',manifest_sha256=manifest_hash,
                     archive_sha256=digest_file(target),archive_bytes=target.stat().st_size,files=len(manifest['files']),created_at=time.time())
        if manifest.get('job_id')!=job['id'] or manifest.get('attempt')!=job['attempt']:raise ValueError('evidence_archive_invalid')
        with self.core.db() as db:
            db.execute('INSERT INTO collection_archives VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,document=excluded.document',
                       (ident,job['id'],job['attempt'],'ready',canonical(receipt)))
        # Delete only duplicate successful bytes already verified in the archive.
        # Unexpected/new/changed files abort cleanup; failure folders never enter here.
        for path in folder.rglob('*'):
            if path.is_symlink():raise ValueError('evidence_directory_rejected')
            if path.is_file():
                meta=manifest['files'].get(str(path.relative_to(folder)))
                if not meta or digest_file(path)!=meta['sha256']:raise ValueError('evidence_changed_during_archive')
        shutil.rmtree(folder)
        return receipt

    def maintain(self,force=False):
        before=self.status();self.alerts(before)
        if before['unsafe_symlink']:return {'status':'blocked','capacity':before,'archived':0}
        if not force and before['status']=='ok':return {'status':'ok','capacity':before,'archived':0}
        with (self.state/'collection-archive.lock').open('a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return {'status':'busy','capacity':before,'archived':0}
            count=0;failed=False
            for job,folder in self.eligible():
                try:self.archive_one(job,folder);count+=1
                except Exception:failed=True;break
                if count>=3 or (not force and self.status()['status']=='ok'):break
        after=self.status();self.alerts(after)
        if failed:
            with self.core.db() as db:db.execute("INSERT OR IGNORE INTO collection_alerts VALUES (?,?,0,'collection_archive_failed','open',?)",(hashlib.sha256(b'archive-failed').hexdigest()[:32],'archive',time.time()))
        return {'status':'archive_failed_originals_retained' if failed else 'completed','capacity':after,'archived':count}

    def listing(self):
        with self.core.db() as db:rows=[json.loads(r[0]) for r in db.execute('SELECT document FROM collection_archives ORDER BY rowid DESC LIMIT 100')]
        return {'archives':rows,'capacity':self.status()}

    def verify(self,archive_id):
        with self.core.db() as db:row=db.execute('SELECT document FROM collection_archives WHERE id=?',(archive_id,)).fetchone()
        if not row:raise ValueError('evidence_archive_not_found')
        receipt=json.loads(row[0]);path=self.archives/(receipt['id']+'.zip')
        if digest_file(path)!=receipt['archive_sha256']:raise ValueError('evidence_archive_invalid')
        self.verify_path(path,receipt['manifest_sha256'])
        return {'id':archive_id,'status':'verified','files':receipt['files'],'archive_sha256':receipt['archive_sha256']}
