"""Assert the project's existing locked Python runtime, without installing."""
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
assert os.environ.get('VERIFY_NETWORK_GUARD_ACTIVE') == '1', 'Python fixture network guard required'
assert sys.version_info >= (3, 12), 'Python 3.12 or newer required'
packages = {}
for filename in ('commerce/requirements.txt', 'commerce/a2ui/requirements.txt'):
    for line in (root / filename).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '-r ')):
            continue
        name, required = line.split('==')
        actual = importlib.metadata.version(name)
        assert actual == required, name + ' locked dependency mismatch'
        packages[name] = actual
for name in ('yaml', 'jsonschema', 'referencing', 'service'):
    importlib.import_module(name)
print(json.dumps({'python': sys.version.split()[0], 'packages': packages, 'commerce_import': True}))
