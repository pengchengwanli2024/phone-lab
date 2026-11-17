"""Explicit source snapshots and fixed checks in a fail-closed macOS sandbox."""
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import socket
import select
import subprocess
import sys
import tempfile
import time
import uuid


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def relative(value):
    if (not isinstance(value, str) or not value or len(value) > 200 or '\\' in value
            or any(ord(c) < 32 for c in value)):
        raise ValueError('engineering_invalid_path')
    parts = PurePosixPath(value).parts
    if (PurePosixPath(value).is_absolute() or str(PurePosixPath(value)) != value
            or any(p in ('.', '..') or p.startswith('.') for p in parts)
            or any(p in ('node_modules', '__pycache__', 'target', 'dist', 'state', 'venv') for p in parts)
            or re.search(r'credential|secret|password|private.key|\.sqlite|\.pem$|\.key$', value, re.I)):
        raise ValueError('engineering_private_or_invalid_path')
    if PurePosixPath(value).suffix not in ('.py', '.md', '.json', '.txt', '.toml', '.js', '.ts', '.tsx', '.css'):
        raise ValueError('engineering_source_type_unsupported')
    return value


def source_file(root, value):
    root = Path(root).resolve()
    path = root / relative(value)
    if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
        raise ValueError('engineering_symlink_denied')
    if not path.resolve().is_relative_to(root): raise ValueError('engineering_invalid_path')
    return path


def capture(root, files, writable):
    if (type(files) is not list or not 1 <= len(files) <= 24 or len(set(files)) != len(files)
            or type(writable) is not list or not 1 <= len(writable) <= 8 or len(set(writable)) != len(writable)):
        raise ValueError('engineering_invalid_scope')
    files = [relative(p) for p in files]
    writable = [relative(p) for p in writable]
    if not set(writable) <= set(files): raise ValueError('engineering_write_scope_not_in_snapshot')
    if any(p == 'AGENTS.md' or p.startswith('commerce/engineering/') or p in (
            'commerce/service.py', 'commerce/capability_lifecycle.py', 'commerce/agent_runtime/policy.py')
            or PurePosixPath(p).name in ('unittest.py', 'sitecustomize.py', 'usercustomize.py') for p in writable):
        raise ValueError('engineering_protected_path')
    if (root / 'AGENTS.md').exists() and 'AGENTS.md' not in files: files.append('AGENTS.md')
    contents, manifest, size = {}, {}, 0
    for name in files:
        p = source_file(root, name)
        if not p.exists():
            if name not in writable: raise ValueError('engineering_source_missing')
            contents[name], manifest[name] = None, None
            continue
        if not p.is_file() or p.stat().st_size > 64000: raise ValueError('engineering_source_too_large')
        raw = p.read_bytes(); size += len(raw)
        if size > 64000: raise ValueError('engineering_context_too_large')
        try: contents[name] = raw.decode('utf-8')
        except UnicodeError: raise ValueError('engineering_source_not_utf8') from None
        manifest[name] = digest(raw)
    return contents, manifest


def current(root, manifest):
    try:
        for name, expected in manifest.items():
            p = source_file(root, name)
            if expected is None:
                if p.exists(): return False
            elif not p.is_file() or p.stat().st_size > 64000 or digest(p.read_bytes()) != expected: return False
        return True
    except (OSError, ValueError): return False


def validate_checks(checks, files, writable):
    if type(checks) is not list or not 1 <= len(checks) <= 4: raise ValueError('engineering_invalid_checks')
    for check in checks:
        if (type(check) is not dict or set(check) != {'kind', 'paths'} or check['kind'] not in ('python_unittest', 'python_compile')
                or type(check['paths']) is not list or not 1 <= len(check['paths']) <= 8):
            raise ValueError('engineering_invalid_checks')
        for name in check['paths']:
            relative(name)
            if not name.endswith('.py') or name not in files: raise ValueError('engineering_check_not_in_snapshot')
            if check['kind'] == 'python_unittest' and name in writable: raise ValueError('engineering_acceptance_must_be_readonly')


