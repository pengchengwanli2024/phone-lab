"""Read-only 24-hour observer of the existing service; never schedules work."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import fcntl,hashlib,json,math,os
from pathlib import Path
import signal,sqlite3,subprocess,sys,tempfile,time,uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'commerce'))
from runtime import STATE,request
from crawler_feed_bridge import atomic

FILES=['commerce/collection_jobs.py','commerce/collection_registry.py','commerce/feed_planner.py',
       'commerce/native_feed_capture.py','commerce/intelligence.py','commerce/intel_store.py','commerce/autonomy.py',
       'commerce/evidence_capacity.py','commerce/article_review.py','commerce/intel_articles.py','commerce/research.py',
       'crawlers/job_worker.py','crawlers/worker.py','crawlers/collect.py','crawlers/rate_limit.py',
       'crawlers/resource_limits.py','crawlers/route_worker.py','crawlers/endurance.py']

def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES if (ROOT/name).is_file()}
def stamp(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()

def verdict(duration,elapsed,max_gap,errors,samples,sources,interval,code_same):
    # A short harness run can validate this code but never establish 24h acceptance.
    if duration<86400 or elapsed<duration:return 'in_progress'
    minimum=max(1,math.floor(duration/interval)-1)
    enough=len(sources)==8 and all(s['terminal']>=minimum and s['succeeded']/max(1,s['terminal'])>=.95 for s in sources.values())
    return 'passed' if code_same and max_gap<=120 and errors/max(1,samples)<=.01 and enough else 'failed'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path);args=parser.parse_args()
    if not (STATE/'auth.token').is_file():raise SystemExit('existing_runtime_required')
    parent=STATE/'crawler-endurance';parent.mkdir(exist_ok=True,mode=0o700)
    lock=(parent/'active.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('observer_already_running')
    folder=args.directory or parent/uuid.uuid4().hex
    if folder.parent.resolve()!=parent.resolve() or len(folder.name)!=32 or any(c not in '0123456789abcdef' for c in folder.name):raise SystemExit('private_evidence_directory_required')
    if folder.exists():raise SystemExit('new_evidence_directory_required')
    folder.mkdir(parents=True,mode=0o700)
    (parent/'latest.json').write_text(json.dumps({'directory':folder.name}))
    began_wall=time.time();began=time.monotonic();frozen=hashes()
    duration=86400;sample_every=30
    initial=request('commerce_runtime_status',{})['public_collection']
    if not initial['enabled'] or len(initial.get('result',{}))!=8:raise SystemExit('eight_source_scheduler_required')
    interval=initial['interval_seconds']
    with sqlite3.connect(str(STATE/'commerce.sqlite')) as db:baseline=db.execute('SELECT coalesce(max(rowid),0) FROM collection_jobs').fetchone()[0]
    manifest=dict(schema='crawler-endurance-v1',started_at=stamp(began_wall),earliest_finish_at=stamp(began_wall+duration),
                  duration_seconds=duration,sample_seconds=sample_every,interval_seconds=interval,source_ids=list(initial['result']),
                  code_sha256=frozen,baseline_job_row=baseline,
                  criteria={'max_monitor_gap_seconds':120,'max_local_poll_failure_fraction':.01,'min_source_success_fraction':.95,
                            'minimum_terminal_jobs_per_source':max(1,math.floor(duration/interval)-1)},
                  public_requests_by_observer=0,model_calls_by_observer=0)
    atomic(folder/'manifest.json',manifest)
    keepawake=None
    if sys.platform=='darwin':keepawake=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    stop=False
    def halt(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,halt);signal.signal(signal.SIGINT,halt)
    errors=samples=0;last=began_wall;gap=0;chain='0'*64;sources={};peak_service_rss=0
    progress={'status':'interrupted','elapsed_seconds':0,'samples':0,'formal_acceptance':False}
    try:
        while not stop:
            now=time.time();elapsed=time.monotonic()-began;gap=max(gap,now-last);last=now
            record={'at':stamp(now),'elapsed_seconds':round(elapsed,2)};policy_changed=False
            try:
                current=request('commerce_runtime_status',{})['public_collection']
                if current['interval_seconds']!=interval or not current['enabled']:
                    policy_changed=True;raise ValueError('schedule_policy_changed')
                with sqlite3.connect('file:'+str(STATE/'commerce.sqlite')+'?mode=ro',uri=True) as db:
                    jobs=[json.loads(r[0]) for r in db.execute("SELECT document FROM collection_jobs WHERE rowid>?",(baseline,))]
                for source in manifest['source_ids']:
                    relevant=[j for j in jobs if j['source']==source and j.get('trigger')=='schedule' and j.get('started_at',0)>=began_wall]
                    count=Counter(j['status'] for j in relevant)
                    sources[source]={'succeeded':count['succeeded'],'terminal':sum(v for k,v in count.items() if k not in ('queued','running','cancelling')),'counts':dict(count)}
                pid=json.loads((STATE/'runtime.json').read_text())['pid']
                rss=subprocess.run(['ps','-o','rss=','-p',str(pid)],capture_output=True,text=True,timeout=2)
                if rss.returncode==0 and rss.stdout.strip().isdigit():peak_service_rss=max(peak_service_rss,int(rss.stdout.strip()))
                record.update(status='observed',sources=sources)
            except Exception:errors+=1;record['status']='local_observation_failed'
            samples+=1;code_same=hashes()==frozen
            record['previous_sha256']=chain;encoded=json.dumps(record,sort_keys=True,separators=(',',':')).encode();chain=hashlib.sha256(encoded).hexdigest()
            with (folder/'samples.jsonl').open('ab') as stream:stream.write(encoded+b'\n');stream.flush();os.fsync(stream.fileno())
            status=verdict(duration,elapsed,gap,errors,samples,sources,interval,code_same)
            if not code_same:status='invalidated_code_changed'
            if policy_changed:status='invalidated_schedule_changed'
            progress=dict(schema='crawler-endurance-status-v1',status=status,started_at=manifest['started_at'],
                          earliest_finish_at=manifest['earliest_finish_at'],observed_at=record['at'],elapsed_seconds=round(elapsed,2),
                          requested_seconds=duration,samples=samples,observation_errors=errors,max_gap_seconds=round(gap,2),
                          sources=sources,samples_chain_sha256=chain,code_unchanged=code_same,peak_service_rss_kib=peak_service_rss,
                          formal_acceptance=status=='passed')
            atomic(folder/'status.json',progress)
            if status!='in_progress':break
            deadline=time.monotonic()+min(sample_every,max(0,duration-elapsed))
            while not stop and time.monotonic()<deadline:time.sleep(min(1,max(0,deadline-time.monotonic())))
        if stop:progress.update(status='interrupted',formal_acceptance=False);atomic(folder/'status.json',progress)
        print(json.dumps({k:progress[k] for k in ('status','elapsed_seconds','samples','formal_acceptance')}))
    finally:
        if keepawake and keepawake.poll() is None:keepawake.terminate();keepawake.wait(timeout=3)

if __name__=='__main__':main()
