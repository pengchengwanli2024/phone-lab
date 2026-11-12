"""Pure rollup of evidence descriptors; it grants no execution authority."""
import re

def evaluate(checks):
    if not isinstance(checks,list):raise ValueError('invalid_checks')
    seen=set();states=[];gaps=[];passed=0
    for c in checks:
        if not isinstance(c,dict):raise ValueError('invalid_check')
        ident=c.get('id');state=c.get('state')
        if not isinstance(ident,str) or not ident.strip() or ident in seen:raise ValueError('invalid_check_id')
        if not isinstance(state,str) or state not in ('PASS','FAIL','BLOCKED','HOLD'):raise ValueError('invalid_state')
        seen.add(ident);evidence=c.get('evidence')
        proof=isinstance(evidence,list) and any(isinstance(e,dict) and isinstance(e.get('ref'),str) and e['ref'].strip() and isinstance(e.get('sha256'),str) and re.fullmatch('[a-f0-9]{64}',e['sha256']) for e in evidence)
        reason=c.get('detail')
        if state=='PASS' and not proof:state='HOLD';reason='evidence_missing'
        if state=='PASS':passed+=1
        else:
            text=lambda v,fallback:v.strip() if isinstance(v,str) and v.strip() else fallback
            gaps.append(dict(id=ident,status=state,reason=text(reason,'missing detail'),owner=text(c.get('owner'),'conductor'),verify=text(c.get('verify'),'missing verification criteria')))
        states.append(state)
    status=next((s for s in ('FAIL','BLOCKED','HOLD','PASS') if s in states),'HOLD')
    return dict(status=status,passed=passed,total=len(checks),gaps=gaps,executable=False)
