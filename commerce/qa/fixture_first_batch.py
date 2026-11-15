"""Explicit synthetic acceptance: shared sources, real local ledgers, no networks."""
import json
import os
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
if not os.environ.get('COMMERCE_STATE') or not os.environ.get('COMMERCE_PORT'):
    raise SystemExit('Isolated state and port required')
import server
from fixture_product_workspace import seed
from agent_runtime import model

app = server.Commerce(server.STATE)
case_id = seed(app)
case = app.organization.case(case_id)
connection = app.live.config()['connection_id']
with app.core.db() as db:
    scope = {**case['scope'], 'store_ref': connection}
    db.execute('UPDATE org_cases SET scope=? WHERE id=?', (json.dumps(scope), case_id))
doc = app.business.template('price')['document']
doc.update(kind='facts', synthetic=True, scope={'platform': 'ozon', 'store_ref': connection, 'subject_ref': case_id},
           label='第一批验收 · 合成来源', records=[{'key': 'material', 'value': '合成验收：杯体材料为合成示例，不代表真实商品事实。'}])
source = app.business.import_source(doc, 'first-batch-source')
fact = app.memory.propose('杯体材料为合成示例', [{'source_id': source['source_id'], 'version': source['version'], 'sha256': source['sha256'], 'record_key': 'material', 'quote': '杯体材料为合成示例'}], 'first-batch-fact')
fact = app.memory.decide('confirm', fact['id'], fact['revision'], fact['sha256'], True, 'first-batch-confirm')
app.memory.summarize([fact['id']], '合成材料摘要', 'first-batch-summary')


def fake_model(payload, cancelled):
    if cancelled(): raise model.Cancelled()
    if not payload['observations']:
        decision = {'phase': 'inspect', 'calls': [{'tool': 'commerce_project_memory_search', 'arguments': {'query': ''}}]}
    else:
        proposals = [{'operation': 'unit_economics', 'reason': '核对本次合成参数并计算单件贡献'}] if payload['parameters']['context'].get('calculator') else []
        decision = {'phase': 'answer', 'answer': '合成验收：已按当前商品范围读取项目记忆，人工确认与导入原文分别保留。资料仍未独立核实。' + (' 请先核对商品来源与报价，再完成同币种测算。' * 3), 'questions': [], 'evidence_refs': ['R1'], 'proposals': proposals}
    return {'decision': decision, 'provider': 'synthetic-no-network', 'model': 'synthetic'}


model.invoke = fake_model
context = {'module': 'organization', 'demo': True, 'platform': 'ozon', 'market': 'RU', 'entity': {'kind': 'case', 'id': case_id}}
thread = app.copilot.open(context, 'first-batch-thread')
for index in range(5):
    app.copilot.send(thread['id'], '合成验收：核对当前商品记忆 ' + str(index + 1), thread['context_sha256'], 'first-batch-turn-' + str(index))
    app.agent_runtime.run_once()
parameters = dict(currency='CNY', price=239, purchase_cost=58, domestic_shipping=5, packaging=3, fulfillment_cost=12, electronic_fee=0, commission_rate=.1, payment_rate=.02, return_rate=.03, ad_rate=.05)
thread = app.copilot.context(thread['id'], {**context, 'calculator': 'unit_economics', 'input': parameters}, thread['context_sha256'])
app.copilot.send(thread['id'], '合成验收：审阅本地测算建议', thread['context_sha256'], 'first-batch-receipt-turn')
app.agent_runtime.run_once()
run = app.copilot.get(thread['id'])['latest_run']
applied = app.copilot.apply(thread['id'], run['id'], 'P1', run['result_sha256'], thread['context_sha256'])
app.autonomy.work(1000)
app.copilot.context(thread['id'], context, thread['context_sha256'])
server.Handler.secret = 'synthetic-first-batch-only'
(server.STATE / 'auth.token').write_text(server.Handler.secret)
server.Handler.service = app
(server.STATE / 'fixture.json').write_text(json.dumps({'case_id': case_id, 'thread_id': thread['id'], 'task_id': applied['task']['id']}))
print('Synthetic first-batch acceptance ready', flush=True)
try:
    server.CommerceHTTPServer(('127.0.0.1', server.PORT), server.Handler).serve_forever()
finally:
    app.agent_runtime.stop()
