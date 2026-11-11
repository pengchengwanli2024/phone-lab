"""Kill an owned controller mid-request; real worker must obey the durable fence."""
import json,os,signal,subprocess,sys,tempfile,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'commerce'),str(ROOT/'crawlers')]


def controller(folder,port):
    from commerce_core import Core
    from collection_jobs import CollectionJobs
    folder=Path(folder);jobs=None
    def command(value,output):
        return [str(ROOT/'.local/crawlers/venv/bin/python'),__file__,'--worker',str(folder),str(port),value['id'],str(value['attempt']),jobs.owner,str(output)]
    jobs=CollectionJobs(Core(folder/'state.sqlite'),folder,command_builder=command)
    job=jobs.request('federal-reserve-press','synthetic-crash')
    (folder/'job.json').write_text(json.dumps(job));jobs.work_once()


def worker(folder,port,job,attempt,owner,output):
    import crawler_feed_bridge
    crawler_feed_bridge.CACHE=Path(folder)/'synthetic-snapshots'
    from job_worker import REGISTRY,run
    REGISTRY['federal-reserve-press']['url']='http://127.0.0.1:'+port+'/synthetic-feed'
    (Path(folder)/'owned-worker.pid').write_text(str(os.getpid()))
    return run(str(Path(folder)/'state.sqlite'),job,int(attempt),owner,Path(output))


class CrashRecovery(unittest.TestCase):
    def test_real_controller_death_stops_route_and_preserves_interrupted(self):
        from commerce_core import Core
        from collection_jobs import CollectionJobs
        received=threading.Event();release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                received.set();release.wait(15)
                try:self.send_response(503);self.end_headers()
                except (BrokenPipeError,ConnectionResetError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        with tempfile.TemporaryDirectory(prefix='crawler-crash-') as folder:
            folder=Path(folder)
            child=subprocess.Popen([str(ROOT/'.local/crawlers/venv/bin/python'),__file__,'--controller',str(folder),str(server.server_port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            owned=None;recovery=None
            try:
                self.assertTrue(received.wait(12),'owned route never reached local fixture')
                owned=int((folder/'owned-worker.pid').read_text())
                child.kill();child.wait(timeout=5)
                recovery=CollectionJobs(Core(folder/'state.sqlite'),folder)
                recovery.start(recover=True)
                job=json.loads((folder/'job.json').read_text())
                self.assertEqual(recovery.get(job['id'])['status'],'interrupted')
                output=folder/'collection-jobs'/job['id']/'1/result.json';end=time.monotonic()+10
                while not output.exists() and time.monotonic()<end:time.sleep(.05)
                self.assertTrue(output.exists(),'old worker did not stop after ownership fence')
                self.assertEqual(json.loads(output.read_text())['status'],'cancelled')
                self.assertFalse((folder/'synthetic-snapshots').exists())
                self.assertEqual(len(recovery.listing()['alerts']),1)
            finally:
                if recovery:recovery.stop()
                if child.poll() is None:child.kill();child.wait(timeout=5)
                if owned:
                    try:os.killpg(owned,signal.SIGTERM)
                    except ProcessLookupError:pass
                release.set();server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--controller':controller(*sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='--worker':raise SystemExit(worker(*sys.argv[2:]))
    else:unittest.main()
