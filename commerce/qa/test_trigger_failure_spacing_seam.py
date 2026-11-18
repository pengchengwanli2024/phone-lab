"""Seam test: consecutive trigger failures delay the next slot and stay visible.

Reuses the local trigger fixtures from test_assistant_team_triggers; no model is called.
"""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_assistant_team_triggers import (BASE, LocalTeams, Models, TeamTriggerTests, TeamTriggers)
from commerce_core import Core
from types import SimpleNamespace
import tempfile

PERIOD = 600


class SpacingSeam(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(TeamTriggers, 'local team triggers are not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.core = Core(Path(self.temp.name) / 'fixture.sqlite')
        service = SimpleNamespace(core=self.core, models=Models(),
                                  agent_runtime=SimpleNamespace(roles=lambda: [{'id': 'fixture', 'name': 'Fixture'}]))
        self.teams = LocalTeams(service)
        self.profile = self.teams.profile_save({'name': 'Fixture', 'role_id': 'fixture', 'instructions': '',
                                                'model_ids': ['project-default'], 'enabled': True})
        self.channel = self.teams.channel_save({'name': 'Room', 'instructions': '',
            'context': {'module': 'overview', 'demo': True}, 'member_ids': [self.profile['id']]})
        self.triggers = TeamTriggers(self.teams)
        self.clock = patch('assistant_team_triggers.time.time', return_value=BASE)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def interval(self):
        saved = self.triggers.save({'name': 'Every hour', 'kind': 'interval',
            'channel_id': self.channel['id'], 'channel_revision': self.channel['revision'],
            'question': 'Summarize the existing brief.', 'dispatch_mode': 'collaborate', 'max_rounds': 2,
            'schedule': {'start_at': datetime.fromtimestamp(int(BASE) - 5 * PERIOD, timezone.utc)
                         .strftime('%Y-%m-%dT%H:%M:%SZ'), 'interval_seconds': PERIOD}})
        return self.triggers.enable(saved['id'], saved['revision'], True)

    def add_event(self, doc, index, status, created, error=None):
        event = {'id': 'trigger_event_seed%d' % index, 'trigger_id': doc['id'], 'trigger_revision': doc['revision'],
                 'event_id': 'seed:%d' % index, 'kind': doc['kind'], 'created': created, 'status': status,
                 'discussion_id': None, 'error': error, 'payload_sha256': None}
        with self.core.db() as db:
            db.execute('INSERT INTO assistant_team_trigger_events VALUES(?,?,?,?,?,?)',
                       (event['id'], doc['id'], event['event_id'], 'seed%d' % index, json.dumps(event), created))
        return event

    def test_three_real_failures_delay_the_next_slot_and_record_why(self):
        doc = self.interval()
        for index in range(3):
            self.add_event(doc, index, 'failed', BASE + (index + 1) * PERIOD, 'team_trigger_not_ready')
        result = self.triggers.tick(BASE + 4 * PERIOD)
        self.assertEqual(len(result['events']), 1)
        event = result['events'][0]
        self.assertEqual((event['status'], event['error']), ('skipped', 'team_trigger_failure_spacing'))
        self.assertIsNone(event['discussion_id'])
        with self.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM assistant_team_discussions').fetchone()[0], 0)
        stored = self.triggers.get(doc['id'])
        self.assertTrue(stored['enabled'], 'a delayed trigger stays enabled for a human to fix it')
        self.assertEqual(stored['error'], 'team_trigger_failure_spacing')
        self.assertEqual(stored['history'][0]['status'], 'skipped')
        # The delay covers only this slot: once the window passes, work resumes normally.
        later = self.triggers.tick(BASE + 10 * PERIOD)
        self.assertEqual([(e['status'], e['error']) for e in later['events']], [('dispatched', None)])
        self.assertEqual(later['events'][0]['kind'], 'interval')

    def test_unknown_and_dispatched_runs_never_delay_the_schedule(self):
        doc = self.interval()
        self.add_event(doc, 0, 'failed', BASE + PERIOD)
        self.add_event(doc, 1, 'failed', BASE + 2 * PERIOD)
        self.add_event(doc, 2, 'unknown', BASE + 3 * PERIOD)
        result = self.triggers.tick(BASE + 4 * PERIOD)
        self.assertEqual(result['events'][0]['status'], 'dispatched')

    def test_a_success_resets_the_backoff(self):
        doc = self.interval()
        for index in range(3):
            self.add_event(doc, index, 'failed', BASE + (index + 1) * PERIOD)
        self.add_event(doc, 9, 'dispatched', BASE + 4 * PERIOD, None)
        result = self.triggers.tick(BASE + 5 * PERIOD)
        self.assertEqual(result['events'][0]['status'], 'dispatched')

    def discussion(self, ident, status):
        with self.core.db() as db:
            doc = {'id': ident, 'channel_id': 'other-channel', 'question': 'q', 'status': status, 'members': [], 'mode': 'all'}
            db.execute('INSERT INTO assistant_team_discussions VALUES(?,?,?,?,?)', (ident, ident, '{}', json.dumps(doc), BASE))

    def dispatched(self, doc, index, created, discussion_status):
        event = self.add_event(doc, index, 'dispatched', created)
        ident = 'discussion_seed%d' % index
        self.discussion(ident, discussion_status)
        event['discussion_id'] = ident
        with self.core.db() as db:
            db.execute('UPDATE assistant_team_trigger_events SET document=? WHERE id=?', (json.dumps(event), event['id']))

    def test_dispatched_work_that_later_failed_counts_toward_spacing(self):
        doc = self.interval()
        for index in range(3):
            self.dispatched(doc, index, BASE + (index + 1) * PERIOD, 'failed')
        event = self.triggers.tick(BASE + 4 * PERIOD)['events'][0]
        self.assertEqual((event['status'], event['error']), ('skipped', 'team_trigger_failure_spacing'))

    def test_unsettled_or_ambiguous_discussions_never_delay(self):
        for offset, status in enumerate(('unknown', 'running', 'partial', 'interrupted', 'awaiting_review')):
            with self.subTest(status=status):
                doc = self.interval()
                base = 10 * (offset + 1)
                self.dispatched(doc, base, BASE + PERIOD, 'failed')
                self.dispatched(doc, base + 1, BASE + 2 * PERIOD, 'failed')
                # Newest work is not settled: the failure run stops here.
                self.dispatched(doc, base + 2, BASE + 3 * PERIOD, status)
                with self.core.db() as db:
                    events = self.triggers._outcomes(db, doc['id'])
                self.assertEqual([e['status'] for e in events], ['not_settled'])
                event = self.triggers.tick(BASE + 4 * PERIOD)['events']
                self.assertNotIn('team_trigger_failure_spacing', [e['error'] for e in event])

    def test_completed_work_resets_even_after_earlier_failures(self):
        doc = self.interval()
        for index in range(3):
            self.dispatched(doc, index, BASE + (index + 1) * PERIOD, 'failed')
        self.dispatched(doc, 5, BASE + 4 * PERIOD, 'completed')
        event = self.triggers.tick(BASE + 5 * PERIOD)['events'][0]
        self.assertEqual(event['status'], 'dispatched')


if __name__ == '__main__':
    unittest.main()
