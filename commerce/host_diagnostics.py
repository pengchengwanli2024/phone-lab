"""Read-only explanations for unconfirmed native attempts, never completion receipts."""
import json
import math
import os
from pathlib import Path
import re
import stat


def latest(state, attempts):
    """Only the final attempt may explain a run; missing history stays unknown."""
    if not attempts:
        return None
    attempt = attempts[-1]
    ident = attempt.get('attempt_id')
    if (attempt.get('status') not in ('unknown', 'failed')
            or not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident)):
        return None
    root = Path(state)
    folder = root / 'host-work' / ident
    path = folder / 'outcome.json'
    descriptor = None
    try:
        if (root / 'host-work').is_symlink() or folder.is_symlink():
            return None
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            return None
        diagnostic = json.loads(os.read(descriptor, 4097))
        if not isinstance(diagnostic, dict):
            return None
        route = attempt.get('route') or {}
        expected = dict(schema='commerce-native-outcome-v1', attempt_id=ident,
                        request_id=attempt.get('request_id'), phase=attempt.get('phase'),
                        provider=route.get('provider'), model=route.get('model'))
        if any(diagnostic.get(key) != value for key, value in expected.items()):
            return None
        code = diagnostic.get('code')
        recorded = diagnostic.get('recorded_at')
        if (code not in ('native_output_limit', 'native_invalid_json')
                or diagnostic.get('submitted') is not True
                or type(recorded) not in (int, float) or not math.isfinite(recorded) or recorded <= 0):
            return None
        # Deliberately exclude raw errors, model output, prompts and filesystem paths.
        return dict(code=code, attempt_id=ident, phase=attempt['phase'], recorded_at=recorded)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
