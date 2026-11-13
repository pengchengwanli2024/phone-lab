"""Project-owned model profiles. Credentials are only accepted by private HTTP setup."""
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
import hashlib,ipaddress,json,os,re,secrets,threading,time,uuid,webbrowser

ENGINES={'llama_cpp':'llama.cpp','vllm':'vLLM','custom':'自定义兼容服务'}
PROBE=threading.BoundedSemaphore(1)


def definitions(schema,string):
    return [
        ('commerce_model_list','读取项目可选模型和接入状态，不返回密钥、不触发推理',schema()),
        ('commerce_model_open_setup','打开本机私有模型配置页，密钥不经过MCP或聊天',schema()),
    ]


def endpoint(value):
    if not isinstance(value,str) or len(value)>1000 or any(c.isspace() for c in value):raise ValueError('model_invalid_endpoint')
    try:
        p=urlsplit(value);port=p.port;host=p.hostname
        if p.scheme not in ('http','https') or not host or p.username is not None or p.password is not None or p.query or p.fragment:raise ValueError()
        if any(x in p.path for x in ('..','%','\\')) or p.path.endswith(('/chat/completions','/responses')):raise ValueError()
        try:address=ipaddress.ip_address(host)
        except ValueError:address=None
        if address and (address.is_unspecified or address.is_link_local or address.is_multicast or address.is_reserved and not address.is_loopback):raise ValueError()
        if p.scheme=='http' and not(host=='localhost' or address and (address.is_loopback or address.is_private)):raise ValueError()
        if port is not None and not 1<=port<=65535:raise ValueError()
        return urlunsplit((p.scheme,p.netloc,p.path.rstrip('/'),'',''))
    except (ValueError,TypeError):raise ValueError('model_invalid_endpoint') from None


