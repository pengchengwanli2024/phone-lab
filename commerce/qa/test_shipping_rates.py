"""Synthetic, hand-calculated shipping tariff contracts; no carrier quotes."""
import csv
import io
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import shipping_rates
except ModuleNotFoundError:
    shipping_rates = None


COLUMNS = (
    'id', 'name', 'mode', 'origin', 'destination', 'currency',
    'valid_from', 'valid_until', 'basis', 'divisor', 'round_step',
    'min_charge', 'unit_price', 'base_fee', 'shipment_fee', 'fuel_pct',
    'other_fee', 'max_weight_kg', 'max_length_cm', 'max_girth_cm',
    'included_fees', 'excluded_fees',
)
RATE = dict(zip(COLUMNS, (
    'synthetic-weight', '合成测试报价（非真实报价）', 'both', 'CN', 'RU', 'CNY',
    '2026-01-01', '2026-12-31', 'weight', '5000', '0.5', '1', '10', '2',
    '7', '10', '3', '30', '120', '300', '已含合成运输费', '未含税费及偏远费',
)))


def csv_content(*rows, columns=COLUMNS):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(key, '') for key in columns])
    return stream.getvalue()


def box(outer=(30, 20, 10), gross='1.1', packaging='2.35'):
    return dict(outer_cm=list(outer), tare_kg='0.1', goods_weight_kg=str(Decimal(gross) - Decimal('.1')),
                gross_weight_kg=gross, packaging_cost=packaging)


class ShippingRateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(shipping_rates, '报价解析及计费模块尚未实现')

    def rate(self, **changes):
        return shipping_rates.parse_csv(csv_content(dict(RATE, **changes)))[0]

    def quote(self, boxes=None, rate=None, **changes):
        options = dict(mode='warehouse', origin='CN', destination='RU',
                       ship_date='2026-06-01', packaging_currency='CNY')
        options.update(changes)
        return shipping_rates.quote(boxes if boxes is not None else [box()],
                                    rate if rate is not None else self.rate(), **options)

    def assert_unavailable(self, result):
        self.assertEqual(result['status'], 'UNAVAILABLE')
        self.assertTrue(result['reason'])
        for key in ('shipping_cost', 'packaging_cost', 'total_cost', 'chargeable_total'):
            self.assertNotIn(key, result)

    def test_template_is_editable_and_explicitly_synthetic(self):
        result = shipping_rates.template()
        rows = list(csv.DictReader(io.StringIO(result)))
        self.assertEqual(tuple(rows[0]), COLUMNS)
        self.assertEqual(len(rows), 1)
        self.assertIn('合成', rows[0]['name'])
        self.assertEqual(len(shipping_rates.parse_csv(result)), 1)

    def test_bom_and_exact_decimal_values_survive_import(self):
        row = dict(RATE, unit_price=' 000.123456 ', name='  合成测试  ')
        rate = shipping_rates.parse_csv('\ufeff' + csv_content(row))[0]
        self.assertEqual(rate['unit_price'], '0.123456')
        self.assertEqual(rate['name'], '合成测试')

    def test_weight_quotes_volume_weight_rounding_fuel_and_one_off_fees(self):
        result = self.quote([box(), box((10, 10, 10), '.55', '1.20')])
        # Box 1: ceil(1.2 / .5) * .5 = 1.5; (15+2)*1.1 = 18.70.
        # Box 2: min 1 kg; (10+2)*1.1 = 13.20; ticket 7+3 once.
        self.assertEqual(result['status'], 'QUOTED')
        self.assertEqual(result['shipping_cost'], '41.90')
        self.assertEqual(result['packaging_cost'], '3.55')
        self.assertEqual(result['total_cost'], '45.45')
        self.assertEqual(result['chargeable_total'], '2.5')
        self.assertEqual(result['box_breakdown'][0]['volumetric_weight_kg'], '1.2')
        self.assertEqual(result['box_breakdown'][0]['chargeable'], '1.5')
        self.assertEqual(result['box_breakdown'][0]['shipping_cost'], '18.70')
        self.assertEqual(result['included_fees'], RATE['included_fees'])
        self.assertEqual(result['excluded_fees'], RATE['excluded_fees'])
        self.assertEqual(result['data_source'], 'user_provided_rate_table')
        self.assertFalse(result['settlement_confirmed'])

    def test_zero_divisor_uses_actual_weight(self):
        result = self.quote([box((100, 50, 20), '1.1')], self.rate(divisor='0'))
        self.assertEqual(result['chargeable_total'], '1.5')
        self.assertEqual(result['box_breakdown'][0]['volumetric_weight_kg'], '0')

    def test_volume_basis_uses_cubic_metres_and_minimum_before_rounding(self):
        result = self.quote([box((50, 40, 30), '5', '2')], self.rate(
            basis='volume', round_step='.01', min_charge='.075', unit_price='100',
            base_fee='2', shipment_fee='7', other_fee='3', fuel_pct='10'))
        # .06 m3 -> .075 minimum -> .08 step; (8+2)*1.1+7+3 = 21.
        self.assertEqual(result['chargeable_total'], '0.08')
        self.assertEqual(result['shipping_cost'], '21.00')
        self.assertEqual(result['total_cost'], '23.00')

    def test_money_rounds_each_box_half_up_before_summing(self):
        rate = self.rate(divisor='0', round_step='1', min_charge='0', unit_price='.335',
                         base_fee='0', fuel_pct='0', shipment_fee='0', other_fee='0')
        result = self.quote([box((1, 1, 1), '1', '.005'), box((1, 1, 1), '1', '.005')], rate)
        self.assertEqual(result['shipping_cost'], '0.68')
        self.assertEqual(result['packaging_cost'], '0.02')
        self.assertEqual(result['total_cost'], '0.70')

    def test_fuel_is_applied_before_per_box_rounding(self):
        rate = self.rate(divisor='0', round_step='1', min_charge='0', unit_price='1.005',
                         base_fee='0', fuel_pct='10', shipment_fee='0', other_fee='0')
        self.assertEqual(self.quote([box((1, 1, 1), '1', '0')], rate)['shipping_cost'], '1.11')

    def test_validity_is_inclusive_and_rejects_other_dates(self):
        for date in ('2026-01-01', '2026-12-31'):
            with self.subTest(date=date):
                self.assertEqual(self.quote(ship_date=date)['status'], 'QUOTED')
        for date in ('2025-12-31', '2027-01-01', '2026-02-30', '20260601'):
            with self.subTest(date=date):
                self.assert_unavailable(self.quote(ship_date=date))

    def test_route_mode_and_currency_mismatches_have_no_partial_total(self):
        for options in (dict(origin='US'), dict(destination='US'), dict(mode='buyer'),
                        dict(mode='other'), dict(packaging_currency='USD'),
                        dict(packaging_currency='cny')):
            with self.subTest(options=options):
                self.assert_unavailable(self.quote(rate=self.rate(mode='warehouse'), **options))

    def test_each_box_weight_length_and_girth_are_checked(self):
        for boxes, changes in (
            ([box(gross='31')], {}),
            ([box((121, 10, 10))], {}),
            ([box((100, 60, 50))], {}),
            ([box(), box(gross='31')], {}),
        ):
            with self.subTest(boxes=boxes):
                self.assert_unavailable(self.quote(boxes=boxes, **changes))

    def test_zero_limits_are_explicitly_unlimited(self):
        result = self.quote([box((200, 200, 200), '100')], self.rate(
            max_weight_kg='0', max_length_cm='0', max_girth_cm='0'))
        self.assertEqual(result['status'], 'QUOTED')

    def test_missing_or_invalid_box_data_is_unavailable(self):
        for invalid in ([], [dict(box(), gross_weight_kg='NaN')],
                        [dict(box(), gross_weight_kg=True)],
                        [dict(box(), packaging_cost='')], [dict(box(), packaging_cost='-1')],
                        [dict(box(), outer_cm=[0, 10, 10])],
                        [dict(box(), outer_cm=[10, 10])],
                        [dict(box(), tare_kg='2')],
                        [dict(box(), goods_weight_kg='2')],
                        [dict(box(), gross_weight_kg='Infinity')]):
            with self.subTest(invalid=invalid):
                self.assert_unavailable(self.quote(boxes=invalid))
        missing = box()
        missing.pop('packaging_cost')
        self.assert_unavailable(self.quote(boxes=[missing]))

    def test_direct_invalid_rate_cannot_bypass_csv_validation(self):
        for updates in (dict(unit_price='NaN'), dict(fuel_pct='101'), dict(round_step='0'),
                        dict(excluded_fees=''), dict(currency='cny')):
            with self.subTest(updates=updates):
                self.assert_unavailable(self.quote(rate=dict(RATE, **updates)))

    def test_required_unknown_duplicate_and_extra_columns_are_rejected(self):
        cases = (
            csv_content(RATE, columns=COLUMNS[:-1]),
            csv_content(RATE, columns=COLUMNS + ('mystery',)),
            csv_content(RATE, columns=COLUMNS + ('id',)),
            csv_content(RATE).rstrip('\r\n') + ',extra\n',
            csv_content(RATE).replace(RATE['excluded_fees'], ''),
        )
        for content in cases:
            with self.subTest(content=content):
                with self.assertRaisesRegex(ValueError, '(行|shipping_)'):
                    shipping_rates.parse_csv(content)

    def test_duplicate_ids_and_row_limit_are_rejected(self):
        with self.assertRaisesRegex(ValueError, '3'):
            shipping_rates.parse_csv(csv_content(RATE, RATE))
        valid = [dict(RATE, id='synthetic-' + str(i)) for i in range(200)]
        self.assertEqual(len(shipping_rates.parse_csv(csv_content(*valid))), 200)
        with self.assertRaisesRegex(ValueError, '(200|202)'):
            shipping_rates.parse_csv(csv_content(*valid, dict(RATE, id='synthetic-last')))

    def test_csv_byte_and_numeric_bounds_are_enforced(self):
        with self.assertRaisesRegex(ValueError, '(字节|shipping_)'):
            shipping_rates.parse_csv('x' * 1_000_001)
        for field, value in (('unit_price', '1000000000001'), ('divisor', '1000000001'),
                             ('round_step', '1000001'), ('max_length_cm', '1000001'),
                             ('min_charge', '1000000001'), ('unit_price', '.0000000001')):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    shipping_rates.parse_csv(csv_content(dict(RATE, **{field: value})))

    def test_unsorted_dimensions_and_exact_limits_are_accepted(self):
        result = self.quote([box((20, 30, 10), '1.1')], self.rate(
            max_weight_kg='1.1', max_length_cm='30', max_girth_cm='90'))
        self.assertEqual(result['status'], 'QUOTED')
        self.assertEqual(result['shipping_cost'], '28.70')

    def test_empty_and_malformed_csv_is_rejected(self):
        for content in ('', ',,\n', csv_content(), csv_content(RATE) + '\n',
                        csv_content(RATE).replace('synthetic-weight', '"unclosed'),
                        '\x00' + csv_content(RATE)):
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    shipping_rates.parse_csv(content)

    def test_invalid_numeric_dates_modes_and_upper_bounds_are_rejected(self):
        invalid_fields = (
            ('unit_price', 'NaN'), ('unit_price', 'Infinity'), ('unit_price', '-1'),
            ('unit_price', '1e99999'), ('unit_price', '1e2'), ('unit_price', '+1'),
            ('fuel_pct', '100.01'), ('round_step', '0'), ('min_charge', '-1'),
            ('max_weight_kg', '-1'), ('divisor', ''), ('base_fee', 'unknown'),
            ('currency', 'cny'), ('currency', 'CNYY'), ('mode', 'air'),
            ('basis', 'parcel'), ('valid_from', '2026-02-30'),
            ('valid_from', '20260101'), ('valid_until', '2025-12-31'),
            ('id', ''), ('name', ''), ('included_fees', ''), ('excluded_fees', ''),
            ('name', 'x' * 5000),
        )
        for field, value in invalid_fields:
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, '(2|shipping_)'):
                    shipping_rates.parse_csv(csv_content(dict(RATE, **{field: value})))

    def test_formula_like_text_is_preserved_as_data_without_evaluation(self):
        rate = self.rate(id='=1+1', name='@SUM(1,2)', included_fees='+合成费用', excluded_fees='-未含税费')
        self.assertEqual(rate['id'], '=1+1')
        self.assertEqual(rate['name'], '@SUM(1,2)')
        result = self.quote(rate=rate)
        self.assertEqual(result['rate_id'], '=1+1')
        self.assertEqual(result['rate_name'], '@SUM(1,2)')


if __name__ == '__main__':
    unittest.main()
