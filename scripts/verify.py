#!/usr/bin/env python3
"""Repeatable offline Commerce gates, run only in a disposable source copy."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.local/agent-team/builder'
IGNORED = {'node_modules', '__pycache__', '.git', 'venv', '.venv', 'dist', 'build', 'coverage'}
EXTENSIONS = {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.css', '.html', '.json', '.txt', '.md', '.yaml', '.yml'}
FAST_MODULES = ['test_a2ui_cost', 'test_product_workspace', 'test_listing_workspace', 'test_full_flow']
FULL_MODULES = FAST_MODULES + ['test_product_evidence', 'test_sourcing_channels', 'test_sourcing_integrity',
                               'test_ui_workflow_acceptance', 'test_service', 'test_copilot_transport',
                               'test_operating_pipeline', 'test_operating_video_policy', 'test_operating_budget', 'test_order_fulfillment',
                               'test_mobile_control', 'test_mobile_control_integration', 'test_operating_control', 'test_operating_loop', 'test_task_dispatch', 'test_operating_health', 'test_operating_loop_mobile', 'test_operating_retrospect', 'test_backup_restore', 'test_agent_text_fence', 'test_trigger_failure_spacing', 'test_trigger_failure_spacing_seam', 'test_trigger_firing', 'test_team_prompt_safety_integration', 'test_decision_checks', 'test_decision_checks_mcp', 'test_ozon_read_backoff', 'test_attempt_outcome', 'test_ozon_accounts', 'test_live_connections',
                               'test_catalog_store_identity','test_media_library','test_intel_opportunities','test_local_model_supervisor','test_catalog_media_integration','test_ozon_search_terms','test_workspace_content_citations','test_market_research_contract','test_catalog_evidence_media',
                               'test_workspace_research', 'test_workspace_research_stdio', 'test_listing_lineage',
                               # The extension runtime executes scheduled read-only work; its failure path is
                               # shared by every schedule, so its suites are part of the full profile.
                               'test_extension_failure', 'test_extension_runtime', 'test_extension_runtime_agents', 'test_extension_runtime_cancellation',
                               'test_extension_runtime_deadlines', 'test_extension_runtime_media', 'test_extension_runtime_network',
                               'test_extension_runtime_output_contract', 'test_extension_runtime_schedules']
GATES = ['python-dependencies', 'node-dependencies', 'browser-dependencies', 'verifier-tests',
         'static', 'generated-sync', 'types', 'frontend-unit', 'python-unit', 'browser-interaction']
NOT_COVERED = ['Native Harness/Codex/Hermes desktop interaction and host versions',
               'Physical devices, real stores, provider models, payments, messages and publishing',
               'Python suites outside the explicit profile allowlist; whole-product acceptance',
               'Open-source release sanitization and public Git history/attachments']


def required_gate_ids(profile):
    if profile not in ('fast', 'full'):
        raise ValueError('unknown verification profile')
    return list(GATES) + (['operating-control-browser', 'operating-loop-browser', 'catalog-library-browser', 'product-research-browser'] if profile == 'full' else [])


def source_paths(root):
    # Never traverse a private state directory, dependencies or symlinked trees.
    for base in ('commerce', 'crawlers', 'scripts/verification', 'scripts/tests'):
        directory = root / base
        if directory.is_symlink():
            raise ValueError('source symlink is not allowed: ' + base)
        for folder, dirs, files in os.walk(directory, followlinks=False):
            for name in dirs[:]:
                child = Path(folder) / name
                if name.startswith('.') or name in IGNORED:
                    dirs.remove(name)
                elif child.is_symlink():
                    raise ValueError('source directory symlink is not allowed')
            for name in sorted(files):
                p = Path(folder) / name
                if name.startswith('.') or p.suffix not in EXTENSIONS:
                    continue
                rel = p.relative_to(root)
                # These are generated host connections, not portable source.
                # Keep any actual integration code visible to verification.
                if rel.as_posix() in {'commerce/integrations/mcp.json', 'commerce/integrations/hermes.json', 'commerce/integrations/codex.toml'}:
                    continue
                # The multi-session coordination log is appended to while checks run and is
                # read by no code or test; counting it voided otherwise clean receipts.
                if rel.as_posix() == 'commerce/WORK_COORDINATION.md':
                    continue
                # QA JSON/PNG/logs are previous run evidence, never inputs.
                if 'qa' in rel.parts and p.suffix not in {'.py', '.mjs', '.js', '.cjs'}:
                    continue
                if p.is_symlink():
                    raise ValueError('source symlink is not allowed: ' + str(rel))
                yield rel
    for name in ('Makefile', 'scripts/verify.py', 'docs/VERIFYING.md'):
        p = root / name
        if p.is_symlink():
            raise ValueError('source symlink is not allowed: ' + name)
        if p.is_file():
            yield Path(name)


def source_hashes(root):
    return {str(p): hashlib.sha256((root / p).read_bytes()).hexdigest() for p in sorted(source_paths(root))}


def copy_sources(root, destination):
    manifest = {}
    for rel in sorted(source_paths(root)):
        data = (root / rel).read_bytes()
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[str(rel)] = hashlib.sha256(data).hexdigest()
    return manifest


def changed_files(before, after):
    return sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))


def validate_browser_report(report, expected):
    try:
        good = (report.get('completed') is True and report.get('sourceStable') is True
                and report.get('errors') == [] and report.get('external') == [] and report.get('checks')
                and report.get('requirements') and all(row.get('passed') is True for row in report['requirements'])
                and report['startHashes']['commerce/web/workbench.sources.json'] == expected)
    except (KeyError, TypeError):
        good = False
    if not good:
        raise ValueError('incomplete, failed or wrong-candidate browser interaction receipt')


def node_test_summary(output):
    summary = {name: int(value) for name, value in re.findall(r'^(?:#|ℹ) (tests|pass|fail|cancelled|skipped|todo) (\d+)\s*$', output, re.M)}
    if (not summary.get('tests') or summary.get('pass') != summary['tests']
            or any(summary.get(name) != 0 for name in ('fail', 'cancelled', 'skipped', 'todo'))):
        raise ValueError('missing Node test summary, empty suite or non-passing test')
    return summary


def validate_control_report(report, expected):
    required = {'scope_and_budget', 'original_task_write_and_readback', 'refresh_preserves_original_task',
                'viewport_1440_light', 'viewport_390_dark', 'synthetic_does_not_leak_into_live',
                'ozon_account_save_and_switch', 'ozon_accounts_credentials_hidden', 'multi_platform_bind_and_readback'}
    checks = report.get('checks', [])
    if (report.get('completed') is not True or report.get('sourceStable') is not True
            or report.get('errors') != [] or report.get('external') != [] or report.get('fatal')
            or report.get('sourceSha256') != expected or not isinstance(checks, list)
            or any(not isinstance(row, dict) or row.get('passed') is not True for row in checks)
            or not required.issubset({row.get('name') for row in checks})):
        raise ValueError('incomplete or wrong-candidate operating control browser receipt')


def validate_loop_report(report, expected):
    required = {'saved_grant_is_disabled_and_idle', 'stage_owner_proposal_waits_for_decision',
                'approval_resumes_original_handoff_once', 'unchanged_evidence_stays_idle', 'disable_keeps_history',
                'viewport_1440_light', 'viewport_390_dark', 'synthetic_does_not_leak_into_live',
                'run_health_reads_real_checks_and_backup_setting_persists'}
    checks = report.get('checks', [])
    if (report.get('completed') is not True or report.get('sourceStable') is not True
            or report.get('errors') != [] or report.get('external') != [] or report.get('fatal')
            or report.get('sourceSha256') != expected or not isinstance(checks, list)
            or any(not isinstance(row, dict) or row.get('passed') is not True for row in checks)
            or not required.issubset({row.get('name') for row in checks})):
        raise ValueError('incomplete or wrong-candidate operating loop browser receipt')


def validate_catalog_report(report, expected_sources):
    keys = ('commerce/web/workbench.bundle.js', 'commerce/web/product-workspace.bundle.js',
            'commerce/web/catalog-ui.js', 'commerce/web/catalog-presentation.js',
            'commerce/web/media-library-ui.js')
    if (report.get('status') != 'passed' or report.get('phase') != 'browser'
            or report.get('ui_verified') is not True or report.get('synthetic_fixture') is not True
            or report.get('errors') != [] or report.get('external') != []
            or report.get('unexpectedWrites') != [] or report.get('error')
            or not isinstance(report.get('checks'), list) or len(report['checks']) < 4
            or report.get('startHashes') != report.get('endHashes')
            or set(report.get('startHashes', {})) != set(keys)
            or any(report['startHashes'][key] != expected_sources.get(key) for key in keys)):
        raise ValueError('incomplete or wrong-candidate catalog/library browser receipt')


def validate_research_report(report, expected_sources):
    keys = {'commerce/web/workbench.sources.json', 'commerce/web/workbench.bundle.js',
            'commerce/web/workbench.html', 'commerce/web/product-workspace.bundle.js',
            'commerce/web/product-research-editor.js'}
    required = {'same_page_edit_save_readback', 'refresh_preserves_saved_revision',
                'changed_source_head_rejects_and_preserves_input', 'sparse_hold_record_opens',
                'issue_link_focus_visible', 'inflight_mode_switch_keeps_original_editor',
                'unknown_mode_switch_and_same_request_recovery', 'ordinary_dirty_can_be_discarded'}
    if not isinstance(report, dict):
        raise ValueError('invalid research form browser receipt')
    checks, start, end = report.get('checks'), report.get('startHashes'), report.get('endHashes')
    good = (report.get('schema') == 'product-research-browser-v1' and report.get('status') == 'passed'
            and report.get('completed') is True and report.get('syntheticFixture') is True
            and report.get('sourceStable') is True and not report.get('fatal')
            and report.get('errors') == [] and report.get('external') == []
            and isinstance(checks, list) and bool(checks)
            and all(isinstance(row, dict) and isinstance(row.get('name'), str)
                    and bool(row['name']) and row.get('passed') is True for row in checks)
            and required.issubset({row['name'] for row in checks})
            and isinstance(start, dict) and isinstance(end, dict)
            and set(start) == keys and set(end) == keys and start == end
            and all(isinstance(start[key], str) and re.fullmatch(r'[a-f0-9]{64}', start[key])
                    and start[key] == expected_sources.get(key) for key in keys))
    if not good:
        raise ValueError('incomplete, failed or wrong-candidate research form browser receipt')


def stop_group(process):
    # Only this gate's new process group; no pkill, shared services or ports.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_command(name, command, cwd, env, log_path, timeout):
    started = time.monotonic()
    result = {'id': name, 'command': [str(x) for x in command], 'cwd': str(cwd),
              'log': str(log_path), 'timeout_seconds': timeout}
    process = None
    with log_path.open('w', encoding='utf-8') as log:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            result['exit_code'] = process.wait(timeout=timeout)
            result['status'] = 'passed' if result['exit_code'] == 0 else 'failed'
        except subprocess.TimeoutExpired:
            result.update(status='timed_out', exit_code=124)
            log.write('\nVerifier timeout; terminating only the owned process group.\n')
        except OSError as error:
            result.update(status='blocked', exit_code=127)
            log.write(type(error).__name__ + ': executable or working directory unavailable\n')
        finally:
            if process is not None:
                stop_group(process)
                process.wait()
    result['duration_seconds'] = round(time.monotonic() - started, 3)
    return result


def python_path(explicit):
    if explicit:
        candidate = Path(explicit).expanduser().absolute()
        return str(candidate)
    for candidate in (ROOT / '.local/crawlers/venv/bin/python', ROOT / '.local/commerce-runtime/venv/bin/python',
                      ROOT / '.venv/bin/python', ROOT / 'venv/bin/python'):
        if candidate.is_file():
            return str(candidate)  # Resolving the symlink would lose venv identity.
    return sys.executable


def playwright_path(explicit):
    if explicit:
        p = Path(explicit).expanduser()
        return p.absolute().as_uri() if p.exists() else explicit
    candidates = [ROOT / 'commerce/workbench/node_modules/playwright/index.mjs']
    candidates += sorted((Path.home() / '.npm/_npx').glob('*/node_modules/playwright/index.mjs'))
    # An interrupted npx download can leave playwright without its core package.
    return next((p.as_uri() for p in candidates
                 if p.is_file() and (p.parent.parent / 'playwright-core' / 'package.json').is_file()), '')


def chrome_path(explicit):
    if explicit:
        return str(Path(explicit).expanduser().absolute())
    candidates = [Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')]
    candidates += [Path(p) for name in ('chromium', 'chromium-browser', 'google-chrome') if (p := shutil.which(name))]
    return next((str(p) for p in candidates if p.is_file()), '')


def isolated_environment(work, snapshot, python, node, playwright, chrome):
    home = work / 'home'; home.mkdir()
    temp = work / 'tmp'; temp.mkdir()
    bin_dir = work / 'bin'; bin_dir.mkdir()
    for name in ('python', 'python3'):
        wrapper = bin_dir / name
        wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(python) + ' "$@"\n')
        wrapper.chmod(0o700)
    # No inherited tokens, provider URLs, proxies, QA flags, state or NODE_OPTIONS.
    env = {'PATH': os.pathsep.join([str(bin_dir), str(Path(node).parent), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin']),
           'HOME': str(home), 'TMPDIR': str(temp) + os.sep, 'LANG': 'en_US.UTF-8', 'TZ': 'UTC',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
           'PYTHONPATH': os.pathsep.join(str(snapshot / p) for p in ('scripts/verification', 'commerce', 'commerce/qa')),
           'COMMERCE_STATE': str(work / 'state'), 'COMMERCE_PYTHON': python,
           'VERIFY_PORTS_FILE': str(work / 'ports.jsonl'), 'VERIFY_DENIALS_FILE': str(work / 'network-denials.jsonl'),
           'NODE_OPTIONS': '--require=' + str(snapshot / 'scripts/verification/network_guard.cjs'),
           'npm_config_cache': str(work / 'npm-cache'), 'npm_config_audit': 'false', 'npm_config_fund': 'false',
           'npm_config_update_notifier': 'false', 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1',
           'PLAYWRIGHT_MODULE': playwright, 'CHROME_PATH': chrome}
    return env


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def static_check(root):
    count = 0
    for rel in source_paths(root):
        if rel.suffix == '.py':
            compile((root / rel).read_bytes(), str(rel), 'exec')
            count += 1
    node = shutil.which('node')
    if not node:
        raise RuntimeError('node executable required')
    js = [str(p) for p in source_paths(root) if p.suffix in {'.js', '.mjs', '.cjs'}]
    for rel in js:
        subprocess.run([node, '--check', rel], cwd=root, check=True)
    print(json.dumps({'python_compiled': count, 'javascript_parsed': len(js), 'scope': 'Commerce, crawler imports and verifier sources'}))


def report_markdown(receipt):
    lines = ['# Builder verification', '', 'Task state: awaiting_review. Verification: ' + receipt['verification_status'] + '.',
             '', 'Profile: ' + receipt['profile'] + '; exit code: ' + str(receipt['exit_code']) +
             '; duration: ' + str(receipt['duration_seconds']) + 's.', '',
             'Receipt: `' + receipt['receipt_path'] + '`. Logs and failure evidence remain in this run directory.', '',
             '| Gate | Status | Exit | Seconds |', '| --- | --- | --- | --- |']
    for step in receipt['commands']:
        lines.append('| {id} | {status} | {exit_code} | {duration_seconds} |'.format(**step))
    for step in receipt['commands']:
        if step['status'] != 'passed':
            lines += ['', '- ' + step['id'] + ': ' + step.get('reason', 'See retained log `' + step.get('log', '') + '`.')]
    if receipt.get('source_drift'):
        lines += ['', 'Source drift (invalidates the run): ' + ', '.join('`'+p+'`' for p in receipt['source_drift'])]
    if receipt.get('error'):
        lines += ['', 'Orchestrator: ' + receipt['error']]
    if receipt.get('python_tests'):
        p = receipt['python_tests']
        lines += ['', 'Python: ' + str(p['tests_run']) + ' executed, ' + str(len(p['failures'])) + ' failures, ' + str(len(p['errors'])) + ' errors, ' + str(p['skipped_count']) + ' skipped.']
    if receipt.get('browser_summary'):
        lines += ['', 'Browser: ' + json.dumps(receipt['browser_summary'], ensure_ascii=False)]
    lines += ['', 'Coverage: Python modules `' + ', '.join(receipt['python_modules']) +
              '`, existing npm unit suite/typecheck, generated sync, static syntax, and required synthetic HTTP/browser interaction.',
              '', 'Source files changed during run: ' + str(len(receipt.get('source_drift', []))) + '.', '', 'Not covered:', '']
    lines += ['- ' + value for value in NOT_COVERED]
    lines += ['', 'No real store state/configuration is copied. Only this run’s scratch tree and owned child process groups are cleaned.',
              'A failed gate, missing dependency, skipped Python test, missing interaction receipt or source drift prevents success.',
              'No main-controller acceptance is implied by this execution report.', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('full', 'fast'), default='full')
    parser.add_argument('--python', default=os.environ.get('COMMERCE_PYTHON'))
    parser.add_argument('--static', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.static:
        static_check(ROOT)
        return 0
    OUTPUT.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:10]
    run_dir = OUTPUT / 'runs' / run_id; run_dir.mkdir(parents=True, mode=0o700)
    started = time.monotonic()
    receipt = {'schema_version': 1, 'run_id': run_id, 'status': 'working', 'profile': args.profile,
               'started_at': datetime.now(timezone.utc).isoformat(), 'commands': [],
               'python_modules': FAST_MODULES if args.profile == 'fast' else FULL_MODULES,
               'required_gates': required_gate_ids(args.profile), 'not_covered': NOT_COVERED,
               'receipt_path': str((run_dir / 'receipt.json').relative_to(ROOT)),
               'isolation': {'source_copy': True, 'inherited_credentials': False, 'network': 'registered fixture loopback only; browser blocks external routes',
                             'shared_service_restart': False, 'real_store_state': False},
               'verification_status': 'running', 'exit_code': 1}
    write_json(run_dir / 'receipt.json', receipt)
    write_json(OUTPUT / 'latest.json', receipt)
    work = Path(tempfile.mkdtemp(prefix='scratch-', dir=run_dir))
    snapshot = work / 'source'
    try:
        receipt['source_hashes'] = copy_sources(ROOT, snapshot)
        receipt['source_fingerprint_sha256'] = hashlib.sha256(json.dumps(receipt['source_hashes'], sort_keys=True).encode()).hexdigest()
        python = python_path(args.python)
        node = shutil.which('node') or 'node'
        npm = shutil.which('npm') or 'npm'
        playwright = playwright_path(os.environ.get('PLAYWRIGHT_MODULE'))
        chrome = chrome_path(os.environ.get('CHROME_PATH'))
        env = isolated_environment(work, snapshot, python, node, playwright, chrome)
        for folder in ('commerce/workbench', 'commerce/workbench/map'):
            dependency = ROOT / folder / 'node_modules'
            if dependency.is_dir():
                (snapshot / folder / 'node_modules').symlink_to(dependency, target_is_directory=True)
        evidence = run_dir / 'evidence'; evidence.mkdir()
        env['QA_OUTPUT_DIR'] = str(evidence)
        dependencies = snapshot / 'scripts/verification/dependencies.py'
        node_dependencies = snapshot / 'scripts/verification/dependencies.mjs'
        commands = [
            ('python-dependencies', [python, str(dependencies)], '.', 30, []),
            ('node-dependencies', [node, str(node_dependencies), 'packages'], '.', 30, []),
            ('browser-dependencies', [node, str(node_dependencies), 'browser'], '.', 30, ['node-dependencies']),
            ('verifier-tests', [python, '-m', 'unittest', 'discover', '-s', 'scripts/tests', '-p', 'test_verify.py', '-v'], '.', 60, ['python-dependencies']),
            ('static', [python, 'scripts/verify.py', '--static'], '.', 120, ['python-dependencies', 'node-dependencies']),
            ('generated-sync', [python, 'commerce/ui/build.py', '--check'], '.', 180, ['python-dependencies', 'node-dependencies']),
            ('types', [npm, 'run', 'check'], 'commerce/workbench', 120, ['node-dependencies']),
            ('frontend-unit', [npm, 'test'], 'commerce/workbench', 180, ['python-dependencies', 'node-dependencies']),
            ('python-unit', [python, 'scripts/verification/unittest_gate.py', '--output', str(evidence / 'python-unit.json'), *receipt['python_modules']], '.', 300, ['python-dependencies']),
            ('browser-interaction', [node, 'commerce/qa/modern_web_regression.mjs'], '.', 360, ['python-dependencies', 'node-dependencies', 'browser-dependencies']),
        ]
        if args.profile == 'full':
            commands.append(('operating-control-browser', [node, 'commerce/qa/operating_control_ui.mjs'], '.', 180,
                             ['python-dependencies', 'node-dependencies', 'browser-dependencies']))
            commands.append(('operating-loop-browser', [node, 'commerce/qa/operating_loop_ui.mjs'], '.', 180,
                             ['python-dependencies', 'node-dependencies', 'browser-dependencies']))
            commands.append(('catalog-library-browser', [node, 'commerce/qa/catalog_library_ui.mjs'], '.', 180,
                             ['python-dependencies', 'node-dependencies', 'browser-dependencies']))
            commands.append(('product-research-browser', [node, 'commerce/qa/product_research_ui.mjs'], '.', 240,
                             ['python-dependencies', 'node-dependencies', 'browser-dependencies']))
        results = {}
        for name, command, cwd, timeout, prerequisites in commands:
            failed_deps = [p for p in prerequisites if results[p]['status'] != 'passed']
            if failed_deps:
                result = {'id': name, 'command': command, 'cwd': str(snapshot / cwd), 'status': 'blocked',
                          'exit_code': None, 'duration_seconds': 0, 'reason': 'Required dependency gate failed: ' + ', '.join(failed_deps)}
            else:
                gate_env = dict(env)
                print('Running ' + name + ' ...', flush=True)
                result = run_command(name, command, snapshot / cwd, gate_env, run_dir / (name + '.log'), timeout)
                if name == 'frontend-unit' and result['status'] == 'passed':
                    try:
                        receipt['frontend_tests'] = node_test_summary((run_dir / 'frontend-unit.log').read_text())
                    except ValueError as error:
                        result.update(status='failed', reason=str(error))
                if name == 'browser-interaction' and result['status'] == 'passed':
                    try:
                        browser_report = json.loads((evidence / 'browser-results.json').read_text())
                        expected = receipt['source_hashes']['commerce/web/workbench.sources.json']
                        validate_browser_report(browser_report, expected)
                        receipt['browser_checks'] = browser_report['checks']
                    except (OSError, KeyError, ValueError):
                        result.update(status='failed', reason='Missing or invalid required interaction receipt')
                if name == 'operating-control-browser' and result['status'] == 'passed':
                    try:
                        control_report = json.loads((evidence / 'operating-control-browser.json').read_text())
                        validate_control_report(control_report, receipt['source_hashes']['commerce/web/workbench.sources.json'])
                        receipt['operating_control_checks'] = control_report['checks']
                    except (OSError, KeyError, ValueError):
                        result.update(status='failed', reason='Missing or invalid operating control interaction receipt')
                if name == 'operating-loop-browser' and result['status'] == 'passed':
                    try:
                        loop_report = json.loads((evidence / 'operating-loop-browser.json').read_text())
                        validate_loop_report(loop_report, receipt['source_hashes']['commerce/web/workbench.sources.json'])
                        receipt['operating_loop_checks'] = loop_report['checks']
                    except (OSError, KeyError, ValueError):
                        result.update(status='failed', reason='Missing or invalid operating loop interaction receipt')
                if name == 'catalog-library-browser' and result['status'] == 'passed':
                    try:
                        catalog_report = json.loads((evidence / 'verification.json').read_text())
                        validate_catalog_report(catalog_report, receipt['source_hashes'])
                        receipt['catalog_library_checks'] = catalog_report['checks']
                    except (OSError, KeyError, ValueError):
                        result.update(status='failed', reason='Missing or invalid catalog/library interaction receipt')
                if name == 'product-research-browser' and result['status'] == 'passed':
                    try:
                        research_report = json.loads((evidence / 'product-research-browser.json').read_text())
                        validate_research_report(research_report, receipt['source_hashes'])
                        receipt['research_browser_checks'] = research_report['checks']
                    except (OSError, KeyError, ValueError):
                        result.update(status='failed', reason='Missing or invalid research form interaction receipt')
            results[name] = result
            receipt['commands'].append(result)
            print(name + ': ' + result['status'] + ' (exit ' + str(result['exit_code']) + ', ' + str(result['duration_seconds']) + 's)', flush=True)
            write_json(run_dir / 'receipt.json', receipt)
        receipt['source_drift'] = changed_files(receipt['source_hashes'], source_hashes(ROOT))
        if (evidence / 'python-unit.json').is_file():
            receipt['python_tests'] = json.loads((evidence / 'python-unit.json').read_text())
        if (evidence / 'browser-results.json').is_file():
            b = json.loads((evidence / 'browser-results.json').read_text())
            receipt['browser_summary'] = {'completed': b.get('completed') is True,
                                          'requirements_passed': sum(r.get('passed') is True for r in b.get('requirements', [])),
                                          'requirements_total': len(b.get('requirements', [])), 'fatal': b.get('fatal')}
        denials = work / 'network-denials.jsonl'
        if denials.exists():
            shutil.copyfile(denials, run_dir / 'network-denials.jsonl')
            receipt['unexpected_network_denials'] = len(denials.read_text().splitlines())
        good = all(results[g]['status'] == 'passed' for g in receipt['required_gates'])
        good = good and not receipt['source_drift'] and not receipt.get('unexpected_network_denials')
        receipt.update(verification_status='passed' if good else 'failed', exit_code=0 if good else 1)
    except KeyboardInterrupt:
        receipt.update(verification_status='interrupted', exit_code=130)
    except Exception as error:
        receipt.update(verification_status='blocked', error=type(error).__name__ + ': ' + str(error), exit_code=1)
        (run_dir / 'orchestrator.log').write_text(type(error).__name__ + ': ' + str(error) + '\n')
    finally:
        # A unique mkdtemp path created by this invocation; never scan/delete peers.
        try:
            shutil.rmtree(work)
            receipt['scratch_cleaned'] = True
        except OSError:
            receipt.update(scratch_cleaned=False, verification_status='failed', exit_code=1)
        receipt.update(status='awaiting_review', finished_at=datetime.now(timezone.utc).isoformat(),
                       duration_seconds=round(time.monotonic() - started, 3))
        completed = {c['id'] for c in receipt['commands']}
        receipt['not_run'] = [g for g in receipt['required_gates'] if g not in completed]
        write_json(run_dir / 'receipt.json', receipt)
        write_json(OUTPUT / 'latest.json', receipt)
        (OUTPUT / 'report.md').write_text(report_markdown(receipt))
        print('Verification ' + receipt['verification_status'] + '; receipt: ' + receipt['receipt_path'], flush=True)
    return receipt['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
