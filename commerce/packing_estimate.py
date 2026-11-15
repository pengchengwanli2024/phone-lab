"""Bounded offline 3D carton estimate with disjoint free-space partitions.

Inspired by the packing capability in Personal Agent OS commerce_growth.py;
independent implementation with weight admission and auditable coordinates.
"""
from decimal import Decimal, ROUND_HALF_UP
from itertools import permutations
import re

from operations_analysis import number


MAX_UNITS = 500
DIMS = ('length_cm', 'width_cm', 'height_cm')


def _object(value, required, optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError('packing_invalid_input')


def _positive(value, field):
    result = number(value, 'packing_' + field, maximum=1000000)
    if result <= 0:
        raise ValueError('packing_invalid_' + field)
    return result


def _sizes(item):
    original = item['size']
    return tuple(dict.fromkeys(permutations(original))) if item['rotation'] else (original,)


def _fits(size, space):
    return all(a <= b for a, b in zip(size, space))


def _place(box, item):
    if box['exclusive'] or (item['no_stack'] and box['items']) or box['weight'] + item['weight'] > box['limit']:
        return False
    for index, (position, space) in enumerate(box['free']):
        for size in _sizes(item):
            if not _fits(size, space):
                continue
            x, y, z = position
            length, width, height = size
            free_l, free_w, free_h = space
            # Three disjoint cuboids: beside, in front of, and above the item.
            # The upper cuboid stays within its supporting item's footprint.
            remainder = [((x + length, y, z), (free_l - length, free_w, free_h)),
                         ((x, y + width, z), (length, free_w - width, free_h)),
                         ((x, y, z + height), (length, width, free_h - height))]
            box['free'].pop(index)
            box['free'].extend((p, s) for p, s in remainder if all(v > 0 for v in s))
            box['items'].append({'sku': item['sku'], 'position_cm': [float(v) for v in position],
                                 'orientation_cm': [float(v) for v in size],
                                 'weight_kg': float(item['weight']), 'no_stack': item['no_stack']})
            box['weight'] += item['weight']
            box['volume'] += length * width * height
            box['exclusive'] = item['no_stack']
            return True
    return False


def estimate(data):
    _object(data, ('container', 'items'), ('max_boxes',))
    container = data['container']
    _object(container, (*DIMS, 'max_weight_kg'))
    dimensions = tuple(_positive(container[k], k) for k in DIMS)
    limit = _positive(container['max_weight_kg'], 'max_weight_kg')
    max_boxes = int(number(data.get('max_boxes', MAX_UNITS), 'packing_max_boxes', minimum=1,
                           maximum=MAX_UNITS, integer=True))
    rows = data['items']
    if type(rows) is not list or not 1 <= len(rows) <= 100:
        raise ValueError('packing_invalid_items')
    items, skus, total = [], set(), 0
    for row in rows:
        _object(row, ('sku', *DIMS, 'weight_kg', 'quantity'), ('rotation_allowed', 'no_stack'))
        sku = row['sku']
        if not isinstance(sku, str) or not sku.strip() or len(sku) > 128 or re.search(r'[\x00-\x1f\x7f]', sku) or sku in skus:
            raise ValueError('packing_invalid_sku')
        skus.add(sku)
        quantity = int(number(row['quantity'], 'packing_quantity', minimum=1, maximum=MAX_UNITS, integer=True))
        total += quantity
        if total > MAX_UNITS:
            raise ValueError('packing_unit_limit')
        for key in ('rotation_allowed', 'no_stack'):
            if key in row and type(row[key]) is not bool:
                raise ValueError('packing_invalid_' + key)
        items.append({'sku': sku, 'size': tuple(_positive(row[k], k) for k in DIMS),
                      'weight': number(row['weight_kg'], 'packing_weight_kg', maximum=1000000),
                      'quantity': quantity, 'rotation': row.get('rotation_allowed', True),
                      'no_stack': row.get('no_stack', False)})
    items.sort(key=lambda item: -(item['size'][0] * item['size'][1] * item['size'][2]))
    boxes, unplaced = [], []
    for item in items:
        reasons = []
        if item['weight'] > limit:
            reasons.append('UNIT_OVERWEIGHT')
        if not any(_fits(size, dimensions) for size in _sizes(item)):
            reasons.append('DIMENSIONS_EXCEEDED')
        if reasons:
            unplaced.append({'sku': item['sku'], 'quantity': item['quantity'], 'reasons': reasons})
            continue
        for unit in range(item['quantity']):
            if any(_place(box, item) for box in boxes):
                continue
            if len(boxes) >= max_boxes:
                unplaced.append({'sku': item['sku'], 'quantity': item['quantity'] - unit,
                                 'reasons': ['BOX_LIMIT_EXCEEDED']})
                break
            box = {'items': [], 'free': [((Decimal(0),) * 3, dimensions)],
                   'weight': Decimal(0), 'volume': Decimal(0), 'limit': limit, 'exclusive': False}
            if not _place(box, item):
                raise RuntimeError('packing_admission_invariant')
            boxes.append(box)
    volume = dimensions[0] * dimensions[1] * dimensions[2]
    missing = sum(row['quantity'] for row in unplaced)
    return {'model': 'disjoint_guillotine_first_fit_v1',
            'status': 'ESTIMATED' if not missing else 'PARTIAL' if boxes else 'NO_FIT',
            'data_source': 'caller_input', 'review_required': True, 'marketplace_writes': False,
            'input_units': total, 'placed_units': total - missing, 'unplaced_units': missing,
            'box_count': len(boxes), 'max_boxes': max_boxes, 'unplaced': unplaced,
            'boxes': [{'box_index': i + 1, 'items': b['items'], 'total_weight_kg': float(b['weight']),
                       'volume_utilization_pct': float((b['volume'] / volume * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))}
                      for i, b in enumerate(boxes)],
            'assumptions': ['Dimensions are usable inner carton sizes in cm; weights use kg.',
                            'Heuristic estimate; it does not prove the minimum number of cartons.',
                            'no_stack conservatively reserves a whole carton for that unit.',
                            'Cushioning, fragility, load strength, centre of gravity and carrier rules require manual review.']}


def definitions(schema):
    positive = {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 1000000}
    item = schema({'sku': {'type': 'string', 'minLength': 1, 'maxLength': 128},
                   **{k: positive for k in DIMS},
                   'weight_kg': {'type': 'number', 'minimum': 0, 'maximum': 1000000},
                   'quantity': {'type': 'integer', 'minimum': 1, 'maximum': MAX_UNITS},
                   'rotation_allowed': {'type': 'boolean', 'default': True},
                   'no_stack': {'type': 'boolean', 'default': False}},
                  ['sku', *DIMS, 'weight_kg', 'quantity'])
    body = schema({'container': schema({**{k: positive for k in DIMS}, 'max_weight_kg': positive}, [*DIMS, 'max_weight_kg']),
                   'items': {'type': 'array', 'items': item, 'minItems': 1, 'maxItems': 100},
                   'max_boxes': {'type': 'integer', 'minimum': 1, 'maximum': MAX_UNITS, 'default': MAX_UNITS}},
                  ['container', 'items'])
    return [('commerce_packing_estimate',
             '按调用者提供的内径(cm)、重量(kg)估算3D装箱；最多500件，返回位置、限重和未装入原因。只读几何草稿，非最优解或承运商验收。',
             schema({'input': body}, ['input']))]