def materialize(work, contents, edits, writable):
    work.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name, content in contents.items():
        if content is not None:
            p = work / name;p.parent.mkdir(parents=True, exist_ok=True);p.write_text(content)
    if type(edits) is not list or not 1 <= len(edits) <= 8: raise ValueError('engineering_invalid_edits')
    seen, size = set(), 0
    for edit in edits:
        if type(edit) is not dict or set(edit) != {'path', 'content'} or not isinstance(edit['content'], str):
            raise ValueError('engineering_invalid_edit')
        name = edit['path']
        if not isinstance(name, str) or name not in writable or name in seen: raise ValueError('engineering_edit_outside_write_scope')
        name = relative(name)
        if contents[name] is None and edit['content'] == '': raise ValueError('engineering_empty_new_file_not_patchable')
        seen.add(name);size += len(edit['content'].encode())
        if size > 32000 or '\x00' in edit['content']: raise ValueError('engineering_edit_too_large')
        p = work / name;p.parent.mkdir(parents=True, exist_ok=True);p.write_text(edit['content'])
    candidate = {name: digest((work / name).read_bytes()) if (work / name).is_file() else None for name in contents}
    for name, content in contents.items():
        if name not in writable and content is not None and candidate[name] != digest(content.encode()):
            raise ValueError('engineering_acceptance_changed')
    patch_lines = []
    for edit in edits:
        for line in difflib.unified_diff((contents[edit['path']] or '').splitlines(keepends=True),
                edit['content'].splitlines(keepends=True),
                fromfile='/dev/null' if contents[edit['path']] is None else 'a/' + edit['path'], tofile='b/' + edit['path']):
            patch_lines.append(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n')
    patch = ''.join(patch_lines)
    if not patch: raise ValueError('engineering_empty_patch')
    return candidate, patch


def interpreter():
    base = Path(getattr(sys, '_base_executable', sys.executable)).resolve()
    framework = base.parents[1] / 'Resources/Python.app/Contents/MacOS/Python'
    return framework if framework.is_file() else base


def policy(work, readonly=()):
    work = str(Path(work).resolve())
    quoted = json.dumps(work)
    executable = [str(interpreter())]
    return ('(version 1) (allow default) (deny network*) (deny process-fork signal process-info*) '
        '(deny mach-lookup) (deny file-write*) '
        '(allow file-write* (subpath ' + quoted + ') (literal "/dev/null")) '
        '(deny file-read* (subpath "/Users") (subpath "/Volumes") '
        '(subpath "/private/var/folders") (subpath "/private/tmp") (subpath "/var/root")) '
        '(allow file-read* (subpath ' + json.dumps(str(Path(sys.base_prefix).resolve())) + ')) '
        '(allow file-read* (subpath ' + quoted + ')) '
        '(deny process-exec) (allow process-exec ' + ' '.join('(literal ' + json.dumps(p) + ')' for p in executable) + ') '
        + ('(deny file-write* ' + ' '.join('(literal ' + json.dumps(str(Path(work) / p)) + ')' for p in readonly) + ')' if readonly else ''))


def execute(code, work, cancelled=lambda: False, timeout=30, readonly=(), on_start=None):
    if cancelled(): raise ValueError('engineering_cancelled')
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise ValueError('engineering_sandbox_unavailable')
    work = Path(work).resolve();home = work / '_home';tmp = work / '_tmp'
    home.mkdir(exist_ok=True);tmp.mkdir(exist_ok=True)
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'TMPDIR': str(tmp), 'LANG': 'en_US.UTF-8', 'PYTHONNOUSERSITE': '1'}
    receipt = work.parent / ('check-' + uuid.uuid4().hex + '.json')
    packet = {'command': ['/usr/bin/sandbox-exec', '-p', policy(work, readonly), str(interpreter()), '-I', '-c', code],
              'cwd': str(work), 'env': env, 'timeout': timeout, 'receipt': str(receipt)}
    proc = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('watchdog.py'))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, start_new_session=True)
    started = time.monotonic()
    try:
        proc.stdin.write(json.dumps(packet).encode() + b'\n');proc.stdin.flush()
        if not select.select([proc.stdout], [], [], 5)[0]: raise ValueError('engineering_watchdog_unavailable')
        ready = json.loads(proc.stdout.readline(1000))
        if ready != {'event': 'ready', 'pid': proc.pid}: raise ValueError('engineering_watchdog_invalid_owner')
        if on_start: on_start(proc.pid, receipt)
        if cancelled(): raise ValueError('engineering_cancelled')
        proc.stdin.write(b'go\n');proc.stdin.flush()
        while not select.select([proc.stdout], [], [], .05)[0]:
            if cancelled(): raise ValueError('engineering_cancelled')
            if time.monotonic() - started > timeout + 6: raise ValueError('engineering_watchdog_timeout')
            if proc.poll() is not None: raise ValueError('engineering_watchdog_lost')
        raw = proc.stdout.readline(80001)
        if len(raw) > 80000: raise ValueError('engineering_check_output_too_large')
        try: result = json.loads(raw)
        except ValueError: raise ValueError('engineering_checker_outcome_unknown') from None
        try: completed = json.loads(receipt.read_text())
        except (OSError, ValueError): completed = {}
        if completed.get('state') != 'finished': raise ValueError('engineering_checker_outcome_unknown')
        error = result.pop('error', None)
        if error: raise ValueError(error)
        result['owner_receipt'] = completed
        return result
    finally:
        if proc.stdin and not proc.stdin.closed:
            try: proc.stdin.close()
            except BrokenPipeError: pass
        try: proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            # Preserve the journalled owner for explicit recovery if supervision is unconfirmed.
            raise ValueError('engineering_watchdog_stop_unknown') from None
        if proc.stdout: proc.stdout.close()


