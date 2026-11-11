"""Strict JSON-LD Product/Offer extraction. Missing fields remain missing."""
from decimal import Decimal, InvalidOperation
from html import unescape
import json
import re
from urllib.parse import urljoin, urlsplit


def plain(value):
    return re.sub(r'\s+', ' ', unescape(re.sub('<[^>]*>', '', str('' if value is None else value)))).strip()


def products(scripts, base_url):
    result=[]
    def visit(node):
        if isinstance(node,list):
            for child in node:visit(child)
        elif isinstance(node,dict):
            types=node.get('@type',[])
            if 'Product' in (types if isinstance(types,list) else [types]):
                offers=node.get('offers',[])
                offers=offers if isinstance(offers,list) else [offers]
                if len(offers)!=1 or not isinstance(offers[0],dict) or offers[0].get('@type')=='AggregateOffer':
                    raise ValueError('ambiguous_product_offers')
                offer=offers[0]
                price=''
                try:
                    number=Decimal(str(offer.get('price','')))
                    if number.is_finite() and number>=0:price=format(number,'f')
                except InvalidOperation:pass
                link=urljoin(base_url,offer.get('url') or node.get('url') or base_url)
                parsed=urlsplit(link)
                if parsed.scheme not in ('http','https') or parsed.hostname.removeprefix('www.')!=urlsplit(base_url).hostname.removeprefix('www.'):link=''
                result.append({'sku':plain(node.get('sku') or offer.get('sku')), 'title':plain(node.get('name')),
                               'price':price,'currency':plain(offer.get('priceCurrency')),
                               'stock':plain(offer.get('availability')).rsplit('/',1)[-1], 'url':link})
            if '@graph' in node:visit(node['@graph'])
    for script in scripts:
        if len(script)>1_000_000:raise ValueError('structured_payload_too_large')
        try:node=json.loads(script)
        except json.JSONDecodeError:raise ValueError('invalid_product_jsonld') from None
        visit(node)
    return result
