"""Bounded, offline shipping carton candidates with auditable 3D placements.

This is a conservative guillotine heuristic, not a proof of optimal packing.
Each free cuboid has full support beneath its footprint; subdividing it keeps
that property. A no_stack unit conservatively occupies a whole carton. There
are no carrier tariffs, network calls or marketplace writes in this module.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
from itertools import permutations
import json
import math
import re

from shipping_models import normalize_model


MAX_UNITS = 500
MAX_SKUS = 100
MAX_CARTONS = 12
MAX_BOXES = 100
MAX_CANDIDATES = 32
# Each of at most 16 initial strategies and its downsizing pass receives its
# own finite orientation-test budget. Hitting it returns an honest partial plan.
MAX_PLACEMENT_CHECKS = 100_000
_DIMS = ('length_cm', 'width_cm', 'height_cm')
_ZERO = Fraction(0)
_Vec = tuple[Fraction, Fraction, Fraction]


@dataclass(frozen=True)
class _Item:
    sku: str
    quantity: int
    size: _Vec
    weight: Fraction
    orientations: tuple[_Vec, ...]
    no_stack: bool

    @property
    def volume(self):
        return math.prod(self.size)


@dataclass(frozen=True)
class _Carton:
    id: str
    name: str
    inner: _Vec
    outer: _Vec
    tare: Fraction
    max_weight: Fraction
    packaging_cost: str
    metadata: dict
    door: tuple[Fraction, Fraction] | None

    @property
    def outer_volume(self):
        return math.prod(self.outer)


@dataclass
class _Box:
    carton: _Carton
    free: list[tuple[_Vec, _Vec]] = field(default_factory=list)
    placements: list[tuple[_Item, _Vec, _Vec]] = field(default_factory=list)
    goods_weight: Fraction = _ZERO
    goods_volume: Fraction = _ZERO
    exclusive: bool = False

    def __post_init__(self):
        self.free = [((_ZERO, _ZERO, _ZERO), self.carton.inner)]


class _SearchLimit(Exception):
    pass


@dataclass
class _Budget:
    remaining: int = MAX_PLACEMENT_CHECKS

    def check(self):
        if self.remaining <= 0:
            raise _SearchLimit
        self.remaining -= 1


def _object(value, required, optional=()):
    if type(value) is not dict or set(required) - value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError('packing_invalid_input')


def _number(value, name, positive=False):
    # Match the existing commerce numeric boundary: JSON numbers, never bools
    # or coercible strings. Fractions keep subtraction and weight admission exact.
    if type(value) not in (int, float) or not 0 <= value <= 1_000_000 or (type(value) is float and not math.isfinite(value)):
        raise ValueError('packing_invalid_' + name)
    if positive and value == 0:
        raise ValueError('packing_invalid_' + name)
    return Fraction(str(value))


def _integer(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError('packing_invalid_' + name)
    return value


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 128 or re.search(r'[\x00-\x1f\x7f]', value):
        raise ValueError('packing_invalid_' + name)
    return value


def _dimensions(value, name):
    if type(value) is not list or len(value) != 3:
        raise ValueError('packing_invalid_' + name)
    return tuple(_number(v, name, positive=True) for v in value)


def _validate(items, cartons, max_boxes):
    _integer(max_boxes, 'max_boxes', MAX_BOXES)
    if type(items) is not list or not 1 <= len(items) <= MAX_SKUS:
        raise ValueError('packing_invalid_items')
    if type(cartons) is not list or not 1 <= len(cartons) <= MAX_CARTONS:
        raise ValueError('packing_invalid_cartons')
    parsed_items, identities, total = [], set(), 0
    for row in items:
        _object(row, ('sku', 'quantity', *_DIMS, 'weight_kg'), ('rotation_allowed', 'no_stack'))
        sku = _text(row['sku'], 'sku')
        if sku in identities:
            raise ValueError('packing_duplicate_sku')
        identities.add(sku)
        quantity = _integer(row['quantity'], 'quantity', MAX_UNITS)
        total += quantity
        if total > MAX_UNITS:
            raise ValueError('packing_unit_limit')
        size = tuple(_number(row[k], k, positive=True) for k in _DIMS)
        weight = _number(row['weight_kg'], 'weight_kg')
        for key in ('rotation_allowed', 'no_stack'):
            if key in row and type(row[key]) is not bool:
                raise ValueError('packing_invalid_' + key)
        orientations = tuple(dict.fromkeys(permutations(size))) if row.get('rotation_allowed', True) else (size,)
        parsed_items.append(_Item(sku, quantity, size, weight, orientations, row.get('no_stack', False)))
    parsed_cartons, identities = [], set()
    for row in cartons:
        row = normalize_model(row)
        identity = _text(row['id'], 'carton_id')
        if identity in identities:
            raise ValueError('packing_duplicate_carton_id')
        identities.add(identity)
        name = _text(row['name'], 'carton_name')
        inner, outer = _dimensions(row['inner_cm'], 'inner_cm'), _dimensions(row['outer_cm'], 'outer_cm')
        if any(a > b for a, b in zip(inner, outer)):
            raise ValueError('packing_invalid_outer_cm')
        tare = _number(row['tare_kg'], 'tare_kg')
        maximum = _number(row['max_weight_kg'], 'max_weight_kg', positive=True)
        cost = row['packaging_cost']
        metadata = {key: row[key] for key in ('kind', 'model_id', 'reference', 'door_cm') if key in row}
        door = tuple(Fraction(str(v)) for v in row['door_cm']) if 'door_cm' in row else None
        parsed_cartons.append(_Carton(identity, name, inner, outer, tare, maximum, cost, metadata, door))
    return parsed_items, parsed_cartons, total


def _fits(size, space):
    return all(length <= boundary for length, boundary in zip(size, space))


def _door_fits(size, carton):
    return carton.door is None or (size[1] <= carton.door[0] and size[2] <= carton.door[1])


def _cost_order(carton):
    # Unknown costs are ordered after known ones solely for deterministic ties.
    # The original blank survives output and is never used as a quoted zero.
    return (carton.packaging_cost == '', Decimal(carton.packaging_cost or '0'))


def _eligible(item, carton):
    return item.weight + carton.tare <= carton.max_weight and any(_fits(size, carton.inner) and _door_fits(size, carton) for size in item.orientations)


def _place(box, item, budget):
    if box.exclusive or (item.no_stack and box.placements) or box.goods_weight + item.weight + box.carton.tare > box.carton.max_weight:
        return False
    # Lower spaces are tried first. Orientation is selected independently for
    # every unit, including consecutive units of the same SKU.
    for index in sorted(range(len(box.free)), key=lambda i: (box.free[i][0][2], box.free[i][0][1], box.free[i][0][0])):
        position, space = box.free[index]
        fitting = []
        for size in item.orientations:
            budget.check()
            if _fits(size, space) and _door_fits(size, box.carton):
                fitting.append(size)
        if not fitting:
            continue
        size = min(fitting, key=lambda dimensions: (tuple(sorted(a - b for a, b in zip(space, dimensions))), dimensions[2], dimensions))
        x, y, z = position
        length, width, height = size
        free_l, free_w, free_h = space
        # These three cuboids are disjoint. Side/front fragments inherit the
        # parent's support; the top fragment stays on the new unit's footprint.
        remainder = [((x + length, y, z), (free_l - length, free_w, free_h)),
                     ((x, y + width, z), (length, free_w - width, free_h)),
                     ((x, y, z + height), (length, width, free_h - height))]
        box.free.pop(index)
        box.free.extend((p, s) for p, s in remainder if all(v > 0 for v in s))
        box.placements.append((item, position, size))
        box.goods_weight += item.weight
        box.goods_volume += item.volume
        box.exclusive = item.no_stack
        return True
    return False


def _admission_reasons(item, cartons):
    reasons = []
    if not any(any(_fits(size, carton.inner) for size in item.orientations) for carton in cartons):
        reasons.append('DIMENSIONS_EXCEEDED')
    if not any(item.weight + carton.tare <= carton.max_weight for carton in cartons):
        reasons.append('UNIT_OVERWEIGHT')
    if not reasons and not any(any(_fits(size, carton.inner) and _door_fits(size, carton)
                                  for size in item.orientations) for carton in cartons):
        reasons.append('DOOR_OPENING_EXCEEDED')
    return reasons or ['NO_COMPATIBLE_CARTON']


def _units(items, order):
    if order == 'longest':
        key = lambda item: (-max(item.size), -item.volume, -item.weight, item.sku)
    else:
        key = lambda item: (-item.volume, -item.weight, item.sku)
    return [item for item in sorted(items, key=key) for _ in range(item.quantity)]


def _pack(items, cartons, max_boxes, order):
    units, boxes, missing = _units(items, order), [], {}
    budget = _Budget()

    def omit(item, reasons):
        entry = missing.setdefault(item.sku, {'sku': item.sku, 'quantity': 0, 'reasons': []})
        entry['quantity'] += 1
        entry['reasons'] = sorted(set(entry['reasons']) | set(reasons))

    admission = {item.sku: [carton for carton in cartons if _eligible(item, carton)] for item in items}
    for index, item in enumerate(units):
        if not admission[item.sku]:
            omit(item, _admission_reasons(item, cartons))
            continue
        try:
            if any(_place(box, item, budget) for box in boxes):
                continue
            if len(boxes) >= max_boxes:
                omit(item, ['BOX_LIMIT_EXCEEDED'])
                continue
            box = _Box(admission[item.sku][0])
            if not _place(box, item, budget):
                raise RuntimeError('packing_admission_invariant')
            boxes.append(box)
        except _SearchLimit:
            for remaining in units[index:]:
                reasons = _admission_reasons(remaining, cartons) if not admission[remaining.sku] else ['SEARCH_LIMIT_REACHED']
                omit(remaining, reasons)
            break
    return boxes, [missing[sku] for sku in sorted(missing)]


def _downsize(boxes, cartons):
    # Each original box is repacked independently. This offers mixed-carton
    # tails without an exponential search over carton combinations.
    smaller_first = sorted(cartons, key=lambda carton: (carton.outer_volume, _cost_order(carton), carton.id))
    result, changed, budget = [], False, _Budget()
    for box_index, original in enumerate(boxes):
        chosen = original
        units = [placement[0] for placement in original.placements]
        for carton in smaller_first:
            if carton.outer_volume >= original.carton.outer_volume or not all(_eligible(item, carton) for item in units):
                continue
            trial = _Box(carton)
            try:
                if all(_place(trial, item, budget) for item in units):
                    chosen, changed = trial, True
                    break
            except _SearchLimit:
                return result + boxes[box_index:], changed
        result.append(chosen)
    return result, changed


def _signature(boxes, unplaced):
    # Carton identity plus SKU quantities determines physical/carrier inputs.
    # Rearrangements with the same allocation are equivalent candidates.
    allocations = sorted((box.carton.id, tuple(sorted(Counter(p[0].sku for p in box.placements).items()))) for box in boxes)
    missing = [(row['sku'], row['quantity'], row['reasons']) for row in unplaced]
    return json.dumps([allocations, missing], ensure_ascii=True, separators=(',', ':'))


def _export_box(box):
    return {'carton_id': box.carton.id, 'carton_name': box.carton.name,
            **deepcopy(box.carton.metadata),
            'inner_cm': [float(v) for v in box.carton.inner],
            'outer_cm': [float(v) for v in box.carton.outer],
            'tare_kg': float(box.carton.tare), 'max_weight_kg': float(box.carton.max_weight),
            'packaging_cost': box.carton.packaging_cost,
            'goods_weight_kg': float(box.goods_weight),
            'gross_weight_kg': float(box.goods_weight + box.carton.tare),
            'volume_utilization_pct': round(float(box.goods_volume / math.prod(box.carton.inner) * 100), 1),
            'items': [{'sku': item.sku, 'position_cm': [float(v) for v in position],
                       'orientation_cm': [float(v) for v in size], 'weight_kg': float(item.weight),
                       'no_stack': item.no_stack} for item, position, size in box.placements]}


def candidates(items, cartons, max_boxes=MAX_BOXES):
    """Return deduplicated geometry candidates for one caller-defined group.

    Inputs use JSON numbers, integer quantities, cm and kg; packaging_cost is
    a nonnegative decimal string or blank for unknown. Optional model metadata
    survives output. A container door constrains width/height in the placement
    orientation; tilting, loading paths, floor strength and securing are not
    proven. Dimensions/weights are bounded at 1,000,000,
    with <= 500 units, 100 SKUs, 12 carton types and 100 boxes. The result is
    deterministic and input objects are never mutated. Caller-supplied carton
    max_weight_kg includes tare. A carton with tare exceeding its limit admits
    no goods. Neither freight prices nor a global optimum are inferred.

    There are <= 12 fixed-type strategies, four mixed strategies and one
    downsizing pass per strategy, each with <= 100,000 orientation tests.
    Exhausted searches report SEARCH_LIMIT_REACHED instead of false success.
    """
    parsed_items, parsed_cartons, total = _validate(items, cartons, max_boxes)
    input_signature = json.dumps([items, cartons, max_boxes], ensure_ascii=True,
                                 sort_keys=True, separators=(',', ':'))
    small = sorted(parsed_cartons, key=lambda carton: (carton.outer_volume, _cost_order(carton), carton.id))
    large = sorted(parsed_cartons, key=lambda carton: (-carton.outer_volume, _cost_order(carton), carton.id))
    strategies = [(f'fixed:{carton.id}', [carton], 'volume') for carton in parsed_cartons]
    strategies += [(f'mixed:{direction}:{order}', ordering, order)
                   for direction, ordering in (('small', small), ('large', large))
                   for order in ('volume', 'longest')]
    plans, seen = [], set()

    def add(boxes, missing, algorithm):
        signature = _signature(boxes, missing)
        if signature in seen or len(plans) >= MAX_CANDIDATES:
            return
        seen.add(signature)
        plans.append({'id': 'packing_' + sha256((input_signature + signature).encode('ascii')).hexdigest()[:16],
                      'boxes': [_export_box(box) for box in boxes], 'unplaced': missing,
                      'placed_units': total - sum(row['quantity'] for row in missing), 'input_units': total,
                      'total_outer_volume_cm3': float(sum((box.carton.outer_volume for box in boxes), _ZERO)),
                      'box_count': len(boxes), 'complete': not missing,
                      'algorithm': 'bounded_supported_guillotine_v1:' + algorithm})

    for label, ordering, order in strategies:
        boxes, missing = _pack(parsed_items, ordering, max_boxes, order)
        add(boxes, missing, label)
        downsized, changed = _downsize(boxes, parsed_cartons)
        if changed:
            add(downsized, missing, label + ':downsize')
    return plans
