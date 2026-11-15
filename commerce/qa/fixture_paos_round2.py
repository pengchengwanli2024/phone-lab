"""Private synthetic HTTP fixture; never starts the daily service or a model."""
from pathlib import Path
import json
import os
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'qa')]
import server
import react_page
from test_organization import OrganizationTests

fixture = OrganizationTests()
fixture.setUp()
server.Handler.service = fixture.app
server.Handler.secret = server.token()
if os.environ.get('PAOS_UI_CANDIDATE'):
    react_page.ROOT = Path(os.environ['PAOS_UI_CANDIDATE']).resolve()
doc = fixture.app.business.template('facts')['document']
doc['records'] = [{'key': 'material', 'value': '合成棉 Synthetic cotton'}]
source = fixture.app.business.import_source(doc, 'synthetic-browser-source')
task = fixture.app.core.invoke('commerce_task_create', {'kind': 'analysis', 'input': {
    'organization_case': fixture.cid, 'title': '合成来源复核'}, 'idempotency_key': 'synthetic-plan-task'})
view = fixture.app.product_workspace.get(fixture.cid)
fixture.app.product_workspace.save(fixture.cid, 'plan', {'goal': '合成工作计划', 'steps': [
    {'title': '核对来源', 'task_id': task['id']}, {'title': '核对成本'}]}, 0, view['source_sha256'])
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
print(json.dumps({'ready': True, 'case_id': fixture.cid, 'source_id': source['source_id']}), flush=True)
try:
    server.CommerceHTTPServer(('127.0.0.1', server.PORT), server.Handler).serve_forever()
finally:
    fixture.tearDown()
