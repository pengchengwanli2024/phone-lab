"""Immutable timeline revisions over existing production requests."""
import copy
import json
import time
import uuid
from research import canonical,digest

SIZES={'9:16':(720,1280),'1:1':(1080,1080),'16:9':(1280,720)}

def validate(editing,count):
 if type(editing)is not dict or set(editing)!={'aspect_ratio','keep_source_audio','shots'}or editing['aspect_ratio']not in SIZES or type(editing['keep_source_audio'])is not bool:raise ValueError('creative_edit_invalid')
 shots=editing['shots']
 if not isinstance(shots,list)or len(shots)!=count:raise ValueError('creative_edit_shots_required')
 for row in shots:
  if type(row)is not dict or set(row)!={'source_index','source_start_ms','duration_ms','caption'}:raise ValueError('creative_edit_invalid')
  if type(row['source_index'])is not int or not 0<=row['source_index']<count:raise ValueError('creative_edit_invalid')
  if type(row['source_start_ms'])is not int or not 0<=row['source_start_ms']<=120000:raise ValueError('creative_edit_invalid')
  if type(row['duration_ms'])is not int or not 250<=row['duration_ms']<=30000:raise ValueError('creative_edit_invalid')
  if not isinstance(row['caption'],str)or len(row['caption'])>100 or any(ord(c)<32 and c!='\n'for c in row['caption']):raise ValueError('creative_edit_invalid')
 if not 1000<=sum(r['duration_ms']for r in shots)<=90000:raise ValueError('creative_edit_invalid_duration')
 return copy.deepcopy(editing)

def revise(workflow,request_id,expected_request_sha256,editing,idempotency_key):
 if not isinstance(idempotency_key,str)or not 1<=len(idempotency_key)<=160:raise ValueError('invalid_idempotency_key')
 with workflow.core.atomic()as db:
  parent=workflow.request_get(request_id);p=workflow._current(parent)
  if parent['spec'].get('delivery_commitment'):raise ValueError('creative_delivery_immutable')
  if not parent['spec']['format'].endswith('_video'):raise ValueError('creative_edit_video_required')
  if parent['request_sha256']!=expected_request_sha256 or digest(canonical({k:parent[k]for k in ('project_id','revision','spec')}))!=expected_request_sha256:raise ValueError('creative_request_changed')
  value=validate(editing,len(parent['spec']['shots']));key=digest(canonical([p['id'],'edit:'+idempotency_key]));signature=digest(canonical([request_id,expected_request_sha256,value]))
  old=db.execute('SELECT id,document FROM creative_requests WHERE idem=?',(key,)).fetchone()
  if old:
   if json.loads(old[1]).get('edit_input_sha256')!=signature:raise ValueError('idempotency_conflict')
   return workflow.request_get(old[0])
  if db.execute('SELECT count(*)FROM creative_requests WHERE project=?',(p['id'],)).fetchone()[0]>=100:raise ValueError('creative_request_limit')
  spec=copy.deepcopy(parent['spec']);spec['editing']=value;spec['width'],spec['height']=SIZES[value['aspect_ratio']];at=0;shots=[]
  for edit in value['shots']:
   shot=copy.deepcopy(parent['spec']['shots'][edit['source_index']]);shot.update(start_ms=at,end_ms=at+edit['duration_ms']);shots.append(shot);at=shot['end_ms']
  spec.update(shots=shots,duration_ms=at)
  frozen={'project_id':p['id'],'revision':p['revision'],'spec':spec}
  d={'id':uuid.uuid4().hex,**frozen,'request_sha256':digest(canonical(frozen)),'input_sha256':parent['input_sha256'],'direction_sha256':parent['direction_sha256'],'status':'awaiting_media','created_at':time.time(),'external_generation_submitted':False,'job_id':None,'assets':[],'result_sha256':None,'review':None,'parent_request_id':request_id,'parent_result_sha256':parent['result_sha256'],'edit_input_sha256':signature}
  db.execute('INSERT INTO creative_requests VALUES(?,?,?,?)',(d['id'],p['id'],key,canonical(d)));return d
