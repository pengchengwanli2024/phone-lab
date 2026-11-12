"""Synthetic, isolated browser fixture; never calls models or a marketplace."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import Commerce
from research import canonical, template
from test_live_connections import batch, SECRET


def seed(app):
    app.live.configure({'ozon_client_id': '123456', 'ozon_api_key': SECRET, 'fulfillment_modes': ['OGL']})
    config = app.live.config()
    for kind in ('orders', 'stock'):
        app.live._publish(config['connection_id'], kind, batch(kind), config, False)
    case = app.organization.import_inventory()['cases'][0]
    scope = dict(case['scope'], label='便携式榨汁机 · 合成验收', synthetic=True)
    with app.core.db() as db:
        db.execute('UPDATE org_cases SET scope=?,currency=? WHERE id=?', (canonical(scope), 'CNY', case['id']))
    cid = case['id']
    record = template('ozon')['record']
    record.update(market='RU', language='en', source_url='https://example.com/synthetic-research',
                  captured_at=datetime.now(timezone.utc).isoformat(), raw_excerpt='Synthetic test material. No market-size evidence.',
                  category_rules_url='https://example.com/synthetic-rules', category_rules_checked=False)
    for key, field in record['fields'].items():
        field.update(original='Portable blender — synthetic test material.', zh='便携式榨汁机。合成测试资料，规格、市场与规则仍需实际核实。', reviewed=False, locator='synthetic:'+key)
    app.organization.record(cid, 'research', {'sku': scope['sku'], 'row_key': scope['row_key'], 'record': record}, 'fixture-research')
    app.organization.record(cid, 'supply', {'currency': 'CNY', 'purchase_cost': 58, 'lead_time_days': 14, 'supplier': '合成供应方', 'source_ref': 'synthetic:quote'}, 'fixture-supply')
    now = datetime.now(timezone.utc)
    source = app.business.template('listing')['document']
    source.update(scope={'platform': 'ozon', 'store_ref': 'synthetic-store', 'subject_ref': cid},
                  label='商品事实 · 合成验收资料', observed_at=now.isoformat(), valid_until=(now+timedelta(days=1)).isoformat())
    values = {'sku': scope['sku'], 'title': '合成示例 · 便携式榨汁机', 'description': '仅用于本机界面与版本流程验证；不代表真实商品事实。', 'category_id': 'synthetic-category',
              'price': '239.00', 'currency': 'CNY', 'quantity': 1, 'image_refs': ['https://example.com/synthetic-product.png']}
    source['records'] = [{'key': k, 'value': v} for k, v in values.items()]
    app.business.import_source(source, 'fixture-facts')
    snapshot = app.product_workspace.get(cid)
    app.product_workspace.save(cid, 'plan', {'goal': '核对研究依据、补齐成本并审阅商品内容草稿', 'steps': [{'title': v} for v in ['核对研究资料与来源', '补齐实际报价和费用', '完成同币种测算', '准备商品内容草稿', '审阅本地交付版本']]}, 0, snapshot['source_sha256'])
    app.core.invoke('commerce_task_create', {'idempotency_key': 'fixture-task', 'kind': 'analysis', 'input': {'organization_case': cid, 'title': '核对研究来源 · 合成任务', 'demo': True}})
    return cid


if __name__ == '__main__':
    if not os.environ.get('COMMERCE_STATE'):
        raise SystemExit('Isolated COMMERCE_STATE required')
    import server
    from agent_runtime import model
    import json

    def fake_model(payload, cancelled):
        if cancelled():
            raise model.Cancelled()
        if not payload['observations']:
            selected = next((t for t in payload['tools'] if t['tool'] == 'commerce_workspace_get'), payload['tools'][0])
            decision = {'phase': 'inspect', 'calls': [selected]}
        else:
            decision = {'phase': 'answer', 'answer': '已读取当前工作项允许的资料。研究内容仍待独立核实；请补齐实际采购报价、包装与费率后完成测算。',
                        'questions': [], 'evidence_refs': ['R1'], 'proposals': []}
        return {'decision': decision, 'provider': 'synthetic-no-network', 'model': 'synthetic'}

    model.invoke = fake_model
    server.Handler.secret = server.token()
    server.Handler.service = Commerce(server.STATE)
    marker = server.STATE / 'fixture.json'
    cid = json.loads(marker.read_text())['case_id'] if marker.exists() else seed(server.Handler.service)
    marker.write_text(json.dumps({'case_id': cid}))
    original_get = server.Handler.do_GET

    def get(handler):
        if handler.path == '/harness-open':
            ready = server.STATE / 'native-host.json'
            if not ready.is_file():
                return handler.answer(503, {'error': 'native_host_starting'})
            return handler.answer(303, '', headers={'Location': json.loads(ready.read_text())['url']})
        return original_get(handler)

    server.Handler.do_GET = get
    server.Handler.service.agent_runtime.start()
    print(json.dumps({'origin': 'http://127.0.0.1:'+str(server.PORT), 'case_id': cid, 'synthetic': True}), flush=True)
    try:
        server.CommerceHTTPServer(('127.0.0.1', server.PORT), server.Handler).serve_forever()
    finally:
        server.Handler.service.agent_runtime.stop()
