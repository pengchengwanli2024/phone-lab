"""Exact Ozon external-task/identity projections. Import is not publication."""
from decimal import Decimal,InvalidOperation
import re

IMPORT_PATH='/v1/product/import/info'
PRODUCT_PATH='/v3/product/info/list'


def identifier(value,zero=False):
    if type(value)is int:value=str(value)
    if not isinstance(value,str)or not re.fullmatch(r'0|[1-9][0-9]{0,18}',value)or int(value)>2**63-1 or(not zero and value=='0'):
        raise ValueError('listing_release_invalid_identifier')
    return value


def text(value,limit=2000):
    if not isinstance(value,str)or len(value)>limit:raise ValueError('listing_release_response_schema')
    return value


def errors(value):
    if type(value)is not list or len(value)>100:raise ValueError('listing_release_response_schema')
    out=[]
    for row in value:
        if type(row)is not dict:raise ValueError('listing_release_response_schema')
        code=text(row.get('code','unknown'),160);message=text(row.get('message',''),4000)
        out.append(dict(code=code,message=message))
    return out


def import_projection(payload,sku):
    result=payload.get('result')if isinstance(payload,dict)else None
    rows=result.get('items')if isinstance(result,dict)else None
    if type(rows)is not list or len(rows)>1000:raise ValueError('listing_release_response_schema')
    matches=[]
    for row in rows:
        if type(row)is not dict or not isinstance(row.get('offer_id'),str):raise ValueError('listing_release_response_schema')
        if row['offer_id']==sku:matches.append(row)
    base=dict(returned_count=len(rows),match_count=len(matches),record=None,import_confirmed=False)
    if not rows:return {**base,'status':'empty_import_result'}
    if len(matches)!=1:return {**base,'status':'scope_mismatch'if not matches else'ambiguous_import_result'}
    row=matches[0];status=text(row.get('status'),100)
    product=identifier(row.get('product_id',0),True);provided='errors'in row
    issues=errors(row['errors'])if provided else[]
    record=dict(sku=sku,product_id=product,status=status,errors=issues,errors_provided=provided)
    base['record']=record
    if status in ('failed','error'):state='import_rejected'
    elif issues:state='import_issues'
    elif status!='imported':state='import_pending'if status in ('pending','processing','in_progress')else'unknown_import_status'
    elif not provided:state='import_details_incomplete'
    elif product=='0':state='awaiting_product_id'
    else:state='awaiting_product_readback'
    return {**base,'status':state}


def product_projection(payload,sku,product_id):
    rows=payload.get('items')if isinstance(payload,dict)else None
    if type(rows)is not list or len(rows)>1000:raise ValueError('listing_release_response_schema')
    matches=[]
    for row in rows:
        if type(row)is not dict:raise ValueError('listing_release_response_schema')
        if identifier(row.get('id'))==product_id and row.get('offer_id')==sku:matches.append(row)
    base=dict(returned_count=len(rows),match_count=len(matches),record=None)
    if len(matches)!=1:return {**base,'status':'product_missing'if not matches else'ambiguous_product_result'}
    row=matches[0];flags=row.get('statuses')
    if flags is not None and not isinstance(flags,dict):raise ValueError('listing_release_response_schema')
    statuses={}
    for key in ('is_created','is_failed'):
        if flags is not None and key in flags:
            if type(flags[key])is not bool:raise ValueError('listing_release_response_schema')
            statuses[key]=flags[key]
    for key in ('status_name','status_description','status','moderate_status','validation_status'):
        if flags is not None and key in flags:statuses[key]=text(flags[key],4000)
    price=row.get('price');currency=row.get('currency_code');name=row.get('name')
    if price is not None:
        if not isinstance(price,str)or not re.fullmatch(r'[0-9]{1,20}(?:\.[0-9]{1,8})?',price):raise ValueError('listing_release_response_schema')
        try:
            if not Decimal(price).is_finite()or Decimal(price)<0:raise InvalidOperation()
        except InvalidOperation:raise ValueError('listing_release_response_schema')from None
    if currency is not None and(not isinstance(currency,str)or not re.fullmatch('[A-Z]{3}',currency)):raise ValueError('listing_release_response_schema')
    if name is not None:name=text(name,2000)
    record=dict(entity_id=product_id,sku=sku,title=name,amount=price,currency=currency,quantity=None,
        quantity_basis='not_returned_by_product_info',status=statuses.get('status_name'),statuses=statuses)
    return {**base,'status':'product_observed','record':record}
