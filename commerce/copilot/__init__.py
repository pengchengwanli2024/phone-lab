"""Shared local dialogue; only explicit sends enqueue the existing bounded runner."""
import hashlib
import json
import re
import threading
import time
import uuid
from agent_runtime import sha
from agent_runtime.policy import canonical
from .context import validate_context, route, CONTEXT_SCHEMA

ACTIVE=('queued','running','cancel_requested')
# Serializes scope changes and review across instances in this process. DB transactions
# additionally serialize writers across processes; apply holds that scope transaction.
LOCK=threading.RLock()


def definitions(schema,string):
    tid={'thread_id':string}; review={**tid,'run_id':string,'proposal_id':string,'result_sha256':string,'context_sha256':string}
    return [
      ('commerce_copilot_open','打开共享业务对话；不会请求模型',schema({'title':string,'context':CONTEXT_SCHEMA,'idempotency_key':string},['context','idempotency_key'])),
      ('commerce_copilot_list','读取最近共享业务对话；不包含宿主聊天记录',schema()),
      ('commerce_copilot_get','读取业务对话及同一模型运行结果；不会重发模型',schema({**tid,'before':string},['thread_id'])),
      ('commerce_copilot_send','明确发送业务问题到现有有界模型队列',schema({**tid,'message':{'type':'string','minLength':1,'maxLength':2000},'context_sha256':string,'idempotency_key':string},['thread_id','message','context_sha256','idempotency_key'])),
      ('commerce_copilot_context','显式更新对话业务范围；旧范围建议失效',schema({**tid,'context':CONTEXT_SCHEMA,'expected_context_sha256':string},['thread_id','context','expected_context_sha256'])),
      ('commerce_copilot_cancel','取消本对话的一次排队或运行请求',schema({**tid,'run_id':string},['thread_id','run_id'])),
      ('commerce_copilot_apply','按范围及结果哈希审阅单条本地建议；不执行店铺写操作',schema(review,list(review))),
    ]


