"""Pure source pacing/ownership planner. Database claims remain the caller's job."""
import math
ACTIVE=frozenset(('queued','running','cancelling'))

def require(value):
    if not value:raise ValueError('invalid_collection_schedule')

def clock(value):return type(value) in (int,float) and value>=0 and math.isfinite(value)

def plan(source_ids,jobs,now,interval,enabled=True):
    require(isinstance(source_ids,list) and bool(source_ids))
    require(all(isinstance(s,str) and bool(s) for s in source_ids))
    require(len(set(source_ids))==len(source_ids))
    require(isinstance(jobs,list) and clock(now) and clock(interval) and interval>0 and type(enabled) is bool)
    active=set();latest={}
    for job in jobs:
        require(isinstance(job,dict))
        require(isinstance(job.get('source'),str) and bool(job['source']))
        require(isinstance(job.get('status'),str) and bool(job['status']))
        start=job.get('started_at');require(start is None or clock(start))
        if job['status'] in ACTIVE:active.add(job['source'])
        if start is not None:latest[job['source']]=max(start,latest.get(job['source'],0))
    if not enabled or 'all' in active:return []
    result=[]
    for source in source_ids:
        started=[latest[key] for key in (source,'all') if key in latest]
        if source not in active and all(now-value>=interval for value in started):result.append(source)
    return result
