"""Isolated QA server. Synthetic upstreams; never opens an outbound connection."""
from pathlib import Path
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import ozon_reader
import feishu_sender
from test_live_connections import raw_order


def fake_post(path, body, client, key):
    if path == ozon_reader.ENDPOINTS['stock']:
        value={'items':[{'product_id':10,'offer_id':'SYN-SKU','stocks':[{'type':'fbs','present':3,'reserved':1,'sku':123}]}],'cursor':''}
    else:
        value={'postings':[raw_order()],'has_next':False,'cursor':''}
    return value, hashlib.sha256(json.dumps(value).encode()).hexdigest()


ozon_reader.post=fake_post
feishu_sender.send=lambda *args: {'outcome':'confirmed','code':'synthetic_no_network'}
server.Handler.secret=server.token()
server.Handler.service=server.Commerce(server.STATE)
if __import__('os').environ.get('COMMERCE_QA_TRANSLATION_SEED')=='1':
    import translation
    from research import digest
    from live_connections import now
    def fake_translation(data):
        return dict(provider='synthetic-no-network',model='synthetic-fixture',translated_at=now(),prompt_version='synthetic',translations=[dict(id=i['id'],zh='合成 '+i['text'],original_sha256=digest(i['text']),zh_sha256=digest('合成 '+i['text']),warnings=[])for i in data['items']])
    translation.run_model=fake_translation
if __import__('os').environ.get('COMMERCE_QA_ORGANIZATION_SEED')=='1':
    from test_live_connections import batch,SECRET
    import base64
    app=server.Handler.service
    app.live.configure({'ozon_client_id':'123456','ozon_api_key':SECRET,'fulfillment_modes':['OGL']})
    config=app.live.config()
    for kind in ('orders','stock'):app.live._publish(config['connection_id'],kind,batch(kind),config,False)
    project=app.creative.create({'synthetic':True,'product':{'name':'Synthetic fixture','verified_facts':[]}},'org-ui-fixture')
    image=server.STATE/'synthetic-image.png';image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6rUAAAAAASUVORK5CYII='))
    app.creative.register(project['id'],'product_image',image,{'display_name':'Synthetic fixture.png','source_ref':'synthetic:fixture','usage_scope':'synthetic_only'})
server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
