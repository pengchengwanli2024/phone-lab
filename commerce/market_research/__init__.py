"""One durable task from explicit chat intent to public evidence and local candidates."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
from research import canonical, digest, template
from research_intent import research_request, requests_research
from . import collector, model

ACTIVE = ('queued', 'running', 'cancelling')
RETRYABLE = ('interrupted', 'failed', 'unknown')


class _SupersededAttempt(Exception):
    """The task has moved on; this worker may read but cannot write it."""


def stamp(): return datetime.now(timezone.utc).isoformat()


def definitions(schema, string):
    task = {'task_id': string}
    return [
        ('commerce_market_research_list', '读取本机公开市场研究任务及候选，不触发采集或模型', schema()),
        ('commerce_market_research_get', '读取同一研究任务、原始来源索引和已保存候选，不重发执行', schema(task, ['task_id'])),
        ('commerce_market_research_cancel', '停止同一研究任务，保留已采集证据与已保存候选', schema(task, ['task_id'])),
        ('commerce_market_research_resume', '明确按修订恢复中断或失败的原研究任务；已确认步骤不重放',
         schema({**task, 'expected_revision': {'type': 'integer', 'minimum': 1}, 'idempotency_key': string},
                ['task_id', 'expected_revision', 'idempotency_key']))]


class MarketResearch:
    def __init__(self, service):
        self.service, self.core = service, service.core
        self.directory = Path(service.state) / 'market-research'
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS market_research_jobs(task_id TEXT PRIMARY KEY, document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS market_research_runs(run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS market_research_retries(task_id TEXT, idem TEXT, request TEXT, PRIMARY KEY(task_id,idem))')

    def invoke(self, name, args):
        return {'commerce_market_research_list': self.listing, 'commerce_market_research_get': self.get,
                'commerce_market_research_cancel': self.cancel, 'commerce_market_research_resume': self.resume}[name](**args)

    def _load(self, db, task_id):
        row = db.execute('SELECT document FROM market_research_jobs WHERE task_id=?', (task_id,)).fetchone()
        if not row: raise ValueError('market_research_task_not_found')
        return json.loads(row[0])

    def _save(self, db, job):
        job['revision'] += 1; job['updated_at'] = stamp()
        job['source_count'] = sum(s['status'] == 'collected' for s in job['sources'])
        job['candidate_count'] = len(job['candidates'])
        db.execute('UPDATE market_research_jobs SET document=? WHERE task_id=?', (canonical(job), job['task_id']))
        db.execute('UPDATE tasks SET status=? WHERE id=?', (job['status'], job['task_id']))

    def public(self, job):
        value={k: v for k, v in job.items() if not k.startswith('_')}
        from research_workspace import workspace_url
        value['candidates'] = [{**candidate, 'research_task_id': job['task_id'],
                                'workspace_url': workspace_url(candidate['case_id'], job['task_id'])}
                               for candidate in job['candidates']]
        if job.get('_execution_hosts'):
            value['execution_hosts']=job['_execution_hosts']
            value['host_attempts']=self.service.host_execution.for_task(job['task_id'])
        return value

    def get(self, task_id):
        with self.core.db() as db: return self.public(self._load(db, task_id))

    def result(self, task_id):
        """Project the original task receipt; never enqueue the generic executor."""
        with self.core.db() as db:
            if not db.in_transaction: db.execute('BEGIN')
            job = self._load(db, task_id)
            task = self.core.present(db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())
            attempts, requested = db.execute('SELECT count(*),min(r.created) FROM market_research_runs m JOIN agent_runs r ON r.id=m.run_id WHERE m.task_id=?', (task_id,)).fetchone()
        content = '已保存 ' + str(job['candidate_count']) + ' 个研究候选；已采集 ' + str(job['source_count']) + ' 个公开来源。'
        if job['report']: content += '\n' + job['report']['summary']
        elif job['questions']: content += '\n' + '\n'.join(job['questions'])
        elif job['error']: content += '\n' + job['error']['message']
        terminal = job['status'] in ('completed', 'partial', 'failed', 'unknown', 'interrupted', 'cancelled')
        return {'task': task, 'execution': {'operation': 'market_research', 'attempt': attempts,
                'requested_at': datetime.fromtimestamp(requested, timezone.utc).isoformat() if requested else None,
                'started_at': None, 'finished_at': job['updated_at'] if terminal else None,
                'status': job['status'], 'result': {'content': content},
                'error': job['error']['code'] if job['error'] else None},
                'research_job': self.public(job), 'external_operations_executed': False}

    def listing(self):
        with self.core.db() as db:
            rows = db.execute('SELECT document FROM market_research_jobs ORDER BY rowid DESC LIMIT 100').fetchall()
        return {'schema': 'commerce-market-research-list-v1', 'jobs': [self.public(json.loads(r[0])) for r in rows]}

    def for_run(self, run_id, db=None):
        if db is None:
            with self.core.db() as connection: return self.for_run(run_id, connection)
        row = db.execute('SELECT task_id FROM market_research_runs WHERE run_id=?', (run_id,)).fetchone()
        return self.public(self._load(db, row[0])) if row else None

    def owns(self, task_id):
        with self.core.db() as db:
            return bool(db.execute('SELECT 1 FROM market_research_jobs WHERE task_id=?', (task_id,)).fetchone())

    def active_for_thread(self, db, thread_id):
        return any(j['thread_id'] == thread_id and j['status'] in ACTIVE
                   for (raw,) in db.execute('SELECT document FROM market_research_jobs') if (j := json.loads(raw)))

    def bind_send(self, db, run_id, thread_id, question, context):
        # Continuation is available only in the same explicitly bound context.
        run_payload=json.loads(db.execute('SELECT payload FROM agent_runs WHERE id=?',(run_id,)).fetchone()[0])
        native_plan=self.service.host_execution.plan_for_payload(run_payload)
        rows = db.execute('SELECT document FROM market_research_jobs ORDER BY rowid DESC LIMIT 100').fetchall()
        prior = next((j for (raw,) in rows if (j := json.loads(raw))['thread_id'] == thread_id
                      and j['status'] == 'awaiting_input' and j['_context'] == context), None)
        if prior:
            if native_plan:prior['_execution_hosts']=native_plan
            prior['query'] = (prior['query'] + '\n补充：' + question)[-4000:]
            prior.update(run_id=run_id, status='queued', phase='planning', questions=[], error=None, _plan=None)
            db.execute('INSERT INTO market_research_runs VALUES (?,?)', (run_id, prior['task_id']))
            self._save(db, prior); return
        # Only the immediately previous human turn may supply missing intent.
        # Match both revision and hash so navigating away/back cannot revive it.
        row = db.execute('''SELECT p.question,r.status,r.result,p.context_sha,p.revision,c.context_sha,c.revision
            FROM copilot_turns p JOIN agent_runs r ON r.id=p.run_id
            JOIN copilot_turns c ON c.run_id=?
            WHERE p.thread_id=? AND p.rowid<c.rowid ORDER BY p.rowid DESC LIMIT 1''', (run_id, thread_id)).fetchone()
        previous = None
        if row and row[3:5] == row[5:7]:
            previous = {'question': row[0], 'status': row[1],
                        'questions': json.loads(row[2] or '{}').get('questions', [])}
        has_research = bool(db.execute('''SELECT 1 FROM market_research_runs m
            JOIN copilot_turns t ON t.run_id=m.run_id WHERE t.thread_id=? LIMIT 1''', (thread_id,)).fetchone())
        question = research_request(question, context, previous=previous, has_research=has_research)
        if question is None: return
        task_id = str(uuid.uuid4()); at = stamp()
        task_payload = {'kind': 'analysis', 'input': {'operation': 'market_research', 'title': question[:100],
                        'query': question, 'market': 'RU', 'thread_id': thread_id, 'demo': False}}
        db.execute('INSERT INTO tasks VALUES (?,?,?,?)',
                   (task_id, 'market-research:' + run_id, json.dumps(task_payload, ensure_ascii=False, sort_keys=True), 'queued'))
        job = {'schema': 'commerce-market-research-v1', 'task_id': task_id, 'run_id': run_id,
               'thread_id': thread_id, 'status': 'queued', 'phase': 'planning', 'revision': 1,
               'query': question, 'market': 'RU', 'source_count': 0, 'candidate_count': 0,
               'error': None, 'questions': [], 'candidates': [], 'sources': [], 'report': None,
               'workspace_url': '/workspace?tab=pilots&research_task_id=' + task_id, 'updated_at': at,
               '_context': context, '_plan': None, '_captures': [], '_analysis': None, '_model_pending': None}
        if native_plan:job['_execution_hosts']=native_plan
        db.execute('INSERT INTO market_research_jobs VALUES (?,?)', (task_id, canonical(job)))
        db.execute('INSERT INTO market_research_runs VALUES (?,?)', (run_id, task_id))

    def cancel(self, task_id):
        with self.core.atomic() as db:
            job = self._load(db, task_id)
            if job['status'] not in ACTIVE: return self.public(job)
            job['status'] = 'cancelled' if job['status'] == 'queued' else 'cancelling'
            db.execute("UPDATE agent_runs SET status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'cancel_requested' END WHERE id=? AND status IN ('queued','running')", (job['run_id'],))
            self._save(db, job)
            return self.public(job)

    def resume(self, task_id, expected_revision, idempotency_key):
        if type(expected_revision) is not int or expected_revision < 1: raise ValueError('market_research_revision_conflict')
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key.strip()) <= 160: raise ValueError('invalid_idempotency_key')
        request = canonical({'expected_revision': expected_revision})
        with self.core.atomic() as db:
            job = self._load(db, task_id)
            old = db.execute('SELECT request FROM market_research_retries WHERE task_id=? AND idem=?', (task_id, idempotency_key)).fetchone()
            if old:
                if old[0] != request: raise ValueError('idempotency_conflict')
                return self.public(job)
            if job['revision'] != expected_revision: raise ValueError('market_research_revision_conflict')
            if job['status'] not in RETRYABLE: raise ValueError('market_research_not_resumable')
            # An unconfirmed model outcome is never replayed silently. This call is
            # explicit authorization; completed capture/analysis checkpoints remain.
            self.service.copilot._idle(db, job['thread_id'])
            thread = self.service.copilot._thread(db, job['thread_id'])
            if thread['context'] != job['_context']: raise ValueError('market_research_context_changed')
            if ((job.get('error') or {}).get('code') == 'market_research_no_product_evidence'
                    and not job['_captures'] and job['sources']
                    and all(s['status'] == 'failed' for s in job['sources'])):
                # Only an explicit resume retries known failed public reads.
                # Keep their receipts and the confirmed plan; analysis recovery
                # never changes the evidence that its request was pinned to.
                job.setdefault('_collection_failures', []).append({'run_id':job['run_id'],'sources':job['sources']})
                job.update(sources=[], phase='collecting')
            source = db.execute('SELECT payload FROM agent_runs WHERE id=?', (job['run_id'],)).fetchone()
            self._queue_successor(db, job, json.loads(source[0]))
            db.execute('INSERT INTO market_research_retries VALUES (?,?,?)', (task_id, idempotency_key, request))
            return self.public(job)

    def _queue_successor(self, db, job, payload):
        run_id = uuid.uuid4().hex; at = time.time()
        db.execute('INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL,?)',
                   (run_id, 'research-resume:' + uuid.uuid4().hex,
                    canonical({'task_id': job['task_id'], 'resume': job['revision']}),
                    canonical(payload), 'queued', at, at, '[]'))
        job.update(run_id=run_id, status='queued', error=None)
        db.execute('INSERT INTO market_research_runs VALUES (?,?)', (run_id, job['task_id']))
        self._save(db, job)

    def recover(self):
        with self.core.atomic() as db:
            for (raw,) in db.execute('SELECT document FROM market_research_jobs').fetchall():
                job = json.loads(raw)
                run = db.execute('SELECT status,payload FROM agent_runs WHERE id=?', (job['run_id'],)).fetchone()
                if job['status'] in ('running', 'cancelling') or (job['status'] == 'queued' and (not run or run[0] != 'queued')):
                    payload = json.loads(run[1]) if run else {}
                    if job.get('_execution_hosts') and self.service.host_execution.plan_for_payload(payload) == job['_execution_hosts']:
                        outcome = self.service.host_execution.recover(db, job['run_id'])
                        cancelled = job['status'] == 'cancelling' or run[0] == 'cancel_requested'
                        context_matches = self.service.copilot._thread(db, job['thread_id'])['context'] == job['_context']
                        # Fence the old parent before exposing any successor to
                        # the runner. The frozen plan authorizes known boundaries
                        # only; unconfirmed native admission requires resume.
                        state = 'cancelled' if cancelled else ('unknown' if outcome == 'unknown' else 'interrupted')
                        code = 'agent_provider_outcome_unknown' if state == 'unknown' else 'agent_interrupted_no_automatic_resubmit'
                        db.execute('UPDATE agent_runs SET status=?,expires=0,updated=?,result=? WHERE id=?',
                                   (state, time.time(), canonical({'error': code}), job['run_id']))
                        if cancelled:
                            job.update(status='cancelled', error={'code':'market_research_cancelled','message':'执行已停止，已确认产物保留。'})
                        elif outcome == 'unknown':
                            job.update(status='unknown', error={'code':code,'message':'宿主请求结果未确认；已确认步骤保留，需显式恢复原任务。'})
                        elif not context_matches:
                            job.update(status='interrupted', error={'code':'market_research_context_changed','message':'对话范围已变化；不会自动恢复执行。'})
                        else:
                            self._queue_successor(db, job, payload)
                            continue
                        self._save(db, job)
                        continue
                    job.update(status='interrupted', error={'code': 'market_research_interrupted', 'message': '执行已中断；不会自动重新提交模型。'})
                    self._save(db, job)

    @staticmethod
    def _is_current_attempt(db, job, run_id, expected_owner):
        if job['run_id'] != run_id or job['status'] not in ACTIVE:return False
        row=db.execute('SELECT owner,status,expires FROM agent_runs WHERE id=?',(run_id,)).fetchone()
        return bool(row and row[0]==expected_owner and row[1] in ('running','cancel_requested')
                    and row[2] is not None and row[2]>time.time())

    def _checkpoint(self, task_id, run_id, expected_owner, **changes):
        with self.core.atomic() as db:
            job = self._load(db, task_id)
            if not self._is_current_attempt(db, job, run_id, expected_owner): raise _SupersededAttempt()
            if job['status'] in ('cancelled', 'cancelling'): raise model.transport.Cancelled()
            job.update(changes); self._save(db, job)
            return job

    def _generate(self, job, phase, payload, cancelled, route, expected_owner):
        self._checkpoint(job['task_id'], job['run_id'], expected_owner, _model_pending=phase)
        if job.get('_execution_hosts'):
            try:
                generated = self.service.host_execution.generate(job, phase, payload,
                    model.output_schema(phase,payload.get('source_ids',()),payload.get('product_refs',())),
                    model.instructions(phase,model.output_schema(phase,payload.get('source_ids',()),payload.get('product_refs',()))),cancelled)
            except ValueError as error:
                if str(error) in ('host_parent_superseded','host_attempt_superseded','host_context_changed','host_phase_changed'):
                    raise _SupersededAttempt() from None
                if str(error)=='host_lease_expired':raise ValueError('agent_provider_outcome_unknown') from None
                raise
        else:generated = model.generate(phase, payload, cancelled, route)
        data = generated.get('data')
        import jsonschema
        try: jsonschema.validate(data, model.output_schema(phase, payload.get('source_ids', ()), payload.get('product_refs', ())))
        except jsonschema.ValidationError: raise ValueError('market_research_invalid_model_output') from None
        if len(canonical(data)) > 20000: raise ValueError('market_research_model_output_too_large')
        return data

    def execute(self, run_id, payload, cancelled):
        with self.core.db() as db:
            row = db.execute('SELECT task_id FROM market_research_runs WHERE run_id=?', (run_id,)).fetchone()
            if not row: return None
            job = self._load(db, row[0])
        task_id = job['task_id']
        expected_owner = self.service.agent_runtime.owner
        def checkpoint(**changes):
            return self._checkpoint(task_id,run_id,expected_owner,**changes)
        try:
            route = self.service.models.runtime_route(payload['model_route'])
            job = checkpoint(status='running')
            if job['_context'].get('demo'):
                job = checkpoint(status='awaiting_input', questions=['请切换到真实资料范围后，再发起公开市场研究。'])
                return self._answer(job)
            if not job['_plan']:
                plan = self._generate(job, 'planning', {'question': job['query'], 'market': 'RU'}, cancelled, route, expected_owner)
                if len(plan['query_ru']) > 120 or len(plan['questions']) > 1 or any(len(q) > 400 for q in plan['questions']):
                    raise ValueError('market_research_invalid_plan')
                job = checkpoint(_plan=plan, _model_pending=None, questions=plan['questions'])
                if plan['questions']:
                    job = checkpoint(status='awaiting_input'); return self._answer(job)
                if not plan['query_ru'].strip(): raise ValueError('market_research_search_phrase_required')
            if len(job['sources']) < len(collector.urls(job['_plan']['query_ru'])):
                job = checkpoint(phase='collecting')
                for url in collector.urls(job['_plan']['query_ru']):
                    if cancelled(): raise model.transport.Cancelled()
                    if any(s['url'] == url for s in job['sources']): continue
                    source_id = 'S' + str(len(job['sources']) + 1)
                    try:
                        page = collector.capture(url, self.directory / task_id, cancelled)
                        page = {**page, 'id': source_id}
                        page['capture_sha256'] = digest(canonical(page))
                        source = {'id': source_id, 'url': url, 'title': page['title'], 'captured_at': page['captured_at'],
                                  'sha256': page['sha256'], 'status': 'collected', 'error': None,
                                  'evidence_kind': 'public_page', 'excerpt': page['text'][:1200]}
                        job['_captures'].append(page)
                    except ValueError as error:
                        if cancelled(): raise model.transport.Cancelled()
                        code = str(error) if str(error).startswith('market_research_') else 'market_research_capture_failed'
                        source = {'id': source_id, 'url': url, 'title': '', 'captured_at': stamp(), 'sha256': None,
                                  'status': 'failed', 'error': code, 'evidence_kind': 'public_page', 'excerpt': ''}
                    job = checkpoint(sources=[*job['sources'], source], _captures=job['_captures'])
            products = {}
            for page in job['_captures']:
                if page.get('capture_sha256') != digest(canonical({k: v for k, v in page.items() if k != 'capture_sha256'})):
                    raise ValueError('market_research_evidence_changed')
                for n, item in enumerate(page.get('products', [])):
                    products[page['id'] + ':P' + str(n+1)] = {**item, 'source_id': page['id']}
            if not products: raise ValueError('market_research_no_product_evidence')
            if not job['_analysis']:
                job = checkpoint(phase='analyzing')
                source_ids = [p['id'] for p in job['_captures']]
                evidence = [{'id': p['id'], 'url': p['url'], 'captured_at': p['captured_at'], 'sha256': p['sha256'], 'text': p['text'][:12000]} for p in job['_captures']]
                analysis = self._generate(job, 'analyzing', {'question': job['query'], 'market': 'RU',
                    'sources': evidence, 'products': products, 'source_ids': source_ids, 'product_refs': list(products)}, cancelled, route, expected_owner)
                if not analysis['summary'].strip() or not analysis['limitations']:
                    raise ValueError('market_research_analysis_limits_required')
                if len({c['product_ref'] for c in analysis['candidates']}) != len(analysis['candidates']):
                    raise ValueError('market_research_duplicate_candidate')
                for candidate in analysis['candidates']:
                    if products[candidate['product_ref']]['source_id'] not in candidate['source_ids']:
                        raise ValueError('market_research_candidate_evidence_mismatch')
                job = checkpoint(_analysis=analysis, _model_pending=None)
            if cancelled(): raise model.transport.Cancelled()
            checkpoint(phase='saving')
            self._publish(task_id, run_id, products, expected_owner)
            return self._answer(self.get(task_id))
        except _SupersededAttempt:
            return self._answer(self.get(task_id))
        except model.transport.Cancelled:
            with self.core.atomic() as db:
                current = self._load(db, task_id)
                if self._is_current_attempt(db, current, run_id, expected_owner):
                    current.update(status='interrupted' if self.service.agent_runtime.stop_event.is_set() else 'cancelled',
                                   error={'code': 'market_research_cancelled', 'message': '执行已停止，已确认产物保留。'})
                    self._save(db, current)
            return self._answer(self.get(task_id))
        except Exception as error:
            code = str(error) if isinstance(error, ValueError) and str(error).startswith(('market_research_', 'agent_')) else 'market_research_failed'
            status = 'unknown' if 'outcome_unknown' in code else 'failed'
            with self.core.atomic() as db:
                job = self._load(db, task_id)
                if self._is_current_attempt(db, job, run_id, expected_owner):
                    status = 'cancelled' if job['status'] == 'cancelling' else status
                    if job.get('_model_pending') and code.startswith('market_research_'):
                        attempt=job.get('_host_attempt',{}).get('id')
                        row=db.execute('SELECT status,run_id FROM agent_host_attempts WHERE id=?',(attempt,)).fetchone()
                        if row and row[0]=='completed' and row[1]==run_id:
                            # A settled native response rejected by domain rules
                            # must remain auditable, but must not become a cache
                            # hit forever when the user explicitly retries.
                            rejected=job.setdefault('_rejected_host_attempts',[])
                            if attempt not in rejected:rejected.append(attempt)
                    job.update(status=status, error={'code': code, 'message': '研究未完成；来源和已确认步骤保留，可显式恢复原任务。'})
                    self._save(db, job)
            return self._answer(job)

    def _publish(self, task_id, run_id, products, expected_owner):
        from organization_candidates import save_research_candidate
        with self.core.atomic() as db:
            job = self._load(db, task_id)
            if not self._is_current_attempt(db, job, run_id, expected_owner): raise _SupersededAttempt()
            if job['status'] in ('cancelled', 'cancelling'): raise model.transport.Cancelled()
            thread = self.service.copilot._thread(db, job['thread_id'])
            if thread['context'] != job['_context']: raise ValueError('market_research_context_changed')
            saved = []
            for candidate in job['_analysis']['candidates']:
                item = products[candidate['product_ref']]
                source = next(p for p in job['_captures'] if p['id'] == item['source_id'])
                case = save_research_candidate(self.core, task_id=task_id, product=item)
                record = template('research')['record']
                record.update(market='RU', language='ru', source_url=source['url'], captured_at=source['captured_at'],
                              raw_excerpt=item['text'][:6000], evidence_note='公开目录供给样本；非销量、需求或独立事实核实。原始页SHA256=' + source['sha256'])
                values = {'subject': (item['title'], job['query']), 'findings': (item['text'][:6000], candidate['reason']),
                          'limitations': ('Public catalog offer; sales and demand unknown.', '单次公开目录样本，翻译待校对；销量、需求、成本和利润未知。')}
                for key, (original, zh) in values.items():
                    record['fields'][key].update(original=original, zh=zh, reviewed=False, kind='inference' if key in ('findings', 'limitations') else 'source_statement', source_url=source['url'], locator=candidate['product_ref'])
                artifact = self.service.organization.record(case['id'], 'research', {'record': record, 'sku': None, 'row_key': case['scope']['row_key']}, 'market-research:' + task_id)
                saved.append({'case_id': case['id'], 'name': item['title'], 'source_url': source['url'], 'product_url': item['url'], 'source_ids': candidate['source_ids'],
                              'workspace_url': '/workspace?tab=operations&case_id=' + case['id'], 'artifact_id': artifact['id']})
            job.update(candidates=saved, report={k: job['_analysis'][k] for k in ('summary', 'findings', 'limitations', 'evidence_refs')},
                       phase='finished', status='partial' if any(s['status'] == 'failed' for s in job['sources']) else 'completed', questions=[], error=None)
            self._save(db, job)

    @staticmethod
    def _answer(job):
        status = job['status']
        answer = (job.get('report') or {}).get('summary') or ('需要补充研究方向。' if status == 'awaiting_input' else
                    '研究已停止，证据保留。' if status in ('interrupted', 'cancelled') else '研究未完成，请查看来源与错误后恢复原任务。')
        if job['candidate_count']: answer += '\n已保存 ' + str(job['candidate_count']) + ' 个研究候选；未导入库存。'
        return {'answer': answer, 'questions': job['questions'], 'evidence_refs': (job.get('report') or {}).get('evidence_refs', []),
                'proposals': [], 'observations': [], 'generator': 'configured_model_public_research',
                'independently_verified': False, 'marketplace_writes': False}
