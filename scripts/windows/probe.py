"""Read Windows inventory using the existing SSH alias and its bound key."""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,120}', args.host):
        raise SystemExit('Use an existing SSH alias')
    code = Path(__file__).with_name('Probe-Windows.ps1').read_text()
    encoded = base64.b64encode(code.encode('utf-16le')).decode('ascii')
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=8', '-o', 'ConnectionAttempts=1', args.host,
               'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand ' + encoded]
    result = subprocess.run(command, capture_output=True, text=True, timeout=75)
    if result.returncode:
        report = {'status': 'ssh_unavailable', 'exit_code': result.returncode,
                  'error': result.stderr.strip()[-2000:], 'remote_environment_observed': False}
    else:
        report = {'status': 'observed', 'inventory': json.loads(result.stdout.lstrip('\ufeff'))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    args.output.chmod(0o600)
    print(json.dumps({'status': report['status'], 'remote_environment_observed': result.returncode == 0}))
    return 0 if result.returncode == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
