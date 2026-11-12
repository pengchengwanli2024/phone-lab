"""Real subprocess lifecycle using only an isolated synthetic local database."""
import json
from contextlib import closing
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


class Standalone(unittest.TestCase):
    def test_fresh_start_crash_recovery_mcp_and_private_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)/'state';state.mkdir()
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            env=dict(os.environ,COMMERCE_STATE=str(state),COMMERCE_PORT=str(port))
            base=f'http://127.0.0.1:{port}'
            processes=[]
            def command(action):
                done=subprocess.run([sys.executable,str(ROOT/'manage.py'),action],env=env,capture_output=True,text=True,timeout=20)
                self.assertEqual(done.returncode,0,done.stdout)
                return json.loads(done.stdout)
            def call(tool,args=None):
                req=urllib.request.Request(base+'/v1/invoke',data=json.dumps({'tool':tool,'arguments':args or {},'client':'test'}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+(state/'auth.token').read_text().strip()})
                with urllib.request.urlopen(req,timeout=5)as response:return json.load(response)
            def wait_for(predicate):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail('subprocess_runtime_condition_timeout')
            try:
                self.assertEqual(command('start')['status'],'ready')
                pid=json.loads((state/'runtime.json').read_text())['pid'];processes.append(pid)
                command('start');self.assertEqual(json.loads((state/'runtime.json').read_text())['pid'],pid)
                wait_for(lambda:call('commerce_runtime_status')['worker']=='running')
                self.assertEqual(command('doctor')['status'],'ready_local')
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+'/v1/health')
                self.assertEqual(error.exception.code,401);error.exception.close()
                task=call('commerce_task_create',{'kind':'report','input':{'demo':True},'idempotency_key':'synthetic-process-work'})
                call('commerce_task_execute',{'task_id':task['id'],'operation':'report'})
                wait_for(lambda:call('commerce_task_result',{'task_id':task['id']})['task']['status']=='completed')
                saved=call('commerce_task_result',{'task_id':task['id']})['execution']['result']['id']
                # Create an interrupted record, then kill the actual process.
                interrupted=call('commerce_task_create',{'kind':'report','idempotency_key':'synthetic-crash'})
                with closing(sqlite3.connect(state/'commerce.sqlite')) as db, db:
                    db.execute("UPDATE tasks SET status='running' WHERE id=?",(interrupted['id'],))
                    db.execute("INSERT INTO task_runs VALUES (?,'report',?, ?,NULL,'synthetic-dead-worker',?,NULL,NULL,1)",(interrupted['id'],time.time(),time.time(),time.time()+120))
                os.kill(pid,9)
                command('start');newpid=json.loads((state/'runtime.json').read_text())['pid'];processes.append(newpid)
                self.assertNotEqual(pid,newpid)
                wait_for(lambda:call('commerce_runtime_status')['worker']=='running')
                self.assertEqual(call('commerce_task_result',{'task_id':task['id']})['execution']['result']['id'],saved)
                self.assertEqual(call('commerce_task_result',{'task_id':interrupted['id']})['task']['status'],'interrupted')
                call('commerce_task_retry',{'task_id':interrupted['id']})
                wait_for(lambda:call('commerce_task_get',{'task_id':interrupted['id']})['status']=='completed')
                copy=command('backup');self.assertEqual(copy['integrity'],'ok')
                with closing(sqlite3.connect(state/'backups'/copy['file'])) as db:self.assertEqual(db.execute('SELECT count(*) FROM reports').fetchone()[0],2)
                # Fresh stdio client, independent of browser and host process.
                lines=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}}, {'jsonrpc':'2.0','id':2,'method':'tools/list'}, {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'commerce_task_result','arguments':{'task_id':task['id']}}}]
                for client in ('codex','hermes','harness'):
                    done=subprocess.run([sys.executable,str(ROOT/'mcp_server.py'),client],env=env,input=''.join(json.dumps(x)+'\n' for x in lines),capture_output=True,text=True,timeout=10)
                    answers=[json.loads(x) for x in done.stdout.splitlines()]
                    tools=answers[1]['result']['tools'];self.assertTrue(next(x for x in tools if x['name']=='commerce_runtime_status')['annotations']['readOnlyHint'])
                    self.assertEqual(answers[2]['result']['structuredContent']['task']['id'],task['id'])
                    self.assertFalse(answers[2]['result']['isError'])
            finally:
                for pid in processes:
                    try:os.kill(pid,15)
                    except ProcessLookupError:pass
                time.sleep(.2)


if __name__=='__main__':unittest.main(verbosity=2)
