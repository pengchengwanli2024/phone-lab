"""Strict, bounded projections for the existing Ozon read-only transport."""
from ozon_reader import ConnectionIssue

PATHS={'tree':'/v1/description-category/tree','attributes':'/v1/description-category/attribute',
       'values':'/v1/description-category/attribute/values'}
MAX_ID=2**53-1


def ident(value,zero=False):
    if type(value)is not int or not (0 if zero else 1)<=value<=MAX_ID:
        raise ValueError('listing_schema_invalid_id')
    return value


def text(value,maximum=2000):
    if not isinstance(value,str)or len(value)>maximum:raise ConnectionIssue('listing_schema_unexpected_response')
    return value


def flag(row,key,default=None):
    value=row.get(key,default)
    if type(value)is not bool:raise ConnectionIssue('listing_schema_unexpected_response')
    return value


def project(resource,payload):
    if type(payload)is not dict or type(payload.get('result'))is not list:
        raise ConnectionIssue('listing_schema_unexpected_response')
    rows=payload['result'];result=[];seen=set()
    if resource=='tree':
        def walk(nodes,parent=None,path=(),disabled=False,depth=0):
            if depth>12 or len(seen)>50000:raise ConnectionIssue('listing_schema_response_too_large')
            for row in nodes:
                if type(row)is not dict or type(row.get('children'))is not list:raise ConnectionIssue('listing_schema_unexpected_response')
                blocked=disabled or flag(row,'disabled',False)
                category=row.get('description_category_id',parent)
                if category is not None:ident(category)
                label=text(row.get('category_name',row.get('type_name','')),500)
                current=(*path,label)if label else path
                if row.get('type_id'):
                    kind=ident(row['type_id']);ident(category);pair=(category,kind)
                    if pair in seen:raise ConnectionIssue('listing_schema_duplicate_identity')
                    seen.add(pair);result.append(dict(category_id=category,type_id=kind,label=label,path=' / '.join(current),disabled=blocked))
                walk(row['children'],category,current,blocked,depth+1)
        walk(rows)
        if not result:raise ConnectionIssue('listing_schema_empty_tree')
        return dict(records=result)
    if len(rows)>5000:raise ConnectionIssue('listing_schema_response_too_large')
    for row in rows:
        if type(row)is not dict:raise ConnectionIssue('listing_schema_unexpected_response')
        key=ident(row.get('id'))
        if key in seen:raise ConnectionIssue('listing_schema_duplicate_identity')
        seen.add(key)
        if resource=='attributes':
            result.append(dict(id=key,name=text(row.get('name'),500),description=text(row.get('description',''),20000),
                type=text(row.get('type'),80),is_required=flag(row,'is_required'),is_collection=flag(row,'is_collection'),
                dictionary_id=ident(row.get('dictionary_id'),True),max_value_count=ident(row.get('max_value_count',0),True),
                complex_id=ident(row.get('attribute_complex_id',0),True)))
        else:result.append(dict(id=key,value=text(row.get('value'),5000)))
    if resource=='values':
        more=flag(payload,'has_next')
        if more and not result:raise ConnectionIssue('listing_schema_invalid_cursor')
        return dict(records=result,has_next=more,next_cursor=result[-1]['id']if more else None)
    return dict(records=result)


def validate_ozon(value):
    """Optional typed extension; old listing payloads remain byte-for-byte shaped."""
    try:
        if type(value)is not dict or set(value)!={'type_id','attributes'}:raise ValueError()
        ident(value['type_id'],True)
        if type(value['attributes'])is not list or len(value['attributes'])>500:raise ValueError()
        seen=set();out=[]
        for row in value['attributes']:
            if type(row)is not dict or set(row)!={'id','values','source_ref'}:raise ValueError()
            key=ident(row['id'])
            if key in seen:raise ValueError()
            seen.add(key)
            if not isinstance(row['source_ref'],str)or len(row['source_ref'])>1000:raise ValueError()
            values=row['values']
            if type(values)is not list or not 1<=len(values)<=100:raise ValueError()
            for v in values:
                if type(v)is not dict or set(v)!={'dictionary_value_id','value'}:raise ValueError()
                ident(v['dictionary_value_id'],True);text(v['value'],5000)
            out.append(dict(id=key,values=values,source_ref=row['source_ref'].strip()))
        return dict(type_id=value['type_id'],attributes=out)
    except (ValueError,ConnectionIssue):raise ValueError('listing_invalid_ozon')from None
