"""Mode-specific field checks and registry discovery, never remote execution."""
from datetime import datetime,timezone
from sealeap_ingest import canonical,sha


def selected_mode(entry,mode_id):
    if not mode_id:return None
    mode=next((m for m in entry.get('subcapabilities',[]) if m['name']==mode_id),None)
    if mode is None:raise ValueError('sealeap_mode_not_in_skill')
    return mode


def mode_plan(mode,data,definitions):
    names={d[0] for d in definitions};contracts=[]
    def provided(name):
        parameters=data.get('parameters')
        value=data.get(name,parameters.get(name) if isinstance(parameters,dict) else None)
        return value is not None and value!='' and not (isinstance(value,str) and not value.strip())
    for capability in mode.get('capabilities') or []:
        tool=capability.get('tool','');required=capability.get('required_fields') or []
        contracts.append(dict(provider=capability.get('provider'),tool=tool,required_fields=required,
            missing_fields=[field for field in required if not provided(field)],
            registered_in_workbench=tool in names,account_entitlement='not_verified',
            policy_and_scope='not_verified',invoked=False))
    missing=sorted({field for c in contracts for field in c['missing_fields']})
    unavailable=[c['tool'] for c in contracts if not c['registered_in_workbench']]
    return dict(mode_id=mode['name'],mode_sha256=sha(canonical(mode).encode()),title=mode['title'],reference=mode['reference'],
        contracts=contracts,field_presence_only=True,missing_fields_across_routes=missing,
        tool_check_scope='workbench_registry_only_not_all_connected_clients',tool_registry_checked_at=datetime.now(timezone.utc).isoformat(),tool_registry_names_sha256=sha(canonical(sorted(names)).encode()),unregistered_tools=unavailable,
        account_entitlement='not_verified',state='needs_inputs_and_tools' if missing and unavailable else 'needs_inputs' if missing else 'needs_external_tools' if unavailable else 'needs_account_and_scope_review',
        external_requests_submitted=False,
        limits=['Contracts are separate route/stage requirements; their union is not a claim that every field is an initial input.',
                'Presence is not validity or source authenticity. Registry presence does not grant account access or write authorization.'])
