"""Read existing conversation/run archives; no second task or memory store."""
import json
from .context import MODULES
from .capabilities import LABELS

ACTIVE=('queued','running','cancel_requested')
ATTENTION=('awaiting_input','awaiting_review','failed','unknown','interrupted')


def definitions(schema,string):
    return [('commerce_copilot_activity','按状态、范围或历史正文检索原助手任务；读取不重发或取消',schema({'query':{'type':'string','maxLength':100},'status':{'type':'string','enum':['all','active','attention','completed']},'module':{'type':'string','enum':list(MODULES)},'demo':{'type':'boolean'},'offset':{'type':'integer','minimum':0,'maximum':10000},'limit':{'type':'integer','minimum':1,'maximum':30}}))]


class CopilotActivity:
    def __init__(self,copilot):self.copilot=copilot;self.service=copilot.service;self.core=copilot.core

    def list(self,query='',status='all',module=None,demo=None,offset=0,limit=20):
        if not isinstance(query,str) or len(query)>100 or any(ord(c)<32 for c in query) or status not in ('all','active','attention','completed') or module is not None and module not in MODULES or demo is not None and type(demo) is not bool or type(offset) is not int or not 0<=offset<=10000 or type(limit) is not int or not 1<=limit<=30:
            raise ValueError('copilot_invalid_activity_query')
        clauses=[];args=[]
        if query.strip():
            # Parameterized literal substring matching keeps %/_ and quotes inert.
            clauses.append("(instr(lower(c.title),lower(?))>0 OR EXISTS(SELECT 1 FROM copilot_turns h LEFT JOIN agent_runs a ON a.id=h.run_id WHERE h.thread_id=c.id AND (instr(lower(h.question),lower(?))>0 OR instr(lower(COALESCE(json_extract(a.result,'$.answer'),'')),lower(?))>0)))")
            args.extend([query.strip()]*3)
        if module is not None:clauses.append("json_extract(c.context,'$.module')=?");args.append(module)
        if demo is not None:clauses.append("COALESCE(json_extract(c.context,'$.demo'),0)=?");args.append(int(demo))
        where=' AND '+' AND '.join(clauses) if clauses else ''
        with self.core.db() as db:
            records=db.execute('''SELECT c.id,c.title,c.context,t.id,t.run_id,t.question,r.status,r.created,r.updated,
                (SELECT count(*) FROM copilot_turns h WHERE h.thread_id=c.id)
                FROM copilot_threads c JOIN copilot_turns t ON t.thread_id=c.id JOIN agent_runs r ON r.id=t.run_id
                WHERE t.rowid=(SELECT max(h.rowid) FROM copilot_turns h WHERE h.thread_id=c.id)'''+where+' ORDER BY r.updated DESC,c.id',args).fetchall()
            items=[]
            for row in records:
                state=row[6];run_id=row[4];updated=row[8]
                job=self.service.market_research.for_run(run_id,db)
                if job:
                    state={'partial':'awaiting_review','cancelling':'cancel_requested'}.get(job['status'],job['status'])
                    effective=db.execute('SELECT updated FROM agent_runs WHERE id=?',(job['run_id'],)).fetchone()
                    run_id=job['run_id'];updated=effective[0] if effective else updated
                if status=='active' and state not in ACTIVE or status=='attention' and state not in ATTENTION or status=='completed' and state!='completed':continue
                context=json.loads(row[2]);safe={k:v for k,v in context.items() if k in ('module','demo','platform','store_id','market','entity')}
                items.append(dict(module_label=LABELS.get(context['module'],context['module']),thread_id=row[0],title=row[1],context=safe,turn_id=row[3],run_id=run_id,question=row[5][:240],status=state,created=row[7],updated=updated,total_turns=row[9]))
        items.sort(key=lambda item:(item['updated'],item['thread_id']),reverse=True)
        return dict(items=items[offset:offset+limit],total=len(items),offset=offset,next_offset=offset+limit if offset+limit<len(items) else None,persistence='existing_copilot_threads_and_agent_runs',read_only=True)

    def invoke(self,name,args):
        if name!='commerce_copilot_activity':raise ValueError('unknown_tool')
        from inspect import signature
        if not isinstance(args,dict):raise ValueError('copilot_invalid_arguments')
        try:signature(self.list).bind(**args)
        except TypeError:raise ValueError('copilot_invalid_arguments') from None
        return self.list(**args)
