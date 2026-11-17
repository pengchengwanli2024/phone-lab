"""Isolated real HTTP service, local-only synthetic model decisions."""
import os
import time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if not os.environ.get('COMMERCE_STATE') or not os.environ.get('COMMERCE_PORT'):raise SystemExit('Isolated state and port required')
import server
from agent_runtime import model

def synthetic(payload,cancelled):
    if cancelled():raise model.Cancelled()
    delay=min(2,max(0,float(os.environ.get('COMMERCE_QA_MODEL_DELAY','0'))))
    if delay:time.sleep(delay)
    decision={'phase':'answer','answer':'合成验收：原任务结果已保留，可返回原对话继续。','questions':[],'proposals':[],'evidence_refs':['R1']}
    if not payload['observations']:decision={'phase':'inspect','calls':[{'tool':'commerce_runtime_status','arguments':{}}]}
    return {'decision':decision,'provider':'synthetic-no-network','model':'synthetic'}

model.invoke=synthetic
app=server.Commerce(server.STATE)
server.Handler.secret='synthetic-capabilities-preview'
(server.STATE/'auth.token').write_text(server.Handler.secret)
server.Handler.service=app
app.agent_runtime.start()
try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
finally:app.agent_runtime.stop();app.extensions.stop()
