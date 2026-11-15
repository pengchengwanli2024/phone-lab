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
if os.environ.get('COMMERCE_QA_LISTING_SCHEMA')=='1':
    from fixture_listing_schema import seed as seed_listing_schema
    seed_listing_schema(app)
marker = server.STATE / 'fixture.json'
case_id = json.loads(marker.read_text())['case_id'] if marker.exists() else seed(app)
if os.environ.get('COMMERCE_QA_LISTING_RELEASE')=='1':
    from fixture_listing_release import install as install_listing_release
    install_listing_release(app)
marker.write_text(json.dumps({'case_id': case_id}))
if os.environ.get('COMMERCE_QA_OWNER_REVIEW')=='1':
    from fixture_owner_review import install as install_owner_review
    install_owner_review(app)
if os.environ.get('COMMERCE_QA_LISTING_ACTIONS')=='1':
    from fixture_listing_actions import install as install_listing_actions
    install_listing_actions(app)
if os.environ.get('COMMERCE_QA_INTEL') == '1':
    # This UI fixture uses persisted synthetic evidence. Automatic quote refresh
    # must not turn a browser regression into a real upstream network run.
    import intel_live
    def no_live_network(*args, **kwargs):
        raise ValueError('upstream_connection_or_format_error')
    intel_live.fetch_json = no_live_network
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
if os.environ.get('COMMERCE_QA_ARTICLE_BATCHES')=='1':
    from article_binding import text_hash
    row=dict(id='f'*24,source='fed',source_key='synthetic-body-batch',title='Synthetic batch bulletin',
        url='https://www.federalreserve.gov/newsevents/pressreleases/synthetic-batch.htm',published=1700001300,
        category='macro',country=None,country_code=None,location=None,publisher_alert=None,collected_at='2026-01-01T00:00:00Z')
    with app.core.db()as db:
        app.intelligence.store.archive(db,row,time.time());db.execute('INSERT OR REPLACE INTO intel_items VALUES (?,?,?)',(row['id'],row['source'],json.dumps(row)))
    def synthetic_article(doc):
        text='Synthetic batch customs evidence. 25 USD. '*8
        return dict(text=text,content_sha256=text_hash(text),source_url=doc['url'],captured_at='2026-01-01T00:00:00Z',routes=['synthetic-a','synthetic-b'])
    app.articles.fetcher=synthetic_article
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
    app.listing_releases.stop()
    app.listing_schema.stop()
    app.agent_runtime.stop()
