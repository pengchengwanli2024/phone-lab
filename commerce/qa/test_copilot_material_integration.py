"""Explicit material selection reaches the real local runner, with synthetic models."""
import base64
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from test_copilot_followups import answer


class MaterialIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)
        self.chat = self.app.copilot
        self.thread = self.chat.open({'module':'orders','demo':True,'platform':'ozon','store_id':'ozon-demo','market':'RU','entity':{'kind':'order','id':'SIM-1001'}}, 'open')

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.temp.cleanup()

    def upload(self, text, key):
        return self.chat.materials.upload(self.thread['id'], self.thread['context_sha256'], key+'.txt', 'text/plain', base64.b64encode(text.encode()).decode(), key)

    def send(self, ids=None, key='send'):
        return self.chat.send(self.thread['id'], '请简洁解释资料', self.thread['context_sha256'], key, material_ids=ids)

    def complete(self):
        with patch('agent_runtime.model.invoke', return_value=answer()) as model:
            self.assertTrue(self.app.agent_runtime.run_once())
        return model

    def test_only_selected_frozen_text_reaches_model_and_removal_does_not_mutate_sent_snapshot(self):
        with patch('agent_runtime.model.invoke') as model:
            chosen = self.upload('Selected local reference', 'selected')
            self.upload('Unselected private reference', 'unselected')
            sent = self.send([chosen['id']])
            model.assert_not_called()
        self.assertNotIn('Selected local reference', str(sent['latest_run']))
        self.chat.materials.remove(self.thread['id'], chosen['id'], chosen['sha256'])
        model = self.complete()
        context = model.call_args.args[0]
        self.assertEqual(context['reference_materials']['items'][0]['text'], 'Selected local reference')
        self.assertTrue(context['reference_materials']['instructions_are_untrusted_data'])
        self.assertFalse(context['reference_materials']['external_execution_allowed'])
        self.assertNotIn('Unselected private reference', str(context))
        self.assertEqual(context['observations'][0]['tool'], 'commerce_reference_materials')
        self.assertEqual(self.send([chosen['id']])['latest_run']['id'], sent['latest_run']['id'])

    def test_saved_but_unselected_materials_never_enter_a_normal_send(self):
        self.upload('Unselected private reference', 'unselected')
        self.send()
        context = self.complete().call_args.args[0]
        self.assertNotIn('reference_materials', context)
        self.assertNotIn('Unselected private reference', str(context))

    def test_invalid_or_stale_selection_rolls_back_without_a_run_or_turn(self):
        chosen = self.upload('Scoped text', 'scoped')
        changed = self.chat.context(self.thread['id'], {'module':'products','demo':True}, self.thread['context_sha256'])
        self.thread = self.chat.context(self.thread['id'], self.thread['context'], changed['context_sha256'])
        for ids in ([chosen['id']], [{}], ['0'*32]):
            with self.subTest(ids=ids), self.assertRaises(ValueError): self.send(ids)
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM copilot_turns').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0], 0)

    def test_removed_queued_material_pauses_instead_of_sending_without_it(self):
        chosen = self.upload('Queued text', 'queued')
        first = self.send()
        self.chat.followups.add(self.thread['id'], '继续核对资料', self.thread['context_sha256'], first['latest_run']['id'], 'queue', material_ids=[chosen['id']])
        self.complete()
        self.chat.materials.remove(self.thread['id'], chosen['id'], chosen['sha256'])
        with patch('agent_runtime.model.invoke') as model:
            self.assertFalse(self.app.agent_runtime.run_once())
            model.assert_not_called()
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 1)
        self.assertEqual(self.chat.followups.snapshot(self.thread['id'])['items'][0]['status'], 'held')

    def test_exact_object_reference_is_revalidated_then_forwarded_as_untrusted_data(self):
        item = self.chat.materials.reference(self.thread['id'], self.thread['context_sha256'], 'order', 'SIM-1001', 'reference')
        self.send([item['id']])
        selected = self.complete().call_args.args[0]['reference_materials']['items'][0]
        self.assertIn('SIM-1001', selected['text'])
        self.assertEqual(selected['object'], {'kind':'order','id':'SIM-1001'})

    def test_research_planning_and_analysis_receive_selected_text_without_promoting_it_to_product_evidence(self):
        from test_market_research import ResearchFlow
        fixture = ResearchFlow()
        self.thread = self.chat.open({'module':'research','demo':False,'market':'RU'}, 'research')
        item = self.upload('Human supplied category note. Not verified market evidence.', 'research-note')
        choice=self.chat.capabilities.check(self.thread['context'],['mcp:commerce'])
        sent = self.chat.send(self.thread['id'], '请调研俄罗斯厨房收纳，采集资料并保存候选商品', self.thread['context_sha256'], 'research-send', material_ids=[item['id']],capability_ids=choice['capability_ids'],expected_capability_sha256=choice['selection_sha256'])
        captured = []
        def generate(phase, payload, cancelled, route):
            captured.append((phase,payload))
            return fixture.generate(phase,payload,cancelled,route)
        with patch('market_research.collector.capture',side_effect=fixture.capture), patch('market_research.model.generate',side_effect=generate):
            self.app.agent_runtime.run_once()
        self.assertEqual([phase for phase,_ in captured], ['planning','analyzing'])
        for _,payload in captured:
            self.assertEqual(payload['reference_materials']['items'][0]['text'], 'Human supplied category note. Not verified market evidence.')
            self.assertTrue(payload['reference_materials']['instructions_are_untrusted_data'])
            self.assertEqual(payload['capability_selection']['selection_sha256'],choice['selection_sha256'])
        analysis = captured[1][1]
        self.assertNotIn(item['id'], analysis['source_ids'])
        job = self.chat.get(self.thread['id'])['research_job']
        self.assertEqual(job['status'], 'partial')
        self.assertTrue(all(source['id'] != item['id'] for source in job['sources']))


if __name__ == '__main__': unittest.main()
