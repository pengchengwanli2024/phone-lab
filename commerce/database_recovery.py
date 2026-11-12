"""Point-in-time SQLite recovery rehearsal, never restore into the live database.

No service import, worker initialization, model call or provider configuration.
Reports and both copies remain under the caller's private state directory.
"""
from datetime import datetime, timezone
from pathlib import Path
import base64
import hashlib
import json
import os
import sqlite3
import time
from urllib.parse import quote
import uuid


def readonly(path):return sqlite3.connect('file:'+quote(str(Path(path).resolve()),safe='/')+'?mode=ro',uri=True,timeout=10)
def quoted(value):return '"'+value.replace('"','""')+'"'
def sha(value):return hashlib.sha256(value).hexdigest()
def file_sha(path):
    value=hashlib.sha256()
    with path.open('rb')as stream:
        for chunk in iter(lambda:stream.read(512*1024),b''):value.update(chunk)
    return value.hexdigest()
def encoded(value):
    if value is None:return ['null',None]
    if isinstance(value,bytes):return ['bytes',base64.b64encode(value).decode()]
    if isinstance(value,float):return ['float',value.hex()]
    if isinstance(value,int):return ['int',str(value)]
    if isinstance(value,str):return ['text',value]
    raise ValueError('unsupported_database_value')


def fingerprint(connection, row_limit=1000000):
    if [r[0]for r in connection.execute('PRAGMA integrity_check')]!=['ok']:raise ValueError('database_integrity_check_failed')
    if connection.execute('PRAGMA foreign_key_check').fetchone()is not None:raise ValueError('database_foreign_key_check_failed')
    schema=connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    schema_sha=sha(json.dumps(schema,ensure_ascii=True,separators=(',',':')).encode());tables={};total=0
    for (name,)in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
        hashes=[]
        for row in connection.execute('SELECT * FROM '+quoted(name)):
            total+=1
            if total>row_limit:raise ValueError('database_rehearsal_row_limit')
            hashes.append(sha(json.dumps([encoded(v)for v in row],ensure_ascii=True,separators=(',',':')).encode()))
        tables[name]={'rows':len(hashes),'sha256':sha('\n'.join(sorted(hashes)).encode())}
    settings={name:connection.execute('PRAGMA '+name).fetchone()[0]for name in ('user_version','application_id','encoding')}
    return dict(schema_sha256=schema_sha,tables=tables,total_rows=total,settings=settings)


def create_private(path):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)


def copy_database(source, destination, deadline):
    def progress(*args):
        if time.monotonic()>deadline:raise ValueError('database_backup_time_limit')
    create_private(destination)
    reader=readonly(source)
    try:
        target=sqlite3.connect(destination,timeout=10)
        try:reader.backup(target,pages=256,progress=progress,sleep=.01)
        finally:target.close()
    finally:reader.close()


def verify_recovery(state, *, row_limit=1000000, timeout_seconds=60):
    state=Path(state).resolve();source=state/'commerce.sqlite'
    if source.is_symlink()or not source.is_file():raise ValueError('database_source_unavailable')
    root=state/'recovery'
    if root.is_symlink():raise ValueError('unsafe_recovery_directory')
    root.mkdir(exist_ok=True,mode=0o700);root.chmod(0o700)
    folder=root/uuid.uuid4().hex;folder.mkdir(mode=0o700)
    backup=folder/'backup.sqlite';restored=folder/'restored.sqlite';started=time.monotonic();deadline=started+timeout_seconds
    report={'schema':'commerce-database-recovery-v1','status':'running','scope':'database_only','created_at':datetime.now(timezone.utc).isoformat(),'live_database_restored':False,'workers_started_or_stopped':False,'asset_files_included':False,'provider_profiles_included':False,'source_access':'sqlite_read_only_backup_api'}
    try:
        copy_database(source,backup,deadline)
        reader=readonly(backup)
        try:expected=fingerprint(reader,row_limit)
        finally:reader.close()
        copy_database(backup,restored,deadline)
        reader=readonly(restored)
        try:actual=fingerprint(reader,row_limit)
        finally:reader.close()
        if expected!=actual:raise ValueError('database_restore_fingerprint_mismatch')
        report.update(status='passed',integrity_valid=True,foreign_keys_valid=True,schema_equal=True,table_fingerprints_equal=True,table_count=len(expected['tables']),snapshot=expected,backup_sha256=file_sha(backup),restored_sha256=file_sha(restored),seconds=round(time.monotonic()-started,3))
    except Exception as error:
        # Never echo a database exception or a row value into a report.
        safe={'database_integrity_check_failed','database_foreign_key_check_failed','database_rehearsal_row_limit','database_backup_time_limit','database_restore_fingerprint_mismatch'}
        report.update(status='failed',code=str(error)if isinstance(error,ValueError)and str(error)in safe else'database_recovery_verification_failed',seconds=round(time.monotonic()-started,3))
    path=folder/'report.json';descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w')as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    return dict(status=report['status'],report=path,details=report)


if __name__=='__main__':
    state=Path(os.environ.get('COMMERCE_STATE',str(Path(__file__).resolve().parents[1]/'.commerce-state')))
    result=verify_recovery(state)
    print(json.dumps({'status':result['status'],'scope':'database_only','private_report':str(result['report']),'live_database_restored':False,'workers_started_or_stopped':False}))
    raise SystemExit(0 if result['status']=='passed'else 1)
