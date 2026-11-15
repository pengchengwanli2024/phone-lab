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
        subprocess.run([sys.executable,str(ROOT/'commerce/qa/seed_intel_workspace.py'),folder],check=True,capture_output=True)
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
            source=call('commerce_intel_search',{'source':'wto'})['items'][0]
            doc=call('commerce_intel_article_list',{'item_id':source['id']})['articles'][0]
            base=doc['article']['translation']['zh_sha256']
            args={'article_id':doc['id'],'operation':'recheck','idempotency_key':'synthetic-recheck','base_sha256':base}
            checked=call('commerce_intel_article_record',args);assert checked==call('commerce_intel_article_record',args)
            revised=call('commerce_intel_article_record',dict(args,operation='revision',idempotency_key='synthetic-revision',zh='合成中文修订 25 USD。',note='Synthetic fixture correction'))
            assert revised['status']=='pending_review'
            records=call('commerce_intel_article_reviews',{'article_id':doc['id']})['records'];assert len(records)==2
            original=call('commerce_intel_article_get',{'article_id':doc['id']})
            assert original['article']==doc['article']
            print(json.dumps({'status':'passed','transport':'fresh stdio MCP','synthetic':True,'append_only_records':len(records),'original_unchanged':True,'human_approval_fabricated':False}))
        finally:
            process.terminate();process.wait(timeout=5)
            runtime=Path(folder)/'runtime.json'
            if runtime.exists():
                try:os.kill(json.loads(runtime.read_text())['pid'],15)
                except ProcessLookupError:pass


if __name__=='__main__':main()
