"""Candidate identity remains distinct from real shop inventory and business gates."""
import unittest

from organization_candidates import create_candidate
import test_organization as fixtures


class Candidates(unittest.TestCase):
    setUp = fixtures.OrganizationTests.setUp
    tearDown = fixtures.OrganizationTests.tearDown

    def create(self, **kwargs):
        return create_candidate(self.app.core.path, kwargs.pop('context', self.org.exchange.context(self.cid)),
                                key=kwargs.pop('key', 'synthetic-caddy'), name=kwargs.pop('name', '合成候选收纳架'),
                                source_ref=kwargs.pop('source_ref', 'synthetic:research-source'), **kwargs)

    def test_candidate_readback_deduplicates_and_never_invents_inventory(self):
        before = self.app.live.inventory_rows()
        result = self.create()
        self.assertEqual(result['case'], self.org.case(result['case']['id']))
        self.assertFalse(result['inventory_created'])
        self.assertIsNone(result['case']['scope']['product_id'])
        self.assertIsNone(result['case']['currency'])
        self.assertEqual(result['case']['scope']['origin'], 'research_candidate_not_inventory')
        self.assertEqual(self.create()['case']['id'], result['case']['id'])
        self.assertEqual(self.app.live.inventory_rows(), before)

    def test_updated_identity_conflicts_instead_of_overwriting(self):
        result = self.create(currency='RUB')
        for args in [{'name': 'different'}, {'source_ref': 'different'}, {'currency': 'CNY'}]:
            with self.assertRaisesRegex(ValueError, 'candidate_key_conflict'):
                self.create(**args)
        self.assertEqual(self.org.case(result['case']['id'])['currency'], 'RUB')

    def test_stale_anchor_rejected_before_insert(self):
        context = self.org.exchange.context(self.cid)
        self.org.set_currency(self.cid, 'RUB')
        with self.assertRaisesRegex(ValueError, 'exchange_scope_changed'):
            self.create(context=context)
        self.assertFalse(any(c['scope']['inventory_type'] == 'candidate' for c in self.org.cases()))

    def test_candidate_cannot_inherit_fresh_inventory_or_sales(self):
        self.app.live.configure({'orders_scope_confirmed': True, 'stock_basis': 'present_minus_reserved', 'basis_confirmed': True})
        result = self.create(currency='RUB')
        board = self.org.board(result['case']['id'])
        self.assertNotEqual(next(s for s in board['stages'] if s['id'] == 'S8')['status'], 'PASS')
        context = self.org.exchange.context(result['case']['id'])
        produced = self.org.exchange.produce(context, 'commerce_unit_economics', {'input': {'currency': 'RUB'}})
        self.assertEqual(produced['status'], 'HOLD')
        self.assertEqual(self.org.artifact(result['case']['id'], 'economics')['payload'], {'currency': 'RUB'})

    def test_wrong_connection_hides_candidate_without_rebinding(self):
        result = self.create()
        self.app.live.configure({'ozon_client_id': '654321'})
        with self.assertRaisesRegex(ValueError, 'organization_case_not_found'):
            self.org.case(result['case']['id'])

    def test_invalid_input_and_example_context_rejected(self):
        for args in [{'key': '../other'}, {'name': ''}, {'source_ref': ''}, {'currency': 'rub'}]:
            with self.assertRaises(ValueError):
                self.create(**args)
        context = self.org.exchange.context(self.cid)
        context['origin'] = 'example'
        with self.assertRaisesRegex(ValueError, 'invalid_exchange_context'):
            self.create(context=context)
