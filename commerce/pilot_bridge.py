"""Reference an existing private product pilot without inventing seller inventory.

Source reports are data, never instructions or authoritative business gates.
This bridge writes only versioned source links; it never changes pilot files,
creates duplicate tasks, or imports a candidate as a real inventory work item.
"""
from pathlib import Path
import hashlib
import json
import re
import time

EXPORTS=('supplier-rfq.md','cost-inputs.csv','restock-inputs.csv','creative-brief.md','compliance-checklist.md')


def sha(value):return hashlib.sha256(value).hexdigest()
def require(ok,code):
 if not ok:raise ValueError(code)


def definitions(schema,string):
 return [
  ('commerce_pilot_list','列出本机已有候选试点与来源链接，不导入为店铺商品或创建任务',schema()),
  ('commerce_pilot_get','核验选定试点文件完整性，读取源报告缺项与已有任务；不代表业务验收',schema({'pilot_id':string},['pilot_id'])),
  ('commerce_pilot_link','按已展示的来源清单版本保存共享链接；不重复任务，不生成SKU或库存',schema({'pilot_id':string,'manifest_sha256':string,'expected_previous_sha256':string},['pilot_id','manifest_sha256'])),
  ('commerce_pilot_export','下载选定试点既有补证模板；私有资料，不发送供应商或执行经营操作',schema({'pilot_id':string,'manifest_sha256':string,'file':{'type':'string','enum':list(EXPORTS)}},['pilot_id','manifest_sha256','file'])),
 ]


