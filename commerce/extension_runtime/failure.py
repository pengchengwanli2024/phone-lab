"""What a failed extension step means. Pure: no clock, no database, no exception objects.

Three questions, and the answers decide whether the run may be asked again:
  * is the step still within its time budget (so it is charged, not silently retried);
  * may it already have produced an external effect or model output (-> unknown, never
    resend automatically) or certainly not (-> failed)?
  * which reason code describes it?
Exception messages are never returned: they can carry provider text, paths or secrets.
Kept apart from the runtime so this decision can be reviewed and changed on its own,
inside the bounded snapshot the engineering executor accepts.

Known inconsistency, deliberately preserved here: the completion path treats a model
step as uncertain as soon as it is in flight, while this failure path only does so
once the run is out of budget. Changing either side alters when a failed run may be
resumed, so it needs an explicit decision rather than a refactor.
"""
import re

CODE = re.compile(r'(extension|agent)_[a-z0-9_]+')
STEP = re.compile(r'[A-Za-z0-9_.:-]{1,200}')
TYPE = re.compile(r'.{1,60}')
GENERIC = 'extension_execution_failed'
BUDGET = 'extension_budget_exhausted'
OUTCOME_UNKNOWN = 'agent_provider_outcome_unknown'


def budget_expired(usage_seconds, max_seconds, flight, now):
    """Wall-clock budget check, counting the time the current step has been in flight."""
    elapsed = max(0, now - flight.get('accounted_at', flight.get('started_at', now))) if flight else 0
    return usage_seconds + elapsed >= max_seconds


def charge_inflight(flight, now):
    """Seconds to add to usage for the step in flight; also stamps it as accounted."""
    if not flight:
        return 0
    spent = max(0, now - flight.get('accounted_at', flight.get('started_at')))
    flight['accounted_at'] = now
    return spent


def holds_uncertain_effect(flight, expired):
    """True when the step may already have written externally.

    A model step counts as uncertain only once the run is out of budget, which is
    what the runtime did before this was extracted; see the note in the module
    docstring about the difference from the completion path.
    """
    return flight.get('effect') == 'external_write' or (expired and flight.get('kind') == 'model')


def classify(*, error_code, error_type, flight, expired, outcome_unknown=False):
    """Return (status, code, cause) for a failed step.

    error_code: str(error); error_type: type(error).__name__; flight: the run's
    inflight dict; expired: budget_expired(...) *before* charging; outcome_unknown:
    the transport reported that its own outcome is unknown.
    """
    uncertain = outcome_unknown or error_code == OUTCOME_UNKNOWN or holds_uncertain_effect(flight, expired)
    if expired:
        code = BUDGET
    elif error_type == 'ValueError' and CODE.fullmatch(error_code):
        # Only a deliberately coded ValueError carries its own code; any other exception
        # text could be anything, including provider output, so it is never used as a code.
        code = error_code
    else:
        code = GENERIC
    cause = None
    if code == GENERIC:
        step = flight.get('step_id')
        cause = {'type': error_type if TYPE.fullmatch(error_type) else 'Error',
                 'step': step if isinstance(step, str) and STEP.fullmatch(step) else None}
    return ('unknown' if uncertain else 'failed'), code, cause
