"""Narrow, typed contract for replacing an existing product's standard gallery."""
import ipaddress
import re
from urllib.parse import urlsplit
from product_catalog import public_url
from listing_release_reads import identifier

WRITE_PATH='/v1/product/pictures/import'
READ_PATH='/v2/product/pictures/info'
CHECKS={'identity':'图片与实物一致','rights':'本次图片使用权','claims':'图片文案与证明','rules':'平台、类目与图片规则'}

def images(value,empty=False):
    if type(value)is not list or not (0 if empty else 1)<=len(value)<=20:raise ValueError('listing_action_invalid_images')
    out=[]
    for url in value:
        if not public_url(url)or re.search(r'[\x00-\x20\x7f]',url):raise ValueError('listing_action_invalid_images')
        host=urlsplit(url).hostname
        if '.'not in host or host.endswith(('.local','.localhost','.internal')):raise ValueError('listing_action_invalid_images')
        try:address=ipaddress.ip_address(host)
        except ValueError:address=None
        if address and(not address.is_global or address.is_multicast):raise ValueError('listing_action_invalid_images')
        if url in out:raise ValueError('listing_action_duplicate_image')
        out.append(url)
    return out

def gallery(raw,product_id):
    rows=raw.get('items')if type(raw)is dict else None
    if type(rows)is not list or len(rows)!=1 or type(rows[0])is not dict or identifier(rows[0].get('product_id'))!=product_id:raise ValueError('listing_action_response_scope')
    row=rows[0];urls=[]
    for key in ('primary_photo','photo'):
        for url in images(row.get(key),True):
            if url not in urls:urls.append(url)
    images(urls)
    color=images(row.get('color_photo'),True);panorama=images(row.get('photo_360'),True)
    errors=row.get('errors')
    if type(errors)is not list or len(errors)>100:raise ValueError('listing_action_response_schema')
    return dict(product_id=product_id,images=urls,special_images=bool(color or panorama),errors_present=bool(errors),error_count=len(errors))

def checklist(value):
    if type(value)is not dict or set(value)!=set(CHECKS):raise ValueError('listing_action_invalid_checks')
    result={}
    for key,row in value.items():
        if type(row)is not dict or set(row)!={'status','source_ref','note'}or row['status']not in ('pending','confirmed','rejected'):raise ValueError('listing_action_invalid_checks')
        if any(type(row[k])is not str or len(row[k])>1000 for k in ('source_ref','note')):raise ValueError('listing_action_invalid_checks')
        if row['status']=='confirmed'and not row['source_ref'].strip():raise ValueError('listing_action_evidence_required')
        result[key]=dict(row)
    return result

def text(value):
    if type(value)is not str or not value.strip()or len(value)>160 or re.search(r'[\x00-\x1f]',value):raise ValueError('listing_action_invalid_input')
    return value.strip()
