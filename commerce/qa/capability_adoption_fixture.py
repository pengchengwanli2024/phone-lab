"""Explicit isolated acceptance history; no model or store execution."""
import copy,json,os,runpy,sys,time,uuid
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
if not os.environ.get('COMMERCE_STATE')or not os.environ.get('COMMERCE_PORT'):raise SystemExit('Isolated state and port required')
from service import Commerce
from agent_runtime.policy import canonical
original=Commerce.__init__
def init(app,*args,**kwargs):
    original(app,*args,**kwargs)
    thread=app.copilot.open({'module':'overview','demo':True},'synthetic-long-history','合成240轮阅读验收')
    first=app.copilot.send(thread['id'],'合成历史问题 000',thread['context_sha256'],'synthetic-history-0')
    with app.core.atomic()as db:
        row=db.execute('SELECT * FROM agent_runs WHERE id=?',(first['latest_run']['id'],)).fetchone()
        payload=json.loads(row[3]);result=dict(answer='合成历史答复 000 · 原回执仅供隔离验收。',questions=[],evidence_refs=[],proposals=[],observations=[])
        db.execute("UPDATE agent_runs SET status='completed',result=? WHERE id=?",(canonical(result),row[0]))
        for i in range(1,240):
            ident=uuid.uuid4().hex;turn=uuid.uuid4().hex;question=f'合成历史问题 {i:03d}';data={**payload,'question':question};answer={**result,'answer':f'合成历史答复 {i:03d} · 原回执仅供隔离验收。'};now=time.time()+i*.001
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,NULL,NULL,?,?)',(ident,'synthetic-history-run-'+str(i),row[2],canonical(data),'completed',now,now,canonical(answer),'[]'))
            db.execute('INSERT INTO copilot_turns VALUES(?,?,?,?,?,?,?,?,?)',(turn,thread['id'],'synthetic-history-'+str(i),canonical({'message':question}),question,ident,thread['context_sha256'],thread['revision'],now))
    (app.state/'capability-fixture.json').write_text(json.dumps({'thread_id':thread['id'],'synthetic':True,'total_turns':240}))
Commerce.__init__=init
runpy.run_path(str(Path(__file__).with_name('react_workbench_fixture.py')),run_name='__main__')
