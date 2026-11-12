"""Scoped evidence contracts, read-only gates and local artifact handoffs.

Configured roles are job contracts, not running models. No outbound I/O.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import html
import json
import os
import re
import shutil
import uuid
from operations_analysis import unit_economics, number
from organization_gate import evaluate
from research import canonical, digest, validate as research_check

ROOT=Path(__file__).resolve().parent
UNGUARDED=object()
def stamp():return datetime.now(timezone.utc).isoformat()
def bytes_sha(value):return hashlib.sha256(value).hexdigest()


class Organization:
    def __init__(self, service):
        self.service=service;self.core=service.core;self.state=service.state/'organization'
        self.contract=json.loads((ROOT/'organization/org.json').read_text())
        roles={r['id'] for r in self.contract['roles']};stages={s['id']:s for s in self.contract['stages']}
        if len(roles)!=12 or set(stages)!={f'S{i}'for i in range(12)}:raise ValueError('organization_contract_incomplete')
        seen=set()
        for stage in self.contract['stages']:
            if stage['role']not in roles or not set(stage['depends_on'])<=seen:raise ValueError('organization_dependency_not_topological')
            seen.add(stage['id'])
        self.contract_sha=digest(canonical(self.contract))
        with self.core.db()as db:
            db.execute('CREATE TABLE IF NOT EXISTS org_cases(id TEXT PRIMARY KEY,connection TEXT,row_key TEXT,scope TEXT,currency TEXT,created TEXT,UNIQUE(connection,row_key))')
            db.execute('CREATE TABLE IF NOT EXISTS org_artifacts(id TEXT PRIMARY KEY,case_id TEXT,kind TEXT,idem TEXT,payload TEXT,sha TEXT,created TEXT,UNIQUE(case_id,kind,idem))')
            db.execute('CREATE TABLE IF NOT EXISTS org_boards(id TEXT PRIMARY KEY,case_id TEXT,payload TEXT,sha TEXT,created TEXT)')
        from organization_exchange import OrganizationExchange
        self.exchange=OrganizationExchange(self)

    def cases(self):
        connection=self.service.live.config().get('connection_id','')
        with self.core.db()as db:rows=db.execute('SELECT id,scope,currency,created FROM org_cases WHERE connection=? ORDER BY created,id',(connection,)).fetchall()
        return [dict(id=r[0],scope=json.loads(r[1]),currency=r[2],created_at=r[3])for r in rows]

    def case(self, case_id):
        case=next((c for c in self.cases()if c['id']==case_id),None)
        if not case:raise ValueError('organization_case_not_found')
        return case

    def import_inventory(self):
        config=self.service.live.config();connection=config.get('connection_id')
        if not connection:raise ValueError('configure_ozon_first')
        snapshot=self.service.live.snapshot(connection,'stock')
        if not snapshot:raise ValueError('fetch_inventory_first')
        for row in self.service.live.inventory_rows():
            scope=dict(platform='ozon',market='RU',fulfillment=config['fulfillment_modes'],product_id=row['product_id'],row_key=row['key'],sku=row['offer_id']or row['sku']or row['product_id'],inventory_type=row['type'],origin='inventory_scope_not_independently_verified',import_snapshot_sha256=snapshot['sha256'])
            with self.core.db()as db:db.execute('INSERT OR IGNORE INTO org_cases VALUES (?,?,?,?,?,?)',(uuid.uuid4().hex,connection,row['key'],canonical(scope),None,stamp()))
        return dict(cases=self.cases(),external_operations_executed=False)

    def set_currency(self, case_id, currency):
        self.case(case_id)
        if not isinstance(currency,str)or not re.fullmatch('[A-Z]{3}',currency):raise ValueError('explicit_currency_required')
        with self.core.db()as db:db.execute('UPDATE org_cases SET currency=? WHERE id=?',(currency,case_id))
        return self.case(case_id)

    def record(self, case_id, kind, payload, idempotency_key, *, _expected_head=UNGUARDED):
        self.case(case_id)
        if kind not in ('research','supply','economics'):raise ValueError('unsupported_organization_record_kind')
        if not isinstance(payload,dict)or not isinstance(idempotency_key,str)or not 1<=len(idempotency_key)<=160:raise ValueError('invalid_organization_record')
        if kind=='supply':
            if set(payload)-{'currency','purchase_cost','lead_time_days','supplier','source_ref'}:raise ValueError('invalid_supply_fields')
            for k in ('purchase_cost','lead_time_days'):
                if payload.get(k)is not None:number(payload[k],k,maximum=365 if k=='lead_time_days'else 10**12,integer=k=='lead_time_days')
            for k in ('currency','supplier','source_ref'):
                if payload.get(k)is not None and (not isinstance(payload[k],str)or len(payload[k])>1000):raise ValueError('invalid_supply_text')
        if kind=='economics':unit_economics(payload)
        if kind=='research':
            if set(payload)-{'record','sku','row_key'}:raise ValueError('invalid_research_binding')
            research_check(payload.get('record'))
            case=self.case(case_id)
            if payload.get('sku')!=case['scope']['sku']or payload.get('row_key')!=case['scope']['row_key']:raise ValueError('research_scope_mismatch')
        return self._store(case_id,kind,payload,idempotency_key,_expected_head=_expected_head)

    def _store(self, case_id, kind, payload, key, *, _expected_head=UNGUARDED):
        value=canonical(payload)
        if len(value.encode())>120000:raise ValueError('organization_artifact_too_large')
        sha=digest(value)
        with self.core.db()as db:
            if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT id,sha FROM org_artifacts WHERE case_id=? AND kind=? AND idem=?',(case_id,kind,key)).fetchone()
            if not prior and _expected_head is not UNGUARDED:
                head=db.execute('SELECT id FROM org_artifacts WHERE case_id=? AND kind=? ORDER BY created DESC,id DESC LIMIT 1',(case_id,kind)).fetchone()
                if (head[0]if head else None)!=_expected_head:raise ValueError('exchange_source_head_changed')
            db.execute('INSERT OR IGNORE INTO org_artifacts VALUES (?,?,?,?,?,?,?)',(uuid.uuid4().hex,case_id,kind,key,value,sha,stamp()))
            row=db.execute('SELECT id,sha FROM org_artifacts WHERE case_id=? AND kind=? AND idem=?',(case_id,kind,key)).fetchone()
        if row[1]!=sha:raise ValueError('organization_idempotency_conflict')
        return dict(id=row[0],sha256=sha,kind=kind,case_id=case_id,verification='caller_supplied_not_independently_verified',external_operations_executed=False)

    def artifact(self, case_id, kind):
        with self.core.db()as db:row=db.execute('SELECT id,payload,sha,created FROM org_artifacts WHERE case_id=? AND kind=? ORDER BY created DESC,id DESC LIMIT 1',(case_id,kind)).fetchone()
        if not row:return None
        payload=json.loads(row[1]);return dict(id=row[0],payload=payload,sha256=row[2],created_at=row[3],intact=digest(canonical(payload))==row[2])

    def deliver(self, case_id, project_id, asset_ids, idempotency_key, *, _expected_head=UNGUARDED):
        case=self.case(case_id)
        if not isinstance(asset_ids,list)or not 1<=len(asset_ids)<=20 or any(not isinstance(a,str)or not re.fullmatch('[a-f0-9]{32}',a)for a in asset_ids)or len(set(asset_ids))!=len(asset_ids):raise ValueError('select_distinct_image_assets')
        if not isinstance(idempotency_key,str)or not 1<=len(idempotency_key)<=160:raise ValueError('invalid_idempotency_key')
        project=self.service.creative.get(project_id);files=[]
        for ident in asset_ids:
            path,meta,kind=self.service.creative.asset(project_id,ident)
            if kind not in ('product_image','generated_image')or path.suffix.lower()not in ('.png','.jpg','.jpeg'):raise ValueError('registered_product_images_required')
            raw=path.read_bytes()
            if len(raw)>32*1024*1024 or bytes_sha(raw)!=meta.get('sha256'):raise ValueError('source_image_hash_mismatch')
            files.append((ident,path,raw,meta))
        if sum(len(f[2])for f in files)>64*1024*1024:raise ValueError('image_delivery_too_large')
        spec=dict(case_id=case_id,project_id=project_id,revision=project['revision'],assets=[dict(id=i,sha256=bytes_sha(raw))for i,p,raw,m in files])
        with self.core.db()as db:old=db.execute("SELECT payload FROM org_artifacts WHERE case_id=? AND kind='images' AND idem=?",(case_id,idempotency_key)).fetchone()
        if old:
            prior=json.loads(old[0]);prior_spec=dict(case_id=case_id,project_id=prior['project_id'],revision=prior['project_revision'],assets=[dict(id=f['asset_id'],sha256=f['sha256'])for f in prior['files']])
            if prior_spec!=spec:raise ValueError('organization_idempotency_conflict')
        token=digest(canonical(spec))[:32];relative=Path('outbox/listing')/case_id/token;destination=self._path(relative)
        self.state.mkdir(exist_ok=True,parents=True,mode=0o700)
        destination.mkdir(parents=True,exist_ok=True,mode=0o700)
        manifest=dict(case_id=case_id,scope=case['scope'],project_id=project_id,project_revision=project['revision'],synthetic_source=bool(project['brief'].get('synthetic')),files=[],claim='仅校验本机交付完整性，未验证图集数量、平台规格、使用权或商品真实性。')
        for i,source,raw,meta in files:
            target=destination/(i+source.suffix.lower())
            if target.is_symlink():raise ValueError('unsafe_delivery_path')
            if target.exists()and bytes_sha(target.read_bytes())!=bytes_sha(raw):raise ValueError('delivered_file_changed')
            if not target.exists():self._write(target,raw)
            manifest['files'].append(dict(asset_id=i,relative_path=str(relative/target.name),sha256=bytes_sha(raw),size=len(raw),usage_scope=meta.get('usage_scope','not_independently_verified')))
        result=self._store(case_id,'images',manifest,idempotency_key,_expected_head=_expected_head)
        self._write(destination/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode())
        return dict(**result,file_count=len(files),delivery='local_outbox_only',marketplace_writes=False)

    def _path(self, relative):
        relative=Path(relative)
        if relative.is_absolute()or'..'in relative.parts:raise ValueError('unsafe_delivery_path')
        path=self.state/relative
        if self.state.is_symlink():raise ValueError('unsafe_delivery_path')
        for part in [self.state,*path.parents,path]:
            if part.is_symlink():raise ValueError('unsafe_delivery_path')
        if not path.resolve().is_relative_to(self.state.resolve()):raise ValueError('unsafe_delivery_path')
        return path

    def _write(self, path, raw):
        if self.state.is_symlink():raise ValueError('unsafe_delivery_path')
        self.state.mkdir(exist_ok=True,parents=True,mode=0o700)
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if path.is_symlink():raise ValueError('unsafe_delivery_path')
        temporary=path.with_name(uuid.uuid4().hex+'.tmp')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb')as f:f.write(raw)
        os.replace(temporary,path)

    def board(self, case_id=None):
        cases=self.cases();case=self.case(case_id)if case_id else cases[0]if cases else None
        ident=case['id']if case else '';scope=case['scope']if case else {};artifacts={k:self.artifact(ident,k)for k in ('research','supply','economics','images')}
        stages=[];by_id={};live=self.service.live.status()
        with self.core.db()as db:
            database_ok=db.execute('SELECT 1').fetchone()[0]==1
            previous=db.execute('SELECT id,payload,sha FROM org_boards WHERE case_id=? ORDER BY created DESC,id DESC LIMIT 1',(ident,)).fetchone()
        for spec in self.contract['stages']:
            checks=[];sid=spec['id'];role=spec['role']
            def add(key,state,detail,verify,evidence=None):checks.append(dict(id=key,state=state,detail=detail,owner=role,verify=verify,evidence=evidence or []))
            def proof(ref,data):return [dict(ref=ref,sha256=digest(canonical(data)))]
            def stored(kind):
                item=artifacts[kind]
                if not item:add('artifact','HOLD','缺少 '+kind+' 岗位产物','补齐对应工作项产物后重新运行门禁');return None
                if not item['intact']:add('artifact','FAIL','已存产物哈希不一致','恢复原始证据并重新交付');return None
                return item
            if sid=='S0':
                add('database','PASS'if database_ok else'FAIL','本机数据库读取检查','重新读取本机数据库',proof('local:database',{'reachable':database_ok}))
                add('contract','PASS','12 岗位与依赖契约已验证','校验契约版本和拓扑顺序',[dict(ref='organization/org.json',sha256=self.contract_sha)])
            elif sid in ('S1','S5'):
                item=stored('research')
                if item:
                    research=item['payload']['record'];checked=research_check(research);same=research.get('platform')==scope.get('platform')and research.get('market')==scope.get('market')and item['payload'].get('sku')==scope.get('sku')and item['payload'].get('row_key')==scope.get('row_key')
                    add('research','PASS'if not checked['issues']and same else'HOLD','原文/中文/来源完整性通过，尚非独立事实核实'if not checked['issues']and same else'采集缺项、译文待校对或平台市场不匹配','补齐采集模板、中文校对、来源并核对平台和市场',[dict(ref='artifact:'+item['id'],sha256=item['sha256'])])
                    if not same:add('scope','FAIL','调研平台或市场与工作项不一致','按当前工作项重新采集')
            elif sid=='S3':
                item=stored('supply')
                if item:
                    data=item['payload'];complete=all(data.get(k)is not None and data.get(k)!=''for k in ('purchase_cost','lead_time_days','supplier','source_ref','currency'))
                    same=bool(case and case['currency']and data.get('currency')==case['currency'])
                    add('supply','PASS'if complete and same else'HOLD','供应商成本交期资料完整（操作者提供，未独立核实）'if complete and same else'缺采购成本、交期、供应商、来源或明确币种','补齐含币种的供应链资料，并设置当前工作项币种',[dict(ref='artifact:'+item['id'],sha256=item['sha256'])])
                    if case and case['currency']and data.get('currency')and not same:add('currency','FAIL','供应链币种与工作项币种不同','核对原始金额币种，不按字段名猜测或自动换算')
            elif sid=='S2':
                item=stored('economics');supply=artifacts['supply']
                if item:
                    data=item['payload'];result=unit_economics(data);same=bool(case and case['currency']and data.get('currency')==case['currency'])
                    matched=bool(supply and supply['intact']and supply['payload'].get('currency')==data.get('currency')and supply['payload'].get('purchase_cost')==data.get('purchase_cost'))
                    state='HOLD'if result['status']!='CALCULATED'or not same or not matched else'FAIL'if result['contribution']<=0 else'PASS'
                    add('contribution',state,'贡献不为正，需给出调整方案'if state=='FAIL'else'测算输入完整且与供应链成本币种一致'if state=='PASS'else'成本缺项、币种未确认或与供应链来源不匹配','使用同一 SKU、明确币种和供应链采购成本重新测算',[dict(ref='artifact:'+item['id'],sha256=item['sha256'])])
                    if case and case['currency']and data.get('currency')and not same:add('currency','FAIL','测算币种与工作项不同','核对来源币种，禁止默认换算')
            elif sid=='S4':
                item=stored('images')
                if item:
                    files=item['payload'].get('files',[]);valid=bool(files)
                    for f in files:
                        try:
                            path=self._path(f['relative_path']);valid=valid and path.is_file()and bytes_sha(path.read_bytes())==f['sha256']
                            source,meta,_=self.service.creative.asset(item['payload']['project_id'],f['asset_id'])
                            valid=valid and bytes_sha(source.read_bytes())==f['sha256']and meta.get('sha256')==f['sha256']
                            manifest_path=self._path(Path(f['relative_path']).parent/'manifest.json')
                            valid=valid and manifest_path.is_file()and digest(canonical(json.loads(manifest_path.read_text())))==item['sha256']
                        except (ValueError,OSError):valid=False
                    try:current=self.service.creative.get(item['payload']['project_id']);valid=valid and current['revision']==item['payload']['project_revision']
                    except ValueError:valid=False
                    add('delivery','PASS'if valid else'FAIL','本机图集交付文件和版本一致；尚未证明平台规格或使用权'if valid else'交付文件缺失、哈希变化或创意版本已更新','从已登记且对应本工作项的图片重新交付，校验交付目录和版本',[dict(ref='artifact:'+item['id'],sha256=item['sha256'])])
                    if item['payload'].get('synthetic_source'):add('synthetic','HOLD','素材项目标为合成验收资料，不能冒充真实商品交付','为真实工作项提供明确对应的真实产品资料和素材')
            elif sid=='S8':
                candidate=next((r for r in self.service.live_plans.candidates()if r['key']==scope.get('row_key')),None)
                ok=bool(candidate and candidate['fresh']and candidate['available']is not None and live['orders']['fresh']and live['orders_scope_confirmed'])
                add('snapshot','PASS'if ok else'HOLD','订单和库存快照已核对；不代表已实际发货'if ok else'快照缺失、已过期、范围或可售口径未确认','重新同步并核对相同产品 ID、履约范围和可售口径',([dict(ref='Ozon:orders',sha256=live['orders']['sha256']),dict(ref='Ozon:stock',sha256=live['stock']['sha256'])]if ok else[]))
            elif sid=='S11':
                intact=bool(previous and digest(previous[1])==previous[2])
                add('comparison','PASS'if intact else'FAIL'if previous else'HOLD','上轮体检快照可读取并验证哈希'if intact else'上轮快照哈希不一致'if previous else'尚未保存本工作项的体检基线','保存本轮体检，再对比上轮门禁与缺项',([dict(ref='board:'+previous[0],sha256=previous[2])]if intact else[]))
            else:
                detail={'S6':'尚未实现独立合规判定，采集字段完整不能代替平台/类目规则与资质核查','S7':'尚未接入实际广告归因与消耗，不能把未知广告费记为零','S9':'尚未接入带来源的真实评论或客服资料，不能把缺数据记为零差评','S10':'尚未接入真实结算对账，成本草稿不能冒充结算'}[sid]
                add('capability','BLOCKED',detail,'补充该岗位真实来源与受支持的核查适配器后重跑本段')
            for dependency in spec['depends_on']:
                if by_id[dependency]['status']!='PASS':checks.append(dict(id='upstream:'+dependency,state='BLOCKED',detail='上游 '+dependency+' 尚未交付可用产物；本段仍可独立补资料',owner=by_id[dependency]['role'],verify='完成上游产物并重新验证对应门禁',evidence=[]))
            result=evaluate(checks);stage=dict(**spec,**result,checks=checks);stages.append(stage);by_id[sid]=stage
        changes=[]
        if previous and digest(previous[1])==previous[2]:
            old={s['id']:s['status']for s in json.loads(previous[1])['stages']}
            changes=[dict(stage=s['id'],before=old.get(s['id']),after=s['status'])for s in stages if old.get(s['id'])!=s['status']]
        passed=sum(s['status']=='PASS'for s in stages)
        return dict(schema='organization-board-v1',case=case,cases=cases,roles=self.contract['roles'],stages=stages,passed=passed,total=len(stages),gate_pass_rate=round(passed/len(stages)*100,1),generated_at=stamp(),contract_sha256=self.contract_sha,changes=changes,feishu='user_deferred',external_execution=False,notice='门禁通过仅表示本轮受支持检查通过；不是销量、转化、合规或商业闭环成功率。角色配置不代表 12 个模型进程正在运行。')

    def brief(self, case_id, stage_id):
        board=self.board(case_id);stage=next((s for s in board['stages']if s['id']==stage_id),None)
        if not stage:raise ValueError('invalid_organization_stage')
        role=next(r for r in self.contract['roles']if r['id']==stage['role'])
        return dict(case=board['case'],stage=stage,role=role,expected_artifact=stage['artifact_kind'],source_contract_sha256=self.contract_sha,execution='local_draft_only',authority='仅沿用已有授权；门禁或岗位均不授予外部执行权。')

    def handoff(self, case_id, stage_id):
        brief=self.brief(case_id,stage_id)
        if brief['stage']['status']=='PASS':return dict(status='already_passed',task=None)
        fingerprint=digest(canonical({'case':brief['case'],'stage':brief['stage'],'contract':self.contract_sha}))
        task=self.core.invoke('commerce_task_create',{'idempotency_key':'org:'+case_id+':'+stage_id+':'+fingerprint,'kind':'analysis','input':{'title':stage_id+' · '+brief['role']['name']+' · 补齐产物契约','agent_role':brief['role']['id'],'organization_case':case_id,'organization_stage':stage_id,'gaps':brief['stage']['gaps'],'expected_artifact':brief['expected_artifact'],'evidence_fingerprint':fingerprint,'execution':'not_requested'}})
        return dict(status='local_task_created',task=task,gate_closed=False,external_execution=False)

    def capture(self, case_id=None):
        board=self.board(case_id);ident=uuid.uuid4().hex;value=canonical(board);case=board['case'];case_id=case['id']if case else''
        with self.core.db()as db:db.execute('INSERT INTO org_boards VALUES (?,?,?,?,?)',(ident,case_id,value,digest(value),stamp()))
        folder=self._path(Path('boards')/(case_id or'project')/ident);self._write(folder/'board.json',json.dumps(board,ensure_ascii=False,indent=2).encode())
        lines=['# 岗位与闭环体检',board['notice'],f"门禁通过率：{board['passed']}/{board['total']}（{board['gate_pass_rate']}%）"]
        for stage in board['stages']:
            lines.append(f"\n## {stage['id']} {stage['name']} · {stage['status']}")
            lines.extend(f"- 缺项：{g['reason']}；责任：{g['owner']}；复验：{g['verify']}"for g in stage['gaps'])
        self._write(folder/'board.md','\n'.join(lines).encode())
        body='<h1>岗位与闭环体检</h1><p>'+html.escape(board['notice'])+'</p>'+''.join('<section class="card"><h2>'+html.escape(s['id']+' '+s['name']+' · '+s['status'])+'</h2>'+''.join('<p>'+html.escape(g['reason']+'；责任：'+g['owner']+'；复验：'+g['verify'])+'</p>'for g in s['gaps'])+'</section>'for s in board['stages'])
        document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>岗位体检</title><style>'+(ROOT/'web/style.css').read_text()+'</style><main class="setup-shell">'+body+'</main></html>'
        self._write(folder/'board.html',document.encode())
        return dict(id=ident,sha256=digest(value),board=board,files=['board.json','board.md','board.html'],location='private:organization/boards/'+(case_id or'project')+'/'+ident,external_execution=False)
