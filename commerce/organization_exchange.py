"""Explicit producer context and durable local artifact exchange; no new workers.

Source methods retain their own semantics. This namespaced writer stores scoped
outputs and recovers completed source jobs without re-submitting model requests.
"""
from copy import deepcopy
import json
import threading
from research import canonical, digest

SOURCE_TOOLS=('commerce_collection_check','commerce_collection_export','commerce_unit_economics','commerce_translation_start')
VERSION='org-exchange-v1-head-guard'
CURRENT_HEAD=object()


def definitions(schema, string):
    return [
        ('commerce_organization_exchange_status','读取工作项绑定上下文与交接回执，不改变产物',schema({'case_id':string})),
        ('commerce_organization_exchange_produce','按明确工作项运行现有采集检查、导出、成本或翻译，并保存本地产物；译文保持待校对',schema({'context':{'type':'object'},'source_tool':{'type':'string','enum':list(SOURCE_TOOLS)},'source_arguments':{'type':'object'},'source_record':{'type':'object'}},['context','source_tool','source_arguments'])),
        ('commerce_organization_exchange_bind_images','按明确对应关系绑定创意项目与图片，保存本机自动交接设置；不发布素材',schema({'context':{'type':'object'},'project_id':string,'asset_ids':{'type':'array','items':{'type':'string'}},'include_new_images':{'type':'boolean'}},['context','project_id','asset_ids','include_new_images'])),
        ('commerce_organization_exchange_sync','接收已完成翻译和已绑定图片；不会重新调用模型、投放或操作店铺',schema({'case_id':string})),
    ]


