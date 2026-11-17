"""Bounded report import using the existing immutable performance records."""
import csv
import io
from research import canonical,digest

COUNTS=('impressions','clicks','orders','returns','video_views','completed_views')
FIELDS={'request_id','request_result_sha256','period_start','period_end','feedback',*COUNTS}

def report(workflow,project_id,csv_text,source_ref,commit=False,expected_preview_sha256=''):
 workflow.project(project_id)
 if type(commit)is not bool or not isinstance(csv_text,str)or len(csv_text.encode())>262144:raise ValueError('creative_report_invalid')
 reader=csv.DictReader(io.StringIO(csv_text.lstrip('\ufeff')))
 if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames)or set(reader.fieldnames)-FIELDS or not {'period_start','period_end'}<=set(reader.fieldnames):raise ValueError('creative_report_columns_invalid')
 rows=[]
 try:
  for row in reader:
   if len(rows)>=100 or None in row or None in row.values():raise ValueError('creative_report_rows_invalid')
   value={k:v.strip()for k,v in row.items()if v.strip()};value['source_ref']=source_ref
   for key in COUNTS:
    if key in value:
     if not value[key].isascii()or not value[key].isdigit():raise ValueError('creative_report_count_invalid')
     value[key]=int(value[key])
   rows.append(value)
 except csv.Error:raise ValueError('creative_report_invalid')from None
 if not rows:raise ValueError('creative_report_empty')
 sha=digest(canonical([project_id,rows]));source_sha=digest(csv_text)
 if commit and sha!=expected_preview_sha256:raise ValueError('creative_report_preview_changed')
 # Validate with the authoritative save path, rolling the preview transaction back.
 class PreviewRollback(Exception):pass
 records=[]
 try:
  with workflow.core.atomic():
   for i,value in enumerate(rows):records.append(workflow.performance_save(project_id,value,'csv:'+sha+':'+str(i)))
   if not commit:raise PreviewRollback()
 except PreviewRollback:pass
 return {'preview_sha256':sha,'source_sha256':source_sha,'row_count':len(rows),'committed':commit,'rows':rows,'record_ids':[r['id']for r in records]if commit else[], 'publication_executed':False}
