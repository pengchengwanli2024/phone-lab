"""Actual HTTP/stdio follow-up persistence with temporary synthetic state only."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


class FollowupTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory();cls.state = Path(cls.temp.name)/'state';cls.state.mkdir()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.origin='http://127.0.0.1:'+str(cls.port)
        cls.env={**os.environ,'COMMERCE_STATE':str(cls.state),'COMMERCE_PORT':str(cls.port)}
        cls.start()

    @classmethod
    def start(cls):
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'qa/fixture_followups.py')],env=cls.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        end=time.monotonic()+10
        while time.monotonic()<end:
            try:cls.call('commerce_followup_targets');return
            except OSError:time.sleep(.05)
        raise AssertionError('isolated follow-up service did not start')

    @classmethod
    def stop(cls):
        if cls.process.poll() is None:cls.process.terminate();cls.process.wait(timeout=8)

    @classmethod
    def tearDownClass(cls):
        cls.stop();cls.temp.cleanup()

    @classmethod
    def call(cls,name,args=None):
        request=urllib.request.Request(cls.origin+'/v1/invoke',data=json.dumps({'tool':name,'arguments':args or {},'client':'test'}).encode(),headers={'Authorization':'Bearer synthetic-followup-only','Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=8) as response:return json.load(response)

    def mcp(self,client,messages):
        result=subprocess.run([sys.executable,str(ROOT/'mcp_server.py'),client],env=self.env,
            input=''.join(json.dumps(m)+'\n'for m in [{'jsonrpc':'2.0','id':0,'method':'initialize','params':{}},*messages]),
            capture_output=True,text=True,check=True,timeout=15)
        return [json.loads(line)['result'] for line in result.stdout.splitlines()][1:]

    def test_client_discovery_and_cross_client_booking_preserve_original_work(self):
        before=self.call('commerce_task_list')
        target=next(v['target']for v in self.call('commerce_followup_targets')['targets']if v['target']['kind']=='public_source'and v['target']['ref']=='usgs')
        due=datetime.fromtimestamp(time.time()+3600,timezone.utc).isoformat()
        listing,created=self.mcp('codex',[{'jsonrpc':'2.0','id':1,'method':'tools/list'},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'commerce_followup_create','arguments':{'target':target,'due_at':due,'idempotency_key':'native-mcp-once'}}}])
        catalog={v['name']:v for v in listing['tools']}
        for name in ('targets','get','list'):self.assertTrue(catalog['commerce_followup_'+name]['annotations']['readOnlyHint'])
        for name in ('create','cancel','ack','reschedule'):self.assertFalse(catalog['commerce_followup_'+name]['annotations']['readOnlyHint'])
        self.assertFalse(created['isError']);saved=created['structuredContent']
        got=self.mcp('hermes',[{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'commerce_followup_get','arguments':{'followup_id':saved['id']}}}])[0]
        self.assertEqual(got['structuredContent']['id'],saved['id'])
        cancelled=self.mcp('harness',[{'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'commerce_followup_cancel','arguments':{'followup_id':saved['id'],'expected_revision':saved['revision']}}}])[0]
        self.assertEqual(cancelled['structuredContent']['state'],'cancelled')
        self.assertEqual(self.call('commerce_task_list'),before)

    def test_real_service_restart_retains_one_due_check_and_never_replays_original_work(self):
        target=next(v['target']for v in self.call('commerce_followup_targets')['targets']if v['target']['kind']=='public_source'and v['target']['ref']=='gdacs')
        value=self.call('commerce_followup_create',{'target':target,'due_at':datetime.fromtimestamp(time.time()+2,timezone.utc).isoformat(),'idempotency_key':'real-restart'})
        self.stop();self.start()
        end=time.monotonic()+8
        while time.monotonic()<end:
            current=self.call('commerce_followup_get',{'followup_id':value['id']})
            if current['state']=='checked':break
            time.sleep(.1)
        self.assertEqual(current['state'],'checked')
        revision=current['revision'];self.stop();self.start()
        self.assertEqual(self.call('commerce_followup_get',{'followup_id':value['id']})['revision'],revision)

    def test_three_clients_read_the_same_original_timeline_and_chain_allowance(self):
        run=next(r for r in self.call('commerce_agent_list')['runs']if r['status']=='awaiting_review')
        expected_timeline=self.call('commerce_task_timeline_get',{'kind':'run','id':run['id']})
        expected_budget=self.call('commerce_chain_budget_get',{'run_id':run['id']})
        self.assertEqual(expected_budget['usage']['model_steps'],2)
        before=self.call('commerce_task_list')
        for client in ('codex','hermes','harness'):
            replies=self.mcp(client,[{'jsonrpc':'2.0','id':1,'method':'tools/list'},
                {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'commerce_task_timeline_get','arguments':{'kind':'run','id':run['id']}}},
                {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'commerce_chain_budget_get','arguments':{'run_id':run['id']}}}])
            catalog={v['name']:v for v in replies[0]['tools']}
            for name in ('commerce_task_timeline_get','commerce_chain_budget_get'):self.assertTrue(catalog[name]['annotations']['readOnlyHint'])
            self.assertEqual(replies[1]['structuredContent'],expected_timeline)
            self.assertEqual(replies[2]['structuredContent'],expected_budget)
        self.assertEqual(self.call('commerce_task_list'),before)


if __name__=='__main__':unittest.main()
