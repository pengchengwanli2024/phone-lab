"""Validate user-supplied CSV tariffs and compute local comparison estimates.

This module never contacts carriers, converts currency, or confirms settlement.
Decimal quantities are kept as strings at its JSON-facing boundaries. Formula-like
text is inert here; callers exporting it to spreadsheets must escape CSV formulas.
"""
import csv
import io
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_UP, localcontext


COLUMNS = (
    'id', 'name', 'mode', 'origin', 'destination', 'currency',
    'valid_from', 'valid_until', 'basis', 'divisor', 'round_step',
    'min_charge', 'unit_price', 'base_fee', 'shipment_fee', 'fuel_pct',
    'other_fee', 'max_weight_kg', 'max_length_cm', 'max_girth_cm',
    'included_fees', 'excluded_fees',
)
MAX_RATES = 200
MAX_CSV_BYTES = 1_000_000
MAX_BOXES = 10_000
_NUMBER = re.compile(r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z')
_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\Z')
_CURRENCY = re.compile(r'[A-Z]{3}\Z')
_NUMERIC_LIMITS = {
    'divisor': '1000000000', 'round_step': '1000000',
    'min_charge': '1000000000', 'unit_price': '1000000000000',
    'base_fee': '1000000000000', 'shipment_fee': '1000000000000',
    'fuel_pct': '100', 'other_fee': '1000000000000',
    'max_weight_kg': '1000000', 'max_length_cm': '1000000',
    'max_girth_cm': '1000000',
}
_TEXT_LIMITS = {'id': 100, 'name': 200, 'origin': 200, 'destination': 200,
                'included_fees': 2000, 'excluded_fees': 2000}
_ZERO = Decimal(0)
_CENT = Decimal('.01')


def _error(row, field, message):
    return ValueError(f'shipping_invalid：第{row}行 {field} {message}')


def _decimal(value, field, row, maximum, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise _error(row, field, '必须为有限非负十进制数')
    text = str(value).strip()
    # Bound parsing and arithmetic before constructing a Decimal; exponents and
    # excessive precision are not part of this CSV format.
    if (len(text) > 40 or not _NUMBER.fullmatch(text)
            or len(text.partition('.')[2]) > 9):
        raise _error(row, field, '必须为有限非负十进制数，最多9位小数')
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise _error(row, field, '必须为有限十进制数') from exc
    if not number.is_finite() or number < 0 or number > Decimal(maximum):
        raise _error(row, field, f'必须在0至{maximum}之间')
    if positive and number == 0:
        raise _error(row, field, '必须大于0')
    return number


def _plain(number):
    text = format(number, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _money(number):
    return number.quantize(_CENT, rounding=ROUND_HALF_UP)


def _date(value, field, row):
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise _error(row, field, '必须为YYYY-MM-DD有效日期')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _error(row, field, '必须为YYYY-MM-DD有效日期') from exc


def _normalize_rate(row, line):
    if not isinstance(row, Mapping) or set(row) != set(COLUMNS):
        raise _error(line, 'columns', '必须完整提供规定的全部字段且无未知字段')
    normalized = {}
    for key in COLUMNS:
        value = row[key]
        if not isinstance(value, str):
            raise _error(line, key, '必须为非空文本')
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise _error(line, key, '不能为空或包含控制字符')
        limit = _TEXT_LIMITS.get(key, 40)
        if len(value) > limit:
            raise _error(line, key, f'超过{limit}字符上限')
        normalized[key] = value
    if normalized['mode'] not in ('warehouse', 'buyer', 'both'):
        raise _error(line, 'mode', '必须为warehouse、buyer或both')
    if normalized['basis'] not in ('weight', 'volume'):
        raise _error(line, 'basis', '必须为weight或volume')
    if not _CURRENCY.fullmatch(normalized['currency']):
        raise _error(line, 'currency', '必须为3位大写币种代码')
    start = _date(normalized['valid_from'], 'valid_from', line)
    end = _date(normalized['valid_until'], 'valid_until', line)
    if end < start:
        raise _error(line, 'valid_until', '不得早于valid_from')
    for key, limit in _NUMERIC_LIMITS.items():
        normalized[key] = _plain(_decimal(normalized[key], key, line, limit,
                                          positive=key == 'round_step'))
    return normalized


def template():
    """Return an editable CSV with one clearly synthetic, non-carrier row."""
    sample = (
        'synthetic-example', '合成示例（非承运商报价，请替换）', 'both',
        '示例发货地', '示例目的地', 'CNY', '2026-01-01', '2026-12-31',
        'weight', '5000', '0.5', '1', '10', '2', '5', '0', '0', '30',
        '120', '300', '合成示例：已含基础运输费', '合成示例：未含税费及偏远附加费',
    )
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\r\n')
    writer.writerow(COLUMNS)
    writer.writerow(sample)
    return stream.getvalue()


def parse_csv(content):
    """Parse up to 200 complete tariffs, raising a row-addressable ValueError.

    All 22 columns are required. Zero fees and unlimited dimensions must be
    explicit zeroes. Numeric values allow up to 9 decimal places, no exponents;
    text cells are stripped, bounded, and otherwise preserved as inert data.
    """
    if not isinstance(content, str):
        raise _error(1, 'CSV', '必须为UTF-8文本')
    try:
        byte_length = len(content.encode('utf-8'))
    except UnicodeEncodeError as exc:
        raise _error(1, 'CSV', '必须为有效UTF-8文本') from exc
    if not content or byte_length > MAX_CSV_BYTES or '\x00' in content:
        raise _error(1, 'CSV', f'不能为空、包含NUL或超过{MAX_CSV_BYTES}字节')
    content = content.removeprefix('\ufeff')
    reader = csv.reader(io.StringIO(content, newline=''), strict=True)
    rates = []
    seen_ids = set()
    try:
        header = next(reader, [])
        if len(header) != len(set(header)):
            raise _error(1, 'columns', '表头重复')
        if len(header) != len(COLUMNS) or set(header) != set(COLUMNS):
            raise _error(1, 'columns', '表头存在缺失或未知字段')
        for cells in reader:
            line = reader.line_num
            if len(rates) >= MAX_RATES:
                raise _error(line, 'CSV', f'最多{MAX_RATES}条报价')
            if len(cells) != len(header):
                raise _error(line, 'columns', '字段数量错误或存在空行')
            normalized = _normalize_rate(dict(zip(header, cells)), line)
            if normalized['id'] in seen_ids:
                raise _error(line, 'id', '报价ID重复')
            seen_ids.add(normalized['id'])
            rates.append(normalized)
    except csv.Error as exc:
        raise _error(max(1, reader.line_num), 'CSV', 'CSV格式错误') from exc
    if not rates:
        raise _error(2, 'CSV', '至少需要1条完整报价')
    return rates


def _quote(boxes, rate, *, mode, origin, destination, ship_date, packaging_currency):
    normalized = _normalize_rate(rate, 1)
    if mode not in ('warehouse', 'buyer'):
        raise ValueError('发货模式必须为warehouse或buyer')
    if normalized['mode'] not in (mode, 'both'):
        raise ValueError('报价不适用于当前发货模式')
    if origin != normalized['origin'] or destination != normalized['destination']:
        raise ValueError('报价发货地或目的地与当前路线不一致')
    shipping_day = _date(ship_date, 'ship_date', 1)
    if not (_date(normalized['valid_from'], 'valid_from', 1) <= shipping_day
            <= _date(normalized['valid_until'], 'valid_until', 1)):
        raise ValueError('发货日期不在报价有效期内')
    if (not isinstance(packaging_currency, str)
            or not _CURRENCY.fullmatch(packaging_currency)
            or packaging_currency != normalized['currency']):
        raise ValueError('报价币种与包材币种不一致，未执行汇率换算')
    if not isinstance(boxes, (list, tuple)) or not 1 <= len(boxes) <= MAX_BOXES:
        raise ValueError(f'发货组必须包含1至{MAX_BOXES}个箱子')
    numbers = {key: Decimal(normalized[key]) for key in _NUMERIC_LIMITS}
    breakdown = []
    shipping = _ZERO
    packaging = _ZERO
    chargeable_total = _ZERO
    for index, box in enumerate(boxes, 1):
        if not isinstance(box, Mapping):
            raise ValueError(f'第{index}箱数据无效')
        dimensions = box.get('outer_cm')
        if not isinstance(dimensions, (list, tuple)) or len(dimensions) != 3:
            raise ValueError(f'第{index}箱必须提供三维外箱尺寸')
        dimensions = [_decimal(value, 'outer_cm', index, '1000000', positive=True)
                      for value in dimensions]
        values = {key: _decimal(box.get(key), key, index, maximum)
                  for key, maximum in (('gross_weight_kg', '1000000'),
                                       ('tare_kg', '1000000'),
                                       ('goods_weight_kg', '1000000'),
                                       ('packaging_cost', '1000000000000'))}
        gross = values['gross_weight_kg']
        if gross <= 0:
            raise ValueError(f'第{index}箱毛重必须大于0')
        if values['tare_kg'] > gross or values['goods_weight_kg'] > gross:
            raise ValueError(f'第{index}箱皮重或货重不得超过毛重')
        # Packing engines may round a measured gross weight independently.  Keep
        # its authoritative value, but reject totals differing by more than 1 g.
        if abs(values['tare_kg'] + values['goods_weight_kg'] - gross) > Decimal('.001'):
            raise ValueError(f'第{index}箱毛重与货重加皮重不一致（容差1克）')
        longest = max(dimensions)
        girth = longest + 2 * (sum(dimensions) - longest)
        for field, measured, label in (
            ('max_weight_kg', gross, '毛重'), ('max_length_cm', longest, '最长边'),
            ('max_girth_cm', girth, '围长'),
        ):
            if numbers[field] and measured > numbers[field]:
                raise ValueError(f'第{index}箱{label}超过报价限制')
        volume_cm3 = dimensions[0] * dimensions[1] * dimensions[2]
        volume_m3 = volume_cm3 / Decimal(1_000_000)
        volumetric = volume_cm3 / numbers['divisor'] if numbers['divisor'] else _ZERO
        quantity = max(gross, volumetric) if normalized['basis'] == 'weight' else volume_m3
        quantity = max(quantity, numbers['min_charge'])
        chargeable = ((quantity / numbers['round_step']).to_integral_value(rounding=ROUND_UP)
                      * numbers['round_step'])
        transport = chargeable * numbers['unit_price']
        subtotal = transport + numbers['base_fee']
        fuel = subtotal * numbers['fuel_pct'] / Decimal(100)
        box_shipping = _money(subtotal + fuel)
        box_packaging = _money(values['packaging_cost'])
        shipping += box_shipping
        packaging += box_packaging
        chargeable_total += chargeable
        breakdown.append({
            'box_index': index, 'gross_weight_kg': _plain(gross),
            'volumetric_weight_kg': _plain(volumetric), 'volume_m3': _plain(volume_m3),
            'chargeable': _plain(chargeable),
            'chargeable_unit': 'kg' if normalized['basis'] == 'weight' else 'm3',
            'transport_cost': _plain(transport), 'base_fee': _plain(numbers['base_fee']),
            'fuel_cost': _plain(fuel), 'shipping_cost': format(box_shipping, '.2f'),
            'packaging_cost': format(box_packaging, '.2f'),
        })
    shipment_fee = _money(numbers['shipment_fee'])
    other_fee = _money(numbers['other_fee'])
    shipping += shipment_fee + other_fee
    return {
        'status': 'QUOTED', 'rate_id': normalized['id'], 'rate_name': normalized['name'],
        'currency': normalized['currency'], 'basis': normalized['basis'],
        'shipping_cost': format(shipping, '.2f'),
        'packaging_cost': format(packaging, '.2f'),
        'total_cost': format(shipping + packaging, '.2f'),
        'chargeable_total': _plain(chargeable_total),
        'chargeable_unit': 'kg' if normalized['basis'] == 'weight' else 'm3',
        'shipment_fee': format(shipment_fee, '.2f'), 'other_fee': format(other_fee, '.2f'),
        'box_breakdown': breakdown, 'included_fees': normalized['included_fees'],
        'excluded_fees': normalized['excluded_fees'],
        'data_source': 'user_provided_rate_table', 'settlement_confirmed': False,
        'notice': '依据用户报价表估算；非承运商确认或实际结算，未含费用请另行核实。',
    }


def quote(boxes, rate, *, mode, origin, destination, ship_date, packaging_currency):
    """Quote one shipment; any invalid box or mismatch makes its total unavailable.

    Each box rounds max(actual, volumetric) weight, or m³ volume, up to the
    tariff step after applying the minimum. Fuel applies to that box's freight
    plus base fee. Round each box's freight incl. fuel and packaging half up to
    cents, then sum; round each once-per-shipment fixed fee separately. Detailed
    transport/base/fuel values retain precision before final per-box rounding.
    """
    try:
        with localcontext() as context:
            context.prec = 80
            return _quote(boxes, rate, mode=mode, origin=origin, destination=destination,
                          ship_date=ship_date, packaging_currency=packaging_currency)
    except (ValueError, InvalidOperation) as exc:
        return {'status': 'UNAVAILABLE', 'reason': str(exc),
                'data_source': 'user_provided_rate_table', 'settlement_confirmed': False}
