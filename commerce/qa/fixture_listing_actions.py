"""Explicit synthetic existing-product fixture; writer never accesses a network."""
import base64,copy,hashlib
from research import canonical,digest

CASE='a819'*8
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII=')

def install(app):
    from organization import stamp
    from listing_action_protocol import gallery
    config=app.live.config();scope=dict(platform='ozon',market='RU',product_id='20',sku='SYN-IMAGE-ACTION',inventory_type='fbs',row_key='20:fbs',origin='inventory_scope_not_independently_verified',label='Synthetic image-action fixture')
    stock=copy.deepcopy(app.live.snapshot(config['connection_id'],'stock')['data'])
    stock['records'].append(dict(product_id='20',offer_id='SYN-IMAGE-ACTION',stocks=[dict(type='fbs',present=10,reserved=0,sku='20')],warehouse_scope='fulfillment_aggregate_not_single_warehouse'))
    app.live._publish(config['connection_id'],'stock',stock,config,False)
    with app.core.db()as db:db.execute('INSERT OR IGNORE INTO org_cases VALUES (?,?,?,?,?,?)',(CASE,config['connection_id'],'20:fbs',canonical(scope),'CNY',stamp()))
    raw={'items':[dict(product_id=20,primary_photo=['https://example.com/original-image.jpg'],photo=[],color_photo=[],photo_360=[],errors=[])]}
    def read(path,body,*args):
        assert body=={'product_id':[20]};return copy.deepcopy(raw),'c'*64
    def write(body,*args):
        assert args[0]=='123456'and body['product_id']==20
        urls=['https://example.com/platform-result-'+str(i)+'.png'for i in range(len(body['images']))]
        raw['items'][0].update(primary_photo=urls[:1],photo=urls[1:])
        snapshot=gallery(raw,'20');snapshot['evidence']=dict(endpoint='/v2/product/pictures/info',request_sha256=digest(canonical({'product_id':[20]})),response_sha256='c'*64)
        source=digest(canonical(snapshot));folder=app.state/'catalog-images';folder.mkdir(exist_ok=True,mode=0o700)
        for url in urls:
            path=folder/(hashlib.sha256((source+url).encode()).hexdigest()+'.image');path.write_bytes(PNG);path.chmod(0o600)
        return {'result':{'pictures':[{'product_id':20,'state':'imported'}]}},'d'*64
    app.listing_actions.reader=read;app.listing_actions.writer=write
