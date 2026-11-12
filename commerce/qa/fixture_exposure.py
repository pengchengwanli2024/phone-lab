"""Isolated synthetic business coverage UI, no outbound model or feed calls."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from agent_runtime import model
from fixture_agent_cases import seed
from test_exposure import publish


def fake_model(payload,cancelled):
    ident=payload['parameters']['assessment_id']
    if not payload['observations']:
        decision={'phase':'inspect','calls':[{'tool':'commerce_exposure_get','arguments':{'assessment_id':ident}}]}
    else:
        decision={'phase':'answer','answer':'存在经营关联线索，实际影响未知，请复核来源时间、经营范围与实际运输情况。','questions':[],
                  'evidence_refs':['R1'],'proposals':[{'operation':'exposure_review','reason':'复核公开信号与明确经营范围','evidence_ref':'R1'}]}
    return {'decision':decision,'provider':'synthetic-no-network','model':'synthetic'}


if __name__=='__main__':
    model.invoke=fake_model
    server.Handler.secret=server.token();server.Handler.service=server.Commerce(server.STATE)
    seed(server.Handler.service);publish(server.Handler.service)
    server.Handler.service.autonomy.start();server.Handler.service.agent_runtime.start()
    try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
    finally:server.Handler.service.agent_runtime.stop();server.Handler.service.autonomy.stop()
