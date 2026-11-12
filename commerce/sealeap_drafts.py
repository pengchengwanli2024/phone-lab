"""Source-bound model draft jobs. Availability, review and business acceptance differ."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

from sealeap_contracts import canonical,digest,validate_input,contract_for
from sealeap_methodology import validate_checks
from sealeap_draft_protocol import require_current_protocol
from translation import model_command

ROOT=Path(__file__).resolve().parent
_slots=threading.BoundedSemaphore(2)


def validate_response(payload,response):
    require_current_protocol(payload)
    raw=response.get('draft') if isinstance(response,dict) else None
    if not isinstance(raw,dict) or set(raw)!={'status','sections','questions','limitations','requirement_checks'} or raw['status'] not in ['draft','needs_inputs']:raise ValueError('sealeap_draft_invalid_response')
    refs={r['id']:r for r in payload['references']};facts={f['id']:f for f in payload['task']['facts']};known=set(refs)|set(facts)
    expected=payload['contract']['sections'];sections=raw['sections'];seen=set();warnings=['all_claims_and_domain_fit_require_human_review']
    if not isinstance(sections,list) or len(sections)!=len(expected):raise ValueError('sealeap_draft_sections_missing')
    for section in sections:
        if not isinstance(section,dict) or set(section)!={'id','items'} or section['id'] not in expected or section['id'] in seen:raise ValueError('sealeap_draft_section_invalid')
        seen.add(section['id']);items=section['items']
        if not isinstance(items,list) or not 1<=len(items)<=6:raise ValueError('sealeap_draft_items_invalid')
        for item in items:
            if not isinstance(item,dict) or set(item)!={'text','kind','basis_refs'} or item['kind'] not in ['fact','inference','proposal','gap'] or not isinstance(item['text'],str) or not 1<=len(item['text'])<=1600:raise ValueError('sealeap_draft_item_invalid')
            cites=item['basis_refs']
            if not isinstance(cites,list) or len(cites)>12 or any(not isinstance(ref,str) or ref not in known for ref in cites):raise ValueError('sealeap_draft_unknown_reference')
            if item['kind']!='gap' and not cites:raise ValueError('sealeap_draft_reference_required')
            if item['kind']=='fact':
                if not any(ref in facts for ref in cites):raise ValueError('sealeap_draft_method_not_product_fact')
                cited=' '.join(facts[ref]['text'] for ref in cites if ref in facts)
                if set(re.findall(r'\d+(?:[.,]\d+)?',item['text']))-set(re.findall(r'\d+(?:[.,]\d+)?',cited)):warnings.append('new_fact_numbers_require_review')
    for key,limit in [('questions',5),('limitations',10)]:
        if not isinstance(raw[key],list) or len(raw[key])>limit or any(not isinstance(v,str) or not 1<=len(v)<=1000 for v in raw[key]):raise ValueError('sealeap_draft_notes_invalid')
    if raw['status']=='needs_inputs' and not raw['questions']:raise ValueError('sealeap_draft_missing_input_question_required')
    method=dict(inputs=[r for r in payload['contract']['source_requirements'] if r['kind']=='inputs'],deliverables=[r for r in payload['contract']['source_requirements'] if r['kind']=='deliverables'])
    gaps=validate_checks(method,raw['requirement_checks'],set(expected),set(facts),set(refs))
    if gaps and raw['status']!='needs_inputs':raise ValueError('sealeap_source_checks_contradict_ready_status')
    return dict(raw,provider=str(response.get('provider','unknown'))[:100],model=str(response.get('model','unknown'))[:160],
        source_requirement_review='model_assessment_requires_business_review',source_requirement_gaps=gaps,
        warnings=sorted(set(warnings)),review_status='pending_review',independently_verified=False,platform_operations_executed=False,tools_enabled=False)


def invoke_model(payload,cancelled,route=None):
    require_current_protocol(payload)
    if route and route.get('provider')=='codex':
        from agent_runtime.codex_provider import invoke_json,Cancelled
        from sealeap_draft_worker import SYSTEM
        def obj(fields):return {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}
        string={'type':'string'};strings={'type':'array','items':string}
        item=obj({'text':string,'kind':{'type':'string','enum':['fact','inference','proposal','gap']},'basis_refs':strings})
        section=obj({'id':string,'items':{'type':'array','items':item}})
        check=obj({'requirement_id':string,'status':{'type':'string','enum':['covered_in_draft','partial','missing','not_applicable']},'basis_refs':strings,'section_ids':strings,'note':string})
        spec=obj({'status':{'type':'string','enum':['draft','needs_inputs']},'sections':{'type':'array','items':section},'questions':strings,'limitations':strings,'requirement_checks':{'type':'array','items':check}})
        model_payload=json.loads(canonical(payload))
        for fact in model_payload['task']['facts']:fact['source_ref']='caller_source_recorded_locally'
        try:raw=invoke_json(model_payload,cancelled,route,spec,SYSTEM,input_limit=256000,response_limit=80000)
        except Cancelled:raise ValueError('sealeap_draft_outcome_unknown_cancel_requested') from None
        except ValueError as error:
            if str(error)=='agent_provider_outcome_unknown':raise ValueError('sealeap_draft_outcome_unknown_timeout') from None
            raise
        response={'draft':raw,'provider':'codex_cli','model':route['model'],'tools_enabled':False}
        try:return validate_response(payload,response)
        except ValueError as error:raise DraftValidationError(str(error),response) from None
    command,env=model_command();command[-1]=str(ROOT/'sealeap_draft_worker.py')
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,cwd=ROOT)
    try:
        model_payload=json.loads(canonical(payload))
        for fact in model_payload['task']['facts']:fact['source_ref']='caller_source_recorded_locally'
        first=True;deadline=time.monotonic()+115
        while True:
            if cancelled():raise ValueError('sealeap_draft_outcome_unknown_cancel_requested')
            if time.monotonic()>deadline:raise ValueError('sealeap_draft_outcome_unknown_timeout')
            try:
                out,_=process.communicate(input=json.dumps(model_payload,ensure_ascii=False) if first else None,timeout=.25);break
            except subprocess.TimeoutExpired:first=False
        if len(out)>70000:raise ValueError('sealeap_draft_response_too_large')
        try:result=json.loads(out)
        except ValueError:raise ValueError('sealeap_draft_invalid_json') from None
        if process.returncode:
            raise ValueError('sealeap_draft_outcome_unknown_provider' if result.get('outcome_unknown') else 'sealeap_draft_provider_failed_no_automatic_retry')
        try:return validate_response(payload,result)
        except ValueError as error:raise DraftValidationError(str(error),result) from None
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        for stream in [process.stdin,process.stdout,process.stderr]:
            if stream:stream.close()


class DraftValidationError(ValueError):
    def __init__(self,code,response):
        super().__init__(code);self.response=response


class SkillDrafts:
    def __init__(self,library):
        self.library=library;self.core=library.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sealeap_drafts(id TEXT PRIMARY KEY,idem TEXT UNIQUE,case_id TEXT,frozen TEXT,payload TEXT,status TEXT,result TEXT,cancel INTEGER,created TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS sealeap_draft_reviews(draft_id TEXT PRIMARY KEY,result_sha TEXT,decision TEXT,note TEXT,created TEXT)')
            db.execute("UPDATE sealeap_drafts SET status='unknown',result=? WHERE status='running'",(canonical({'error':'sealeap_draft_outcome_unknown_restart_no_resubmit'}),))
            db.execute("UPDATE sealeap_drafts SET status='interrupted',result=? WHERE status='queued'",(canonical({'error':'sealeap_draft_interrupted_before_model_no_resubmit'}),))

    def list_for_case(self,case):
        with self.core.db() as db:rows=db.execute('SELECT id,status,created FROM sealeap_drafts WHERE case_id=? ORDER BY rowid DESC LIMIT 10',(case,)).fetchall()
        return [dict(id=r[0],status=r[1],created=r[2]) for r in rows]

    def context(self,case):
        e=self.library.entry(case['skill_id']);contract=contract_for(e,case.get('mode_id'))
        if not contract:raise ValueError('sealeap_use_offline_adapter')
        if not self.library.verify(e) or case['source_sha256']!=e['source_sha256']:raise ValueError('sealeap_source_integrity_changed')
        task,missing=validate_input(case['input'],contract)
        if contract['mode_selection_required'] and not case.get('mode_id'):missing.append('mode_id')
        candidates=[f['path'] for f in e['files'] if f['path'].endswith('.md') and f['path']!='SKILL.md']
        mode=None
        if case.get('mode_id'):
            mode=next((m for m in e['subcapabilities'] if m['name']==case['mode_id']),None)
            if mode is None or case.get('mode_sha256')!=digest(mode):raise ValueError('sealeap_draft_mode_changed')
            candidates.sort(key=lambda p:(p!=mode['reference'],'playbook' not in p,p))
        else:
            terms=set(re.findall(r'[a-zA-Z]{3,}',task['goal'].lower()))
            candidates.sort(key=lambda p:(-sum(term in p.lower() for term in terms),not any(token in p for token in ['playbook','workflow','input','guardrail']),p))
        required_paths=set(contract['required_source_paths'])
        candidates.sort(key=lambda p:p not in required_paths)
        references=[];omitted=[];used=0
        for path in ['SKILL.md']+candidates:
            content=self.library.source_file(e,path).read_text();size=len(content)
            if used+size>48000 or len(references)>=7:
                omitted.append(dict(path=path,reason='whole_file_omitted_context_budget'));continue
            references.append(dict(id='K'+str(len(references)+1),path=path,sha256=next(f['sha256'] for f in e['files'] if f['path']==path),content=content));used+=size
        if not references or references[0]['path']!='SKILL.md':raise ValueError('sealeap_draft_source_too_large_select_manually')
        if mode and mode['reference'] not in [r['path'] for r in references]:raise ValueError('sealeap_draft_mode_reference_budget_exceeded')
        if required_paths-{r['path'] for r in references}:raise ValueError('sealeap_draft_required_source_budget_exceeded')
        payload=dict(contract=contract,task=task,references=references,omitted_references=omitted,mode=mode,synthetic=case['synthetic'],
            current_policy_verified=False,account_entitlement_verified=False,platform_operations_enabled=False)
        return payload,missing

    def start(self,case_id,key):
        case=self.library.case(case_id);payload,missing=self.context(case)
        frozen=canonical(dict(case_id=case_id,source_sha256=case['source_sha256'],contract_sha256=payload['contract']['sha256'],task=payload['task'],mode=case.get('mode_sha256'),synthetic=case['synthetic'],worker_sha256=hashlib.sha256((ROOT/'sealeap_draft_worker.py').read_bytes()).hexdigest()))
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT id,frozen FROM sealeap_drafts WHERE idem=?',(key,)).fetchone()
            if old:
                if old[1]!=frozen:raise ValueError('idempotency_conflict')
                return self.get(old[0])
            if db.execute('SELECT count(*) FROM sealeap_drafts WHERE case_id=?',(case_id,)).fetchone()[0]>=20:raise ValueError('sealeap_draft_case_limit')
            if db.execute('SELECT count(*) FROM sealeap_drafts').fetchone()[0]>=2000:raise ValueError('sealeap_draft_limit')
            if not missing and not _slots.acquire(blocking=False):raise ValueError('sealeap_draft_busy_try_later')
            ident=uuid.uuid4().hex;result=dict(status='needs_inputs',missing_fields=missing,generator='local_input_gate',model_requested=False,review_status='needs_inputs',platform_operations_executed=False) if missing else None
            try:db.execute('INSERT INTO sealeap_drafts VALUES(?,?,?,?,?,?,?,?,?)',(ident,key,case_id,frozen,canonical(payload),'needs_inputs' if missing else 'queued',canonical(result) if result else None,0,datetime.now(timezone.utc).isoformat()))
            except Exception:
                if not missing:_slots.release()
                raise
        if not missing:threading.Thread(target=self.work,args=(ident,payload),daemon=True).start()
        return self.get(ident)

    def cancelled(self,ident):
        with self.core.db() as db:return bool(db.execute('SELECT cancel FROM sealeap_drafts WHERE id=?',(ident,)).fetchone()[0])

    def work(self,ident,payload):
        try:
            with self.core.db() as db:
                row=db.execute('SELECT cancel FROM sealeap_drafts WHERE id=?',(ident,)).fetchone()
                if row[0]:
                    db.execute("UPDATE sealeap_drafts SET status='cancelled',result=? WHERE id=?",(canonical({'error':'cancelled_before_model_request','model_requested':False}),ident));return
                db.execute("UPDATE sealeap_drafts SET status='running' WHERE id=?",(ident,))
            from agent_runtime.codex_provider import route
            selected=route(Path(self.core.path).parent)
            result=invoke_model(payload,lambda:self.cancelled(ident),route=selected) if selected['provider']=='codex' else invoke_model(payload,lambda:self.cancelled(ident))
            status='needs_inputs' if result['status']=='needs_inputs' else 'awaiting_review'
        except Exception as error:
            code=str(error) if isinstance(error,ValueError) else 'sealeap_draft_processing_failed'
            status='unknown' if 'outcome_unknown' in code else 'failed';result=dict(error=code,automatic_retry=False)
            if isinstance(error,DraftValidationError):result['unvalidated_response']=error.response
        finally:
            # The early cancelled branch has already committed its terminal state.
            if 'result' in locals():
                with self.core.db() as db:db.execute('UPDATE sealeap_drafts SET status=?,result=? WHERE id=?',(status,canonical(result),ident))
            _slots.release()

    def get(self,ident):
        with self.core.db() as db:
            row=db.execute('SELECT id,case_id,payload,status,result,cancel,created FROM sealeap_drafts WHERE id=?',(ident,)).fetchone()
            review=db.execute('SELECT result_sha,decision,note,created FROM sealeap_draft_reviews WHERE draft_id=?',(ident,)).fetchone()
        if not row:raise ValueError('sealeap_draft_not_found')
        payload=json.loads(row[2]);result=json.loads(row[4]) if row[4] else None
        current=self.library.entry(payload['contract']['skill_id'])
        try:current_contract=contract_for(current,payload['contract'].get('mode_id'))
        except ValueError:current_contract=None
        matches=bool(current_contract and current_contract['sha256']==payload['contract']['sha256'] and current['draft_contract']['sha256']==contract_for(current)['sha256'] and self.library.verify(current))
        if payload.get('mode'):
            mode=next((m for m in current.get('subcapabilities',[]) if m['name']==payload['mode']['name']),None)
            matches=matches and mode==payload['mode']
        return dict(id=row[0],case_id=row[1],status=row[3],result=result,result_sha256=digest(result) if result else None,cancel_requested=bool(row[5]),created_at=row[6],
            skill_id=payload['contract']['skill_id'],contract=payload['contract'],source_matches_current=matches,
            references=payload['references'],omitted_references=payload['omitted_references'],task=payload['task'],synthetic=payload['synthetic'],
            review=dict(result_sha256=review[0],decision=review[1],note=review[2],created=review[3],scope='caller_review_not_independent_business_acceptance') if review else None,
            platform_operations_executed=False)

    def cancel(self,ident):
        self.get(ident)
        with self.core.db() as db:db.execute("UPDATE sealeap_drafts SET cancel=1 WHERE id=? AND status IN ('queued','running')",(ident,))
        return self.get(ident)

    def review(self,ident,result_sha,decision,note=''):
        item=self.get(ident)
        if decision not in ['accept','reject'] or not isinstance(note,str) or len(note)>500:raise ValueError('sealeap_draft_review_invalid')
        if item['status'] not in ['awaiting_review','needs_inputs'] or not item['result'].get('sections') or item['result_sha256']!=result_sha or not item['source_matches_current']:raise ValueError('sealeap_draft_not_reviewable_or_changed')
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT result_sha,decision,note FROM sealeap_draft_reviews WHERE draft_id=?',(ident,)).fetchone()
            if old and tuple(old)!=(result_sha,decision,note):raise ValueError('sealeap_draft_review_already_recorded')
            if not old:db.execute('INSERT INTO sealeap_draft_reviews VALUES(?,?,?,?,?)',(ident,result_sha,decision,note,datetime.now(timezone.utc).isoformat()))
        return self.get(ident)

    def export(self,ident,format='json'):
        item=self.get(ident)
        if format=='json':return dict(export_kind='private_skill_draft',draft=item)
        if format!='markdown':raise ValueError('sealeap_draft_export_format_invalid')
        def plain(value):return re.sub(r'([\\`*_{}\[\]()#!|])',r'\\\1',str(value).replace('<','&lt;').replace('>','&gt;').replace('\n',' '))
        lines=['# 技能执行草稿 · 待业务审阅','',plain(item['skill_id']),'',f"来源契约：{item['contract']['sha256']}",f"状态：{item['status']}",'平台操作未执行；当前规则与事实未独立核实。',
            '合成输入：'+str(item['synthetic']), '当前来源仍匹配：'+str(item['source_matches_current']), '', '## 调用者提供的依据','']
        lines+=['- '+v['id']+'：'+plain(v['text'])+'；标注 '+plain(v['label'])+'；来源 '+plain(v['source_ref']) for v in item['task']['facts']]
        result=item['result'] or {}
        for section in result.get('sections',[]):
            lines+=['## '+plain(section['id']),'']
            for v in section['items']:lines.append('- '+plain(v['text'])+' ['+', '.join(v['basis_refs'])+']')
            lines.append('')
        lines+=['## 待补问题','']+['- '+plain(v) for v in result.get('questions',result.get('missing_fields',[]))]
        lines+=['','## 原始要求对照（模型自评，待业务审阅）','']
        requirements={r['id']:r for r in item['contract'].get('source_requirements',[])}
        for check in result.get('requirement_checks',[]):
            source=requirements.get(check['requirement_id'],{})
            lines.append('- '+plain(check['requirement_id'])+' '+plain(source.get('text',''))+'；'+plain(check['status'])+'；'+plain(check['note'])+'；依据 '+plain(', '.join(check['basis_refs']))+'；草稿章节 '+plain(', '.join(check['section_ids'])))
        lines+=['','## 引用清单','']+['- '+v['id']+'：'+plain(v['path'])+'；SHA-256 '+v['sha256'] for v in item['references']]
        lines+=['','## 未纳入上下文的文件','']+['- '+plain(v['path'])+'：'+plain(v['reason']) for v in item['omitted_references']]
        lines+=['','## 适用限制与审阅','']+['- '+plain(v) for v in result.get('limitations',[])+result.get('warnings',[])]
        lines.append(plain(item['review'] or '尚无调用者审阅记录；输出不是业务验收。'))
        return dict(format='markdown',content='\n'.join(lines)+'\n',export_kind='private_skill_draft')
