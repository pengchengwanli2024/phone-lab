"""One HTTP attempt, to one fixed endpoint. No transport or business retries."""
import hashlib
import http.client
import json
import ssl
from listing_action_protocol import WRITE_PATH,images
from listing_release_reads import identifier
from ozon_reader import DirectConnection,pinned_hosts,source_addresses,ConnectionIssue

def connection():
    pins=pinned_hosts()
    if not pins:
        c=http.client.HTTPSConnection('api-seller.ozon.ru',443,timeout=10,context=ssl.create_default_context())
        try:c.connect();return c
        except (OSError,TimeoutError,ssl.SSLError):c.close();raise ConnectionIssue('ozon_connect_failed_before_write')from None
    # Selecting a working TLS route is safe before any HTTP body is sent.
    # There is no route retry once request() has been called.
    for ip in pins:
        for source in source_addresses():
            c=DirectConnection(ip,source,10)
            try:c.connect();return c
            except (OSError,TimeoutError,ssl.SSLError):c.close()
    raise ConnectionIssue('ozon_connect_failed_before_write')

def post_once(body,client_id,api_key):
    if type(body)is not dict or set(body)!={'product_id','images'}or type(body['product_id'])is not int:raise ValueError('listing_action_invalid_payload')
    identifier(body['product_id']);images(body['images'])
    data=json.dumps(body).encode();transport=connection()
    try:
        transport.request('POST',WRITE_PATH,body=data,headers={'Content-Type':'application/json','Client-Id':client_id,'Api-Key':api_key,'User-Agent':'local-commerce-image-action/0.1'})
        response=transport.getresponse();raw=response.read(1024*1024+1)
        if response.status in (401,403):raise ConnectionIssue('ozon_auth_or_permission',response.status)
        if response.status==429:raise ConnectionIssue('ozon_rate_limited',429)
        if response.status!=200:raise ConnectionIssue('ozon_write_outcome_unknown',response.status)
        if len(raw)>1024*1024:raise ConnectionIssue('ozon_write_outcome_unknown')
        payload=json.loads(raw)
        if type(payload)is not dict:raise ConnectionIssue('ozon_write_outcome_unknown')
        return payload,hashlib.sha256(raw).hexdigest()
    except (OSError,TimeoutError,ssl.SSLError,http.client.HTTPException,ValueError)as exc:
        if isinstance(exc,ConnectionIssue):raise
        raise ConnectionIssue('ozon_write_outcome_unknown')from None
    finally:transport.close()
