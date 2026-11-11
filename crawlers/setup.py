"""Install the desktop crawler lab without changing shared agent profiles."""
import json
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.local' / 'crawlers'


def environment():
    env = os.environ.copy()
    network = STATE / 'network-env.json'
    if network.exists():
        env.update(json.loads(network.read_text()))
    env.update(
        UV_CACHE_DIR=str(STATE / 'cache' / 'uv'),
        PLAYWRIGHT_BROWSERS_PATH=str(STATE / 'browsers'),
        CRAWL4_AI_BASE_DIRECTORY=str(STATE),
        XDG_CACHE_HOME=str(STATE / 'cache'),
        CRAWLEE_STORAGE_DIR=str(STATE / 'storage'),
    )
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh-lock', action='store_true')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    (STATE / 'logs').mkdir(exist_ok=True)
    logs = STATE / 'logs' / ('setup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    logs.mkdir(mode=0o700)
    commands = []
    if not (STATE / 'venv/bin/python').exists():
        commands.append(['uv', 'venv', '--python', '3.12', str(STATE / 'venv')])
    if args.refresh_lock or not (ROOT / 'crawlers/requirements.lock').exists():
        commands.append(['uv', 'pip', 'compile', '--python', '3.12',
                         'crawlers/requirements.in', '--output-file',
                         'crawlers/requirements.lock', '--no-header'])
    commands.extend([
        ['uv', 'pip', 'sync', '--python', str(STATE / 'venv/bin/python'),
         'crawlers/requirements.lock'],
        [str(STATE / 'venv/bin/python'), '-m', 'playwright', 'install', 'chromium'],
    ])
    for index, command in enumerate(commands):
        with (logs / f'step-{index}.log').open('w') as log:
            result = subprocess.run(command, cwd=ROOT, env=environment(), stdout=log, stderr=log)
        print(json.dumps({'step': index, 'exit_code': result.returncode}), flush=True)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
