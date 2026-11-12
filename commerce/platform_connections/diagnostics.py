"""Project private metadata into counts only; never return store fields."""
from . import VERSION
from . import protocols as api


def summarize(catalog,listing):
 def require(ok):
  if not ok:raise ValueError('platform_diagnostic_metadata_invalid')
 require(isinstance(catalog,dict)and isinstance(listing,dict))
 providers=catalog.get('providers');stores=listing.get('stores')
 require(isinstance(providers,list)and len(providers)==len(api.CATALOG)and all(isinstance(p,dict)for p in providers))
 ids=[p.get('id')for p in providers]
 require(all(isinstance(p,str)for p in ids)and set(ids)==set(api.CATALOG))
 require(isinstance(stores,list)and len(stores)<=20)
 limits=catalog.get('limits',{})
 current=catalog.get('schema')==VERSION and isinstance(limits,dict)and all(
  type(limits.get(k))is int and limits[k]==expected for k,expected in
  [('normalized_records_per_job',api.MAX_RECORDS),('normalized_records_json_bytes',api.LIMIT_PROJECTION_BYTES)])
 result={p:dict(stores=0,enabled_stores=0,configured_stores=0,scope_reviewed_stores=0,
                fresh_resources=0,stale_resources=0,missing_resources=0,last_read_errors=0,active_reads=0)for p in api.CATALOG}
 for store in stores:
  require(isinstance(store,dict));provider=store.get('platform');require(isinstance(provider,str)and provider in result)
  require(all(type(store.get(k))is bool for k in ('enabled','configured','scope_reviewed')))
  row=result[provider];row['stores']+=1
  for key in ('enabled','configured','scope_reviewed'):row[key+'_stores']+=int(store[key])
  snapshots=store.get('snapshots');require(isinstance(snapshots,dict)and set(snapshots)==set(api.CATALOG[provider]['resources']))
  for value in snapshots.values():
   require(isinstance(value,dict)and all(type(value.get(k))is bool for k in ('available','fresh')))
   require(not value['fresh']or value['available']and store['enabled'])
   row['fresh_resources'if value['fresh']else'stale_resources'if value['available']else'missing_resources']+=1
  job=store.get('last_job')
  if job is not None:
   require(isinstance(job,dict)and job.get('status')in ('queued','running','cancel_requested','succeeded','failed','partial','unknown','superseded','cancelled'))
   row['active_reads']+=int(job['status']in ('queued','running','cancel_requested'))
   row['last_read_errors']+=int(job['status']in ('failed','partial','unknown','superseded'))
 return {'status':'current'if current else'update_pending','running_version_current':current,
         'registered_providers':len(providers),'stores':len(stores),'by_platform':result,
         'business_acceptance':False,'automatic_sync':False,'diagnostic_only':True}
