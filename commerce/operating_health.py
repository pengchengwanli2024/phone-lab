"""One read-only answer to "is the platform able to keep running unattended?".

Checks are local facts only: worker heartbeat, background faults, work nobody
will pick up, unconfirmed results, snapshot freshness, backup age and disk
space. A green result is not business acceptance. The optional daily database
backup is off until explicitly enabled and only ever deletes backups it made.
"""
from contextlib import closing
import os
import re
import shutil
import sqlite3
import threading
import time

READ_ONLY = {'commerce_operating_health_get'}
ORDER = {'ok': 0, 'unknown': 1, 'warning': 2, 'critical': 3}
AUTO = re.compile(r'auto-commerce-\d{10,20}\.sqlite')
ANY = re.compile(r'(auto-)?commerce-\d{10,20}\.sqlite')
KEEP, DAY = 7, 86400
FAULTS = {'media_error': '媒体制作', 'extension_error': '扩展与定时计划', 'team_error': '团队触发器',
          'engineering_error': '工程任务调度', 'operating_loop_error': '经营回路检查'}


def definitions(schema, string):
    return [
        ('commerce_operating_health_get', '读取无人值守运行的本机健康检查：心跳、后台故障、无主任务、未知结果、快照时效、备份与磁盘；不代表经营验收', schema()),
        ('commerce_operating_health_configure', '启停每日本机数据库自动备份；只保留并清理自己生成的最近7份，不含凭据、素材与知识',
         schema({'auto_backup': {'type': 'boolean'}}, ['auto_backup'])),
    ]


