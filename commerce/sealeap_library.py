"""Pinned skill coverage, bounded source reading and explicit offline execution."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from coverage_rules import state as coverage_state
from sealeap_ingest import canonical, sha, audit_script
from sealeap_offline import tree_for
from sealeap_modes import selected_mode,mode_plan
from sealeap_contracts import input_template

ROOT=Path(__file__).resolve().parent


def definitions(schema,string):
    skill={'type':'string','minLength':1,'maxLength':160,'pattern':'^sealeap-[a-z0-9-]+$'}
    return [
      ('commerce_skills_status','读取固定版本能力库与覆盖分层；源码已读取不等于业务验证',schema()),
      ('commerce_skills_search','搜索两库全部技能及逐项接入缺口；分类为自动归纳，需结合原文',schema({'query':{'type':'string','maxLength':120},'repo':{'type':'string','enum':['all','ecommerce','amazon']},'platform':{'type':'string','maxLength':30},'area':{'type':'string','enum':['all','research','advertising','inventory','creative','operations']},'execution':{'type':'string','enum':['all','unmapped','adapter_ready','local_verified','live_verified']},'offset':{'type':'integer','minimum':0,'maximum':10000},'limit':{'type':'integer','minimum':1,'maximum':50}})),
      ('commerce_skills_get','读取技能流程、来源哈希、依赖、样例及完整引用清单',schema({'skill_id':skill},['skill_id'])),
      ('commerce_skills_read','只读取该技能登记并通过哈希检查的参考文件；不执行文件内容',schema({'skill_id':skill,'path':{'type':'string','minLength':1,'maxLength':400}},['skill_id','path'])),
      ('commerce_skills_prepare','创建具备来源版本的本机任务；细分模式独立检查工具与字段，不执行外部操作',schema({'skill_id':skill,'mode_id':skill,'input':{'type':'object'},'idempotency_key':string,'synthetic':{'type':'boolean'}},['skill_id','input','idempotency_key'])),
      ('commerce_skills_execute','明确执行该任务对应的已审查离线JSON计算器；不调用平台API或提交变更',schema({'case_id':string},['case_id'])),
      ('commerce_skills_case_get','读取同一任务输入、结果、状态及来源；未知或中断不会自动重发',schema({'case_id':string},['case_id'])),
      ('commerce_skills_cases','读取最近本机技能任务；执行范围与合成数据保持标注',schema()),
      ('commerce_skills_export','导出全量覆盖清单CSV或JSON；本机验证不等于完整技能验收',schema({'format':{'type':'string','enum':['json','csv']}},[])),
      ('commerce_skills_generate','按所选技能和已提供依据请求既有模型生成结构化草稿；不执行平台操作',schema({'case_id':string,'idempotency_key':string},['case_id','idempotency_key'])),
      ('commerce_skills_draft_get','读取草稿、来源引用、缺项及待审阅状态，不自动重发',schema({'draft_id':string},['draft_id'])),
      ('commerce_skills_draft_cancel','请求取消本机草稿任务；模型请求可能已发生，未知不重发',schema({'draft_id':string},['draft_id'])),
      ('commerce_skills_draft_export','导出私有草稿和引用，支持JSON和Markdown，不发布内容',schema({'draft_id':string,'format':{'type':'string','enum':['json','markdown']}},['draft_id'])),
      ('commerce_skills_draft_review','按结果哈希记录调用者审阅；不是独立事实核查或平台操作授权',schema({'draft_id':string,'result_sha256':string,'decision':{'type':'string','enum':['accept','reject']},'note':{'type':'string','maxLength':500}},['draft_id','result_sha256','decision']))]


class SkillLibrary:
    def __init__(self,core,state,tool_catalog=None):
        self.tool_catalog=tool_catalog or (lambda:[])
        self.core=core;self.private=Path(state).resolve()/'sealeap';self.private.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.source_root=Path(os.environ.get('SEALEAP_SOURCE_ROOT',str(ROOT.parent/'.local/sealeap-sources'))).resolve()
        self.catalog=json.loads((ROOT/'sealeap/catalogue.json').read_text());self.entries={r['id']:r for r in self.catalog['skills']}
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sealeap_cases(id TEXT PRIMARY KEY,idem TEXT UNIQUE,frozen TEXT,skill TEXT,source_sha TEXT,adapter TEXT,status TEXT,output TEXT,created TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS sealeap_receipts(id TEXT PRIMARY KEY,skill TEXT,source_sha TEXT,adapter TEXT,outcome TEXT,level TEXT,scope TEXT)')
            db.execute("UPDATE sealeap_cases SET status='interrupted',output=? WHERE status='running'",(canonical({'error':'local_execution_interrupted_query_before_manual_new_case'}),))
        from sealeap_drafts import SkillDrafts
        self.drafts=SkillDrafts(self)

    def entry(self,skill):
        if skill not in self.entries:raise ValueError('sealeap_skill_not_found')
        return self.entries[skill]

    def source_file(self,e,relative):
        f=next((f for f in e['files'] if f['path']==relative),None)
        if f is None:raise ValueError('sealeap_reference_not_registered')
        base=self.source_root/e['repo']/Path(e['path']).parent
        target=base/relative
        if any(p=='..' for p in Path(relative).parts) or target.is_symlink() or not target.resolve().is_relative_to(base.resolve()) or not target.is_file():raise ValueError('sealeap_source_missing_or_unsafe')
        if target.stat().st_size!=f['bytes'] or sha(target.read_bytes())!=f['sha256']:raise ValueError('sealeap_source_integrity_changed')
        return target

    def verify(self,e):
        try:
            for f in e['files']:self.source_file(e,f['path'])
            return True
        except (OSError,ValueError):return False

    def receipts(self):
        with self.core.db() as db:rows=db.execute('SELECT skill,source_sha,adapter,outcome,level,scope FROM sealeap_receipts').fetchall()
        return [dict(skill_id=r[0],source_sha256=r[1],adapter=r[2],outcome=r[3],level=r[4],scope=r[5]) for r in rows]

    def coverage(self,e,receipts,verify=True):
        adapter=e.get('adapter')
        return coverage_state(dict(id=e['id'],integrity=self.verify(e) if verify or adapter else (self.source_root/e['repo']).is_dir(),source_sha256=e['source_sha256'],inspected=True,adapter=adapter['id'] if adapter else None),receipts)

    def summary(self):
        receipts=self.receipts();levels=Counter(self.coverage(e,receipts,False)['execution'] for e in self.entries.values())
        contracts=[e['draft_contract'] for e in self.entries.values() if e.get('draft_contract')]
        with self.core.db() as db:model_samples=db.execute("SELECT count(DISTINCT case_id) FROM sealeap_drafts WHERE status IN ('awaiting_review','needs_inputs') AND json_extract(result,'$.sections') IS NOT NULL").fetchone()[0]
        return dict(total=len(self.entries),nested_modes=len(self.catalog.get('subcapabilities',[])),draft_workflow_entries=len(contracts),draft_families=dict(Counter(c['family'] for c in contracts)),model_draft_cases=model_samples,sources=self.catalog['sources'],platforms=dict(Counter(e['platform'] for e in self.entries.values())),areas=dict(Counter(e['area'] for e in self.entries.values())),execution=dict(levels),offline_adapters=sum(bool(e['adapter']) for e in self.entries.values()),
          source_review='all_package_texts_read_and_structurally_indexed_not_semantic_mastery',
          limits=['Local verification is scoped to a specific offline script and supplied inputs, not the entire skill or account readiness.','Statistics use installed catalogue; individual reads/executions recheck package hashes.','No platform changes, advertising or messages are submitted.'])

    def search(self,args):
        for name,default,low,high in [('offset',0,0,10000),('limit',20,1,50)]:
            value=args.get(name,default)
            if type(value) is not int or not low<=value<=high:raise ValueError('sealeap_invalid_pagination')
        query=args.get('query','').casefold().split();receipts=self.receipts();found=[]
        for e in self.entries.values():
            if args.get('repo','all') not in ['all',e['repo']] or args.get('platform','all') not in ['all','',e['platform']] or args.get('area','all') not in ['all',e['area']]:continue
            haystack=(' '.join([e['id'],e['title'],e['description'],*e['external_prerequisites'],*[m['name']+' '+m['title']+' '+m['description'] for m in e.get('subcapabilities',[])]] )).casefold()
            if any(term not in haystack for term in query):continue
            # All executable entries are rehashed even in list/statistics views;
            # catalogue-only rows describe historical structural review.
            coverage=self.coverage(e,receipts,False)
            if args.get('execution','all') not in ['all',coverage['execution']]:continue
            found.append({k:e[k] for k in ['id','repo','platform','area','title','description','source_url','source_sha256','workbench_entry','business_gaps']}|dict(coverage=coverage,has_adapter=bool(e['adapter']),draft_family=(e.get('draft_contract') or {}).get('label'),nested_modes=len(e.get('subcapabilities',[]))))
        offset=args.get('offset',0);limit=args.get('limit',20)
        return dict(total=len(found),offset=offset,limit=limit,items=found[offset:offset+limit],next_offset=offset+limit if offset+limit<len(found) else None)

    def get(self,skill):
        e=self.entry(skill);integrity=self.verify(e)
        result=dict(e,coverage=self.coverage(e,self.receipts()),integrity=integrity,skill_text=None,example_input=None,draft_input_template=input_template(e) if e.get('draft_contract') else None)
        if integrity:
            result['skill_text']=self.source_file(e,'SKILL.md').read_text()
            if e.get('example'):result['example_input']=json.loads(self.source_file(e,e['example']).read_text())
            elif e.get('example_input_inline') is not None:result['example_input']=json.loads(canonical(e['example_input_inline']))
        return result

    def read(self,skill,path):
        e=self.entry(skill);p=self.source_file(e,path)
        if p.stat().st_size>160000:raise ValueError('sealeap_reference_too_large_read_upstream')
        return dict(skill_id=skill,path=path,content=p.read_text(),sha256=sha(p.read_bytes()),reference_data_not_execution_authority=True)

    def case(self,ident):
        with self.core.db() as db:r=db.execute('SELECT id,frozen,skill,source_sha,adapter,status,output,created FROM sealeap_cases WHERE id=?',(ident,)).fetchone()
        if not r:raise ValueError('sealeap_case_not_found')
        data=json.loads(r[1]);return dict(id=r[0],skill_id=r[2],mode_id=data.get('mode_id'),mode_sha256=data.get('mode_sha256'),source_sha256=r[3],adapter=r[4],status=r[5],output=json.loads(r[6]) if r[6] else None,created_at=r[7],input=data['input'],synthetic=data['synthetic'],drafts=self.drafts.list_for_case(r[0]),marketplace_writes=False)

    def prepare(self,args):
        e=self.entry(args['skill_id'])
        if not self.verify(e):raise ValueError('sealeap_source_integrity_changed')
        mode=selected_mode(e,args.get('mode_id'))
        data=dict(skill_id=e['id'],source_sha256=e['source_sha256'],input=args['input'],synthetic=args.get('synthetic',False))
        if mode:data.update(mode_id=mode['name'],mode_sha256=sha(canonical(mode).encode()))
        frozen=canonical(data)
        if len(frozen)>96000:raise ValueError('sealeap_input_too_large')
        adapter=e['adapter']['id'] if e['adapter'] else ''
        output=dict(kind='workflow_preparation_not_business_result',source_url=e['source_url'],workflow=e['sections'],
           required_next=['核对技能输入与参考资料','提供同口径数据并核对当前平台条件'],
           references=[f['path'] for f in e['files'] if f['path'].endswith('.md')],
           related_tools={'creative':['commerce_creative_create'],'research':['commerce_collection_template'],'inventory':['commerce_restock_plan'],'advertising':['commerce_campaign_compare'],'operations':['commerce_unit_economics']}.get(e['area'],[]),
           related_tools_are_partial_analogues=True,external_prerequisites=e['external_prerequisites'])
        if mode:
            output['mode_plan']=mode_plan(mode,args['input'],self.tool_catalog())
            output['mode_workflow']=self.read(e['id'],mode['reference'])
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT id,frozen FROM sealeap_cases WHERE idem=?',(args['idempotency_key'],)).fetchone()
            if old:
                if old[1]!=frozen:raise ValueError('idempotency_conflict')
                return self.case(old[0])
            if db.execute('SELECT count(*) FROM sealeap_cases').fetchone()[0]>=2000:raise ValueError('sealeap_case_limit')
            ident=uuid.uuid4().hex
            db.execute('INSERT INTO sealeap_cases VALUES(?,?,?,?,?,?,?,?,?)',(ident,args['idempotency_key'],frozen,e['id'],e['source_sha256'],adapter,'prepared' if adapter and args['input'] else 'needs_inputs' if adapter else 'guidance_ready',canonical(output),datetime.now(timezone.utc).isoformat()))
        return self.case(ident)

    def execute(self,ident):
        case=self.case(ident);e=self.entry(case['skill_id'])
        if not e['adapter']:return case # No speculative mapping or external execution.
        if case['status'] not in ['prepared','needs_inputs']:return case
        if not self.verify(e) or e['source_sha256']!=case['source_sha256']:raise ValueError('sealeap_source_integrity_changed')
        if case['adapter']!=e['adapter']['id']:raise ValueError('sealeap_adapter_changed_prepare_new_case')
        if not case['input']:return case
        script=self.source_file(e,e['adapter']['script'])
        if e['adapter'].get('runner'):
            tree_for(e['adapter']['runner'],script.read_text())
            if sha((ROOT/'sealeap_offline.py').read_bytes())!=e['adapter']['worker_sha256']:raise ValueError('sealeap_worker_changed_rebuild_required')
        else:audit_script(script.read_text())
        if sha(script.read_bytes())!=e['adapter']['script_sha256']:raise ValueError('sealeap_script_changed')
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            updated=db.execute("UPDATE sealeap_cases SET status='running' WHERE id=? AND status='prepared'",(ident,)).rowcount
        if not updated:return self.case(ident)
        folder=self.private/ident;folder.mkdir(mode=0o700,exist_ok=True);input_file=folder/'input.json'
        input_file.write_text(canonical(case['input']));input_file.chmod(0o600)
        if e['adapter'].get('runner'):
            argv=[sys.executable,'-I',str(ROOT/'sealeap_offline.py'),e['adapter']['runner'],str(script),str(input_file)]
        else:argv=[sys.executable,'-I',str(script)]+(['--input'] if e['adapter']['input_flag'] else [])+[str(input_file)]+e['adapter'].get('extra_args',[])
        try:
            done=subprocess.run(argv,cwd=folder,stdin=subprocess.DEVNULL,capture_output=True,timeout=10,env={'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8'})
            if len(done.stdout)>1500000:raise ValueError('sealeap_output_too_large')
            try:result=json.loads(done.stdout)
            except (ValueError,UnicodeError):raise ValueError('sealeap_invalid_calculator_output') from None
            if not isinstance(result,dict):raise ValueError('sealeap_invalid_calculator_output')
            status='completed' if done.returncode==0 else 'hold' if done.returncode==2 else 'failed'
            outcome='passed' if status=='completed' else 'blocked' if status=='hold' else 'failed'
            output=dict(kind='offline_script_result_not_full_skill_acceptance',result=result,returncode=done.returncode,source_url=e['source_url'],
                synthetic=case['synthetic'],script_sha256=e['adapter']['script_sha256'],adapter_id=e['adapter']['id'],input_sha256=sha(input_file.read_bytes()),
                validation_scope=e['adapter'].get('scope','Offline script on supplied inputs; no current-policy, account or outcome verification.'),external_requests_submitted=False)
        except (ValueError,OSError,subprocess.TimeoutExpired) as error:
            status='interrupted' if isinstance(error,subprocess.TimeoutExpired) else 'failed';outcome='failed'
            output=dict(error=str(error) if isinstance(error,ValueError) else 'sealeap_local_execution_failed_no_automatic_retry')
        with self.core.db() as db:
            db.execute('UPDATE sealeap_cases SET status=?,output=? WHERE id=?',(status,canonical(output),ident))
            db.execute('INSERT INTO sealeap_receipts VALUES(?,?,?,?,?,?,?)',(ident,e['id'],e['source_sha256'],e['adapter']['id'],outcome,'local','synthetic_fixture' if case['synthetic'] else 'caller_supplied_input'))
        return self.case(ident)

    def export(self,format='json'):
        import csv,io
        receipts=self.receipts();rows=[]
        for e in self.entries.values():
            c=self.coverage(e,receipts,False)
            def excerpt(pattern):
                sections=[s['text'] for s in e['sections'] if re.search(pattern,s['heading'],re.I)]
                return re.sub(r'\s+',' ',' '.join(sections))[:1200] or '见技能正文与配套参考；待具体任务核对'
            rows.append(dict(skill_id=e['id'],repo=e['repo'],platform=e['platform'],title=e['title'],area=e['area'],commit=e['commit'],source_sha256=e['source_sha256'],source_review=c['source'],execution=c['execution'],adapter_script=e['adapter']['script'] if e['adapter'] else '',draft_route='commerce_skills_generate' if e.get('draft_contract') else '',draft_contract_sha256=(e.get('draft_contract') or {}).get('sha256',''),draft_family=(e.get('draft_contract') or {}).get('family',''),workbench_entry=e['workbench_entry'],input_contract_preview=(re.sub(r'\s+',' ',' '.join(r['text'] for r in e.get('source_method',{}).get('inputs',[])))[:1200] or (e.get('draft_contract') or {}).get('source_input_excerpt') or excerpt('输入|资料|input')),output_contract_preview=excerpt('交付|输出|output'),method_sha256=e.get('source_method',{}).get('sha256',''),method_extraction_gaps=';'.join(e.get('source_method',{}).get('extraction_gaps',[])),external_prerequisites=';'.join(e['external_prerequisites']),gaps=';'.join(e['business_gaps']),source_url=e['source_url'],validation_scope='offline script only when locally verified; not full skill acceptance'))
        if format=='json':return dict(summary=self.summary(),rows=rows)
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader()
        for row in rows:writer.writerow({k:("'"+str(v) if str(v).startswith(('=','+','-','@')) else v) for k,v in row.items()})
        return dict(format='csv',content=stream.getvalue(),rows=len(rows))

    def invoke(self,name,args):
        action=name.removeprefix('commerce_skills_')
        if action=='status':return self.summary()
        if action=='search':return self.search(args)
        if action=='get':return self.get(args['skill_id'])
        if action=='read':return self.read(args['skill_id'],args['path'])
        if action=='prepare':return self.prepare(args)
        if action=='execute':return self.execute(args['case_id'])
        if action=='case_get':return self.case(args['case_id'])
        if action=='generate':return self.drafts.start(args['case_id'],args['idempotency_key'])
        if action=='draft_get':return self.drafts.get(args['draft_id'])
        if action=='draft_cancel':return self.drafts.cancel(args['draft_id'])
        if action=='draft_export':return self.drafts.export(args['draft_id'],args.get('format','json'))
        if action=='draft_review':return self.drafts.review(args['draft_id'],args['result_sha256'],args['decision'],args.get('note',''))
        if action=='cases':
            with self.core.db() as db:ids=[r[0] for r in db.execute('SELECT id FROM sealeap_cases ORDER BY rowid DESC LIMIT 30')]
            return {'cases':[self.case(i) for i in ids]}
        if action=='export':return self.export(args.get('format','json'))
        raise ValueError('sealeap_unknown_tool')
