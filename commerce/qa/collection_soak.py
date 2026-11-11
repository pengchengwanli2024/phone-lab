"""Opt-in bounded real-process soak. Only synthetic outputs, no network/model."""
import argparse,json,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'commerce'))
from commerce_core import Core
from collection_jobs import CollectionJobs,save
from collection_state import evolve
from resource import getrusage,RUSAGE_SELF

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=600);args=parser.parse_args()
    if not 10<=args.seconds<=1800:raise ValueError('bounded duration required')
    started=time.monotonic();cycles=failures=cancelled=restarts=0;peak=0
    with tempfile.TemporaryDirectory(prefix='synthetic-collection-soak-') as folder:
        core=Core(Path(folder)/'state.sqlite')
        while time.monotonic()-started<args.seconds:
            clock=time.time()+cycles*120
            failed=cycles%4==0
            def command(value,output):
                value={'status':'failed' if failed else 'succeeded','completed_sources':[]}
                return [sys.executable,'-c','import pathlib;pathlib.Path('+repr(str(output))+').write_text('+repr(json.dumps(value))+')']
            jobs=CollectionJobs(core,folder,command_builder=command)
            with patch('collection_jobs.time.time',return_value=clock):
                job=jobs.request('federal-reserve-press','synthetic-soak-'+str(cycles))
                if cycles%5==0:
                    jobs.cancel(job['id']);cancelled+=1
                elif cycles%7==0:
                    with core.db() as db:save(db,evolve(job,'start',clock,attempt=1),'synthetic-dead-owner',clock)
                    jobs.start(recover=True);jobs.stop()
                    assert jobs.get(job['id'])['status']=='interrupted';restarts+=1
                else:
                    assert jobs.work_once()
                    expected='failed' if failed else 'succeeded'
                    assert jobs.get(job['id'])['status']==expected
                    failures+=int(failed)
            assert not jobs.thread or not jobs.thread.is_alive()
            peak=max(peak,getrusage(RUSAGE_SELF).ru_maxrss)
            cycles+=1
            checkpoint=dict(status='running',elapsed_seconds=round(time.monotonic()-started,1),cycles=cycles,synthetic_failures=failures,queued_cancellations=cancelled,recoveries=restarts,public_requests=0,model_calls=0)
            target=ROOT/'.local/crawlers/results/soak-progress.json';target.write_text(json.dumps(checkpoint))
            time.sleep(min(5,max(0,args.seconds-(time.monotonic()-started))))
        summary=dict(checkpoint,status='passed',elapsed_seconds=round(time.monotonic()-started,1),requested_seconds=args.seconds,peak_controller_rss_bytes=peak if sys.platform=='darwin' else peak*1024,private_artifact_bytes=sum(p.stat().st_size for p in Path(folder).rglob('*') if p.is_file()),duration_scope='bounded synthetic process soak, not 24-hour production availability')
        (ROOT/'commerce/qa/collection-soak-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))

if __name__=='__main__':main()
