"""Prove that a recorded database backup can be restored and actually read.

A backup nobody restored is unproven. This takes one recorded backup, copies it
into a private temporary directory, checks SQLite integrity, opens the domain
service against the copy (workers stopped immediately) and reads a few real
endpoints from it, then compares row counts with the live database read-only.

It never writes to the live state, never starts the real service, never sends
anything and needs no network. The backup's own scope still applies: it is the
database only, without media, credentials or knowledge.
"""
from contextlib import closing
import os
import re
import shutil
import sqlite3
import tempfile
import time

AUTO = re.compile(r'auto-commerce-\d{10,20}\.sqlite')
MANUAL = re.compile(r'commerce-\d{10,20}\.sqlite')
TABLES = ('tasks', 'org_cases', 'live_snapshots', 'operating_loop_grants')


def backups(state, pattern=AUTO):
    folder = state / 'backups'
    if not folder.is_dir() or folder.is_symlink():
        return []
    rows = [p for p in folder.iterdir() if pattern.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    return sorted(rows, key=lambda p: p.stat().st_mtime, reverse=True)


def _counts(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {name: db.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0] for name in TABLES if name in names}


def drill(state, backup=None, timeout_seconds=120):
    """Restore one backup into a temporary state and read from it. Returns a receipt."""
    state = state.resolve()
    started = time.monotonic()
    receipt = {'schema': 'commerce-backup-restore-drill-v1', 'status': 'running', 'scope': 'database_only',
               'live_state_written': False, 'service_started': False, 'network_used': False, 'backup': None,
               'checks': [], 'restored_reads': {}, 'row_counts_match': None}
    work = None
    try:
        source = backup or (backups(state)[0] if backups(state) else None)
        if source is None:
            receipt.update(status='unavailable', code='no_backup_recorded');return receipt
        source = source.resolve()
        if source.is_symlink() or not source.is_file() or not source.is_relative_to(state / 'backups'):
            receipt.update(status='failed', code='backup_path_not_allowed');return receipt
        receipt['backup'] = source.name
        live = _counts(state / 'commerce.sqlite') if (state / 'commerce.sqlite').is_file() else {}
        work = tempfile.mkdtemp(prefix='restore-drill-')
        restored = __import__('pathlib').Path(work) / 'commerce.sqlite'
        fd = os.open(restored, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600);os.close(fd)
        shutil.copyfile(source, restored)
        os.chmod(restored, 0o600)
        receipt['copied_bytes'] = restored.stat().st_size
        try:
            with closing(sqlite3.connect(restored.as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('integrity')
        except sqlite3.DatabaseError:
            # Truncated or foreign bytes are a failed backup, not an unknown drill outcome.
            raise ValueError('integrity') from None
        receipt['checks'].append('integrity_ok')
        if time.monotonic() - started > timeout_seconds: raise ValueError('time_limit')
        # Open the domain service against the restored copy only, then stop its workers.
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from service import Commerce
        app = Commerce(Path(work))
        try:
            for stop in ('autonomy', 'agent_runtime', 'extensions', 'capabilities'):
                owner = getattr(app, stop, None)
                if owner is not None and hasattr(owner, 'stop'): owner.stop()
            receipt['service_started'] = True
            for name, args in (('commerce_runtime_status', {}), ('commerce_operating_loop_get', {}),
                               ('commerce_operating_health_get', {}), ('commerce_task_list', {})):
                if time.monotonic() - started > timeout_seconds: raise ValueError('time_limit')
                value = app.invoke(name, args, 'local')
                receipt['restored_reads'][name] = isinstance(value, dict) and value.get('schema') or 'ok'
            receipt['checks'].append('service_reads_ok')
            restored_counts = _counts(restored)
        finally:
            for stop in ('autonomy', 'agent_runtime', 'extensions'):
                owner = getattr(app, stop, None)
                if owner is not None and hasattr(owner, 'stop'): owner.stop()
        receipt['row_counts_match'] = {name: live.get(name) == count for name, count in restored_counts.items()}
        # The backup may predate recent live writes, so a lower count is expected; a higher one is not.
        if any((restored_counts.get(name) or 0) > (live.get(name) or 0) for name in restored_counts):
            raise ValueError('restored_exceeds_live')
        receipt.update(status='passed', seconds=round(time.monotonic() - started, 3))
        return receipt
    except Exception as error:
        code = str(error)
        receipt.update(status='failed', code=code if re.fullmatch('[a-z_]{3,60}', code) else 'restore_drill_failed',
                       seconds=round(time.monotonic() - started, 3))
        return receipt
    finally:
        if work: shutil.rmtree(work, ignore_errors=True)