def sandbox_probe():
    if sys.platform != 'darwin': return {'available': False, 'denied': [], 'reason': 'macos_sandbox_required'}
    try:
        with tempfile.TemporaryDirectory(prefix='engineering-probe-') as root:
            root = Path(root).resolve();work = root / 'work';work.mkdir()
            outside = root / 'outside.txt';outside.write_text('synthetic sandbox marker')
            listener = socket.socket();listener.bind(('127.0.0.1', 0));listener.listen(2)
            port = listener.getsockname()[1]
            victim = subprocess.Popen([sys.executable, '-I', '-c', 'import time;time.sleep(15)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            code = ('import json, pathlib, socket, subprocess, os, signal\n'
                'def fork_once():\n'
                ' pid=os.fork()\n'
                ' if pid==0: os._exit(0)\n'
                ' os.waitpid(pid,0)\n'
                'denied=[]\n'
                'for name, operation in [\n'
                ' ("outside_read",lambda:pathlib.Path(' + repr(str(outside)) + ').read_text()),\n'
                ' ("outside_write",lambda:pathlib.Path(' + repr(str(root / 'written')) + ').write_text("bad")),\n'
                ' ("network",lambda:socket.create_connection(("127.0.0.1",' + str(port) + '),timeout=1)),\n'
                ' ("shell",lambda:subprocess.run(["/bin/sh","-c","exit 0"],check=True)),\n'
                ' ("signal",lambda:os.kill(' + str(victim.pid) + ',signal.SIGTERM)),\n'
                ' ("fork",fork_once)]:\n'
                ' try: operation()\n'
                ' except (PermissionError, OSError): denied.append(name)\n'
                'print(json.dumps(denied))\n')
            try: result = execute(code, work, timeout=8)
            finally:
                listener.close()
                if victim.poll() is None: victim.terminate()
                victim.wait(timeout=3)
            denied = json.loads(result['output']) if result['returncode'] == 0 else []
            return {'available': denied == ['outside_read', 'outside_write', 'network', 'shell', 'signal', 'fork'], 'denied': denied,
                    'verification': 'local_denial_probes_not_formal_security_proof'}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'available': False, 'denied': [], 'reason': 'sandbox_probe_failed'}


def checks(work, recipes, cancelled, readonly, timeout=30, on_start=None):
    results = []
    for recipe in recipes:
        paths = recipe['paths']
        marker = 'ENGINEERING_CHECK_' + os.urandom(24).hex() + ':'
        if recipe['kind'] == 'python_compile':
            code = 'import py_compile,json\n' + '\n'.join('py_compile.compile(' + repr(p) + ', doraise=True)' for p in paths)
            code += '\nprint(' + repr(marker) + '+json.dumps({"compiled":' + str(len(paths)) + '}),flush=True)\n'
        else:
            code = ('import sys,unittest,importlib.util,pathlib,json\n'
                'sys.path[:0]=[str(pathlib.Path.cwd()),str(pathlib.Path.cwd()/"commerce")]\n'
                'suite=unittest.TestSuite()\n'
                'for i,path in enumerate(' + repr(paths) + '):\n'
                ' spec=importlib.util.spec_from_file_location("engineering_check_"+str(i),path)\n'
                ' module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)\n'
                ' suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))\n'
                'result=unittest.TextTestRunner(verbosity=2).run(suite)\n'
                'print(' + repr(marker) + '+json.dumps({"tests":result.testsRun,"skipped":len(result.skipped),"successful":result.wasSuccessful()}),flush=True)\n'
                'sys.exit(0 if result.wasSuccessful() and result.testsRun>len(result.skipped) else 1)\n')
        result = execute(code, work, cancelled, timeout, readonly, on_start=on_start)
        lines = result['output'].splitlines();attestations = [line[len(marker):] for line in lines if line.startswith(marker)]
        try: receipt = json.loads(attestations[0]) if len(attestations) == 1 else {}
        except ValueError: receipt = {}
        valid = receipt.get('compiled') == len(paths) if recipe['kind'] == 'python_compile' else (
            type(receipt.get('tests')) is int and type(receipt.get('skipped')) is int
            and receipt['tests'] > receipt['skipped'] >= 0 and receipt.get('successful') is True)
        result['output'] = '\n'.join(line for line in lines if not line.startswith(marker))
        results.append({**recipe, **result, 'receipt': receipt,
            'status': 'passed' if result['returncode'] == 0 and valid else 'failed'})
    return results
