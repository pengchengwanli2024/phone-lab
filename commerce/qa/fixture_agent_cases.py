"""Synthetic scoped-work-item UI fixture, with no provider/network calls."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from agent_runtime import model
from test_live_connections import batch, SECRET
from live_connections import now
from research import template


def seed(app):
    app.live.configure({'ozon_client_id':'123456','ozon_api_key':SECRET,'fulfillment_modes':['OGL']})
    config=app.live.config()
    for kind in ('orders','stock'):app.live._publish(config['connection_id'],kind,batch(kind),config,False)
    case=app.organization.import_inventory()['cases'][0];cid=case['id'];app.organization.set_currency(cid,'CNY')
    record=template('ozon')['record'];record.update(market='RU',language='en',source_url='https://example.org/synthetic',captured_at=now(),raw_excerpt='Synthetic item.',category_rules_url='https://example.org/rules',category_rules_checked=True)
    for value in record['fields'].values():value.update(original='Synthetic item.',zh='合成资料。',reviewed=True,locator='synthetic paragraph')
    app.organization.record(cid,'research',{'record':record,'sku':case['scope']['sku'],'row_key':case['scope']['row_key']},'synthetic-ui-research')
    return cid


def fake_model(payload, cancelled):
    params=payload['parameters']
    if not payload['observations']:
        decision={'phase':'inspect','calls':[{'tool':'commerce_organization_brief','arguments':{'case_id':params['case_id'],'stage_id':params.get('stage_id','S3')}}]}
    else:
        decision={'phase':'answer','answer':'选定工作项缺少供应链产物，请向该岗位补齐资料后复验。','questions':[],
                  'evidence_refs':['R1'],'proposals':[{'operation':'organization_handoff','reason':'补齐供应链资料并按同一币种复验','evidence_ref':'R1'}]}
    return {'decision':decision,'provider':'synthetic-no-network','model':'synthetic'}


if __name__=='__main__':
    model.invoke=fake_model
    server.Handler.secret=server.token();server.Handler.service=server.Commerce(server.STATE);seed(server.Handler.service)
    server.Handler.service.autonomy.start();server.Handler.service.agent_runtime.start()
    try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
    finally:server.Handler.service.agent_runtime.stop();server.Handler.service.autonomy.stop()
