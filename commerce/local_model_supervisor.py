"""Optional private llama-server health/recovery; never installed or enabled here.

No MCP interface, shell strings, downloads, arbitrary endpoints or stop/kill.
Health readiness is not model identity verification or successful inference.
"""
import argparse
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import tempfile
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.error import HTTPError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):return None


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def private_file(path, limit=16000):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size > limit):
        raise ValueError('local_model_private_file_required')
    return path.read_bytes()


def load_config(path):
    try:return _load_config(path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError('local_model_configuration_unavailable') from None


def _load_config(path):
    value = json.loads(private_file(path))
    allowed = {'enabled', 'argv', 'executable_sha256', 'startup_timeout_seconds', 'cooldown_seconds', 'max_starts_per_day'}
    if type(value) is not dict or set(value) - allowed or type(value.get('enabled', False)) is not bool:
        raise ValueError('local_model_invalid_config')
    fingerprint = hashlib.sha256(encoded(value).encode()).hexdigest()
    if not value.get('enabled', False):return {'enabled': False, 'config_sha256': fingerprint}
    argv = value.get('argv')
    if (type(argv) is not list or not 7 <= len(argv) <= 40
            or any(type(arg) is not str or not arg or len(arg) > 2000 or any(ord(c) < 32 for c in arg) for arg in argv)):
        raise ValueError('local_model_invalid_argv')
    executable = Path(argv[0])
    if not executable.is_absolute():raise ValueError('local_model_absolute_executable_required')
    executable = executable.resolve(strict=True)
    if executable.name != 'llama-server' or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError('local_model_existing_llama_server_required')
    digest = value.get('executable_sha256')
    if type(digest) is not str or not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('local_model_executable_pin_required')
    checksum = hashlib.sha256()
    with executable.open('rb') as handle:
        for block in iter(lambda: handle.read(1048576), b''):checksum.update(block)
    if checksum.hexdigest() != digest:raise ValueError('local_model_executable_changed')
    aliases = {'-m': '--model', '-c': '--ctx-size', '-t': '--threads', '-ngl': '--n-gpu-layers',
               '-np': '--parallel', '-b': '--batch-size', '-ub': '--ubatch-size', '-fa': '--flash-attn'}
    numbers = {'--ctx-size': (512, 131072), '--threads': (1, 64), '--n-gpu-layers': (0, 999),
               '--parallel': (1, 8), '--batch-size': (1, 8192), '--ubatch-size': (1, 8192)}
    switches = {'--jinja', '--no-webui', '--mlock'}
    values = {};index = 1
    while index < len(argv):
        flag = aliases.get(argv[index], argv[index])
        if flag in values:raise ValueError('local_model_duplicate_flag')
        if flag in switches:values[flag] = True;index += 1;continue
        if flag not in {'--host', '--port', '--model', '--alias', '--flash-attn', '--cache-type-k', '--cache-type-v', *numbers} or index + 1 >= len(argv):
            raise ValueError('local_model_flag_not_approved')
        values[flag] = argv[index + 1];index += 2
        if flag in numbers and (not re.fullmatch('[0-9]{1,6}', values[flag]) or not numbers[flag][0] <= int(values[flag]) <= numbers[flag][1]):
            raise ValueError('local_model_resource_limit')
    if values.get('--host') != '127.0.0.1' or not re.fullmatch('[0-9]{4,5}', values.get('--port', '')) or not 1024 <= int(values['--port']) <= 65535:
        raise ValueError('local_model_loopback_endpoint_required')
    if '--alias' in values and not re.fullmatch('[A-Za-z0-9._-]{1,100}', values['--alias']):
        raise ValueError('local_model_invalid_alias')
    if values.get('--flash-attn', 'auto') not in ('on', 'off', 'auto'):
        raise ValueError('local_model_invalid_flash_attention')
    for flag in ('--cache-type-k', '--cache-type-v'):
        if values.get(flag, 'f16') not in ('f16', 'f32', 'q8_0', 'q4_0', 'q4_1', 'q5_0', 'q5_1', 'iq4_nl'):
            raise ValueError('local_model_invalid_cache_type')
    model = Path(values.get('--model', ''))
    if not model.is_absolute():raise ValueError('local_model_existing_gguf_required')
    model = model.resolve(strict=True)
    if not model.is_file():raise ValueError('local_model_existing_gguf_required')
    with model.open('rb') as handle:
        if handle.read(4) != b'GGUF':raise ValueError('local_model_invalid_gguf')
    bounds = {'startup_timeout_seconds': (30, 1, 120), 'cooldown_seconds': (300, 30, 3600), 'max_starts_per_day': (3, 1, 6)}
    for key, (default, low, high) in bounds.items():
        number = value.get(key, default)
        if type(number) is not int or not low <= number <= high:raise ValueError('local_model_invalid_start_budget')
        value[key] = number
    return {**value, 'enabled': True, 'port': int(values['--port']), 'config_sha256': fingerprint}


def healthy(port):
    try:
        request = Request('http://127.0.0.1:' + str(port) + '/health', headers={'Accept': 'application/json'})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=1) as response:
            raw = response.read(4097)
            return response.status == 200 and len(raw) <= 4096 and json.loads(raw).get('status') == 'ok'
    except HTTPError as error:
        error.close();return False
    except (OSError, ValueError, AttributeError):return False


