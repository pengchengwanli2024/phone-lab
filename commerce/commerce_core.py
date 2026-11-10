"""Durable, shared offline task core. No marketplace side effects."""
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import uuid

PLATFORMS = ('ozon','tiktok','amazon','mercado','temu')


class Core:
    def __init__(self,db_path):
        self.path=str(db_path)
        Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL)')

    @contextmanager
    def db(self):
        connection=sqlite3.connect(self.path,timeout=20)
        try:
            with connection: yield connection
        finally: connection.close()

    @staticmethod
    def present(row):
        if row is None: raise ValueError('task_not_found')
        return dict(json.loads(row[2]),id=row[0],status=row[3])

    def invoke(self,name,args):
        if not isinstance(args,dict):raise ValueError('invalid_arguments')
        if name=='commerce_status':return {'platforms':list(PLATFORMS),'mode':'unconfigured'}
        if name not in ('commerce_task_create','commerce_task_list','commerce_task_get','commerce_task_cancel'):raise ValueError('unknown_tool')
        if name=='commerce_task_create':
            key=args.get('idempotency_key');kind=args.get('kind');data=args.get('input',{})
            if not isinstance(key,str) or not key.strip() or len(key)>160 or not isinstance(kind,str) or kind not in ('analysis','draft','report') or not isinstance(data,dict):raise ValueError('invalid_task')
            try:payload=json.dumps(dict(kind=kind,input=data),sort_keys=True,ensure_ascii=False,allow_nan=False)
            except (ValueError,TypeError):raise ValueError('invalid_input')
            if len(payload)>20000:raise ValueError('input_too_large')
            with self.db() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute('SELECT * FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
                if row is not None:
                    if row[2]!=payload:raise ValueError('idempotency_conflict')
                    return self.present(row)
                row=(str(uuid.uuid4()),key,payload,'queued')
                c.execute('INSERT INTO tasks VALUES (?,?,?,?)',row)
                return self.present(row)
        with self.db() as c:
            if name=='commerce_task_list':
                return {'tasks':[self.present(r)for r in c.execute('SELECT * FROM tasks ORDER BY rowid DESC LIMIT 100')]}
            tid=args.get('task_id')
            if not isinstance(tid,str) or not tid:raise ValueError('invalid_task_id')
            if name=='commerce_task_cancel':c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            task=self.present(row)
            if name=='commerce_task_cancel':
                c.execute("UPDATE tasks SET status='cancelled' WHERE id=?",(tid,));task['status']='cancelled'
            return task
