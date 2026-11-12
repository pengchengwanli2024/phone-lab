"""Isolated synthetic provider for full shared-UI acceptance. No model network calls."""
from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from agent_runtime import model

def fake_model(payload,cancelled):
    question=payload['question']
    if 'slow' in question:
        for _ in range(1000):
            if cancelled():raise model.Cancelled()
            time.sleep(.02)
    if 'unknown' in question:raise ValueError('agent_provider_outcome_unknown')
    if 'clarify' in question or '哪些资料' in question:
        d={'phase':'answer','answer':'请补充已核对的资料，不推测数值。','questions':['请明确本次币种和采购成本。'],'evidence_refs':[],'proposals':[]}
    elif not payload['observations']:
        d={'phase':'inspect','calls':[payload['tools'][0]]}
    else:
        d={'phase':'answer','answer':'已读取当前允许的依据。可以继续审阅本地简报建议；这不是经营操作完成。','questions':[],'evidence_refs':['R1'],'proposals':[{'operation':'report','reason':'生成当前模式的本地简报'}] if 'report' in question else []}
    return {'decision':d,'provider':'synthetic-no-network','model':'synthetic'}

model.invoke=fake_model
server.Handler.secret=server.token();server.Handler.service=server.Commerce(server.STATE)
original=server.Handler.service.invoke

def invoke(name,args,client='local'):
    if name=='commerce_knowledge_list':raise ValueError('synthetic_optional_knowledge_unavailable')
    return original(name,args,client)
server.Handler.service.invoke=invoke
server.Handler.service.autonomy.start();server.Handler.service.agent_runtime.start()
try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
finally:server.Handler.service.agent_runtime.stop();server.Handler.service.autonomy.stop()
