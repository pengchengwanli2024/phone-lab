"""Exercise the shipped crawler entry point without contacting a remote site."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ResearchPackaging(unittest.TestCase):
    def test_published_crawler_entry_point_exposes_its_launch_contract(self):
        result = subprocess.run([sys.executable, str(ROOT / 'crawlers/market.py'), '--help'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--url', result.stdout)
        self.assertIn('--output', result.stdout)

    def test_crawler_entry_point_rejects_private_origin_with_a_real_error_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'rejected.json'
            result = subprocess.run([
                sys.executable, str(ROOT / 'crawlers/market.py'),
                '--url', 'http://127.0.0.1/private', '--output', str(output)],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(output.read_text()),
                             {'error': 'market_research_url_rejected'})
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
