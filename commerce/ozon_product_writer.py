"""One fixed product import attempt; never retry an HTTP body."""
import hashlib,http.client,json,re,ssl
from ozon_image_writer import connection
from ozon_reader import ConnectionIssue
from listing_submission_protocol import WRITE_PATH,projected_attributes
from listing_action_protocol import images


def validate_wire(body):
    if type(body)is not dict or set(body)!={'items'}or type(body['items'])is not list or len(body['items'])!=1:raise ValueError('listing_submission_invalid_body')
    row=body['items'][0];required={'offer_id','name','description_category_id','price','currency_code','images','attributes','depth','width','height','dimension_unit','weight','weight_unit','vat'}
    if type(row)is not dict or not required<=set(row)or set(row)-required-{'barcode','old_price'}:raise ValueError('listing_submission_invalid_body')
    for k in ('depth','width','height','weight','description_category_id'):
        if type(row[k])is not int or not 0<row[k]<=2**53-1:raise ValueError('listing_submission_invalid_body')
    if row['dimension_unit']!='mm'or row['weight_unit']!='g':raise ValueError('listing_submission_invalid_body')
    for k,maximum in [('offer_id',500),('name',500),('price',30),('currency_code',3),('vat',20)]:
        if type(row[k])is not str or not row[k].strip()or len(row[k])>maximum:raise ValueError('listing_submission_invalid_body')
    if not re.fullmatch('[A-Z]{3}',row['currency_code'])or not re.fullmatch(r'\d{1,13}(?:\.\d{1,8})?',row['price'])or not re.fullmatch(r'(?:0(?:\.\d{1,6})?|1(?:\.0{1,6})?)',row['vat']):raise ValueError('listing_submission_invalid_body')
    images(row['images'])
    if len(row['images'])>10:raise ValueError('listing_submission_invalid_body')
    projected_attributes(row['attributes'])
    for k in ('barcode','old_price'):
        if k in row and(type(row[k])is not str or len(row[k])>2000):raise ValueError('listing_submission_invalid_body')


def post_once(body,client_id,api_key):
    validate_wire(body);raw=json.dumps(body).encode();c=connection()
    try:
        c.request('POST',WRITE_PATH,body=raw,headers={'Content-Type':'application/json','Client-Id':client_id,'Api-Key':api_key,'User-Agent':'local-commerce-product-import/0.1'})
        response=c.getresponse();data=response.read(1024*1024+1)
        if response.status!=200 or len(data)>1024*1024:raise ConnectionIssue('ozon_write_outcome_unknown',response.status)
        value=json.loads(data)
        if type(value)is not dict:raise ConnectionIssue('ozon_write_outcome_unknown')
        return value,hashlib.sha256(data).hexdigest()
    except (OSError,TimeoutError,ssl.SSLError,http.client.HTTPException,ValueError)as exc:
        if isinstance(exc,ConnectionIssue):raise
        raise ConnectionIssue('ozon_write_outcome_unknown')from None
    finally:c.close()
