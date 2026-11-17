"""Run explicitly selected synthetic suites; empty or skipped suites fail."""
import argparse
import json
from pathlib import Path
import time
import unittest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('modules', nargs='+')
args = parser.parse_args()
started = time.monotonic()
suite = unittest.defaultTestLoader.loadTestsFromNames(args.modules)
result = unittest.TextTestRunner(verbosity=2).run(suite)
ok = result.wasSuccessful() and result.testsRun > 0 and not result.skipped
receipt = {'status': 'passed' if ok else 'failed', 'tests_run': result.testsRun,
           'skipped_count': len(result.skipped), 'skipped': [(t.id(), reason) for t, reason in result.skipped],
           'failures': [t.id() for t, _ in result.failures], 'errors': [t.id() for t, _ in result.errors],
           'duration_seconds': round(time.monotonic() - started, 3), 'modules': args.modules}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(receipt, indent=2) + '\n')
raise SystemExit(0 if ok else 1)
