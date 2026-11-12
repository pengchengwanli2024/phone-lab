"""Independent local entry point; emits no credential, private path or source data."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request
import webbrowser
from runtime import ROOT, STATE, PORT, ensure, health, request, token


def backup():
    folder=STATE/'backups';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    folder.chmod(0o700)
    source=STATE/'commerce.sqlite'
    if not source.is_file():raise ValueError('database_not_initialized')
    name='commerce-'+str(time.time_ns())+'.sqlite'
    path=folder/name
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    try:
        with closing(sqlite3.connect(source)) as current, closing(sqlite3.connect(path)) as copy:
            current.backup(copy)
            if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('backup_integrity_failed')
    except Exception:
        path.unlink(missing_ok=True);raise
    return {'status':'backed_up','file':name,'integrity':'ok','scope':'database_only','credentials_and_knowledge_included':False}


def doctor():
    checks={}
    try:checks['http']=health()['status']
    except Exception:return {'status':'unavailable','checks':{'http':'unavailable'},'next_action':'run python3 commerce/manage.py start'}
    checks['runtime']=request('commerce_runtime_status',{})
    checks['connections']=request('commerce_live_status',{})
    # Include booleans/counts only. This report never dumps a real store label,
    # local filesystem path, credentials, queue payload or source content.
    live=checks.pop('connections')
    checks['platforms']={'ozon_configured':live['configured'],'orders_available':live['orders']['available'],'stock_available':live['stock']['available']}
    checks['notifications']={'configured':live['credentials_present']['feishu_webhook'],'enabled':live['notifications_enabled']}
    try:
        from platform_connections.diagnostics import summarize
        checks['read_connectors']=summarize(request('commerce_platform_catalog',{}),request('commerce_platform_list',{}))
    except Exception:
        checks['read_connectors']={'status':'unknown','running_version_current':False,'diagnostic_only':True}
    current=checks['read_connectors']['running_version_current']
    result={'status':'ready_local' if checks['runtime']['worker']=='running' and current else 'degraded','checks':checks,'full_business_acceptance':False}
    if not current:result['next_action']='review_current_version_and_load_only_after_shared_idle_audit'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['start','serve','open','doctor','backup'])
    args=parser.parse_args()
    if args.command=='serve':
        os.execv(sys.executable,[sys.executable,str(ROOT/'server.py')])
    if args.command in ('start','open'):ensure()
    if args.command=='start':result={'status':'ready','origin':f'http://127.0.0.1:{PORT}'}
    elif args.command=='doctor':result=doctor()
    elif args.command=='backup':result=backup()
    else:
        req=urllib.request.Request(f'http://127.0.0.1:{PORT}/v1/connections/ticket',data=b'{}',headers={'Content-Type':'application/json','Authorization':'Bearer '+token()})
        with urllib.request.urlopen(req,timeout=5)as response:ticket=json.load(response)['ticket']
        if not webbrowser.open(f'http://127.0.0.1:{PORT}/open?ticket='+ticket):raise ValueError('browser_open_failed')
        result={'status':'opened','authentication':'single_use_local_ticket'}
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result['status'] in ('unavailable','degraded') else 0


if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        print(json.dumps({'status':'failed','error':'local_operation_failed','next_action':'check private service log or run doctor'}));sys.exit(1)