class Copilot:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.runtime=service.agent_runtime
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS copilot_threads(id TEXT PRIMARY KEY,idem TEXT UNIQUE,request TEXT,title TEXT,context TEXT,context_sha TEXT,revision INTEGER,created REAL,updated REAL,approving TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS copilot_turns(id TEXT PRIMARY KEY,thread_id TEXT,idem TEXT,request TEXT,question TEXT,run_id TEXT UNIQUE,context_sha TEXT,revision INTEGER,created REAL,UNIQUE(thread_id,idem))')
            db.execute('CREATE INDEX IF NOT EXISTS copilot_thread_turns ON copilot_turns(thread_id)')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS copilot_a2a_message ON copilot_turns(idem) WHERE idem LIKE 'a2a:%'")

    def invoke(self,name,args):
        from inspect import signature
        methods={'open':self.open,'list':self.list,'get':self.get,'send':self.send,'context':self.context,'cancel':self.cancel,'apply':self.apply}
        fn=methods.get(name.removeprefix('commerce_copilot_')) if name.startswith('commerce_copilot_') else None
        if not fn:raise ValueError('unknown_tool')
        if not isinstance(args,dict) or set(args)-set(signature(fn).parameters):raise ValueError('copilot_invalid_arguments')
        try:signature(fn).bind(**args)
        except TypeError:raise ValueError('copilot_invalid_arguments') from None
        return fn(**args)

    @staticmethod
    def key(value):
        if not isinstance(value,str) or not value.strip() or len(value)>160:raise ValueError('invalid_idempotency_key')
        return value

    def _thread(self,db,thread_id):
        row=db.execute('SELECT id,title,context,context_sha,revision,created,updated FROM copilot_threads WHERE id=?',(thread_id,)).fetchone()
        if not row:raise ValueError('copilot_thread_not_found')
        return dict(id=row[0],title=row[1],context=json.loads(row[2]),context_sha256=row[3],revision=row[4],created=row[5],updated=row[6])

    def get(self,thread_id,before=None):
        return self._get(thread_id,before=before)

    def _get(self,thread_id,before=None,include_turn=None):
        with self.core.db() as db:
            thread=self._thread(db,thread_id)
            boundary='';values=[thread_id]
            if before is not None or include_turn is not None:
                cursor=before if before is not None else include_turn
                if not isinstance(cursor,str) or not re.fullmatch('[a-f0-9]{32}',cursor):raise ValueError('copilot_invalid_cursor')
                row=db.execute('SELECT rowid FROM copilot_turns WHERE thread_id=? AND id=?',(thread_id,cursor)).fetchone()
                if not row:raise ValueError('copilot_invalid_cursor')
                boundary=' AND rowid'+('<' if before is not None else '<=')+'?';values.append(row[0])
            rows=db.execute('SELECT id,question,run_id,context_sha,revision,idem,rowid FROM copilot_turns WHERE thread_id=?'+boundary+' ORDER BY rowid DESC LIMIT 40',values).fetchall()
            rows.reverse()
            thread['turns']=[dict(id=r[0],question=r[1],run=self.runtime._get(r[2],_db=db),context_sha256=r[3],context_revision=r[4],idempotency_key=r[5]) for r in rows]
            thread['total_turns']=db.execute('SELECT count(*) FROM copilot_turns WHERE thread_id=?',(thread_id,)).fetchone()[0]
            thread['has_more']=bool(rows and db.execute('SELECT 1 FROM copilot_turns WHERE thread_id=? AND rowid<? LIMIT 1',(thread_id,rows[0][6])).fetchone())
            thread['next_cursor']=rows[0][0] if thread['has_more'] else None
            latest=db.execute('SELECT run_id FROM copilot_turns WHERE thread_id=? ORDER BY rowid DESC LIMIT 1',(thread_id,)).fetchone()
            thread['latest_run']=self.runtime._get(latest[0],_db=db) if latest else None
        from .methods import method_for
        thread['method']=method_for(thread['context'])
        thread['memory']={'model_history_max_turns':6,'model_history_max_bytes':32000,'full_history':'persistent_paginated'}
        from protocols.a2ui import surface
        thread['surfaces']=surface(thread['latest_run'],thread['context']) if thread['latest_run'] else []
        return thread

    def list(self):
        with self.core.db() as db:
            rows=db.execute('SELECT id,title,context,context_sha,updated FROM copilot_threads ORDER BY updated DESC LIMIT 50').fetchall()
        return {'threads':[dict(id=r[0],title=r[1],context=json.loads(r[2]),context_sha256=r[3],updated=r[4]) for r in rows]}

    def open(self,context,idempotency_key,title=None):
        context=validate_context(context);self.key(idempotency_key)
        if title is not None and (not isinstance(title,str) or not title.strip() or len(title)>160):raise ValueError('copilot_invalid_title')
        request=canonical({'context':context,'title':title});ident=uuid.uuid4().hex;at=time.time()
        with LOCK,self.core.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT id,request FROM copilot_threads WHERE idem=?',(idempotency_key,)).fetchone()
            if old:
                if old[1]!=request:raise ValueError('idempotency_conflict')
                ident=old[0]
            else:db.execute('INSERT INTO copilot_threads VALUES(?,?,?,?,?,?,?,?,?,NULL)',(ident,idempotency_key,request,title or '业务助手',canonical(context),sha(context),1,at,at))
        return self.get(ident)

    def send(self,thread_id,message,context_sha256,idempotency_key):
        self.key(idempotency_key)
        if not isinstance(message,str) or not message.strip() or len(message)>2000:raise ValueError('copilot_invalid_message')
        request=canonical({'message':message.strip(),'context_sha256':context_sha256})
        with LOCK,self.core.db() as db:
            db.execute('BEGIN IMMEDIATE');thread=self._thread(db,thread_id)
            if idempotency_key.startswith('a2a:'):
                owner=db.execute('SELECT thread_id FROM copilot_turns WHERE idem=?',(idempotency_key,)).fetchone()
                if owner and owner[0]!=thread_id:raise ValueError('idempotency_conflict')
            old=db.execute('SELECT request,id FROM copilot_turns WHERE thread_id=? AND idem=?',(thread_id,idempotency_key)).fetchone()
            if old:
                if old[0]!=request:raise ValueError('idempotency_conflict')
            else:
                if thread['context_sha256']!=context_sha256:raise ValueError('copilot_context_changed')
                self._idle(db,thread_id)
                topic,parameters=route(thread['context'])
                previous=db.execute("SELECT t.run_id FROM copilot_turns t JOIN agent_runs r ON r.id=t.run_id WHERE t.thread_id=? AND t.revision=? AND r.status IN ('completed','awaiting_input','awaiting_review') ORDER BY t.rowid DESC LIMIT 1",(thread_id,thread['revision'])).fetchone()
                parent=previous[0] if previous else None
                ident=uuid.uuid4().hex;at=time.time()
                history_rows=db.execute("SELECT t.question,r.result,r.id FROM copilot_turns t JOIN agent_runs r ON r.id=t.run_id WHERE t.thread_id=? AND t.revision=? AND r.status IN ('completed','awaiting_input','awaiting_review') ORDER BY t.rowid DESC LIMIT 6",(thread_id,thread['revision'])).fetchall()
                history=[]
                for question,result,run_id in reversed(history_rows):
                    result=json.loads(result) if result else {}
                    history.append({'question':question[:2000],'answer':str(result.get('answer',''))[:5000],'run_id':run_id})
                while len(canonical(history).encode())>32000:history.pop(0)
                run=self.runtime._create(question=message.strip(),role='conductor',topic=topic,parameters=parameters,parent_id=parent,idempotency_key='copilot:'+ident,_db=db,_conversation=history)
                db.execute('INSERT INTO copilot_turns VALUES(?,?,?,?,?,?,?,?,?)',(ident,thread_id,idempotency_key,request,message.strip(),run['id'],context_sha256,thread['revision'],at))
                db.execute('UPDATE copilot_threads SET updated=? WHERE id=?',(at,thread_id))
        return self._get(thread_id,include_turn=old[1] if old else ident)

    def _idle(self,db,thread_id):
        if db.execute('SELECT approving FROM copilot_threads WHERE id=?',(thread_id,)).fetchone()[0]:raise ValueError('copilot_active_review_retry_required')
        if db.execute("SELECT 1 FROM copilot_turns t JOIN agent_runs r ON r.id=t.run_id WHERE t.thread_id=? AND r.status IN ('queued','running','cancel_requested')",(thread_id,)).fetchone():raise ValueError('copilot_active_run')

    def context(self,thread_id,context,expected_context_sha256):
        context=validate_context(context)
        with LOCK,self.core.db() as db:
            db.execute('BEGIN IMMEDIATE');thread=self._thread(db,thread_id)
            if thread['context_sha256']!=expected_context_sha256:raise ValueError('copilot_context_changed')
            self._idle(db,thread_id)
            if thread['context']!=context:db.execute('UPDATE copilot_threads SET context=?,context_sha=?,revision=revision+1,updated=? WHERE id=?',(canonical(context),sha(context),time.time(),thread_id))
        return self.get(thread_id)

    def _member(self,db,thread_id,run_id):
        self._thread(db,thread_id)
        row=db.execute('SELECT context_sha,revision FROM copilot_turns WHERE thread_id=? AND run_id=?',(thread_id,run_id)).fetchone()
        if not row:raise ValueError('copilot_run_not_in_thread')
        return row

    def cancel(self,thread_id,run_id):
        with LOCK,self.core.db() as db:self._member(db,thread_id,run_id)
        self.runtime.cancel(run_id)
        return self.get(thread_id)

    def lookup_message(self,idempotency_key):
        with self.core.db() as db:row=db.execute('SELECT thread_id,id FROM copilot_turns WHERE idem=? ORDER BY rowid LIMIT 1',(idempotency_key,)).fetchone()
        return self._get(row[0],include_turn=row[1]) if row else None

    def lookup_run(self,run_id):
        with self.core.db() as db:row=db.execute('SELECT thread_id,id FROM copilot_turns WHERE run_id=?',(run_id,)).fetchone()
        if not row:raise ValueError('copilot_run_not_in_thread')
        return self._get(row[0],include_turn=row[1])

    def apply(self,thread_id,run_id,proposal_id,result_sha256,context_sha256):
        approval=run_id+':'+proposal_id
        with LOCK:
            with self.core.db() as db:
                db.execute('BEGIN IMMEDIATE');thread=self._thread(db,thread_id);binding=self._member(db,thread_id,run_id)
                if context_sha256!=thread['context_sha256'] or tuple(binding)!=(context_sha256,thread['revision']):raise ValueError('copilot_context_changed')
                current=db.execute('SELECT approving FROM copilot_threads WHERE id=?',(thread_id,)).fetchone()[0]
                if current and current!=approval:raise ValueError('copilot_active_review_retry_required')
                # Durable marker prevents a second process changing context during task
                # writes. A crashed approval can be explicitly retried by the same key.
                db.execute('UPDATE copilot_threads SET approving=? WHERE id=?',(approval,thread_id))
            try:return self.runtime.apply(run_id,proposal_id,result_sha256)
            finally:
                with self.core.db() as db:db.execute('UPDATE copilot_threads SET approving=NULL WHERE id=? AND approving=?',(thread_id,approval))
