"""Opt-in real public feed smoke through fresh stdio MCP; no store calls."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    with tempfile.TemporaryDirectory(prefix='collection-mcp-') as folder:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=dict(os.environ,COMMERCE_STATE=folder,COMMERCE_PORT=str(port))
        process=subprocess.Popen([sys.executable,str(ROOT/'commerce/mcp_server.py')],env=env,
                                 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        seq=0
        def rpc(method,params=None):
            nonlocal seq
            seq+=1;process.stdin.write(json.dumps({'jsonrpc':'2.0','id':seq,'method':method,'params':params or {}})+'\n');process.stdin.flush()
            response=json.loads(process.stdout.readline())
            if response.get('error'):raise RuntimeError(response['error'])
            return response['result']
        def call(name,args=None):
            result=rpc('tools/call',{'name':name,'arguments':args or {}})
            assert not result.get('isError'),result
            return json.loads(result['content'][0]['text'])
        try:
            rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'public-feed-smoke','version':'1'}})
            tools={t['name']:t for t in rpc('tools/list')['tools']}
            assert tools['commerce_crawler_get']['annotations']['readOnlyHint']
            call('commerce_runtime_configure',{'enabled':True,'interval_seconds':'900'})
            end=time.monotonic()+300
            jobs=[]
            while time.monotonic()<end:
                jobs=call('commerce_crawler_list')['jobs']
                if len(jobs)==8 and all(j['status'] not in ('queued','running','cancelling') for j in jobs):break
                time.sleep(.5)
            assert len(jobs)==8 and all(j['trigger']=='schedule' for j in jobs)
            assert len({j['source'] for j in jobs})==8
            assert all(j['status'] not in ('queued','running','cancelling') for j in jobs)
            status=call('commerce_runtime_status')['public_collection']
            assert len(status['result'])==8
            summary={'status':'passed' if all(j['status']=='succeeded' for j in jobs) else 'partial',
                     'source_jobs':{j['source']:{'status':j['status'],'error':j.get('error'),'records':sum(i['records'] for i in j['sources'])} for j in jobs},
                     'scheduled_jobs':len(jobs),'duplicate_jobs':len(jobs)-len({j['source'] for j in jobs}),
                     'last_all_success_present':status['last_success'] is not None,'transport':'fresh stdio MCP','store_calls':False}
            (ROOT/'commerce/qa/schedule-mcp-result.json').write_text(json.dumps(summary,indent=2)+'\n')
            print(json.dumps(summary))
        finally:
            process.terminate();process.wait(timeout=5)
            runtime=Path(folder)/'runtime.json'
            if runtime.exists():
                try:os.kill(json.loads(runtime.read_text())['pid'],15)
                except ProcessLookupError:pass


if __name__=='__main__':main()
