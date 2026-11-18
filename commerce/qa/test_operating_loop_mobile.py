"""Loop proposals decided from an authenticated phone card; synthetic SDK events, no network."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from test_agent_cases import inspect, answer
from mobile_control import FeishuSDKAdapter
from operating_loop_mobile import LoopMobileDecisions

POLICY = {'app_id': 'synthetic-app', 'tenant_key': 'synthetic-tenant', 'owner_allowlist': ['synthetic-owner'], 'revision': 1}


class LoopMobileTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests();self.fixture.setUp();self.app = self.fixture.app
        self.addCleanup(self.fixture.tearDown);self.addCleanup(self.app.autonomy.stop);self.addCleanup(self.app.agent_runtime.stop)
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'));guard.start();self.addCleanup(guard.stop)
        self.loop = self.app.operating_loop;self.cards = self.app.operating_loop_mobile;self.cid = self.fixture.cid
        self.policy = copy.deepcopy(POLICY);self.seq = 0
        self.adapter = FeishuSDKAdapter(self.app.mobile_control, lambda: self.policy, app_id=POLICY['app_id'])
        self.owner = [POLICY['app_id'], POLICY['tenant_key'], 'synthetic-owner']
        target = {'case_id': self.cid, 'platform': 'ozon', 'store_ref': 'ozon-live', 'market': 'RU'}
        grant = self.loop.grant_save(target=target, goal='launch', stages=['research', 'sourcing'], level='prepare', max_runs_per_day=6, expected_revision=0)
        self.grant = self.loop.grant_enable(grant['id'], grant['revision'], True)
        self.loop.advance(self.grant['id'])
        with patch('agent_runtime.model.invoke', side_effect=[inspect(self.cid, 'S1'), answer()]): self.app.agent_runtime.run_once()
        self.loop.advance(self.grant['id'])
        self.work = self.loop.get(self.grant['id'])['work'][0]
        self.assertEqual(self.work['status'], 'awaiting_decision')

    def card(self, **extra):
        return self.cards.prepare(self.work['id'], 'P1', self.owner, self.policy, **extra)

    def click(self, packet, index=0, operator='synthetic-owner'):
        self.seq += 1
        nonce = packet['card']['elements'][-1]['actions'][index]['value']['nonce']
        return {'schema': '2.0', 'header': {'app_id': POLICY['app_id'], 'tenant_key': POLICY['tenant_key'], 'event_id': 'loop-event-' + str(self.seq),
                'event_type': 'card.action.trigger', 'create_time': str(int(time.time() * 1000000))},
                'event': {'operator': {'tenant_key': POLICY['tenant_key'], 'open_id': operator}, 'action': {'value': {'nonce': nonce}, 'tag': 'button'}}}

    def tasks(self):
        with self.app.core.db() as db: return db.execute('SELECT count(*) FROM tasks').fetchone()[0]

    def status(self):
        return self.loop.get(self.grant['id'])['work'][0]['status']

    def test_card_names_the_exact_object_and_carries_only_random_nonces(self):
        packet = self.card();text = packet['card']['elements'][0]['text']['content']
        for expected in ('市场研究与选品', '市场调研', '补齐当前岗位产物', '0 CNY', self.work['result_sha256'][:16]): self.assertIn(expected, text)
        self.assertEqual((packet['delivery_status'], packet['amount'], packet['external_operations_executed']), ('not_sent', 0, False))
        values = [a['value'] for a in packet['card']['elements'][-1]['actions']]
        self.assertTrue(all(set(v) == {'nonce'} and len(v['nonce']) == 43 for v in values));self.assertNotEqual(values[0], values[1])
        with self.app.core.db() as db: stored = ' '.join(r[0] for r in db.execute('SELECT token_sha256 FROM loop_mobile_nonces'))
        self.assertFalse(any(v['nonce'] in stored for v in values))
        self.assertEqual(self.tasks(), 0);self.assertEqual(self.status(), 'awaiting_decision')

    def test_approval_from_the_phone_resumes_the_original_handoff_exactly_once(self):
        packet = self.card();event = self.click(packet)
        receipt = self.adapter.handle_sdk_event(event)
        self.assertEqual((receipt['status'], receipt['work_status'], receipt['external_operations_executed']), ('approved', 'completed', False))
        task = self.app.core.invoke('commerce_task_get', {'task_id': receipt['handoff_task_id']})
        self.assertEqual((task['input']['organization_case'], task['input']['organization_stage']), (self.cid, 'S1'))
        self.assertEqual(self.adapter.handle_sdk_event(event), receipt)
        with ThreadPoolExecutor(max_workers=4) as pool:
            again = list(pool.map(lambda _: self.adapter.handle_sdk_event(self.click(packet)), range(4)))
        self.assertEqual({r['status'] for r in again}, {'approved'});self.assertEqual(self.tasks(), 1)
        self.assertEqual(self.adapter.handle_sdk_event(self.click(packet, 1))['status'], 'approved')

    def test_rejection_creates_no_task_and_closes_the_item(self):
        receipt = self.adapter.handle_sdk_event(self.click(self.card(), 1))
        self.assertEqual((receipt['status'], receipt['handoff_task_id'], self.status(), self.tasks()), ('rejected', None, 'rejected', 0))

    def test_wrong_person_expired_card_and_revoked_identity_decide_nothing(self):
        packet = self.card()
        with self.assertRaisesRegex(ValueError, 'mobile_sdk_identity_or_event_invalid'):
            self.adapter.handle_sdk_event(self.click(packet, operator='someone-else'))
        self.policy['owner_allowlist'].append('second-owner')
        with self.assertRaisesRegex(ValueError, 'mobile_owner_mismatch'):
            self.adapter.handle_sdk_event(self.click(packet, operator='second-owner'))
        self.policy = copy.deepcopy(POLICY);self.policy['revision'] = 2
        blocked = self.adapter.handle_sdk_event(self.click(packet))
        self.assertEqual((blocked['status'], blocked['reason']), ('blocked', 'identity_policy_changed'))
        self.policy = copy.deepcopy(POLICY)
        short = self.cards.prepare(self.work['id'], 'P1', self.owner, self.policy, ttl_seconds=1)
        with self.app.core.db() as db: db.execute('UPDATE loop_mobile_decisions SET expires=1 WHERE id=?', (short['decision_id'],))
        expired = self.adapter.handle_sdk_event(self.click(short))
        self.assertEqual((expired['status'], expired['reason']), ('blocked', 'decision_expired'))
        self.assertEqual((self.tasks(), self.status()), (0, 'awaiting_decision'))

    def test_evidence_changed_after_the_card_was_built_blocks_approval(self):
        packet = self.card();self.fixture.org.set_currency(self.cid, 'CNY')
        receipt = self.adapter.handle_sdk_event(self.click(packet))
        self.assertEqual((receipt['status'], receipt['reason']), ('blocked', 'agent_case_evidence_changed'))
        self.assertEqual((self.tasks(), self.status()), (0, 'awaiting_decision'))

    def test_item_already_decided_at_the_desk_is_reported_not_overridden(self):
        packet = self.card();self.loop.decide(self.work['id'], 'reject', self.work['result_sha256'])
        receipt = self.adapter.handle_sdk_event(self.click(packet))
        self.assertEqual((receipt['status'], receipt['reason']), ('blocked', 'operating_loop_already_decided'))
        self.assertEqual((self.tasks(), self.status()), (0, 'rejected'))

    def test_only_one_live_card_per_item_and_only_for_items_awaiting_decision(self):
        self.card()
        with self.assertRaisesRegex(ValueError, 'loop_mobile_decision_already_exists'): self.card()
        with self.assertRaisesRegex(ValueError, 'loop_mobile_proposal_not_found'): self.cards.prepare(self.work['id'], 'P9', self.owner, self.policy)
        with self.assertRaisesRegex(ValueError, 'invalid_mobile_expiry'): self.card(ttl_seconds=901)
        with self.assertRaisesRegex(ValueError, 'loop_mobile_not_awaiting_decision'): self.cards.prepare('loopwork_missing', 'P1', self.owner, self.policy)

    def test_unknown_nonce_is_still_rejected_and_original_local_cards_still_work(self):
        forged = {'card': {'elements': [{}, {'actions': [{'value': {'nonce': 'A' * 43}}]}]}}
        with self.assertRaisesRegex(ValueError, 'mobile_nonce_invalid'): self.adapter.handle_sdk_event(self.click(forged))
        self.assertEqual(self.tasks(), 0)

    def test_crash_between_claim_and_loop_decision_reads_unknown_and_never_retries(self):
        packet = self.card()
        with patch.object(self.loop, 'decide', side_effect=RuntimeError('synthetic crash')):
            with self.assertRaises(RuntimeError): self.adapter.handle_sdk_event(self.click(packet))
        with patch.object(self.loop, 'decide') as decide:
            receipt = self.adapter.handle_sdk_event(self.click(packet));decide.assert_not_called()
        self.assertEqual((receipt['status'], receipt['reason']), ('unknown', 'loop_decision_receipt_missing_no_automatic_retry'))
        self.assertEqual(self.tasks(), 0)

    def test_cards_are_not_reachable_as_tools(self):
        import service
        names = {n for n, _, _ in service.TOOLS}
        self.assertFalse(any('loop_mobile' in n for n in names))
        with self.assertRaisesRegex(ValueError, 'unknown_tool'): self.loop.invoke('commerce_operating_loop_mobile_prepare', {})


if __name__ == '__main__':
    unittest.main()
