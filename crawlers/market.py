"""One bounded, rate-limited public page; no redirect or authenticated browser."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
from setup import environment
from rate_limit import wait_for, outcome

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'commerce'))
from market_research.collector import allowed, extract, MAX_BYTES


def capture(url, output):
    env = environment()
    proxy = urlsplit(env.get('HTTPS_PROXY') or env.get('https_proxy') or '')
    allowed(url, resolve=not (proxy.scheme in ('http', 'https') and proxy.hostname in ('127.0.0.1', 'localhost', '::1')))
    wait_for(url, time.monotonic() + 30)
    raw_path = output.with_suffix('.html')
    result = subprocess.run(['curl', '--disable', '--silent', '--show-error', '--proto', '=https',
                             '--max-time', '23', '--max-filesize', str(MAX_BYTES), '--output', str(raw_path),
                             '--write-out', '%{http_code}', '--user-agent', 'phone-lab-public-research/0.1', url],
                            env=env, capture_output=True, timeout=26)
    status = result.stdout.decode('ascii', errors='replace')
    outcome(url, status in ('429', '503'))
    if raw_path.exists(): raw_path.chmod(0o600)
    if result.returncode == 28: raise ValueError('market_research_source_timeout')
    if status in ('301', '302', '303', '307', '308'): raise ValueError('market_research_redirect_not_followed')
    if status != '200': raise ValueError('market_research_http_' + (status if status.isdigit() else 'failed'))
    if result.returncode: raise ValueError('market_research_capture_failed')
    page = extract(raw_path.read_bytes(), url)
    return {**page, 'captured_at': datetime.now(timezone.utc).isoformat(), 'raw_file': raw_path.name,
            'evidence_kind': 'public_page', 'independently_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--url', required=True)
    parser.add_argument('--output', required=True, type=Path); args = parser.parse_args()
    try:
        result = capture(args.url, args.output); code = 0
    except Exception as error:
        message = str(error)
        result = {'error': message if isinstance(error, ValueError) and message.startswith('market_research_') else 'market_research_capture_failed'}
        code = 1
    args.output.write_text(json.dumps(result, ensure_ascii=False)); args.output.chmod(0o600)
    sys.exit(code)
