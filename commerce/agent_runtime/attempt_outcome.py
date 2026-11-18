"""Classify one model attempt from its own event log. Pure: no process, clock or I/O.

The decision that matters is whether a failed attempt may already have produced
model output (outcome unknown: check the original, never resend) or certainly did
not (failed: safe to ask again explicitly). Kept apart from the CLI transport so
it can be reviewed and changed on its own, within the engineering executor's
bounded snapshot.
"""
import json
import math

STAGES = {'thread.started': (1, 'session_started'), 'turn.started': (2, 'model_started'),
          'item.completed': (3, 'message_received'), 'turn.completed': (4, 'turn_completed')}
KNOWN_STAGES = ('process_started', 'session_started', 'model_started', 'message_received', 'turn_completed')
KNOWN_REASONS = ('invalid_response', 'cli_exit', 'deadline', 'cancelled')
# Once the model has started a turn, output may exist even if the process then failed.
MAY_HAVE_OUTPUT = ('model_started', 'message_received')
MAX_LOG_BYTES = 1000000


def furthest_stage(raw):
    """Furthest stage reached according to a JSON-lines event log (bytes)."""
    stage, rank = 'process_started', 0
    for line in raw[:MAX_LOG_BYTES].splitlines():
        try: event = json.loads(line)
        except (ValueError, UnicodeError): continue
        if not isinstance(event, dict): continue
        item = event.get('item')
        if event.get('type') == 'item.completed' and (not isinstance(item, dict) or item.get('type') != 'agent_message'):
            continue
        current = STAGES.get(event.get('type'))
        if current and current[0] > rank: rank, stage = current
    return stage


def diagnostic(raw, elapsed_seconds, reason, returncode):
    # No response text, stderr, prompts, paths, session IDs or credentials.
    return {'provider': 'codex_cli', 'stage': furthest_stage(raw), 'reason': reason,
            'elapsed_seconds': round(elapsed_seconds, 3), 'returncode': returncode, 'automatic_retry': False}


def exit_error(stage):
    """Error code for a CLI that exited non-zero after reaching `stage`."""
    return 'agent_provider_outcome_unknown' if stage in MAY_HAVE_OUTPUT else 'agent_provider_failed_no_automatic_retry'


def valid(value):
    """True only for a diagnostic shaped exactly like ours; anything else is ignored."""
    return (isinstance(value, dict) and value.get('provider') == 'codex_cli' and value.get('stage') in KNOWN_STAGES
            and value.get('reason') in KNOWN_REASONS and type(value.get('elapsed_seconds')) in (int, float)
            and math.isfinite(value['elapsed_seconds']) and value['elapsed_seconds'] >= 0
            and (value.get('returncode') is None or type(value['returncode']) is int))
