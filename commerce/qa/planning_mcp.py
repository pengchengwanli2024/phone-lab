"""Native stdio MCP acceptance across clients, isolated state and synthetic upstreams."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='commerce-mcp-planning-') as temp:
    state=Path(temp)/'state';state.mkdir();secret='synthetic-mcp-planning-session';(state/'auth.token').write_text(secret)
    with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    env={**os.environ,'COMMERCE_STATE':str(state),'COMMERCE_PORT':str(port)};origin=f'http://127.0.0.1:{port}'
    server=subprocess.Popen([sys.executable,str(ROOT/'qa/live_http_fixture.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def post(route,data):
        request=urllib.request.Request(origin+route,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+secret})
        with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)
    def mcp(client,method,params):
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','id':2,'method':method,'params':params}]
        done=subprocess.run([sys.executable,str(ROOT/'mcp_server.py'),client],env=env,input=''.join(json.dumps(m)+'\n'for m in messages),capture_output=True,text=True,timeout=15,check=True)
        result=json.loads(done.stdout.splitlines()[-1])['result']
        if method=='tools/call':assert not result.get('isError');return result['structuredContent']
        return result
    def call(client,name,arguments=None):return mcp(client,'tools/call',{'name':name,'arguments':arguments or {}})
    try:
        for _ in range(100):
            try:post('/v1/invoke',{'tool':'commerce_status'});break
            except Exception:time.sleep(.05)
        else:raise AssertionError('isolated service unavailable')
        tools={t['name']:t for t in mcp('codex','tools/list',{})['tools']}
        for name in ('readiness','restock_list','restock_save','restock_export'):
            tool=tools['commerce_live_'+name];assert tool['annotations']['readOnlyHint']==(name!='restock_save');assert not tool['annotations']['openWorldHint']
        post('/v1/connections/save',{'ozon_client_id':'123456','ozon_api_key':'synthetic-mcp-not-network-key','fulfillment_modes':['OGL']})
        call('codex','commerce_live_sync')
        for _ in range(100):
            if call('codex','commerce_live_status')['last_job']['status']!='running':break
            time.sleep(.02)
        post('/v1/connections/save',{'orders_scope_confirmed':True,'stock_basis':'present_minus_reserved','basis_confirmed':True})
        row=call('codex','commerce_live_restock_list')['candidates'][0]
        plan=call('codex','commerce_live_restock_save',{'row_key':row['key'],'source_sha256':row['source_sha256'],'input':{'sold_units':60,'window_days':30,'lead_time_days':14,'safety_days':7,'pack_size':6,'inbound_units':0,'source_ref':'synthetic:sales.csv row 2','demand_observed_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()},'idempotency_key':'synthetic-shared-draft'})
        assert plan['current_result']['suggested_qty']==42
        shared=call('hermes','commerce_live_restock_list');assert shared['plans'][0]['id']==plan['id']
        exported=json.loads(call('hermes','commerce_live_restock_export',{'plan_id':plan['id']})['content']);assert exported['plan']['stock']['key']==row['key']
        readiness=call('codex','commerce_live_readiness');assert any(c['key']=='feishu'and c['status']=='needs_action'for c in readiness['checks'])
        result={'status':'passed','synthetic':True,'external_messages_sent':False,'checks':['native MCP discovers four tools and correct annotations','actual MCP save binds exact stock and rounds draft','Codex and Hermes native adapters read the same persisted draft','actual MCP export contains source evidence and Chinese fields','readiness reports missing recipient without sending']}
        (ROOT/'qa/planning-mcp-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
