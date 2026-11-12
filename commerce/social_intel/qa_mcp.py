"""Actual stdio MCP roundtrip against an isolated loopback service, synthetic data."""
import base64
import json
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_package import fixture
from test_store import seal

ROOT=Path(__file__).resolve().parents[2]

def main():
    with tempfile.TemporaryDirectory(prefix='social-mcp-') as raw:
        base=Path(raw);source=base/'source';source.mkdir();bundle=fixture(source)
        bundle['records'][0]['source']['url']='https://www.tiktok.com/@synthetic/video/1234567890123456789';seal(bundle)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        state=base/'state';env=dict(os.environ,COMMERCE_STATE=str(state),COMMERCE_PORT=str(port))
        child=subprocess.Popen([sys.executable,str(ROOT/'commerce/mcp_server.py'),'test'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,env=env)
        seq=0
        def rpc(method,params=None):
            nonlocal seq
            seq+=1;child.stdin.write(json.dumps({'jsonrpc':'2.0','id':seq,'method':method,'params':params or {}})+'\n');child.stdin.flush()
            with selectors.DefaultSelector() as sel:
                sel.register(child.stdout,selectors.EVENT_READ)
                if not sel.select(25):raise RuntimeError('isolated_mcp_timeout')
            response=json.loads(child.stdout.readline());assert not response.get('error'),response
            return response['result']
        def call(name,args=None,error=False):
            result=rpc('tools/call',{'name':name,'arguments':args or {}})
            if error:assert result['isError'];return result['content'][0]['text']
            assert not result.get('isError'),result
            return result['structuredContent']
        try:
            rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'social-acceptance','version':'1'}})
            tools={t['name']:t for t in rpc('tools/list')['tools']};names=[name for name in tools if name.startswith('commerce_social_')];assert len(names)==9
            assert tools['commerce_social_asset_read']['annotations']['readOnlyHint'];assert not tools['commerce_social_commit']['annotations']['readOnlyHint']
            stage=call('commerce_social_stage',{'bundle':bundle,'idempotency_key':'synthetic-mcp'})
            for a in bundle['assets']:
                data=(source/a['path']).read_bytes();upload={'stage_id':stage['stage_id'],'evidence_id':a['evidence_id'],'offset':'0','content_base64':base64.b64encode(data).decode()}
                assert not call('commerce_social_upload',upload)['replayed'];assert call('commerce_social_upload',upload)['replayed']
            args={'stage_id':stage['stage_id'],'idempotency_key':'synthetic-mcp','expected_heads':{}}
            receipt=call('commerce_social_commit',args);assert call('commerce_social_commit',args)==receipt
            assert call('commerce_social_search',{'view':'top'})['total']==1
            item=call('commerce_social_get',{'record_id':'synthetic-01'});r=item['record']
            marked=call('commerce_social_mark',{'record_id':r['record_id'],'record_sha256':r['record_sha256'],'action':'bookmark'});assert marked['is_bookmarked']
            task=call('commerce_social_review',{'record_id':r['record_id'],'record_sha256':r['record_sha256'],'idempotency_key':'codex-review'})
            other=call('commerce_social_review',{'record_id':r['record_id'],'record_sha256':r['record_sha256'],'idempotency_key':'hermes-review'});assert task['id']==other['id'] and task['status']=='queued'
            evidence=call('commerce_social_asset_read',{'batch_id':receipt['batch_id'],'evidence_id':'asset-01'});assert base64.b64decode(evidence['content_base64'])==data
            pack=call('commerce_social_export',{'batch_id':receipt['batch_id'],'format':'json'});assert json.loads(pack['content'])==bundle
            assert call('commerce_social_search',{'category':'ai'})['total']==0
            assert 'social_' in call('commerce_social_get',{'record_id':'missing'},error=True)
            result={'status':'passed','transport':'actual stdio MCP and isolated authenticated HTTP service','checks':['nine tools discovered and annotations checked','idempotent stage, chunk replay and commit','source-backed TOP query','shared record and bookmark','cross-client review deduplication','evidence bytes and portable export','truthful empty topic and error response'],'marketplace_calls':False}
            out=ROOT/'.local/social-intel/integration';out.mkdir(parents=True,exist_ok=True,mode=0o700);(out/'mcp-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
        finally:
            child.terminate();child.wait(timeout=5)
            if (state/'runtime.json').exists():
                try:os.kill(json.loads((state/'runtime.json').read_text())['pid'],15)
                except ProcessLookupError:pass

if __name__=='__main__':main()
