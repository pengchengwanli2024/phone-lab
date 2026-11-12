"""Synthetic integration acceptance: auth, cross-client state and scoped notes."""
import importlib.util
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from service import Commerce


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.state=Path(cls.tmp.name)/'state';cls.state.mkdir()
        cls.token='synthetic-test-only-local-token';(cls.state/'auth.token').write_text(cls.token)
        with socket.socket()as s:s.bind(('127.0.0.1',0));cls.port=s.getsockname()[1]
        cls.origin=f'http://127.0.0.1:{cls.port}'
        cls.env=dict(os.environ,COMMERCE_STATE=str(cls.state),COMMERCE_PORT=str(cls.port))
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'server.py')],env=cls.env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(80):
            try:cls.call('commerce_status',{});break
            except Exception:time.sleep(.05)
        else:raise RuntimeError('test service did not start')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.process.stderr.close();cls.tmp.cleanup()

    @classmethod
    def call(cls,tool,args,client='test',headers=None):
        req=urllib.request.Request(cls.origin+'/v1/invoke',data=json.dumps({'tool':tool,'arguments':args,'client':client}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+cls.token,**(headers or{})})
        with urllib.request.urlopen(req,timeout=5)as response:return json.load(response)

    def test_auth_and_browser_origin(self):
        for headers,status in [({'Authorization':'Bearer invalid'},401),({'Origin':'https://foreign.example'},403),({'Host':'foreign.example'},403)]:
            with self.assertRaises(urllib.error.HTTPError)as e:self.call('commerce_status',{},headers=headers)
            self.assertEqual(e.exception.code,status);e.exception.close()
        with self.assertRaises(urllib.error.HTTPError)as e:urllib.request.urlopen(self.origin)
        self.assertEqual(e.exception.code,401);e.exception.close()
        request=urllib.request.Request(self.origin,headers={'Authorization':'Bearer '+self.token})
        with urllib.request.urlopen(request)as response:page=response.read().decode()
        self.assertNotIn(self.token,page);self.assertIn('commerce_dashboard',page);self.assertNotIn('INLINE_APP',page)

    def test_live_and_demo_are_distinct(self):
        live=self.call('commerce_dashboard',{});self.assertIsNone(live['sales']);self.assertEqual(live['platforms'],[])
        demo=self.call('commerce_dashboard',{'demo':True});self.assertEqual(demo['sales'],128640);self.assertEqual(sum(x['amount']for x in demo['platforms']),demo['sales'])
        totals=[self.call('commerce_dashboard',{'demo':True,'platform':p})for p in ['ozon','tiktok','amazon','mercado','temu']]
        self.assertEqual(sum(x['orders']for x in totals),demo['orders']);self.assertEqual(sum(x['pending']for x in totals),32)
        status=self.call('commerce_status',{});self.assertFalse(status['marketplace_writes']);self.assertEqual(len(status['platforms']),5)
        self.assertEqual(len(status['agent_team']['roles']),12)
        self.assertEqual(status['agent_team']['deployment']['phase'],'mac-integration')

    def test_parallel_reads_no_resets(self):
        with ThreadPoolExecutor(max_workers=20)as pool:
            values=list(pool.map(lambda _:self.call('commerce_dashboard',{'demo':True}),range(80)))
        self.assertEqual(len(values),80)
        self.assertTrue(all(v['sales']==128640 for v in values))

    def test_filter_inventory_identity(self):
        all_products=self.call('commerce_products_list',{'demo':True})['products']
        for p in all_products:
            selected=self.call('commerce_products_list',{'demo':True,'platform':p['platform']})['products'][0]
            self.assertEqual(selected['available'],p['available'])
        self.assertEqual(self.call('commerce_orders_list',{'demo':True,'query':'CUP-014'})['total'],1)
        self.assertEqual(self.call('commerce_orders_list',{})['total'],0)
        self.assertEqual(self.call('commerce_dashboard',{'demo':True,'market':'US'})['sales'],63440)
        self.assertEqual(self.call('commerce_orders_list',{'demo':True,'store_id':'ozon-demo'})['total'],1)
        self.assertEqual(self.call('commerce_dashboard',{'demo':True,'platform':'amazon','market':'MX'})['sales'],0)

    def test_http_cross_client_tasks(self):
        args={'kind':'analysis','idempotency_key':'cross-http','input':{'title':'synthetic shared task'}}
        a=self.call('commerce_task_create',args,'hermes');b=self.call('commerce_task_create',args,'codex');self.assertEqual(a['id'],b['id'])
        self.assertEqual(self.call('commerce_task_get',{'task_id':a['id']},'harness')['status'],'queued')
        self.call('commerce_task_cancel',{'task_id':a['id']},'codex')
        self.assertEqual(self.call('commerce_task_get',{'task_id':a['id']},'hermes')['status'],'cancelled')
        with self.assertRaises(urllib.error.HTTPError)as e:self.call('commerce_task_create',{**args,'kind':'draft'})
        e.exception.close()
        for name,args in [('commerce_refund',{}),('commerce_dashboard',{'demo':'true'}),('commerce_status',{'unexpected':True})]:
            with self.assertRaises(urllib.error.HTTPError)as e:self.call(name,args)
            e.exception.close()

    def rpc(self,p,message):
        p.stdin.write(json.dumps(message)+'\n');p.stdin.flush()
        ready,_,_=select.select([p.stdout],[],[],15)
        self.assertTrue(ready,'MCP response deadline')
        return json.loads(p.stdout.readline())

    def test_three_stdio_clients_share_one_service(self):
        clients=[]
        try:
            for name in ['codex','hermes','harness']:
                p=subprocess.Popen([sys.executable,str(ROOT/'mcp_server.py'),name],env=self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1);clients.append(p)
                hello=self.rpc(p,{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'synthetic-'+name,'version':'1'}}})
                self.assertEqual(hello['result']['serverInfo']['name'],'commerce-backend')
                tools=self.rpc(p,{'jsonrpc':'2.0','id':2,'method':'tools/list'})['result']['tools'];self.assertGreaterEqual(len(tools),10)
            task=self.rpc(clients[0],{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'commerce_task_create','arguments':{'kind':'draft','idempotency_key':'three-mcp-clients'}}})['result']['structuredContent']
            for p in clients[1:]:
                found=self.rpc(p,{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'commerce_task_get','arguments':{'task_id':task['id']}}})['result']['structuredContent'];self.assertEqual(found['id'],task['id'])
            self.rpc(clients[1],{'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'commerce_task_cancel','arguments':{'task_id':task['id']}}})
            found=self.rpc(clients[2],{'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'commerce_task_get','arguments':{'task_id':task['id']}}})['result']['structuredContent'];self.assertEqual(found['status'],'cancelled')
        finally:
            for p in clients:
                p.terminate();p.wait(timeout=5)
                for stream in [p.stdin,p.stdout,p.stderr]:stream.close()


class ScopedKnowledge(unittest.TestCase):
    def test_scope_search_and_idempotent_archive(self):
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp);state=root/'state';notes=root/'business';notes.mkdir();outside=root/'private.md';outside.write_text('out-of-scope synthetic canary')
            app=Commerce(state);(state/'config.json').write_text(json.dumps({'knowledge_root':str(notes)}))
            (notes/'SOP.md').write_text('# Synthetic SOP\n交运前核对包装。')
            (notes/'link.md').symlink_to(outside)
            self.assertEqual(app.invoke('commerce_knowledge_list',{})['notes'],['SOP.md'])
            self.assertEqual(len(app.invoke('commerce_knowledge_search',{'query':'包装'})['hits']),1)
            for value in ['../private.md','link.md',str(outside)]:
                with self.assertRaises(ValueError):app.invoke('commerce_knowledge_read',{'path':value})
            report=app.invoke('commerce_report_create',{'demo':True,'idempotency_key':'archive'})
            for _ in range(2):self.assertTrue(app.invoke('commerce_summary_save',{'report_id':report['id']})['saved'])
            self.assertEqual(len(app.invoke('commerce_knowledge_list',{})['notes']),2)
            self.assertEqual(outside.read_text(),'out-of-scope synthetic canary')


if __name__=='__main__':unittest.main(verbosity=2)
