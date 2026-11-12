"""Synthetic archive/capacity checks; all artifacts stay in a temporary state."""
from pathlib import Path
import sys,tempfile,time,unittest,uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from collection_jobs import CollectionJobs,save
from collection_state import evolve
from evidence_capacity import EvidenceCapacity

class Capacity(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.jobs=CollectionJobs(Core(self.root/'core.sqlite'),self.root)
        self.capacity=EvidenceCapacity(self.jobs.core,self.root,limit=300000,min_age=0,keep=1)
    def tearDown(self):self.tmp.cleanup()
    def artifact(self,status='succeeded'):
        job=self.jobs.request('federal-reserve-press',uuid.uuid4().hex)
        job=evolve(job,'start',time.time()-7200,attempt=1)
        job=evolve(job,'finish_ok' if status=='succeeded' else 'finish_error',time.time()-7100,attempt=1,error='synthetic_failure')
        job['finished_at']=time.time()-7100
        with self.jobs.core.db() as db:save(db,job)
        folder=self.jobs.directory/job['id']/'1';folder.mkdir(parents=True)
        (folder/'result.json').write_bytes(b'X'*180000)
        return job,folder
    def test_verified_archive_frees_duplicate_success_bytes_and_keeps_latest(self):
        old,folder=self.artifact();self.artifact();new,latest=self.artifact()
        result=self.capacity.maintain()
        self.assertEqual(result['capacity']['status'],'ok');self.assertEqual(result['archived'],2)
        self.assertFalse(folder.exists());self.assertTrue(latest.exists())
        for archive in self.capacity.listing()['archives']:self.assertEqual(self.capacity.verify(archive['id'])['status'],'verified')
    def test_failed_evidence_is_retained_even_when_above_limit(self):
        _,failed=self.artifact('failed');self.artifact();self.artifact()
        self.capacity.maintain(force=True)
        self.assertTrue((failed/'result.json').is_file())
        self.assertEqual(self.capacity.status()['status'],'blocked')
    def test_corrupt_or_interrupted_archive_never_removes_originals(self):
        _,folder=self.artifact();self.artifact()
        with patch.object(self.capacity,'verify_path',side_effect=ValueError('synthetic verification failure')):
            result=self.capacity.maintain(force=True)
        self.assertEqual(result['status'],'archive_failed_originals_retained');self.assertTrue(folder.exists())
    def test_symlink_is_blocked_and_not_followed(self):
        _,folder=self.artifact();self.artifact()
        (folder/'unsafe').symlink_to(self.root/'core.sqlite')
        self.assertEqual(self.capacity.maintain(force=True)['status'],'blocked')
        self.assertTrue((self.root/'core.sqlite').exists())
    def test_archive_tampering_is_detected(self):
        self.artifact();self.artifact();self.capacity.maintain(force=True)
        archive=self.capacity.listing()['archives'][0]
        (self.capacity.archives/(archive['id']+'.zip')).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'archive_invalid'):self.capacity.verify(archive['id'])
    def test_acknowledged_warning_rearms_after_pressure_clears(self):
        self.capacity.alerts({'status':'warning'})
        alert=next(a for a in self.jobs.listing()['alerts'] if a['job_id']=='storage')
        self.jobs.acknowledge(alert['id'])
        self.capacity.alerts({'status':'ok'});self.capacity.alerts({'status':'warning'})
        self.assertEqual(next(a for a in self.jobs.listing()['alerts'] if a['id']==alert['id'])['status'],'open')

if __name__=='__main__':unittest.main()
