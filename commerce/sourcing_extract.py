"""Bounded product metadata extraction. Exported statements remain unverified."""
from html.parser import HTMLParser
import json, re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit, parse_qs, parse_qsl

MAX_CONTENT = 200000

def clean(value, limit=1000):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]

def price(value):
    try:
        if isinstance(value, bool): return None
        v=Decimal(str(value))
        return str(v) if v.is_finite() and 0<=v<=Decimal('1000000000') else None
    except (InvalidOperation, ValueError, TypeError): return None

def public_image(value, origin):
    try:
        from product_evidence import url
        return url(urljoin(origin, value))
    except (ValueError, TypeError): return None

def product_url_match(data, origin):
    """Compare declared product identity; missing legacy URLs remain unknown."""
    reference=data.get('url') or data.get('@id')
    if isinstance(reference,dict):reference=reference.get('@id') or reference.get('url')
    if not isinstance(reference,str) or not reference:return None
    if not reference.startswith(('http://','https://','/','#')):return None
    def identity(value):
        p=urlsplit(value)
        query=tuple(sorted((k,v) for k,v in parse_qsl(p.query,keep_blank_values=True)
                           if not k.lower().startswith('utm_') and k.lower() not in ('spm','scm')))
        return (p.hostname or '').lower(),p.port,p.path.rstrip('/'),query
    try:return identity(urljoin(origin,reference))==identity(origin)
    except (ValueError,TypeError):return False

def normalize(data, origin, method):
    if not isinstance(data, dict): raise ValueError('sourcing_product_object_required')
    if product_url_match(data,origin) is False:raise ValueError('sourcing_product_url_mismatch')
    title=clean(data.get('name') or data.get('title'), 500)
    if not title: raise ValueError('sourcing_product_title_required')
    images=data.get('image', data.get('images', []))
    if isinstance(images, (str,dict)): images=[images]
    if not isinstance(images,list): images=[]
    urls=[]
    for image in images[:24]:
        v=public_image(image.get('url') or image.get('contentUrl') if isinstance(image,dict) else image,origin)
        if v and v not in urls: urls.append(v)
    offers=data.get('offers',[])
    if isinstance(offers,dict): offers=[offers]
    if not isinstance(offers,list): offers=[]
    rows=[]
    for o in offers[:20]:
        if not isinstance(o,dict): continue
        aggregate=o.get('@type')=='AggregateOffer' or 'lowPrice' in o
        amount=price(o.get('price'))
        currency=clean(o.get('priceCurrency') or o.get('currency'),10).upper()
        currency=currency if re.fullmatch('[A-Z]{3}',currency) else ''
        if amount is None and not aggregate:continue
        seller=o.get('seller',{})
        offered=o.get('itemOffered',{})
        if not isinstance(offered,dict):offered={}
        rows.append({'price':amount,'currency':currency,'variant':clean(o.get('variant') or o.get('name') or offered.get('variant') or offered.get('name') or offered.get('sku'),500),
                     'sku':clean(offered.get('sku') or o.get('sku'),200),
                     'moq':clean(o.get('moq'),80),'seller':clean(seller.get('name') if isinstance(seller,dict) else seller,500),
                     'kind':'price_range_not_variant_quote' if aggregate else 'advertised_not_formal_quote',
                     'low_price':price(o.get('lowPrice')),'high_price':price(o.get('highPrice'))})
    specifications={k:data[k] for k in ('attributes','dimensions','weight','packaging','material','variants') if k in data}
    return {'title':title,'model':clean(data.get('model') or data.get('sku'),200),'variant':clean(data.get('variant'),500),
            'supplier':clean(data.get('supplier'),500),'description':clean(data.get('description'),1800),
            'specifications':clean(json.dumps(specifications,ensure_ascii=False),1800) if specifications else '',
            'images':urls[:12],'offers':rows,'method':method,'independently_verified':False}

class Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.meta={};self.blocks=[];self.current=None;self.total=0;self.title=[];self.in_title=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='title':self.in_title=True
        if tag=='meta':
            key=(a.get('property') or a.get('name') or '').lower()
            if key.startswith(('og:','product:')):self.meta[key]=a.get('content','')[:4000]
        if tag=='script' and a.get('type','').lower()=='application/ld+json' and len(self.blocks)<12:self.current=[]
    def handle_data(self,data):
        if self.in_title:self.title.append(data[:1000])
        if self.current is not None and self.total<MAX_CONTENT:
            data=data[:MAX_CONTENT-self.total];self.current.append(data);self.total+=len(data)
    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False
        if tag=='script' and self.current is not None:
            self.blocks.append(''.join(self.current));self.current=None

def products(value, depth=0):
    if depth>8:return []
    if isinstance(value,list):return [p for v in value[:30] for p in products(v,depth+1)][:12]
    if not isinstance(value,dict):return []
    kind=value.get('@type',[]);kind=[kind] if isinstance(kind,str) else kind
    if isinstance(kind,list) and any(str(k).split('/')[-1]=='Product' for k in kind):return [value]
    return [p for k,v in list(value.items())[:40] if k in ('@graph','mainEntity','itemListElement','item') for p in products(v,depth+1)][:12]

def exact_product_url(origin):
    p=urlsplit(origin);host=p.hostname or '';q=parse_qs(p.query)
    return (host=='item.jd.com' and p.path.endswith('.html')
            or host in ('item.taobao.com','detail.tmall.com') and p.path=='/item.htm' and bool(q.get('id'))
            or host in ('www.chinagoods.com','chinagoods.com') and bool(re.fullmatch(r'/store/goodsdetail/\d+',p.path))
            or (host=='yiwugo.com' or host.endswith('.yiwugo.com')) and bool(re.fullmatch(r'/product/detail/\d+\.html',p.path))
            or (host=='made-in-china.com' or host.endswith('.made-in-china.com')) and p.path.startswith('/product/') and p.path.endswith('.html'))

def html_product(html, origin):
    parser=Metadata();parser.feed(html);found=[]
    for block in parser.blocks:
        try:found.extend(products(json.loads(block)))
        except (ValueError,RecursionError):continue
    # Do not silently choose an unrelated first product on a catalogue page.
    if len(found)>1:
        matching=[item for item in found if product_url_match(item,origin) is True]
        if len(matching)==1:found=matching
        else:return {'multiple_products':True,'count':len(found),'independently_verified':False}
    if found:
        try:return normalize(found[0],origin,'page_json_ld')
        except ValueError:return None
    partial=parser.meta.get('og:type') not in ('product','og:product')
    if partial and not exact_product_url(origin):return None
    title=parser.meta.get('og:title') or clean(' '.join(parser.title),500)
    if re.search(r'captcha|安全验证|访问验证|访问受限|登录|sign.?in|access denied',title,re.I):return None
    data={'title':title,'image':parser.meta.get('og:image'),
          'description':parser.meta.get('og:description'),
          'offers':{'price':parser.meta.get('product:price:amount'),'priceCurrency':parser.meta.get('product:price:currency')}}
    try:
        result=normalize(data,origin,'page_metadata_partial' if partial else 'page_open_graph')
        if partial:result['needs_variant_confirmation']=True
        return result
    except ValueError:return None

def imported(content, format, origin):
    if not isinstance(content,str) or not 0<len(content)<=MAX_CONTENT:raise ValueError('sourcing_import_size')
    if format=='json':
        try:data=json.loads(content)
        except (ValueError,RecursionError):raise ValueError('sourcing_invalid_json') from None
        found=products(data)
        if len(found)>1:raise ValueError('sourcing_choose_exact_product')
        return normalize(found[0] if found else data,origin,'user_export_json')
    if format=='html':
        data=html_product(content,origin)
        if data and not data.get('multiple_products'):return {**data,'method':'user_export_html'}
        raise ValueError('sourcing_structured_product_missing')
    raise ValueError('sourcing_import_format')