class OperatingHealth:
    def __init__(self, service):
        self.service, self.core, self.state = service, service.core, service.state
        self._lock = threading.Lock();self._thread = None
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS operating_health_settings (id INTEGER PRIMARY KEY, auto_backup INTEGER NOT NULL, '
                       'last_backup REAL, last_error TEXT)')
            db.execute('INSERT OR IGNORE INTO operating_health_settings VALUES (1,0,NULL,NULL)')

    def invoke(self, name, args):
        if name == 'commerce_operating_health_get': return self.get(**args)
        if name == 'commerce_operating_health_configure': return self.configure(**args)
        raise ValueError('unknown_tool')

    def _settings(self):
        with self.core.db() as db:
            row = db.execute('SELECT auto_backup,last_backup,last_error FROM operating_health_settings WHERE id=1').fetchone()
        return {'auto_backup': bool(row[0]), 'last_backup': row[1], 'last_error': row[2]}

    def configure(self, auto_backup):
        if type(auto_backup) is not bool: raise ValueError('operating_health_invalid_setting')
        with self.core.db() as db:
            db.execute('UPDATE operating_health_settings SET auto_backup=? WHERE id=1', (int(auto_backup),))
        return self.get()

    # ---- backup -------------------------------------------------------
    def _folder(self):
        return self.state / 'backups'

    def _backups(self, pattern=ANY):
        folder = self._folder()
        if not folder.is_dir() or folder.is_symlink(): return []
        rows = [p for p in folder.iterdir() if pattern.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
        return sorted(rows, key=lambda p: p.stat().st_mtime, reverse=True)

    def backup_now(self, at=None):
        """Online copy with integrity check. Database only."""
        at = time.time() if at is None else at
        folder = self._folder();folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if folder.is_symlink(): raise ValueError('operating_health_backup_folder_invalid')
        path = folder / ('auto-commerce-' + str(time.time_ns()) + '.sqlite')
        error = None
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600);os.close(fd)
            with closing(sqlite3.connect((self.state / 'commerce.sqlite').as_uri() + '?mode=ro', uri=True)) as current, closing(sqlite3.connect(path)) as copy:
                current.backup(copy)
                if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('integrity')
            # Retention touches only files this method created.
            for old in self._backups(AUTO)[KEEP:]:
                old.unlink()
        except (OSError, sqlite3.Error, ValueError):
            error = 'operating_health_backup_failed'
            try: path.unlink()
            except OSError: pass
        with self.core.db() as db:
            if error: db.execute('UPDATE operating_health_settings SET last_error=? WHERE id=1', (error,))
            else: db.execute('UPDATE operating_health_settings SET last_backup=?,last_error=NULL WHERE id=1', (at,))
        return {'status': 'failed' if error else 'backed_up', 'error': error, 'scope': 'database_only'}

    def tick(self, at=None):
        at = time.time() if at is None else at
        settings = self._settings()
        if not settings['auto_backup'] or (settings['last_backup'] or 0) + DAY > at: return
        with self._lock:
            if self._thread and self._thread.is_alive(): return
            self._thread = threading.Thread(target=self.backup_now, name='commerce-auto-backup', daemon=True)
            self._thread.start()

    # ---- checks -------------------------------------------------------
    def get(self, at=None):
        at = time.time() if at is None else at
        checks = []
        def add(ident, status, label, detail, target='connections'):
            checks.append({'id': ident, 'status': status, 'label': label, 'detail': detail, 'target': target})
        with self.core.db() as db:
            clock = db.execute("SELECT expires FROM runtime_leases WHERE id='clock'").fetchone()
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # Count through the attention projection so a checked-and-closed outcome is settled,
        # while the same request ending differently counts again. An unreadable source is unknown.
        try:
            rows, errors = self.service.attention._collect(include_followups=False)
            unconfirmed = None if errors else len({row['source_id'] for row in rows if row['source'] == 'agent' and row.get('status') in ('unknown', 'interrupted')})
        except (ValueError, KeyError, TypeError, sqlite3.Error):
            unconfirmed = None
        alive = bool(clock and clock[0] > at)
        add('worker', 'ok' if alive else 'critical', '后台工作器', '正在运行' if alive else '没有在运行，排队任务和定时计划不会被处理')
        faults = [label for key, label in FAULTS.items() if self.service.capability_lifecycle.status().get(key)]
        add('background', 'critical' if faults else 'ok', '后台周期任务', ('正在失败：' + '、'.join(faults)) if faults else '没有报错')
        parked = self.service.task_dispatch.get()['unassigned']
        add('unassigned', 'warning' if parked else 'ok', '排队任务', f'{parked} 条已登记但没有执行者，需要明确执行或取消' if parked else '没有无主任务', 'tasks')
        if unconfirmed is None: add('unconfirmed', 'unknown', '模型请求', '未读全待核对事项', 'tasks')
        else: add('unconfirmed', 'warning' if unconfirmed else 'ok', '模型请求', f'{unconfirmed} 条结果未知或已中断，需要核对原请求' if unconfirmed else '没有未确认的结果', 'tasks')
        try:
            live = self.service.live.status()
            if not live['configured']:
                add('snapshots', 'unknown', '店铺快照', '尚未接入店铺', 'platforms')
            else:
                stale = [name for key, name in (('orders', '订单'), ('stock', '库存'), ('sales', '销量')) if not live[key]['fresh']]
                add('snapshots', 'warning' if stale else 'ok', '店铺快照', ('已过期或缺失：' + '、'.join(stale)) if stale else '订单、库存、销量均在有效期内', 'platforms')
        except (ValueError, KeyError, OSError):
            add('snapshots', 'unknown', '店铺快照', '未读到连接状态', 'platforms')
        settings = self._settings();backups = self._backups()
        age = at - backups[0].stat().st_mtime if backups else None
        if settings['last_error']: add('backup', 'warning', '数据库备份', '最近一次自动备份失败')
        elif age is None: add('backup', 'warning', '数据库备份', '还没有备份')
        elif age > 2 * DAY: add('backup', 'warning', '数据库备份', f'最近一份在 {int(age // DAY)} 天前；自动备份{"已开启" if settings["auto_backup"] else "未开启"}')
        else: add('backup', 'ok', '数据库备份', '最近一份在 2 天内；仅含数据库，不含凭据、素材与知识')
        try:
            free = shutil.disk_usage(self.state).free
            add('disk', 'critical' if free < 1024 ** 3 else 'warning' if free < 5 * 1024 ** 3 else 'ok', '磁盘空间',
                f'剩余约 {free // 1024 ** 3} GB')
        except OSError:
            add('disk', 'unknown', '磁盘空间', '未读到')
        worst = max((c['status'] for c in checks), key=ORDER.get)
        return {'schema': 'commerce-operating-health-v1', 'status': worst, 'checks': checks, 'checked_at': at,
                'auto_backup': settings['auto_backup'], 'auto_backup_count': len(self._backups(AUTO)),
                'availability': 'local_user_session_awake_only', 'business_acceptance': False}
