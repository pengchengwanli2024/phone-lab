"""Single-client native event receipts, distinct from verified multiroute feeds."""
from pathlib import Path
import hashlib
import fcntl
import os
from crawler_feed_bridge import ROOT,atomic,read,digest,stamp,canonical

CACHE=ROOT/'.local/crawlers/native-published'

def persist(source,result,cache=None):
    from intelligence import parse
    cache=Path(cache or CACHE)
    if cache.is_symlink():raise ValueError('crawler_snapshot_invalid')
    capture=result.get('native_capture')
    if result.get('status')!='ok' or not isinstance(capture,dict):raise ValueError('crawler_native_capture_failed')
    data=capture['payload'].encode()
    rows=parse(source['id'],data)
    if hashlib.sha256(data).hexdigest()!=capture['payload_sha256'] or not rows:raise ValueError('crawler_snapshot_invalid')
    for row in rows:
        refs=result.get('record_evidence',{}).get(row['id'],[])
        if not refs or any(r.get('source_url')!=source['url'] or r.get('payload_sha256')!=capture['payload_sha256'] for r in refs):raise ValueError('crawler_snapshot_invalid')
    stamp(capture['captured_at'])
    payload={'source_id':source['id'],'source_url':source['url'],**capture,'record_evidence':result['record_evidence']}
    envelope={'schema':'native-publisher-capture-v1','integrity_sha256':digest(payload),'payload':payload}
    if len(canonical(envelope).encode())>4_000_000:raise ValueError('crawler_native_capture_too_large')
    cache.mkdir(parents=True,exist_ok=True,mode=0o700);cache.chmod(0o700)
    fd=os.open(cache/(source['id']+'.lock'),os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        old=read(cache/(source['id']+'.json'),optional=True)
        if old and old.get('integrity_sha256')==digest(old.get('payload')) and stamp(old['payload']['captured_at'])>stamp(capture['captured_at']):return
        atomic(cache/(source['id']+'.json'),envelope)

def load(source_id,cache=None):
    from intelligence import SOURCES,parse
    cache=Path(cache or CACHE)
    if cache.is_symlink():raise ValueError('crawler_snapshot_invalid')
    envelope=read(cache/(source_id+'.json'));payload=envelope.get('payload',{})
    if envelope.get('schema')!='native-publisher-capture-v1' or envelope.get('integrity_sha256')!=digest(payload):raise ValueError('crawler_snapshot_invalid')
    if payload.get('source_id')!=source_id or payload.get('source_url')!=SOURCES[source_id]['url']:raise ValueError('crawler_snapshot_invalid')
    data=payload['payload'].encode();observed=stamp(payload['captured_at'])
    if hashlib.sha256(data).hexdigest()!=payload['payload_sha256']:raise ValueError('crawler_snapshot_invalid')
    rows=parse(source_id,data)
    for row in rows:
        refs=payload['record_evidence'].get(row['id'],[])
        if not refs or any(r.get('source_url')!=payload['source_url'] or r.get('payload_sha256')!=payload['payload_sha256'] for r in refs):raise ValueError('crawler_snapshot_invalid')
        row.update(collection_provenance=refs,publisher=SOURCES[source_id]['name'],collection_mode='single_client_native_feed')
    return data,rows,{'collected_at':observed,'snapshot_checked_at':payload['captured_at'],
                      'last_collection_attempt':{'status':'captured_single_route','checked_at':payload['captured_at']}}
