"""Version-bound projection of unresolved model and research work.

Reads never change anything. The one write, close, records that the operator has
checked a failed, unknown or interrupted outcome; it never resubmits, and the
original request and its status stay exactly as they were.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3

import time

from agent_runtime.policy import canonical

KINDS = ('unknown', 'failed', 'review', 'input')
ITEM_ID = re.compile(r'attention_[a-f0-9]{64}')
CURSOR = re.compile(r'[0-3]:attention_[a-f0-9]{64}')


def definitions(schema, string):
    return [
        ('commerce_attention_list', '分页读取尚需介入的模型事项及研究异常；不调用模型或执行任务',
         schema({'demo': {'type': 'boolean'}, 'kind': {'type': 'string', 'enum': ['all', *KINDS]},
                 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}, 'cursor': string, 'include_followups': {'type':'boolean'}})),
        ('commerce_attention_get', '重新核对一条事项的当前版本与原工作入口；不批准或恢复执行',
         schema({'item_id': string}, ['item_id'])),
        ('commerce_attention_close', '核对后关闭一条失败、结果未知或中断的事项；绑定当前版本，不重发、不改变原请求',
         schema({'item_id': string, 'note': {'type': 'string', 'maxLength': 500}}, ['item_id'])),
    ]


def object_json(value):
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError('attention_invalid_source')
    return result


def text(value, maximum=400):
    return value[:maximum] if isinstance(value, str) else ''


def item(source, source_id, part, version, kind, title, detail, action, **references):
    fingerprint = hashlib.sha256(canonical([source, source_id, part, version]).encode()).hexdigest()
    return {'id': 'attention_' + fingerprint, 'source': source, 'source_id': source_id,
            'kind': kind, 'title': text(title, 120), 'detail': text(detail), 'action': action,
            **references}


class Attention:
    def __init__(self, service):
        self.service = service
        self.core = service.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS attention_closed (item_id TEXT PRIMARY KEY, source TEXT NOT NULL, '
                       'source_id TEXT NOT NULL, kind TEXT NOT NULL, note TEXT NOT NULL, closed REAL NOT NULL)')

    def invoke(self, name, args):
        return {'commerce_attention_list': self.listing, 'commerce_attention_get': self.get,
                'commerce_attention_close': self.close}[name](**args)

    def _collect(self, demo=None, include_followups=False):
        result, errors = [], set()
        with self.core.db() as db:
            if not db.in_transaction:
                db.execute('BEGIN')  # All references below describe the same read snapshot.
            research_runs = set()
            try:
                research_runs = {row[0] for row in db.execute('SELECT run_id FROM market_research_runs')}
                for task_id, raw in db.execute('SELECT task_id,document FROM market_research_jobs'):
                    try:
                        job = object_json(raw)
                        research_runs.add(job['run_id'])
                        context = job.get('_context', {})
                        if not isinstance(context, dict):
                            raise ValueError('attention_invalid_source')
                        if demo is not None and (context.get('demo') is True) != demo:
                            continue
                        state = job['status']
                        kind = 'input' if state == 'awaiting_input' else 'unknown' if state == 'unknown' else 'failed'
                        if state not in ('awaiting_input', 'unknown', 'failed', 'interrupted', 'partial'):
                            continue
                        bound = db.execute('SELECT revision,context_sha FROM copilot_threads WHERE id=?', (job['thread_id'],)).fetchone()
                        if not bound or bound[1] != hashlib.sha256(canonical(context).encode()).hexdigest():
                            continue
                        origin = db.execute('''SELECT t.revision,t.context_sha,t.thread_id FROM copilot_turns t
                            JOIN market_research_runs m ON m.run_id=t.run_id WHERE m.task_id=?
                            ORDER BY t.rowid DESC LIMIT 1''', (task_id,)).fetchone()
                        if not origin:
                            raise ValueError('attention_missing_research_binding')
                        if (origin[0], origin[1], origin[2]) != (bound[0], bound[1], job['thread_id']):
                            continue
                        questions = job.get('questions') or []
                        detail = '；'.join(text(q) for q in questions) if kind == 'input' else {
                            'unknown': '执行结果尚未确认，请先核对原研究，再明确恢复。',
                            'partial': '已有部分研究结果，请核对缺失来源及限制。',
                        }.get(state, '研究未完成，已确认的来源与步骤保留。')
                        result.append(item('research', task_id, 'current', [job['revision'], bound[0], bound[1]],
                            kind, job.get('query') or '公开市场研究', detail, {'type': 'research', 'id': task_id},
                            task_id=task_id, run_id=job['run_id'], thread_id=job['thread_id'],
                            status=state, source_revision=job['revision'], demo=context.get('demo') is True))
                    except (ValueError, KeyError, TypeError):
                        errors.add('research')
            except sqlite3.Error:
                # Without the ownership map an old research run must not be shown as unrelated model work.
                return [], ['research', 'agent']

            try:
                answered = set()
                for raw, state in db.execute('SELECT payload,status FROM agent_runs'):
                    try:
                        payload = object_json(raw)
                        if state != 'cancelled' and payload.get('parent_id'):
                            answered.add(payload['parent_id'])
                    except (ValueError, TypeError):
                        errors.add('agent')
                rows = db.execute('''SELECT a.id,a.payload,a.status,a.result,t.thread_id,t.revision,t.context_sha,
                    c.revision,c.context_sha,c.title FROM agent_runs a
                    LEFT JOIN copilot_turns t ON t.run_id=a.id LEFT JOIN copilot_threads c ON c.id=t.thread_id
                    WHERE a.status IN ('awaiting_input','awaiting_review','completed','failed','unknown','interrupted')''')
                for row in rows:
                    try:
                        if row[0] in research_runs:
                            continue
                        result.extend(self._agent_items(db, row, answered, demo))
                    except (ValueError, KeyError, TypeError):
                        errors.add('agent')
            except sqlite3.Error:
                errors.add('agent')
            if include_followups:
                try:result.extend(self.service.followups.attention_items(db, demo))
                except (sqlite3.Error, ValueError, KeyError, TypeError):errors.add('followup')
        # An item id includes its version, so a closed item reappears if the outcome changes.
        with self.core.db() as db:
            closed = {row[0] for row in db.execute('SELECT item_id FROM attention_closed')}
        return sorted((row for row in result if row['id'] not in closed), key=self._key), sorted(errors)

    @staticmethod
    def _key(value):
        return KINDS.index(value['kind']), value['id']

    def _agent_items(self, db, row, answered, demo):
        ident, raw, state, saved, thread_id, revision, context_sha, current_revision, current_sha, title = row
        payload = object_json(raw)
        if thread_id and (revision != current_revision or context_sha != current_sha):
            return []
        parameters = payload.get('parameters', {})
        if not isinstance(parameters, dict):
            raise ValueError('attention_invalid_source')
        context = parameters.get('context', parameters)
        if not isinstance(context, dict):
            raise ValueError('attention_invalid_source')
        example = context.get('demo') is True
        case_id = parameters.get('case_id')
        if 'demo' not in context and payload.get('topic') == 'business_exposure':
            assessment = db.execute('SELECT case_id FROM exposure_assessments WHERE id=?', (parameters.get('assessment_id'),)).fetchone()
            if not assessment:
                raise ValueError('attention_missing_assessment')
            case_id = assessment[0]
        if 'demo' not in context and case_id:
            case = db.execute('SELECT scope FROM org_cases WHERE id=?', (case_id,)).fetchone()
            if not case:
                raise ValueError('attention_missing_case')
            example = object_json(case[0]).get('synthetic') is True
        if demo is not None and example != demo:
            return []
        value = object_json(saved) if saved else {}
        version = [value, state, revision, context_sha]
        action = {'type': 'thread', 'id': thread_id} if thread_id else {'type': 'agent', 'id': ident}
        refs = {'run_id': ident, 'thread_id': thread_id, 'status': state, 'demo': example}
        title = title or text(payload.get('question')) or '模型事项'
        if state in ('failed', 'unknown', 'interrupted'):
            detail = '执行结果尚未确认，不会自动重发。' if state == 'unknown' else '本轮未完成，请返回原工作核对原因和已确认结果。'
            return [item('agent', ident, 'outcome', version, 'unknown' if state == 'unknown' else 'failed',
                         title, detail, action, **refs)]
        result = []
        applied = {r[0] for r in db.execute('SELECT proposal_id FROM agent_actions WHERE run_id=?', (ident,))}
        for proposal in value.get('proposals', []):
            proposal_id = proposal['id']
            if proposal_id in applied:
                continue
            # A crash can commit the idempotent task before recording agent_actions. Reads never repair or replay it.
            task = db.execute('SELECT id FROM tasks WHERE idempotency_key=?', ('agent:' + ident + ':' + proposal_id,)).fetchone()
            if task:
                result.append(item('agent', ident, 'proposal:' + proposal_id, [version, task[0]], 'unknown',
                    '建议提交记录待核对', '已有原任务，关联回执尚不完整；请返回原工作核对，勿另建任务。',
                    action, **{**refs, 'status': 'submission_unknown'}, proposal_id=proposal_id, task_id=task[0]))
            else:
                result.append(item('agent', ident, 'proposal:' + proposal_id, version, 'review', title,
                    proposal.get('reason'), action, **refs, proposal_id=proposal_id))
        if ident not in answered:
            for index, question in enumerate(value.get('questions', [])):
                result.append(item('agent', ident, 'question:' + str(index), version, 'input', title,
                                   question, action, **refs))
        return result

    def listing(self, demo=False, kind='all', limit=30, cursor=None, include_followups=False):
        if type(demo) is not bool or kind not in ('all', *KINDS) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('invalid_attention_query')
        if cursor is not None and (not isinstance(cursor, str) or not CURSOR.fullmatch(cursor)):
            raise ValueError('invalid_attention_cursor')
        if type(include_followups) is not bool:raise ValueError('invalid_attention_query')
        rows, errors = self._collect(demo, include_followups)
        if kind != 'all':
            rows = [row for row in rows if row['kind'] == kind]
        if cursor:
            rank, ident = cursor.split(':', 1)
            rows = [row for row in rows if self._key(row) > (int(rank), ident)]
        page, more = rows[:limit], len(rows) > limit
        return {'schema': 'commerce-attention-v1', 'items': page, 'has_more': more,
                'next_cursor': str(self._key(page[-1])[0]) + ':' + page[-1]['id'] if more else None,
                'complete': not errors, 'source_errors': errors,
                'read_at': datetime.now(timezone.utc).isoformat()}

    def get(self, item_id):
        if not isinstance(item_id, str) or not ITEM_ID.fullmatch(item_id):
            raise ValueError('invalid_attention_item')
        rows, errors = self._collect(include_followups=True)
        current = next((row for row in rows if row['id'] == item_id), None)
        if current is None:
            raise ValueError('attention_source_unavailable' if errors else 'attention_item_changed')
        return {'schema': 'commerce-attention-item-v1', 'item': current,
                'complete': not errors, 'source_errors': errors}

    def close(self, item_id, note=''):
        """Record that a failed/unknown/interrupted outcome was checked. Nothing is resubmitted."""
        if not isinstance(item_id, str) or not ITEM_ID.fullmatch(item_id):
            raise ValueError('invalid_attention_item')
        if not isinstance(note, str) or len(note) > 500 or any(ord(c) < 32 and c not in '\n\t' for c in note):
            raise ValueError('invalid_attention_note')
        with self.core.db() as db:
            prior = db.execute('SELECT source,source_id,kind,closed FROM attention_closed WHERE item_id=?', (item_id,)).fetchone()
        if not prior:
            rows, errors = self._collect(include_followups=True)
            current = next((row for row in rows if row['id'] == item_id), None)
            if current is None:
                raise ValueError('attention_source_unavailable' if errors else 'attention_item_changed')
            # Questions and proposals need an answer or a decision in their own flow, and a
            # submission whose task already exists must be reconciled there.
            if current['kind'] not in ('unknown', 'failed') or current.get('status') == 'submission_unknown' or current['source'] == 'followup':
                raise ValueError('attention_not_closable')
            prior = (current['source'], current['source_id'], current['kind'], time.time())
            with self.core.db() as db:
                db.execute('INSERT OR IGNORE INTO attention_closed VALUES (?,?,?,?,?,?)', (item_id, *prior[:3], note.strip(), prior[3]))
        return {'schema': 'commerce-attention-close-v1', 'item_id': item_id, 'status': 'closed', 'source': prior[0],
                'source_id': prior[1], 'kind': prior[2], 'resubmitted': False, 'original_changed': False}
