"""Synthetic schedule transaction/native event preservation checks."""
from concurrent.futures import ThreadPoolExecutor
import hashlib,json
from pathlib import Path
from types import SimpleNamespace
import sys,tempfile,time,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'commerce'),str(ROOT/'crawlers')]
from service import Commerce
from collection_registry import REGISTRY
from collection_jobs import CollectionJobs,save
from collection_state import evolve
from native_feed_capture import persist,load
from intelligence import parse
from worker import Result

class Schedules(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name);self.jobs=self.app.collections
    def tearDown(self):self.jobs.stop();self.temp.cleanup()
    def test_all_eight_sources_share_durable_queue(self):
        result=self.jobs.schedule_tick(True,900,1000)
        self.assertEqual(len(self.jobs.listing()['jobs']),8)
        self.assertEqual(set(result['sources']),set(REGISTRY))
        self.assertIsNone(result['last_success'])
        self.assertTrue(all(j['trigger']=='schedule' for j in self.jobs.listing()['jobs']))
        self.jobs.schedule_tick(True,900,1001)
        self.assertEqual(len(self.jobs.listing()['jobs']),8)
    def test_concurrent_timers_and_manual_overlap_do_not_duplicate(self):
        self.jobs.request('federal-reserve-press','manual-first')
        peer=CollectionJobs(self.app.core,self.app.state)
        with ThreadPoolExecutor(2) as pool:list(pool.map(lambda j:j.schedule_tick(True,900,1000),[self.jobs,peer]))
        self.assertEqual(len(self.jobs.listing()['jobs']),8)
        self.assertEqual(sum(j['source']=='federal-reserve-press' for j in self.jobs.listing()['jobs']),1)
    def test_disable_keeps_receipts_and_never_enqueues(self):
        self.jobs.schedule_tick(False,900,1000);self.assertEqual(self.jobs.listing()['jobs'],[])
    def test_failure_pacing_and_queued_cancel_are_not_replayed_same_slot(self):
        self.jobs.schedule_tick(True,900,1000)
        for job in self.jobs.listing()['jobs']:self.jobs.cancel(job['id'])
        self.jobs.schedule_tick(True,900,1001)
        self.assertEqual(len(self.jobs.listing()['jobs']),8)
        self.jobs.schedule_tick(True,900,1900)
        self.assertEqual(len(self.jobs.listing()['jobs']),16)
    def test_autonomy_dispatch_is_nonblocking_and_does_not_legacy_fetch(self):
        self.app.autonomy.configure(True)
        with patch('intelligence.fetch',side_effect=AssertionError('duplicate legacy fetch')):
            self.app.autonomy.tick(at=1000)
        self.assertEqual(len(self.jobs.listing()['jobs']),8)
        self.assertEqual(self.app.autonomy.status()['public_collection']['result']['usgs']['status'],'queued')
    def test_native_event_snapshot_keeps_geolocation_identity_and_single_route_label(self):
        cache=Path(self.temp.name)/'native'
        data=json.dumps({'type':'FeatureCollection','features':[{'id':'synthetic','properties':{'title':'Synthetic earthquake','url':'https://example.org/quake','time':1700000000000},'geometry':{'coordinates':[110,30,10]}}]}).encode()
        rows=parse('usgs',data);out=Result(SimpleNamespace(kind='native-usgs',engine='native-intel'))
        out.add_page(REGISTRY['usgs']['url'],rows,data,format='native-publisher')
        out.native_capture={'payload':data.decode(),'payload_sha256':hashlib.sha256(data).hexdigest(),'captured_at':out.pages[0]['captured_at']}
        persist(REGISTRY['usgs'],out.finish(),cache)
        _,loaded,_=load('usgs',cache)
        self.assertEqual(loaded[0]['id'],rows[0]['id']);self.assertEqual(loaded[0]['location'],{'lon':110.,'lat':30.})
        self.assertEqual(loaded[0]['collection_mode'],'single_client_native_feed')
        with patch('native_feed_capture.CACHE',cache):self.app.intelligence.import_collection('usgs')
        self.assertEqual(self.app.intelligence.store.item(rows[0]['id'])['location'],rows[0]['location'])

if __name__=='__main__':unittest.main()
