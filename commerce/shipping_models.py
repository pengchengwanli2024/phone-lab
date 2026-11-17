"""Editable physical references for one-level goods-to-carton/container packing.

Container examples come from the cited shipping line pages, not an assigned
unit's measurement or plate. Carton starters are illustrative only. No prices,
carrier bookings, network access or carton-to-container nesting are inferred.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import math
import re
from urllib.parse import urlsplit


_REQUIRED = frozenset(('id', 'name', 'inner_cm', 'outer_cm', 'tare_kg',
                       'max_weight_kg', 'packaging_cost'))
_OPTIONAL = frozenset(('kind', 'model_id', 'reference', 'door_cm'))
_PHYSICAL = ('kind', 'inner_cm', 'outer_cm', 'tare_kg', 'max_weight_kg', 'door_cm')
_SPEC_PDF = 'https://www.hapag-lloyd.com/content/dam/website/downloads/press_and_media/publications/15211_Container_Specification_engl_Gesamt_web.pdf'
_PAGE = 'https://www.hapag-lloyd.com/en/services-information/cargo-fleet/container/'
_CHECKED = '2026-11-16'


def _starter(size, inner, outer, tare, maximum):
    ident = 'carton-' + size.lower()
    return {'id': ident, 'name': size + ' 纸箱参考', 'kind': 'carton', 'model_id': ident,
            'inner_cm': inner, 'outer_cm': outer, 'tare_kg': tare,
            'max_weight_kg': maximum, 'packaging_cost': '',
            'reference': {'status': 'illustrative', 'source_name': '可编辑纸箱示例',
                          'source_urls': [], 'checked_on': _CHECKED,
                          'note': '尺寸、皮重和承重仅为起始示例，未实测且非通用标准；请按自有纸箱修改。包装费未知。'}}


def _container(code, inner, outer, tare, maximum, door, page):
    ident = 'container-' + code.lower()
    return {'id': ident, 'name': code + ' 集装箱参考', 'kind': 'container', 'model_id': ident,
            'inner_cm': inner, 'outer_cm': outer, 'tare_kg': tare,
            'max_weight_kg': maximum, 'packaging_cost': '', 'door_cm': door,
            'reference': {'status': 'reference', 'source_name': 'Hapag-Lloyd 船队规格示例',
                          'source_urls': [_PAGE + page + '.html', _SPEC_PDF],
                          'checked_on': _CHECKED,
                          'note': '内径、柜门和重量取自船公司型号页；外径取自规格手册第5页。不同厂家与箱号存在差异，装货前核对实箱、铭牌与线路限重。包装费未知。'}}


_MODELS = [
    _starter('S', [30, 20, 20], [32, 22, 22], .4, 15),
    _starter('M', [40, 30, 30], [42, 32, 32], .7, 20),
    _starter('L', [60, 40, 40], [62, 42, 42], 1.2, 25),
    _container('20GP', [590, 235.2, 239.5], [605.8, 243.8, 259.1], 2350, 30480,
               [234, 229.2], '20-standard'),
    _container('40GP', [1203.2, 235.2, 239.5], [1219.2, 243.8, 259.1], 3750, 32500,
               [234, 229.2], '40-standard'),
    # The page table gives 2350 mm width while its graphic gives 2352 mm;
    # use the smaller table value rather than silently enlarging usable space.
    _container('40HQ', [1203.2, 235, 270], [1219.2, 243.8, 289.6], 3900, 32500,
               [234, 259.7], '40-standard-high-cube'),
]
_BY_ID = {row['id']: row for row in _MODELS}


def _text(value, field, maximum=128, empty=False):
    if (type(value) is not str or len(value) > maximum
            or (not empty and not value.strip())
            or re.search(r'[\x00-\x1f\x7f]', value)):
        raise ValueError('packing_invalid_' + field)
    return value


def _number(value, field, positive=False):
    if (type(value) not in (int, float) or not 0 <= value <= 1_000_000
            or not math.isfinite(value) or (positive and value == 0)):
        raise ValueError('packing_invalid_' + field)
    return value


def _dimensions(value, field, count=3):
    if type(value) is not list or len(value) != count:
        raise ValueError('packing_invalid_' + field)
    return [_number(v, field, positive=True) for v in value]


def _reference(value):
    required = {'status', 'source_name', 'source_urls'}
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - {'checked_on', 'note'}:
        raise ValueError('packing_invalid_reference')
    if value['status'] not in ('reference', 'illustrative', 'custom', 'customized_reference'):
        raise ValueError('packing_invalid_reference_status')
    _text(value['source_name'], 'reference_source_name', 160)
    if type(value['source_urls']) is not list or len(value['source_urls']) > 4:
        raise ValueError('packing_invalid_reference_source_urls')
    for url in value['source_urls']:
        _text(url, 'reference_source_url', 1000)
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('packing_invalid_reference_source_url')
    if 'checked_on' in value:
        stamp = value['checked_on']
        if type(stamp) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', stamp):
            raise ValueError('packing_invalid_reference_checked_on')
        try:
            date.fromisoformat(stamp)
        except ValueError:
            raise ValueError('packing_invalid_reference_checked_on') from None
    if 'note' in value:
        _text(value['note'], 'reference_note', 1000, empty=True)
    return deepcopy(value)


def normalize_model(row):
    """Validate an existing carton row or a model row; return an independent copy.

    Dimensions are JSON numbers in cm; weights are kg and max_weight_kg is
    maximum gross including tare. Blank packaging_cost means unknown, never 0.
    Optional door_cm is [width, height] and constrains axis-aligned entry only.
    References are user-visible provenance, not a claim of measurement/approval.
    Legacy tare above maximum remains representable and admits no goods.
    """
    if type(row) is not dict or not _REQUIRED <= row.keys() or row.keys() - _REQUIRED - _OPTIONAL:
        raise ValueError('packing_invalid_input')
    result = deepcopy(row)
    _text(row['id'], 'carton_id')
    _text(row['name'], 'carton_name')
    inner = _dimensions(row['inner_cm'], 'inner_cm')
    outer = _dimensions(row['outer_cm'], 'outer_cm')
    if any(a > b for a, b in zip(inner, outer)):
        raise ValueError('packing_invalid_outer_cm')
    _number(row['tare_kg'], 'tare_kg')
    _number(row['max_weight_kg'], 'max_weight_kg', positive=True)
    cost = row['packaging_cost']
    if (type(cost) is not str or len(cost) > 32 or
            (cost != '' and (not re.fullmatch(r'\d+(?:\.\d+)?', cost, re.ASCII)
                             or Decimal(cost) > Decimal('1000000000000')))):
        raise ValueError('packing_invalid_packaging_cost')
    kind = row.get('kind', 'carton')
    if kind not in ('carton', 'container'):
        raise ValueError('packing_invalid_kind')
    result['kind'] = kind
    if 'model_id' in row:
        _text(row['model_id'], 'model_id')
    if 'door_cm' in row:
        door = _dimensions(row['door_cm'], 'door_cm', count=2)
        if kind != 'container' or door[0] > inner[1] or door[1] > inner[2]:
            raise ValueError('packing_invalid_door_cm')
    if 'reference' in row:
        result['reference'] = _reference(row['reference'])
        baseline = _BY_ID.get(row.get('model_id'))
        if baseline and any(result.get(key) != baseline.get(key) for key in _PHYSICAL):
            result['reference']['status'] = 'customized_reference'
    return result


def model_payload(model_id, overrides=None):
    """Copy one reference into the existing solver contract, with editable values."""
    if type(model_id) is not str or model_id not in _BY_ID:
        raise ValueError('packing_unknown_model_id')
    if overrides is not None and type(overrides) is not dict:
        raise ValueError('packing_invalid_model_overrides')
    return normalize_model(deepcopy(_BY_ID[model_id]) | deepcopy(overrides or {}))


def model_catalog():
    """Return fresh references and the requirements for fully custom physical rows."""
    return {'version': 'shipping-models-v2', 'units': {'length': 'cm', 'weight': 'kg'},
            'editable': True, 'models': deepcopy(_MODELS),
            'custom': {'kinds': ['carton', 'container'], 'requires_physical_values': True},
            'notice': '商品直接装入所选箱型或柜型；参考值可修改，装货前复测。纸箱示例非实测；集装箱示例不代表分配实箱。包装费及承运商费用需自行提供。'}
