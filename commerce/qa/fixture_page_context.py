"""Isolated synthetic snapshots for page binding; never requests upstream data."""
from datetime import datetime, timedelta, timezone
from operating_statistics import fetch_sales
from ozon_reader import stamp


def seed(app):
    app.live.configure({'lookback_days':3}if app.live.config().get('connection_id')else{'ozon_client_id':'123','ozon_api_key':'synthetic-page-context','lookback_days':3})
    config=app.live.config()
    end=datetime.now(timezone.utc).date()-timedelta(days=1)
    current=datetime.combine(end+timedelta(days=1),datetime.min.time(),timezone.utc)
    records=[{'dimensions':[{'id':(end-timedelta(days=2-i)).isoformat()}],'metrics':[amount,units]}
             for i,(amount,units)in enumerate(((20,2),(10,1),(0,0)))]
    batch=fetch_sales(config,lambda *args:({'result':{'data':records,'totals':[30,3]}},'a'*64),current)
    app.live._publish(config['connection_id'],'sales',batch,config,False)
    if not app.live.snapshot(config['connection_id'],'stock'):
        app.live._publish(config['connection_id'],'stock',{'kind':'stock','observed_at':stamp(),'records':[
            {'product_id':'123','offer_id':'SYNTHETIC-SKU','sku':'456','stocks':[{'type':'fbs','present':12,'reserved':3}]}]},config,False)
    return batch
