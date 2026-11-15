"""Rehearse database, registered media and private configuration recovery offline.

Copies never replace live files and never instantiate services or replay work.
Historical verification and duplicate backup directories are outside this scope.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import time
from database_recovery import verify_recovery, readonly, file_sha, create_private

EXCLUDED={'recovery','verification','coordination','backups','connector-backups','harness-backup','harness-local','upgrade-backups','release-candidates','ui-releases'}

def inventory(state,limit,max_bytes):
    result={};total=0
    for base,dirs,files in os.walk(state,followlinks=False):
        root=Path(base)
        dirs[:]=[d for d in dirs if not(root==state and d in EXCLUDED)]
        if any((root/d).is_symlink()for d in dirs):raise ValueError('state_recovery_symlink_rejected')
        for name in files:
            path=root/name;rel=path.relative_to(state)
            if name=='commerce.sqlite'or name.endswith(('.log','.pid','.lock','-wal','-shm'))or name=='.DS_Store':continue
            if path.is_symlink()or not path.is_file():raise ValueError('state_recovery_unsafe_file')
            size=path.stat().st_size;total+=size
            if len(result)>=limit or total>max_bytes:raise ValueError('state_recovery_size_limit')
            result[str(rel)]={'sha256':file_sha(path),'size':size,'mode':0o700 if path.stat().st_mode&0o111 else 0o600}
    return result

def private_copy(source,target):
    target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    create_private(target)
    with source.open('rb')as reader,target.open('wb')as writer:shutil.copyfileobj(reader,writer,512*1024)
    target.chmod(0o700 if source.stat().st_mode&0o111 else 0o600)

def verify_state_recovery(state,*,file_limit=20000,max_bytes=20*1024**3,timeout_seconds=180):
    state=Path(state).resolve();started=time.monotonic()
    before=inventory(state,file_limit,max_bytes)
    result=verify_recovery(state,timeout_seconds=timeout_seconds)
    folder=result['report'].parent;report={'schema':'commerce-state-recovery-v1','status':'running','scope':'database_assets_private_configuration',
        'live_files_restored':False,'workers_started_or_stopped':False,'excluded_root_directories':sorted(EXCLUDED),'excluded_transient_files':['logs','pids','locks','SQLite WAL/SHM'],
        'database_report':'report.json','files':before,'secrets_included_in_private_copies':True}
    report['installed_host_sdk_and_generated_previews_included']=False
    try:
        if result['status']!='passed':raise ValueError('state_recovery_database_failed')
        backup=folder/'backup-state';restored=folder/'restored-state'
        backup.mkdir(mode=0o700);restored.mkdir(mode=0o700)
        private_copy(folder/'backup.sqlite',backup/'commerce.sqlite');private_copy(folder/'restored.sqlite',restored/'commerce.sqlite')
        for rel,meta in before.items():
            if time.monotonic()-started>timeout_seconds:raise ValueError('state_recovery_time_limit')
            source=state/rel
            if source.is_symlink()or not source.is_file():raise ValueError('state_recovery_source_changed')
            private_copy(source,backup/rel)
            if file_sha(backup/rel)!=meta['sha256']:raise ValueError('state_recovery_source_changed')
            private_copy(backup/rel,restored/rel)
            if file_sha(restored/rel)!=meta['sha256']:raise ValueError('state_recovery_restore_mismatch')
            if (restored/rel).stat().st_mode&0o777!=meta['mode']:raise ValueError('state_recovery_restore_mode_mismatch')
        if inventory(state,file_limit,max_bytes)!=before:raise ValueError('state_recovery_source_changed')
        checked=0
        with readonly(restored/'commerce.sqlite')as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table'AND name='creative_assets'").fetchone()
            if exists:
                for project,filename,raw in db.execute('SELECT project,filename,metadata FROM creative_assets'):
                    path=restored/'creative'/project/filename
                    if not path.resolve().is_relative_to(restored/'creative')or not path.is_file():raise ValueError('state_recovery_registered_asset_missing')
                    expected=json.loads(raw).get('sha256')
                    if not expected or file_sha(path)!=expected:raise ValueError('state_recovery_registered_asset_mismatch')
                    checked+=1
        report.update(status='passed',file_count=len(before),total_bytes=sum(v['size']for v in before.values()),registered_assets_checked=checked,
            all_copied_file_hashes_equal=True,database_integrity_verified=True,seconds=round(time.monotonic()-started,3))
    except Exception as exc:
        report.update(status='failed',code=str(exc)if isinstance(exc,ValueError)and str(exc).startswith('state_recovery_')else'state_recovery_failed')
    path=folder/'state-report.json';create_private(path)
    with path.open('w')as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    return {'status':report['status'],'report':path,'details':report}

if __name__=='__main__':
    state=Path(os.environ.get('COMMERCE_STATE',str(Path(__file__).resolve().parents[1]/'.commerce-state')))
    try:result=verify_state_recovery(state)
    except (OSError,ValueError):
        print(json.dumps({'status':'failed','code':'state_recovery_preflight_failed','live_files_restored':False}))
        raise SystemExit(1)from None
    print(json.dumps({k:result['details'].get(k)for k in ('status','scope','file_count','registered_assets_checked','live_files_restored','code')}))
    raise SystemExit(0 if result['status']=='passed'else 1)
