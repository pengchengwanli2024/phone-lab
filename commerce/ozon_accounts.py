"""Private Ozon account archive over the existing single-active read connector.

No credentials in MCP. No network requests, timers or business permissions.
Legacy settings saves must route through configure(), not bypass this registry.
"""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from live_connections import DEFAULTS

SCHEMA = 'ozon-single-active-accounts-v1'
IDENT = re.compile(r'[a-f0-9]{32}')


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def paused(config):
    value=deepcopy(config)
    for flag in ('sync_enabled','notifications_enabled','orders_scope_confirmed',
                 'feishu_test_verified','feishu_received_confirmed'):
        value[flag]=False
    value['stock_basis']='unconfirmed'
    for field in ('orders_scope_reviewed_at','orders_scope_review_snapshot',
                  'basis_reviewed_at','basis_review_snapshot'):
        value.pop(field,None)
    return value


class OzonAccounts:
    def __init__(self,live):
        self.live=live
        self.directory=Path(live.state)/'ozon-accounts'
        if self.directory.is_symlink():raise ValueError('ozon_accounts_registry_invalid')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700);self.directory.chmod(0o700)
        self.path=self.directory/'accounts.json'
        self.journal=self.directory/'pending.json'
        self.lock_path=self.directory/'registry.lock'

    @staticmethod
    def _empty():
        return dict(schema=SCHEMA,revision='0',active_account_id=None,accounts={},requests={})

    def _read(self):
        if self.path.is_symlink():raise ValueError('ozon_accounts_registry_invalid')
        if not self.path.exists():return self._empty()
        try:
            value=json.loads(self.path.read_text())
            if (value.get('schema')!=SCHEMA or not isinstance(value['revision'],str)
                    or not isinstance(value['accounts'],dict) or not isinstance(value['requests'],dict)
                    or len(value['accounts'])>20):raise ValueError()
            for ident,item in value['accounts'].items():
                if not IDENT.fullmatch(ident) or item['id']!=ident or not self._configured(item['config']):raise ValueError()
            if value['active_account_id'] is not None and value['active_account_id']not in value['accounts']:raise ValueError()
            return value
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            raise ValueError('ozon_accounts_registry_invalid')from None

    @staticmethod
    def _configured(config):
        return isinstance(config,dict)and bool(config.get('ozon_client_id')and config.get('ozon_api_key')and config.get('connection_id'))

    def _write(self,path,value):
        if path.is_symlink():raise ValueError('ozon_accounts_registry_invalid')
        fd,name=tempfile.mkstemp(prefix='account-',dir=self.directory)
        try:
            with os.fdopen(fd,'w')as out:
                out.write(encoded(value));out.flush();os.fsync(out.fileno())
            os.chmod(name,0o600);os.replace(name,path);path.chmod(0o600)
        finally:
            if os.path.exists(name):os.unlink(name)

    @contextmanager
    def _exclusive(self):
        if self.lock_path.is_symlink():raise ValueError('ozon_accounts_registry_invalid')
        fd=os.open(self.lock_path,os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'a+')as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            if not self.live.lock.acquire(blocking=False):raise ValueError('ozon_account_busy')
            try:
                with self.live.config_lock:
                    with self.live.core.db()as db:
                        busy=db.execute("SELECT 1 FROM live_jobs WHERE status='running' LIMIT 1").fetchone()
                        sending=db.execute("SELECT 1 FROM live_outbox WHERE status='sending' LIMIT 1").fetchone()
                    if busy or sending:raise ValueError('ozon_account_busy')
                    yield
            finally:self.live.lock.release()

    def _recover(self):
        if self.journal.is_symlink():raise ValueError('ozon_accounts_registry_invalid')
        if not self.journal.exists():return
        try:
            intent=json.loads(self.journal.read_text())
            if intent.get('schema')!='ozon-account-intent-v1':raise ValueError()
            prepared=isinstance(intent.get('after_config'),dict)and isinstance(intent.get('after_registry'),dict)
            config=intent['after_config']if prepared else intent['before_config']
            registry=intent['after_registry']if prepared else intent['before_registry']
            if not isinstance(config,dict)or registry.get('schema')!=SCHEMA:raise ValueError()
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            raise ValueError('ozon_accounts_recovery_invalid')from None
        self.live._save(config);self._write(self.path,registry);self.journal.unlink()

    def recover(self):
        with self._exclusive():self._recover()
        return self.listing()

    def _capture(self,registry,config):
        if not self._configured(config):return None
        matches=[ident for ident,item in registry['accounts'].items()
                 if item['config']['ozon_client_id']==config['ozon_client_id']]
        if len(matches)>1:raise ValueError('ozon_accounts_registry_invalid')
        ident=matches[0]if matches else hashlib.sha256(('ozon-account:'+config['connection_id']).encode()).hexdigest()[:32]
        old=registry['accounts'].get(ident,{})
        if not old and len(registry['accounts'])>=20:raise ValueError('ozon_account_limit')
        connections=list(old.get('connection_ids',[]))
        if config['connection_id']not in connections:connections.append(config['connection_id'])
        registry['accounts'][ident]=dict(id=ident,config=deepcopy(config),connection_ids=connections,
            updated_at=old.get('updated_at',time.time())if old.get('config')==config else time.time())
        registry['active_account_id']=ident
        return ident

    def _view(self):
        if self.journal.exists()or self.journal.is_symlink():raise ValueError('ozon_accounts_recovery_required')
        registry=self._read();self._capture(registry,self.live.config());return registry

    def listing(self):
        with self.live.config_lock:
            registry=self._view();rows=[]
            for ident,item in registry['accounts'].items():
                config=item['config'];active=ident==registry['active_account_id']
                with self.live.core.db()as db:
                    count=db.execute('SELECT count(*) FROM live_snapshots WHERE connection=?',(config['connection_id'],)).fetchone()[0]
                rows.append(dict(account_id=ident,label=config.get('store_label','Ozon'),active=active,
                    connection_id=config['connection_id'],configured=True,stored_snapshot_count=count,
                    fulfillment_modes=config.get('fulfillment_modes',[]),updated_at=item['updated_at'],
                    status='active_single_connector'if active else'stored_inactive',
                    automatic_sync_enabled=bool(active and config.get('sync_enabled'))))
            return dict(schema=SCHEMA,revision=registry['revision'],active_account_id=registry['active_account_id'],
                accounts=sorted(rows,key=lambda r:(not r['active'],r['label'],r['account_id'])),
                mode='single_active_connector',parallel_store_sync=False,credentials_exposed=False,
                account_identity_verified=False,external_execution_allowed=False)

    def status(self,account_id=None):
        result=self.listing()
        if account_id is None:return result
        if not isinstance(account_id,str)or not IDENT.fullmatch(account_id):raise ValueError('ozon_account_not_found')
        item=next((r for r in result['accounts']if r['account_id']==account_id),None)
        if not item:raise ValueError('ozon_account_not_found')
        return dict(schema=SCHEMA,revision=result['revision'],account=item,mode=result['mode'],credentials_exposed=False)

    @staticmethod
    def _key(key):
        if key is not None and (not isinstance(key,str)or not 1<=len(key)<=160):raise ValueError('ozon_accounts_invalid_idempotency_key')

    def _response(self,registry,replay=False,request_result=None):
        return {**self.live.status(),'accounts':dict(revision=registry['revision'],
            active_account_id=registry['active_account_id'],mode='single_active_connector',
            idempotent_replay=replay,request_result=request_result,parallel_store_sync=False)}

    def _mutate(self,request,key,expected,operation):
        self._key(key)
        with self._exclusive():
            self._recover();before_registry=self._read();before_config=self.live.config()
            registry=deepcopy(before_registry);self._capture(registry,before_config)
            prior=registry['requests'].get(key)if key else None
            if prior:
                if prior['request_sha256']!=fingerprint(request):raise ValueError('ozon_accounts_idempotency_conflict')
                return self._response(registry,True,prior['result'])
            if expected is not None and (not isinstance(expected,str)or expected!=registry['revision']):
                raise ValueError('ozon_accounts_revision_changed')
            intent=dict(schema='ozon-account-intent-v1',before_config=before_config,
                before_registry=before_registry,after_config=None,after_registry=None)
            self._write(self.journal,intent)
            try:
                operation(registry,before_config)
                final=self.live.config();self._capture(registry,final);registry['revision']=uuid.uuid4().hex
                result=dict(account_id=registry['active_account_id'],revision=registry['revision'])
                if key:registry['requests'][key]=dict(request_sha256=fingerprint(request),result=result)
                intent.update(after_config=final,after_registry=registry);self._write(self.journal,intent)
                self._write(self.path,registry);self.journal.unlink()
            except Exception:
                # Restore both files after validation/write failure; an interrupted
                # restoration leaves the durable journal for explicit recovery.
                self.live._save(before_config);self._write(self.path,before_registry)
                self.journal.unlink(missing_ok=True)
                raise
            return self._response(registry,False,result)

    def configure(self,values,expected_revision=None,idempotency_key=None):
        """Private HTTP only; returns legacy live.status plus safe account metadata."""
        if not isinstance(values,dict):raise ValueError('invalid_setup_fields')
        request=dict(operation='configure',values=values,expected_revision=expected_revision)
        def apply(registry,before):
            client=values.get('ozon_client_id')or before.get('ozon_client_id')
            switching=bool(client and client!=before.get('ozon_client_id'))
            key=values.get('ozon_api_key')
            rotating=bool(key and key!=before.get('ozon_api_key'))
            incoming=deepcopy(values)
            if switching:
                target=next((item['config']for item in registry['accounts'].values()
                    if item['config']['ozon_client_id']==client),None)
                self.live._save(paused(target or dict(DEFAULTS)))
            if switching or rotating:
                for flag in ('sync_enabled','notifications_enabled','orders_scope_confirmed','feishu_received_confirmed'):
                    incoming[flag]=False
                incoming['stock_basis']='unconfirmed'
                for field in ('basis_confirmed','expected_orders_sha256','expected_stock_sha256'):incoming.pop(field,None)
            self.live.configure(incoming)
            if switching or rotating:self.live._save(paused(self.live.config()))
        return self._mutate(request,idempotency_key,expected_revision,apply)

    def activate(self,account_id,expected_revision,idempotency_key):
        """Switch exact stored identity; never starts sync or inherits attestations."""
        if not isinstance(account_id,str)or not IDENT.fullmatch(account_id):raise ValueError('ozon_account_not_found')
        if not isinstance(expected_revision,str)or not expected_revision:raise ValueError('ozon_accounts_revision_changed')
        if idempotency_key is None:raise ValueError('ozon_accounts_invalid_idempotency_key')
        request=dict(operation='activate',account_id=account_id,expected_revision=expected_revision)
        def apply(registry,before):
            target=registry['accounts'].get(account_id)
            if not target:raise ValueError('ozon_account_not_found')
            if registry['active_account_id']!=account_id:self.live._save(paused(target['config']))
        return self._mutate(request,idempotency_key,expected_revision,apply)