def occupied(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(.25)
        # Ambiguous socket errors are occupied/unknown, never permission to spawn.
        return connection.connect_ex(('127.0.0.1', port)) != errno.ECONNREFUSED


def process_alive(pid):
    if type(pid) is not int or pid <= 0:return True
    try:os.kill(pid, 0)
    except ProcessLookupError:return False
    except PermissionError:return True
    return True


class LocalModelSupervisor:
    def __init__(self, config_path):
        path = Path(config_path).absolute()
        # Canonicalize parent aliases without following a config-file symlink.
        self.path = path.parent.resolve() / path.name

    @staticmethod
    def result(status, config, **extra):
        return {'status': status, 'enabled': config['enabled'], 'config_sha256': config['config_sha256'],
                'endpoint': 'http://127.0.0.1:' + str(config['port']) if config['enabled'] else None,
                'inference_verified': False, 'model_identity_verified': False, 'process_adopted': False,
                'external_process_stopped': False, **extra}

    def status(self):
        config = load_config(self.path)
        if not config['enabled']:return self.result('disabled', config)
        if healthy(config['port']):return self.result('ready_reused', config)
        return self.result('port_occupied_unhealthy' if occupied(config['port']) else 'unavailable', config)

    def _directory(self):
        directory = self.path.parent / '.local-model-supervisor'
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('local_model_private_state_required')
        return directory

    @staticmethod
    def _read(path):
        if not path.exists():
            if path.is_symlink():raise ValueError('local_model_invalid_state')
            return {}
        value = json.loads(private_file(path))
        if (type(value) is not dict or type(value.get('starts')) is not int or not 0 <= value['starts'] <= 6
                or type(value.get('last_start')) not in (int, float)
                or not isinstance(value.get('day'), str) or value.get('status') not in ('starting', 'unknown', 'ready_started', 'start_failed')
                or value.get('owned_pid') is not None and (type(value['owned_pid']) is not int or value['owned_pid'] <= 0)):
            raise ValueError('local_model_invalid_state')
        return value

    @staticmethod
    def _write(path, value):
        descriptor, name = tempfile.mkstemp(prefix='state-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w') as handle:
                handle.write(encoded(value));handle.flush();os.fsync(handle.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):os.unlink(name)

    def ensure(self):
        config = load_config(self.path)
        if not config['enabled']:return self.result('disabled', config)
        port = config['port']
        if healthy(port):return self.result('ready_reused', config)
        if occupied(port):return self.result('port_occupied_unhealthy', config)
        directory = self._directory()
        # Approval revisions do not reset this endpoint's pending intent or budget.
        identity = hashlib.sha256((str(self.path) + ':127.0.0.1:' + str(port)).encode()).hexdigest()[:24]
        lock_path, state_path = directory / (identity + '.lock'), directory / (identity + '.json')
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(descriptor, 'a+') as lock:
            info = os.fstat(lock.fileno())
            if info.st_uid != os.getuid() or info.st_mode & 0o077:raise ValueError('local_model_private_lock_required')
            try:fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:return self.result('locked', config)
            if healthy(port):return self.result('ready_reused', config)
            if occupied(port):return self.result('port_occupied_unhealthy', config)
            current = load_config(self.path)
            if current['config_sha256'] != config['config_sha256']:return self.result('configuration_changed', current)
            state = self._read(state_path);at = time.time()
            if state and (state.get('owned_pid') is not None and process_alive(state['owned_pid'])
                          or state.get('status') in ('starting', 'unknown') and state.get('owned_pid') is None):
                return self.result('unknown', config)
            day = datetime.fromtimestamp(at, timezone.utc).date().isoformat()
            starts = state.get('starts', 0) if state.get('day') == day else 0
            if starts >= config['max_starts_per_day']:return self.result('daily_start_limit', config)
            next_retry = state.get('last_start', 0) + min(3600, config['cooldown_seconds'] * 2 ** max(0, starts - 1))
            if state and at < next_retry:return self.result('backoff', config, next_retry_at=next_retry)
            state = {'status': 'starting', 'owned_pid': None, 'day': day, 'starts': starts + 1,
                     'last_start': at, 'config_sha256': config['config_sha256'], 'port': port}
            self._write(state_path, state)
            log_fd = os.open(directory / (identity + '.log'), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(log_fd, 'ab') as log:
                info = os.fstat(log.fileno())
                if info.st_uid != os.getuid() or info.st_mode & 0o077:raise ValueError('local_model_private_log_required')
                try:
                    process = subprocess.Popen(config['argv'], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        start_new_session=True, close_fds=True,
                        env={'PATH': str(Path(config['argv'][0]).parent) + os.pathsep + os.defpath, 'LANG': 'en_US.UTF-8', 'LC_ALL': 'en_US.UTF-8'})
                except OSError:
                    state['status'] = 'start_failed';self._write(state_path, state)
                    return self.result('start_failed', config)
            state['owned_pid'] = process.pid;self._write(state_path, state)
            deadline = time.monotonic() + config['startup_timeout_seconds']
            while time.monotonic() < deadline:
                if healthy(port):
                    state['status'] = 'ready_started';self._write(state_path, state)
                    return self.result('ready_started', config)
                time.sleep(.2)
            state['status'] = 'unknown';self._write(state_path, state)
            return self.result('unknown', config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('command', nargs='?', choices=('status', 'ensure', 'watch'), default='status')
    args = parser.parse_args();supervisor = LocalModelSupervisor(args.config)
    try:
        while True:
            result = supervisor.status() if args.command == 'status' else supervisor.ensure()
            print(json.dumps(result), flush=True)
            if args.command != 'watch' or result['status'] == 'disabled':return
            time.sleep(30)
    except KeyboardInterrupt:return
    except Exception:
        print(json.dumps({'status': 'configuration_or_supervision_error', 'started_confirmed': False}))
        raise SystemExit(1)


if __name__ == '__main__':main()
