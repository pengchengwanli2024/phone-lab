"""Opt-in publisher article + configured translation smoke through fresh MCP."""
import json,os,socket,subprocess,sys,tempfile,time
from contextlib import nullcontext
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def main():
    live=os.environ.get('COMMERCE_ARTICLE_SMOKE_LIVE')=='1'
    with (nullcontext(str(ROOT/'.commerce-state')) if live else tempfile.TemporaryDirectory(prefix='article-mcp-')) as folder:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=38731 if live else sock.getsockname()[1]
        process=subprocess.Popen([sys.executable,str(ROOT/'commerce/mcp_server.py')],env=dict(os.environ,COMMERCE_STATE=folder,COMMERCE_PORT=str(port)),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        seq=0
        def rpc(method,params=None):
            nonlocal seq
            seq+=1;process.stdin.write(json.dumps(dict(jsonrpc='2.0',id=seq,method=method,params=params or {}))+'\n');process.stdin.flush()
            value=json.loads(process.stdout.readline());assert not value.get('error'),value
            return value['result']
        def call(name,args=None):
            value=rpc('tools/call',dict(name=name,arguments=args or {}));assert not value.get('isError'),value
            return json.loads(value['content'][0]['text'])
        try:
            rpc('initialize');tools={t['name']:t for t in rpc('tools/list')['tools']}
            assert tools['commerce_intel_article_get']['annotations']['readOnlyHint']
            call('commerce_intel_refresh',{'source':'fed'})
            item=call('commerce_intel_search',{'source':'fed','limit':'20'})['items'][0]
            args=dict(item_id=item['id'],record_sha256=item['record_sha256'],idempotency_key='article-live-smoke')
            doc=call('commerce_intel_article_start',args)
            assert call('commerce_intel_article_start',args)['id']==doc['id']
            end=time.monotonic()+65
            while doc['status'] in ('queued','running') and time.monotonic()<end:
                time.sleep(.4);doc=call('commerce_intel_article_get',{'article_id':doc['id']})
            assert doc['status']=='ready',doc.get('error')
            original=doc['article']['content_sha256']
            doc=call('commerce_intel_article_translate',{'article_id':doc['id']});end=time.monotonic()+180
            while doc['translation_status']=='running' and time.monotonic()<end:
                time.sleep(.5);doc=call('commerce_intel_article_get',{'article_id':doc['id']})
            assert doc['translation_status']=='pending_review',doc.get('error')
            translated=doc['article']['translation']
            assert translated['original_sha256']==original and translated['independently_verified'] is False
            assert all(r['tools_enabled'] is False and r['model'] for r in translated['model_receipts'])
            summary=dict(status='passed',transport='fresh stdio MCP',source='fed',
                         original_characters=len(doc['article']['text']),translated_characters=len(translated['zh']),
                         routes=doc['article']['routes'],translation_status='pending_review',
                         numeric_warning_count=len(translated['warnings']),model_receipts=len(translated['model_receipts']),
                         tools_enabled=False,store_calls=False,independently_verified=False)
            (ROOT/'commerce/qa/article-mcp-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
        finally:
            process.terminate();process.wait(timeout=5)
            runtime=Path(folder)/'runtime.json'
            if runtime.exists() and not live:
                try:os.kill(json.loads(runtime.read_text())['pid'],15)
                except ProcessLookupError:pass

if __name__=='__main__':main()
