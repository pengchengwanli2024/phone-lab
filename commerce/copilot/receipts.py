"""Read-only receipts over original action/task rows; no new execution owner."""
import hashlib
from autonomy import stamp


def attach(db, run):
    if not run:
        return
    known = {action['proposal_id'] for action in run.get('actions', [])}
    # Recover a committed task identity after a lost approval acknowledgment.
    # This projection does not repair the journal or schedule the task.
    for proposal in (run.get('result') or {}).get('proposals', []):
        if proposal['id'] in known:continue
        task = db.execute('SELECT id FROM tasks WHERE idempotency_key=?', ('agent:' + run['id'] + ':' + proposal['id'],)).fetchone()
        if task:run.setdefault('actions', []).append(dict(proposal_id=proposal['id'], task_id=task[0], submission_unknown=True))
    for action in run.get('actions', []):
        task_id = action['task_id']
        row = db.execute('''SELECT t.status,r.operation,r.finished,r.result,r.error
            FROM tasks t LEFT JOIN task_runs r ON r.task_id=t.id WHERE t.id=?''', (task_id,)).fetchone()
        status = row[0] if row else 'unknown'
        outcome = ('unknown' if action.get('submission_unknown') else 'pending' if status in ('queued', 'running') else
                   'succeeded' if status == 'completed' and row[2] is not None and row[3] is not None and not row[4] else
                   'failed' if status == 'failed' else 'cancelled' if status == 'cancelled' else 'unknown')
        action['receipt'] = dict(task_id=task_id, status=status, outcome=outcome,
            operation=row[1] if row else None,
            finished_at=stamp(row[2]) if row and row[2] is not None else None,
            result_sha256=hashlib.sha256(row[3].encode()).hexdigest() if row and row[3] is not None else None,
            external_operations_executed=False)
