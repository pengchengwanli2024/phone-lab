"""Read confirmed native receipts before considering a new model allowance."""
import json
from host_execution import digest


def completed(service,task_id,run_id,phase,payload,output_schema,instructions):
    host=service.host_execution
    content={'payload':payload,'output_schema':output_schema,'instructions':instructions}
    with service.core.db() as db:
        if not db.in_transaction:db.execute('BEGIN')
        job,_,run=host._parent(db,task_id,run_id,service.agent_runtime.owner)
        plan=host.plan_for_payload(run)
        rows=db.execute("SELECT * FROM agent_host_attempts WHERE task_id=? AND phase=? AND status='completed' ORDER BY generation DESC",(task_id,phase))
        for row in rows:
            if row[0] in job.get('_rejected_host_attempts',[]):continue
            stored=json.loads(row[7])
            # These are the original host request's cache identity boundaries.
            if (all(stored[k]==value for k,value in content.items())
                    and stored.get('context_sha256')==digest(job['_context']) and stored['route'] in plan):
                value=host._public(row)
                return {'data':value['result'],**{key:value['route'][key]for key in ('provider','model','host_id')}}
    return None
