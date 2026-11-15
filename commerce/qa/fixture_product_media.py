"""Isolated, explicitly synthetic product/media browser fixture."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixture_product_workspace import seed
from creative_render import render_svg
from service import Commerce
import server

if not os.environ.get('COMMERCE_STATE'):raise SystemExit('Isolated COMMERCE_STATE required')
server.Handler.secret=server.token();app=Commerce(server.STATE);server.Handler.service=app
marker=server.STATE/'product-media-fixture.json'
if not marker.is_file():
    cid=seed(app);detail=app.catalog.get(cid)
    p=app.catalog.creative(cid,detail['source_sha256'],'synthetic-media-fixture')
    b=p['brief'];b['product']['name']='合成验收 · 便携式榨汁机';b['product']['verified_facts']=[{'id':'f1','text':'合成规格：容量500毫升','evidence_ref':'synthetic:spec'}]
    b['target'].update(audience='合成验收人群',use_scene='合成厨房场景')
    p=app.creative.save(p['id'],b,p['revision'])
    svg='''<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1080"><rect width="1080" height="1080" fill="#f0f4fb"/><rect x="390" y="180" width="300" height="650" rx="60" fill="#ffffff" stroke="#0861f8" stroke-width="10"/><rect x="400" y="680" width="280" height="140" rx="40" fill="#0861f8"/><circle cx="540" cy="750" r="25" fill="#ffffff"/><text x="540" y="970" text-anchor="middle" font-family="sans-serif" font-size="42" fill="#182335">SYNTHETIC QA PRODUCT</text></svg>'''
    product_svg,product=render_svg(app.creative,server.STATE,'synthetic-product',svg)
    raw=product.read_bytes()
    asset=app.creative.register(p['id'],'product_image',product,{'display_name':'合成商品原图','source_ref':'synthetic:product','origin':'synthetic_fixture'})
    reference=server.STATE/'synthetic-reference.png';reference.write_bytes(raw)
    ref=app.creative.register(p['id'],'reference_image',reference,{'display_name':'合成参考图','source_ref':'synthetic:reference','origin':'synthetic_fixture'})
    # Preserve the test input file for real browser uploads; no actual product.
    upload=server.STATE/'synthetic-upload.png';upload.write_bytes(raw)
    marker.write_text(json.dumps({'case_id':cid,'project_id':p['id'],'asset_id':asset['id'],'reference_id':ref['id']}))
app.autonomy.start();print(json.dumps({'synthetic':True,'port':server.PORT}),flush=True)
try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
finally:app.autonomy.stop()