class PilotBridge:
 def __init__(self,service):
  self.service=service;self.core=service.core;self.root=service.state/'pilots'
  with self.core.db()as db:
   db.execute('CREATE TABLE IF NOT EXISTS pilot_links(pilot_id TEXT PRIMARY KEY,manifest_sha TEXT,linked REAL)')
   db.execute('CREATE TABLE IF NOT EXISTS pilot_link_history(pilot_id TEXT,manifest_sha TEXT,linked REAL,PRIMARY KEY(pilot_id,manifest_sha))')

 def source(self,pilot_id):
  require(isinstance(pilot_id,str)and bool(re.fullmatch('[a-z0-9][a-z0-9-]{1,79}',pilot_id)),'pilot_invalid_id')
  root=self.root/pilot_id;require(root.is_dir()and not root.is_symlink(),'pilot_not_found')
  manifest=root/'manifest.json';require(manifest.is_file()and not manifest.is_symlink()and manifest.stat().st_size<=100000,'pilot_invalid_manifest')
  original=manifest.read_bytes();value=json.loads(original);require(isinstance(value,dict),'pilot_invalid_manifest');files=value.get('files')
  require(isinstance(files,list)and 1<=len(files)<=100,'pilot_invalid_manifest');captured={};size=0
  for item in files:
   require(isinstance(item,dict)and isinstance(item.get('path'),str),'pilot_invalid_manifest');path=Path(item['path'])
   require(not path.is_absolute()and path.parts and '..'not in path.parts and path.as_posix()not in captured,'pilot_invalid_file_path')
   current=root
   for part in path.parts:
    current=current/part;require(not current.is_symlink(),'pilot_invalid_file_path')
   require(current.is_file()and current.stat().st_size<=4*1024*1024,'pilot_file_missing_or_large')
   data=current.read_bytes();size+=len(data);require(size<=24*1024*1024,'pilot_source_budget_exceeded')
   require(sha(data)==item.get('sha256')and len(data)==item.get('bytes'),'pilot_source_changed')
   captured[path.as_posix()]=data
  require(manifest.read_bytes()==original,'pilot_source_changed')
  require('pilot-board.json'in captured and 'REVIEW.md'in captured,'pilot_source_incomplete')
  board=json.loads(captured['pilot-board.json']);require(isinstance(board,dict),'pilot_source_invalid_board');stages=board.get('stages')
  require(isinstance(stages,list)and len(stages)<=20,'pilot_source_invalid_board')
  projected=[]
  for item in stages:
   require(isinstance(item,dict)and re.fullmatch('S(?:[0-9]|1[01])',str(item.get('stage',''))),'pilot_source_invalid_board')
   stage=next((s for s in self.service.organization.contract['stages']if s['id']==item['stage']),{})
   projected.append({'stage':item['stage'],'name':stage.get('name',item['stage']),'reported_state':str(item.get('state','UNKNOWN'))[:40],
                     'reported_owner':str(item.get('owner','unknown'))[:60],'reported_detail':str(item.get('detail',''))[:1600],
                     'business_gate':'not_verified_by_this_bridge'})
  lines=captured['REVIEW.md'].decode('utf-8').splitlines();first=lines[0].lstrip('# ').strip()[:100]if lines else pilot_id
  return {'id':pilot_id,'label':first or pilot_id,'manifest_sha256':sha(original),'file_count':len(captured),'files':captured,'stages':projected,
          'reported_mapping':{k:board.get(k)for k in ('organization_case_id','store_product_id','seller_sku')},'source_scope':str(board.get('scope','unknown'))[:160]}

 def listing(self):
  result=[]
  if self.root.is_dir():
   for folder in sorted(self.root.iterdir())[:100]:
    if not folder.is_dir()or folder.is_symlink()or not re.fullmatch('[a-z0-9][a-z0-9-]{1,79}',folder.name):continue
    try:
     source=self.source(folder.name)
     with self.core.db()as db:row=db.execute('SELECT manifest_sha FROM pilot_links WHERE pilot_id=?',(folder.name,)).fetchone()
     result.append({'id':folder.name,'label':source['label'],'manifest_sha256':source['manifest_sha256'],'source_integrity':'matches_manifest',
                    'linked_sha256':row[0]if row else None,'link_current':bool(row and row[0]==source['manifest_sha256']),'business_accepted':False})
    except (ValueError,KeyError,UnicodeError,TypeError):result.append({'id':folder.name,'label':folder.name,'source_integrity':'unavailable_or_changed','business_accepted':False})
    if len(result)>=20:break
  return {'pilots':result,'automatic_import':False,'seller_inventory_created':False}

 def get(self,pilot_id):
  source=self.source(pilot_id);files=source.pop('files');tasks=[]
  entries=json.loads(files.get('workbench-tasks.json',b'[]'));require(isinstance(entries,list)and len(entries)<=50,'pilot_invalid_tasks')
  for entry in entries:
   require(isinstance(entry,dict),'pilot_invalid_tasks');raw=entry.get('task',{});ident=raw.get('id')if isinstance(raw,dict)else None
   require(isinstance(ident,str)and bool(re.fullmatch('[a-f0-9-]{32,36}',ident)),'pilot_invalid_task_reference')
   try:
    task=self.core.invoke('commerce_task_get',{'task_id':ident});tasks.append({'id':ident,'status':task['status'],'title':str(task.get('input',{}).get('title',''))[:200]})
   except ValueError:tasks.append({'id':ident,'status':'unavailable','title':'原任务不可用，不会重建'})
  with self.core.db()as db:row=db.execute('SELECT manifest_sha,linked FROM pilot_links WHERE pilot_id=?',(pilot_id,)).fetchone()
  return {**source,'source_integrity':'matches_manifest','checked_at':time.time(),'existing_tasks':tasks,
          'link':{'manifest_sha256':row[0],'linked_at':row[1],'current':row[0]==source['manifest_sha256']}if row else None,
          'downloads':[p for p in EXPORTS if p in files],'candidate_stage':'source_backed_candidate_not_seller_product',
          'business_accepted':False,'publish_ready':False,'commercial_closed_loop':False,'inventory_mapping_verified':False,
          'authority':'source_report_is_reference_only_not_an_organization_gate','tasks_created':0,'source_files_changed':False}

 def link(self,pilot_id,manifest_sha256,expected_previous_sha256=None):
  source=self.source(pilot_id);require(source['manifest_sha256']==manifest_sha256,'pilot_source_changed')
  with self.core.atomic()as db:
   old=db.execute('SELECT manifest_sha FROM pilot_links WHERE pilot_id=?',(pilot_id,)).fetchone()
   if old and old[0]==manifest_sha256:return {'pilot':self.get(pilot_id),'reused':True,'tasks_created':0}
   require((old and old[0]==expected_previous_sha256)or(not old and expected_previous_sha256 is None),'pilot_link_changed')
   at=time.time();db.execute('INSERT INTO pilot_links VALUES (?,?,?)ON CONFLICT(pilot_id)DO UPDATE SET manifest_sha=excluded.manifest_sha,linked=excluded.linked',(pilot_id,manifest_sha256,at))
   db.execute('INSERT OR IGNORE INTO pilot_link_history VALUES (?,?,?)',(pilot_id,manifest_sha256,at))
  return {'pilot':self.get(pilot_id),'reused':False,'tasks_created':0}

 def export(self,pilot_id,manifest_sha256,file):
  require(file in EXPORTS,'pilot_export_not_allowed');source=self.source(pilot_id);require(source['manifest_sha256']==manifest_sha256,'pilot_source_changed')
  require(file in source['files'],'pilot_export_missing');content=source['files'][file]
  return {'filename':file,'content':content.decode('utf-8'),'sha256':sha(content),'business_accepted':False,'privacy':'existing_private_pilot_material_not_public_release_attachment'}

 def invoke(self,name,args):
  return {'commerce_pilot_list':self.listing,'commerce_pilot_get':self.get,'commerce_pilot_link':self.link,'commerce_pilot_export':self.export}[name](**args)
