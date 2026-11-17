"""Run a real isolated backend and verify HTTP, UI and SQLite; no store/model calls."""
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def check(root):
    with tempfile.TemporaryDirectory(prefix='phone-lab-windows-test-') as scratch:
        state = Path(scratch) / 'state'
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT')}
        env.update(COMMERCE_STATE=str(state), COMMERCE_PORT=str(port), PYTHONDONTWRITEBYTECODE='1')
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen([sys.executable, str(root / 'commerce/server.py')],
                                       cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                base = 'http://127.0.0.1:' + str(port)
                deadline = time.monotonic() + 35
                while True:
                    try:
                        secret = (state / 'auth.token').read_text().strip()
                        headers = {'Authorization': 'Bearer ' + secret}
                        with opener.open(urllib.request.Request(base + '/v1/health', headers=headers), timeout=1) as response:
                            health = json.load(response)
                        break
                    except (OSError, urllib.error.URLError):
                        if process.poll() is not None or time.monotonic() > deadline:
                            log.seek(0)
                            raise RuntimeError('isolated_backend_start_failed: ' + log.read(10000).decode(errors='replace'))
                        time.sleep(.15)
                if health.get('service') != 'commerce-backend' or health.get('status') != 'ready':
                    raise RuntimeError('unexpected_backend')
                try:
                    opener.open(base + '/v1/health', timeout=3).close()
                except urllib.error.HTTPError as error:
                    if error.code != 401:
                        raise
                else:
                    raise RuntimeError('authentication_not_enforced')
                with opener.open(urllib.request.Request(base + '/', headers=headers), timeout=8) as response:
                    page = response.read()
                    if response.status != 200 or b'/* INLINE_APP */' in page or len(page) < 10000:
                        raise RuntimeError('workbench_artifact_missing')
                body = json.dumps({'tool': 'commerce_media_provider_catalog', 'arguments': {}, 'client': 'local'}).encode()
                with opener.open(urllib.request.Request(base + '/v1/invoke', data=body,
                        headers={**headers, 'Content-Type': 'application/json'}), timeout=8) as response:
                    catalog = json.load(response)
                    if 'error' in catalog or not isinstance(catalog.get('profiles'), list) or not any(a.get('id') == 'comfyui' for a in catalog.get('adapters', [])):
                        raise RuntimeError('media_provider_catalog_failed')
                with sqlite3.connect(state / 'commerce.sqlite') as database:
                    if database.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('database_integrity_failed')
                return {'status': 'passed', 'platform': sys.platform, 'checks': [
                    'authenticated_http', 'unauthenticated_rejected', 'inline_workbench',
                    'media_provider_catalog', 'isolated_sqlite_integrity'],
                    'real_store_or_model_calls': False, 'windows_host_verified': False}
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(check(args.root.resolve())))
