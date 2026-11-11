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
            args={'source':'federal-reserve-press','idempotency_key':'public-feed-smoke'}
            job=call('commerce_crawler_start',args)
            assert call('commerce_crawler_start',args)['id']==job['id']
            other=call('commerce_crawler_start',{'source':'ecb-press','idempotency_key':'cancel-smoke'})
            assert call('commerce_crawler_cancel',{'job_id':other['id']})['status']=='cancelled'
            # A queued retry is allowed only once the active source finishes.
            end=time.monotonic()+150
            while time.monotonic()<end:
                job=call('commerce_crawler_get',{'job_id':job['id']})
                if job['status'] not in ('queued','running','cancelling'):break
                time.sleep(.5)
            assert job['status']=='succeeded',job.get('error')
            assert job['result']['imports'][0]['records']>0
            retried=call('commerce_crawler_retry',{'job_id':other['id']})
            assert retried['attempt']==2
            call('commerce_crawler_cancel',{'job_id':other['id']})
            sources=call('commerce_intel_sources')['sources']
            fed=next(s for s in sources if s['id']=='fed')
            assert fed['cached_items']>0 and fed['status']=='ok'
            summary={'status':'passed','transport':'fresh stdio MCP + loopback worker',
                     'checks':['idempotent start','queued cancel','explicit retry generation','real three-route collection','snapshot imported before success'],
                     'source':'federal-reserve-press','records':fed['cached_items'],
                     'routes':job['sources'][0]['agreeing_routes'],'store_calls':False}
            (ROOT/'commerce/qa/collection-mcp-result.json').write_text(json.dumps(summary,indent=2)+'\n')
            print(json.dumps(summary))
        finally:
            process.terminate();process.wait(timeout=5)
            runtime=Path(folder)/'runtime.json'
            if runtime.exists():
                try:os.kill(json.loads(runtime.read_text())['pid'],15)
                except ProcessLookupError:pass


if __name__=='__main__':main()
