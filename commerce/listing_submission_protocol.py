"""Bounded single-product import contract. No inferred facts, tax or inventory writes."""
from copy import deepcopy
import re
from listing_release_reads import identifier
from listing_action_protocol import images

WRITE_PATH='/v3/product/import'
ATTR_PATH='/v4/product/info/attributes'
PUBLICATION_KEYS={'depth','width','height','dimension_unit','weight','weight_unit','vat','source_ref','vat_source_ref','description_attribute_id'}

def validate_publication(value):
    if type(value)is not dict or set(value)!=PUBLICATION_KEYS:raise ValueError('listing_invalid_publication')
    for k in ('depth','width','height','weight'):
        v=value[k]
        if v is not None and(type(v)is not int or not 0<=v<=100000000):raise ValueError('listing_invalid_publication')
    for k,choices in [('dimension_unit',('','mm')),('weight_unit',('','g'))]:
        if value[k]not in choices:raise ValueError('listing_invalid_publication')
    for k in ('source_ref','vat_source_ref','vat'):
        if type(value[k])is not str or len(value[k])>(20 if k=='vat'else 1000):raise ValueError('listing_invalid_publication')
    if value['vat']and not re.fullmatch(r'(?:0(?:\.\d{1,6})?|1(?:\.0{1,6})?)',value['vat']):raise ValueError('listing_invalid_publication')
    if type(value['description_attribute_id'])is not int or not 0<=value['description_attribute_id']<=2**53-1:raise ValueError('listing_invalid_publication')
    return deepcopy(value)

def publication_issues(payload,metadata):
    fields=payload['fields'];ozon=payload.get('ozon')or{};pub=ozon.get('publication');issues=[]
    if not pub:return ['publication']
    validate_publication(pub)
    for k in ('depth','width','height','weight','dimension_unit','weight_unit','vat','source_ref','vat_source_ref'):
        if pub[k]is None or pub[k]==' 'or pub[k]==''or(type(pub[k])is int and pub[k]<=0):issues.append(k)
    for k in ('source_ref','vat_source_ref'):
        if not pub[k].strip()and k not in issues:issues.append(k)
    if not fields['title']or len(fields['title'])>500:issues.append('name')
    try:images(fields['image_refs'])
    except ValueError:issues.append('images')
    if not 1<=len(fields['image_refs'])<=10 and 'images'not in issues:issues.append('images')
    attrs={a['id']:a for a in ozon.get('attributes',[])};schema={a['id']:a for a in metadata};desc=attrs.get(pub['description_attribute_id']);ds=schema.get(pub['description_attribute_id'])
    if not desc or not ds or ds['dictionary_id']or ds['complex_id']or ds['type'].lower()not in ('string','text')or desc['values']!=[dict(dictionary_value_id=0,value=fields['description'])]or not fields['description']or len(fields['description'])>5000:issues.append('description_attribute')
    typ=attrs.get(8229)
    if not typ or len(typ['values'])!=1 or typ['values'][0]['dictionary_value_id']!=ozon.get('type_id'):issues.append('type_attribute')
    return issues

def projected_attributes(rows):
    if type(rows)is not list or len(rows)>500:raise ValueError('listing_submission_before_incomplete')
    result=[];seen=set()
    for row in rows:
        if type(row)is not dict or row.get('complex_id',0)!=0:raise ValueError('listing_submission_complex_not_supported')
        ident=row.get('id',row.get('attribute_id'))
        if type(ident)is not int or not 0<ident<=2**53-1 or ident in seen:raise ValueError('listing_submission_before_incomplete')
        seen.add(ident);values=row.get('values')
        if type(values)is not list or not 1<=len(values)<=100:raise ValueError('listing_submission_before_incomplete')
        for v in values:
            if type(v)is not dict or type(v.get('dictionary_value_id'))is not int or not 0<=v['dictionary_value_id']<=2**53-1 or type(v.get('value'))is not str or len(v['value'])>5000:raise ValueError('listing_submission_before_incomplete')
        result.append(dict(id=ident,complex_id=0,values=[dict(dictionary_value_id=v['dictionary_value_id'],value=v['value'])for v in values]))
    return sorted(result,key=lambda a:a['id'])

def project_before(info,attributes,sku,expected_product=None,gallery_view=None):
    rows=info.get('items')if type(info)is dict else None
    if type(rows)is not list or len(rows)>1:raise ValueError('listing_submission_scope_mismatch')
    if not rows:
        if expected_product:raise ValueError('listing_submission_existing_product_missing')
        return dict(kind='new',sku=sku,attributes=[],images=[])
    row=rows[0]
    if type(row)is not dict or row.get('offer_id')!=sku:raise ValueError('listing_submission_scope_mismatch')
    pid=identifier(row.get('id'))
    if expected_product and pid!=str(expected_product):raise ValueError('listing_submission_scope_mismatch')
    values=attributes.get('result')if type(attributes)is dict else None
    if type(values)is not list or len(values)!=1:raise ValueError('listing_submission_before_incomplete')
    a=values[0]
    if a.get('offer_id')!=sku or identifier(a.get('id'))!=pid:raise ValueError('listing_submission_scope_mismatch')
    if type(a.get('complex_attributes'))is not list:raise ValueError('listing_submission_before_incomplete')
    if a['complex_attributes']:raise ValueError('listing_submission_complex_not_supported')
    special=any(row.get(k)or a.get(k)for k in ('images360','images_360','color_image','color_images','pdf_list'))or len(a.get('barcodes')or[])>1
    if gallery_view is not None:
        special=special or gallery_view['special_images']or gallery_view['errors_present']
    result=dict(kind='existing',product_id=pid,sku=sku,category_id=int(identifier(a.get('description_category_id'))),type_id=int(identifier(a.get('type_id'))),attributes=projected_attributes(a.get('attributes')),barcode=a.get('barcode')or'',special_media=bool(special),images=gallery_view['images']if gallery_view else row.get('images',[]))
    for k in ('depth','width','height','weight','dimension_unit','weight_unit'):
        v=a.get(k)
        if v is not None and ((type(v)is not int or v<0)if k in ('depth','width','height','weight')else type(v)is not str):raise ValueError('listing_submission_before_incomplete')
        result[k]=v
    for k in ('name','price','currency_code','old_price'):
        v=row.get(k)
        if v is not None and(type(v)is not str or len(v)>2000):raise ValueError('listing_submission_before_incomplete')
        result[k]=v
    return result

def materialize(payload,metadata,before):
    if publication_issues(payload,metadata):raise ValueError('listing_submission_inputs_incomplete')
    f=payload['fields'];o=payload['ozon'];p=o['publication'];category=int(identifier(f['category_id']))
    if before['kind']=='existing':
        if before['category_id']!=category or before['type_id']!=o['type_id']:raise ValueError('listing_submission_category_change_not_supported')
        if before['special_media']:raise ValueError('listing_submission_special_media_not_supported')
    attrs={r['id']:deepcopy(r)for r in before['attributes']}
    attrs.update({r['id']:dict(id=r['id'],complex_id=0,values=deepcopy(r['values']))for r in o['attributes']})
    item=dict(offer_id=f['sku'],name=f['title'],description_category_id=category,price=str(f['price']),currency_code=f['currency'],images=f['image_refs'],attributes=sorted(attrs.values(),key=lambda r:r['id']),**{k:p[k]for k in ('depth','width','height','dimension_unit','weight','weight_unit','vat')})
    if before.get('barcode'):item['barcode']=before['barcode']
    if before.get('old_price')is not None:item['old_price']=before['old_price']
    return dict(items=[item])
