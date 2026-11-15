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
        sys.path.insert(0,str(ROOT/'commerce'))
        from service import Commerce
        from collection_jobs import save
        from collection_state import evolve
        app=Commerce(folder)
        for i in range(5):
            j=app.collections.request('federal-reserve-press','synthetic-archive-'+str(i));j=evolve(evolve(j,'start',time.time()-7200,attempt=1),'finish_ok',time.time()-7100,attempt=1);j['finished_at']=time.time()-7100
            with app.core.db() as db:save(db,j)
            directory=Path(folder)/'collection-jobs'/j['id']/'1';directory.mkdir(parents=True);(directory/'result.json').write_bytes(b'S'*180000)

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
            before=call('commerce_crawler_storage')
            archived=call('commerce_crawler_archive');assert archived['archived']==3
            after=call('commerce_crawler_storage');assert len(after['archives'])==3
            for receipt in after['archives']:assert call('commerce_crawler_archive_verify',{'archive_id':receipt['id']})['status']=='verified'
            assert after['capacity']['used_bytes']<before['capacity']['used_bytes']
            assert call('commerce_crawler_endurance_status')['formal_acceptance'] is False
            print(json.dumps({'status':'passed','transport':'fresh stdio MCP','synthetic':True,'verified_archives':3,'capacity_reduced':True,'premature_endurance_acceptance':False}))
        finally:
            process.terminate();process.wait(timeout=5)
            runtime=Path(folder)/'runtime.json'
            if runtime.exists():
                try:os.kill(json.loads(runtime.read_text())['pid'],15)
                except ProcessLookupError:pass


if __name__=='__main__':main()
