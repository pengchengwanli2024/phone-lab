"""Isolated synthetic picker/catalog load with explicit source-latency injection."""
import base64,json,os,sys,time
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
if not os.environ.get('COMMERCE_STATE') or not os.environ.get('COMMERCE_PORT'):raise SystemExit('Isolated state and port required')
import server
import catalog_media
from fixture_product_workspace import seed
# Public source URLs retain their identity; their bytes are synthetic locally.
catalog_media.fetch=lambda _url:base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII=')
app=server.Commerce(server.STATE);cid=seed(app)
with app.core.db()as db:
 connection,raw=db.execute('SELECT connection,scope FROM org_cases WHERE id=?',(cid,)).fetchone();scope=json.loads(raw);scope.pop('label',None)
 db.execute('UPDATE org_cases SET scope=? WHERE id=?',(json.dumps(scope),cid))
 for i in range(54):
  value={**scope,'sku':'SYN-READ-'+str(i),'row_key':'synthetic-read-'+str(i)}
  db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',('synthetic-read-'+str(i),connection,'synthetic-read-'+str(i),json.dumps(value),None,'2026-01-01T00:00:00+00:00'))
# Optional local forensic baseline; never used by the application or default QA.
old=os.environ.get('COMMERCE_QA_BASELINE_WORKSPACE')
if old:
 ns={};exec(compile(Path(old).read_text(),'qa-before-workspace.py','exec'),ns)
 app.product_workspace=ns['ProductWorkspace'](app);app.catalog.workspace=app.product_workspace
original_listing=app.business.listing
scans=[]
def listing(mode):
 scans.append({'mode':mode,'at':time.monotonic()});time.sleep(float(os.environ.get('COMMERCE_QA_SOURCE_DELAY','0.3')))
 return original_listing(mode)
app.business.listing=listing
invoke=app.invoke
requests=[]
def monitored(tool,args=None,client='local'):
 requests.append({'tool':tool,'at':time.monotonic()})
 (server.STATE/'reads.json').write_text(json.dumps({'requests':requests,'source_scans':scans}))
 fault=server.STATE/'.fail-next-workspace-read'
 if tool=='commerce_workspace_list' and fault.exists():fault.unlink();raise ValueError('commerce_service_unavailable')
 value=invoke(tool,args or {},client)
 (server.STATE/'reads.json').write_text(json.dumps({'requests':requests,'source_scans':scans}))
 return value
app.invoke=monitored
(server.STATE/'fixture.json').write_text(json.dumps({'case_id':cid}))
(server.STATE/'auth.token').write_text('synthetic-product-read-preview');(server.STATE/'auth.token').chmod(0o600)
server.Handler.secret='synthetic-product-read-preview';server.Handler.service=app
print('Synthetic product-read fixture ready',flush=True)
try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
finally:app.agent_runtime.stop()
