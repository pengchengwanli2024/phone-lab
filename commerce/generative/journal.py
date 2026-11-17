"""Bounded append-only presentation deltas in the original Commerce SQLite DB."""
import json
import time

class Journal:
    def __init__(self,core):
        self.core=core
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS agent_ui_events(run_id TEXT,seq INTEGER,event TEXT,created REAL,PRIMARY KEY(run_id,seq))')

    def append(self,run_id,event):
        if type(event)is not dict or event.get('type') not in ('reset','answer_delta','component','settled'):raise ValueError('agent_ui_invalid_event')
        encoded=json.dumps(event,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            last=db.execute('SELECT seq,event FROM agent_ui_events WHERE run_id=? ORDER BY seq DESC LIMIT 1',(run_id,)).fetchone()
            seq=last[0]+1 if last else 1
            previous=json.loads(last[1])['type'] if last else None
            if previous=='settled' or seq>512:return
            if event['type']!='settled':
                if previous=='limit':return
                used=db.execute('SELECT COALESCE(SUM(length(CAST(event AS BLOB))),0) FROM agent_ui_events WHERE run_id=?',(run_id,)).fetchone()[0]
                # Optional preview must never abort an otherwise valid answer.
                # Reserve space for a visible limit and authoritative settlement.
                if seq>=511 or len(encoded.encode())>65536 or used+len(encoded.encode())>2*1024*1024:
                    encoded=json.dumps({'type':'limit','reason':'preview_budget','final_result_available_after_completion':True})
            db.execute('INSERT INTO agent_ui_events VALUES(?,?,?,?)',(run_id,seq,encoded,time.time()))

    @staticmethod
    def fold(rows):
        snapshot={'answer':'','components':[],'provisional':True,'mode':'pending','cursor':0,'truncated':False}
        for seq,raw in rows:
            event=json.loads(raw);kind=event['type'];snapshot['cursor']=seq
            if kind=='reset':snapshot.update(answer='',components=[],provisional=True,mode=event['mode'])
            elif kind=='answer_delta':snapshot['answer']=(snapshot['answer']+event['delta'])[:5000]
            elif kind=='component':snapshot['components'].append(event.get('component',event['selection']))
            elif kind=='limit':snapshot['truncated']=True
            elif kind=='settled':snapshot.update(answer='',components=[],provisional=False,status=event['status'])
        return snapshot

    def snapshot(self,run_id,db=None):
        if db is not None:return self.fold(db.execute('SELECT seq,event FROM agent_ui_events WHERE run_id=? ORDER BY seq',(run_id,)).fetchall())
        with self.core.db() as db:return self.snapshot(run_id,db)

    def read(self,db,run_id,after=0,limit=100):
        if type(after)is not int or after<0 or type(limit)is not int or not 1<=limit<=100:raise ValueError('copilot_invalid_stream_cursor')
        rows=db.execute('SELECT seq,event FROM agent_ui_events WHERE run_id=? ORDER BY seq',(run_id,)).fetchall()
        if after>(rows[-1][0] if rows else 0):raise ValueError('copilot_invalid_stream_cursor')
        selected=[(seq,raw) for seq,raw in rows if seq>after][:limit]
        cursor=selected[-1][0] if selected else after
        return {'run_id':run_id,'events':[{'seq':seq,**json.loads(raw)} for seq,raw in selected],
                'cursor':cursor,'has_more':bool(rows and cursor<rows[-1][0]),'snapshot':self.fold(rows),
                'recovery':'read_original_run_only','automatic_resubmit':False}
