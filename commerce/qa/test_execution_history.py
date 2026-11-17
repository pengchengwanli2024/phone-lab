"""Isolated real-SQLite coverage for the read-only execution directory."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce, schema
from execution_history import ExecutionHistory, tools


class ExecutionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)
        self.history = ExecutionHistory(self.app)

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.app.autonomy.stop()
        self.app.extensions.stop()
        self.temp.cleanup()

    def agent(self, ident, at=1800000000, status='completed', title='合成模型问题'):
        payload = {'role': {'id': 'conductor'}, 'question': title, 'topic': 'runtime',
                   'parameters': {'secret': 'synthetic-parameter-must-stay-private'},
                   'model_route': {'model': 'synthetic-model-must-stay-private'}}
        with self.app.core.db() as db:
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,NULL,NULL,?,?)',
                       (ident, ident, 'synthetic-request-must-stay-private', json.dumps(payload), status,
                        at, at, json.dumps({'answer': 'synthetic-result-must-stay-private'}), '[]'))

    def skill(self, ident, at=1800000000, status='succeeded', title='合成旧版能力'):
        definition = {'id': 'fixture_skill', 'name': title, 'kind': 'workflow'}
        doc = {'id': ident, 'extension_id': 'fixture_skill', 'version': 1, 'status': status,
               'created_at': at, 'input': {'token': 'synthetic-input-must-stay-private'},
               'pins': {'fixture_skill': {'version': 1, 'definition': definition}},
               'models': {'private': 'synthetic-model-must-stay-private'},
               'output': None, 'checkpoints': {}, 'usage': {'steps': 0}, 'budget': {'max_steps': 1}}
        with self.app.core.db() as db:
            db.execute('INSERT OR IGNORE INTO extension_versions VALUES(?,?,?,?,?,?)',
                       ('fixture_skill', 1, json.dumps(definition), '{}', 'untested', 1))
            db.execute('INSERT INTO extension_runs VALUES(?,?,?,?,?,?)',
                       (ident, ident, 'fixture_skill', status, json.dumps(doc), at))

    def team(self, ident, runs=(), at=1800000000, **changes):
        doc = {'id': ident, 'question': '合成团队问题', 'created': at,
               'members': [{'run_id': run, 'thread_id': 'synthetic-thread', 'profile_id': 'synthetic-profile'} for run in runs],
               'profile_snapshots': {'secret': 'synthetic-profile-must-stay-private'},
               'model_pins': {'secret': 'synthetic-model-must-stay-private'}, **changes}
        with self.app.core.db() as db:
            db.execute('INSERT INTO assistant_team_discussions VALUES(?,?,?,?,?)',
                       (ident, ident, 'synthetic-team-request-must-stay-private', json.dumps(doc), at))

    def snapshot(self):
        with self.app.core.db() as db:
            return {name: db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
                    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def all_pages(self, **filters):
        rows, cursor = [], None
        for _ in range(1000):
            page = self.history.listing(**filters, **({'cursor': cursor} if cursor else {}))
            rows.extend(page['items'])
            cursor = page['next_cursor']
            if cursor is None:
                return rows
        self.fail('unbounded pagination loop')

    def test_full_history_exceeds_old_caps_and_same_time_ids_never_repeat_or_disappear(self):
        for i in range(45):
            self.agent(f'row_{i:03}')
        for i in range(125):
            self.skill(f'row_{i:03}')
        for i in range(35):
            self.team(f'row_{i:03}', ['row_000'])
        rows = self.all_pages(limit=7)
        expected = [f'{origin}:row_{i:03}' for origin, count in [('agent', 45), ('assistant-team', 35), ('skills', 125)] for i in range(count)]
        self.assertEqual([r['key'] for r in rows], expected)
        self.assertEqual(len({r['key'] for r in rows}), 205)

    def test_snapshot_watermarks_keep_later_insertions_out_of_in_progress_pages(self):
        for i in range(8):
            self.agent(f'original_{i}', at=1800000000 - i)
        first = self.history.listing(limit=2)
        self.agent('newer', at=1900000000)
        self.agent('backdated', at=1700000000)
        rows, page = first['items'][:], first
        while page['next_cursor']:
            page = self.history.listing(limit=2, cursor=page['next_cursor'])
            rows.extend(page['items'])
        self.assertEqual([r['id'] for r in rows], [f'original_{i}' for i in range(8)])
        self.assertEqual(len(self.all_pages(limit=2)), 10)

    def test_original_states_source_and_literal_keyword_filters_are_server_side(self):
        self.agent('same-id', status='completed', title='合成目标百分号 %')
        self.skill('same-id', status='succeeded', title='合成目标旧版')
        self.team('same-id', ['same-id'])
        self.assertEqual([r['origin'] for r in self.all_pages(status='completed')], ['agent', 'assistant-team'])
        self.assertEqual([r['origin'] for r in self.all_pages(status='succeeded')], ['skills'])
        self.assertEqual([r['origin'] for r in self.all_pages(query='旧版', origin='skills')], ['skills'])
        self.assertEqual([r['origin'] for r in self.all_pages(query='%')], ['agent'])
        self.assertEqual(len(self.all_pages(query='same-id')), 3)
        self.assertEqual(self.all_pages(query="' OR 1=1 --"), [])
        self.assertEqual(self.all_pages(status='future_historical_state'), [])

    def test_search_covers_the_full_safe_question_beyond_the_list_title_preview(self):
        self.agent('long-question', title='合成' * 160 + '末尾关键词')
        rows = self.history.listing(query='末尾关键词')['items']
        self.assertEqual([r['id'] for r in rows], ['long-question'])
        self.assertEqual(len(rows[0]['title']), 240)

    def test_plugin_names_use_the_original_private_header_redaction_contract(self):
        secret = 'SYNTHETIC-OPAQUE-PRIVATE-VALUE'
        self.skill('plugin', title='合成插件 ' + secret)
        with self.app.core.db() as db:
            raw = json.loads(db.execute("SELECT document FROM extension_runs WHERE id='plugin'").fetchone()[0])
            raw['pins']['fixture_skill']['definition']['kind'] = 'plugin'
            db.execute("UPDATE extension_runs SET document=? WHERE id='plugin'", (json.dumps(raw),))
        with patch.object(self.app.extensions, '_secret_headers', return_value={'X-Api-Key': secret}) as headers:
            value = self.history.listing()
            filtered = self.history.listing(query=secret)
        self.assertEqual(headers.call_args.args, ('fixture_skill', 1))
        self.assertNotIn(secret, json.dumps(value))
        self.assertEqual(filtered['items'], [])

    def test_cursor_is_bound_to_filters_page_size_anchor_and_format(self):
        self.agent('a'); self.agent('b')
        cursor = self.history.listing(limit=1)['next_cursor']
        for filters in ({'query': 'changed'}, {'origin': 'skills'}, {'status': 'unknown'}, {'limit': 2}):
            with self.subTest(filters=filters), self.assertRaisesRegex(ValueError, 'execution_history_invalid_cursor'):
                self.history.listing(**{'limit': 1, 'cursor': cursor, **filters})
        for bad in ('', 'garbage', cursor[:-1] + ('0' if cursor[-1] != '0' else '1'), 1, {}, 'eh1.!!.aaa'):
            with self.subTest(cursor=bad), self.assertRaisesRegex(ValueError, 'execution_history_invalid_cursor'):
                self.history.listing(limit=1, cursor=bad)
        with self.app.core.db() as db:
            db.execute("UPDATE agent_runs SET created=created+1 WHERE id='a'")
        with self.assertRaisesRegex(ValueError, 'execution_history_invalid_cursor'):
            self.history.listing(limit=1, cursor=cursor)

    def test_cursor_signature_rejects_reencoded_filter_tampering_and_other_instances(self):
        self.agent('a'); self.agent('b')
        cursor = self.history.listing(limit=1)['next_cursor']
        prefix, encoded, signature = cursor.split('.')
        raw = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        raw['filters']['query'] = 'changed'
        serialized = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        reencoded = base64.urlsafe_b64encode(serialized).decode().rstrip('=')
        for checksum in (signature, hashlib.sha256(serialized).hexdigest()):
            with self.assertRaisesRegex(ValueError, 'execution_history_invalid_cursor'):
                self.history.listing(limit=1, query='changed', cursor=prefix + '.' + reencoded + '.' + checksum)
        with self.assertRaisesRegex(ValueError, 'execution_history_invalid_cursor'):
            ExecutionHistory(self.app).listing(limit=1, cursor=cursor)

    def test_missing_times_titles_and_states_stay_missing_at_the_end_of_history(self):
        self.agent('known', at=1)
        self.agent('missing', at=None, status=None, title=None)
        self.agent('invalid', at='not-a-date', title=None)
        self.agent('iso', at='2023-11-14T22:13:20Z')
        rows = self.all_pages(limit=1)
        self.assertEqual([r['id'] for r in rows], ['iso', 'known', 'invalid', 'missing'])
        self.assertEqual(rows[-2]['at'], None)
        self.assertEqual((rows[-1]['at'], rows[-1]['title'], rows[-1]['status']), (None, None, None))

    def test_empty_result_is_distinct_from_unavailable_source_and_invalid_query(self):
        empty = self.history.listing(query='不存在')
        self.assertEqual(empty['items'], [])
        self.assertIsNone(empty['next_cursor'])
        self.assertTrue(empty['read_only'])
        for args in ({'limit': True}, {'limit': 101}, {'limit': 0}, {'query': '\n'}, {'status': '等待补充'}, {'origin': 'invented'}, {'query': 1}, {'status': 1}):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'execution_history_invalid_query'):
                self.history.listing(**args)
        with self.app.core.db() as db:
            db.execute('DROP TABLE extension_runs')
        with self.assertRaisesRegex(ValueError, 'execution_history_source_unavailable'):
            self.history.listing()

    def test_minimal_metadata_redacts_titles_and_does_not_use_getters_or_write(self):
        secret = 'sk-' + 'SYNTHETICSECRET' * 3
        self.agent('private-agent', title='合成问题 token=synthetic-token ' + secret)
        self.skill('private-skill', title='合成能力 Bearer synthetic-bearer-secret')
        self.team('private-team', ['private-agent'], question='合成团队 /Users/synthetic/private/path')
        before = self.snapshot()
        with patch.object(self.app.agent_runtime, 'get', side_effect=AssertionError('getter')), \
                patch.object(self.app.agent_runtime, '_get', side_effect=AssertionError('getter')), \
                patch.object(self.app.extensions, 'run_get', side_effect=AssertionError('getter')), \
                patch.object(self.app.assistant_team, 'discussion_get', side_effect=AssertionError('getter')), \
                patch('agent_runtime.model.invoke', side_effect=AssertionError('model')):
            value = self.history.listing()
        self.assertEqual(self.snapshot(), before)
        raw = json.dumps(value)
        for sensitive in (secret, 'synthetic-token', 'synthetic-bearer-secret', '/Users/synthetic', 'must-stay-private', 'payload', 'request', 'model_pins'):
            self.assertNotIn(sensitive, raw)
        for row in value['items']:
            self.assertEqual(set(row), {'key', 'id', 'origin', 'title', 'status', 'at', 'version'})
        self.assertEqual(self.history.listing(query='synthetic-token')['items'], [])

    def test_team_status_matches_original_detail_precedence_without_advancing(self):
        for ident, state in [('completed', 'completed'), ('queued', 'queued'), ('running', 'running'), ('unknown', 'unknown'), ('input', 'awaiting_input')]:
            self.agent(ident, status=state)
        cases = [(['queued'], {}), (['completed', 'queued'], {}), (['unknown'], {}), (['input'], {}),
                 (['input', 'completed'], {}), (['completed'], {'mode': 'collaborate', 'collaboration_state': 'running'}),
                 (['completed'], {'mode': 'collaborate', 'plan': [{}, {}]}),
                 (['input'], {'mode': 'collaborate', 'collaboration_state': 'completed'}),
                 (['queued'], {'collaboration_state': 'cancelled'}),
                 (['unknown'], {'collaboration_state': 'cancelled'}),
                 (['completed'], {'collaboration_state': 'failed'}), ([], {})]
        for i, (members, fields) in enumerate(cases):
            self.team(f'discussion_{i:02}', members, **fields)
        original = {f'discussion_{i:02}': self.app.assistant_team.discussion_get(f'discussion_{i:02}')['status'] for i in range(len(cases))}
        rows = self.all_pages(origin='assistant-team', limit=3)
        self.assertEqual({r['id']: r['status'] for r in rows}, original)
        self.team('missing_member', ['absent'])
        self.assertIsNone(self.history.listing(query='missing_member')['items'][0]['status'])

    def test_team_research_and_continuation_states_follow_exact_stored_references(self):
        self.agent('original', status='unknown'); self.agent('continuation', status='completed')
        self.team('research', ['original'])
        self.team('continued', ['original'], members=[{'run_id': 'original', 'continuation_run_id': 'continuation'}])
        with self.app.core.db() as db:
            db.execute('INSERT INTO market_research_runs VALUES(?,?)', ('original', 'research-task'))
            db.execute('INSERT INTO market_research_jobs VALUES(?,?)', ('research-task', json.dumps({'status': 'awaiting_input'})))
        states = {r['id']: r['status'] for r in self.all_pages(origin='assistant-team')}
        self.assertEqual(states, {'research': 'awaiting_input', 'continued': 'completed'})

    def test_old_list_apis_are_unchanged_after_new_reads(self):
        self.agent('legacy'); self.skill('legacy'); self.team('legacy', ['legacy'])
        def legacy():
            return [self.app.invoke(name, {}, 'test') for name in ('commerce_agent_list', 'commerce_extension_run_list', 'commerce_assistant_team_catalog')]
        before = legacy()
        self.all_pages(limit=1)
        self.assertEqual(legacy(), before)
        self.assertEqual([n for n, _, _ in tools(schema)], ['commerce_execution_history'])
        self.assertEqual(self.history.invoke('commerce_execution_history', {'query': 'legacy'})['items'][0]['id'], 'legacy')
        with self.assertRaisesRegex(ValueError, 'unknown_tool'):
            self.history.invoke('commerce_agent_list', {})
        with self.assertRaisesRegex(ValueError, 'invalid_query'):
            self.history.invoke('commerce_execution_history', {'payload': 'no'})

    def test_corrupt_historical_documents_preserve_reference_and_missing_metadata(self):
        self.agent('malformed')
        with self.app.core.db() as db:
            db.execute("UPDATE agent_runs SET payload='{' WHERE id='malformed'")
        row = self.history.listing()['items'][0]
        self.assertEqual(row['id'], 'malformed')
        self.assertIsNone(row['title'])
        self.assertEqual(row['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
