"""Owned collection worker. Its route children poll the durable cancellation fence."""
import argparse
import json
from pathlib import Path
import sys
import time

from collect import collect,execute
from setup import ROOT, STATE
sys.path.insert(0, str(ROOT / 'commerce'))
from collection_jobs import worker_valid, save
from commerce_core import Core
from crawler_feed_bridge import atomic, persist_collection
from collection_registry import REGISTRY,NATIVE_KEYS
from native_feed_capture import persist as persist_native


def run(database, job, attempt, owner, output):
    core = Core(database)
    def cancelled():
        with core.db() as db:
            _, valid = worker_valid(db, job, attempt, owner)
            return not valid
    def update(**changes):
        with core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            value, valid = worker_valid(db, job, attempt, owner)
            if not valid:return
            value['progress'].update(changes)
            value['updated_at'] = time.time()
            save(db, value, owner, time.time())
    with core.db() as db:
        value, valid = worker_valid(db, job, attempt, owner)
    if not valid:
        atomic(output, {'status':'cancelled','completed_sources':[]});return 1
    selected = list(REGISTRY) if value['source'] == 'all' else [value['source']]
    outcomes, completed = [], []
    folder = output.parent / 'evidence'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for ident in selected:
        if cancelled():break
        source = REGISTRY[ident]
        update(current_source=ident, routes_checked=0)
        config = {'kind':source['kind'], 'max_pages':1, 'min_records':1, 'min_agreeing':2,
                  'route_timeout':35,'total_timeout':100,
                  'routes':[{'id':label,'engine':engine,'url':source['url'],
                             'source_id':ident,'publisher':source['publisher']}
                            for label,engine in [('standard','feed-http'),('scrapling','feed-scrapling'),('native','feed-native')]]}
        if ident in NATIVE_KEYS:
            directory=folder/ident;directory.mkdir(mode=0o700)
            result=execute({'id':'native','engine':'native-intel','url':source['url']},config,directory,35,cancelled=cancelled)
            result.update(unique_records=len(result.get('rows',[])),agreeing_routes=[])
            update(routes_checked=1)
        else:
            result = collect(config, folder / ident, cancelled=cancelled,
                             progress=lambda done,total:update(routes_checked=done))
        atomic(folder / (ident+'.json'), result)
        # The ownership/cancellation fence and publication share the same DB lock.
        # A cancellation accepted first prevents publication; already committed
        # source snapshots remain available and are explicitly listed in progress.
        with core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            value, valid = worker_valid(db, job, attempt, owner)
            if not valid:break
            good=result['status']=='ok' if ident in NATIVE_KEYS else result['status']=='verified'
            if ident in NATIVE_KEYS:
                if good:persist_native(source,result)
            else:persist_collection(source,result)
            entry={'source_id':ident,'status':result['status'],'records':result['unique_records'],
                   'agreeing_routes':result['agreeing_routes']}
            outcomes.append(entry)
            if good:completed.append(ident)
            value['sources']=outcomes
            value['progress'].update(processed=len(outcomes),successful=len(completed),current_source=None)
            value['updated_at']=time.time();save(db,value,owner,time.time())
    status='cancelled' if cancelled() else 'succeeded' if len(completed)==len(selected) else 'failed'
    atomic(output, {'status':status,'completed_sources':completed,'sources':outcomes})
    return 0 if status=='succeeded' else 1


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--job',required=True)
    parser.add_argument('--attempt',required=True,type=int)
    parser.add_argument('--owner',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    return run(args.database,args.job,args.attempt,args.owner,args.output)


if __name__=='__main__':
    raise SystemExit(main())
