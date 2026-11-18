"""Bounded serial collaboration over original Copilot turns, never a second worker."""
import hashlib
import json
import time
import uuid

from agent_runtime.policy import canonical
from agent_text_fence import fence_collaboration
from copilot import LOCK
from assistant_team_routing import choose_members, normalize_routing, collaboration_plan

ACTIVE = {'queued', 'running', 'cancel_requested', 'cancelling'}


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class TeamDiscussions:
    def __init__(self, teams):
        self.teams = teams
        self.service = teams.service
        self.core = teams.core

    def _load(self, db, ident):
        row = db.execute('SELECT document FROM assistant_team_discussions WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('team_discussion_not_found')
        return json.loads(row[0])

    @staticmethod
    def _store(db, doc):
        doc['updated'] = max(time.time(), doc.get('updated', 0) + .000001)
        db.execute('UPDATE assistant_team_discussions SET document=? WHERE id=?', (canonical(doc), doc['id']))

    def _member(self, db, original):
        member = dict(original)
        base = member.get('continuation_run_id', member['run_id'])
        research = self.service.market_research.for_run(base, db)
        member['original_run_id'] = member['run_id']
        member['run_id'] = research['run_id'] if research else base
        if research:
            member['research_task_id'] = research['task_id']
        run = self.service.agent_runtime._get(member['run_id'], _db=db)
        answer = run.get('result') or {}
        content = answer.get('answer', '')
        member.update(status=research['status'] if research else run['status'], run_status=run['status'],
                      answer=content, questions=answer.get('questions', []), result_sha256=run.get('result_sha256'),
                      answer_sha256=hashlib.sha256(content.encode()).hexdigest() if isinstance(content, str) and content else None)
        return member

    def get(self, discussion_id):
        with self.core.db() as db:
            doc = self._load(db, discussion_id)
            members = [self._member(db, m) for m in doc['members']]
        statuses = [m['status'] for m in members]
        if any(s in ACTIVE for s in statuses):
            status = 'queued' if all(s == 'queued' for s in statuses) else 'running'
        elif 'unknown' in statuses:
            status = 'unknown'
        elif statuses and len(set(statuses)) == 1:
            status = statuses[0]
        else:
            status = 'partial'
        plan = [dict(step) for step in doc.get('plan', [])]
        for i, member in enumerate(members):
            if i < len(plan):
                plan[i].update(status=member['status'], thread_id=member['thread_id'], run_id=member['run_id'])
        state = doc.get('collaboration_state')
        if state == 'cancelled':
            status = 'cancelling' if any(s in ACTIVE for s in statuses) else 'unknown' if 'unknown' in statuses else 'cancelled'
        elif state in ('blocked', 'unknown', 'failed', 'interrupted', 'awaiting_input', 'awaiting_review'):
            status = state
        elif doc.get('mode') == 'collaborate':
            # Keep clients polling until the scheduler persists the next step
            # or pause. Mixed completed/awaiting_input members are not a
            # terminal partial result while this serial plan is still running.
            if state == 'running' and not any(s in ACTIVE for s in statuses):
                status = 'running'
            elif len(members) < len(plan) and status == 'completed':
                status = 'running'
            if state == 'completed':
                status = 'completed'
        public = {k: v for k, v in doc.items() if k not in ('profile_snapshots', 'channel_snapshot', 'model_pins', 'playbook_snapshot')}
        final = members[-1].get('answer', '') if status == 'completed' and members and doc.get('mode') == 'collaborate' else ''
        return {**public, 'members': members, 'plan': plan, 'mode': doc.get('mode', 'all'), 'status': status,
                'completed': statuses.count('completed'), 'total': len(plan) if plan else len(members),
                'updated': doc.get('updated', doc['created']), 'stopped_reason': doc.get('stopped_reason'),
                'final_answer': final,
                'budget': {'max_member_requests': len(plan) if plan else len(members), 'used_member_requests': len(members)}}

    def _enqueue(self, db, doc, step):
        channel = self.teams._get(db, 'channels', doc['channel_id'])
        if canonical(channel['context']) != canonical(doc['channel_snapshot']['context']):
            raise ValueError('team_channel_scope_changed')
        profile = doc['profile_snapshots'][step['profile_id']]
        current = self.teams._get(db, 'profiles', profile['id'])
        if not current['enabled']:
            raise ValueError('team_profile_disabled')
        pin = doc['model_pins'][profile['id']]
        snapshot = self.service.models.snapshot(db, model_id=pin['model_id'])
        if sha(snapshot) != pin['sha256']:
            raise ValueError('team_model_changed')
        key = sha({'discussion': doc['id'], 'step': step['index']})
        opened = self.teams.thread_open(profile['id'], 'discussion:' + key, doc['channel_id'])
        thread = opened['thread']
        self.service.models.select(thread['id'], pin['model_id'], self.service.models.selection(db, thread['id'])['revision'])
        binding = self.teams.binding_for_thread(db, thread['id'])
        binding.update(profile=profile, channel=doc['channel_snapshot'])
        if doc['mode'] == 'collaborate':
            latest = {}
            for old in doc['members']:
                result = self._member(db, old)
                if result['status'] == 'completed' and result.get('answer'):
                    latest[result['profile_id']] = {k: result[k] for k in ('profile_id', 'name', 'thread_id', 'run_id', 'answer_sha256')}
                    latest[result['profile_id']]['answer'] = result['answer']
                    latest[result['profile_id']]['truncated'] = len(result['answer']) > 2000
            # Prior answers are other agents' output: fence the prompt copy only.
            binding['collaboration'] = fence_collaboration({'discussion_id': doc['id'], 'index': step['index'], 'round': step['round'],
                'kind': step['kind'], 'prior_answers': list(latest.values()), 'max_member_requests': len(doc['plan'])})

        if doc.get('playbook_snapshot'):
            binding['playbook'] = doc['playbook_snapshot']
        if doc.get('trigger_firing'):
            binding['trigger_firing'] = doc['trigger_firing']
        db.execute('UPDATE assistant_team_threads SET document=? WHERE thread_id=?', (canonical(binding), thread['id']))
        sent = self.service.copilot.send(thread['id'], doc['question'], thread['context_sha256'], 'team-send:' + key)
        member = {'profile_id': profile['id'], 'name': profile['name'], 'thread_id': thread['id'],
                  'run_id': sent['latest_run']['id'], 'index': step['index'], 'kind': step['kind'], 'round': step['round']}
        doc['members'].append(member)

    def start(self, channel_id, expected_revision, question, idempotency_key, mode=None, max_rounds=None, playbook_key=None,
              firing=None):
        self.service.copilot.key(idempotency_key)
        if firing is not None and (not isinstance(firing, dict) or set(firing) != {'trigger_id', 'kind', 'event_id', 'instruction'}):
            raise ValueError('team_invalid_firing')
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise ValueError('team_invalid_text')
        question = question.strip()
        request_data = {'channel_id': channel_id, 'expected_revision': expected_revision, 'question': question}
        for key, value in [('mode', mode), ('max_rounds', max_rounds), ('playbook_key', playbook_key)]:
            if value is not None:
                request_data[key] = value
        request = canonical(request_data)
        with LOCK, self.core.atomic(reuse=True) as db:
            old = db.execute('SELECT id,request FROM assistant_team_discussions WHERE idem=?', (idempotency_key,)).fetchone()
            if old:
                if old[1] != request:
                    raise ValueError('idempotency_conflict')
                return self.get(old[0])
            channel = self.teams._get(db, 'channels', channel_id)
            if type(expected_revision) is not int or channel['revision'] != expected_revision:
                raise ValueError('team_revision_changed')
            routing = normalize_routing(channel.get('routing'), channel['member_ids'])
            mode = routing['mode'] if mode is None else mode
            rounds = routing['max_rounds'] if max_rounds is None else max_rounds
            if type(rounds) is not int or not 1 <= rounds <= 3:
                raise ValueError('team_invalid_routing')
            profiles = [self.teams._get(db, 'profiles', p) for p in channel['member_ids']]
            decision = choose_members(channel, profiles, question, mode)
            selected = [p for p in profiles if p['id'] in decision['selected_member_ids']]
            pins = {}
            for profile in selected:
                route = self.teams._route(profile)
                pins[profile['id']] = {'model_id': route['selected_model_id'],
                    'sha256': sha(self.service.models.snapshot(db, model_id=route['selected_model_id']))}
            plan = (collaboration_plan(selected, routing['lead_id'], rounds) if mode == 'collaborate' else
                    [dict(index=i, round=1, profile_id=p['id'], name=p['name'], kind='contribution', status='pending')
                     for i, p in enumerate(selected)])
            playbook = self.teams.playbook_for_channel(channel, playbook_key or channel.get('playbook_key'))
            at = time.time()
            doc = {'id': 'discussion_' + uuid.uuid4().hex, 'channel_id': channel_id, 'question': question,
                'mode': mode, 'max_rounds': rounds if mode == 'collaborate' else 1, 'routing_decision': decision,
                'plan': plan, 'members': [], 'created': at, 'updated': at, 'stopped_reason': None,
                'collaboration_state': 'running' if mode == 'collaborate' else None,
                'profile_snapshots': {p['id']: p for p in selected}, 'model_pins': pins,
                'channel_snapshot': channel, 'playbook_snapshot': playbook}
            if firing:
                doc['trigger_firing'] = firing
            for step in plan[:1] if mode == 'collaborate' else plan:
                self._enqueue(db, doc, step)
            db.execute('INSERT INTO assistant_team_discussions VALUES(?,?,?,?,?)', (doc['id'], idempotency_key, request, canonical(doc), at))
            return self.get(doc['id'])

    def tick(self, at=None):
        advanced = 0
        with self.core.db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM assistant_team_discussions WHERE json_extract(document,'$.collaboration_state')='running' ORDER BY created LIMIT 24")]
        for ident in ids:
            with LOCK, self.core.atomic(reuse=True) as db:
                doc = self._load(db, ident)
                if doc.get('collaboration_state') != 'running':
                    continue
                current = self._member(db, doc['members'][-1])
                status = current['status']
                if status in ACTIVE:
                    continue
                if status != 'completed':
                    doc.update(collaboration_state=status if status in ('awaiting_input', 'awaiting_review', 'unknown', 'failed', 'interrupted', 'cancelled') else 'blocked',
                               stopped_reason='team_collaboration_' + status)
                elif len(doc['members']) == len(doc['plan']):
                    doc['collaboration_state'] = 'completed'
                else:
                    # A transient queue limit leaves the exact next step pending.
                    # Any source revocation/unknown stops; no model is retried.
                    db.execute('SAVEPOINT team_next_step')
                    try:
                        self._enqueue(db, doc, doc['plan'][len(doc['members'])])
                        db.execute('RELEASE team_next_step'); advanced += 1
                    except ValueError as error:
                        db.execute('ROLLBACK TO team_next_step'); db.execute('RELEASE team_next_step')
                        if str(error) == 'agent_queue_full':
                            continue
                        doc.update(collaboration_state='blocked', stopped_reason=str(error) if str(error).startswith('team_') else 'team_collaboration_dispatch_failed')
                self._store(db, doc)
        return {'advanced': advanced}

    def cancel(self, discussion_id):
        with LOCK, self.core.atomic(reuse=True) as db:
            doc = self._load(db, discussion_id)
            if doc.get('mode') == 'collaborate' and doc.get('collaboration_state') != 'completed':
                doc.update(collaboration_state='cancelled', stopped_reason='team_collaboration_cancelled')
                self._store(db, doc)
            members = list(doc['members'])
        # Research cancellation owns its transaction and parent fencing. Mark
        # the serial plan stopped first, then let that original owner cancel.
        with LOCK:
            for old in members:
                with self.core.db() as db:
                    member = self._member(db, old)
                if member['status'] in ACTIVE:
                    if member.get('research_task_id'):
                        self.service.market_research.cancel(member['research_task_id'])
                    else:
                        self.service.copilot.cancel(member['thread_id'], member['run_id'])
        return self.get(discussion_id)

    def advance(self, discussion_id, expected_updated=None):
        with LOCK, self.core.atomic(reuse=True) as db:
            doc = self._load(db, discussion_id)
            if expected_updated is not None and expected_updated != doc.get('updated', doc['created']):
                raise ValueError('team_discussion_changed')
            if doc.get('collaboration_state') not in ('awaiting_input', 'awaiting_review'):
                raise ValueError('team_discussion_requires_review')
            old = doc['members'][-1]
            thread = self.service.copilot.get(old['thread_id'])
            latest = thread.get('latest_run') or {}
            if latest.get('status') != 'completed' or not (latest.get('result') or {}).get('answer'):
                raise ValueError('team_discussion_reply_required')
            old['continuation_run_id'] = latest['id']
            doc.update(collaboration_state='running', stopped_reason=None)
            self._store(db, doc)
        return self.get(discussion_id)
