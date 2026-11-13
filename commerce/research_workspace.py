"""Read-only study views over a shared product and immutable research artifacts."""
import json
from urllib.parse import urlencode
from research import canonical, digest


def workspace_url(case_id, task_id):
    return '/workspace?' + urlencode({'tab': 'workspace', 'case_id': case_id,
                                      'research_task_id': task_id})


def views(core, case, current_artifact_id, selected_task_id=None):
    if selected_task_id is not None and (not isinstance(selected_task_id, str)
            or not selected_task_id or len(selected_task_id) > 160):
        raise ValueError('workspace_research_context_mismatch')
    with core.db() as db:
        if not db.in_transaction:
            db.execute('BEGIN')
        query = '''SELECT j.task_id,j.document,a.id,a.payload,a.sha,a.created
                   FROM org_artifacts a JOIN market_research_jobs j
                   ON a.idem='market-research:'||j.task_id
                   WHERE a.case_id=? AND a.kind='research' '''
        rows = db.execute(query + 'ORDER BY a.created DESC,a.id DESC LIMIT 50',
                          (case['id'],)).fetchall()
        if selected_task_id is not None and not any(r[0] == selected_task_id for r in rows):
            rows += db.execute(query + 'AND j.task_id=? ORDER BY a.created DESC,a.id DESC',
                               (case['id'], selected_task_id)).fetchall()
        references, full, invalid = [], {}, set()
        for task_id, encoded, artifact_id, payload_text, sha, created in rows:
            try:
                job, payload = json.loads(encoded), json.loads(payload_text)
                if not isinstance(job, dict) or not isinstance(payload, dict):
                    raise ValueError()
                candidates = [c for c in job['candidates'] if c['case_id'] == case['id']
                              and c['artifact_id'] == artifact_id]
                if (len(candidates) != 1 or job['task_id'] != task_id
                        or digest(canonical(payload)) != sha
                        or payload.get('row_key') != case['scope']['row_key']
                        or payload.get('sku') != case['scope']['sku']):
                    raise ValueError()
                candidate = candidates[0]
                reference = {'task_id': task_id, 'run_id': job['run_id'], 'status': job['status'],
                             'revision': job['revision'], 'case_id': case['id'],
                             'artifact_id': artifact_id, 'artifact_sha256': sha,
                             'source_ids': candidate['source_ids'],
                             'is_current_artifact': artifact_id == current_artifact_id,
                             'read_only': True, 'workspace_url': workspace_url(case['id'], task_id)}
                references.append(reference)
                full[task_id] = {**reference, 'artifact': {'id': artifact_id, 'payload': payload,
                                'sha256': sha, 'created_at': created, 'intact': True}}
            except (KeyError, TypeError, ValueError):
                invalid.add(task_id)
        if selected_task_id is not None:
            if selected_task_id in invalid:
                raise ValueError('workspace_research_artifact_invalid')
            if selected_task_id not in full:
                raise ValueError('workspace_research_context_mismatch')
            selected = full[selected_task_id]
        else:
            selected = next((full[r['task_id']] for r in references if r['is_current_artifact']), None)
        if selected is not None:
            selected = {**selected, 'selected_explicitly': selected_task_id is not None}
        return {'research_context': selected, 'research_contexts': references,
                'research_context_errors': [{'task_id': task_id, 'error': 'workspace_research_artifact_invalid'}
                                            for task_id in sorted(invalid)]}
