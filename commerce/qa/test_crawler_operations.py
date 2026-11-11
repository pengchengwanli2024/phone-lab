"""Bounded operations checks. No public traffic, notifications or credentials."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'commerce'),str(ROOT/'crawlers')]
from collection_jobs import CollectionJobs
from commerce_core import Core
from rate_limit import reserve,outcome
from collect import execute


class CrawlerOperations(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        def command(value,output):return [sys.executable,'-c','import pathlib;pathlib.Path('+repr(str(output))+').write_text('+repr('{"status":"failed","completed_sources":[]}')+')']
        self.jobs=CollectionJobs(Core(self.root/'state.sqlite'),self.root,command_builder=command)
    def tearDown(self):self.jobs.stop();self.temp.cleanup()
    def test_persistent_host_spacing_and_exponential_backoff(self):
        path=self.root/'rate.sqlite';url='https://example.org/public'
        self.assertEqual(reserve(url,path,100),0);self.assertEqual(reserve(url,path,101),1)
        outcome(url,True,path,102);self.assertEqual(reserve(url,path,103),9)
        outcome(url,True,path,104);self.assertEqual(reserve(url,path,105),19)
        outcome(url,False,path,106);self.assertEqual(reserve(url,path,107),17)
    def test_cooldown_alert_survives_reopen_and_ack(self):
        job=self.jobs.request('federal-reserve-press','synthetic-fail');self.jobs.work_once()
        self.assertEqual(self.jobs.get(job['id'])['status'],'failed')
        alert=self.jobs.listing()['alerts'][0]
        newer=CollectionJobs(self.jobs.core,self.root)
        self.assertEqual(newer.listing()['alerts'][0]['status'],'open')
        newer.acknowledge(alert['id']);self.assertEqual(self.jobs.listing()['alerts'][0]['status'],'acknowledged')
        retry=self.jobs.retry(job['id'])
        self.assertGreaterEqual(retry['not_before'],job['created_at']+89)
        self.assertFalse(self.jobs.work_once())
    def test_quota_stops_new_process_and_creates_alert(self):
        with (self.jobs.directory/'synthetic-sparse').open('wb') as output:output.truncate(200_000_001)
        job=self.jobs.request('federal-reserve-press','synthetic-quota');self.jobs.work_once()
        self.assertEqual(self.jobs.get(job['id'])['error'],'collection_evidence_quota_reached')
        self.assertEqual(len(self.jobs.listing()['alerts']),1)
    def test_memory_observation_kills_only_owned_route(self):
        route={'id':'synthetic','engine':'json-http','url':'http://127.0.0.1:9/synthetic'}
        with patch('resource_limits.group_rss_kib',return_value=2*1024*1024):
            result=execute(route,dict(kind='products',max_pages=1),self.root,5)
        self.assertEqual(result['errors'],['worker_memory_limit'])
    def test_os_file_and_cpu_limits_in_fixed_wrapper(self):
        code="import runpy,resource,json;original=runpy.run_path;runpy.run_path=lambda *a,**k:print(json.dumps([resource.getrlimit(resource.RLIMIT_CPU)[0],resource.getrlimit(resource.RLIMIT_FSIZE)[0],resource.getrlimit(resource.RLIMIT_NOFILE)[0]]));original("+repr(str(ROOT/'crawlers/route_worker.py'))+")"
        done=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=10)
        self.assertEqual(json.loads(done.stdout),[120,8*1024*1024,1024])


if __name__=='__main__':unittest.main()
