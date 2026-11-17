"""Trusted checker supervisor: parent pipe EOF revokes its owned process group."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    packet = json.loads(sys.stdin.buffer.readline(100001))
    receipt = Path(packet['receipt'])
    def checkpoint(value):
        temporary = receipt.with_suffix('.pending')
        temporary.write_text(json.dumps(value));temporary.replace(receipt)
    checkpoint({'state': 'armed', 'watchdog_pid': os.getpid()})
    emit({'event': 'ready', 'pid': os.getpid()})
    # No candidate code starts before the caller durably records this owner.
    if sys.stdin.buffer.readline(20) != b'go\n':
        checkpoint({'state': 'finished', 'watchdog_pid': os.getpid(), 'not_started': True})
        return
    with tempfile.TemporaryFile() as output:
        proc = subprocess.Popen(packet['command'], cwd=packet['cwd'], env=packet['env'],
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        checkpoint({'state': 'running', 'watchdog_pid': os.getpid(), 'checker_pid': proc.pid})
        started = time.monotonic();error = None
        try:
            while proc.poll() is None:
                readable, _, _ = select.select([sys.stdin.buffer], [], [], .05)
                if readable and not os.read(sys.stdin.fileno(), 1): error = 'engineering_parent_lost';break
                if time.monotonic() - started >= packet['timeout']: error = 'engineering_check_timeout';break
                if os.fstat(output.fileno()).st_size > 64000: error = 'engineering_check_output_too_large';break
        finally:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            proc.wait(timeout=3)
        checkpoint({'state': 'finished', 'watchdog_pid': os.getpid(), 'checker_pid': proc.pid, 'returncode': proc.returncode})
        output.seek(0);raw = output.read(64001)
        if len(raw) > 64000: error = 'engineering_check_output_too_large'
        emit({'returncode': proc.returncode, 'output': raw.decode('utf-8', errors='replace')[-12000:],
              'seconds': round(time.monotonic() - started, 3), 'error': error})


if __name__ == '__main__':
    try: main()
    except BrokenPipeError: pass