class OrganizationExchange:
    def __init__(self, organization):
        self.org=organization;self.service=organization.service;self.core=organization.core;self.lock=threading.RLock()
        with self.core.db()as db:
            db.execute('CREATE TABLE IF NOT EXISTS org_exchange(id TEXT PRIMARY KEY,case_id TEXT,context TEXT,kind TEXT,payload TEXT,status TEXT,code TEXT,artifact TEXT,created TEXT,updated TEXT)')
            if 'expected_head'not in {r[1]for r in db.execute('PRAGMA table_info(org_exchange)')}:db.execute('ALTER TABLE org_exchange ADD COLUMN expected_head TEXT')
            db.execute('CREATE TABLE IF NOT EXISTS org_exchange_jobs(case_id TEXT,job_id TEXT,context TEXT,record TEXT,items TEXT,status TEXT,PRIMARY KEY(case_id,job_id))')
            db.execute('CREATE TABLE IF NOT EXISTS org_exchange_images(case_id TEXT PRIMARY KEY,context TEXT,project_id TEXT,assets TEXT,include_new INTEGER)')
            # Only a local idempotent write can have been interrupted here.
            db.execute("UPDATE org_exchange SET status='pending',code='local_publish_interrupted' WHERE status='publishing'")

    def context(self, case_id):
        case=self.org.case(case_id)
        return dict(case_id=case_id,scope_sha256=digest(canonical(case)),origin='manual')

    def verify(self, context):
        if not isinstance(context,dict)or set(context)!={'case_id','scope_sha256','origin'}:raise ValueError('invalid_exchange_context')
        if context['origin']!='manual':raise ValueError('example_output_cannot_be_real_artifact')
        current=self.context(context['case_id'])
        if current!=context:raise ValueError('exchange_scope_changed_refresh_binding')
        return self.org.case(context['case_id'])

    @staticmethod
    def stamp():
        from organization import stamp
        return stamp()

    def _record_scope(self, case, record):
        if not isinstance(record,dict)or record.get('platform')!=case['scope']['platform']or record.get('market')!=case['scope']['market']:raise ValueError('exchange_research_scope_mismatch')
        from research import validate
        validate(record)
        return dict(sku=case['scope']['sku'],row_key=case['scope']['row_key'],record=deepcopy(record))

    def _queue(self, context, kind, payload, expected_head=CURRENT_HEAD):
        value=canonical(payload)
        if len(value.encode())>120000:raise ValueError('exchange_payload_too_large')
        current=self.org.artifact(context['case_id'],kind)
        if current and current['intact']:
            with self.core.db()as db:existing=db.execute("SELECT id FROM org_exchange WHERE artifact=? AND context=? AND payload=? AND status='saved' ORDER BY created DESC LIMIT 1",(current['id'],canonical(context),value)).fetchone()
            if existing:return existing[0]
        if expected_head is CURRENT_HEAD:expected_head=current['id']if current else None
        key=digest(canonical(dict(context=context,kind=kind,payload=payload,expected_head=expected_head)));now=self.stamp()
        with self.core.db()as db:db.execute('INSERT OR IGNORE INTO org_exchange VALUES (?,?,?,?,?,?,?,?,?,?,?)',(key,context['case_id'],canonical(context),kind,value,'pending',None,None,now,now,expected_head))
        return key

    def _publish(self, key):
        with self.lock:
            with self.core.db()as db:row=db.execute('SELECT case_id,context,kind,payload,status,artifact,expected_head FROM org_exchange WHERE id=?',(key,)).fetchone()
            if not row:raise ValueError('exchange_receipt_not_found')
            try:
                context=json.loads(row[1]);self.verify(context)
                if row[4]=='saved':
                    with self.core.db()as db:prior=db.execute('SELECT payload,sha FROM org_artifacts WHERE id=?',(row[5],)).fetchone()
                    if not prior or digest(canonical(json.loads(prior[0])))!=prior[1]:raise ValueError('exchange_stored_artifact_changed')
                    if row[2]!='images':return self.receipt(key)
                with self.core.db()as db:db.execute("UPDATE org_exchange SET status='publishing',updated=? WHERE id=?",(self.stamp(),key))
                payload=json.loads(row[3])
                if row[2]=='images':
                    result=self.org.deliver(row[0],payload['project_id'],payload['asset_ids'],'exchange:'+key,_expected_head=row[6])
                else:result=self.org.record(row[0],row[2],payload,'exchange:'+key,_expected_head=row[6])
                # If another workflow changed scope, retain the historical write
                # but never report it as a current, accepted handoff.
                self.verify(context)
                code='translation_or_source_review_still_required'if row[2]=='research'else'local_draft_only'
                with self.core.db()as db:db.execute("UPDATE org_exchange SET status='saved',artifact=?,code=?,updated=? WHERE id=?",(result['id'],code,self.stamp(),key))
            except ValueError as error:
                with self.core.db()as db:db.execute("UPDATE org_exchange SET status='held',code=?,updated=? WHERE id=?",(str(error),self.stamp(),key))
            except Exception:
                with self.core.db()as db:db.execute("UPDATE org_exchange SET status='pending',code='local_handoff_not_confirmed',updated=? WHERE id=?",(self.stamp(),key))
            return self.receipt(key)

    def receipt(self, key):
        with self.core.db()as db:row=db.execute('SELECT id,case_id,kind,status,code,artifact,created,updated,context FROM org_exchange WHERE id=?',(key,)).fetchone()
        if not row:raise ValueError('exchange_receipt_not_found')
        current=True
        try:self.verify(json.loads(row[8]))
        except ValueError:current=False
        head=self.org.artifact(row[1],row[2]);artifact_current=bool(head and head['id']==row[5]and head['intact'])
        return dict(id=row[0],case_id=row[1],kind=row[2],status=row[3],code=row[4],artifact_id=row[5],created_at=row[6],updated_at=row[7],context_current=current,artifact_current=artifact_current,gate_passed=False,external_operations_executed=False)

    def status(self, case_id=None):
        cases=self.org.cases()
        if case_id:self.org.case(case_id)
        allowed={c['id']for c in cases};ids=[]
        with self.core.db()as db:
            for row in db.execute('SELECT id,case_id FROM org_exchange ORDER BY updated DESC LIMIT 100'):
                if row[1]in allowed and(not case_id or row[1]==case_id):ids.append(row[0])
            bindings=[dict(case_id=r[0],project_id=r[1],asset_ids=json.loads(r[2]),include_new_images=bool(r[3]))for r in db.execute('SELECT case_id,project_id,assets,include_new FROM org_exchange_images')if r[0]in allowed and(not case_id or r[0]==case_id)]
        return dict(version=VERSION,context=self.context(case_id)if case_id else None,receipts=[self.receipt(i)for i in ids[:30]],image_bindings=bindings,notice='交接保存不等于门禁通过；原文、校对状态、币种和来源判据保持不变。')

    def produce(self, context, source_tool, source_arguments, source_record=None):
        case=self.verify(context)
        if source_tool not in SOURCE_TOOLS or not isinstance(source_arguments,dict):raise ValueError('invalid_exchange_source')
        # Use the current public domain API; no provider or collector internals.
        self.service.validate(source_tool,source_arguments)
        if source_tool in ('commerce_collection_check','commerce_collection_export'):
            payload=self._record_scope(case,source_arguments['record']);kind='research'
        elif source_tool=='commerce_unit_economics':
            payload=source_arguments['input'];kind='economics'
            if case['currency']and payload.get('currency')and payload['currency']!=case['currency']:raise ValueError('exchange_currency_mismatch')
        else:
            payload=self._record_scope(case,source_record);kind='research'
            record=payload['record'];items=source_arguments['input'].get('items')
            if source_arguments['input'].get('language')!=record['language']or not isinstance(items,list)or any(not isinstance(i,dict)or i.get('id')not in record['fields']or i.get('text')!=record['fields'][i['id']].get('original')for i in items):raise ValueError('exchange_translation_source_mismatch')
            # Establish the original evidence before the asynchronous model call.
            self._publish(self._queue(context,kind,payload))
        head=self.org.artifact(case['id'],kind);expected_head=head['id']if head else None
        result=self.service.invoke(source_tool,deepcopy(source_arguments),'local')
        if source_tool=='commerce_translation_start':
            with self.core.db()as db:
                old=db.execute('SELECT context,record,items FROM org_exchange_jobs WHERE case_id=? AND job_id=?',(case['id'],result['id'])).fetchone()
                frozen=(canonical(context),canonical(payload['record']),canonical(source_arguments['input']['items']))
                if old and tuple(old)!=frozen:raise ValueError('exchange_translation_binding_conflict')
                db.execute('INSERT OR IGNORE INTO org_exchange_jobs VALUES (?,?,?,?,?,?)',(case['id'],result['id'],*frozen,'pending'))
            result=dict(result,artifact_handoff=dict(status='waiting_for_source',job_id=result['id'],case_id=case['id'],gate_passed=False))
        else:
            receipt=self._publish(self._queue(context,kind,payload,expected_head));result=dict(result,artifact_handoff=receipt)
            if 'result_sha256'in result:
                result.pop('result_sha256');result['result_sha256']=digest(canonical(result))
        return result

    def bind_images(self, context, project_id, asset_ids, include_new_images):
        case=self.verify(context);self.service.creative.get(project_id)
        if type(include_new_images)is not bool or not isinstance(asset_ids,list)or any(not isinstance(a,str)for a in asset_ids)or len(asset_ids)>20 or len(set(asset_ids))!=len(asset_ids):raise ValueError('invalid_image_binding')
        if not asset_ids and not include_new_images:raise ValueError('select_images_or_explicit_new_image_binding')
        for ident in asset_ids:
            _,_,kind=self.service.creative.asset(project_id,ident)
            if kind not in ('product_image','generated_image'):raise ValueError('registered_product_images_required')
        with self.core.db()as db:db.execute('INSERT OR REPLACE INTO org_exchange_images VALUES (?,?,?,?,?)',(case['id'],canonical(context),project_id,canonical(sorted(asset_ids)),int(include_new_images)))
        return self.sync(case['id'])

    @staticmethod
    def _source_signature(record):
        return digest(canonical({k:record.get(k)for k in ('platform','market','language','source_url','captured_at','raw_excerpt')}|{'originals':{k:v.get('original')for k,v in record['fields'].items()}}))

    def _translation(self, case_id, job_id, context, original, items):
        self.verify(context);job=self.service.translations.get(job_id)
        if job['status']in ('queued','running'):return dict(status='waiting_for_source',job_id=job_id)
        if job['status']!='completed':return dict(status='source_failed_no_resubmit',job_id=job_id)
        latest=self.org.artifact(case_id,'research')
        if not latest or not latest['intact']:raise ValueError('exchange_original_artifact_missing')
        current=latest['payload']['record']
        if self._source_signature(current)!=self._source_signature(original):raise ValueError('exchange_source_changed_translation_not_applied')
        if job.get('input_sha256')!=digest(canonical({'language':original['language'],'items':items})):raise ValueError('exchange_translation_input_changed')
        record=deepcopy(current);lookup={i['id']:i['text']for i in items};result=job['result'];translations=result.get('translations')
        if not isinstance(translations,list)or len(translations)!=len(lookup)or {v.get('id')for v in translations if isinstance(v,dict)}!=set(lookup):raise ValueError('exchange_translation_evidence_mismatch')
        for value in translations:
            key=value.get('id');text=lookup.get(key)
            if text is None or value.get('original_sha256')!=digest(text)or not isinstance(value.get('zh'),str)or value.get('zh_sha256')!=digest(value['zh']):raise ValueError('exchange_translation_evidence_mismatch')
            field=record['fields'][key]
            if field.get('zh','').strip():continue  # Preserve a person's edits.
            field['zh']=value['zh'];field['reviewed']=False
            field['translation']=dict(job_id=job_id,model=result.get('model'),provider=result.get('provider'),translated_at=result.get('translated_at'),original_sha256=value['original_sha256'],model_output=value['zh'],model_output_sha256=value['zh_sha256'],edited_by_user=False,prompt_version=result.get('prompt_version'),warnings=value.get('warnings',[]))
        payload=self._record_scope(self.org.case(case_id),record);receipt=self._publish(self._queue(context,'research',payload,latest['id']))
        if receipt['status']=='saved':
            with self.core.db()as db:db.execute("UPDATE org_exchange_jobs SET status='saved' WHERE case_id=? AND job_id=?",(case_id,job_id))
        return receipt

    def sync(self, case_id=None):
        cases=self.org.cases();allowed={c['id']for c in cases}
        if case_id:self.org.case(case_id);allowed={case_id}
        results=[]
        with self.core.db()as db:
            jobs=db.execute("SELECT case_id,job_id,context,record,items FROM org_exchange_jobs WHERE status='pending'").fetchall()
            images=db.execute('SELECT case_id,context,project_id,assets,include_new FROM org_exchange_images').fetchall()
            pending=[r[0]for r in db.execute("SELECT id,case_id FROM org_exchange WHERE status IN ('pending','held')")if r[1]in allowed]
        for key in pending[:30]:results.append(self._publish(key))
        for cid,job,context,record,items in jobs[:30]:
            if cid not in allowed:continue
            try:results.append(self._translation(cid,job,json.loads(context),json.loads(record),json.loads(items)))
            except ValueError as error:results.append(dict(status='held',job_id=job,code=str(error)))
        for cid,context,pid,assets,include_new in images[:30]:
            if cid not in allowed:continue
            try:
                context=json.loads(context);self.verify(context);head=self.org.artifact(cid,'images');expected_head=head['id']if head else None;project=self.service.creative.get(pid);selected=json.loads(assets)
                if include_new:selected=sorted(a['id']for a in project['assets']if a['kind']in ('product_image','generated_image'))
                if not selected:results.append(dict(status='waiting_for_source',case_id=cid,kind='images'));continue
                payload=dict(project_id=pid,asset_ids=selected,project_revision=project['revision'])
                # Asset hashes are part of the event identity, so changed sources
                # cannot be mistaken for a successful older delivery.
                payload['source_hashes']=[self.service.creative.asset(pid,a)[1].get('sha256')for a in selected]
                results.append(self._publish(self._queue(context,'images',payload,expected_head)))
            except ValueError as error:results.append(dict(status='held',case_id=cid,kind='images',code=str(error)))
        return dict(results=results,external_operations_executed=False,model_requests_submitted=False)

    def invoke(self, name, args):
        operation=name.removeprefix('commerce_organization_exchange_')
        if operation=='status':return self.status(**args)
        if operation=='produce':return self.produce(**args)
        if operation=='bind_images':return self.bind_images(**args)
        if operation=='sync':return self.sync(**args)
        raise ValueError('unknown_exchange_tool')
