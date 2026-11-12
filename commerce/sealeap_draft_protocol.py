"""Fail closed before provider access when host and worker contracts differ."""

CONTRACT_VERSION = 'source-bound-draft-v2'


class DraftProtocolError(ValueError):
    pass


def require_current_protocol(payload):
    contract = payload.get('contract') if isinstance(payload, dict) else None
    if not isinstance(contract, dict) or contract.get('version') != CONTRACT_VERSION:
        raise DraftProtocolError('sealeap_draft_contract_version_mismatch_refresh_required')
    sections = contract.get('sections')
    requirements = contract.get('source_requirements')
    if (not isinstance(sections, list) or not sections or
            any(not isinstance(s, str) or not s for s in sections) or
            len(set(sections)) != len(sections) or not isinstance(requirements, list) or
            any(not isinstance(r, dict) or not isinstance(r.get('id'), str) or not r['id'] or
                r.get('kind') not in ('inputs', 'deliverables') for r in requirements) or
            len({r['id'] for r in requirements}) != len(requirements)):
        raise DraftProtocolError('sealeap_draft_contract_incomplete_refresh_required')
    return contract
