"""Shared host spacing/backoff for public crawler requests; durable across clients."""
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit
from setup import STATE
from contextlib import contextmanager


@contextmanager
def connection(path=None):
    path=Path(path or STATE/'host-rate.sqlite');path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    db=sqlite3.connect(path,timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS hosts (host TEXT PRIMARY KEY, next_at REAL, failures INTEGER)')
    try:
        with db:yield db
    finally:db.close()


def reserve(url, path=None, now=None):
    host=urlsplit(url).hostname
    if host in ('127.0.0.1','localhost','::1'):return 0
    now=time.time() if now is None else now
    with connection(path) as db:
        db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT next_at FROM hosts WHERE host=?',(host,)).fetchone()
        wait=max(0,(row[0] if row else 0)-now)
        if not wait:
            db.execute('INSERT INTO hosts VALUES (?,?,0) ON CONFLICT(host) DO UPDATE SET next_at=excluded.next_at',(host,now+2))
        return wait


def outcome(url, failed, path=None, now=None):
    host=urlsplit(url).hostname
    if host in ('127.0.0.1','localhost','::1'):return
    now=time.time() if now is None else now
    with connection(path) as db:
        db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT next_at,failures FROM hosts WHERE host=?',(host,)).fetchone()
        failures=min(6,(row[1] if row else 0)+1) if failed else 0
        due=max(row[0] if row else 0,now+min(300,10*2**(failures-1))) if failed else max(row[0] if row else 0,now)
        db.execute('INSERT OR REPLACE INTO hosts VALUES (?,?,?)',(host,due,failures))


def wait_for(url, deadline, cancelled=None):
    while True:
        if cancelled and cancelled():raise ValueError('collection_cancelled')
        wait=reserve(url)
        if not wait:return
        if wait>30 or time.monotonic()+wait>=deadline:raise ValueError('crawler_host_backoff')
        time.sleep(min(.1,wait))
