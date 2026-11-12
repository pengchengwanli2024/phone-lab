"""Explicit private form checkpoints, separate from business evidence and approvals."""
import hashlib
import json
import re
import time


def definitions(schema):
    fields={'scope':{'type':'object'}}
    return [('commerce_form_draft_get','读取当前表单范围的私有输入草稿；不执行计算、模型或交付',schema(fields,['scope'])),
            ('commerce_form_draft_save','显式保存私有表单输入；按版本防止并发覆盖，不改变业务证据或审阅',schema({**fields,'payload':{'type':'object'},'expected_revision':{'type':'integer','minimum':0}},['scope','payload','expected_revision']))]


class FormDrafts:
    def __init__(self,core):
        self.core=core
        with core.db() as db:db.execute('CREATE TABLE IF NOT EXISTS form_drafts(scope_key TEXT PRIMARY KEY,scope TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,updated REAL NOT NULL)')

    def key(self,scope):
        if not isinstance(scope,dict) or set(scope)!={'module','form','case_id'}:raise ValueError('form_draft_invalid_scope')
        if scope['module'] not in ('research','operations','business_import','business_edit','product_workspace'):raise ValueError('form_draft_invalid_scope')
        if not isinstance(scope['form'],str) or not re.fullmatch('[a-z0-9_-]{1,50}',scope['form']):raise ValueError('form_draft_invalid_scope')
        if not isinstance(scope['case_id'],str) or not re.fullmatch('[a-zA-Z0-9_-]{0,160}',scope['case_id']):raise ValueError('form_draft_invalid_scope')
        raw=json.dumps(scope,sort_keys=True,separators=(',',':'));return hashlib.sha256(raw.encode()).hexdigest(),raw

    def get(self,scope):
        key,_=self.key(scope)
        with self.core.db() as db:row=db.execute('SELECT revision,payload,updated FROM form_drafts WHERE scope_key=?',(key,)).fetchone()
        return {'scope':scope,'revision':row[0] if row else 0,'payload':json.loads(row[1]) if row else None,'saved_at':row[2] if row else None,'business_submission':False}

    def save(self,scope,payload,expected_revision):
        key,raw_scope=self.key(scope)
        if type(expected_revision) is not int or expected_revision<0 or not isinstance(payload,dict):raise ValueError('form_draft_invalid_input')
        def walk(value,depth=0):
            if depth>20:raise ValueError('form_draft_invalid_input')
            if isinstance(value,dict):
                if any(not isinstance(k,str) or k in ('__proto__','constructor','prototype') for k in value):raise ValueError('form_draft_invalid_input')
                for v in value.values():walk(v,depth+1)
            elif isinstance(value,list):
                for v in value:walk(v,depth+1)
            elif value is not None and type(value) not in (str,int,float,bool):raise ValueError('form_draft_invalid_input')
        walk(payload)
        try:raw=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        except (ValueError,TypeError):raise ValueError('form_draft_invalid_input') from None
        if len(raw.encode())>100000:raise ValueError('form_draft_too_large')
        with self.core.db() as db:
            if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision FROM form_drafts WHERE scope_key=?',(key,)).fetchone();revision=row[0] if row else 0
            if revision!=expected_revision:raise ValueError('form_draft_conflict')
            if not row and db.execute('SELECT count(*) FROM form_drafts').fetchone()[0]>=256:raise ValueError('form_draft_capacity_reached')
            saved_at=time.time()
            db.execute('INSERT INTO form_drafts VALUES (?,?,?,?,?) ON CONFLICT(scope_key) DO UPDATE SET revision=excluded.revision,payload=excluded.payload,updated=excluded.updated',(key,raw_scope,revision+1,raw,saved_at))
        return {'scope':json.loads(raw_scope),'revision':revision+1,'payload':json.loads(raw),'saved_at':saved_at,'business_submission':False}

    def invoke(self,name,args):
        if isinstance(args.get('scope'),dict) and args['scope'].get('module')=='product_workspace':
            raise ValueError('workspace_scope_requires_guard')
        if name=='commerce_form_draft_get' and set(args)=={'scope'}:return self.get(**args)
        if name=='commerce_form_draft_save' and set(args)=={'scope','payload','expected_revision'}:return self.save(**args)
        raise ValueError('form_draft_invalid_arguments')
