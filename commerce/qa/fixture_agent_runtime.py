"""Synthetic UI server. Provider model is replaced only inside this QA process."""
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from agent_runtime import model


def fake_model(payload, cancelled):
    if 'slow' in payload['question']:
        for _ in range(1000):
            if cancelled():raise model.Cancelled()
            time.sleep(.02)
    if 'unknown' in payload['question']:raise ValueError('agent_provider_outcome_unknown')
    if 'clarify' in payload['question']:
        decision={'phase':'answer','answer':'当前缺少明确币种。','questions':['请补充币种和采购成本。'],'evidence_refs':[],'proposals':[]}
    elif not payload['observations']:
        decision={'phase':'inspect','calls':[{'tool':'commerce_runtime_status','arguments':{}}]}
    else:
        decision={'phase':'answer','answer':'已读取本机运行状态，下面是待审阅的本地建议。','questions':[],
                  'evidence_refs':['R1'],'proposals':[{'operation':'report','reason':'生成本地模板简报'}] if 'report' in payload['question'] else []}
    return {'decision':decision,'provider':'synthetic-no-network','model':'synthetic'}


model.invoke=fake_model
server.Handler.secret=server.token();server.Handler.service=server.Commerce(server.STATE)
server.Handler.service.autonomy.start();server.Handler.service.agent_runtime.start()
try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
finally:
    server.Handler.service.agent_runtime.stop();server.Handler.service.autonomy.stop()
