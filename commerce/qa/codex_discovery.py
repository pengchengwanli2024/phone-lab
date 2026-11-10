"""Real Codex app-server discovery, without sending a model turn."""
import json
import os
import sys
from pathlib import Path
import select
import subprocess
import time

p=subprocess.Popen([os.environ.get('CODEX_BIN','codex'),'app-server'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
def call(ident,method,params):
    p.stdin.write(json.dumps({'id':ident,'method':method,'params':params})+'\n');p.stdin.flush()
    end=time.monotonic()+45
    while time.monotonic()<end:
        ready,_,_=select.select([p.stdout],[],[],1)
        if not ready:continue
        line=p.stdout.readline()
        if not line:raise RuntimeError('app-server exited')
        message=json.loads(line)
        if message.get('id')==ident:
            if 'error'in message:raise RuntimeError(json.dumps(message['error']))
            return message['result']
    raise RuntimeError('app-server response timeout')
try:
    call(1,'initialize',{'clientInfo':{'name':'commerce-acceptance','version':'0.1.0'},'capabilities':{'experimentalApi':True}})
    p.stdin.write(json.dumps({'method':'initialized'})+'\n');p.stdin.flush()
    result=call(2,'mcpServerStatus/list',{'serverName':'commerce','detail':'toolsAndAuthOnly','limit':100})
    data=result.get('data',[])
    server=next((r for r in data if r.get('name')=='commerce'),None)
    if server is None:raise RuntimeError('commerce missing from Codex MCP discovery')
    tools=server.get('tools',{})
    names=list(tools)if isinstance(tools,dict)else[t.get('name')for t in tools]
    if not any('commerce_status'in name for name in names):raise RuntimeError('commerce_status not discovered')
    thread=call(3,'thread/start',{'cwd':str(Path(__file__).resolve().parents[2]),'ephemeral':True,'approvalPolicy':'never','sandbox':'workspace-write','config':{'mcp_servers':{'commerce':{'command':sys.executable,'args':[str(Path(__file__).resolve().parents[1]/'mcp_server.py'),'codex']}}}})
    result=call(4,'mcpServer/tool/call',{'threadId':thread['thread']['id'],'server':'commerce','tool':'commerce_status','arguments':{}})
    if result.get('isError'):raise RuntimeError('native Codex commerce_status returned an error')
    status=result.get('structuredContent')or json.loads(result['content'][0]['text'])
    if status.get('version')!='0.1.0':raise RuntimeError('Unexpected shared service version')
    output={'status':'passed','client':'native Codex app-server','tools':len(names),'model_turn_sent':False,'server':'commerce','tool_call':'commerce_status','knowledge_configured':status['knowledge']['configured']}
    Path(__file__).with_name('codex-result.json').write_text(json.dumps(output,indent=2));print(json.dumps(output))
finally:
    p.terminate();p.wait(timeout=8);p.stdin.close();p.stdout.close()
