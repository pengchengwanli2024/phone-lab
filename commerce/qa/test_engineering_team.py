"""Engineering receipts use real SQLite/files/sandbox; inference is synthetic here."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core


class Models:
    def snapshot(self, db, model_id=None):
        return {'provider': 'codex', 'model': 'synthetic', 'profile_id': model_id or 'project-default'}

    def runtime_route(self, snapshot):
        return snapshot

    def public_snapshot(self, snapshot):
        return snapshot


class EngineeringTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('engineering'), 'engineering runtime missing')
        from engineering import EngineeringTeam
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source = base / 'source'
        self.source.mkdir()
        (self.source / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
        (self.source / 'test_calc.py').write_text('import unittest\nfrom calc import add\nclass Addition(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n')
        (self.source / 'AGENTS.md').write_text('Preserve existing behavior. Run actual tests.\n')
        self.service = type('Service', (), {})()
        self.service.state = base / 'state'
        self.service.state.mkdir()
        self.service.core = Core(self.service.state / 'commerce.sqlite')
        self.service.models = Models()
        self.team = EngineeringTeam(self.service, project_root=self.source)
        self.addCleanup(self.team.stop)
        self.team.configure(True)

    def create(self, key='one', **extra):
        return self.team.create(goal='Fix addition while preserving its signature.',
            files=['calc.py', 'test_calc.py'], writable_paths=['calc.py'],
            checks=[{'kind': 'python_unittest', 'paths': ['test_calc.py']}],
            idempotency_key=key, **extra)

    def reply(self, stage, payload, route, cancelled):
        if stage == 'plan':
            return {'summary': 'Fix the arithmetic operator.', 'acceptance': ['2+3 equals 5']}
        if stage == 'build':
            return {'summary': 'Corrected addition.', 'edits': [{'path': 'calc.py', 'content': 'def add(a, b):\n    return a + b\n'}]}
        return {'decision': 'approve', 'reason': 'Small correction; original acceptance passes.'}

    def execute(self, run):
        with patch.object(self.team, '_model', side_effect=self.reply):
            self.assertTrue(self.team.run_once())
        return self.team.get(run['id'])

    def test_complete_patch_is_reviewable_and_never_changes_source(self):
        result = self.execute(self.create())
        self.assertEqual(result['status'], 'awaiting_review')
        self.assertEqual(result['verification']['baseline'][0]['status'], 'failed')
        self.assertEqual(result['verification']['candidate'][0]['status'], 'passed')
        self.assertTrue(result['source_current'])
        self.assertIn('return a - b', (self.source / 'calc.py').read_text())
        artifact = self.team.artifact(result['id'])
        self.assertIn('+    return a + b', artifact['patch'])
        self.assertEqual(result['candidate_sha256'], artifact['candidate_sha256'])
        task = self.service.core.invoke('commerce_task_get', {'task_id': result['task_id']})
        self.assertEqual(task['input']['engineering_run_id'], result['id'])
        self.assertEqual(task['status'], 'blocked')

    def test_idempotency_rejects_changed_goal_and_no_duplicate_tasks(self):
        first = self.create()
        self.assertEqual(self.create()['id'], first['id'])
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.team.create('Different goal', ['calc.py', 'test_calc.py'], ['calc.py'],
                [{'kind': 'python_unittest', 'paths': ['test_calc.py']}], 'one')

    def test_hidden_paths_traversal_symlinks_and_credential_files_rejected(self):
        (self.source / 'link.py').symlink_to(self.source / 'calc.py')
        for path in ['../calc.py', '/tmp/x.py', '.local/x.py', 'credentials.json', 'link.py']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.team.create('check', [path], [path],
                    [{'kind': 'python_compile', 'paths': [path]}], 'bad-' + path)

    def test_model_cannot_edit_acceptance_or_ungranted_files(self):
        for target in ['test_calc.py', 'escape.py', '../escape.py']:
            with self.subTest(target=target):
                run = self.create('bad-edit-' + target)
                def bad(stage, payload, route, cancelled):
                    value = self.reply(stage, payload, route, cancelled)
                    if stage == 'build': value['edits'][0]['path'] = target
                    return value
                with patch.object(self.team, '_model', side_effect=bad): self.team.run_once()
                self.assertEqual(self.team.get(run['id'])['status'], 'failed')
                self.assertIn('outside_write_scope', self.team.get(run['id'])['error'])

    def test_source_drift_blocks_work_and_invalidates_artifact(self):
        run = self.create()
        (self.source / 'calc.py').write_text('def add(a,b):\n    return a+b+1\n')
        with patch.object(self.team, '_model') as model:
            self.team.run_once()
            model.assert_not_called()
        self.assertEqual(self.team.get(run['id'])['error'], 'engineering_source_changed')

    def test_reviewer_and_checks_bind_to_same_candidate(self):
        seen = []
        def reply(stage, payload, route, cancelled):
            if stage == 'review': seen.append(payload)
            return self.reply(stage, payload, route, cancelled)
        run = self.create()
        with patch.object(self.team, '_model', side_effect=reply): self.team.run_once()
        result = self.team.get(run['id'])
        self.assertEqual(seen[0]['candidate_sha256'], result['candidate_sha256'])
        self.assertEqual(result['review']['candidate_sha256'], result['candidate_sha256'])

    def test_budget_reserved_before_model_and_never_reset_on_resume(self):
        run = self.create(max_model_calls=1)
        result = self.execute(run)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'engineering_model_budget_exhausted')
        self.assertEqual(result['usage']['model_calls'], 1)

    def test_global_pause_and_task_cancel_prevent_dispatch(self):
        run = self.create()
        self.team.configure(False)
        with patch.object(self.team, '_model') as model:
            self.assertFalse(self.team.run_once())
            model.assert_not_called()
        self.team.configure(True)
        self.team.cancel(run['id'])
        self.assertFalse(self.team.run_once())
        self.assertEqual(self.team.get(run['id'])['status'], 'cancelled')

    def test_original_core_task_cancel_cannot_be_resurrected(self):
        run = self.create()
        self.service.core.invoke('commerce_task_cancel', {'task_id': run['task_id']})
        with patch.object(self.team, '_model') as model:
            self.team.run_once();model.assert_not_called()
        self.assertEqual(self.team.get(run['id'])['status'], 'cancelled')
        self.assertEqual(self.service.core.invoke('commerce_task_get', {'task_id': run['task_id']})['status'], 'cancelled')

    def test_zero_exit_before_test_execution_is_not_a_pass(self):
        run = self.create(max_attempts=1)
        def early_exit(stage, *args):
            value = self.reply(stage, *args)
            if stage == 'build': value['edits'][0]['content'] = 'import os\nos._exit(0)\ndef add(a,b):\n    return 99\n'
            return value
        with patch.object(self.team, '_model', side_effect=early_exit): self.team.run_once()
        result = self.team.get(run['id'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['verification']['candidate'][0]['status'], 'failed')

    def test_unknown_model_attempt_is_not_replayed_after_restart(self):
        run = self.create()
        with self.service.core.db() as db:
            raw = json.loads(db.execute('SELECT document FROM engineering_runs WHERE id=?', (run['id'],)).fetchone()[0])
            raw.update(status='running', inflight={'kind': 'model', 'stage': 'plan'})
            db.execute('UPDATE engineering_runs SET status=?,document=? WHERE id=?', ('running', json.dumps(raw), run['id']))
        self.team.recover()
        self.assertEqual(self.team.get(run['id'])['status'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'cannot_resume'): self.team.resume(run['id'])
        with patch.object(self.team, '_model') as model:
            self.assertFalse(self.team.run_once())
            model.assert_not_called()

    def test_unconfirmed_checker_blocks_resume_and_next_task_even_if_watcher_died(self):
        import os
        run = self.create()
        directory = self.team.state / run['id'];directory.mkdir()
        receipt = directory / 'check.json'
        receipt.write_text(json.dumps({'state': 'running', 'watchdog_pid': 999999999, 'checker_pid': os.getpid()}))
        with self.service.core.db() as db:
            doc = self.team._load(db, run['id'])
            doc.update(status='running', inflight={'kind': 'verification', 'watchdog_pid': 999999999,
                'verification_receipt': str(receipt.relative_to(self.team.state))})
            self.team._save(db, doc)
        self.team.recover()
        self.assertEqual(self.team.get(run['id'])['status'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'cannot_resume'): self.team.resume(run['id'])
        self.create('next-task')
        with patch.object(self.team, '_model') as model:
            self.assertFalse(self.team.run_once());model.assert_not_called()
        with self.service.core.db() as db:
            doc = self.team._load(db, run['id']);doc['status'] = 'cancelled';self.team._save(db, doc)
        with patch.object(self.team, '_model') as model:
            self.assertFalse(self.team.run_once());model.assert_not_called()

    def test_memory_requires_confirmation_and_stales_with_source(self):
        result = self.execute(self.create())
        candidate = self.team.memory_propose('Addition regression must retain both operands.', result['id'], 'lesson-one')
        self.assertEqual(self.team.memory_search('Addition')['items'], [])
        confirmed = self.team.memory_decide(candidate['id'], candidate['sha256'], 'confirm', True)
        self.assertEqual(len(self.team.memory_search('Addition')['items']), 1)
        (self.source / 'calc.py').write_text('def add(a,b):\n    return a+b\n')
        self.assertEqual(self.team.memory_search('Addition')['items'], [])
        self.assertEqual(self.team.memory_get(confirmed['id'])['effective_status'], 'stale')

    def test_memory_and_episodes_survive_a_new_runtime_instance(self):
        result = self.execute(self.create())
        from engineering import EngineeringTeam
        other = EngineeringTeam(self.service, project_root=self.source)
        self.addCleanup(other.stop)
        self.assertEqual(other.get(result['id'])['candidate_sha256'], result['candidate_sha256'])
        self.assertEqual(other.recall()['episodes'][0]['run_id'], result['id'])

    def test_retrospect_does_not_invoke_model_or_auto_create_work(self):
        with patch.object(self.team, '_model') as model:
            report = self.team.retrospect()
            model.assert_not_called()
        self.assertFalse(report['automatically_applied'])
        self.assertEqual(report['new_tasks_created'], 0)

    def test_adoption_requires_actual_candidate_hashes_and_does_not_write_source(self):
        run = self.execute(self.create())
        with self.assertRaisesRegex(ValueError, 'candidate_not_applied'):
            self.team.record_adoption(run['id'], run['candidate_sha256'], True)
        (self.source / 'calc.py').write_text('def add(a, b):\n    return a + b\n')
        accepted = self.team.record_adoption(run['id'], run['candidate_sha256'], True)
        self.assertEqual(accepted['status'], 'completed')
        self.assertTrue(accepted['patch_adopted'])
        note = self.team.memory_propose('Use the actual accepted source as experience evidence.', run['id'], 'adopted-lesson')
        self.assertEqual(note['effective_status'], 'proposed')

    def test_daily_model_allowance_is_persistent_and_reserved_before_call(self):
        run = self.create()
        with self.service.core.db() as db:
            db.execute('INSERT INTO engineering_daily_usage VALUES(?,30)', (self.team._day(),))
        with patch.object(self.team, '_model') as model:
            self.team.run_once();model.assert_not_called()
        self.assertEqual(self.team.get(run['id'])['error'], 'engineering_daily_model_budget_exhausted')

    def test_unsupported_model_route_is_rejected_before_task_creation(self):
        with patch.object(self.service.models, 'snapshot', return_value={'provider': 'host_auto'}):
            with self.assertRaisesRegex(ValueError, 'model_route_unsupported'): self.create()

    def test_safe_verification_resume_reuses_confirmed_model_outputs(self):
        from engineering import workspace
        original = workspace.checks
        count = 0
        stages = []
        def interrupted(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2: raise KeyboardInterrupt()
            return original(*args, **kwargs)
        def model(stage, *args):
            stages.append(stage)
            return self.reply(stage, *args)
        run = self.create()
        with patch.object(self.team, '_model', side_effect=model), patch.object(workspace, 'checks', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): self.team.run_once()
        self.team.recover()
        self.assertEqual(self.team.get(run['id'])['status'], 'interrupted')
        self.team.resume(run['id'])
        with patch.object(self.team, '_model', side_effect=model): self.team.run_once()
        self.assertEqual(stages, ['plan', 'build', 'review'])
        self.assertEqual(self.team.get(run['id'])['usage']['model_calls'], 3)
        self.assertEqual(self.team.get(run['id'])['status'], 'awaiting_review')

    def test_recovery_does_not_steal_a_live_owner(self):
        from engineering import EngineeringTeam
        other = EngineeringTeam(self.service, project_root=self.source)
        self.addCleanup(other.stop)
        run = self.create()
        def model(stage, *args):
            if stage == 'plan':
                self.assertEqual(other.recover()['recovered'], 0)
                self.assertEqual(other.get(run['id'])['status'], 'running')
                self.assertFalse(other.run_once())
            return self.reply(stage, *args)
        with patch.object(self.team, '_model', side_effect=model): self.team.run_once()
        self.assertEqual(self.team.get(run['id'])['status'], 'awaiting_review')


class ServiceIntegration(unittest.TestCase):
    def test_authenticated_tool_entry_and_passive_lifecycle_use_original_service(self):
        from service import Commerce, TOOLS
        with tempfile.TemporaryDirectory() as state:
            app = Commerce(state)
            try:
                self.assertIn('commerce_engineering_create', {t[0] for t in TOOLS})
                result = app.invoke('commerce_engineering_status', {}, 'test')
                self.assertFalse(result['enabled'])
                self.assertEqual(app.invoke('commerce_engineering_recall', {}, 'test')['episodes'], [])
                app.capability_lifecycle.tick()
                self.assertFalse(app.engineering.status()['worker_running'])
            finally:
                app.agent_runtime.stop();app.autonomy.stop()

    def test_original_task_result_and_controls_dispatch_to_engineering_owner(self):
        from service import Commerce
        from engineering import EngineeringTeam
        with tempfile.TemporaryDirectory() as state:
            app = Commerce(Path(state) / 'state')
            source = Path(state) / 'source';source.mkdir()
            (source / 'x.py').write_text('value=1\n')
            app.engineering.stop();app.engineering = EngineeringTeam(app, project_root=source)
            app.models = Models()
            try:
                run = app.engineering.create('check', ['x.py'], ['x.py'], [{'kind': 'python_compile', 'paths': ['x.py']}], 'task-owner', kind='feature')
                result = app.invoke('commerce_task_result', {'task_id': run['task_id']}, 'test')
                self.assertEqual(result['engineering_run_id'], run['id'])
                self.assertEqual(result['execution']['operation'], 'engineering')
                with self.assertRaisesRegex(ValueError, 'engineering_task_use'):
                    app.invoke('commerce_task_execute', {'task_id': run['task_id'], 'operation': 'report'}, 'test')
                app.invoke('commerce_task_cancel', {'task_id': run['task_id']}, 'test')
                self.assertEqual(app.engineering.get(run['id'])['status'], 'cancelled')
            finally:
                app.agent_runtime.stop();app.autonomy.stop()

    def test_mcp_annotations_distinguish_reads_and_model_dispatch(self):
        import contextlib
        import io
        import mcp_server
        messages = b'{"id":1,"method":"initialize","params":{}}\n{"id":2,"method":"tools/list"}\n'
        fake_input = type('Input', (), {'buffer': io.BytesIO(messages)})()
        out = io.StringIO()
        with patch.object(mcp_server, 'ensure'), patch.object(sys, 'stdin', fake_input), patch.object(sys, 'argv', ['mcp', 'test']), contextlib.redirect_stdout(out):
            mcp_server.main()
        rows = json.loads(out.getvalue().splitlines()[1])['result']['tools']
        tools = {r['name']: r for r in rows}
        self.assertTrue(tools['commerce_engineering_status']['annotations']['readOnlyHint'])
        self.assertFalse(tools['commerce_engineering_create']['annotations']['readOnlyHint'])
        self.assertTrue(tools['commerce_engineering_create']['annotations']['openWorldHint'])


class SandboxTests(unittest.TestCase):
    def test_cancel_after_ready_records_that_no_checker_was_started(self):
        from engineering.workspace import execute
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder).resolve() / 'work';work.mkdir()
            cancelled = False;receipts = []
            def started(pid, receipt):
                nonlocal cancelled
                receipts.append(receipt);cancelled = True
            with self.assertRaisesRegex(ValueError, 'engineering_cancelled'):
                execute('from pathlib import Path;Path("should-not-run").write_text("bad")', work,
                    cancelled=lambda: cancelled, on_start=started)
            self.assertFalse((work / 'should-not-run').exists())
            result = json.loads(receipts[0].read_text())
            self.assertEqual(result['state'], 'finished')
            self.assertTrue(result['not_started'])

    def test_killed_host_does_not_leave_an_orphan_checker(self):
        import os
        import signal
        import subprocess
        import time
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve();work = root / 'work';work.mkdir()
            code = ('import os,time\nfrom pathlib import Path\nPath("checker.pid").write_text(str(os.getpid()))\n'
                    'while True:\n Path("heartbeat").write_text(str(time.time_ns()))\n time.sleep(.03)\n')
            script = ('import sys\nfrom pathlib import Path\nsys.path.insert(0,' + repr(str(Path(__file__).resolve().parents[1])) + ')\n'
                      'from engineering.workspace import execute\nexecute(' + repr(code) + ',Path(' + repr(str(work)) + '),timeout=8)\n')
            host = subprocess.Popen([sys.executable, '-I', '-c', script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            checker = None
            try:
                end = time.monotonic() + 4
                while not (work / 'heartbeat').exists() and host.poll() is None and time.monotonic() < end: time.sleep(.03)
                self.assertTrue((work / 'heartbeat').exists(), 'checker did not start')
                checker = int((work / 'checker.pid').read_text())
                host.kill();host.wait(timeout=2)
                end = time.monotonic() + 2
                while time.monotonic() < end:
                    try: os.kill(checker, 0)
                    except ProcessLookupError: break
                    time.sleep(.03)
                else: self.fail('checker survived loss of its owning host')
            finally:
                if host.poll() is None: host.kill();host.wait(timeout=2)
                if checker:
                    try: os.killpg(checker, signal.SIGKILL)
                    except ProcessLookupError: pass

    def test_empty_new_file_cannot_silently_disappear_from_patch(self):
        from engineering.workspace import materialize
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'empty_new_file'):
                materialize(Path(folder) / 'candidate', {'x.py': 'value=1\n', 'pkg/__init__.py': None},
                    [{'path': 'x.py', 'content': 'value=2\n'}, {'path': 'pkg/__init__.py', 'content': ''}], ['x.py', 'pkg/__init__.py'])

    def test_unterminated_source_lines_still_produce_an_applicable_patch(self):
        import subprocess
        from engineering.workspace import materialize
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);original = root / 'original';original.mkdir()
            (original / 'x.py').write_text('value = 1')
            _, patch_text = materialize(root / 'candidate', {'x.py': 'value = 1'},
                [{'path': 'x.py', 'content': 'value = 2'}], ['x.py'])
            diff = root / 'change.diff';diff.write_text(patch_text)
            result = subprocess.run(['/usr/bin/patch', '--dry-run', '-p1', '-i', str(diff)], cwd=original, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual((root / 'candidate' / 'x.py').read_text(), 'value = 2')

    def test_real_sandbox_denies_outside_reads_writes_network_and_shell(self):
        self.assertIsNotNone(importlib.util.find_spec('engineering'), 'engineering runtime missing')
        from engineering.workspace import sandbox_probe
        result = sandbox_probe()
        if sys.platform != 'darwin':
            self.assertFalse(result['available'])
        else:
            self.assertTrue(result['available'], result)
            self.assertEqual(result['denied'], ['outside_read', 'outside_write', 'network', 'shell', 'signal', 'fork'])


if __name__ == '__main__':
    unittest.main()
