"""Read-only preflight; uses the existing draft context and fixed-script guards."""
from pathlib import Path
from sealeap_ingest import canonical, sha, audit_script
from sealeap_modes import selected_mode, mode_plan
from sealeap_offline import tree_for

ROOT=Path(__file__).resolve().parent


def assess(library,skill_id,input=None,mode_id=None,expected_source=None,expected_mode=None):
    data={} if input is None else input
    if type(data) is not dict:raise ValueError('sealeap_invalid_readiness_input')
    try:encoded=canonical(data)
    except (TypeError,ValueError,RecursionError):raise ValueError('sealeap_invalid_readiness_input') from None
    if len(encoded)>96000:raise ValueError('sealeap_input_too_large')
    entry=library.entry(skill_id);mode=selected_mode(entry,mode_id)
    integrity=library.verify(entry)
    matches=expected_source is None or expected_source==entry['source_sha256']
    mode_matches=expected_mode is None or bool(mode and expected_mode==sha(canonical(mode).encode()))
    source_ok=integrity and matches and mode_matches
    offline=dict(supported=bool(entry.get('adapter')),can_request=False,input_validation='on_explicit_offline_check')
    draft=dict(supported=not bool(entry.get('adapter')),inputs_ready=False,runtime_status='not_checked',requested=False)
    missing=[];issues=[];references=[]
    if not source_ok:state='source_unavailable'
    elif entry.get('adapter'):
        adapter=entry['adapter'];script=library.source_file(entry,adapter['script'])
        try:
            if sha(script.read_bytes())!=adapter['script_sha256']:raise ValueError('sealeap_script_changed')
            if adapter.get('runner'):
                tree_for(adapter['runner'],script.read_text())
                if sha((ROOT/'sealeap_offline.py').read_bytes())!=adapter['worker_sha256']:raise ValueError('sealeap_worker_changed_rebuild_required')
            else:audit_script(script.read_text())
        except (ValueError,OSError) as error:
            issues.append(str(error) if isinstance(error,ValueError) else 'sealeap_source_unavailable')
        if not data:missing.append('input')
        offline['can_request']=bool(data) and not issues
        state='local_check_available' if offline['can_request'] else 'needs_inputs' if missing else 'blocked'
    else:
        case=dict(skill_id=skill_id,source_sha256=entry['source_sha256'],input=data,synthetic=False,
                  mode_id=mode_id,mode_sha256=sha(canonical(mode).encode()) if mode else None)
        try:
            context,missing=library.drafts.context(case)
            references=[{k:r[k] for k in ('id','path','sha256')} for r in context['references']]
            draft['inputs_ready']=not missing
        except ValueError as error:issues.append(str(error))
        state='draft_inputs_ready' if draft['inputs_ready'] else 'needs_mode' if 'mode_id' in missing else 'needs_inputs' if missing else 'blocked'
    return dict(skill_id=skill_id,mode_id=mode_id,source_sha256=entry['source_sha256'],
                input_sha256=sha(encoded.encode()),source_intact=integrity,source_matches_prepared=matches,mode_matches_prepared=mode_matches,
                state=state,missing_fields=missing,issues=issues,references=references,
                offline_check=offline,model_draft=draft,
                mode_plan=mode_plan(mode,data,library.tool_catalog()) if mode else None,
                external_prerequisites=entry['external_prerequisites'],
                account_entitlement='not_verified',external_execution=dict(available=False,authorized=False),
                field_presence_is_not_business_validation=True,external_requests_submitted=False)