class ModelRegistry:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.state=service.state
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS model_profiles(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,config TEXT NOT NULL,enabled INTEGER NOT NULL,tested_revision INTEGER,test_status TEXT NOT NULL,tested_at REAL,updated REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS copilot_models(thread_id TEXT PRIMARY KEY,model_id TEXT NOT NULL,revision INTEGER NOT NULL)')

    def _record(self,db,ident):
        if not isinstance(ident,str) or not re.fullmatch('model_[a-f0-9]{16}',ident):raise ValueError('model_profile_not_found')
        row=db.execute('SELECT id,revision,config,enabled,tested_revision,test_status,tested_at FROM model_profiles WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('model_profile_not_found')
        return {'id':row[0],'revision':str(row[1]),'config':json.loads(row[2]),'enabled':bool(row[3]),'tested_revision':str(row[4]) if row[4] is not None else None,'test_status':row[5],'tested_at':row[6]}

    def _public(self,row):
        config=row['config'];return {k:v for k,v in row.items() if k!='config'}|{k:config[k] for k in ('label','engine','base_url','model','json_mode')}|{'key_configured':bool(config.get('credential_ref')),'selectable':row['enabled'] and row['test_status']=='passed' and row['tested_revision']==row['revision']}

    def default_snapshot(self):
        from agent_runtime.codex_provider import route
        config=route(self.state)
        return {**config,'profile_id':'project-default','label':'项目默认','profile_revision':'0'}

    def catalog(self):
        try:
            route=self.default_snapshot();default={'id':'project-default','label':'项目默认','engine':'builtin','model':route.get('model') or '既有Hermes配置','provider':route['provider'],'enabled':True,'selectable':True,'revision':'0','test_status':'existing_route'}
        except ValueError:default={'id':'project-default','label':'项目默认 · 配置待修复','engine':'builtin','enabled':False,'selectable':False,'revision':'0','test_status':'invalid_configuration','model':''}
        with self.core.db() as db:models=[self._public(self._record(db,r[0])) for r in db.execute('SELECT id FROM model_profiles ORDER BY updated DESC')]
        return {'models':[default,*models],'selection_scope':'conversation','credentials_via_private_setup_only':True}

    def _secret(self,reference):
        if not reference:return ''
        if not re.fullmatch('[a-f0-9]{32}',reference):raise ValueError('agent_model_credentials_unavailable')
        path=self.state/'model-credentials'/(reference+'.json')
        if path.is_symlink() or path.parent.is_symlink():raise ValueError('agent_model_credentials_unavailable')
        try:value=json.loads(path.read_text())['api_key']
        except (OSError,ValueError,KeyError):raise ValueError('agent_model_credentials_unavailable') from None
        return value

    def configure(self,data):
        allowed={'id','expected_revision','label','engine','base_url','model','api_key','clear_api_key','json_mode'}
        if not isinstance(data,dict) or set(data)-allowed:raise ValueError('model_invalid_configuration')
        for key,limit in [('label',80),('model',160)]:
            if not isinstance(data.get(key),str) or not data[key].strip() or len(data[key])>limit or any(ord(c)<32 for c in data[key]):raise ValueError('model_invalid_'+key)
        if data.get('engine') not in ENGINES or type(data.get('json_mode',True)) is not bool or type(data.get('clear_api_key',False)) is not bool:raise ValueError('model_invalid_configuration')
        base_url=endpoint(data.get('base_url'));key=data.get('api_key','')
        if not isinstance(key,str) or len(key)>8192 or any(ord(c)<32 or ord(c)==127 for c in key):raise ValueError('model_invalid_api_key')
        ident=data.get('id') or 'model_'+uuid.uuid4().hex[:16]
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE');old=self._record(db,ident) if data.get('id') else None
            if old and data.get('expected_revision')!=old['revision']:raise ValueError('model_profile_changed')
            reference=None if data.get('clear_api_key') else (old or {}).get('config',{}).get('credential_ref')
            if key.strip():
                directory=self.state/'model-credentials';directory.mkdir(exist_ok=True,mode=0o700)
                if directory.is_symlink():raise ValueError('model_invalid_credential_storage')
                directory.chmod(0o700)
                reference=secrets.token_hex(16);path=directory/(reference+'.json')
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as f:json.dump({'api_key':key.strip()},f)
            config={'label':data['label'].strip(),'engine':data['engine'],'base_url':base_url,'model':data['model'].strip(),'json_mode':data.get('json_mode',True),'credential_ref':reference}
            revision=int(old['revision'])+1 if old else 1
            db.execute('INSERT INTO model_profiles VALUES(?,?,?,?,NULL,?,NULL,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,config=excluded.config,tested_revision=NULL,test_status=excluded.test_status,tested_at=NULL,updated=excluded.updated',(ident,revision,json.dumps(config,ensure_ascii=False),int(old['enabled']) if old else 0,'not_tested',time.time()))
            return self._public(self._record(db,ident))

    def _snapshot(self,row):
        return {**row['config'],'provider':'compatible','profile_id':row['id'],'profile_revision':row['revision']}

    def test(self,model_id,expected_revision):
        if not PROBE.acquire(blocking=False):raise ValueError('model_test_busy')
        try:
            with self.core.db() as db:row=self._record(db,model_id)
            if row['revision']!=expected_revision:raise ValueError('model_profile_changed')
            config=self._snapshot(row);config['api_key']=self._secret(config.get('credential_ref'))
            from .inference import invoke_json
            try:
                result=invoke_json({'connectivity_test':True},lambda:False,config,'Reply with only the JSON object {"ok":true}. This is a synthetic connection test.',max_tokens=64)
                passed=result.get('decision')=={'ok':True}
            except Exception as error:
                passed=False
                unknown=isinstance(error,ValueError) and str(error)=='agent_provider_outcome_unknown'
            else:unknown=False
            with self.core.db() as db:
                if self._record(db,model_id)['revision']!=expected_revision:raise ValueError('model_profile_changed')
                db.execute('UPDATE model_profiles SET tested_revision=?,test_status=?,tested_at=? WHERE id=?',(int(expected_revision),'passed' if passed else 'unknown' if unknown else 'failed',time.time(),model_id))
                result=self._public(self._record(db,model_id))
            if not passed:raise ValueError('model_test_unknown' if unknown else 'model_test_failed')
            return result
        finally:PROBE.release()

    def set_enabled(self,model_id,enabled,expected_revision):
        if type(enabled) is not bool:raise ValueError('model_invalid_configuration')
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE');row=self._record(db,model_id)
            if row['revision']!=expected_revision:raise ValueError('model_profile_changed')
            if enabled and (row['test_status']!='passed' or row['tested_revision']!=row['revision']):raise ValueError('model_not_ready')
            db.execute('UPDATE model_profiles SET enabled=?,updated=? WHERE id=?',(int(enabled),time.time(),model_id))
            return self._public(self._record(db,model_id))

    def selection(self,db,thread_id):
        row=db.execute('SELECT model_id,revision FROM copilot_models WHERE thread_id=?',(thread_id,)).fetchone()
        ident,revision=(row[0],str(row[1])) if row else ('project-default','0')
        candidate=next((r for r in self.catalog()['models'] if r['id']==ident),None)
        binding={'model_id':ident,'revision':revision,'profile_revision':candidate['revision'] if candidate else None,'model':candidate.get('model') if candidate else None,'available':bool(candidate and candidate['selectable'])}
        binding['sha256']=hashlib.sha256(json.dumps(binding,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return {**binding,'label':candidate['label'] if candidate else '模型已不可用'}

    def select(self,thread_id,model_id,expected_revision):
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM copilot_threads WHERE id=?',(thread_id,)).fetchone():raise ValueError('copilot_thread_not_found')
            selected=self.selection(db,thread_id)
            if selected['revision']!=expected_revision:raise ValueError('model_selection_changed')
            self.service.copilot._idle(db,thread_id)
            self.snapshot(db,model_id=model_id)
            db.execute('INSERT INTO copilot_models VALUES(?,?,?) ON CONFLICT(thread_id) DO UPDATE SET model_id=excluded.model_id,revision=excluded.revision',(thread_id,model_id,int(expected_revision)+1))
        return self.service.copilot.get(thread_id)

    def snapshot(self,db,thread_id=None,model_id=None,expected_sha256=None):
        selected=self.selection(db,thread_id) if thread_id else None
        if expected_sha256 is not None and (not selected or selected['sha256']!=expected_sha256):raise ValueError('copilot_model_changed')
        if model_id is None:model_id=selected['model_id'] if selected else 'project-default'
        if model_id=='project-default':return self.default_snapshot()
        row=self._record(db,model_id)
        if not self._public(row)['selectable']:raise ValueError('model_not_ready')
        return self._snapshot(row)

    def runtime_route(self,snapshot):
        if snapshot.get('provider')!='compatible':return snapshot
        with self.core.db() as db:
            if not self._record(db,snapshot['profile_id'])['enabled']:raise ValueError('agent_model_disabled')
        return {**snapshot,'api_key':self._secret(snapshot.get('credential_ref'))}

    @staticmethod
    def public_snapshot(snapshot):
        return {k:snapshot[k] for k in ('profile_id','profile_revision','label','provider','model','engine') if k in snapshot}

    def open_setup(self):
        from runtime import PORT
        ticket=self.service.live.new_setup_ticket()
        opened=webbrowser.open(f'http://127.0.0.1:{PORT}/model-setup?ticket={ticket}')
        return {'opened':bool(opened),'status':'opened_local_private_setup' if opened else 'browser_open_unconfirmed'}
