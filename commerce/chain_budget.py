"""Conservative durable allowances for existing explicitly requested model chains."""
from contextlib import contextmanager
import json
import re
import time

from agent_runtime.policy import canonical

DEFAULTS={'model_steps':24,'read_steps':32,'model_seconds':900,'max_depth':32,'step_seconds':90}


def definitions(schema,string):
    return [('commerce_chain_budget_get','只读核对同一任务链的本机步骤与耗时额度；Token及费用未知，不恢复执行',schema({'run_id':string},['run_id']))]


class ChainBudget:
    def __init__(self,service):
        self.service,self.core=service,service.core
        self.history_unresolved=False
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS chain_budgets(id TEXT PRIMARY KEY,limits TEXT NOT NULL,created REAL NOT NULL,legacy INTEGER NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS chain_steps(
                chain_id TEXT NOT NULL,run_id TEXT NOT NULL,step TEXT NOT NULL,kind TEXT NOT NULL,
                status TEXT NOT NULL,started REAL NOT NULL,finished REAL,seconds REAL NOT NULL,
                PRIMARY KEY(run_id,step))''')
            db.execute('CREATE INDEX IF NOT EXISTS chain_steps_chain ON chain_steps(chain_id)')
            db.execute('CREATE TABLE IF NOT EXISTS chain_budget_aliases(old_id TEXT PRIMARY KEY,root_id TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS chain_budget_alias_root ON chain_budget_aliases(root_id)')
        # Retain earlier split accounting verbatim. An alias folds its usage
        # into the true ancestor instead of deleting or rewriting old receipts.
        with self.core.atomic() as db:
            memo={}
            for old_id, in db.execute('SELECT id FROM chain_budgets').fetchall():
                try:
                    if old_id.startswith('task:'):
                        first=db.execute('SELECT run_id FROM market_research_runs WHERE task_id=? ORDER BY rowid LIMIT 1',(old_id[5:],)).fetchone()
                        if not first:raise ValueError('agent_chain_history_unavailable')
                        run_id=first[0]
                    elif old_id.startswith('run:'):run_id=old_id[4:]
                    else:raise ValueError('agent_chain_history_unavailable')
                    root,_=self._scope(db,run_id,memo)
                    if root!=old_id:db.execute('INSERT OR REPLACE INTO chain_budget_aliases VALUES(?,?)',(old_id,root))
                except (ValueError,KeyError,TypeError):self.history_unresolved=True

    def settings(self):
        path=self.service.state/'chain-limits.json'
        try:overrides=json.loads(path.read_text()) if path.exists() else {}
        except (OSError,ValueError):raise ValueError('agent_chain_limits_invalid') from None
        if not isinstance(overrides,dict) or set(overrides)-set(DEFAULTS):raise ValueError('agent_chain_limits_invalid')
        value={**DEFAULTS,**overrides}
        if any(type(v) is not int or not 1<=v<=(86400 if k=='model_seconds' else 1000) for k,v in value.items()):raise ValueError('agent_chain_limits_invalid')
        return value

    def _scope(self,db,run_id,memo=None):
        if not isinstance(run_id,str) or not re.fullmatch('[a-f0-9]{32}',run_id):raise ValueError('agent_run_not_found')
        memo={} if memo is None else memo
        visited=set();trail=[];current=run_id
        while current:
            if current in memo:
                key,depth=memo[current];break
            if current in visited or len(visited)>=1000:raise ValueError('agent_chain_invalid_parent')
            visited.add(current)
            research=db.execute('SELECT task_id FROM market_research_runs WHERE run_id=?',(current,)).fetchone()
            if research:
                task_key='task:'+research[0]
                if task_key in memo:
                    key,depth=memo[task_key];memo[current]=(key,depth);break
                first=db.execute('SELECT m.run_id,r.payload FROM market_research_runs m JOIN agent_runs r ON r.id=m.run_id WHERE m.task_id=? ORDER BY m.rowid LIMIT 1',(research[0],)).fetchone()
                if not first:raise ValueError('agent_chain_history_unavailable')
                count=db.execute('SELECT count(*) FROM market_research_runs WHERE task_id=?',(research[0],)).fetchone()[0]
                trail.append(([current,first[0],task_key],count))
                parent=json.loads(first[1]).get('parent_id')
                if not parent:key,depth=task_key,0;break
                current=parent;continue
            row=db.execute('SELECT payload FROM agent_runs WHERE id=?',(current,)).fetchone()
            if not row:raise ValueError('agent_run_not_found')
            payload=json.loads(row[0]);parent=payload.get('parent_id')
            trail.append(([current],1))
            if not parent:key,depth='run:'+current,0;break
            current=parent
        else:raise ValueError('agent_chain_invalid_parent')
        for identifiers,increment in reversed(trail):
            depth+=increment
            for ident in identifiers:memo[ident]=(key,depth)
        return memo[run_id]

    def _state(self,db,run_id,scope=None):
        key,depth=scope if scope is not None else self._scope(db,run_id)
        aliases=[key,*[row[0]for row in db.execute('SELECT old_id FROM chain_budget_aliases WHERE root_id=?',(key,))]]
        placeholders=','.join('?'for _ in aliases)
        records=db.execute('SELECT limits,created,legacy FROM chain_budgets WHERE id IN ('+placeholders+')',aliases).fetchall()
        known=[json.loads(row[0])for row in records]
        limits={name:min(record[name]for record in known)for name in DEFAULTS} if known else self.settings()
        usage={'model_steps':0,'read_steps':0,'model_seconds':0.0};unconfirmed=0
        for kind,status,seconds in db.execute('SELECT kind,status,seconds FROM chain_steps WHERE chain_id IN ('+placeholders+')',aliases):
            usage[kind+'_steps']+=1
            if kind=='model':
                usage['model_seconds']+=seconds
                if status in ('reserved','unknown'):unconfirmed+=1
        return {'chain_id':key,'depth':depth,'limits':limits,'usage':usage,'unconfirmed_steps':unconfirmed,
                'recorded_since':min(row[1]for row in records) if records else None,'historical_usage_unrecorded':any(row[2]for row in records) if records else True,
                'accounting_complete':not self.history_unresolved,
                'token_usage':None,'cost':None,'waiting_time_charged':False}

    def summary(self,run_id,_db=None):
        if _db is not None:return self._state(_db,run_id)
        with self.core.db() as db:
            db.execute('BEGIN');return self._state(db,run_id)

    def summaries(self,db,run_ids):
        memo={};selected={}
        for run_id in sorted(set(run_ids)):
            key,depth=self._scope(db,run_id,memo)
            if key not in selected or depth>selected[key][1]:selected[key]=(run_id,depth)
        return [self._state(db,run_id,(key,depth))for key,(run_id,depth) in sorted(selected.items())]

    def check_child(self,db,parent_id):
        if not parent_id:return
        state=self._state(db,parent_id)
        if state['depth']+1>state['limits']['max_depth']:raise ValueError('agent_chain_depth_exhausted')

    def check_successor(self,db,run_id):
        # A successor may only need a committed receipt and local publication.
        # Charge new inference at dispatch, not at this recoverable queue boundary.
        self.check_child(db,run_id)

    def _reserve(self,run_id,step,kind):
        if self.history_unresolved:raise ValueError('agent_chain_history_unavailable')
        if kind not in ('model','read') or not isinstance(step,str) or not re.fullmatch('[a-z0-9:_-]{1,100}',step):raise ValueError('agent_chain_invalid_step')
        with self.core.atomic() as db:
            row=db.execute('SELECT status,owner,expires FROM agent_runs WHERE id=?',(run_id,)).fetchone()
            if not row or row[0]!='running' or row[1]!=self.service.agent_runtime.owner or row[2]<=time.time():raise ValueError('agent_chain_parent_not_running')
            if db.execute('SELECT 1 FROM chain_steps WHERE run_id=? AND step=?',(run_id,step)).fetchone():raise ValueError('agent_chain_step_already_recorded')
            state=self._state(db,run_id);limits,usage=state['limits'],state['usage']
            if state['depth']>limits['max_depth']:raise ValueError('agent_chain_depth_exhausted')
            if usage[kind+'_steps']>=limits[kind+'_steps']:raise ValueError('agent_chain_budget_exhausted')
            seconds=min(limits['step_seconds'],limits['model_seconds']-usage['model_seconds']) if kind=='model' else 0
            if kind=='model' and seconds<=0:raise ValueError('agent_chain_budget_exhausted')
            if not db.execute('SELECT 1 FROM chain_budgets WHERE id=?',(state['chain_id'],)).fetchone():
                # Historical providers did not persist comparable step accounting.
                if state['chain_id'].startswith('task:'):
                    legacy=db.execute('SELECT 1 FROM agent_runs r JOIN market_research_runs m ON m.run_id=r.id WHERE m.task_id=? AND r.result IS NOT NULL LIMIT 1',(state['chain_id'][5:],)).fetchone()
                else:legacy=db.execute('SELECT 1 FROM agent_runs WHERE id=? AND result IS NOT NULL',(state['chain_id'][4:],)).fetchone()
                created=state['recorded_since'] if state['recorded_since'] is not None else time.time()
                legacy=state['historical_usage_unrecorded'] if state['recorded_since'] is not None else bool(legacy)
                db.execute('INSERT INTO chain_budgets VALUES(?,?,?,?)',(state['chain_id'],canonical(limits),created,int(legacy)))
            db.execute('INSERT INTO chain_steps VALUES(?,?,?,?,?,?,?,?)',(state['chain_id'],run_id,step,kind,'reserved' if kind=='model' else 'consumed',time.time(),None,seconds))
        return seconds

    def read_step(self,run_id,step):self._reserve(run_id,step,'read')

    def _settle(self,run_id,step,elapsed,allowance,error=None):
        uncertain=error is not None and ('outcome_unknown' in str(error) or type(error).__name__=='Cancelled')
        status='unknown' if uncertain else 'failed' if error else 'completed'
        seconds=max(allowance,elapsed) if uncertain else elapsed
        with self.core.atomic() as db:
            db.execute("UPDATE chain_steps SET status=?,finished=?,seconds=? WHERE run_id=? AND step=? AND status='reserved'",(status,time.time(),seconds,run_id,step))

    @contextmanager
    def model_step(self,run_id,step,cancelled):
        allowance=self._reserve(run_id,step,'model');start=time.monotonic()
        stop=lambda:cancelled() or time.monotonic()-start>=allowance
        try:
            yield stop
        except BaseException as error:
            elapsed=time.monotonic()-start;self._settle(run_id,step,elapsed,allowance,error)
            if elapsed>=allowance:raise ValueError('agent_chain_budget_exhausted') from error
            raise
        else:
            elapsed=time.monotonic()-start;self._settle(run_id,step,elapsed,allowance)
            if elapsed>=allowance:raise ValueError('agent_chain_budget_exhausted')
