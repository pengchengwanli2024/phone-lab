"""Explicitly synthetic local acceptance, with no model or marketplace network."""
import json
import hashlib
import os
from pathlib import Path
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
if not os.environ.get('COMMERCE_STATE') or not os.environ.get('COMMERCE_PORT'):
    raise SystemExit('An isolated state directory and port are required')
import server
from fixture_product_workspace import seed
from agent_runtime import model
import channel_connections


def synthetic_channel_probe():
    return {'profile_available': True, 'shared_core_configured': True, 'platforms': {
        name: {'adapter_available': True, 'credentials_present': False,
               'missing_fields': ['SYNTHETIC_APP_CREDENTIAL'], 'gateway_enabled': False,
               'runtime_status': 'not_running'}
        for name in ('feishu', 'wecom', 'wecom_callback', 'weixin', 'dingtalk')}}


channel_connections.probe_profile = synthetic_channel_probe


def fake_model(payload, cancelled):
    if cancelled():
        raise model.Cancelled()
    if not payload['observations']:
        decision = {'phase': 'inspect', 'calls': [payload['tools'][0]]}
    else:
        decision = {'phase': 'answer', 'answer': '合成验收：已读取当前允许的商品资料；成本仍由确定性计算器核对。', 'questions': [], 'evidence_refs': ['R1'], 'proposals': []}
    return {'decision': decision, 'provider': 'synthetic-no-network', 'model': 'synthetic'}


model.invoke = fake_model
app = server.Commerce(server.STATE)
original_invoke = app.invoke


def invoke_with_explicit_fault(tool, args=None, client='local'):
    result = original_invoke(tool, args or {}, client)
    # QA-only opt-in: commit the real synthetic action, then withhold its response
    # past the browser timeout. This checks unknown recovery without faking data.
    fault = server.STATE / '.delay-next-cost-response'
    if tool == 'commerce_a2ui_action' and fault.is_file():
        fault.unlink()
        time.sleep(22)
    return result


app.invoke = invoke_with_explicit_fault
marker = server.STATE / 'fixture.json'
case_id = json.loads(marker.read_text())['case_id'] if marker.exists() else seed(app)
marker.write_text(json.dumps({'case_id': case_id}))
if os.environ.get('COMMERCE_QA_INTEL') == '1':
    from seed_intel_workspace import seed as seed_intelligence
    seed_intelligence(server.STATE)
    from crawler_feed_bridge import SOURCES
    sample = app.intelligence.search(source='wto')['items'][0]
    for source in ('hmrc', 'transport'):
        row = {**sample, 'id': hashlib.sha256(('synthetic-' + source).encode()).hexdigest()[:24], 'source': source,
               'category': SOURCES[source]['category'], 'title': 'Synthetic ' + source + ' bulletin',
               'url': 'https://example.org/' + source}
        with app.core.db() as db:
            app.intelligence.store.archive(db, row, time.time())
            db.execute('INSERT INTO intel_items VALUES (?,?,?)', (row['id'], source, json.dumps(row)))
# Deliberately public test-only credential; this fixture never contains real data.
server.Handler.secret = 'synthetic-workbench-preview'
(server.STATE / 'auth.token').write_text(server.Handler.secret)
server.Handler.service = app
original_get = server.Handler.do_GET


def get(handler):
    if handler.path == '/harness-open':
        descriptor = server.STATE / 'native-host.json'
        if not descriptor.is_file():
            return handler.answer(503, {'error': 'isolated_host_not_ready'})
        return handler.answer(303, '', headers={'Location': json.loads(descriptor.read_text())['url']})
    return original_get(handler)


server.Handler.do_GET = get
app.agent_runtime.start()
(server.STATE / 'qa-server.pid').write_text(str(os.getpid()))
print('Synthetic React acceptance server ready on loopback', flush=True)
try:
    server.CommerceHTTPServer(('127.0.0.1', server.PORT), server.Handler).serve_forever()
finally:
    app.agent_runtime.stop()
