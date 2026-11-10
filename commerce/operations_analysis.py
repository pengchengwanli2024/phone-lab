"""Read-only draft calculations adapted from ozon-ops; see THIRD_PARTY_NOTICES.md.

No embedded marketplace tariffs, automatic FX, API calls or purchasing actions.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
import re


MONEY = ('purchase_cost', 'domestic_shipping', 'packaging', 'fulfillment_cost', 'electronic_fee')
RATES = ('commission_rate', 'payment_rate', 'return_rate', 'ad_rate')
UNIT_FIELDS = ('currency', 'price', *MONEY, *RATES)
STOCK_FIELDS = ('available', 'sold_units', 'window_days', 'lead_time_days', 'safety_days', 'pack_size')


def draft(model):
    return {'model': model, 'status': 'HOLD', 'data_source': 'caller_input',
            'review_required': True, 'marketplace_writes': False, 'missing': []}


def number(value, name, minimum=0, maximum=10**12, integer=False):
    if type(value) not in (int, float):
        raise ValueError('invalid_' + name)
    n = Decimal(str(value))
    if not n.is_finite() or not minimum <= n <= maximum or (integer and n != n.to_integral_value()):
        raise ValueError('invalid_' + name)
    return n


def inputs(data, fields):
    if not isinstance(data, dict) or set(data) - set(fields):
        raise ValueError('invalid_analysis_input')
    return [key for key in fields if data.get(key) is None]


def money(value):
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def unit_economics(data):
    result = draft('explicit_unit_contribution')
    result.update(contribution=None, contribution_rate=None, total_cost=None)
    result['missing'] = inputs(data, UNIT_FIELDS)
    if result['missing']:
        return result
    currency = data['currency']
    if not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency):
        raise ValueError('invalid_currency')
    price = money(number(data['price'], 'price', minimum=Decimal('0.01')))
    components = {key: money(number(data[key], key)) for key in MONEY}
    for key in RATES:
        components[key.removesuffix('_rate')] = money(price * number(data[key], key, maximum=1))
    total = money(sum(components.values()))
    contribution = money(price - total)
    result.update(status='CALCULATED', currency=currency, rounding_decimals=2,
                  price=float(price), cost_breakdown={k: float(v) for k, v in components.items()},
                  total_cost=float(total), contribution=float(contribution),
                  contribution_rate=float((contribution / price).quantize(Decimal('0.000001'))),
                  assumptions=['All input amounts use the stated currency; no FX conversion.',
                               'Rates apply to the stated sale price; fees and costs require caller verification.',
                               'Two-decimal contribution model, not a settlement or accounting statement.'])
    return result


def restock_plan(data):
    result = draft('windowed_stock_cover')
    result.update(velocity=None, days_of_cover=None, target_units=None, suggested_qty=None, urgency=None)
    result['missing'] = inputs(data, STOCK_FIELDS)
    if result['missing']:
        return result
    available = number(data['available'], 'available', integer=True)
    sold = number(data['sold_units'], 'sold_units', integer=True)
    window = number(data['window_days'], 'window_days', minimum=1, maximum=365, integer=True)
    lead = number(data['lead_time_days'], 'lead_time_days', maximum=365, integer=True)
    safety = number(data['safety_days'], 'safety_days', maximum=365, integer=True)
    pack = number(data['pack_size'], 'pack_size', minimum=1, maximum=10**9, integer=True)
    if sold == 0:
        result.update(velocity=0, reason='no_demand_observed')
        return result
    velocity = sold / window
    cover = available / velocity
    target = velocity * (lead + safety)
    quantity = max(Decimal(0), target - available)
    packs = (quantity / pack).to_integral_value(rounding=ROUND_CEILING)
    urgency = 'P0' if cover <= lead else 'P1' if cover <= lead + safety else 'P2'
    result.update(status='CALCULATED', velocity=float(velocity.quantize(Decimal('0.000001'))),
                  days_of_cover=float(cover.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                  target_units=int(target.to_integral_value(rounding=ROUND_CEILING)),
                  suggested_qty=int(packs * pack), urgency=urgency,
                  assumptions=['Forecast extrapolates the supplied observation window; demand is not guaranteed.',
                               'Available means current usable stock; inbound deliveries are not modelled.',
                               'No purchase order or inventory update is created.'])
    return result


def input_schema(fields):
    properties = {}
    for key in fields:
        properties[key] = {'type': 'string', 'pattern': '^[A-Z]{3}$'} if key == 'currency' else {'type': 'integer' if key in STOCK_FIELDS else 'number', 'minimum': 0}
    return {'type': 'object', 'properties': properties, 'additionalProperties': False}
